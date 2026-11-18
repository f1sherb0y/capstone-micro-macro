"""GOV-A01 versioned preliminary advice; no approval or investment decision."""
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.government_advice_objects import (
    GovConsultationRequestView, GovAdviceAuthorityView, GovAdviceBriefView,
    GovAdviceOptionView, GovAdviceProcedureView, GovAdviceRuleView,
    GovAdviceRequirementView, GovAdviceTargetView, GovAdviceTriggerView, GovAdviceRecipientView,
)
from src.actions.contracts.government_objects import (
    GovJurisdictionView, GovMatterView, GovResponseRequirementView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.government import IntakeGap, _needs, _unsupported
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def respond_to_consultation(context, action_input, reading):
    scope, now = action_input.scope, context.business_time

    def current(window):
        if window.start.clock_ref != now.clock_ref:
            _unsupported('government-advice-clock-alignment')
        if not window.contains(now):
            _needs('current_consultation_or_guidance')

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('government-advice-evidence-schema')
            if row.effective_window is not None:
                current(row.effective_window)

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported(f'government-advice-projection:{ref.kind}')
        if hasattr(row, 'scope') and not scope_covers(row.scope, scope):
            raise ValueError('Consultation projection does not cover the requested scope')
        if hasattr(row, 'available_at'):
            if row.available_at.clock_ref != now.clock_ref:
                _unsupported('government-advice-clock-alignment')
            if row.available_at.offset > now.offset:
                _needs('available_consultation_facts', [ref])
        if hasattr(row, 'effective_window'):
            current(row.effective_window)
        evidence(getattr(row, 'evidence_refs', []))
        return row

    def same_versions(row):
        if (row.consultation_ref != request.ref or row.brief_ref != request.brief_ref
                or set(row.option_refs) != set(request.option_refs)):
            raise ValueError('Guidance, target or trigger covers different consultation/brief/option versions')
        unique_refs(row.option_refs)

    def rule(ref, purposes):
        row = read(ref, GovAdviceRuleView)
        same_versions(row)
        if (row.organization_id != reading.organization_id or row.matter_ref != request.matter_ref
                or row.jurisdiction_ref != request.jurisdiction_ref or row.procedure_ref != request.procedure_ref
                or row.purpose not in purposes):
            raise ValueError('Consultation rule changes authority, matter, jurisdiction, procedure or purpose')
        grant = read(row.author_authority_ref, Authorization)
        assignment = read(row.author_function_ref, RoleAssignment)
        evidence([*grant.basis_refs, *assignment.basis_refs])
        if (assignment.role != 'Government' or grant.actor_id != row.author_actor_id
                or grant.function_ref != row.author_function_ref or grant.organization_id != reading.organization_id
                or 'GOV-A01' not in grant.action_ids
                or not any(scope_covers(s, scope) for s in grant.scopes)):
            raise ValueError('Consultation interpretation lacks original independent Government authorization')
        current(grant.validity)
        unique_refs(row.information_requirement_refs)
        return row

    def questions(rows):
        for question in rows:
            if question.scope != scope or not question.target_refs or not question.recipient_refs:
                raise ValueError('Consultation question lacks exact scope, targets or recipients')
            requirement_rule = rule(question.requirement_ref, {'advice', 'clarification', 'refer'})
            unique_refs(question.target_refs); unique_refs(question.recipient_refs)
            for ref in question.target_refs:
                same_versions(read(ref, GovAdviceTargetView))
            for ref in question.recipient_refs:
                recipient = read(ref, GovAdviceRecipientView)
                if recipient.actor_id not in authority.allowed_recipient_ids:
                    raise ValueError('Consultation question discloses data to an unauthorized recipient')
                if requirement_rule.recipient_ref is not None and ref != requirement_rule.recipient_ref:
                    raise ValueError('Consultation question changes its rule-designated recipient')
            response = read(question.response_requirement_ref, GovResponseRequirementView)
            if response.rule_ref != question.requirement_ref:
                raise ValueError('Consultation response requirement changes original question rule')
            evidence(question.evidence_refs)
        return rows

    def completed(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {
            'choice': choice, 'scope': scope,
            'note': 'Preliminary consultation only; no permit, investment approval or design certification', **fields}}

    try:
        if scope != context.scope:
            raise ValueError('Consultation changes the invocation scope')
        unique_refs(action_input.option_refs); unique_refs(action_input.evidence_refs)
        request = read(action_input.consultation_ref, GovConsultationRequestView)
        for field in ('scope', 'brief_ref', 'matter_ref', 'jurisdiction_ref', 'procedure_ref'):
            if getattr(request, field) != getattr(action_input, field):
                raise ValueError('Consultation input changes an original version or scope')
        if (set(request.option_refs) != set(action_input.option_refs)
                or set(request.supplied_evidence_refs) != set(action_input.evidence_refs)):
            raise ValueError('Consultation input omits or changes original options/evidence')
        if request.recipient_organization_id != reading.organization_id:
            raise ValueError('Consultation is addressed to another government organization')
        if request.status != 'active':
            _needs('active_original_consultation', [request.ref])
        authority = read(request.consultation_authority_ref, GovAdviceAuthorityView)
        if (authority.consultation_ref != request.ref or authority.applicant_id != request.applicant_id
                or authority.recipient_organization_id != reading.organization_id
                or authority.delegate_actor_id != context.actor_id or authority.delegate_function_ref != context.function_ref):
            raise ValueError('Consultation authority changes original applicant, recipient or delegate')
        if authority.permitted.state == 'not_supported':
            reading.recheck()
            return {'kind': 'unsupported', 'capability_ref': authority.permitted.capability_ref}
        if authority.permitted.state != 'known' or not authority.permitted.value:
            _needs('independent_consultation_permission', [authority.ref])
        evidence(action_input.evidence_refs)
        if request.brief_ref is not None:
            brief = read(request.brief_ref, GovAdviceBriefView)
            unique_refs(brief.option_refs)
            if (brief.applicant_id != request.applicant_id or set(brief.option_refs) != set(request.option_refs)
                    or reading.organization_id not in brief.recipient_organization_ids):
                raise ValueError('Consultation brief changes applicant, original options or authorized recipient')
        for ref in request.option_refs:
            option = read(ref, GovAdviceOptionView)
            if (option.brief_ref != request.brief_ref or option.applicant_id != request.applicant_id
                    or reading.organization_id not in option.recipient_organization_ids):
                raise ValueError('Consultation option changes brief, applicant or authorized recipient')
        matter = read(request.matter_ref, GovMatterView)
        jurisdiction = read(request.jurisdiction_ref, GovJurisdictionView)
        if jurisdiction.organization_id != reading.organization_id:
            raise ValueError('Consultation uses another government organization jurisdiction')
        if request.procedure_ref is not None:
            procedure = read(request.procedure_ref, GovAdviceProcedureView)
            if procedure.matter_ref != matter.ref or procedure.jurisdiction_ref != jurisdiction.ref:
                raise ValueError('Consultation procedure changes matter or jurisdiction')
            unique_refs(procedure.guidance_rule_refs); unique_refs(procedure.information_requirement_refs)
            if (not set(request.guidance_rule_refs) <= set(procedure.guidance_rule_refs)
                    or not set(request.information_requirement_refs) <= set(procedure.information_requirement_refs)):
                raise ValueError('Consultation adds requirements outside the original procedure')
        states = [jurisdiction.covered_matter_codes, jurisdiction.covered_project_region_ids, matter.project_region_id]
        for state in states:
            if state.state == 'not_supported':
                reading.recheck()
                return {'kind': 'unsupported', 'capability_ref': state.capability_ref}
        # Missing facts remain unknown. Actor/applicant registration location is never a jurisdiction criterion.
        criteria = [any(scope_covers(s, scope) for s in jurisdiction.covered_scopes)]
        criteria.append(matter.matter_code in states[0].value if states[0].state == 'known' else None)
        criteria.append(states[2].value in states[1].value
                        if states[1].state == states[2].state == 'known' else None)
        covered = False if False in criteria else (None if None in criteria else True)
        if covered is False and jurisdiction.referral is not None:
            referral = jurisdiction.referral
            basis = rule(referral.basis_ref, {'refer'})
            if basis.recipient_ref is None:
                _needs('original_lawful_consultation_referral_recipient')
            recipient = read(basis.recipient_ref, GovAdviceRecipientView)
            if (recipient.actor_id != referral.recipient_id or recipient.actor_id not in authority.allowed_recipient_ids
                    or matter.ref not in recipient.matter_refs or recipient.organization_id == reading.organization_id):
                raise ValueError('Referral changes original permitted recipient or covered matter')
            target = read(recipient.jurisdiction_ref, GovJurisdictionView)
            if target.organization_id != recipient.organization_id:
                raise ValueError('Referral recipient uses another organization jurisdiction')
            if (target.covered_matter_codes.state != 'known'
                    or matter.matter_code not in target.covered_matter_codes.value
                    or target.covered_project_region_ids.state != 'known' or matter.project_region_id.state != 'known'
                    or matter.project_region_id.value not in target.covered_project_region_ids.value
                    or not any(scope_covers(s, scope) for s in target.covered_scopes)):
                _needs('known_actual_referral_matter_and_project_jurisdiction')
            return completed('refer', recipient_id=recipient.actor_id, basis_ref=basis.ref,
                             questions=questions(request.questions))
        gap_questions = questions(request.questions)
        if request.response_mode == 'clarify':
            if not gap_questions:
                _needs('original_scoped_consultation_questions')
            return completed('clarify', questions=gap_questions)
        rules = [rule(ref, {'advice', 'outside_coverage'}) for ref in request.guidance_rule_refs]
        findings = []
        for row in rules:
            if row.applicability.state == 'not_supported':
                reading.recheck()
                return {'kind': 'unsupported', 'capability_ref': row.applicability.capability_ref}
            findings.append(row.applicability.value if row.applicability.state == 'known' else None)
        applicability = 'unknown'
        if covered is True and findings and None not in findings and len(set(findings)) == 1:
            applicability = findings[0]
        allowed_requirements = {ref for row in rules for ref in row.information_requirement_refs}
        if not set(request.information_requirement_refs) <= allowed_requirements:
            raise ValueError('Preliminary advice invents a requirement without an original applicable rule')
        for ref in request.information_requirement_refs:
            requirement = read(ref, GovAdviceRequirementView)
            if (requirement.consultation_ref != request.ref or requirement.procedure_ref != request.procedure_ref
                    or requirement.rule_ref not in request.guidance_rule_refs):
                raise ValueError('Advice information requirement changes consultation, procedure or rule')
            owner_rule = next(row for row in rules if row.ref == requirement.rule_ref)
            if ref not in owner_rule.information_requirement_refs:
                raise ValueError('Advice requirement lacks its own original rule basis')
        for ref in request.update_trigger_refs:
            same_versions(read(ref, GovAdviceTriggerView))
        return completed('advise', advice={
            'matter_ref': matter.ref, 'jurisdiction_ref': jurisdiction.ref, 'applicability': applicability,
            'basis_refs': request.guidance_rule_refs, 'information_requirement_refs': request.information_requirement_refs,
            'known_gap_questions': gap_questions, 'update_trigger_refs': request.update_trigger_refs,
            'explanation': 'Original-version procedural opinion; applicability remains unknown outside confirmed jurisdiction or evidence'
                           + ('; ' + '; '.join(row.explanation for row in rules) if rules else ''),
        })
    except IntakeGap as exc:
        reading.recheck()
        return exc.result
