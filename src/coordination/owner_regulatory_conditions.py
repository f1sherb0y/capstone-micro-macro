"""Reconcile original regulatory commands and independently authorized event waits."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.owner_regulatory_objects import (
    OwnerRegulatoryRequirementView, OwnerRegulatoryProfileView, OwnerRegulatoryExecutionView,
    OwnerRegulatoryCaseView, OwnerRegulatoryAuthorityView, OwnerRegulatoryProcedureView,
    OwnerRegulatoryNoticeView, OwnerRegulatoryRecoveryDispositionView,
)
from src.actions.roles.owner_regulatory import handle_regulatory
from src.coordination.continuations import ConditionProfile
from src.coordination.owner_closeout_conditions import same_closeout_scope
from src.coordination.owner_saved_wait_conditions import OwnerSavedWaitConditionReading, read_owner_saved_wait
from src.coordination.tasks import TaskConflict, _text
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


QUERY_PREFIX = 'query_original_command:'
CORRECTION_CODE = 'separate_authorized_regulatory_correction_required'
CASE_CODE = 'original_case_disposition_change'
PROCEDURE_CODE = 'original_late_action_disposition'
NOTICE_CODE = 'original_notice_late_response_disposition'
FIXED_CODES = (CORRECTION_CODE, CASE_CODE, PROCEDURE_CODE, NOTICE_CODE)
_FIXED_KINDS = {CORRECTION_CODE: ('RegulatorySubmissionExecution', 'Evidence'),
    CASE_CODE: ('RegulatoryCase',), PROCEDURE_CODE: ('Procedure',), NOTICE_CODE: ('RegulatoryNotice',)}
_DISPOSITIONS = {CORRECTION_CODE: 'authorized_correction', CASE_CODE: 'case_action',
    PROCEDURE_CODE: 'procedure_action', NOTICE_CODE: 'notice_response'}


def regulatory_wait_kinds(code):
    if code.startswith(QUERY_PREFIX):
        _text(code[len(QUERY_PREFIX):])
        return ('RegulatorySubmissionExecution',)
    if code not in _FIXED_KINDS:
        raise ValueError('Unknown original Owner regulatory event condition')
    return _FIXED_KINDS[code]


@dataclass(frozen=True)
class OwnerRegulatoryConditionReading(OwnerSavedWaitConditionReading):
    disposition_ref: Reference | None = None


def check_owner_regulatory_conditions(check, selected, validate_relation):
    code = check.condition.condition_code
    old_input, current_input, saved = read_owner_saved_wait(check, selected, validate_relation,
        action_id='OWN-A08', code=code, kinds=regulatory_wait_kinds(code),
        reading_type=OwnerRegulatoryConditionReading, trigger='event')
    source = check.source['identity']
    context, original, reading = selected.context, selected.original_context, selected.reading
    query = code.startswith(QUERY_PREFIX)
    if (old_input.applicant_id != current_input.applicant_id
            or old_input.regulatory_requirement_ref.key()[:2] != current_input.regulatory_requirement_ref.key()[:2]
            or not same_closeout_scope(old_input.scope_ref, current_input.scope_ref)):
        raise TaskConflict('Owner regulatory recovery changes the original applicant, requirement or affected scope')

    def physical(refs):
        result = {ref.key()[:2]: ref for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('Owner regulatory recovery repeats physical authorities, submissions, cases or notices')
        return result

    def read(ref, schema, invocation, *, historical=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref:
            raise TaskConflict('Owner regulatory recovery requires exact typed authorized sources')
        at = invocation.business_time
        point = getattr(row, 'available_at', None)
        if point is not None and (point.clock_ref != at.clock_ref or point.offset > at.offset):
            raise TaskConflict('Owner regulatory recovery imports information unavailable at its recorded time')
        if hasattr(row, 'scope') and not scope_covers(row.scope, invocation.scope):
            raise TaskConflict('Owner regulatory recovery substitutes unrelated regulatory work')
        window = getattr(row, 'effective_window', None)
        if window is not None and (window.start.clock_ref != at.clock_ref or window.end.clock_ref != at.clock_ref
                or not historical and not window.contains(at)):
            raise TaskConflict('Owner regulatory recovery lacks a current source or its original business clock')
        return row

    for name in ('authority_candidates', 'submission_refs', 'notice_refs', 'case_refs'):
        if not set(physical(getattr(old_input, name))) <= set(physical(getattr(current_input, name))):
            raise TaskConflict('Owner regulatory recovery drops original authorities, professional submissions, notices or cases')
    versions = []
    for values, invocation in ((old_input, original), (current_input, context)):
        requirement = read(values.regulatory_requirement_ref, OwnerRegulatoryRequirementView, invocation)
        profile = read(requirement.decision_profile_ref, OwnerRegulatoryProfileView, invocation)
        if (requirement.applicant_id != values.applicant_id or profile.organization_id != source['organization_id']
                or profile.requirement_ref != requirement.ref or values.scope_ref != invocation.scope):
            raise TaskConflict('Owner regulatory recovery changes the original owner/applicant/requirement relation')
        versions.append((requirement, profile))
    (old_requirement, old_profile), (requirement, profile) = versions
    if (old_requirement.project_region_id != requirement.project_region_id
            or old_profile.ref.key()[:2] != profile.ref.key()[:2]
            or not set(physical(old_requirement.matter_refs)) <= set(physical(requirement.matter_refs))):
        raise TaskConflict('Owner regulatory recovery changes the original region/profile or discards regulatory matters')
    if old_profile.case_ref is not None and (profile.case_ref is None
            or old_profile.case_ref.key()[:2] != profile.case_ref.key()[:2]):
        raise TaskConflict('Owner regulatory recovery substitutes the original follow-up case')
    if old_profile.case_ref is not None and profile.choice == 'submit' and not query:
        raise TaskConflict('Owner regulatory recovery cannot replace an existing case follow-up with a new application')
    if old_profile.case_ref is not None and not query:
        old_case = read(old_profile.case_ref, OwnerRegulatoryCaseView, original)
        case = read(profile.case_ref, OwnerRegulatoryCaseView, context)
        if (old_case.applicant_id != old_input.applicant_id or case.applicant_id != current_input.applicant_id
                or old_case.requirement_ref != old_requirement.ref or case.requirement_ref != requirement.ref
                or old_case.authority_ref.key()[:2] != case.authority_ref.key()[:2]):
            raise TaskConflict('Owner regulatory recovery changes the original follow-up case attribution')
        # Permission to perform one follow-up action does not retract the
        # original matters or the independently authored submissions. Exact
        # versions may advance, while their physical history remains declared.
        for name in ('matter_refs', 'submission_refs'):
            if not set(physical(getattr(old_case, name))) <= set(physical(getattr(case, name))):
                raise TaskConflict('Owner regulatory recovery discards original case matters or professional submissions')

    # A08 has no professional calculations. Recheck the original deterministic
    # gate with its own immutable sources and business time, without substituting
    # a current judgment or inventing a historical method result.
    before_methods = reading.method_evidence()
    gate = handle_regulatory(original, old_input, reading)
    if (reading.method_evidence() != before_methods
            or selected.contract.result_adapter.validate_python(gate).model_dump(mode='json') != saved['result']):
        raise TaskConflict('Owner regulatory saved wait differs from its actual original processor gate')
    old_ref, ref = check.condition.object_refs[0], selected.history_ref
    if old_ref.key()[:2] != ref.key()[:2]:
        raise TaskConflict('Owner regulatory recovery substitutes its original event dependency')
    schemas = {'RegulatorySubmissionExecution': OwnerRegulatoryExecutionView,
        'RegulatoryCase': OwnerRegulatoryCaseView, 'Procedure': OwnerRegulatoryProcedureView,
        'RegulatoryNotice': OwnerRegulatoryNoticeView}
    previous = read(old_ref, schemas[old_ref.kind], original, historical=True)
    current = read(ref, schemas[old_ref.kind], context, historical=query or code == CORRECTION_CODE)
    evidence = {}

    def observed(refs):
        for evidence_ref in refs:
            record = read(evidence_ref, EvidenceRecord, context)
            if record.source_kind == 'synthetic' or record.basis_kind != 'observed':
                raise TaskConflict('Regulatory recovery requires observed actual native query/disposition evidence')
            evidence[record.ref.key()] = record.model_dump(mode='json')

    command_id, disposition = None, None
    if query or code == CORRECTION_CODE:
        command_id = previous.command_id
        if (previous.organization_id != source['organization_id'] or previous.applicant_id != old_input.applicant_id
                or previous.requirement_ref != old_requirement.ref or old_profile.prior_execution_ref != previous.ref
                or current.organization_id != previous.organization_id or current.applicant_id != previous.applicant_id
                or current.requirement_ref != requirement.ref or current.command_id != command_id
                or previous.case_ref is not None and (current.case_ref is None
                    or previous.case_ref.key()[:2] != current.case_ref.key()[:2])
                or profile.case_ref is not None and current.case_ref != profile.case_ref):
            raise TaskConflict('Owner regulatory recovery changes original command, applicant, requirement or case identity')
        if query:
            if (code != QUERY_PREFIX + command_id or previous.status not in {'unknown', 'pending', 'received'}
                    or profile.prior_execution_ref != current.ref or profile.choice != old_profile.choice
                    or selected.disposition_ref is not None):
                raise TaskConflict('Owner regulatory query changes its original command wait or bypasses unresolved execution')
            if current.status in {'unknown', 'pending', 'received'}:
                return 'waiting', None
        elif previous.status != 'rejected' or current.status != 'rejected':
            raise TaskConflict('Regulatory correction must retain the original rejected command result')
        elif profile.prior_execution_ref is not None:
            return 'waiting', None
        observed([current.result_basis_ref, *current.evidence_refs])
    elif code == CASE_CODE:
        if (previous.ref != old_profile.case_ref or current.ref != profile.case_ref
                or previous.applicant_id != current.applicant_id or current.applicant_id != current_input.applicant_id
                or previous.requirement_ref != old_requirement.ref or current.requirement_ref != requirement.ref
                or previous.authority_ref.key()[:2] != current.authority_ref.key()[:2]):
            raise TaskConflict('Owner regulatory disposition changes the original case/applicant/receiving authority')
    elif code == NOTICE_CODE:
        if (old_ref not in old_input.notice_refs or ref not in current_input.notice_refs
                or previous.applicant_id != current.applicant_id or current.applicant_id != current_input.applicant_id
                or previous.case_ref != old_profile.case_ref or current.case_ref != profile.case_ref
                or previous.case_ref.key()[:2] != current.case_ref.key()[:2]
                or previous.authority_ref.key()[:2] != current.authority_ref.key()[:2]
                or previous.purpose != current.purpose):
            raise TaskConflict('Owner regulatory late response substitutes the original notice/case/authority or notice purpose')
        for name in ('required_response_refs', 'subject_refs', 'issue_refs'):
            if not set(physical(getattr(previous, name))) <= set(physical(getattr(current, name))):
                raise TaskConflict('Owner regulatory late response discards original notice questions or response duties')
        if profile.choice in {'supplement', 'request_review'}:
            case = read(profile.case_ref, OwnerRegulatoryCaseView, context)
            if current.ref not in case.open_notice_refs:
                raise TaskConflict('Owner regulatory recovery drops the original late notice from its response duties')
    else:
        if previous.authority_ref.key()[:2] != current.authority_ref.key()[:2]:
            raise TaskConflict('Owner regulatory late action substitutes the original procedure authority')
        if profile.case_ref is None:
            active_authority_ref = profile.competent_authority_ref
        else:
            active_authority_ref = read(profile.case_ref, OwnerRegulatoryCaseView, context).authority_ref
        if active_authority_ref != current.authority_ref:
            raise TaskConflict('Owner regulatory recovery bypasses the original procedure with another authority')
        active_authority = read(active_authority_ref, OwnerRegulatoryAuthorityView, context)
        if active_authority.procedure_ref != current.ref:
            raise TaskConflict('Owner regulatory recovery selects a procedure outside its current authority')

    if not query:
        if not isinstance(selected.disposition_ref, Reference) or selected.disposition_ref.kind != 'RegulatoryRecoveryDisposition':
            return 'waiting', None
        disposition = read(selected.disposition_ref, OwnerRegulatoryRecoveryDispositionView, context)
        if (disposition.recipient_organization_id != source['organization_id']
                or disposition.applicant_id != current_input.applicant_id
                or disposition.original_request_id != source['request_id']
                or disposition.original_input_sha256 != source['input_sha256']
                or disposition.original_condition_code != code
                or disposition.original_requirement_ref != old_requirement.ref or disposition.requirement_ref != requirement.ref
                or disposition.original_dependency_ref != previous.ref or disposition.current_dependency_ref != current.ref
                or disposition.current_profile_ref != profile.ref or disposition.permitted_choice != profile.choice
                or disposition.disposition_kind != _DISPOSITIONS[code] or disposition.command_id != command_id
                or disposition.issued_at.clock_ref != context.business_time.clock_ref
                or not original.business_time.offset <= disposition.issued_at.offset <= disposition.available_at.offset):
            raise TaskConflict('Owner regulatory recovery borrows an unrelated or stale native correction/late-action disposition')
        if disposition.permitted.state != 'known' or disposition.permitted.value is not True:
            return 'waiting', None
        grant = read(disposition.issuer_authority_ref, Authorization, context)
        function = read(disposition.issuer_function_ref, RoleAssignment, context)
        if code == CORRECTION_CODE:
            issuer, role, action_ids = current_input.applicant_id, 'Owner', {'OWN-A08'}
        else:
            authority_ref = previous.authority_ref
            authority = read(authority_ref, OwnerRegulatoryAuthorityView, original, historical=True)
            issuer, role = authority.organization_id, 'Government'
            action_ids = {f'GOV-A{number:02}' for number in range(1, 13)}
        if (disposition.issuer_organization_id != issuer or grant.organization_id != issuer
                or grant.actor_id != disposition.issuer_actor_id or grant.function_ref != function.function_ref
                or function.role != role or disposition.issuer_action_id not in action_ids
                or disposition.issuer_action_id not in grant.action_ids
                or grant.validity.start.clock_ref != disposition.issued_at.clock_ref
                or not grant.validity.contains(disposition.issued_at)
                or not any(scope_covers(scope, disposition.scope) for scope in grant.scopes)):
            raise TaskConflict('Regulatory recovery lacks independent applicant/competent-government disposition authority')
        observed([*disposition.evidence_refs, *grant.basis_refs, *function.basis_refs, *current.evidence_refs])

    result = handle_regulatory(context, current_input, reading)
    result = selected.contract.result_adapter.validate_python(result)
    if query:
        # The native projection has no accepted terminal. A reconciled failure
        # or rejection permits a fresh judgment that records that exact outcome;
        # it never authorizes resubmission, assumes a permit or clears a command.
        valid = ((current.status == 'failed' and result.kind == 'technical_error'
                    and result.error.kind == 'unrecorded' and result.error.correlation_id == command_id
                    and result.error.code == 'original_regulatory_submission_failed')
            or (current.status == 'rejected' and result.kind == 'deferred'
                    and result.resume_condition.condition_code == CORRECTION_CODE
                    and list(result.resume_condition.object_refs) == [current.ref, current.result_basis_ref]))
        if not valid:
            return 'waiting', None
    elif result.kind != 'completed':
        return 'waiting', None
    else:
        selected.contract.validate_decision(current_input, result.payload)
    resolution = dict(schema_version='owner-regulatory-event-resolution.v1', condition_code=code,
        mode='query_original_command' if query else 'authorized_current_action',
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_action_input=deepcopy(selected.original_action_input), action_input=deepcopy(selected.action_input),
        original_record=saved, original_dependency=previous.model_dump(mode='json'),
        current_dependency=current.model_dump(mode='json'), command_id=command_id,
        disposition=None if disposition is None else disposition.model_dump(mode='json'),
        evidence=list(evidence.values()), sources=reading.evidence(), current_result=result.model_dump(mode='json'))
    if validate_relation(source_identity=deepcopy(source), condition_code=code, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Regulatory event recovery lacks independent original native query/disposition authentication')
    return 'ready', resolution


def owner_original_regulatory_profile(read_current, validate_relation, condition_code):
    regulatory_wait_kinds(condition_code)
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Regulatory recovery requires guarded original sources and actual native authentication')

    def evaluate(check):
        if check.condition.condition_code != condition_code:
            raise TaskConflict('Regulatory event substitutes another registered original condition')
        selected = read_current(deepcopy(check))
        try:
            return check_owner_regulatory_conditions(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('OWN-A08', condition_code, '1', frozenset({'event'}), evaluate)
