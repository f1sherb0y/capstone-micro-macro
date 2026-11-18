"""Expose the assembled journal to selected V7 waits without rebuilding it."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from integration.task_continuation import observation_signal_matches
from src.coordination.continuations import ResumeSignal
from src.coordination.tasks import TaskConflict, TaskIdentity


@dataclass(frozen=True)
class ExecutionWaitRecoveryBridge:
    dispatch: object
    dispatcher: object
    read_guard: object
    check_binding: object
    action_id: str
    role: str
    _original: tuple = field(init=False, repr=False)
    _selection: tuple = field(init=False, repr=False)

    def __post_init__(self):
        allowed = {'BANK-A06': 'Bank', 'BANK-A07': 'Bank', 'BANK-A08': 'Bank', 'BANK-A09': 'Bank', 'BANK-A10': 'Bank', 'BANK-A11': 'Bank', 'BANK-A12': 'Bank',
            'OWN-A01': 'Owner', 'OWN-A02': 'Owner', 'OWN-A03': 'Owner', 'OWN-A04': 'Owner', 'OWN-A05': 'Owner', 'OWN-A08': 'Owner',
            'OWN-A12': 'Owner', 'OWN-A13': 'Owner', 'OWN-A14': 'Owner', 'OWN-A15': 'Owner',
            'ARCHITECT-A02': 'Architect', 'ARCHITECT-A04': 'Architect', 'ARCHITECT-A05': 'Architect', 'ARCHITECT-A07': 'Architect', 'ARCHITECT-A10': 'Architect', 'ARCHITECT-A11': 'Architect', 'ARCHITECT-A12': 'Architect', 'ARCHITECT-A13': 'Architect', 'ENGINEER-A02': 'Engineer', 'ENGINEER-A04': 'Engineer', 'ENGINEER-A05': 'Engineer', 'ENGINEER-A07': 'Engineer', 'ENGINEER-A08': 'Engineer', 'ENGINEER-A09': 'Engineer', 'ENGINEER-A10': 'Engineer', 'ENGINEER-A11': 'Engineer', 'ENGINEER-A12': 'Engineer', 'ENGINEER-A13': 'Engineer',
            'CONTRACTOR-A03': 'Contractor', 'CONTRACTOR-A04': 'Contractor', 'CONTRACTOR-A05': 'Contractor', 'CONTRACTOR-A06': 'Contractor', 'CONTRACTOR-A07': 'Contractor', 'CONTRACTOR-A09': 'Contractor', 'CONTRACTOR-A10': 'Contractor', 'CONTRACTOR-A11': 'Contractor', 'CONTRACTOR-A12': 'Contractor',
            'SUPPLIER-A01': 'Supplier', 'SUPPLIER-A05': 'Supplier', 'SUPPLIER-A06': 'Supplier', 'SUPPLIER-A07': 'Supplier', 'SUPPLIER-A08': 'Supplier', 'SUPPLIER-A09': 'Supplier', 'SUPPLIER-A10': 'Supplier', 'SUPPLIER-A11': 'Supplier', 'SUPPLIER-A12': 'Supplier',
            'GOV-A03': 'Government', 'GOV-A04': 'Government', 'GOV-A05': 'Government', 'GOV-A06': 'Government', 'GOV-A07': 'Government', 'GOV-A08': 'Government', 'GOV-A09': 'Government', 'GOV-A10': 'Government', 'GOV-A11': 'Government', 'GOV-A12': 'Government', 'QS-A02': 'QS', 'QS-A03': 'QS', 'QS-A04': 'QS', 'QS-A05': 'QS', 'QS-A06': 'QS', 'QS-A07': 'QS', 'QS-A08': 'QS', 'QS-A09': 'QS', 'QS-A10': 'QS', 'QS-A11': 'QS', 'QS-A12': 'QS', 'QS-A13': 'QS'}
        if allowed.get(self.action_id) != self.role:
            raise ValueError('Execution V7 bridge requires its original supported action/role pair')
        object.__setattr__(self, '_selection', (self.action_id, self.role))
        object.__setattr__(self, '_original', self._components())

    def _components(self):
        current = self.dispatcher
        return (self.dispatch, current, self.read_guard, self.check_binding, current.inbox,
            current.journal, current.journal.store, current.journal.registry,
            current.prepare, current.revalidate, current.project_signal)

    def _check(self):
        if ((self.action_id, self.role) != self._selection
                or any(actual is not original for actual, original in zip(self._components(), self._original))
                or self.dispatcher.action_ids != frozenset({self.action_id})):
            raise TaskConflict('Execution V7 bridge changed original journal, recipient or callbacks')
        self.check_binding()

    def __call__(self, *, run_id, organization_id):
        self._check()
        result = self.dispatch(run_id=run_id, organization_id=organization_id)
        self._check()
        return result

    def wait_recovery_sources(self, *, identity, journal_path, check_application, close):
        from integration.lifecycle_v7_wait_recovery import WaitRecoverySources

        self._check()
        selected = TaskIdentity(**identity.as_dict())
        journal, store = self.dispatcher.journal, self.dispatcher.journal.store
        path = Path(journal_path).resolve()
        if (selected.action_id != self.action_id or selected.role != self.role or selected.purpose != 'action'
                or selected.run_id != store.run_id or selected.organization_id not in store.organization_ids
                or store.path is None or Path(store.path).resolve() != path or not path.is_file()
                or not callable(check_application) or not callable(close)):
            raise TaskConflict('Execution V7 bridge requires its original persistent journal and selected role task')

        def check():
            self._check()
            check_application()
            if store.path is None or Path(store.path).resolve() != path or not path.is_file():
                raise TaskConflict('Execution V7 original persistent journal changed')

        def check_selected(source, signal):
            check()
            if (source['identity'] != selected.as_dict() or signal.run_id != selected.run_id
                    or signal.organization_id != selected.organization_id):
                raise TaskConflict('Execution V7 callback changed selected original wait or recipient')

        @contextmanager
        def guard(current_identity, current_signal):
            check()
            signal = ResumeSignal.model_validate(current_signal).model_copy(deep=True)
            if (current_identity != selected or signal.run_id != selected.run_id
                    or signal.organization_id != selected.organization_id):
                raise TaskConflict('Execution V7 source guard changed selected original wait or recipient')
            with self.read_guard(run_id=selected.run_id, organization_id=selected.organization_id):
                check()
                if store.get(selected)['identity'] != selected.as_dict():
                    raise TaskConflict('Execution V7 selected original task changed')
                rows = [row for row in self.dispatcher.inbox.for_organization(
                    run_id=selected.run_id, organization_id=selected.organization_id)
                    if row['event_id'] == signal.event_id]
                if len(rows) != 1:
                    raise TaskConflict('Execution V7 signal lacks its original persisted recipient feedback')
                projected = self.dispatcher.project_signal(deepcopy(rows[0]))
                row = rows[0]
                if not observation_signal_matches(row, projected, expected=signal):
                    raise TaskConflict('Execution V7 signal changes the actual persisted feedback projection')
                check()
                try:
                    yield
                finally:
                    check()

        def prepare(source, signal):
            check_selected(source, signal)
            result = self.dispatcher.prepare(deepcopy(source), signal.model_copy(deep=True))
            check_selected(source, signal)
            return result

        def revalidate(source, preparation, signal):
            check_selected(source, signal)
            result = self.dispatcher.revalidate(deepcopy(source), deepcopy(preparation), signal.model_copy(deep=True))
            check_selected(source, signal)
            return result

        check()
        return WaitRecoverySources(journal=journal, prepare=prepare, revalidate=revalidate,
            read_guard=guard, close=close)
