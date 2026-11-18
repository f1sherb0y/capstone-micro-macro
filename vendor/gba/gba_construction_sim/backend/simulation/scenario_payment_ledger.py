"""Opt-in local scenario payments; never a bank connection or historic cash proof.

The archived aggregate simulator has no cash ledger. This isolated supplemental
phase starts from explicitly declared assumptions and owns its own transactional
debit, beneficiary credit and receipts. Existing simulations do not import it.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import sqlite3


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def key(ref):
    return ref['kind'], ref['id'], ref['version']


class ScenarioPaymentLedger:
    """Durable single-currency two-party ledger with immutable command identity."""
    VERSION = 'scenario-payment-ledger.v1'

    def __init__(self, path, *, initial):
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=DELETE')
        with self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS initial (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, payload TEXT NOT NULL, result TEXT NOT NULL)')
            prior = self.db.execute('SELECT value FROM initial WHERE id=1').fetchone()
            if prior is None:
                if initial.get('source_declaration') != 'explicit_scenario_assumptions_not_historic_cash':
                    raise ValueError('Explicit initial financial assumption declaration required')
                for balance in initial['accounts']:
                    cash = Decimal(balance['cash'])
                    if not cash.is_finite() or cash < 0:
                        raise ValueError('Initial cash must be finite and nonnegative')
                if len({a['organization_id'] for a in initial['accounts']}) != len(initial['accounts']):
                    raise ValueError('Each scenario party must have one distinct account')
                obligations = initial['obligations']
                if len({key(o['ref']) for o in obligations}) != len(obligations):
                    raise ValueError('Duplicate initial payment obligation')
                for obligation in obligations:
                    amount = Decimal(obligation['amount'])
                    if not amount.is_finite() or amount <= 0:
                        raise ValueError('Initial obligation must be positive and finite')
                self.db.execute('INSERT INTO initial VALUES(1,?)', (canonical(initial),))
            elif json.loads(prior[0]) != initial:
                raise ValueError('Cannot change the financial phase initial conditions')
        self.initial = deepcopy(initial)

    def close(self):
        self.db.close()

    def history(self):
        return [json.loads(row[0]) for row in self.db.execute('SELECT result FROM commands ORDER BY rowid')]

    def balances(self):
        values = {a['organization_id']: Decimal(a['cash']) for a in self.initial['accounts']}
        for command in self.history():
            if command['status'] == 'succeeded':
                for transfer in command['transfers']:
                    values[transfer['payer_id']] -= Decimal(transfer['amount'])
                    values[transfer['beneficiary_id']] += Decimal(transfer['amount'])
        return {party: str(value) for party, value in values.items()}

    def query(self, command_id):
        row = self.db.execute('SELECT result FROM commands WHERE id=?', (command_id,)).fetchone()
        return None if row is None else json.loads(row[0])

    def submit(self, command):
        """Commit all lines atomically, or persist failure without any cash effects."""
        command = deepcopy(command)
        command_id = command['command_id']
        self.db.execute('BEGIN IMMEDIATE')
        try:
            previous = self.db.execute('SELECT payload,result FROM commands WHERE id=?', (command_id,)).fetchone()
            if previous:
                if previous[0] != canonical(command):
                    raise ValueError('Payment command idempotency conflict')
                self.db.commit()
                return json.loads(previous[1])
            initial = self.initial
            if (command['run_id'] != initial['run_id'] or command['project_id'] != initial['project_id']
                    or command['phase_tick'] < initial['start_tick'] or command['plan']['choice'] != 'pay'):
                raise ValueError('Command changes authorized financial phase')
            payer = command['organization_id']
            payer_account = next(a for a in initial['accounts'] if a['organization_id'] == payer)
            if key(command['plan']['account_ref'])[:2] != key(payer_account['ref'])[:2]:
                raise ValueError('Command changes payer account')
            before = self.balances()
            paid = {}
            for previous in self.history():
                if previous['status'] == 'succeeded':
                    for transfer in previous['transfers']:
                        k = tuple(transfer['obligation_identity'])
                        paid[k] = paid.get(k, Decimal(0)) + Decimal(transfer['amount'])
            transfers, seen = [], set()
            for index, line in enumerate(command['plan']['lines']):
                identity = key(line['obligation_ref'])[:2]
                obligation = next(o for o in initial['obligations'] if key(o['ref'])[:2] == identity)
                value = Decimal(line['amount']['value'])
                parts = line['component_amounts']
                if (identity in seen or not value.is_finite() or value <= 0
                        or payer != obligation['debtor_id'] or line['payee_id'] != obligation['payee_id']
                        or line['amount']['currency'] != initial['currency']
                        or len(parts) != 1 or key(parts[0]['component_ref'])[:2] != key(obligation['component_ref'])[:2]
                        or line['component_refs'] != [parts[0]['component_ref']]
                        or parts[0]['amount'] != line['amount']
                        or value > Decimal(obligation['amount']) - paid.get(identity, Decimal(0))):
                    raise ValueError('Payment changes original positive unpaid obligation/allocation')
                seen.add(identity)
                beneficiary = next(a for a in initial['accounts'] if a['organization_id'] == line['payee_id'])
                transfers.append({'line_index': index, 'payer_id': payer, 'beneficiary_id': line['payee_id'],
                    'beneficiary_account_ref': beneficiary['ref'], 'obligation_identity': list(identity),
                    'amount': str(value), 'currency': initial['currency'],
                    'execution_id': command_id + ':' + str(index), 'receipt_id': command_id + ':' + str(index) + ':receipt'})
            if not transfers:
                raise ValueError('Cannot execute an empty payment command')
            amount = sum((Decimal(t['amount']) for t in transfers), Decimal(0))
            status = 'succeeded' if Decimal(before[payer]) >= amount else 'failed'
            after = {p: Decimal(v) for p, v in before.items()}
            if status == 'succeeded':
                for transfer in transfers:
                    after[payer] -= Decimal(transfer['amount'])
                    after[transfer['beneficiary_id']] += Decimal(transfer['amount'])
            result = {'schema_version': self.VERSION, 'command_id': command_id, 'command_sha256': digest(command),
                'source_task_sha256': command['source_task_sha256'], 'phase_tick': command['phase_tick'],
                'status': status, 'reason': None if status == 'succeeded' else 'insufficient_scenario_cash',
                'transfers': transfers, 'before': before, 'after': {p: str(v) for p, v in after.items()},
                'initial_sha256': digest(initial), 'execution_kind': 'local_scenario_no_external_bank'}
            self.db.execute('INSERT INTO commands VALUES(?,?,?)', (command_id, canonical(command), canonical(result)))
            self.db.commit()
            return result
        except BaseException:
            self.db.rollback()
            raise
