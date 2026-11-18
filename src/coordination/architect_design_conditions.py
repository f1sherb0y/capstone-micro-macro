"""Authenticate actual authorization of original design tasks without erasing their work history."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.catalog import ActionContract
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.architect_design_objects import (
    ArchitectDesignTaskView, ArchitectDesignProfileView, ArchitectDesignLimitView,
    ArchitectAppointmentView, ArchitectPlanningWorkFactView, QSCostBriefView,
    ArchitectDesignSubmissionView, ArchitectDesignRegistrationView, ArchitectResearchOptionView,
)
from src.actions.contracts.references import ActionReadView
from src.actions.roles.architect_design import (
    compile_design, recheck_original_architect_design_candidate_limit, recheck_original_architect_design_work_limit,
    recheck_original_architect_design_submission,
)
from src.methods.pricing import decimal_fraction
from src.coordination.contractor_closeout_conditions import ContractorCloseoutConditionReading
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest


AUTHORIZATION_CODE = 'original_design_task_not_authorized_for_work'
CANDIDATE_CODE = 'original_design_engagement_candidate_or_revision_limit_reached'
WORK_CODE = 'original_design_engagement_work_limit_reached'
SUBMISSION_CODE = 'query_original_design_submission_before_duplicate_production'
_REF_KINDS = {AUTHORIZATION_CODE: ('Task',), CANDIDATE_CODE: ('DesignLimit', 'Task'),
    WORK_CODE: ('DesignLimit',), SUBMISSION_CODE: ('Submission',)}
_CODES = set(_REF_KINDS)


@dataclass(frozen=True)
class ArchitectDesignConditionReading(ContractorCloseoutConditionReading):
    contract: ActionContract | None = None


def check_architect_design_authorization(check, selected, validate_relation):
    if check.condition.condition_code != AUTHORIZATION_CODE:
        raise TaskConflict('Design authorization checker substitutes the original wait branch')
    return _check_architect_design_history(check, selected, validate_relation)


def check_architect_design_submission(check, selected, validate_relation, *, terminal=False):
    if check.condition.condition_code != SUBMISSION_CODE:
        raise TaskConflict('Design submission checker substitutes the original wait branch')
    return _check_architect_design_history(check, selected, validate_relation, terminal=terminal)


def _check_architect_design_history(check, selected, validate_relation, *, terminal=False):
    source = check.source['identity']
    code = check.condition.condition_code
    if (source['action_id'] != 'ARCHITECT-A05' or source['role'] != 'Architect' or source['purpose'] != 'action'
            or code not in _CODES or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != _REF_KINDS.get(code)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, ArchitectDesignConditionReading) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)
            or terminal and code != SUBMISSION_CODE):
        raise TaskConflict('Design authorization recovery requires the original private design task wait')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id']
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and (raw != current_raw or context.actor_id != original.actor_id or context.function_ref != original.function_ref)
            or context.run_id != source['run_id'] or context.contract_ref != original.contract_ref
            or context.contract_ref.id != 'ARCHITECT-A05' or context.scope != original.scope or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Design authorization recovery substitutes original snapshot, time, scope or current read authority')
    reading.check_method_context(context, 'ARCHITECT-A05')
    contract = selected.contract
    if not isinstance(contract, ActionContract) or contract.action_id != 'ARCHITECT-A05' or contract.role != 'Architect':
        raise TaskConflict('Design recovery lacks its actual registered original A05 contract')
    original_input, current_input = contract.validate_input(raw), contract.validate_input(current_raw)

    def physical(refs):
        result = {ref.key()[:2]: ref for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('Design recovery aliases physical work, option or method histories')
        return result

    def read(ref, schema, at):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Design recovery lacks exact typed original/current sources')
        available = getattr(row, 'available_at', None)
        if available is not None and (available.clock_ref != at.clock_ref or available.offset > at.offset):
            raise TaskConflict('Design recovery introduces sources unavailable at their original/query time')
        return row

    versions = []
    for values, at in ((original_input, original.business_time), (current_input, context.business_time)):
        if terminal:
            at = original.business_time
        task = read(values.task_ref, ArchitectDesignTaskView, at)
        brief = read(values.brief_ref, QSCostBriefView, at)
        profile = read(values.design_profile_ref, ArchitectDesignProfileView, at)
        appointment = read(task.appointment_ref, ArchitectAppointmentView, at)
        limit = read(task.design_limit_ref, ArchitectDesignLimitView, at)
        if (values.scope != context.scope or task.organization_id != source['organization_id']
                or appointment.provider_organization_id != source['organization_id'] or task.brief_ref != brief.ref
                or task.design_profile_ref != profile.ref or limit.appointment_ref != appointment.ref):
            raise TaskConflict('Design recovery changes original private task, engagement, brief, catalog or work limits')
        facts = {key: read(ref, ArchitectPlanningWorkFactView, at)
            for key, ref in physical(list({ref.key(): ref for ref in (*task.work_fact_refs, *limit.work_fact_refs)}.values())).items()}
        versions.append(dict(task=task, brief=brief, profile=profile, appointment=appointment, limit=limit, facts=facts))
    old, current = versions
    for name in ('task', 'brief', 'profile', 'appointment', 'limit'):
        before, after = old[name], current[name]
        if before.ref.key()[:2] != after.ref.key()[:2] or before.ref == after.ref and before != after:
            raise TaskConflict('Design recovery replaces original physical inputs or rewrites an immutable version')
    task, current_task = old['task'], current['task']
    if code == AUTHORIZATION_CODE:
        if (task.ref != check.condition.object_refs[0] or current_task.ref != selected.history_ref
                or task.status == 'authorized'):
            raise TaskConflict('Original design task does not reproduce the original authorization wait')
        # This original processor gate precedes every method and design production branch.
        original_gate = compile_design(original, original_input, reading)
    elif code == SUBMISSION_CODE:
        if old['limit'].prior_submission_ref != check.condition.object_refs[0]:
            raise TaskConflict('Design submission query replaces the actual original engagement submission')
        original_gate = recheck_original_architect_design_submission(original, original_input, reading)
    else:
        if (tuple(check.condition.object_refs) != ((old['limit'].ref, task.ref) if code == CANDIDATE_CODE else (old['limit'].ref,))
                or selected.history_ref != current['limit'].ref):
            raise TaskConflict('Design limit recovery substitutes the original engagement limit or task history')
        original_gate = (recheck_original_architect_design_candidate_limit if code == CANDIDATE_CODE
            else recheck_original_architect_design_work_limit)(original, original_input, reading)
    if (original_gate.get('resume_condition', {}).get('condition_code') != code
            or original_gate.get('resume_condition', {}).get('object_refs') != list(check.condition.object_refs)):
        raise TaskConflict('Design task wait differs from its actual original authorized reading')
    if task.status == 'closed' and current_task.status != 'closed':
        raise TaskConflict('Design authorization recovery cannot reopen an original closed task')
    for name in ('scope', 'choice', 'requested_use', 'required_effort'):
        if getattr(task, name) != getattr(current_task, name):
            raise TaskConflict('Design authorization recovery changes original work purpose, use or measured effort')
    if len(current_task.drafts) < len(task.drafts):
        raise TaskConflict('Design authorization recovery drops original finite drafts')
    for before, after in zip(task.drafts, current_task.drafts):
        if (before.scope != after.scope or before.relation != after.relation
                or before.brief_ref.key()[:2] != after.brief_ref.key()[:2]
                or before.design_profile_ref.key()[:2] != after.design_profile_ref.key()[:2]
                or (before.parent_option_ref is None) != (after.parent_option_ref is None)
                or before.parent_option_ref is not None and before.parent_option_ref.key()[:2] != after.parent_option_ref.key()[:2]
                or not set(physical([row.variable_ref for row in before.variables])) <= set(physical([row.variable_ref for row in after.variables]))
                or not set(physical([row.coverage_ref for row in before.component_groups])) <= set(physical([row.coverage_ref for row in after.component_groups]))):
            raise TaskConflict('Design authorization recovery replaces original draft purpose, variables or component scope')
    for name in ('available_option_refs', 'professional_refs', 'cost_refs', 'method_result_refs',
            'work_fact_refs', 'required_input_refs', 'question_refs'):
        if not set(physical(getattr(task, name))) <= set(physical(getattr(current_task, name))):
            raise TaskConflict('Design authorization recovery drops original input or work histories')
    before_appointment, after_appointment = old['appointment'], current['appointment']
    for name in ('scope', 'provider_id', 'provider_organization_id', 'client_id', 'client_organization_id',
            'payer_id', 'payer_organization_id', 'relation'):
        if getattr(before_appointment, name) != getattr(after_appointment, name):
            raise TaskConflict('Design authorization recovery changes original service parties or scope')
    if before_appointment.terms_ref.key()[:2] != after_appointment.terms_ref.key()[:2]:
        raise TaskConflict('Design authorization recovery substitutes the original accepted terms')
    before_limit, after_limit = old['limit'], current['limit']
    for name in ('option_refs', 'work_fact_refs'):
        if not set(physical(getattr(before_limit, name))) <= set(physical(getattr(after_limit, name))):
            raise TaskConflict('Design recovery erases original engagement candidate or investment history')
    if (after_limit.revision_count < before_limit.revision_count or after_limit.version_branch_count < before_limit.version_branch_count
            or before_limit.maximum_effort.unit != after_limit.maximum_effort.unit
            or before_limit.maximum_cost.currency != after_limit.maximum_cost.currency
            or before_limit.prior_submission_ref is not None and (after_limit.prior_submission_ref is None
                or before_limit.prior_submission_ref.key()[:2] != after_limit.prior_submission_ref.key()[:2])
                and not (code == SUBMISSION_CODE and after_limit.prior_submission_ref is None)):
        raise TaskConflict('Design recovery resets original engagement limits, units or prior submission history')
    if not set(old['facts']) <= set(current['facts']):
        raise TaskConflict('Design authorization recovery loses original actual investment history')
    for key, before in old['facts'].items():
        after = current['facts'][key]
        if (before.organization_id != source['organization_id'] or after.organization_id != source['organization_id']
                or before.task_ref.key()[:2] != after.task_ref.key()[:2]
                or any(getattr(before, name) != getattr(after, name) for name in ('investment_key', 'effort', 'internal_cost', 'window'))
                or before.status == 'committed' and after.status != 'committed'
                or before.ref == after.ref and before != after):
            raise TaskConflict('Design recovery rewrites original actual effort, cost or investment slices')
    if current_task.status != 'authorized':
        return 'waiting', None
    if code == AUTHORIZATION_CODE and current_task.ref == task.ref:
        raise TaskConflict('Design recovery requires an actual new authorized task version')
    history = current_task if code == AUTHORIZATION_CODE else after_limit
    submission_query = None
    if code == SUBMISSION_CODE:
        before_submission = read(before_limit.prior_submission_ref, ArchitectDesignSubmissionView, original.business_time)
        history = read(selected.history_ref, ArchitectDesignSubmissionView, context.business_time)
        if (history.ref.key()[:2] != before_submission.ref.key()[:2]
                or before_submission.ref == history.ref and before_submission != history):
            raise TaskConflict('Design submission query replaces its original physical or immutable history')
        excluded = {'ref', 'status', 'available_at', 'effective_window', 'evidence_refs', 'queried_at', 'registration_refs'}
        if (before_submission.model_dump(exclude=excluded) != history.model_dump(exclude=excluded)
                or history.run_id != source['run_id'] or history.organization_id != source['organization_id']
                or history.appointment_ref.key()[:2] != old['appointment'].ref.key()[:2]
                or before_submission.status in {'registered', 'rejected', 'confirmed_uncommitted'} and history.status != before_submission.status
                or not set(physical(before_submission.registration_refs)) <= set(physical(history.registration_refs))):
            raise TaskConflict('Design submission query rewrites original command, payload, production or terminal disposition')
        for version, at in ((before_submission, original.business_time), (history, context.business_time)):
            if (version.queried_at.clock_ref != at.clock_ref or version.available_at.clock_ref != at.clock_ref
                    or version.queried_at.offset > version.available_at.offset or version.available_at.offset > at.offset):
                raise TaskConflict('Design submission query lacks an actual received query at its original/current time')
        if history.queried_at != context.business_time:
            return 'unavailable', None
        production_task = read(history.source_task_ref, ArchitectDesignTaskView, original.business_time)
        if (production_task.organization_id != source['organization_id'] or production_task.choice != 'produce'
                or production_task.scope != history.scope
                or production_task.appointment_ref != history.appointment_ref or production_task.brief_ref != history.brief_ref
                or production_task.design_profile_ref != history.design_profile_ref or production_task.drafts != history.drafts):
            raise TaskConflict('Design submission query does not retain its original finite authored task and drafts')
        registrations, options, indices = [], [], set()
        for ref in history.registration_refs:
            row = read(ref, ArchitectDesignRegistrationView, context.business_time)
            if (row.run_id != history.run_id or row.organization_id != history.organization_id
                    or row.source_task_ref != history.source_task_ref or row.scope != history.scope
                    or row.draft_index >= len(history.drafts) or row.draft_index in indices
                    or row.draft != history.drafts[row.draft_index]
                    or any(getattr(row, name) != getattr(history, name) for name in
                        ('task_sha256', 'record_sha256', 'result_sha256', 'source_reading_sha256'))):
                raise TaskConflict('Design query aliases registered draft slices or changes original production provenance')
            indices.add(row.draft_index)
            registrations.append(row.model_dump(mode='json'))
            if row.registration_status == 'registered':
                if (row.registered_at is None or row.authored_at.clock_ref != context.business_time.clock_ref
                        or row.registered_at.clock_ref != context.business_time.clock_ref
                        or not row.authored_at.offset <= row.registered_at.offset <= row.available_at.offset
                        or row.author_authority_ref != production_task.authority_ref):
                    raise TaskConflict('Design query lacks actual original authorship and native registration chronology')
                option = read(row.option_ref, ArchitectResearchOptionView, context.business_time)
                if (row.option_sha256 is None or task_digest(option.model_dump(mode='json')) != row.option_sha256
                        or option.brief_ref != history.brief_ref):
                    raise TaskConflict('Design query lacks its actual registered original option version')
                options.append(option.model_dump(mode='json'))
        if history.status in {'pending', 'unknown'}:
            return 'waiting', None
        if history.status == 'registered':
            if indices != set(range(len(history.drafts))) or any(row['registration_status'] != 'registered' for row in registrations):
                return 'waiting', None
            if not terminal and (history.source_task_ref.key()[:2] == current_task.ref.key()[:2]
                    or any(draft in history.drafts for draft in current_task.drafts)):
                return 'waiting', None
            if not terminal and not set(physical([Reference.model_validate(row['option_ref']) for row in registrations])) <= set(physical(after_limit.option_refs)):
                raise TaskConflict('Design continuation omits actually registered prior engagement options')
        elif any(row['registration_status'] not in {'failed', 'rejected'} for row in registrations):
            return 'waiting', None
        submission_query = dict(original=before_submission.model_dump(mode='json'), current=history.model_dump(mode='json'),
            production_task=production_task.model_dump(mode='json'), registrations=registrations, registered_options=options)
    if code == CANDIDATE_CODE:
        if history.ref == before_limit.ref or not any(getattr(history, name) > getattr(before_limit, name)
                for name in ('maximum_candidates', 'maximum_revisions', 'maximum_versions_branches')):
            return 'waiting', None
    if code == WORK_CODE:
        if (history.ref == before_limit.ref
                or not (decimal_fraction(history.maximum_effort.value) > decimal_fraction(before_limit.maximum_effort.value)
                    or decimal_fraction(history.maximum_cost.value) > decimal_fraction(before_limit.maximum_cost.value))):
            return 'waiting', None
    evidence = []
    for ref in history.evidence_refs:
        row = read(ref, EvidenceRecord, context.business_time)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Design recovery requires observed actual task authorization evidence')
        if row.effective_window is not None and not row.effective_window.contains(context.business_time):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    if not evidence:
        return 'unavailable', None
    current_result = None
    if not terminal:
        current_result = compile_design(context, current_input, reading)
        if current_result.get('kind') != 'completed':
            return 'waiting', None
        contract.validate_decision(current_input, current_result['payload'])

    def dump(version):
        return {name: ({str(key): row.model_dump(mode='json') for key, row in value.items()}
            if isinstance(value, dict) else value.model_dump(mode='json')) for name, value in version.items()}

    resolution = dict(schema_version=('architect-design-authorization-resolution.v1' if code == AUTHORIZATION_CODE
        else 'architect-design-candidate-limit-resolution.v1' if code == CANDIDATE_CODE
        else 'architect-design-submission-resolution.v1' if code == SUBMISSION_CODE
        else 'architect-design-work-limit-resolution.v1'), condition_code=code,
        history=history.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_sources=dump(old), current_sources=dump(current), evidence=evidence, sources=reading.evidence(),
        original_gate=contract.result_adapter.validate_python(original_gate).model_dump(mode='json'))
    if current_result is not None:
        resolution['current_result'] = contract.result_adapter.validate_python(current_result).model_dump(mode='json')
    if submission_query is not None:
        resolution['submission_query'] = submission_query
        resolution['disposition'] = 'actual_prior_submission_archive' if terminal else 'independent_current_design_work'
    if validate_relation(source_identity=deepcopy(source), condition_code=code, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Design recovery lacks actual independent native task authorization and remaining-duty authentication')
    return 'ready', resolution


def architect_original_design_profile(read_current, validate_relation, condition_code=AUTHORIZATION_CODE):
    if condition_code not in _CODES or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Design recovery requires actual guarded original task sources and native authority validation')
    def evaluate(check):
        if check.condition.condition_code != condition_code:
            raise TaskConflict('Design condition profile substitutes the original wait branch')
        selected = read_current(deepcopy(check))
        try:
            return _check_architect_design_history(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()
    return ConditionProfile('ARCHITECT-A05', condition_code, '1', frozenset({'dependency_change'}), evaluate)
