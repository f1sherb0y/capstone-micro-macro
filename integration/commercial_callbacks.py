"""Fresh host callbacks connect commercial waits to exact successor snapshots."""
from copy import deepcopy
from dataclasses import dataclass

from integration.commercial_actions import CommercialActionAssembler
from integration.commercial_successors import prepare_commercial_successor, revalidate_commercial_successor
from src.actions.contracts.common import ActionContext, Reference, ResumeCondition
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.commercial_capacity_conditions import CapacityConditionReading
from src.coordination.commercial_conditions import commercial_continuation_profiles
from src.coordination.continuations import ConditionCheck, ConditionRegistry, ContinuationPreparation, ResumeSignal
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class CommercialNextSelection:
    """Host chooses a current invocation and retains the original task context."""
    original_context: ActionContext
    context: ActionContext
    profile_ref: Reference
    current_refs: list[Reference]
    request_id: str


class CommercialSuccessorCallbacks:
    """prepare and revalidate each perform a new host selection and projection.

    select_next receives source, signal and request_id as named arguments. On
    revalidation, request_id is the already proposed successor ID. The host
    must supply the original persisted context and explicit current dependency
    versions. All waits are reevaluated in one newly assembled read boundary;
    no callback executes a handler or submits a formal operation.
    """

    def __init__(self, *, assembler, select_next, client_version, model_version,
            read_prepared=None, validate_relation=None):
        if not isinstance(assembler,CommercialActionAssembler) or not callable(select_next):
            raise ValueError('Successor callbacks require the commercial assembler and actual host selection')
        self.assembler, self.select_next = assembler, select_next
        self.client_version, self.model_version = client_version, model_version
        if ((read_prepared is None) != (validate_relation is None)
                or read_prepared is not None and (not callable(read_prepared) or not callable(validate_relation))):
            raise ValueError('Formal successor reading requires both prepared-source and native relation callbacks')
        self.read_prepared, self.validate_relation = read_prepared, validate_relation

    def _fresh(self, source, signal, *, request_id=None):
        if not isinstance(signal,ResumeSignal):
            raise TaskConflict('Successor callbacks require a typed original signal')
        previous = TaskIdentity(**source['identity'])
        selected = self.select_next(source=deepcopy(source),signal=signal.model_copy(deep=True),request_id=request_id)
        if (not isinstance(selected,CommercialNextSelection)
                or not isinstance(selected.original_context,ActionContext)
                or not isinstance(selected.context,ActionContext) or not isinstance(selected.profile_ref,Reference)
                or not isinstance(selected.current_refs,list)
                or any(not isinstance(ref,Reference) for ref in selected.current_refs)):
            raise TaskConflict('Host must select typed original/current contexts, profile and dependency versions')
        selected = deepcopy(selected)
        old, current = selected.original_context, selected.context
        if (task_digest(old.model_dump(mode='json')) != previous.context_sha256
                or old.run_id != previous.run_id or old.contract_ref.id != previous.action_id
                or old.contract_ref.kind != 'ActionContract' or current.scope != old.scope
                or current.business_time.clock_ref != old.business_time.clock_ref
                or current.business_time.offset < old.business_time.offset):
            raise TaskConflict('Successor changes its original context snapshot, scope or business chronology')
        if request_id is not None and selected.request_id != request_id:
            raise TaskConflict('Revalidation must preserve the proposed successor request ID')
        conditions = [ResumeCondition.model_validate(raw) for raw in source.get('conditions',[])]
        if not conditions or any(len(condition.object_refs) != 1 for condition in conditions):
            raise TaskConflict('Commercial successors require explicit original waiting conditions')
        unique_refs(selected.current_refs)
        refs = {(ref.kind,ref.id):ref for ref in selected.current_refs}
        required = {(condition.object_refs[0].kind,condition.object_refs[0].id) for condition in conditions}
        if set(refs) != required:
            raise TaskConflict('Host must supply every original dependency current version without substitutions')
        visible = {ref.key() for ref in current.visible_refs}
        needed = {ref.key() for ref in selected.current_refs} | {c.object_refs[0].key() for c in conditions}
        if not needed <= visible:
            raise TaskConflict('Original/current dependencies must share the new authorized read point')
        prepared = self.assembler.build(current,profile_ref=selected.profile_ref)

        def read_condition(check):
            old_ref = check.condition.object_refs[0]
            ref = refs[(old_ref.kind,old_ref.id)]
            if self.read_prepared is not None:
                return self.read_prepared(check, prepared, ref)
            if check.condition.condition_code == 'commercial_resume_capacity_unavailable':
                return CapacityConditionReading(prepared.context,prepared.reading,ref,
                    prepared.action_input.continuation_profile_ref)
            from src.coordination.commercial_execution_query import EXECUTION_CODE, CommercialExecutionConditionReading
            if check.condition.condition_code == EXECUTION_CODE:
                return CommercialExecutionConditionReading(prepared.context, prepared.reading, ref,
                    prepared.action_input.continuation_profile_ref)
            return prepared.context,prepared.reading,ref

        registry = ConditionRegistry(commercial_continuation_profiles(read_condition, self.validate_relation))
        ready = True
        for condition in conditions:
            earliest = condition.earliest_time
            if earliest is not None and (earliest.clock_ref != current.business_time.clock_ref
                    or earliest.offset > current.business_time.offset):
                ready = False
                continue
            profile = registry.get(previous.action_id,condition)
            outcome = profile.evaluate(ConditionCheck(deepcopy(source),condition.model_copy(deep=True),signal.model_copy(deep=True)))
            if outcome not in {'ready','waiting','unavailable'}:
                raise TaskConflict('Condition must return its explicit scheduling outcome')
            ready = ready and outcome == 'ready'
        prepared.reading.recheck()
        return prepared,selected.request_id,ready

    def prepare(self, source, signal):
        prepared,request_id,ready = self._fresh(source,signal)
        if not ready:
            raise TaskConflict('Current commercial conditions changed; retain the original waiting task')
        return prepare_commercial_successor(source,signal,prepared,request_id=request_id,
            client_version=self.client_version,model_version=self.model_version)

    def revalidate(self, source, preparation, signal):
        if not isinstance(preparation,ContinuationPreparation):
            raise TaskConflict('Revalidation requires the proposed exact successor snapshot')
        prepared,_,ready = self._fresh(source,signal,request_id=preparation.successor.request_id)
        if not ready: return False
        return revalidate_commercial_successor(source,preparation,signal,prepared,
            client_version=self.client_version,model_version=self.model_version)


def build_commercial_successor_dispatcher(*, inbox, store, assembler, select_current,
        select_next, project_signal, client_version, model_version, action_ids=None):
    """Compose the declared A12 waits, fresh successor callbacks and journal."""
    from integration.commercial_continuation import build_assembled_commercial_continuation_dispatcher

    callbacks = CommercialSuccessorCallbacks(assembler=assembler,select_next=select_next,
        client_version=client_version,model_version=model_version)
    return build_assembled_commercial_continuation_dispatcher(inbox=inbox,store=store,assembler=assembler,
        select_current=select_current,project_signal=project_signal,prepare=callbacks.prepare,revalidate=callbacks.revalidate,
        action_ids=action_ids)
