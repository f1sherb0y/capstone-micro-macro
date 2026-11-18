"""Connect explicit host ref selections to authorized commercial A12 assembly."""
from copy import deepcopy
from dataclasses import dataclass

from integration.commercial_actions import CommercialActionAssembler
from src.actions.contracts.common import ActionContext, Reference
from src.coordination.commercial_capacity_conditions import CapacityConditionReading
from src.coordination.commercial_conditions import commercial_continuation_profiles
from src.coordination.commercial_execution_query import EXECUTION_CODE, CommercialExecutionConditionReading
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class CommercialCurrentSelection:
    """Actual host read point, selected current profile and dependency version."""
    context: ActionContext
    profile_ref: Reference
    current_ref: Reference


class CommercialContinuationReader:
    """Read current conditions through the same input/runner assembly boundary.

    select_current is a trusted host callback. It receives the original task,
    condition and signal but must select an actual current context and refs.
    No versions are sorted or guessed, and no signal data becomes a projection.
    Historical dependencies must remain explicitly visible and authorized.
    """

    def __init__(self, *, assembler, select_current):
        if not isinstance(assembler,CommercialActionAssembler) or not callable(select_current):
            raise ValueError('Commercial continuation requires its assembler and an explicit host selection callback')
        self.assembler, self.select_current = assembler, select_current
        self._conditions = frozenset((p.action_id,p.condition_code)
            for p in commercial_continuation_profiles(lambda check: None))

    def __call__(self, check):
        source = check.source['identity']
        action_id = source['action_id']
        if (action_id,check.condition.condition_code) not in self._conditions:
            raise TaskConflict('Condition is outside the commercial continuation binding')
        if (check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id']
                or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Continuation signal changes the original run, recipient or trigger')
        old_refs = check.condition.object_refs
        if len(old_refs) != 1:
            raise TaskConflict('Commercial condition requires one explicit original dependency')
        selected = self.select_current(deepcopy(check))
        if (not isinstance(selected,CommercialCurrentSelection)
                or not isinstance(selected.context,ActionContext)
                or not isinstance(selected.profile_ref,Reference)
                or not isinstance(selected.current_ref,Reference)):
            raise TaskConflict('Host must select a typed actual current read point and references')
        context = selected.context.model_copy(deep=True)
        profile_ref, ref = selected.profile_ref.model_copy(deep=True), selected.current_ref.model_copy(deep=True)
        if (context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != action_id or context.business_time != check.signal.business_time):
            raise TaskConflict('Current host selection changes run, action or signal business time')
        old_ref = old_refs[0]
        if (ref.kind,ref.id) != (old_ref.kind,old_ref.id) or profile_ref.kind != 'ContinuationProfile':
            raise TaskConflict('Current host selection substitutes the original dependency or profile kind')
        visible = {r.key() for r in context.visible_refs}
        if not {old_ref.key(),ref.key(),profile_ref.key()} <= visible:
            raise TaskConflict('Original and current dependency/profile must be explicitly visible together')
        prepared = self.assembler.build(context,profile_ref=profile_ref)
        if prepared.reading.organization_id != source['organization_id']:
            raise TaskConflict('Current invocation belongs to another organization')
        prepared.reading.recheck()
        self.validate_prepared(check, prepared)
        return self.condition_reading(check, prepared, ref)

    def condition_reading(self, check, prepared, ref):
        if check.condition.condition_code == 'commercial_resume_capacity_unavailable':
            profile = prepared.reading.resolve(prepared.action_input.continuation_profile_ref)
            state = prepared.reading.resolve(profile.state_ref)
            if state.resource_calendar_ref != ref:
                raise TaskConflict('Selected capacity dependency is not the current profile calendar')
            prepared.reading.recheck()
            return CapacityConditionReading(prepared.context,prepared.reading,ref,
                prepared.action_input.continuation_profile_ref)
        if check.condition.condition_code == EXECUTION_CODE:
            return CommercialExecutionConditionReading(prepared.context, prepared.reading, ref,
                prepared.action_input.continuation_profile_ref)
        return prepared.context, prepared.reading, ref

    def validate_prepared(self, check, prepared):
        """Formal bindings can authenticate the exact selected closed input."""


def build_assembled_commercial_continuation_dispatcher(*, inbox, store, assembler,
        select_current, project_signal, prepare, revalidate, extra_profiles=(), action_ids=None):
    """Use assembled typed inputs for all twenty-one declared A12 waits.

    Signal projection, successor preparation and fresh validation remain host
    callbacks. This only composes existing read and durable scheduling paths;
    it never executes a handler or submits a formal business operation.
    """
    from integration.task_continuation import build_commercial_continuation_dispatcher

    reader = CommercialContinuationReader(assembler=assembler,select_current=select_current)
    return build_commercial_continuation_dispatcher(inbox=inbox,store=store,read_current=reader,
        project_signal=project_signal,prepare=prepare,revalidate=revalidate,extra_profiles=extra_profiles,
        action_ids=action_ids)
