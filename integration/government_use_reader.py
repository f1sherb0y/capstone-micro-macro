"""Read actual Government A11 use-plan sources from the original task journal."""
from copy import deepcopy
from dataclasses import dataclass

from integration.government_inspection_reader import (
    GovernmentInspectionReader, GovernmentInspectionRecoveryBindings, GovernmentInspectionRecoverySettings,
    _build_assembled_government_dispatcher,
)
from integration.government_use_actions import GovernmentUseActionAssembler
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference, walk_references
from src.actions.contracts.government_use_objects import (
    GovUseApplicationView, GovUseProcedureView, GovUsePlanView, GovSchedulingDependencyView, GovSchedulingTaskView,
)
from src.coordination.government_use_conditions import GovernmentUseConditionReading, _DEPENDENCY_CODE, _CAPACITY_CODE, _CODES, _INPUT_LISTS
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class GovernmentUseCurrentSelection:
    request: RoleContractInvocation


class GovernmentUseRecoverySettings(GovernmentInspectionRecoverySettings):
    """Original A11 current source/policy/binding versions."""


@dataclass(frozen=True)
class GovernmentUseRecoveryBindings(GovernmentInspectionRecoveryBindings):
    """Actual A11 source selector, original guard and native/successor validators."""


class GovernmentUseReader(GovernmentInspectionReader):
    """Assemble a separately authorized use judgment without executing it.

    Original application/plan/Task/Dependency versions remain explicitly
    readable. Native validation authenticates their independently authored
    lineage and full current input. A07 signing, A10 supervision, retained
    permit conditions and actual work or use effects remain separate.
    """
    ACTION_ID = 'GOV-A11'
    CONDITION_CODE = _DEPENDENCY_CODE
    CONDITION_CODES = _CODES
    ASSEMBLER_TYPE = GovernmentUseActionAssembler
    READER_SCHEMA = 'government-use-reader.v1'

    def __call__(self, check):
        self._check()
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != self.ACTION_ID or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code not in self.CONDITION_CODES or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 1 or old_refs[0].kind != ('Dependency' if check.condition.condition_code == _DEPENDENCY_CODE else 'ResourceCalendar')):
            raise TaskConflict('Government use reader substitutes original action, recipient or dependency wait')
        identity = TaskIdentity(**deepcopy(source))
        snapshot = self.snapshots.get(identity)
        registration = self.assembler.registry.get(self.ACTION_ID)
        original_input = registration.contract.validate_input(deepcopy(snapshot['action_input']))
        selected = self.select_current(deepcopy(check))
        self._check()
        if not isinstance(selected, GovernmentUseCurrentSelection):
            raise TaskConflict('Government use reader requires an explicit typed current invocation')
        request = RoleContractInvocation.model_validate(selected.request).model_copy(deep=True)
        context = request.context
        current_input = registration.contract.validate_input(deepcopy(request.action_input))
        if (context.run_id != source['run_id'] or context.run_id != self.assembler.organizations.run_id
                or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.ACTION_ID
                or context.execution_mode != 'llm' or request.execution_path not in {None, registration.strategy}
                or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                or context.scope.model_dump(mode='json') != snapshot['context']['scope']
                or current_input.scope != original_input.scope
                or any(getattr(original_input, field).key()[:2] != getattr(current_input, field).key()[:2]
                    for field in ('case_ref', 'use_application_ref', 'procedure_ref'))
                or not {ref.key() for ref in (*old_refs, *walk_references(original_input), *walk_references(current_input))}
                    <= {ref.key() for ref in context.visible_refs}):
            raise TaskConflict('Government use reader substitutes original scope/application or authorized original/current sources')
        prepared = self.assembler.build(context, **deepcopy(request.action_input))
        baseline = deepcopy(prepared.reading.evidence())
        try:
            reading = prepared.reading
            if task_digest(baseline) != prepared.reading_sha256 or reading.organization_id != source['organization_id']:
                raise TaskConflict('Government use assembly changes original source snapshot or authorized recipient')
            for ref in walk_references(original_input):
                reading.resolve(ref)
            applications, procedures, plans = [], [], []
            for action_input in (original_input, prepared.action_input):
                application = reading.resolve(action_input.use_application_ref)
                procedure = reading.resolve(action_input.procedure_ref)
                if (not isinstance(application, GovUseApplicationView) or application.ref != action_input.use_application_ref
                        or not isinstance(procedure, GovUseProcedureView) or procedure.ref != action_input.procedure_ref
                        or application.case_ref != action_input.case_ref or application.recipient_organization_id != source['organization_id']
                        or procedure.application_ref != application.ref or procedure.case_ref != application.case_ref
                        or procedure.content_sha256 != application.content_sha256 or procedure.plan_ref is None):
                    raise TaskConflict('Government use reader substitutes original application/procedure or its independent plan')
                plan = reading.resolve(procedure.plan_ref)
                if (not isinstance(plan, GovUsePlanView) or plan.ref != procedure.plan_ref or plan.application_ref != application.ref
                        or plan.content_sha256 != application.content_sha256):
                    raise TaskConflict('Government use reader replaces original application content or plan linkage')
                applications.append(application); procedures.append(procedure); plans.append(plan)
                # Expose the complete independently authored task set, not
                # only a selector-supplied task that could hide other work.
                reading.resolve(plan.plan.work_profile_ref)
                for ref in plan.task_refs:
                    reading.resolve(ref)
            old_application, application = applications
            old_plan, plan = plans
            if (old_application.content_sha256 != application.content_sha256 or old_plan.ref.key()[:2] != plan.ref.key()[:2]
                    or {ref.key()[:2] for ref in old_plan.task_refs} != {ref.key()[:2] for ref in plan.task_refs}):
                raise TaskConflict('Government use reader replaces original signed content, plan or task identities')
            if check.condition.condition_code == _CAPACITY_CODE:
                if (old_plan.resource_calendar_ref.key() != old_refs[0].key()
                        or plan.resource_calendar_ref.key()[:2] != old_refs[0].key()[:2]):
                    raise TaskConflict('Government use reader changes original emitted capacity calendar')
                for selected_plan in (old_plan, plan):
                    reading.resolve(selected_plan.resource_calendar_ref)
                    reading.resolve(selected_plan.capacity_result_ref)
                    for ref in selected_plan.task_refs:
                        selected_task = reading.resolve(ref)
                        if not isinstance(selected_task, GovSchedulingTaskView):
                            raise TaskConflict('Government use reader requires complete actual capacity task sources')
                        reading.resolve(selected_task.estimate_ref)
                        for work_ref in selected_task.work_fact_refs:
                            reading.resolve(work_ref)
            else:
                old_dependency = reading.resolve(old_refs[0])
                if (not isinstance(old_dependency, GovSchedulingDependencyView) or old_dependency.ref.key() != old_refs[0].key()
                        or old_dependency.task_ref.key() not in {ref.key() for ref in old_plan.task_refs}):
                    raise TaskConflict('Government use reader dependency is outside its original plan')
                old_task = reading.resolve(old_dependency.task_ref)
                current_tasks = [ref for ref in plan.task_refs if ref.key()[:2] == old_dependency.task_ref.key()[:2]]
                if len(current_tasks) != 1:
                    raise TaskConflict('Government use reader substitutes or duplicates original dependency task')
                task = reading.resolve(current_tasks[0])
                if (not isinstance(old_task, GovSchedulingTaskView) or not isinstance(task, GovSchedulingTaskView)
                        or old_refs[0].key() not in {ref.key() for ref in old_task.dependency_refs}):
                    raise TaskConflict('Government use reader drops its original emitted dependency')
                current_dependencies = [ref for ref in task.dependency_refs if ref.key()[:2] == old_refs[0].key()[:2]]
                if len(current_dependencies) != 1:
                    raise TaskConflict('Government use reader changes original dependency identity')
                dependency = reading.resolve(current_dependencies[0])
                if not isinstance(dependency, GovSchedulingDependencyView) or dependency.task_ref != task.ref:
                    raise TaskConflict('Government use reader substitutes original current dependency/task association')
            for field in _INPUT_LISTS:
                old_refs_by_id = {ref.key()[:2]: ref for ref in getattr(original_input, field)}
                current_refs_by_id = {ref.key()[:2]: ref for ref in getattr(prepared.action_input, field)}
                if (len(old_refs_by_id) != len(getattr(original_input, field))
                        or len(current_refs_by_id) != len(getattr(prepared.action_input, field))
                        or set(old_refs_by_id) != set(current_refs_by_id)):
                    raise TaskConflict('Government use reader changes original received proof/permit/condition identities')
                if field in {'permit_refs', 'remaining_condition_refs'}:
                    continue  # Their native effect/status is independently revalidated.
                for key, old_ref in old_refs_by_id.items():
                    old, current = reading.resolve(old_ref), reading.resolve(current_refs_by_id[key])
                    # Recorded provenance and physical work quantities survive
                    # projection refresh; native validation authenticates any
                    # initially unresolved verification result separately.
                    for name in type(old).model_fields:
                        if (name.startswith('author_') or name in {'authored_at', 'method_ref', 'input_sha256', 'content_sha256',
                                'investment_key', 'core_event_id', 'effort', 'window', 'completed_scope_refs'}):
                            if not hasattr(current, name) or getattr(old, name) != getattr(current, name):
                                raise TaskConflict('Government use reader rewrites original proof provenance or actual work quantity')
                    if not {ref.key() for ref in getattr(old, 'evidence_refs', [])} <= {ref.key() for ref in getattr(current, 'evidence_refs', [])}:
                        raise TaskConflict('Government use reader drops original received proof evidence')
            return GovernmentUseConditionReading(prepared.context, reading,
                deepcopy(snapshot['action_input']), prepared.action_input.model_dump(mode='json'))
        finally:
            prepared.reading.recheck()
            self._check()
            current_evidence = {Reference.model_validate(row['ref']).key(): row['projection'] for row in prepared.reading.evidence()}
            if (self.snapshots.get(identity) != snapshot
                    or any(current_evidence.get(Reference.model_validate(row['ref']).key()) != row['projection'] for row in baseline)
                    or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                    or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
                raise TaskConflict('Government use reader changed original snapshot or assembled context/input/source reading')


def build_assembled_government_use_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate):
    """Hold the actual source/authority/inbox/journal guard through A11 recovery."""
    from integration.task_continuation import build_government_use_continuation_dispatcher

    return _build_assembled_government_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate,
        reader_type=GovernmentUseReader, dispatcher_factory=build_government_use_continuation_dispatcher)
