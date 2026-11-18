"""GOV-A06 closes only verified requirements and preserves unaffected review scope."""
from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.government_objects import GovJurisdictionView, GovMatterView, GovRecipientView, GovResponseRequirementView
from src.actions.contracts.government_supplement_objects import (
    GovSupplementCaseView, GovSupplementSubmissionView, GovSubmissionComponentView, GovSupplementProfileView,
    GovSupplementIssueView, GovSupplementRequirementView, GovSupplementRuleView, GovSupplementResponseView,
    GovResponseFactView, GovSupplementResultView, GovSupplementAssessmentView, GovSupplementQuestionView,
    GovSupplementClockView, GovSupplementDelayAuthorityView, GovSupplementTriggerView,
    GovSupplementRevisionView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.government_rules import GOV_RULE_METHOD, GovRuleInput
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def handle_supplements(context, action_input, reading):
    now, scope, org = context.business_time, action_input.scope, reading.organization_id
    sources = {}

    def keys(refs):
        unique_refs(refs)
        return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('government-supplement-clock-alignment')

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('government-supplement-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
            sources[ref.key()] = row

    def read(ref, schema, historic=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported('government-supplement-projection:' + ref.kind)
        if hasattr(row, 'scope') and not scope_covers(scope, row.scope):
            raise ValueError('Supplement record leaves original authorized scope')
        evidence(getattr(row, 'evidence_refs', []))
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset:
                _needs('received_original_supplement_record', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now):
                _needs('current_original_supplement_record', [ref])
        sources[ref.key()] = row
        return row

    def authorize(ref, actor, function, organization, action, at):
        row = read(ref, Authorization); assignment = read(function, RoleAssignment)
        roles = {'GOV': 'Government', 'OWN': 'Owner', 'ARCHITECT': 'Architect', 'ENGINEER': 'Engineer',
            'QS': 'QS', 'CONTRACTOR': 'Contractor', 'SUPPLIER': 'Supplier', 'BANK': 'Bank'}
        if (row.actor_id != actor or row.function_ref != function or row.organization_id != organization
                or assignment.role != roles.get(action.split('-')[0]) or action not in row.action_ids
                or not any(scope_covers(s, scope) for s in row.scopes)):
            raise ValueError('Supplement author substitutes original actor/function/action/scope authority')
        evidence(row.basis_refs + assignment.basis_refs); clock(at); clock(row.validity.start)
        if not row.validity.contains(at):
            _needs('original_supplement_authority_at_execution', [ref])
        return row

    def author(row, agency=False):
        clock(row.authored_at)
        if row.authored_at.offset > row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Supplement record predates its original applicable execution')
        if agency and (row.author_organization_id != org or row.author_action_id != 'GOV-A06'):
            raise ValueError('Response verification substitutes original responsible agency/action')
        return authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_organization_id, row.author_action_id, row.authored_at)

    def wait(code, refs):
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {'trigger': 'dependency_change',
            'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    def completed(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'scope': scope, 'choice': choice,
            'note': 'Original scoped supplement handling only; unaffected review remains reusable. No design edit, automatic approval/refusal or formal issue/assignment effect.', **fields}}

    try:
        case = read(action_input.case_ref, GovSupplementCaseView)
        profile = read(case.supplement_profile_ref, GovSupplementProfileView)
        original = read(action_input.original_submission_ref, GovSupplementSubmissionView, True)
        current = read(action_input.current_submission_ref, GovSupplementSubmissionView)
        if (case.organization_id != org or profile.organization_id != org or profile.case_ref != case.ref
                or profile.original_submission_ref != original.ref or profile.current_submission_ref != current.ref
                or case.current_submission_ref != current.ref or original.ref not in case.linked_submission_refs
                or current.ref not in case.linked_submission_refs or profile.clock_rule_ref != action_input.clock_rule_ref):
            raise ValueError('Supplement handling changes original case or submission lineage')
        for submission in (original, current):
            if (submission.matter_ref != case.matter_ref or submission.procedure_ref != case.procedure_ref
                    or submission.jurisdiction_ref != case.jurisdiction_ref or submission.recipient_organization_id != org
                    or submission.applicant_id != case.applicant_id):
                raise ValueError('Supplement submission substitutes original applicant, agency or procedure')
        if current.receipt_status != 'received' or current.status != 'active' or case.status in {'closed', 'withdrawn'}:
            return wait('government_supplement_case_not_ready', [case.ref, current.ref])
        authorize(profile.authority_ref, context.actor_id, context.function_ref, org, 'GOV-A06', now)
        jurisdiction = read(case.jurisdiction_ref, GovJurisdictionView); matter = read(case.matter_ref, GovMatterView)
        if (jurisdiction.organization_id != org or matter.matter_code not in _known(jurisdiction.covered_matter_codes, 'supplement_jurisdiction_matters')
                or _known(case.region_id, 'supplement_case_region') not in _known(jurisdiction.covered_project_region_ids, 'supplement_jurisdiction_regions')
                or not any(scope_covers(s, scope) for s in jurisdiction.covered_scopes)):
            raise ValueError('Agency has no original lawful supplement jurisdiction')
        if profile.coverage != 'complete' or profile.as_of != now:
            _needs('complete_current_original_supplement_history')
        if keys(action_input.issue_refs) != keys(profile.issue_refs) or keys(action_input.response_refs) != keys(profile.response_refs):
            _needs('complete_original_issue_and_response_set')
        if original.ref != current.ref:
            if profile.revision_basis_ref is None:
                _needs('original_authorized_revision_procedure_basis')
            revision = read(profile.revision_basis_ref, GovSupplementRevisionView); author(revision, True)
            if (revision.case_ref != case.ref or revision.original_submission_ref != original.ref
                    or revision.original_content_sha256 != original.content_sha256 or revision.current_submission_ref != current.ref
                    or revision.current_content_sha256 != current.content_sha256 or revision.procedure_ref != case.procedure_ref):
                raise ValueError('Revision procedure basis substitutes original or current submission content')
            if revision.route == 'unmodeled':
                _unsupported('government-supplement-revision-procedure')
            if revision.route != 'continue_scoped_review':
                return wait('government_supplement_requires_' + revision.route, [case.ref, revision.ref, current.ref])
        if not action_input.issue_refs:
            _needs('specific_original_supplement_issues')
        issues = [read(ref, GovSupplementIssueView) for ref in action_input.issue_refs]
        for issue in issues:
            if issue.case_ref != case.ref or issue.original_submission_ref != original.ref:
                raise ValueError('Issue substitutes original case or submission version')
            keys(issue.requirement_refs); clock(issue.opened_at)
            if not issue.requirement_refs or issue.opened_at.offset > now.offset:
                raise ValueError('Supplement issue lacks actual original requirements or opening time')
        clock_rule = read(action_input.clock_rule_ref, GovSupplementClockView)
        if clock_rule.case_ref != case.ref or clock_rule.procedure_ref != case.procedure_ref or keys(clock_rule.issue_refs) != keys(action_input.issue_refs):
            raise ValueError('Supplement clock rule concerns another original case/procedure/issue set')
        if profile.choice == 'request_supplement':
            output = []
            for issue in issues:
                if issue.status == 'resolved':
                    continue
                keys(issue.question_refs)
                for ref in issue.question_refs:
                    row = read(ref, GovSupplementQuestionView); q = row.question
                    if row.issue_ref != issue.ref or q.scope != issue.scope or ref.key() not in keys(q.target_refs):
                        raise ValueError('Supplement question changes original issue, scope or targets')
                    rule = read(q.requirement_ref, GovSupplementRuleView)
                    if rule.case_ref != case.ref or rule.organization_id != org or rule.purpose != 'supplement' or issue.ref not in rule.issue_refs:
                        raise ValueError('Supplement question invents an unrelated legal rule')
                    if not _known(rule.permitted, 'original_supplement_requirement_permission'):
                        _needs('authorized_original_supplement_requirement', [rule.ref])
                    response_requirement = read(q.response_requirement_ref, GovResponseRequirementView)
                    if response_requirement.rule_ref != rule.ref or response_requirement.scope != q.scope or not q.recipient_refs:
                        raise ValueError('Supplement question changes its original response requirement')
                    for target in q.target_refs:
                        target_row = read(target, GovSupplementQuestionView)
                        if target_row.issue_ref != issue.ref or target_row.question != q:
                            raise ValueError('Supplement question mixes original issue targets')
                    for recipient in q.recipient_refs:
                        recipient_row = read(recipient, GovRecipientView)
                        if recipient_row.scope != q.scope:
                            raise ValueError('Supplement recipient leaves original question scope')
                    evidence(q.evidence_refs); output.append(q.model_dump(mode='python'))
            if not output:
                _needs('specific_original_unresolved_supplement_questions')
            return completed('request_supplement', questions=output)
        if profile.choice == 'process_delay':
            if clock_rule.deadline is None or profile.delay_rule_ref is None or profile.next_trigger_ref is None:
                return wait('government_supplement_no_evidenced_delay_rule', [case.ref, clock_rule.ref])
            clock(clock_rule.deadline)
            if now.offset <= clock_rule.deadline.offset:
                return wait('government_supplement_response_window_still_open', [case.ref, clock_rule.ref])
            rule = read(profile.delay_rule_ref, GovSupplementRuleView)
            if (rule.case_ref != case.ref or rule.organization_id != org or rule.purpose != 'delay'
                    or keys(rule.issue_refs) != keys(action_input.issue_refs) or rule.delay_authority_ref is None
                    or rule.delay_effect is None):
                raise ValueError('Delay handling lacks an original scoped lawful effect rule')
            authority = read(rule.delay_authority_ref, GovSupplementDelayAuthorityView)
            if (authority.organization_id != org or authority.actor_id != context.actor_id or authority.function_ref != context.function_ref
                    or authority.case_ref != case.ref or authority.rule_ref != rule.ref or authority.clock_rule_ref != clock_rule.ref
                    or authority.next_trigger_ref != profile.next_trigger_ref or keys(authority.issue_refs) != keys(action_input.issue_refs)):
                raise ValueError('Delay handling substitutes independently authorized scope or trigger')
            if not _known(rule.permitted, 'original_delay_rule_permission') or not _known(authority.permitted, 'original_delay_authority_permission'):
                return wait('government_supplement_delay_effect_not_authorized', [case.ref, rule.ref])
            trigger = read(profile.next_trigger_ref, GovSupplementTriggerView)
            if trigger.case_ref != case.ref or trigger.rule_ref != rule.ref or keys(trigger.issue_refs) != keys(action_input.issue_refs):
                raise ValueError('Delay trigger concerns another original case/rule/issues')
            if rule.delay_effect == 'schedule_followup':
                if trigger.kind != 'scheduled_followup' or trigger.next_at is None:
                    _needs('original_future_followup_trigger')
                clock(trigger.next_at)
                if trigger.next_at.offset <= now.offset:
                    _needs('original_future_followup_trigger')
            elif trigger.kind != 'response_received':
                raise ValueError('Retained queue must wait for original response trigger')
            if any(issue.status != 'open' for issue in issues):
                _needs('currently_unresolved_issues_for_delay_handling')
            received = [read(ref, GovSupplementResponseView, True) for ref in action_input.response_refs]
            if any(row.status == 'received' for row in received):
                return wait('government_supplement_verify_actual_responses_before_delay', [case.ref, *action_input.response_refs])
            return completed('process_delay', issue_refs=action_input.issue_refs, basis_ref=rule.ref, next_trigger_ref=trigger.ref)

        def components(submission):
            keys(submission.component_refs); output = {}
            for ref in submission.component_refs:
                row = read(ref, GovSubmissionComponentView, submission.ref != current.ref)
                if row.submission_ref != submission.ref or row.component_key in output:
                    raise ValueError('Submission components substitute version or repeat local scope identity')
                output[row.component_key] = row
            return output

        before, after = components(original), components(current)
        affected, reusable = [], []
        keys(profile.assessment_refs)
        for ref in profile.assessment_refs:
            assessment = read(ref, GovSupplementAssessmentView, True); author(assessment)
            if (assessment.case_ref != case.ref or assessment.submission_ref != original.ref
                    or assessment.content_sha256 != original.content_sha256):
                raise ValueError('Reuse assessment does not bind the original reviewed submission')
            keys(assessment.component_refs)
            unchanged = bool(assessment.component_refs) and assessment.status == 'valid'
            for component_ref in assessment.component_refs:
                component = read(component_ref, GovSubmissionComponentView, True)
                previous = before.get(component.component_key); updated = after.get(component.component_key)
                if previous is None or previous.ref != component.ref:
                    raise ValueError('Assessment component coverage does not belong to original submission')
                unchanged &= (updated is not None and updated.content_sha256 == component.content_sha256 and updated.scope == component.scope)
            (reusable if unchanged else affected).append(assessment.ref)
        if keys(reusable) != keys(action_input.reusable_assessment_refs):
            raise ValueError('Declared reusable review set differs from unchanged original component coverage')
        responses, events = {}, {}
        for ref in action_input.response_refs:
            response = read(ref, GovSupplementResponseView, True); author(response); clock(response.received_at)
            if (response.case_ref != case.ref or response.issue_ref not in action_input.issue_refs
                    or response.original_submission_ref != original.ref or response.current_submission_ref != current.ref
                    or response.current_content_sha256 != current.content_sha256
                    or response.author_actor_id not in profile.authorized_response_actor_ids
                    or response.received_at.offset < response.authored_at.offset or response.received_at.offset > response.available_at.offset):
                raise ValueError('Response changes original issue, current revised submission or receipt provenance')
            body = response.model_dump(mode='json', exclude={'ref', 'available_at', 'effective_window', 'evidence_refs'})
            if response.event_id in events:
                if events[response.event_id] != body:
                    raise ValueError('Duplicate supplement response event changes original content')
                continue
            events[response.event_id] = body
            if response.status == 'received':
                responses.setdefault(response.issue_ref.key(), []).append(response)
        resolutions = []
        for issue in issues:
            received = responses.get(issue.ref.key(), []); facts = {}
            for response in received:
                keys(response.fact_refs)
                for ref in response.fact_refs:
                    fact = read(ref, GovResponseFactView); author(fact, True)
                    if fact.response_ref != response.ref or fact.requirement_ref not in issue.requirement_refs:
                        raise ValueError('Response fact substitutes its original author response or requirement')
                    requirement = read(fact.requirement_ref, GovSupplementRequirementView)
                    component = after.get(requirement.component_key)
                    if (component is None or component.ref != fact.component_ref
                            or not scope_covers(issue.scope, fact.scope) or not scope_covers(requirement.scope, component.scope)):
                        raise ValueError('Response verification uses a stale or unrelated submission component')
                    if fact.requirement_ref.key() in facts:
                        _needs('unambiguous_original_current_requirement_fact', [ref])
                    facts[fact.requirement_ref.key()] = fact
            saved = None
            if issue.verification_result_ref is not None:
                saved = read(issue.verification_result_ref, GovSupplementResultView); grant = author(saved, True)
                if (saved.issue_ref != issue.ref or saved.current_submission_ref != current.ref or saved.current_content_sha256 != current.content_sha256
                        or keys(saved.response_refs) != keys([row.ref for row in received]) or saved.method_ref != GOV_RULE_METHOD):
                    raise ValueError('Issue verification substitutes current scope, actual responses or method')
                if saved.status == 'failed':
                    raise ObservationGap({'kind': 'technical_error', 'error': {'kind': 'unrecorded',
                        'correlation_id': context.operation_id, 'code': 'original_supplement_verification_failed'}, 'retryability': 'unknown'})
                if saved.status == 'unsupported':
                    _unsupported('government-supplement-original-verification-method')
            retained = []
            for ref in issue.requirement_refs:
                requirement = read(ref, GovSupplementRequirementView)
                if requirement.issue_ref != issue.ref:
                    raise ValueError('Issue borrows another original requirement')
                rule = read(requirement.rule_ref, GovSupplementRuleView)
                if rule.case_ref != case.ref or rule.organization_id != org or rule.purpose != 'supplement' or issue.ref not in rule.issue_refs:
                    raise ValueError('Requirement has no original scoped legal supplement basis')
                if requirement.criterion == 'unmodeled':
                    _unsupported('government-supplement-unmodeled-requirement')
                fact = facts.get(ref.key())
                data_refs = [issue.ref, requirement.ref, rule.ref, current.ref]
                if fact is not None:
                    data_refs += [fact.ref, fact.response_ref, fact.component_ref, *fact.evidence_refs]
                    data_refs = list({r.key(): r for r in data_refs}.values())
                    if fact.measured_value is not None and fact.measured_value.state == 'known':
                        if fact.measured_value.value.basis_ref not in fact.evidence_refs:
                            raise ValueError('Response quantity lacks original sourced fact evidence')
                    if any(sources[e.key()].basis_kind == 'assumed' for e in fact.evidence_refs):
                        _needs('verified_response_facts_instead_of_assumptions', fact.evidence_refs)
                data = GovRuleInput(criterion=requirement.criterion, applicable=rule.permitted,
                    measured_value=fact.measured_value if fact else None, code_value=fact.code_value if fact else None,
                    unit=requirement.unit, minimum=requirement.minimum, maximum=requirement.maximum, expected_code=requirement.expected_code,
                    professional_findings=[], professional_complete=True, source_refs=data_refs)
                finding = 'unknown'
                if saved is not None and saved.status == 'ok':
                    if (saved.input_sha256s.get(ref.id) != content_digest(data) or not keys(data_refs) <= keys(grant.readable_refs)
                            or any(hasattr(sources[r.key()], 'available_at') and sources[r.key()].available_at.offset > saved.authored_at.offset for r in data_refs)):
                        raise ValueError('Issue verification changes original inputs, source read authority or execution time')
                    result = reading.calculate(GOV_RULE_METHOD, data)
                    if result.kind != 'ok':
                        if result.kind == 'invalid_input':
                            raise ValueError('Original response rule violates declared method domain')
                        raw = result.model_dump(mode='python')
                        if result.kind == 'needs_information':
                            raw['requested_refs'] = []
                        raise ObservationGap(raw)
                    if saved.reports.get(ref.id) != result.value:
                        raise ValueError('Saved response verification differs from original current evidence')
                    finding = result.value.finding
                if finding != 'conforms':
                    retained.append(ref)
            if saved is not None and saved.status == 'ok':
                if set(saved.input_sha256s) != {ref.id for ref in issue.requirement_refs} or set(saved.reports) != set(saved.input_sha256s):
                    raise ValueError('Verification must preserve every original issue requirement')
            usable = saved is not None and saved.status == 'ok'
            resolution = 'unresolved' if not usable or len(retained) == len(issue.requirement_refs) else ('partially_resolved' if retained else 'resolved')
            resolutions.append({'issue_ref': issue.ref, 'response_refs': [row.ref for row in received],
                'verification_result_ref': saved.ref if usable else None, 'resolution': resolution,
                'retained_requirement_refs': retained, 'affected_assessment_refs': affected, 'reusable_assessment_refs': reusable})
        return completed('verify_response', resolutions=resolutions)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
