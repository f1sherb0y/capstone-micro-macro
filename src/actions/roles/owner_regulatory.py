"""OWN-A08 authorized applications; intake and permits belong to independent core."""
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.owner_regulatory_objects import (
    OwnerRegulatoryRequirementView, OwnerRegulatoryProfileView, OwnerRegulatoryAgencyView,
    OwnerRegulatoryAuthorityView, OwnerRegulatoryJurisdictionView, OwnerRegulatoryMatterView,
    OwnerRegulatoryMaterialView, OwnerRegulatoryProcedureView, OwnerRegulatorySubmissionView,
    OwnerRegulatoryCaseView, OwnerRegulatoryNoticeView, OwnerRegulatoryResponseSourceView, OwnerRegulatoryExecutionView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def handle_regulatory(context, action_input, reading):
    now, owner = context.business_time, reading.organization_id

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('owner-regulatory-clock-alignment')

    def evidence(refs, historical=False):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('owner-regulatory-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not historical and not row.effective_window.contains(now): _needs('current_original_regulatory_evidence', [ref])

    def read(ref, schema, historical=False, scope=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'owner-regulatory-projection:{ref.kind}')
        if hasattr(row, 'scope') and not scope_covers(row.scope, scope or context.scope):
            raise ValueError('Regulatory input leaves original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at); clock(row.effective_window.start)
            if row.available_at.offset > now.offset: _needs('received_original_regulatory_input', [ref])
            if not historical and not row.effective_window.contains(now): _needs('current_original_regulatory_input', [ref])
        evidence(getattr(row, 'evidence_refs', []), historical); return row

    def authorize(ref, actor, function_ref, organization, action, roles):
        grant = read(ref, Authorization); function = read(function_ref, RoleAssignment)
        if (grant.actor_id != actor or grant.function_ref != function_ref or grant.organization_id != organization
                or function.role not in roles or action not in grant.action_ids
                or not any(scope_covers(scope, context.scope) for scope in grant.scopes)):
            raise ValueError('Regulatory action lacks original independent party/actor/scope authority')
        clock(grant.validity.start)
        if not grant.validity.contains(now): _needs('current_original_regulatory_actor_authority', [ref])
        evidence([*grant.basis_refs, *function.basis_refs])

    def completed(choice, **fields):
        reading.recheck(); return {'kind': 'completed', 'payload': {'choice': choice, 'note': profile.note, **fields}}

    def deferred(reason, refs, condition):
        reading.recheck(); return {'kind': 'deferred', 'reason_code': reason, 'resume_condition': {
            'trigger': 'event', 'object_refs': refs, 'earliest_time': None, 'condition_code': condition}}

    def response_source(ref, notice=None, scope=None):
        row = read(ref, OwnerRegulatoryResponseSourceView, scope=scope)
        if not same(row.requirement_ref, requirement.ref) or row.applicant_id != action_input.applicant_id:
            raise ValueError('Regulatory response changes original requirement/applicant')
        if notice is not None and (row.case_ref is None or row.notice_ref is None
                or not same(row.case_ref, case.ref) or not same(row.notice_ref, notice.ref)):
            raise ValueError('Regulatory response changes original case/notice attribution')
        if not _known(row.permitted, 'original_regulatory_response_permission'): _needs('original_regulatory_response_permission', [ref])
        return row

    try:
        if action_input.scope_ref != context.scope: raise ValueError('Regulatory decision changes invocation scope')
        requirement = read(action_input.regulatory_requirement_ref, OwnerRegulatoryRequirementView)
        profile = read(requirement.decision_profile_ref, OwnerRegulatoryProfileView)
        if (requirement.applicant_id != action_input.applicant_id or profile.organization_id != owner
                or not same(profile.requirement_ref, requirement.ref)):
            raise ValueError('Regulatory choice changes original applicant/requirement/owner')
        authorize(profile.authority_ref, context.actor_id, context.function_ref, owner, 'OWN-A08', {'Owner'})
        agency = None
        if profile.agency_authority_ref is not None:
            agency = read(profile.agency_authority_ref, OwnerRegulatoryAgencyView)
            if not same(agency.requirement_ref, requirement.ref) or agency.applicant_id != action_input.applicant_id:
                raise ValueError('Regulatory agency scope belongs to another applicant/requirement')
            authorize(agency.issuer_authority_ref, agency.issuer_actor_id, agency.issuer_function_ref,
                      agency.applicant_id, 'OWN-A08', {'Owner'})
        if action_input.applicant_id != owner:
            if (agency is None or agency.status != 'effective' or agency.delegate_id != owner
                    or profile.choice not in agency.permitted_choices or not _known(agency.permission, 'original_regulatory_agency_permission')):
                _needs('effective_original_applicant_delegation_for_this_regulatory_action')
        if profile.choice == 'authorize_agent':
            if action_input.applicant_id != owner or profile.delegate_id is None or profile.delegate_id == owner:
                _needs('explicit_other_organization_for_original_applicant_agency')
            delegated = profile.delegated_scope
            if not scope_covers(context.scope, delegated.scope_ref) or not delegated.basis_refs:
                raise ValueError('Delegated regulatory scope exceeds original owner authority or lacks basis')
            evidence(delegated.basis_refs); keys(delegated.condition_refs)
            for ref in delegated.condition_refs: response_source(ref, scope=delegated.scope_ref)
            if agency is None or agency.delegate_id != profile.delegate_id or agency.scope != delegated.scope_ref or agency.status == 'revoked':
                _needs('explicit_original_proposed_agency_scope_and_permissions')
            if not agency.permitted_choices or not _known(agency.permission, 'original_proposed_regulatory_agency_permission'):
                _needs('original_proposed_regulatory_agency_permission')
            if not agency.matter_refs or not keys(agency.matter_refs) <= keys(requirement.matter_refs):
                raise ValueError('Agency must propose nonempty original regulatory matters')
            return completed('authorize_agent', delegate_id=profile.delegate_id, delegated_scope=delegated.model_dump(mode='python'))
        if profile.prior_execution_ref is not None:
            execution = read(profile.prior_execution_ref, OwnerRegulatoryExecutionView, historical=True)
            if (execution.organization_id != owner or execution.applicant_id != action_input.applicant_id
                    or not same(execution.requirement_ref, requirement.ref)):
                raise ValueError('Regulatory retry changes original command/applicant/requirement identity')
            if profile.case_ref is not None and (execution.case_ref is None or not same(execution.case_ref, profile.case_ref)):
                raise ValueError('Regulatory retry changes the original case identity')
            evidence([execution.result_basis_ref], True)
            if execution.status in {'unknown', 'pending', 'received'}:
                return deferred('original_regulatory_submission_reconciliation_required', [execution.ref],
                                f'query_original_command:{execution.command_id}')
            if execution.status == 'failed':
                reading.recheck(); return {'kind': 'technical_error', 'error': {'kind': 'unrecorded',
                    'correlation_id': execution.command_id, 'code': 'original_regulatory_submission_failed'}, 'retryability': 'unknown'}
            return deferred('original_regulatory_submission_rejected', [execution.ref, execution.result_basis_ref],
                            'separate_authorized_regulatory_correction_required')
        case = None
        if profile.choice != 'submit':
            if profile.case_ref is None or profile.case_ref.key() not in keys(action_input.case_refs): _needs('original_case_for_followup_regulatory_action')
            case = read(profile.case_ref, OwnerRegulatoryCaseView)
            if case.applicant_id != action_input.applicant_id or not same(case.requirement_ref, requirement.ref):
                raise ValueError('Follow-up regulatory action changes original case applicant/requirement')
            if profile.choice not in case.permitted_choices or case.status in {'withdrawn', 'closed'}:
                return deferred('original_case_action_not_currently_permitted', [case.ref], 'original_case_disposition_change')
        authority_ref = profile.competent_authority_ref if case is None else case.authority_ref
        if authority_ref is None or authority_ref.key() not in keys(action_input.authority_candidates): _needs('original_competent_authority_candidate')
        if case is not None and profile.competent_authority_ref is not None and not same(profile.competent_authority_ref, authority_ref):
            raise ValueError('Follow-up action changes the original receiving authority')
        authority = read(authority_ref, OwnerRegulatoryAuthorityView)
        jurisdiction = read(authority.jurisdiction_ref, OwnerRegulatoryJurisdictionView)
        procedure = read(authority.procedure_ref, OwnerRegulatoryProcedureView)
        if (jurisdiction.organization_id != authority.organization_id or not same(procedure.authority_ref, authority.ref)
                or requirement.project_region_id not in jurisdiction.region_ids):
            _needs('original_competent_jurisdiction_for_project_region_and_matter')
        if not _known(jurisdiction.permission, 'current_original_regulatory_jurisdiction'):
            _needs('current_original_regulatory_jurisdiction')
        if action_input.applicant_id not in procedure.applicant_ids or profile.choice not in procedure.permitted_choices:
            _needs('original_applicant_eligibility_and_procedure_action')
        window = procedure.response_windows.get(profile.choice)
        if window is None: _needs('original_procedure_action_window')
        clock(window.start)
        if not window.contains(now): return deferred('original_regulatory_action_outside_procedure_window', [procedure.ref], 'original_late_action_disposition')
        matters = profile.requested_matter_refs if case is None else case.matter_refs
        if not matters: _needs('original_nonempty_regulatory_matters')
        selected = keys(matters)
        if (not selected <= keys(requirement.matter_refs) or not selected <= keys(authority.matter_refs)
                or not selected <= keys(jurisdiction.matter_refs) or not selected <= keys(procedure.matter_refs)):
            _needs('same_original_applicant_requirement_authority_jurisdiction_and_procedure_matters')
        if agency is not None and not selected <= keys(agency.matter_refs): _needs('original_agency_permission_for_selected_matters')
        material_refs = {}
        for ref in matters:
            matter = read(ref, OwnerRegulatoryMatterView)
            if (not same(matter.requirement_ref, requirement.ref) or matter.region_id != requirement.project_region_id
                    or not same(matter.authority_ref, authority.ref)):
                raise ValueError('Regulatory matter changes original region/requirement/authority')
            keys(matter.required_material_refs)
            for material_ref in matter.required_material_refs: material_refs[material_ref.key()] = (material_ref, matter.ref)
        if profile.choice == 'submit':
            if not keys(profile.submission_refs) <= keys(action_input.submission_refs): raise ValueError('Application adds undeclared professional submissions')
            if procedure.professional_submission_required and not profile.submission_refs: _needs('original_required_professional_application_materials')
            for ref in profile.submission_refs:
                row = read(ref, OwnerRegulatorySubmissionView)
                if (row.applicant_id != action_input.applicant_id or not same(row.requirement_ref, requirement.ref)
                        or row.status != 'submitted' or 'regulatory_submission' not in row.allowed_use_codes
                        or row.maturity not in procedure.allowed_submission_maturities):
                    _needs('same_original_authorized_professional_regulatory_materials', [ref])
                role = read(row.author_function_ref, RoleAssignment).role
                prefix = {'Architect': 'ARCHITECT-', 'Engineer': 'ENGINEER-', 'QS': 'QS-'}
                if not row.author_action_id.startswith(prefix.get(role, '!')): raise ValueError('Application material has no original independent professional author')
                authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
                          row.author_organization_id, row.author_action_id, {role})
            evidence(profile.evidence_refs_to_submit); evidence_keys = keys(profile.evidence_refs_to_submit)
            for ref, matter_ref in material_refs.values():
                material = read(ref, OwnerRegulatoryMaterialView)
                if not same(material.matter_ref, matter_ref): raise ValueError('Application material category changes original matter')
                if (material.evidence_ref.key() not in evidence_keys or not keys(material.submission_refs) <= keys(profile.submission_refs)
                        or not _known(material.verified, 'original_application_material_schema_verification')):
                    _needs('complete_original_matter_specific_application_materials', [ref])
            return completed('submit', authority_ref=authority.ref, application={
                'requirement_ref': requirement.ref, 'applicant_id': action_input.applicant_id, 'scope_ref': context.scope,
                'submission_refs': profile.submission_refs, 'evidence_refs': profile.evidence_refs_to_submit,
                'requested_matter_refs': matters})
        if profile.choice == 'withdraw':
            if not profile.withdrawal_basis_refs: _needs('original_explicit_case_withdrawal_basis')
            evidence(profile.withdrawal_basis_refs)
            return completed('withdraw', case_ref=case.ref, basis_refs=profile.withdrawal_basis_refs)
        if not case.open_notice_refs or not keys(case.open_notice_refs) <= keys(action_input.notice_refs):
            _needs('all_original_received_case_notices', case.open_notice_refs)
        notices, requirements, subjects, issues = {}, {}, {}, {}
        for ref in case.open_notice_refs:
            notice = read(ref, OwnerRegulatoryNoticeView); clock(notice.response_window.start)
            if (not same(notice.case_ref, case.ref) or not same(notice.authority_ref, authority.ref)
                    or notice.applicant_id != action_input.applicant_id): raise ValueError('Response notice changes original case/authority/applicant')
            if not notice.issuer_action_id.startswith('GOV-'): raise ValueError('Regulatory notice has no original competent government author')
            authorize(notice.issuer_authority_ref, notice.issuer_actor_id, notice.issuer_function_ref,
                      authority.organization_id, notice.issuer_action_id, {'Government'})
            required_purpose = {'supplement'} if profile.choice == 'supplement' else {'review', 'decision'}
            if notice.purpose not in required_purpose: continue
            if not notice.response_window.contains(now): return deferred('original_notice_response_outside_window', [notice.ref], 'original_notice_late_response_disposition')
            notices[ref.key()] = notice
            for target, source in ((notice.required_response_refs, requirements), (notice.subject_refs, subjects), (notice.issue_refs, issues)):
                for ref_ in target:
                    if ref_.key() in source: raise ValueError('Case notice repeats one response attribution')
                    source[ref_.key()] = notice
        if not notices or not profile.response_items: _needs('original_notice_linked_regulatory_response_items')
        if len({item.local_key for item in profile.response_items}) != len(profile.response_items): raise ValueError('Regulatory response local identity repeated')
        answered = set(); evidence(profile.evidence_refs_to_submit); submitted_evidence = keys(profile.evidence_refs_to_submit)
        for item in profile.response_items:
            notice = subjects.get(item.subject_ref.key())
            if notice is None or not item.request.strip(): _needs('original_notice_case_subject_for_structured_response')
            response_source(item.subject_ref, notice)
            if not item.requirement_refs and item.issue_ref is None: _needs('original_response_requirement_or_disputed_issue')
            keys(item.requirement_refs)
            for ref in item.requirement_refs:
                if ref.key() not in requirements or not same(requirements[ref.key()].ref, notice.ref):
                    raise ValueError('Response uses another notice requirement')
                if ref.key() in answered: raise ValueError('Regulatory response answers one original requirement twice')
                response_source(ref, notice); answered.add(ref.key())
            if item.issue_ref is not None:
                if item.issue_ref.key() not in issues or not same(issues[item.issue_ref.key()].ref, notice.ref):
                    raise ValueError('Response uses another notice disputed issue')
                response_source(item.issue_ref, notice)
            if not keys(item.evidence_refs) <= submitted_evidence: _needs('original_response_evidence_in_submission_envelope')
            evidence(item.evidence_refs)
        if answered != set(requirements): _needs('all_original_notice_response_requirements_answered')
        return completed(profile.choice, authority_ref=authority.ref, case_ref=case.ref,
                         evidence_refs=profile.evidence_refs_to_submit,
                         response_items=[item.model_dump(mode='python') for item in profile.response_items])
    except ObservationGap as gap:
        reading.recheck(); return gap.result
