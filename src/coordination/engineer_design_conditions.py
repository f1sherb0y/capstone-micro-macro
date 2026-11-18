"""Recover original professional design authorization without clearing work history."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.catalog import ActionContract
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.engineer_design_objects import (
    EngineerDesignTaskView, EngineerDesignProfileView, ArchitectDesignLimitView,
    EngineerAppointmentView, EngineerPlanningWorkFactView, QSCostBriefView,
    EngineerDesignSubmissionView,
)
from src.actions.contracts.engineer_submission_objects import (
    EngineerDesignRegistrationView, EngineerRevisionRegistrationView, EngineerSubmissionDeliverableView,
)
from src.actions.contracts.engineer_research_objects import EngineerResearchTargetView
from src.actions.contracts.references import ActionReadView
from src.actions.roles.engineer_design import (
    compile_professional_design, recheck_original_engineer_design_candidate_limit, recheck_original_engineer_design_work_limit,
    recheck_original_engineer_design_submission,
)
from src.actions.roles.qs_change import content_digest
from src.coordination.contractor_closeout_conditions import ContractorCloseoutConditionReading
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest


AUTHORIZATION_CODE = 'original_professional_task_waiting_or_closed'
CANDIDATE_CODE = 'original_professional_candidate_revision_limit_reached'
WORK_CODE = 'original_professional_work_limit_reached'
SUBMISSION_CODE = 'query_original_professional_submission_before_reproduction'
_REF_KINDS = {AUTHORIZATION_CODE: ('Task',), CANDIDATE_CODE: ('DesignLimit',), WORK_CODE: ('DesignLimit',),
    SUBMISSION_CODE: ('Submission',)}


@dataclass(frozen=True)
class EngineerDesignConditionReading(ContractorCloseoutConditionReading):
    contract: ActionContract | None = None


def check_engineer_design_authorization(check, selected, validate_relation):
    if check.condition.condition_code != AUTHORIZATION_CODE:
        raise TaskConflict('Professional design authorization checker substitutes the original wait branch')
    return _check_engineer_design_history(check, selected, validate_relation)


def check_engineer_design_submission(check, selected, validate_relation, *, terminal=False):
    if check.condition.condition_code != SUBMISSION_CODE:
        raise TaskConflict('Professional design submission checker substitutes the original wait branch')
    return _check_engineer_design_history(check, selected, validate_relation, terminal=terminal)


def _check_engineer_design_history(check, selected, validate_relation, *, terminal=False, action_id='ENGINEER-A05'):
    if action_id not in {'ENGINEER-A05', 'ENGINEER-A09'}:
        raise TaskConflict('Professional design recovery requires a declared original action and wait route')
    source = check.source['identity']
    code = check.condition.condition_code
    if (source['action_id'] != action_id or source['role'] != 'Engineer' or source['purpose'] != 'action'
            or code not in _REF_KINDS or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != _REF_KINDS.get(code)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, EngineerDesignConditionReading) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)
            or terminal and code != SUBMISSION_CODE):
        raise TaskConflict('Professional design recovery requires the original private task authorization wait')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id']
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and (raw != current_raw or context.actor_id != original.actor_id or context.function_ref != original.function_ref)
            or context.run_id != source['run_id'] or context.contract_ref != original.contract_ref
            or context.contract_ref.id != action_id or context.scope != original.scope or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Professional design recovery substitutes original snapshot, scope, time or current read authority')
    reading.check_method_context(context, action_id)
    contract = selected.contract
    if not isinstance(contract, ActionContract) or contract.action_id != action_id or contract.role != 'Engineer':
        raise TaskConflict('Professional design recovery lacks the actual registered original action contract')
    original_action_input, current_action_input = contract.validate_input(raw), contract.validate_input(current_raw)
    original_input, current_input = original_action_input, current_action_input
    revision_sources = None
    if action_id == 'ENGINEER-A09':
        from src.actions.roles.engineer_change import (
            handle_professional_change, recheck_original_engineer_change_candidate_limit, recheck_original_engineer_change_work_limit,
            recheck_original_engineer_change_submission,
        )
        from src.coordination.engineer_change_design_conditions import prepare_engineer_change_design_inputs
        original_input, current_input, revision_sources = prepare_engineer_change_design_inputs(selected,
            original_action_input, current_action_input)

    def physical(refs):
        result = {ref.key()[:2]: ref for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('Professional design recovery aliases physical inputs or work histories')
        return result

    def read(ref, schema, at):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Professional design recovery lacks exact typed original/current sources')
        available = getattr(row, 'available_at', None)
        if available is not None and (available.clock_ref != at.clock_ref or available.offset > at.offset):
            raise TaskConflict('Professional design recovery introduces sources unavailable at their original/query time')
        return row

    versions = []
    for values, at in ((original_input, original.business_time), (current_input, context.business_time)):
        if terminal:
            at = original.business_time
        task = read(values.task_ref, EngineerDesignTaskView, at)
        brief = read(values.brief_ref, QSCostBriefView, at)
        profile = read(values.engineering_profile_ref, EngineerDesignProfileView, at)
        appointment = read(task.appointment_ref, EngineerAppointmentView, at)
        limit = read(task.design_limit_ref, ArchitectDesignLimitView, at)
        if (values.scope != context.scope or task.organization_id != source['organization_id']
                or appointment.provider_organization_id != source['organization_id'] or task.brief_ref != brief.ref
                or task.engineering_profile_ref != profile.ref or limit.appointment_ref != appointment.ref):
            raise TaskConflict('Professional design recovery replaces original task, engagement, brief, profile or limits')
        facts = {key: read(ref, EngineerPlanningWorkFactView, at)
            for key, ref in physical(list({ref.key(): ref for ref in (*task.work_fact_refs, *limit.work_fact_refs)}.values())).items()}
        versions.append(dict(task=task, brief=brief, profile=profile, appointment=appointment, limit=limit, facts=facts))
    old, current = versions
    for name in ('task', 'brief', 'profile', 'appointment', 'limit'):
        before, after = old[name], current[name]
        if before.ref.key()[:2] != after.ref.key()[:2] or before.ref == after.ref and before != after:
            raise TaskConflict('Professional design recovery replaces physical inputs or rewrites an immutable version')
    task, current_task = old['task'], current['task']
    if code == AUTHORIZATION_CODE:
        if (task.ref != check.condition.object_refs[0] or current_task.ref != selected.history_ref
                or task.status == 'authorized'):
            raise TaskConflict('Professional design task does not reproduce the original authorization wait')
        # The real authorization gate precedes appointment limits, methods and design production.
        if action_id == 'ENGINEER-A09':
            original_gate = handle_professional_change(original, original_action_input, reading)
        else:
            original_gate = compile_professional_design(original, original_input, reading)
    elif code == SUBMISSION_CODE:
        if old['limit'].prior_submission_ref != check.condition.object_refs[0]:
            raise TaskConflict('Professional submission recovery substitutes the original engagement query')
        original_gate = (recheck_original_engineer_change_submission(original, original_action_input, reading) if action_id == 'ENGINEER-A09'
            else recheck_original_engineer_design_submission(original, original_input, reading))
    else:
        if old['limit'].ref != check.condition.object_refs[0] or current['limit'].ref != selected.history_ref:
            raise TaskConflict('Professional limit recovery substitutes the original engagement limit')
        if action_id == 'ENGINEER-A09':
            original_gate = (recheck_original_engineer_change_candidate_limit if code == CANDIDATE_CODE
                else recheck_original_engineer_change_work_limit)(original, original_action_input, reading)
        else:
            original_gate = (recheck_original_engineer_design_candidate_limit if code == CANDIDATE_CODE
                else recheck_original_engineer_design_work_limit)(original, original_input, reading)
    if (original_gate.get('resume_condition', {}).get('condition_code') != code
            or original_gate.get('resume_condition', {}).get('object_refs') != list(check.condition.object_refs)):
        raise TaskConflict('Professional task wait differs from the original processor evaluation')
    if task.status == 'closed' and current_task.status != 'closed':
        raise TaskConflict('Professional design recovery cannot reopen an original closed task')
    for name in ('scope', 'choice', 'discipline_code', 'function_code', 'requested_use', 'required_effort'):
        if getattr(task, name) != getattr(current_task, name):
            raise TaskConflict('Professional design recovery changes original purpose, discipline, function, use or effort')
    for name in ('evidence_input_refs', 'method_result_refs', 'check_spec_refs', 'question_refs', 'work_fact_refs'):
        if not set(physical(getattr(task, name))) <= set(physical(getattr(current_task, name))):
            raise TaskConflict('Professional design recovery drops original inputs, checks, questions or investments')
    before_targets = physical([row.check_spec_ref for row in task.check_result_targets])
    after_targets = physical([row.check_spec_ref for row in current_task.check_result_targets])
    before_results = {row.check_spec_ref.key()[:2]: row.calculation_ref for row in task.check_result_targets}
    after_results = {row.check_spec_ref.key()[:2]: row.calculation_ref for row in current_task.check_result_targets}
    if (not set(before_targets) <= set(after_targets)
            or any(before_results[key].key()[:2] != after_results[key].key()[:2] for key in before_targets)):
        raise TaskConflict('Professional design recovery substitutes original check/result targets')
    if task.draft is not None:
        before, after = task.draft, current_task.draft
        if (after is None or before.scope != after.scope
                or before.brief_ref.key()[:2] != after.brief_ref.key()[:2]
                or before.engineering_profile_ref.key()[:2] != after.engineering_profile_ref.key()[:2]
                or (before.parent_option_ref is None) != (after.parent_option_ref is None)
                or before.parent_option_ref is not None and before.parent_option_ref.key()[:2] != after.parent_option_ref.key()[:2]):
            raise TaskConflict('Professional design recovery replaces the original finite draft or parent option')
        for name in ('selected_parameter_refs', 'method_result_refs', 'evidence_refs', 'interface_refs', 'quantity_basis_refs'):
            if not set(physical(getattr(before, name))) <= set(physical(getattr(after, name))):
                raise TaskConflict('Professional design recovery drops original draft parameters or source histories')
    before_parent, after_parent = original_input.prior_option_ref, current_input.prior_option_ref
    if ((before_parent is None) != (after_parent is None)
            or before_parent is not None and before_parent.key()[:2] != after_parent.key()[:2]):
        raise TaskConflict('Professional design recovery substitutes its original revision parent')
    before_appointment, after_appointment = old['appointment'], current['appointment']
    for name in ('scope', 'provider_id', 'provider_organization_id', 'client_id', 'client_organization_id',
            'payer_id', 'payer_organization_id', 'relation'):
        if getattr(before_appointment, name) != getattr(after_appointment, name):
            raise TaskConflict('Professional design recovery changes original service parties or scope')
    for name in ('terms_ref', 'service_relationship_ref', 'capability_ref', 'independence_check_ref'):
        before, after = getattr(before_appointment, name), getattr(after_appointment, name)
        if before is not None and (after is None or before.key()[:2] != after.key()[:2]):
            raise TaskConflict('Professional design recovery replaces original engagement or professional authority history')
    before_limit, after_limit = old['limit'], current['limit']
    for name in ('option_refs', 'work_fact_refs'):
        if not set(physical(getattr(before_limit, name))) <= set(physical(getattr(after_limit, name))):
            raise TaskConflict('Professional design recovery erases original engagement options or investments')
    if (after_limit.revision_count < before_limit.revision_count or after_limit.version_branch_count < before_limit.version_branch_count
            or before_limit.maximum_effort.unit != after_limit.maximum_effort.unit
            or before_limit.maximum_cost.currency != after_limit.maximum_cost.currency
            or before_limit.prior_submission_ref is not None and (after_limit.prior_submission_ref is None
                or before_limit.prior_submission_ref.key()[:2] != after_limit.prior_submission_ref.key()[:2])
                and not (code == SUBMISSION_CODE and after_limit.prior_submission_ref is None)):
        raise TaskConflict('Professional design recovery resets engagement limits, units or submission history')
    if not set(old['facts']) <= set(current['facts']):
        raise TaskConflict('Professional design recovery loses original actual work history')
    for key, before in old['facts'].items():
        after = current['facts'][key]
        if (before.organization_id != source['organization_id'] or after.organization_id != source['organization_id']
                or before.task_ref.key()[:2] != after.task_ref.key()[:2]
                or any(getattr(before, name) != getattr(after, name) for name in ('investment_key', 'effort', 'internal_cost', 'window'))
                or before.status == 'committed' and after.status != 'committed'
                or before.ref == after.ref and before != after):
            raise TaskConflict('Professional design recovery rewrites actual effort, cost or investment slices')
    if not terminal and current_task.status != 'authorized':
        return 'waiting', None
    if code == AUTHORIZATION_CODE and current_task.ref == task.ref:
        raise TaskConflict('Professional design recovery requires an actual new authorized task version')
    history = current_task if code == AUTHORIZATION_CODE else after_limit
    submission_query = None
    if code == SUBMISSION_CODE:
        status, history, submission_query = _read_original_professional_submission(check, selected, old, current,
            read=read, physical=physical, terminal=terminal, action_id=action_id, revision_sources=revision_sources)
        if status != 'ready':
            return status, None
    evidence = []
    for ref in history.evidence_refs:
        row = read(ref, EvidenceRecord, context.business_time)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Professional design recovery requires observed native task/limit authorization')
        if row.effective_window is not None and not row.effective_window.contains(context.business_time):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    if not evidence:
        return 'unavailable', None
    limit_authorization = None
    if code in {CANDIDATE_CODE, WORK_CODE}:
        fields = (('maximum_candidates', 'maximum_versions_branches', 'maximum_revisions') if code == CANDIDATE_CODE
            else ('maximum_effort', 'maximum_cost'))
        if history.ref == before_limit.ref:
            raise TaskConflict('Professional limit recovery requires an actual new authorized limit version')

        def amount(value):
            return value.model_dump(mode='json') if hasattr(value, 'model_dump') else value

        changes = {name: dict(original=amount(getattr(before_limit, name)), current=amount(getattr(after_limit, name)))
            for name in fields if getattr(before_limit, name) != getattr(after_limit, name)}
        if not changes:
            return 'waiting', None
        limit_authorization = dict(schema_version='engineer-design-limit-authorization-resolution.v1',
            original_limit=before_limit.model_dump(mode='json'), current_limit=after_limit.model_dump(mode='json'),
            changes=changes, evidence=evidence, sources=reading.evidence())
        if revision_sources is not None:
            limit_authorization['revision_sources'] = revision_sources
        if validate_relation(source_identity=deepcopy(source), condition_code=code, resolution=deepcopy(limit_authorization),
                context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Professional limit recovery lacks independent native approval of revised engagement caps')
    current_result = None
    if not terminal:
        current_result = (handle_professional_change(context, current_action_input, reading) if action_id == 'ENGINEER-A09'
            else compile_professional_design(context, current_input, reading))
        if current_result.get('kind') != 'completed':
            return 'waiting', None
        contract.validate_decision(current_action_input, current_result['payload'])

    def dump(version):
        return {name: ({str(key): row.model_dump(mode='json') for key, row in value.items()}
            if isinstance(value, dict) else value.model_dump(mode='json')) for name, value in version.items()}

    resolution = dict(schema_version=('engineer-design-authorization-resolution.v1' if code == AUTHORIZATION_CODE
        else 'engineer-design-candidate-limit-resolution.v1' if code == CANDIDATE_CODE
        else 'engineer-design-submission-resolution.v1' if code == SUBMISSION_CODE
        else 'engineer-design-work-limit-resolution.v1'), condition_code=code,
        history=history.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_sources=dump(old), current_sources=dump(current), evidence=evidence, sources=reading.evidence(),
        original_gate=contract.result_adapter.validate_python(original_gate).model_dump(mode='json'))
    if current_result is not None:
        resolution['current_result'] = contract.result_adapter.validate_python(current_result).model_dump(mode='json')
    if revision_sources is not None:
        resolution['schema_version'] = ('engineer-change-design-authorization-resolution.v1' if code == AUTHORIZATION_CODE
            else 'engineer-change-design-candidate-limit-resolution.v1' if code == CANDIDATE_CODE
            else 'engineer-change-design-work-limit-resolution.v1' if code == WORK_CODE
            else 'engineer-change-design-submission-resolution.v1')
        resolution['revision_sources'] = revision_sources
    if submission_query is not None:
        resolution['submission_query'] = submission_query
        resolution['disposition'] = 'actual_prior_submission_status_observed'
    if limit_authorization is not None:
        resolution['limit_authorization'] = limit_authorization
    if validate_relation(source_identity=deepcopy(source), condition_code=code, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Professional design recovery lacks independent native authorization and remaining-duty validation')
    return 'ready', resolution


def _read_original_professional_submission(check, selected, old, current, *, read, physical, terminal,
        action_id='ENGINEER-A05', revision_sources=None):
    source, context, original = check.source['identity'], selected.context, selected.original_context
    query_schema, registration_schema = EngineerDesignSubmissionView, EngineerDesignRegistrationView
    if action_id == 'ENGINEER-A09':
        from src.actions.contracts.engineer_change_objects import EngineerRevisionSubmissionView
        query_schema, registration_schema = EngineerRevisionSubmissionView, EngineerRevisionRegistrationView
    before = read(old['limit'].prior_submission_ref, query_schema, original.business_time)
    history = read(selected.history_ref, query_schema, context.business_time)
    if (history.ref.key()[:2] != before.ref.key()[:2] or before.ref == history.ref and before != history):
        raise TaskConflict('Professional query replaces its original physical or immutable submission')
    excluded = {'ref', 'status', 'available_at', 'effective_window', 'evidence_refs', 'queried_at', 'registration_refs', 'option_ref'}
    if action_id == 'ENGINEER-A09':
        excluded.add('registered_deliverables')
    if (before.model_dump(exclude=excluded) != history.model_dump(exclude=excluded)
            or history.run_id != source['run_id'] or history.organization_id != source['organization_id']
            or history.appointment_ref.key()[:2] != old['appointment'].ref.key()[:2] or history.scope != context.scope
            or before.status in {'registered', 'rejected', 'confirmed_uncommitted'} and history.status != before.status
            or not set(physical(before.registration_refs)) <= set(physical(history.registration_refs))
            or before.option_ref is not None and (history.option_ref is None or before.option_ref.key()[:2] != history.option_ref.key()[:2])):
        raise TaskConflict('Professional query rewrites original command, payload, production or registration history')
    for version, at in ((before, original.business_time), (history, context.business_time)):
        if (version.queried_at.clock_ref != at.clock_ref or version.available_at.clock_ref != at.clock_ref
                or not version.queried_at.offset <= version.available_at.offset <= at.offset):
            raise TaskConflict('Professional query lacks an actual received observation at its original/current time')
    if history.queried_at != context.business_time or not history.effective_window.contains(context.business_time):
        return 'unavailable', history, None
    embedded_deliverables = {}
    if action_id == 'ENGINEER-A09':
        from src.actions.contracts.engineer_change_objects import EngineerChangeBasisView
        if revision_sources is None:
            raise TaskConflict('Revision query lacks the actual original A09 source lineage')
        origin = revision_sources['original']
        if (history.issue_ref.key()[:2] != (origin['issue']['ref']['kind'], origin['issue']['ref']['id'])
                or history.obligation_ref.key()[:2] != (origin['obligation']['ref']['kind'], origin['obligation']['ref']['id'])
                or history.prior_deliverable_ref != Reference.model_validate(origin['parent']['ref'])
                or history.original_content_sha256 != origin['parent']['content_sha256']):
            raise TaskConflict('Revision query substitutes original issue, obligation, parent design or content')
        basis = read(history.change_basis_ref, EngineerChangeBasisView, original.business_time)
        if (basis.issue_ref != history.issue_ref or basis.obligation_ref != history.obligation_ref
                or basis.prior_deliverable_ref != history.prior_deliverable_ref
                or basis.original_content_sha256 != history.original_content_sha256
                or basis.instruction_ref != history.instruction_ref or basis.draft_sha256 != content_digest(history.draft)):
            raise TaskConflict('Revision query changes its actually authored draft, instruction or change basis')
        physical([row.ref for row in history.registered_deliverables])
        embedded_deliverables = {row.ref.key(): row for row in history.registered_deliverables}
        for row in before.registered_deliverables:
            if embedded_deliverables.get(row.ref.key()) != row:
                raise TaskConflict('Revision query drops or rewrites an already observed native deliverable')
    task = read(history.source_task_ref, EngineerDesignTaskView, original.business_time)
    if (task.organization_id != source['organization_id'] or task.choice != 'produce' or task.scope != history.scope
            or task.appointment_ref != history.appointment_ref or task.brief_ref != history.brief_ref
            or task.engineering_profile_ref != history.engineering_profile_ref or task.draft != history.draft):
        raise TaskConflict('Professional query does not retain its original authored task and complete draft')
    before_rows = {key: read(ref, registration_schema, original.business_time)
        for key, ref in physical(before.registration_refs).items()}
    rows, deliverables, successes = [], [], []
    for ref in history.registration_refs:
        row = read(ref, registration_schema, context.business_time)
        if (row.run_id != history.run_id or row.organization_id != history.organization_id or row.scope != history.scope
                or row.task_ref != task.ref or row.appointment_ref != task.appointment_ref or row.draft != history.draft
                or row.author_authority_ref != task.authority_ref
                or any(getattr(row, name) != getattr(history, name) for name in
                    ('task_sha256', 'record_sha256', 'result_sha256', 'source_reading_sha256'))):
            raise TaskConflict('Professional registration query changes original draft, author or production provenance')
        if action_id == 'ENGINEER-A09' and any(getattr(row, name) != getattr(history, name) for name in
                ('issue_ref', 'obligation_ref', 'prior_deliverable_ref', 'original_content_sha256', 'change_basis_ref', 'instruction_ref')):
            raise TaskConflict('Revision registration changes original issue, obligation, parent, basis or instruction')
        previous = before_rows.get(row.ref.key()[:2])
        if previous is not None:
            mutable = {'ref', 'registration_status', 'registered_at', 'available_at', 'effective_window', 'evidence_refs',
                'deliverable_sha256', 'deliverable_content_sha256'}
            if (previous.ref == row.ref and previous != row
                    or previous.model_dump(exclude=mutable) != row.model_dump(exclude=mutable)
                    or previous.registration_status in {'registered', 'failed', 'rejected'} and previous.registration_status != row.registration_status
                    or previous.registered_at is not None and previous.registered_at != row.registered_at
                    or previous.deliverable_sha256 is not None and previous.deliverable_sha256 != row.deliverable_sha256
                    or previous.deliverable_content_sha256 is not None and previous.deliverable_content_sha256 != row.deliverable_content_sha256):
                raise TaskConflict('Professional query rewrites an immutable or terminal native registration')
        if (row.authored_at.clock_ref != context.business_time.clock_ref
                or not task.available_at.offset <= row.authored_at.offset <= row.available_at.offset):
            raise TaskConflict('Professional registration lacks original production chronology')
        rows.append(row.model_dump(mode='json'))
        if row.registration_status != 'registered':
            continue
        if (row.registered_at is None or row.registered_at.clock_ref != context.business_time.clock_ref
                or not row.authored_at.offset <= row.registered_at.offset <= row.available_at.offset
                or not row.effective_window.contains(context.business_time)):
            raise TaskConflict('Professional query lacks actual received native registration chronology')
        deliverable = (embedded_deliverables.get(row.deliverable_ref.key()) if action_id == 'ENGINEER-A09'
            else read(row.deliverable_ref, EngineerSubmissionDeliverableView, context.business_time))
        if not isinstance(deliverable, EngineerSubmissionDeliverableView):
            raise TaskConflict('Revision registration query lacks its complete actual native deliverable')
        if (content_digest(deliverable) != row.deliverable_sha256 or deliverable.content_sha256 != row.deliverable_content_sha256
                or deliverable.task_ref != task.ref or deliverable.appointment_ref != task.appointment_ref
                or deliverable.scope != history.scope or deliverable.author_organization_id != source['organization_id']
                or deliverable.author_actor_id != row.author_actor_id or deliverable.author_function_ref != row.author_function_ref
                or deliverable.author_authority_ref != row.author_authority_ref or deliverable.author_action_id != action_id
                or task.discipline_code not in deliverable.discipline_codes or deliverable.issue_coverage != 'complete'
                or deliverable.dependency_refs != row.dependency_refs or deliverable.unresolved_issue_refs != row.unresolved_issue_refs
                or deliverable.authored_at.clock_ref != context.business_time.clock_ref
                or not row.authored_at.offset <= deliverable.authored_at.offset <= row.registered_at.offset <= deliverable.available_at.offset):
            raise TaskConflict('Professional query lacks its actual original registered deliverable, issues or dependencies')
        physical(deliverable.dependency_refs)
        physical(deliverable.unresolved_issue_refs)
        successes.append(row)
        deliverables.append(deliverable.model_dump(mode='json'))
    if action_id == 'ENGINEER-A09' and set(embedded_deliverables) != {row.deliverable_ref.key() for row in successes}:
        raise TaskConflict('Revision query adds unregistered or omits actually registered native deliverables')
    if history.status in {'pending', 'unknown'}:
        return 'waiting', history, None
    option = None
    if history.status == 'registered':
        if len(successes) != 1 or any(row['registration_status'] in {'pending', 'unknown'} for row in rows):
            return 'waiting', history, None
        if not terminal and (task.ref.key()[:2] == current['task'].ref.key()[:2] or history.draft == current['task'].draft):
            return 'waiting', history, None
        if history.option_ref is not None:
            option = read(history.option_ref, EngineerResearchTargetView, context.business_time)
            registered = successes[0]
            if (option.brief_ref != history.brief_ref or option.author_action_id != action_id
                    or option.author_authority_ref != registered.author_authority_ref
                    or option.author_actor_id != registered.author_actor_id or option.author_function_ref != registered.author_function_ref):
                raise TaskConflict('Professional query substitutes the registered candidate accounting identity')
        if not terminal:
            if option is None:
                return 'unavailable', history, None
            if option.ref.key()[:2] not in physical(current['limit'].option_refs):
                raise TaskConflict('Professional continuation omits its actually registered prior candidate')
    elif history.option_ref is not None or any(row['registration_status'] not in {'failed', 'rejected'} for row in rows):
        return 'waiting', history, None
    query = dict(original=before.model_dump(mode='json'), current=history.model_dump(mode='json'),
        production_task=task.model_dump(mode='json'), registrations=rows, registered_deliverables=deliverables,
        registered_option=None if option is None else option.model_dump(mode='json'))
    return 'ready', history, query


def engineer_original_design_profile(read_current, validate_relation, condition_code=AUTHORIZATION_CODE):
    if condition_code not in _REF_KINDS or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Professional design recovery requires actual guarded task sources and native authority validation')
    def evaluate(check):
        if check.condition.condition_code != condition_code:
            raise TaskConflict('Professional design condition profile substitutes its original wait branch')
        selected = read_current(deepcopy(check))
        try:
            return _check_engineer_design_history(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()
    return ConditionProfile('ENGINEER-A05', condition_code, '1', frozenset({'dependency_change'}), evaluate)
