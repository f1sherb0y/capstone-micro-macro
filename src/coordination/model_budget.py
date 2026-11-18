"""Run-local durable call reservations; unknown attempted model calls remain charged."""
from src.json_input import parse_json_object
from src.coordination.tasks import TaskConflict, TaskStore, canonical, task_digest, _text


class ModelCallBudget:
    """Share a call-count limit across strategies/processes using the original journal.

    This bounds adapter call attempts, not money or provider internal retries.
    Reserve a whole discussion first, mark each attempt before calling, then
    release only unstarted slots. A crash cannot reset or replay a reservation.
    """
    SCHEMA = 'model-call-budget.v1'

    def __init__(self, *, store, budget_id, max_calls):
        if not isinstance(store, TaskStore) or type(max_calls) is not int or max_calls <= 0:
            raise ValueError('Model call budget requires the original journal and a positive explicit limit')
        _text(budget_id)
        self.store, self.budget_id, self.max_calls = store, budget_id, max_calls
        self.configuration = {'schema_version': self.SCHEMA, 'run_id': store.run_id,
                              'budget_id': budget_id, 'max_calls': max_calls}
        self.configuration_sha256 = task_digest(self.configuration)
        self.key = task_digest([store.run_id, budget_id])
        with store._transaction():
            store._db.execute('CREATE TABLE IF NOT EXISTS model_call_budgets (budget_key TEXT PRIMARY KEY, record TEXT NOT NULL)')
            store._db.execute('CREATE TABLE IF NOT EXISTS model_call_reservations (reservation_key TEXT PRIMARY KEY, budget_key TEXT NOT NULL, record TEXT NOT NULL)')
            prior = store._db.execute('SELECT record FROM model_call_budgets WHERE budget_key=?', (self.key,)).fetchone()
            if prior is None:
                store._db.execute('INSERT INTO model_call_budgets VALUES (?,?)',
                    (self.key, canonical(self._seal({**self.configuration, 'charged_calls': 0}))))
            else:
                self._budget()

    @staticmethod
    def _seal(record):
        return {**record, 'record_sha256': task_digest(record)}

    def _decode(self, raw):
        try:
            record = parse_json_object(raw)
        except (TypeError, ValueError) as exc:
            raise TaskConflict('Stored model budget/reservation has ambiguous or invalid JSON') from exc
        if task_digest({k: v for k, v in record.items() if k != 'record_sha256'}) != record.get('record_sha256'):
            raise TaskConflict('Stored model budget/reservation changed its original digest')
        return record

    def _budget(self):
        if (task_digest(self.configuration) != self.configuration_sha256
                or self.configuration.get('max_calls') != self.max_calls
                or self.configuration.get('run_id') != self.store.run_id
                or self.configuration.get('budget_id') != self.budget_id):
            raise TaskConflict('Original model budget configuration changed; no implicit limit reset')
        row = self.store._db.execute('SELECT record FROM model_call_budgets WHERE budget_key=?', (self.key,)).fetchone()
        if row is None:
            raise TaskConflict('Original model call budget is missing')
        record = self._decode(row[0])
        if (set(record) != {*self.configuration, 'charged_calls', 'record_sha256'}
                or task_digest({key: record[key] for key in self.configuration}) != self.configuration_sha256
                or type(record['charged_calls']) is not int or not 0 <= record['charged_calls'] <= self.max_calls):
            raise TaskConflict('Model call budget changes its original run, limit or counters')
        return record

    def _reservation(self, reservation_id):
        _text(reservation_id)
        key = task_digest([self.key, reservation_id])
        row = self.store._db.execute('SELECT budget_key, record FROM model_call_reservations WHERE reservation_key=?', (key,)).fetchone()
        if row is None:
            return key, None
        record = self._decode(row[1])
        if (row[0] != self.key or set(record) != {'budget_sha256', 'reservation_id', 'reserved', 'attempted', 'closed', 'record_sha256'}
                or record['budget_sha256'] != self.configuration_sha256 or record['reservation_id'] != reservation_id
                or type(record['reserved']) is not int or not 0 < record['reserved'] <= self.max_calls
                or type(record['attempted']) is not int or not 0 <= record['attempted'] <= record['reserved']
                or type(record['closed']) is not bool):
            raise TaskConflict('Original model call reservation changed')
        return key, record

    def _write_budget(self, record, charged_calls):
        raw = {k: v for k, v in record.items() if k != 'record_sha256'}
        raw['charged_calls'] = charged_calls
        self.store._db.execute('UPDATE model_call_budgets SET record=? WHERE budget_key=?',
            (canonical(self._seal(raw)), self.key))

    def reserve(self, reservation_id, calls):
        if type(calls) is not int or calls <= 0:
            raise ValueError('A positive explicit model call reservation is required')
        with self.store._transaction():
            budget = self._budget()
            key, existing = self._reservation(reservation_id)
            if existing is not None:
                raise TaskConflict('Original model reservation already exists; no automatic replay')
            if budget['charged_calls'] + calls > self.max_calls:
                return False
            record = self._seal({'budget_sha256': self.configuration_sha256, 'reservation_id': reservation_id,
                                'reserved': calls, 'attempted': 0, 'closed': False})
            self.store._db.execute('INSERT INTO model_call_reservations VALUES (?,?,?)', (key, self.key, canonical(record)))
            self._write_budget(budget, budget['charged_calls'] + calls)
            return True

    def begin_attempt(self, reservation_id):
        with self.store._transaction():
            self._budget()
            key, record = self._reservation(reservation_id)
            if record is None or record['closed'] or record['attempted'] >= record['reserved']:
                raise TaskConflict('Model call has no open original reserved slot')
            raw = {k: v for k, v in record.items() if k != 'record_sha256'}
            raw['attempted'] += 1
            self.store._db.execute('UPDATE model_call_reservations SET record=? WHERE reservation_key=?',
                (canonical(self._seal(raw)), key))

    def finish(self, reservation_id):
        with self.store._transaction():
            budget = self._budget()
            key, record = self._reservation(reservation_id)
            if record is None:
                raise TaskConflict('Original model reservation is missing')
            if record['closed']:
                return
            charged = budget['charged_calls'] - (record['reserved'] - record['attempted'])
            if charged < 0:
                raise TaskConflict('Model reservation counters disagree with the original budget')
            raw = {k: v for k, v in record.items() if k != 'record_sha256'}
            raw['closed'] = True
            self.store._db.execute('UPDATE model_call_reservations SET record=? WHERE reservation_key=?',
                (canonical(self._seal(raw)), key))
            self._write_budget(budget, charged)

    def usage(self):
        with self.store._transaction():
            budget = self._budget()
            return {'run_id': self.store.run_id, 'budget_id': self.budget_id, 'max_calls': self.max_calls,
                    'charged_or_reserved_calls': budget['charged_calls'], 'remaining_calls': self.max_calls - budget['charged_calls']}
