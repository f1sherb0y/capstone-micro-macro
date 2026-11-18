"""Authenticate original inspection task authorization and preserve received work histories."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.catalog import ActionContract
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.engineer_inspection_objects import (
    EngineerInspectionTaskView, EngineerInspectionDesignView, EngineerAppointmentView, EngineerPlanningWorkFactView,
    EngineerInspectionObservationView,
    EngineerPlanningEstimateView,
    EngineerPlanningCalendarView, EngineerPlanningAllocationView,
    EngineerPlanningQualificationView,
    EngineerInspectionIssueView, EngineerInspectionDesignChangeView,
)
from src.actions.contracts.service_objects import ServiceWorkProfileView
from src.actions.contracts.references import ActionReadView
from src.actions.roles.engineer_inspection import (
    inspect_and_support, recheck_original_engineer_inspection_observation_wait, recheck_original_engineer_inspection_investment,
    recheck_original_engineer_inspection_personnel,
    recheck_original_engineer_inspection_qualification,
    recheck_original_engineer_inspection_equipment,
    recheck_original_engineer_inspection_capacity,
    recheck_original_engineer_inspection_design_change,
)
from src.actions.roles.qs_change import content_digest
from src.methods.pricing import decimal_fraction
from src.coordination.contractor_closeout_conditions import ContractorCloseoutConditionReading
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


AUTHORIZATION_CODE = 'original_inspection_task_waiting_or_closed'
OBSERVATION_CODE = 'original_visible_inspection_observations_not_received'
INVESTMENT_CODE = 'original_inspection_work_already_invested'
PERSONNEL_CODE = 'original_inspection_personnel_unsuitable'
QUALIFICATION_CODE = 'original_inspection_personnel_qualification_unavailable'
EQUIPMENT_CODE = 'original_inspection_equipment_unavailable'
CAPACITY_CODE = 'shared_inspection_capacity_unavailable'
CHANGE_CODE = 'separate_original_professional_design_change_required'
_RESOURCE_CODES = {PERSONNEL_CODE, QUALIFICATION_CODE, EQUIPMENT_CODE}
_CALENDAR_CODES = {*_RESOURCE_CODES, CAPACITY_CODE}
_CODES = {AUTHORIZATION_CODE, OBSERVATION_CODE, INVESTMENT_CODE, CHANGE_CODE, *_CALENDAR_CODES}


@dataclass(frozen=True)
class EngineerInspectionConditionReading(ContractorCloseoutConditionReading):
    contract: ActionContract | None = None


def check_engineer_inspection_authorization(check, selected, validate_relation):
    if check.condition.condition_code != AUTHORIZATION_CODE:
        raise TaskConflict('Inspection authorization checker substitutes the original wait branch')
    return _check_engineer_inspection_history(check, selected, validate_relation)


def check_engineer_inspection_investment(check, selected, validate_relation, *, terminal=False):
    if check.condition.condition_code != INVESTMENT_CODE:
        raise TaskConflict('Inspection investment checker substitutes the original wait branch')
    return _check_engineer_inspection_history(check, selected, validate_relation, terminal=terminal)


def _check_engineer_inspection_history(check, selected, validate_relation, *, terminal=False):
    source = check.source['identity']
    code = check.condition.condition_code
    if (source['action_id'] != 'ENGINEER-A08' or source['role'] != 'Engineer' or source['purpose'] != 'action'
            or code not in _CODES or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != (('Resource',) if code in {PERSONNEL_CODE, EQUIPMENT_CODE}
                else ('Qualification',) if code == QUALIFICATION_CODE
                else ('Issue', 'Deliverable') if code == CHANGE_CODE
                else ('ResourceCalendar',) if code == CAPACITY_CODE else ('Task',))
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, EngineerInspectionConditionReading) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)
            or terminal and code != INVESTMENT_CODE):
        raise TaskConflict('Inspection recovery requires the original private task authorization wait')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id']
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and (raw != current_raw or context.actor_id != original.actor_id or context.function_ref != original.function_ref)
            or context.run_id != source['run_id'] or context.contract_ref != original.contract_ref
            or context.contract_ref.id != 'ENGINEER-A08' or context.scope != original.scope or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Inspection recovery replaces original snapshot, scope, time or current read authority')
    reading.check_method_context(context, 'ENGINEER-A08')
    contract = selected.contract
    if not isinstance(contract, ActionContract) or contract.action_id != 'ENGINEER-A08' or contract.role != 'Engineer':
        raise TaskConflict('Inspection recovery lacks the original registered A08 contract')
    original_input, current_input = contract.validate_input(raw), contract.validate_input(current_raw)
    if original_input.access_ref is not None and (current_input.access_ref is None
            or original_input.access_ref.key()[:2] != current_input.access_ref.key()[:2]):
        raise TaskConflict('Inspection recovery replaces the original site access identity')

    def physical(refs):
        result = {ref.key()[:2]: ref for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('Inspection recovery aliases physical source or work histories')
        return result

    def read(ref, schema, at):
        row = reading.resolve(ref)
        identity = row.function_ref if isinstance(row, RoleAssignment) else getattr(row, 'ref', None)
        if not isinstance(row, schema) or identity != ref:
            raise TaskConflict('Inspection recovery lacks exact typed original/current sources')
        available = getattr(row, 'available_at', None)
        if available is not None and (available.clock_ref != at.clock_ref or available.offset > at.offset):
            raise TaskConflict('Inspection recovery introduces a source unavailable at its original/query time')
        return row

    versions = []
    for values, at in ((original_input, original.business_time), (current_input, context.business_time)):
        if terminal:
            at = original.business_time
        task = read(values.inspection_task_ref, EngineerInspectionTaskView, at)
        design = read(values.applicable_design_ref, EngineerInspectionDesignView, at)
        appointment = read(task.appointment_ref, EngineerAppointmentView, at)
        if (task.organization_id != source['organization_id'] or appointment.provider_organization_id != source['organization_id']
                or task.applicable_design_ref != design.ref or task.design_content_sha256 != design.content_sha256
                or values.scope != context.scope or task.scope != context.scope
                or values.observation_method_ref != task.observation_method_ref):
            raise TaskConflict('Inspection recovery replaces original organization, scope, design or method')
        facts = {key: read(ref, EngineerPlanningWorkFactView, at) for key, ref in physical(task.work_fact_refs).items()}
        version = dict(task=task, design=design, appointment=appointment, facts=facts)
        if code == INVESTMENT_CODE:
            if task.choice != 'plan_inspection' or task.estimate_ref is None or task.work_profile_ref is None:
                raise TaskConflict('Inspection investment recovery requires the original finite planning work')
            version['estimate'] = read(task.estimate_ref, EngineerPlanningEstimateView, at)
            version['profile'] = read(task.work_profile_ref, ServiceWorkProfileView, at)
        if code in _CALENDAR_CODES:
            if task.choice != 'plan_inspection' or task.resource_calendar_ref is None:
                raise TaskConflict('Inspection personnel recovery requires the original planning task and calendar')
            calendar = read(task.resource_calendar_ref, EngineerPlanningCalendarView, at)
            if calendar.organization_id != source['organization_id']:
                raise TaskConflict('Inspection personnel recovery borrows another private resource calendar')
            physical([row.resource_ref for row in calendar.resources])
            version['calendar'] = calendar
            version['allocation'] = {} if task.existing_allocation_ref is None else {
                task.existing_allocation_ref.key()[:2]: read(task.existing_allocation_ref, EngineerPlanningAllocationView, at)}
        versions.append(version)
    old, current = versions
    for name in ('task', 'design', 'appointment'):
        before, after = old[name], current[name]
        if ((before.ref.key()[:2] != after.ref.key()[:2] and not (code == CHANGE_CODE and name == 'design'))
                or before.ref == after.ref and before != after):
            raise TaskConflict('Inspection recovery replaces physical originals or rewrites immutable source versions')
    task, current_task = old['task'], current['task']
    if (code not in {*_CALENDAR_CODES, CHANGE_CODE} and (task.ref != check.condition.object_refs[0] or current_task.ref != selected.history_ref)
            or code == AUTHORIZATION_CODE and task.status == 'authorized'):
        raise TaskConflict('Inspection recovery substitutes its actual original/current task query')
    historical_comparisons = []
    if code == CAPACITY_CODE:
        original_gate, historical_comparisons = recheck_original_engineer_inspection_capacity(original, original_input, reading)
    else:
        original_gate = (inspect_and_support if code == AUTHORIZATION_CODE
            else recheck_original_engineer_inspection_observation_wait if code == OBSERVATION_CODE
            else recheck_original_engineer_inspection_investment if code == INVESTMENT_CODE
            else recheck_original_engineer_inspection_personnel if code == PERSONNEL_CODE
            else recheck_original_engineer_inspection_qualification if code == QUALIFICATION_CODE
            else recheck_original_engineer_inspection_design_change if code == CHANGE_CODE
            else recheck_original_engineer_inspection_equipment)(original, original_input, reading)
    if (original_gate.get('resume_condition', {}).get('condition_code') != code
            or original_gate.get('resume_condition', {}).get('object_refs') != list(check.condition.object_refs)):
        raise TaskConflict('Inspection wait differs from the original authorized processor evaluation')
    if task.status == 'closed' and current_task.status != 'closed':
        raise TaskConflict('Inspection recovery cannot reopen an original closed task')
    for name in ('scope', 'choice', 'design_content_sha256', 'discipline_code', 'function_code', 'requested_use'):
        if code == CHANGE_CODE and name == 'design_content_sha256':
            continue
        if getattr(task, name) != getattr(current_task, name):
            raise TaskConflict('Inspection recovery changes original design content, purpose or professional scope')
    for name in ('observation_method_ref', 'work_profile_ref', 'estimate_ref', 'resource_calendar_ref',
            'access_dependency_ref', 'existing_allocation_ref', 'test_method_ref', 'response_issue_ref'):
        before, after = getattr(task, name), getattr(current_task, name)
        if before is not None and (after is None or before.key()[:2] != after.key()[:2]):
            raise TaskConflict('Inspection recovery drops original method, work, occupation or query identity')
    for name in ('received_observation_refs', 'received_query_refs', 'engineering_scope_refs', 'check_spec_refs',
            'work_fact_refs', 'dependency_refs', 'question_refs'):
        if not set(physical(getattr(task, name))) <= set(physical(getattr(current_task, name))):
            raise TaskConflict('Inspection recovery removes original received observations, queries, checks or work')
    if code != CHANGE_CODE and old['design'].content_sha256 != current['design'].content_sha256:
        raise TaskConflict('Inspection recovery requires a separate authorized task for changed applicable design content')
    for name in ('scope', 'provider_id', 'provider_organization_id', 'client_id', 'client_organization_id',
            'payer_id', 'payer_organization_id', 'relation'):
        if getattr(old['appointment'], name) != getattr(current['appointment'], name):
            raise TaskConflict('Inspection recovery changes original service parties or scope')
    for name in ('terms_ref', 'service_relationship_ref', 'capability_ref', 'independence_check_ref'):
        before, after = getattr(old['appointment'], name), getattr(current['appointment'], name)
        if before is not None and (after is None or before.key()[:2] != after.key()[:2]):
            raise TaskConflict('Inspection recovery substitutes original accepted engagement or professional authority')
    if not set(old['facts']) <= set(current['facts']):
        raise TaskConflict('Inspection recovery loses actual original investments')
    for key, before in old['facts'].items():
        after = current['facts'][key]
        if (before.task_ref.key()[:2] != task.ref.key()[:2] or after.task_ref.key()[:2] != current_task.ref.key()[:2]
                or before.organization_id != source['organization_id'] or after.organization_id != source['organization_id']
                or any(getattr(before, name) != getattr(after, name) for name in ('investment_key', 'effort', 'internal_cost', 'window'))
                or before.status == 'committed' and after.status != 'committed'
                or before.ref == after.ref and before != after):
            raise TaskConflict('Inspection recovery rewrites actual work, cost or investment slices')
    if current_task.status != 'authorized':
        return 'waiting', None
    if not terminal and task.ref == current_task.ref:
        if code not in _CALENDAR_CODES:
            raise TaskConflict('Inspection recovery requires an actual new authorized task version')
    history = current_task
    design_change_resolution = None
    if code == CHANGE_CODE:
        status, history, design_change_resolution = _read_inspection_design_change(check, selected, old, current,
            read=read, validate_relation=validate_relation)
        if status != 'ready':
            return status, None
    personnel_resolution = None
    if code in _CALENDAR_CODES:
        before_calendar, after_calendar = old['calendar'], current['calendar']
        if (before_calendar.ref.key()[:2] != after_calendar.ref.key()[:2]
                or before_calendar.ref == after_calendar.ref and before_calendar != after_calendar):
            raise TaskConflict('Inspection personnel recovery substitutes or rewrites the original calendar')
        anchor = check.condition.object_refs[0]
        before_resources = {row.resource_ref.key()[:2]: row for row in before_calendar.resources}
        after_resources = {row.resource_ref.key()[:2]: row for row in after_calendar.resources}
        qualification_resolution = None
        if code == CAPACITY_CODE:
            before_resource, after_resource = None, None
            if before_calendar.ref != anchor or after_calendar.ref != selected.history_ref:
                raise TaskConflict('Inspection capacity recovery substitutes its actual original/current calendar anchor')
            if before_calendar.ref == after_calendar.ref:
                return 'waiting', None
        elif code in {PERSONNEL_CODE, EQUIPMENT_CODE}:
            original_demands = task.resource_shares if code == PERSONNEL_CODE else task.tool_demands
            current_demands = current_task.resource_shares if code == PERSONNEL_CODE else current_task.tool_demands
            before_resource, after_resource = before_resources.get(anchor.key()[:2]), after_resources.get(anchor.key()[:2])
            if (before_resource is None or before_resource.resource_ref != anchor or after_resource is None
                    or after_resource.resource_ref != selected.history_ref
                    or anchor.key()[:2] not in physical([item.resource_ref for item in original_demands])
                    or after_resource.resource_ref not in [item.resource_ref for item in current_demands]):
                raise TaskConflict('Inspection resource recovery substitutes its actual original/current personnel or equipment demand')
        else:
            before_qualification = read(anchor, EngineerPlanningQualificationView, original.business_time)
            after_qualification = read(selected.history_ref, EngineerPlanningQualificationView, context.business_time)
            if (before_qualification.ref.key()[:2] != after_qualification.ref.key()[:2]
                    or before_qualification.ref == after_qualification.ref and before_qualification != after_qualification):
                raise TaskConflict('Inspection qualification recovery replaces physical or immutable qualification history')
            if before_qualification.ref == after_qualification.ref:
                return 'waiting', None
            original_demanded = physical([share.resource_ref for share in task.resource_shares])
            current_demanded = physical([share.resource_ref for share in current_task.resource_shares])
            matches = [(row, after_resources.get(key)) for key, row in before_resources.items()
                if key in original_demanded and anchor in row.qualification_refs
                and key in current_demanded and key in after_resources
                and after_qualification.ref in after_resources[key].qualification_refs]
            if not matches:
                raise TaskConflict('Inspection qualification query does not belong to its original/current demanded personnel')
            before_resource, after_resource = matches[0]
            physical(before_resource.qualification_refs)
            physical(after_resource.qualification_refs)
            qualification_resolution = dict(original=before_qualification.model_dump(mode='json'),
                current=after_qualification.model_dump(mode='json'))
            qualification_evidence = []
            for ref in after_qualification.evidence_refs:
                row = read(ref, EvidenceRecord, context.business_time)
                if row.source_kind != 'synthetic' and row.basis_kind == 'observed':
                    if row.effective_window is None or row.effective_window.contains(context.business_time):
                        qualification_evidence.append(row.model_dump(mode='json'))
            if not qualification_evidence:
                return 'unavailable', None
            qualification_resolution['evidence'] = qualification_evidence
        for key in before_resources.keys() & after_resources.keys():
            before, after = before_resources[key], after_resources[key]
            if before.resource_ref == after.resource_ref and before != after:
                raise TaskConflict('Inspection personnel recovery rewrites an immutable embedded resource version')
        if code in {PERSONNEL_CODE, EQUIPMENT_CODE} and after_resource.resource_ref == before_resource.resource_ref:
            return 'waiting', None
        if not set(old['allocation']) <= set(current['allocation']):
            raise TaskConflict('Inspection personnel recovery drops its original allocation history')
        for key, before in old['allocation'].items():
            after = current['allocation'][key]
            if (before.ref == after.ref and before != after
                    or before.organization_id != source['organization_id'] or after.organization_id != source['organization_id']
                    or before.task_ref.key()[:2] != after.task_ref.key()[:2]
                    or before.appointment_ref.key()[:2] != after.appointment_ref.key()[:2]
                    or before.work_plan_ref.key()[:2] != after.work_plan_ref.key()[:2]
                    or before.status == 'released' and after.status != 'released'
                    or not set(physical(before.work_fact_refs)) <= set(physical(after.work_fact_refs))):
                raise TaskConflict('Inspection personnel recovery rewrites original allocation or investment identity')
        physical([row.commitment_ref for row in before_calendar.commitments])
        physical([row.commitment_ref for row in after_calendar.commitments])
        before_commitments = {row.commitment_ref.key()[:2]: row for row in before_calendar.commitments}
        after_commitments = {row.commitment_ref.key()[:2]: row for row in after_calendar.commitments}
        for key in before_commitments.keys() & after_commitments.keys():
            before, after = before_commitments[key], after_commitments[key]
            if (before.commitment_ref == after.commitment_ref and before != after
                    or before.resource_ref.key()[:2] != after.resource_ref.key()[:2]):
                raise TaskConflict('Inspection personnel recovery rewrites immutable commitments or moves their resource identity')
        calendar_evidence = []
        for ref in after_calendar.evidence_refs:
            row = read(ref, EvidenceRecord, context.business_time)
            if row.source_kind != 'synthetic' and row.basis_kind == 'observed':
                if row.effective_window is None or row.effective_window.contains(context.business_time):
                    calendar_evidence.append(row.model_dump(mode='json'))
        if not calendar_evidence:
            return 'unavailable', None
        personnel_resolution = dict(schema_version=('engineer-inspection-equipment-native-resolution.v1'
            if code == EQUIPMENT_CODE else 'engineer-inspection-capacity-native-resolution.v1' if code == CAPACITY_CODE
            else 'engineer-inspection-personnel-native-resolution.v1'),
            original_resource=None if before_resource is None else before_resource.model_dump(mode='json'),
            current_resource=None if after_resource is None else after_resource.model_dump(mode='json'),
            original_calendar=before_calendar.model_dump(mode='json'), current_calendar=after_calendar.model_dump(mode='json'),
            original_allocation={str(key): row.model_dump(mode='json') for key, row in old['allocation'].items()},
            current_allocation={str(key): row.model_dump(mode='json') for key, row in current['allocation'].items()},
            evidence=calendar_evidence, sources=reading.evidence())
        if qualification_resolution is not None:
            personnel_resolution['qualification_authentication'] = qualification_resolution
        if validate_relation(source_identity=deepcopy(source), condition_code=code, resolution=deepcopy(personnel_resolution),
                context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Inspection resource recovery lacks native assignment, eligibility and occupation change authentication')
        history = (after_qualification if code == QUALIFICATION_CODE
            else after_calendar if code == CAPACITY_CODE else after_resource)
    investment_resolution = None
    if code == INVESTMENT_CODE:
        before_estimate, after_estimate = old['estimate'], current['estimate']
        for name in ('estimate', 'profile'):
            before, after = old[name], current[name]
            if before.ref.key()[:2] != after.ref.key()[:2] or before.ref == after.ref and before != after:
                raise TaskConflict('Inspection investment recovery replaces physical work sources or immutable versions')
        for name in ('method', 'clock_ref', 'effort_unit', 'capacity_unit', 'effort_per_capacity_tick'):
            if getattr(old['profile'], name) != getattr(current['profile'], name):
                raise TaskConflict('Inspection investment recovery reinterprets original work units or method')
        if (after_estimate.task_ref != current_task.ref or after_estimate.work_profile_ref != current['profile'].ref
                or before_estimate.method != after_estimate.method or before_estimate.effort.unit != after_estimate.effort.unit
                or after_estimate.status != 'succeeded' or after_estimate.executed_at.clock_ref != context.business_time.clock_ref
                or after_estimate.executed_at.offset > after_estimate.available_at.offset
                or current_task.work_fact_coverage != 'complete'):
            raise TaskConflict('Inspection investment recovery lacks the actual authorized successful work estimate and complete history')
        if not terminal and (before_estimate.ref == after_estimate.ref
                or decimal_fraction(after_estimate.effort.value) <= decimal_fraction(before_estimate.effort.value)):
            return 'waiting', None
        investment_evidence = []
        refs = [after_estimate.effort.basis_ref, *after_estimate.evidence_refs]
        for fact in current['facts'].values():
            refs.extend([fact.effort.basis_ref, fact.internal_cost.basis_ref, *fact.evidence_refs])
        for ref in {ref.key(): ref for ref in refs}.values():
            row = read(ref, EvidenceRecord, context.business_time)
            if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                continue
            if row.effective_window is None or row.effective_window.contains(context.business_time):
                investment_evidence.append(row.model_dump(mode='json'))
        if not investment_evidence:
            return 'unavailable', None
        if terminal:
            if task != current_task or before_estimate != after_estimate:
                raise TaskConflict('Inspection archival must retain the exact original fully invested task and estimate')
            if (any(fact.status != 'committed' for fact in current['facts'].values())
                    or sum(decimal_fraction(fact.effort.value) for fact in current['facts'].values())
                    != decimal_fraction(after_estimate.effort.value)):
                raise TaskConflict('Inspection archival lacks actual full work investment coverage')
        investment_resolution = dict(schema_version='engineer-inspection-investment-authority-resolution.v1',
            original_estimate=before_estimate.model_dump(mode='json'), current_estimate=after_estimate.model_dump(mode='json'),
            original_facts={str(key): fact.model_dump(mode='json') for key, fact in old['facts'].items()},
            current_facts={str(key): fact.model_dump(mode='json') for key, fact in current['facts'].items()},
            evidence=investment_evidence, sources=reading.evidence(),
            purpose='archive_original_planning_wait_only' if terminal else 'independently_authorized_additional_work')
        if validate_relation(source_identity=deepcopy(source), condition_code=code, resolution=deepcopy(investment_resolution),
                context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Inspection recovery lacks independent native work increment or actual investment authentication')
    received_observations = []
    if code == OBSERVATION_CODE:
        if task.choice != 'report' or current_task.choice != 'report' or task.received_observation_refs:
            raise TaskConflict('Inspection observation recovery replaces the original empty report intake')
        if not current_task.received_observation_refs:
            return 'waiting', None
        for ref in current_task.received_observation_refs:
            row = read(ref, EngineerInspectionObservationView, context.business_time)
            if (row.task_ref != current_task.ref or row.scope != context.scope
                    or row.applicable_design_ref != current['design'].ref
                    or row.design_content_sha256 != current_task.design_content_sha256
                    or row.method_ref != current_task.observation_method_ref
                    or row.check_spec_ref not in current_task.check_spec_refs
                    or row.engineering_scope_ref not in current_task.engineering_scope_refs):
                raise TaskConflict('Inspection recovery borrows observations from another task, design, method or scope')
            received_evidence = []
            for basis in row.evidence_refs:
                evidence_row = read(basis, EvidenceRecord, context.business_time)
                if evidence_row.source_kind == 'synthetic' or evidence_row.basis_kind != 'observed':
                    continue
                if evidence_row.effective_window is not None and not evidence_row.effective_window.contains(context.business_time):
                    return 'unavailable', None
                received_evidence.append(evidence_row.model_dump(mode='json'))
            if not received_evidence:
                return 'unavailable', None
            received_observations.append(dict(observation=row.model_dump(mode='json'), receipt_evidence=received_evidence))
    evidence = []
    for ref in current_task.evidence_refs:
        row = read(ref, EvidenceRecord, context.business_time)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Inspection recovery requires observed native task authorization')
        if row.effective_window is not None and not row.effective_window.contains(context.business_time):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    if not evidence:
        return 'unavailable', None
    current_result = None
    if not terminal:
        current_result = inspect_and_support(context, current_input, reading)
        if current_result.get('kind') != 'completed':
            return 'waiting', None
        contract.validate_decision(current_input, current_result['payload'])

    def dump(version):
        return {name: ({str(key): row.model_dump(mode='json') for key, row in value.items()}
            if isinstance(value, dict) else value.model_dump(mode='json')) for name, value in version.items()}

    resolution = dict(schema_version=('engineer-inspection-authorization-resolution.v1' if code == AUTHORIZATION_CODE
        else 'engineer-inspection-observation-resolution.v1' if code == OBSERVATION_CODE
        else 'engineer-inspection-personnel-resolution.v1' if code == PERSONNEL_CODE
        else 'engineer-inspection-qualification-resolution.v1' if code == QUALIFICATION_CODE
        else 'engineer-inspection-equipment-resolution.v1' if code == EQUIPMENT_CODE
        else 'engineer-inspection-capacity-resolution.v1' if code == CAPACITY_CODE
        else 'engineer-inspection-design-change-resolution.v1' if code == CHANGE_CODE
        else 'engineer-inspection-investment-resolution.v1'), condition_code=code,
        history=history.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_sources=dump(old), current_sources=dump(current), evidence=evidence, sources=reading.evidence(),
        original_gate=contract.result_adapter.validate_python(original_gate).model_dump(mode='json'))
    if current_result is not None:
        resolution['current_result'] = contract.result_adapter.validate_python(current_result).model_dump(mode='json')
    if design_change_resolution is not None:
        resolution['independent_design_change'] = design_change_resolution
    if personnel_resolution is not None:
        resolution['equipment_authentication' if code == EQUIPMENT_CODE else 'capacity_authentication'
            if code == CAPACITY_CODE else 'personnel_authentication'] = personnel_resolution
    if code == CAPACITY_CODE:
        resolution['historical_comparisons'] = historical_comparisons
    if investment_resolution is not None:
        resolution['investment_authentication'] = investment_resolution
        if terminal:
            resolution['disposition'] = 'actual_original_work_fully_invested_without_inspection_completion'
    if code == OBSERVATION_CODE:
        resolution['received_observations'] = received_observations
    if validate_relation(source_identity=deepcopy(source), condition_code=code, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Inspection recovery lacks independent native task authorization and remaining-duty validation')
    return 'ready', resolution


def _read_inspection_design_change(check, selected, old, current, *, read, validate_relation):
    source, context, original = check.source['identity'], selected.context, selected.original_context
    task, current_task = old['task'], current['task']
    if task.choice != 'respond' or current_task.choice != 'respond' or task.response_issue_ref is None:
        raise TaskConflict('Inspection design change recovery requires its original technical response task')
    before = read(task.response_issue_ref, EngineerInspectionIssueView, original.business_time)
    query = read(selected.history_ref, EngineerInspectionIssueView, context.business_time)
    if (tuple(check.condition.object_refs) != (before.ref, old['design'].ref)
            or query.ref != current_task.response_issue_ref or before.ref.key()[:2] != query.ref.key()[:2]
            or before.ref == query.ref and before != query or not before.response_changes_design
            or before.task_ref != task.ref or query.task_ref != current_task.ref
            or before.applicable_design_ref != old['design'].ref or query.applicable_design_ref != current['design'].ref
            or before.design_content_sha256 != old['design'].content_sha256
            or query.design_content_sha256 != current['design'].content_sha256
            or before.sender_id != query.sender_id
            or before.response_requirement_ref.key()[:2] != query.response_requirement_ref.key()[:2]
            or before.engineering_scope_ref.key()[:2] != query.engineering_scope_ref.key()[:2]):
        raise TaskConflict('Inspection recovery replaces the original technical query, sender, scope or response requirement')
    if query.response_changes_design or query.design_change_ref is None:
        return 'waiting', query, None
    linkage = read(query.design_change_ref, EngineerInspectionDesignChangeView, context.business_time)
    if (linkage.run_id != source['run_id'] or linkage.organization_id != source['organization_id']
            or linkage.scope != context.scope or linkage.original_task_ref != task.ref or linkage.current_task_ref != current_task.ref
            or linkage.original_query_ref != before.ref or linkage.current_query_ref != query.ref
            or linkage.original_design_ref != old['design'].ref or linkage.current_design_ref != current['design'].ref
            or linkage.original_content_sha256 != old['design'].content_sha256
            or linkage.current_content_sha256 != current['design'].content_sha256):
        raise TaskConflict('Inspection design change linkage substitutes original/current task, query or design content')
    if linkage.status != 'registered' or linkage.as_of != context.business_time:
        return 'waiting', query, None
    if not linkage.effective_window.contains(context.business_time):
        return 'unavailable', query, None
    registration, deliverable = linkage.registration, linkage.deliverable
    if (registration.run_id != source['run_id'] or registration.registration_status != 'registered'
            or registration.prior_deliverable_ref != old['design'].ref
            or registration.original_content_sha256 != old['design'].content_sha256
            or registration.deliverable_ref != current['design'].ref or registration.deliverable_ref == registration.prior_deliverable_ref
            or registration.deliverable_sha256 != content_digest(deliverable)
            or registration.deliverable_content_sha256 != linkage.current_content_sha256
            or deliverable.ref != registration.deliverable_ref or deliverable.task_ref != registration.task_ref
            or deliverable.appointment_ref != registration.appointment_ref
            or deliverable.author_organization_id != registration.organization_id
            or deliverable.author_action_id != 'ENGINEER-A09' or deliverable.status != 'compiled'
            or deliverable.issue_coverage != 'complete' or deliverable.dependency_refs != registration.dependency_refs
            or deliverable.unresolved_issue_refs != registration.unresolved_issue_refs
            or not scope_covers(registration.scope, context.scope) or not scope_covers(deliverable.scope, context.scope)):
        raise TaskConflict('Inspection recovery lacks an actual separate A09 revision registration with its complete original lineage')
    fields = ('ref', 'content_sha256', 'discipline_codes', 'valid_for_uses', 'invalidated_uses', 'status',
        'author_organization_id', 'author_actor_id', 'author_function_ref', 'author_authority_ref', 'author_action_id', 'authored_at')
    if any(getattr(current['design'], name) != getattr(deliverable, name) for name in fields):
        raise TaskConflict('Inspection applicable design does not match the independently registered actual revision')
    if not deliverable.effective_window.contains(context.business_time):
        return 'unavailable', query, None
    if any(getattr(registration, name) != getattr(deliverable, name) for name in
            ('author_actor_id', 'author_function_ref', 'author_authority_ref')):
        raise TaskConflict('Inspection revision registration and actual deliverable disagree on original authorship')
    if registration.registered_at is None:
        return 'waiting', query, None
    points = [registration.authored_at, deliverable.authored_at, registration.registered_at,
        registration.available_at, linkage.available_at, context.business_time]
    if (any(point.clock_ref != context.business_time.clock_ref for point in points)
            or any(left.offset > right.offset for left, right in zip(points, points[1:]))
            or deliverable.available_at.clock_ref != context.business_time.clock_ref
            or not registration.registered_at.offset <= deliverable.available_at.offset <= linkage.available_at.offset):
        raise TaskConflict('Inspection independent revision lacks actual production, registration and receipt chronology')
    grant = read(registration.author_authority_ref, Authorization, context.business_time)
    assignment = read(registration.author_function_ref, RoleAssignment, context.business_time)
    if (grant.actor_id != registration.author_actor_id or grant.function_ref != registration.author_function_ref
            or grant.organization_id != registration.organization_id or assignment.role != 'Engineer'
            or 'ENGINEER-A09' not in grant.action_ids or not any(scope_covers(scope, context.scope) for scope in grant.scopes)
            or not grant.validity.contains(registration.authored_at)):
        raise TaskConflict('Inspection design change cannot borrow A08 reply authority for an independent A09 revision')
    evidence = []
    for ref in linkage.evidence_refs:
        row = read(ref, EvidenceRecord, context.business_time)
        if row.source_kind != 'synthetic' and row.basis_kind == 'observed':
            if row.effective_window is None or row.effective_window.contains(context.business_time):
                evidence.append(row.model_dump(mode='json'))
    if not evidence:
        return 'unavailable', query, None
    resolution = dict(schema_version='engineer-inspection-independent-revision-resolution.v1',
        original_query=before.model_dump(mode='json'), current_query=query.model_dump(mode='json'),
        native_linkage=linkage.model_dump(mode='json'), independent_authority=grant.model_dump(mode='json'),
        independent_function=assignment.model_dump(mode='json'), evidence=evidence, sources=selected.reading.evidence())
    if validate_relation(source_identity=deepcopy(source), condition_code=CHANGE_CODE, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=selected.reading) is not True:
        raise TaskConflict('Inspection recovery lacks independent native A09 execution, issue/obligation and current-use authentication')
    return 'ready', query, resolution


def engineer_original_inspection_profile(read_current, validate_relation, condition_code=AUTHORIZATION_CODE):
    if condition_code not in _CODES or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Inspection recovery requires actual guarded task sources and native authority validation')
    def evaluate(check):
        if check.condition.condition_code != condition_code:
            raise TaskConflict('Inspection condition profile substitutes the original wait branch')
        selected = read_current(deepcopy(check))
        try:
            return _check_engineer_inspection_history(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()
    return ConditionProfile('ENGINEER-A08', condition_code, '1', frozenset({'dependency_change'}), evaluate)
