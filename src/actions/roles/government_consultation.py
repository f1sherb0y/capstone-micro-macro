"""GOV-A05 prepares lawful consultation and preserves actual opinion provenance."""
from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.government_objects import GovJurisdictionView, GovMatterView, GovRecipientView, GovResponseRequirementView
from src.actions.contracts.government_scheduling_objects import GovSchedulingCaseView
from src.actions.contracts.government_review_objects import GovReviewSubmissionView
from src.actions.contracts.government_consultation_objects import (
    GovConsultationRuleView, GovConsultationApplicabilityView, GovDisclosurePackageView,
    GovDisclosureAuthorityView, GovConsultationRecipientView, GovConsultationClockView, GovConsultationView,
    GovConsultationDeliveryView, GovConsultationResponseView, GovParticipationView, GovConsultationTaskView,
    GovConsultationResultView, GovConsultationQuestionView, GovConsultationProcedureView,
    GovConsultationCaseView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.government_consultation import CONSULTATION_METHOD, ConsultationCoverageInput
from src.methods.qs_cost import unknown
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def organize_consultation(context, action_input, reading):
    now, scope, org = context.business_time, action_input.scope, reading.organization_id
    sources = {}

    def keys(refs):
        unique_refs(refs)
        return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('government-consultation-clock-alignment')

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('government-consultation-evidence-schema')
            sources[ref.key()] = row

    def read(ref, schema, historic=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported('government-consultation-projection:' + ref.kind)
        if hasattr(row, 'scope') and not scope_covers(scope, row.scope):
            raise ValueError('Consultation input leaves original authorized scope')
        evidence(getattr(row, 'evidence_refs', []))
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset:
                _needs('received_original_consultation_record', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now):
                _needs('current_original_consultation_record', [ref])
        sources[ref.key()] = row
        return row

    def authorize(ref, actor, function, organization, action, at):
        row = read(ref, Authorization); assignment = read(function, RoleAssignment)
        roles = {'OWN': 'Owner', 'CONTRACTOR': 'Contractor', 'SUPPLIER': 'Supplier', 'ARCHITECT': 'Architect',
            'ENGINEER': 'Engineer', 'QS': 'QS', 'GOV': 'Government', 'BANK': 'Bank'}
        if (row.actor_id != actor or row.function_ref != function or row.organization_id != organization
                or assignment.role != roles.get(action.split('-')[0]) or action not in row.action_ids
                or not any(scope_covers(s, scope) for s in row.scopes)):
            raise ValueError('Consultation source substitutes original actor/function/action authority')
        evidence(row.basis_refs + assignment.basis_refs); clock(at); clock(row.validity.start)
        if not row.validity.contains(at):
            _needs('original_consultation_authority_at_execution', [ref])
        return row

    def author(row, agency=False):
        clock(row.authored_at)
        if row.authored_at.offset > row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Consultation source predates its original applicable author execution')
        if agency and (row.author_organization_id != org or row.author_action_id != 'GOV-A05'):
            raise ValueError('Consultation verification substitutes responsible agency/action')
        return authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_organization_id, row.author_action_id, row.authored_at)

    def completed(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'scope': scope, 'choice': choice,
            'note': 'Original consultation procedure only; delivery, opinion and participation remain distinct. No unanimity, veto, signed decision or permission effect.', **fields}}

    def wait(code, refs):
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {'trigger': 'dependency_change',
            'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    def questions(refs):
        output = []; keys(refs)
        for ref in refs:
            row = read(ref, GovConsultationQuestionView)
            q = row.question
            if row.case_ref != case.ref or q.scope != row.scope or q.requirement_ref != rule.ref or ref.key() not in keys(q.target_refs):
                raise ValueError('Consultation question substitutes original case/scope/rule/targets')
            response = read(q.response_requirement_ref, GovResponseRequirementView)
            if response.rule_ref != rule.ref or response.scope != q.scope or not q.recipient_refs:
                raise ValueError('Consultation question substitutes original response requirement')
            for target in q.target_refs:
                original = read(target, GovConsultationQuestionView)
                if original.case_ref != case.ref or original.question != q:
                    raise ValueError('Consultation question mixes unrelated original targets')
            for recipient in q.recipient_refs:
                if recipient not in disclosure.question_recipient_refs:
                    raise ValueError('Consultation question uses an unauthorized original disclosure recipient')
                read(recipient, GovRecipientView)
            evidence(q.evidence_refs)
            if not keys(q.evidence_refs) <= keys(disclosure.evidence_refs_allowed):
                raise ValueError('Consultation question discloses evidence outside original disclosure authority')
            output.append(q.model_dump(mode='python'))
        return output

    try:
        case = read(action_input.case_ref, GovConsultationCaseView)
        keys(case.consultation_refs)
        rule = read(action_input.consultation_rule_ref, GovConsultationRuleView)
        package = read(action_input.disclosure_package_ref, GovDisclosurePackageView)
        if (case.organization_id != org or rule.organization_id != org or rule.case_ref != case.ref
                or rule.procedure_ref != case.procedure_ref or package.case_ref != case.ref):
            raise ValueError('Consultation changes original responsible agency/case/procedure')
        authorize(rule.authority_ref, context.actor_id, context.function_ref, org, 'GOV-A05', now)
        procedure = read(case.procedure_ref, GovConsultationProcedureView)
        if procedure.case_ref != case.ref or procedure.rule_ref != rule.ref:
            raise ValueError('Consultation rule belongs to another original procedure')
        if not rule.modeled or not procedure.modeled:
            _unsupported('government-consultation-unmodeled-procedure')
        jurisdiction = read(case.jurisdiction_ref, GovJurisdictionView); matter = read(case.matter_ref, GovMatterView)
        if (jurisdiction.organization_id != org or matter.matter_code not in _known(jurisdiction.covered_matter_codes, 'consultation_jurisdiction_matters')
                or _known(case.region_id, 'consultation_case_region') not in _known(jurisdiction.covered_project_region_ids, 'consultation_jurisdiction_regions')
                or not any(scope_covers(s, scope) for s in jurisdiction.covered_scopes)):
            raise ValueError('Agency lacks original lawful consultation jurisdiction')
        if case.status in {'closed', 'withdrawn'}:
            return wait('government_consultation_case_not_open', [case.ref])
        submission = read(case.current_submission_ref, GovReviewSubmissionView)
        if package.submission_ref != submission.ref or package.submission_sha256 != submission.content_sha256:
            raise ValueError('Disclosure package uses stale submission content')
        disclosure = read(rule.disclosure_authority_ref, GovDisclosureAuthorityView)
        if (disclosure.organization_id != org or disclosure.actor_id != context.actor_id or disclosure.function_ref != context.function_ref
                or disclosure.case_ref != case.ref or disclosure.rule_ref != rule.ref or disclosure.package_ref != package.ref
                or disclosure.content_sha256 != package.content_sha256 or package.status != 'authorized'):
            raise ValueError('Consultation lacks original exact package/actor disclosure authority')
        if not _known(disclosure.permitted, 'original_consultation_disclosure_permission'):
            return wait('government_consultation_disclosure_not_authorized', [package.ref])
        if not keys(package.disclosed_evidence_refs) <= keys(disclosure.evidence_refs_allowed):
            raise ValueError('Consultation package exposes evidence outside original permitted content')
        evidence(package.disclosed_evidence_refs)
        if (keys(action_input.recipient_refs) != keys(rule.recipient_refs)
                or not keys(rule.recipient_refs) <= keys(package.allowed_recipient_refs)
                or not keys(rule.recipient_refs) <= keys(disclosure.recipient_refs)):
            raise ValueError('Consultation substitutes original channels or unauthorized disclosure recipients')
        recipients = [read(ref, GovConsultationRecipientView) for ref in action_input.recipient_refs]
        applicability = read(rule.applicability_basis_ref, GovConsultationApplicabilityView); author(applicability, True)
        if applicability.case_ref != case.ref or applicability.rule_ref != rule.ref:
            raise ValueError('Consultation applicability belongs to another original case/rule')
        known_inapplicable = isinstance(applicability.applicable, Known) and not applicability.applicable.value
        if (not recipients and not known_inapplicable) or len({r.channel_key for r in recipients}) != len(recipients):
            raise ValueError('Consultation must use distinct original recipient channels')
        for recipient in recipients:
            if recipient.case_ref != case.ref or recipient.procedure_ref != case.procedure_ref:
                raise ValueError('Consultation recipient belongs to another case or procedure')
        clock_rule = read(rule.clock_rule_ref, GovConsultationClockView)
        if (clock_rule.case_ref != case.ref or clock_rule.rule_ref != rule.ref or clock_rule.procedure_ref != case.procedure_ref
                or clock_rule.response_duration_ticks <= 0):
            raise ValueError('Consultation timing lacks an original positive applicable clock rule')
        keys(action_input.response_refs)
        if rule.choice == 'refer':
            if rule.referral_recipient_ref is None or rule.referral_recipient_ref != disclosure.referral_recipient_ref:
                _needs('original_authorized_consultation_referral_recipient')
            recipient = read(rule.referral_recipient_ref, GovRecipientView)
            output = questions(rule.question_refs)
            if not output or any(rule.referral_recipient_ref not in q['recipient_refs'] for q in output):
                _needs('specific_original_consultation_referral_questions')
            return completed('refer', questions=output, recipient_id=recipient.actor_id)
        if rule.choice == 'initiate':
            if action_input.prior_consultation_ref is not None:
                return wait('government_consultation_query_existing_before_duplicate', [action_input.prior_consultation_ref])
            for ref in case.consultation_refs:
                existing = read(ref, GovConsultationView, True)
                if existing.case_ref != case.ref:
                    raise ValueError('Consultation case history substitutes another case')
                if existing.rule_ref == rule.ref and existing.disclosure_package_ref == package.ref and existing.status == 'active':
                    return wait('government_consultation_query_existing_before_duplicate', [existing.ref])
            if action_input.response_refs:
                raise ValueError('New consultation cannot borrow responses from an earlier consultation')
            if not _known(applicability.applicable, 'original_consultation_applicability'):
                return wait('government_consultation_not_applicable_by_original_basis', [case.ref, applicability.ref])
            return completed('initiate', draft={'case_ref': case.ref, 'procedure_ref': case.procedure_ref,
                'disclosure_package_ref': package.ref, 'recipient_refs': action_input.recipient_refs,
                'questions': questions(rule.question_refs), 'clock_rule_ref': clock_rule.ref})
        if action_input.prior_consultation_ref is None:
            _needs('original_existing_consultation_for_response_or_analysis')
        if action_input.prior_consultation_ref not in case.consultation_refs:
            raise ValueError('Response/analysis borrows a consultation outside original case history')
        consultation = read(action_input.prior_consultation_ref, GovConsultationView)
        if (consultation.organization_id != org or consultation.case_ref != case.ref or consultation.rule_ref != rule.ref
                or consultation.procedure_ref != case.procedure_ref or consultation.disclosure_package_ref != package.ref
                or consultation.content_sha256 != package.content_sha256 or consultation.clock_rule_ref != clock_rule.ref
                or keys(consultation.recipient_refs) != keys(action_input.recipient_refs)):
            raise ValueError('Original consultation changes disclosed content, recipients or procedure')
        if consultation.status != 'active':
            return wait('government_consultation_not_active', [consultation.ref])
        if consultation.coverage != 'complete' or consultation.as_of != now or keys(consultation.response_refs) != keys(action_input.response_refs):
            _needs('complete_current_original_consultation_response_history')
        by_recipient = {r.ref: r for r in recipients}
        events, responses = {}, []
        pending_questions = list(rule.question_refs)
        for ref in action_input.response_refs:
            response = read(ref, GovConsultationResponseView, True); author(response)
            recipient = by_recipient.get(response.recipient_ref)
            clock(response.received_at)
            if (recipient is None or response.consultation_ref != consultation.ref or response.package_ref != package.ref
                    or response.content_sha256 != package.content_sha256 or response.author_actor_id != recipient.representative_actor_id
                    or response.author_organization_id != recipient.organization_id
                    or response.author_function_ref != recipient.representative_function_ref or response.author_action_id != recipient.response_action_id
                    or response.authored_at.offset > response.received_at.offset or response.received_at.offset > response.available_at.offset):
                raise ValueError('Response substitutes original consultation/channel/content or actual authorized author')
            body = response.model_dump(mode='json', exclude={'ref', 'available_at', 'effective_window', 'evidence_refs'})
            if response.event_id in events:
                if events[response.event_id] != body:
                    raise ValueError('Repeated response event changes original opinion content')
                continue
            events[response.event_id] = body; responses.append(response)
            pending_questions.extend(response.issue_question_refs)
        if not set(consultation.registered_event_ids) <= set(events):
            raise ValueError('Consultation registered opinion history references an absent actual event')
        if rule.choice == 'register_response':
            new = [r.ref for r in responses if r.status == 'received' and r.response_kind == 'opinion'
                and r.event_id not in consultation.registered_event_ids]
            if not new:
                return wait('government_consultation_wait_for_new_actual_opinion', [consultation.ref])
            return completed('register_response', consultation_ref=consultation.ref, response_refs=new)
        if not known_inapplicable and not any(r.status == 'received' and r.response_kind == 'opinion' for r in responses):
            return wait('government_consultation_no_actual_opinion_yet', [consultation.ref])
        if not {r.event_id for r in responses if r.status == 'received' and r.response_kind == 'opinion'} <= set(consultation.registered_event_ids):
            _needs('registered_original_opinion_history_before_consultation_analysis')
        channels = []; data_sources = [rule.ref, applicability.ref, consultation.ref, package.ref, clock_rule.ref]
        keys(consultation.delivery_refs); keys(consultation.participation_refs)
        deliveries = [read(ref, GovConsultationDeliveryView, True) for ref in consultation.delivery_refs]
        participations = [read(ref, GovParticipationView, True) for ref in consultation.participation_refs]
        for row in deliveries:
            if row.consultation_ref != consultation.ref or row.recipient_ref not in by_recipient or row.package_ref != package.ref or row.content_sha256 != package.content_sha256:
                raise ValueError('Delivery receipt belongs to another consultation/channel/content')
            if row.delivered_at is not None:
                clock(row.delivered_at)
                if row.delivered_at.offset > row.available_at.offset:
                    raise ValueError('Delivery receipt predates actual delivery')
            elif isinstance(row.delivered, Known) and row.delivered.value:
                raise ValueError('Positive delivery requires its original actual delivery time')
        for row in participations:
            author(row, True)
            if row.consultation_ref != consultation.ref or row.recipient_ref not in by_recipient or row.rule_ref != rule.ref:
                raise ValueError('Participation verification covers another original consultation/channel/rule')
        for recipient in recipients:
            sent = [r for r in deliveries if r.recipient_ref == recipient.ref]
            participation = [r for r in participations if r.recipient_ref == recipient.ref]
            if len(sent) > 1 or len(participation) > 1:
                _needs('unambiguous_original_current_channel_delivery_and_participation')
            if participation:
                verified = participation[0]; clock(verified.started_at)
                if verified.completed_at is not None:
                    clock(verified.completed_at)
                    if verified.completed_at.offset > verified.authored_at.offset:
                        raise ValueError('Participation verification predates actual completion')
                if isinstance(verified.satisfied, Known) and verified.satisfied.value:
                    if (recipient.kind != 'public_channel' or not sent or sent[0].delivered_at is None
                            or verified.started_at != sent[0].delivered_at or verified.completed_at is None
                            or verified.completed_at.offset < verified.started_at.offset + clock_rule.response_duration_ticks):
                        raise ValueError('Public completion lacks original delivery and full applicable participation window')
            channel_responses = [r for r in responses if r.recipient_ref == recipient.ref and r.status == 'received' and r.response_kind == 'opinion']
            if sent and sent[0].delivered_at is not None and any(r.received_at.offset < sent[0].delivered_at.offset for r in channel_responses):
                raise ValueError('Consultation opinion predates the original disclosed delivery')
            channels.append({'channel_key': recipient.channel_key, 'required': recipient.required,
                'delivered': sent[0].delivered if sent else unknown('consultation_delivery_unknown'),
                'response_event_ids': [r.event_id for r in channel_responses], 'public_channel': recipient.kind == 'public_channel',
                'participation_verified': participation[0].satisfied if participation else unknown('public_participation_not_verified')})
            data_sources += [recipient.ref, *[r.ref for r in sent + participation + channel_responses]]
        if rule.analysis_task_ref is None:
            _needs('original_authorized_consultation_analysis_task')
        task = read(rule.analysis_task_ref, GovConsultationTaskView)
        if task.organization_id != org or task.case_ref != case.ref or task.consultation_ref != consultation.ref or task.function_ref != context.function_ref:
            raise ValueError('Consultation analysis task belongs to another original case/actor')
        authorize(task.authority_ref, context.actor_id, context.function_ref, org, 'GOV-A05', now)
        if task.status != 'authorized':
            return wait('government_consultation_analysis_task_wait', [task.ref])
        data_sources.append(task.ref)
        data = ConsultationCoverageInput(applicable=applicability.applicable, channels=channels, source_refs=data_sources)
        finding, saved_ref = 'unknown', None
        if rule.analysis_result_ref is not None:
            saved = read(rule.analysis_result_ref, GovConsultationResultView); grant = author(saved, True)
            if saved.consultation_ref != consultation.ref or saved.task_ref != task.ref or saved.rule_ref != rule.ref or saved.method_ref != CONSULTATION_METHOD:
                raise ValueError('Consultation analysis result substitutes original task/rule/method')
            if saved.status == 'unsupported':
                _unsupported('government-consultation-analysis-method')
            if saved.status == 'failed':
                raise ObservationGap({'kind': 'technical_error', 'error': {'kind': 'unrecorded',
                    'correlation_id': context.operation_id, 'code': 'original_consultation_analysis_failed'}, 'retryability': 'unknown'})
            if saved.status == 'ok':
                if saved.input_sha256 != content_digest(data) or not keys(data_sources) <= keys(grant.readable_refs):
                    raise ValueError('Consultation result changes original source input or execution read authority')
                if any(sources[ref.key()].available_at.offset > saved.authored_at.offset for ref in data_sources):
                    _needs('consultation_analysis_after_original_inputs', [saved.ref])
                result = reading.calculate(CONSULTATION_METHOD, data)
                if result.kind != 'ok':
                    if result.kind == 'invalid_input':
                        raise ValueError('Consultation source coverage violates declared method domain')
                    raw = result.model_dump(mode='python')
                    if result.kind == 'needs_information':
                        raw['requested_refs'] = []
                    raise ObservationGap(raw)
                if saved.report != result.value:
                    raise ValueError('Consultation saved finding differs from actual replies and participation coverage')
                finding, saved_ref = result.value.finding, saved.ref
        opinions = [r for r in responses if r.response_kind == 'opinion' and r.status == 'received']
        counts = {position: sum(r.position == position for r in opinions) for position in ('support', 'oppose', 'advice', 'unknown')}
        return completed('analyze', consultation_ref=consultation.ref, assessment={'target_ref': case.ref,
            'task_ref': task.ref, 'checks': [{'rule_ref': rule.ref, 'covered_scope': scope,
                'evidence_refs': list({r.key(): r for row in [rule, applicability, *responses, *deliveries, *participations] for r in row.evidence_refs}.values()),
                'method_result_ref': saved_ref, 'finding': finding}],
            'proposed_questions': questions(list({r.key(): r for r in pending_questions}.values())),
            'explanation': 'Consultation procedure coverage only; original opinion counts ' + str(counts)
                + '. Opposition is retained as an opinion; missing replies remain pending. This creates no veto, unanimity, substantive compliance or permit.'})
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
