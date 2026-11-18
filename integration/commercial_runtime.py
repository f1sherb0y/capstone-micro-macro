"""One explicit host assembly for commercial tasks, feedback and recovery."""
from copy import deepcopy
from contextlib import nullcontext
from dataclasses import dataclass

from integration.commercial_actions import CommercialActionAssembler
from integration.commercial_callbacks import CommercialNextSelection, build_commercial_successor_dispatcher
from integration.commercial_worker import CommercialTaskWorker
from src.actions.contracts.common import ActionContext, Reference
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, TaskStore


@dataclass(frozen=True)
class CommercialRuntimeNextSelection:
    """Host chooses fresh data; the runtime supplies persisted original context."""
    context: ActionContext
    profile_ref: Reference
    current_refs: list[Reference]
    request_id: str


class CommercialRuntime:
    """Connect an actual host provider's assembler to a single run-local store.

    Construction never executes a handler or consumes feedback. The host owns
    stores, event delivery and facts. dispatch_feedback only creates validated
    successor tasks; run executes one explicitly selected invocation. Formal
    submission/query stays outside this local runtime.
    """

    def __init__(self, *, assembler, store, inbox, select_current, select_next,
                 project_signal, client_version, model_version,
                 validate_invocation, validate_wait, validate_recovery, read_guard=None):
        if (not isinstance(assembler,CommercialActionAssembler) or not isinstance(store,TaskStore)
                or assembler.organizations.run_id != store.run_id
                or inbox.run_id != store.run_id or inbox.organization_ids != store.organization_ids):
            raise ValueError('Commercial runtime requires one assembler/store/inbox run and recipient set')
        if not all(callable(callback) for callback in (select_current,select_next,project_signal,
                validate_invocation,validate_wait,validate_recovery)):
            raise ValueError('Actual host selection, signal, execution/wait/recovery checks are required')
        if (assembler.source_mode == 'formal' and not callable(read_guard)
                or read_guard is not None and not callable(read_guard)):
            raise ValueError('Formal commercial feedback recovery requires its actual source/authority/journal guard')
        self.assembler, self.store, self.inbox = assembler, store, inbox
        self.read_guard = read_guard
        self.snapshots = InvocationSnapshotStore(store)

        def select_persisted_next(*, source, signal, request_id):
            identity = TaskIdentity(**source['identity'])
            snapshot = self.snapshots.get(identity)
            selected = select_next(source=deepcopy(source),signal=signal.model_copy(deep=True),
                request_id=request_id,original_snapshot=deepcopy(snapshot))
            if not isinstance(selected,CommercialRuntimeNextSelection):
                raise TaskConflict('Runtime host must select fresh typed data without replacing original history')
            selected = deepcopy(selected)
            return CommercialNextSelection(original_context=ActionContext.model_validate(snapshot['context']),
                context=selected.context,profile_ref=selected.profile_ref,
                current_refs=selected.current_refs,request_id=selected.request_id)

        self.dispatcher = build_commercial_successor_dispatcher(inbox=inbox,store=store,assembler=assembler,
            select_current=select_current,select_next=select_persisted_next,project_signal=project_signal,
            client_version=client_version,model_version=model_version)
        self.worker = CommercialTaskWorker(assembler=assembler,journal=self.dispatcher.journal,
            snapshots=self.snapshots,client_version=client_version,model_version=model_version,
            validate_invocation=validate_invocation,validate_wait=validate_wait,validate_recovery=validate_recovery)
        self._recovery_mode = assembler.source_mode
        self._recovery_components = self._feedback_components()

    def _feedback_components(self):
        return (self.assembler, self.store, self.inbox, self.read_guard, self.snapshots,
            self.snapshots.store, self.dispatcher, self.dispatcher.inbox, self.dispatcher.journal,
            self.dispatcher.journal.store, self.dispatcher.journal.registry,
            self.dispatcher.project_signal, self.dispatcher.prepare, self.dispatcher.revalidate)

    def _check_feedback_binding(self):
        current = self._feedback_components()
        if (len(current) != len(self._recovery_components)
                or any(now is not original for now, original in zip(current, self._recovery_components))
                or self.assembler.source_mode != self._recovery_mode
                or self.assembler.organizations.run_id != self.store.run_id
                or self.dispatcher.inbox is not self.inbox or self.dispatcher.journal.store is not self.store
                or self.snapshots.store is not self.store):
            raise TaskConflict('Commercial feedback recovery changed its original journal/guard/source/callback bindings')

    def register(self, context, *, profile_ref, request_id, purpose):
        """Assemble and atomically persist one root invocation; do not execute."""
        prepared = self.assembler.build(context,profile_ref=profile_ref)
        return self.worker.register(prepared,request_id=request_id,purpose=purpose)

    def run(self, identity):
        """Consume one explicitly selected root or successor; no automatic retry."""
        return self.worker.run(identity)

    def dispatch_feedback(self, *, organization_id):
        """Scan persisted recipient feedback and atomically link ready successors."""
        self._check_feedback_binding()
        if organization_id not in self.store.organization_ids:
            raise TaskConflict('Commercial feedback recovery requires the original run recipient')
        guard = nullcontext() if self.read_guard is None else self.read_guard(
            run_id=self.store.run_id, organization_id=organization_id)
        with guard:
            self._check_feedback_binding()
            result = self.dispatcher(run_id=self.store.run_id,organization_id=organization_id)
            self._check_feedback_binding()
            return result

    def ready(self, *, organization_id):
        """Return ready local tasks for explicit consumption, including roots."""
        tasks = self.store.for_organization(run_id=self.store.run_id,organization_id=organization_id)
        ready = []
        for task in tasks:
            if (task['identity']['action_id'] in {'CONTRACTOR-A12','SUPPLIER-A12'}
                    and task['state'] == 'waiting_input' and not task['conditions']):
                identity = TaskIdentity(**task['identity'])
                if self.store.continuation(identity) is None:
                    ready.append(deepcopy(task))
        return ready
