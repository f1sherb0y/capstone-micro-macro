"""GOV-A08 verifies scoped fulfillment without bypassing other execution gates."""
from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.government_objects import GovRecipientView, GovResponseRequirementView
from src.actions.contracts.government_permit_objects import (
    GovPermitView, GovPermitDecisionView, GovPermitEffectView, GovPermitActionView, GovPermitRuleView,
    GovPermitAuthorityView, GovPermitConditionView, GovPermitFactView, GovPermitDependencyView,
    GovPermitDependencyVerificationView, GovPermitResultView, GovPermitQuestionView,
)
from src.actions.contracts.government_decision_objects import GovDecisionNotificationView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.government_rules import GOV_RULE_METHOD, GovRuleInput
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def verify_permit_conditions(context, action_input, reading):
    now, scope, org = context.business_time, action_input.scope, reading.organization_id
    sources = {}

    def keys(refs):
        unique_refs(refs)
        return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('government-permit-clock-alignment')

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('government-permit-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
            sources[ref.key()] = row

    def read(ref, schema, linked=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported('government-permit-projection:' + ref.kind)
        if hasattr(row, 'scope') and not linked and not scope_covers(scope, row.scope):
            raise ValueError('Permit source leaves the intended action scope')
        evidence(getattr(row, 'evidence_refs', []))
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset:
                _needs('received_original_permit_source', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
        sources[ref.key()] = row
        return row

    def authorize(ref, actor, function, organization, at, target_scope=scope):
        grant = read(ref, Authorization); assignment = read(function, RoleAssignment)
        evidence(grant.basis_refs + assignment.basis_refs); clock(at); clock(grant.validity.start)
        if (grant.actor_id != actor or grant.function_ref != function or grant.organization_id != organization
                or assignment.role != 'Government' or 'GOV-A08' not in grant.action_ids
                or not any(scope_covers(s, target_scope) for s in grant.scopes)):
            raise ValueError('Permit verification lacks independent original agency/function/scope authority')
        if not grant.validity.contains(at):
            _needs('original_condition_verifier_authority_at_execution', [ref])
        return grant

    def author(row, target_scope=scope, own=True):
        clock(row.authored_at)
        if (row.author_action_id != 'GOV-A08' or (own and row.author_organization_id != org)
                or row.authored_at.offset > row.available_at.offset or not row.effective_window.contains(row.authored_at)):
            raise ValueError('Condition fact/result substitutes original verifier function or creation time')
        return authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_organization_id, row.authored_at, target_scope)

    def bound(row):
        if row.permit_ref != permit.ref or row.action_ref != action.ref:
            raise ValueError('Condition source substitutes original permit version or intended action')

    def completed(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'scope': scope, 'choice': choice,
            'note': 'Condition verification only for the recorded action and scope. Actual fulfillment and cross-scope dependencies remain explicit; core execution still checks technical, funding and resource gates.', **fields}}

    def wait(code, refs):
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {'trigger': 'dependency_change',
            'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    def technical():
        raise ObservationGap({'kind': 'technical_error', 'error': {'kind': 'unrecorded',
            'correlation_id': context.operation_id, 'code': 'original_permit_verification_failed'}, 'retryability': 'unknown'})

    def effective(row, linked=False):
        if row.status != 'valid' or not row.effective_window.contains(now):
            return False if row.status != 'unknown' else None
        if not isinstance(row.effective, Known):
            return None
        if not row.effective.value:
            return False
        decision = read(row.decision_ref, GovPermitDecisionView, linked)
        if (decision.permit_ref != row.ref or decision.outcome not in {'approve', 'approve_with_conditions'}
                or not scope_covers(decision.scope, row.scope)):
            raise ValueError('Permit lacks its original scoped formal approving decision')
        if not isinstance(decision.effective, Known) or not decision.effective.value:
            return None
        effect = read(decision.effect_rule_ref, GovPermitEffectView, linked)
        if effect.decision_ref != decision.ref:
            raise ValueError('Permit effect refers to another original decision')
        if effect.mode == 'on_actual_delivery':
            delivered = set(); keys(decision.notification_refs)
            for ref in decision.notification_refs:
                notification = read(ref, GovDecisionNotificationView, linked)
                if notification.decision_ref != decision.ref or notification.recipient_id not in effect.notification_recipient_ids:
                    raise ValueError('Permit notification changes original decision/recipient')
                if notification.status == 'delivered':
                    if notification.delivered_at is None:
                        raise ValueError('Permit delivery needs its original actual time')
                    clock(notification.delivered_at)
                    if notification.delivered_at.offset > notification.available_at.offset:
                        raise ValueError('Notification predates actual permit delivery')
                    delivered.add(notification.recipient_id)
            if not effect.notification_recipient_ids or delivered != set(effect.notification_recipient_ids):
                return None
        return True

    def questions(refs, selected=None):
        keys(refs); output = []
        for ref in refs:
            row = read(ref, GovPermitQuestionView); bound(row); q = row.question
            if (row.condition_ref not in action_input.condition_refs or (selected is not None and row.condition_ref != selected.ref)
                    or q.scope != row.scope or q.requirement_ref != rule.ref or ref.key() not in keys(q.target_refs)):
                raise ValueError('Condition question changes original condition, rule, targets or scope')
            response = read(q.response_requirement_ref, GovResponseRequirementView)
            if response.rule_ref != rule.ref or response.scope != q.scope or not q.recipient_refs:
                raise ValueError('Condition question has no original scoped response requirement')
            for target in q.target_refs:
                original = read(target, GovPermitQuestionView); bound(original)
                if original.condition_ref != row.condition_ref or original.question != q:
                    raise ValueError('Condition question mixes unrelated targets')
            for ref in q.recipient_refs:
                recipient = read(ref, GovRecipientView)
                if recipient.scope != q.scope:
                    raise ValueError('Condition question recipient leaves original scope')
            evidence(q.evidence_refs); output.append(q.model_dump(mode='python'))
        return output

    try:
        permit = read(action_input.permit_ref, GovPermitView, linked=True)
        action = read(action_input.intended_action_ref, GovPermitActionView)
        rule = read(action_input.verification_rule_ref, GovPermitRuleView); bound(rule)
        if not scope_covers(permit.scope, scope) or permit.organization_id != org or action.permit_ref != permit.ref or action.scope != scope:
            raise ValueError('Verification changes lawful permit agency or intended action scope')
        if rule.verification is None:
            raise ValueError('Selected original rule is not a verification rule')
        profile = rule.verification
        if not rule.effective_window.contains(now):
            _needs('current_original_permit_verification_rule', [rule.ref])
        if profile.organization_id != org:
            raise ValueError('Verification rule belongs to another original agency')
        authorize(profile.authority_ref, context.actor_id, context.function_ref, org, now)
        if action.ref not in permit.allowed_action_refs or action.coverage != 'complete':
            _needs('original_complete_action_specific_permit_coverage')
        if keys(action_input.condition_refs) != keys(action.applicable_condition_refs) or not keys(action_input.condition_refs) <= keys(permit.condition_refs):
            _needs('all_original_conditions_for_intended_action')
        keys(action_input.evidence_refs); evidence(action_input.evidence_refs)
        authority = read(profile.verification_authority_ref, GovPermitAuthorityView); bound(authority)
        if (authority.organization_id != org or authority.actor_id != context.actor_id or authority.function_ref != context.function_ref
                or not keys(action_input.condition_refs) <= keys(authority.condition_refs)):
            raise ValueError('Condition verification lacks original scoped independent verifier permission')
        if not authority.effective_window.contains(now):
            _needs('current_independent_permit_verification_authority', [authority.ref])
        if not _known(authority.permitted, 'independent_original_condition_verification_permission'):
            _needs('original_permitted_condition_verification')
        if effective(permit, linked=True) is not True:
            return wait('government_permit_not_currently_effective_for_intended_action', [permit.ref])
        conditions = [read(ref, GovPermitConditionView) for ref in action_input.condition_refs]
        for condition in conditions:
            if condition.permit_ref != permit.ref or action.ref not in condition.action_refs or not scope_covers(scope, condition.scope):
                raise ValueError('Condition does not cover the original action or declared local scope')
            keys(condition.dependency_refs); keys(condition.evidence_refs_required)
            if not condition.effective_window.contains(now):
                _needs('current_original_permit_condition_version', [condition.ref])
        if profile.choice == 'request_condition_change':
            if 'request_change' not in authority.purposes or profile.selected_condition_ref not in action_input.condition_refs:
                _needs('original_authorized_selected_condition_change')
            if not profile.change_rule_refs or profile.change_reason is None:
                _needs('specific_original_condition_change_reason_and_rules')
            keys(profile.change_rule_refs)
            for ref in profile.change_rule_refs:
                basis = read(ref, GovPermitRuleView); bound(basis)
                if (basis.change is None or basis.change.condition_ref != profile.selected_condition_ref
                        or not basis.effective_window.contains(now) or not _known(basis.change.permitted, 'condition_change_rule_permission')):
                    raise ValueError('Condition-change request lacks original specific legal basis')
            return completed('request_condition_change', condition_ref=profile.selected_condition_ref,
                basis_refs=profile.change_rule_refs, reason=profile.change_reason)
        if 'verify' not in authority.purposes:
            _needs('independent_original_condition_verification_authority')
        if profile.choice == 'request_evidence':
            refs = list({ref.key(): ref for condition in conditions for ref in condition.question_refs}.values())
            output = questions(refs)
            if not output:
                _needs('specific_original_condition_evidence_questions')
            return completed('request_evidence', questions=output)
        dependencies = {}
        for ref in list({ref.key(): ref for ref in [*action.dependency_refs, *[r for c in conditions for r in c.dependency_refs]]}.values()):
            dep = read(ref, GovPermitDependencyView); bound(dep); author(dep)
            if not dep.effective_window.contains(now):
                _needs('current_original_cross_scope_permit_dependency', [ref])
            dependent_permit = read(dep.dependent_permit_ref, GovPermitView, linked=True)
            dependent_action = read(dep.dependent_action_ref, GovPermitActionView, linked=True)
            if (not scope_covers(dependent_permit.scope, dep.dependent_scope) or dependent_action.scope != dep.dependent_scope
                    or dependent_action.permit_ref != dependent_permit.ref or dependent_action.ref not in dependent_permit.allowed_action_refs):
                raise ValueError('Cross-scope dependency substitutes original dependent permit/action/scope')
            state, refs = 'unknown', [dep.ref, dependent_permit.ref, dependent_action.ref]
            dependent_effect = effective(dependent_permit, linked=True)
            if dependent_effect is False:
                state = 'nonconforms'
            if dep.verification_ref is not None:
                verified = read(dep.verification_ref, GovPermitDependencyVerificationView)
                author(verified, dep.dependent_scope, own=False)
                if (verified.dependency_ref != dep.ref or verified.dependent_permit_ref != dep.dependent_permit_ref
                        or verified.dependent_action_ref != dep.dependent_action_ref or verified.dependent_scope != dep.dependent_scope):
                    raise ValueError('Dependency verification substitutes actual cross-scope target')
                if verified.status == 'failed':
                    technical()
                if verified.status == 'unsupported':
                    _unsupported('government-permit-dependent-verification')
                if (verified.status == 'ok' and dependent_effect is True and verified.effective_window.contains(now)
                        and dependent_action.coverage == 'complete' and isinstance(verified.satisfied, Known)):
                    state = 'conforms' if verified.satisfied.value else 'nonconforms'
                refs.append(verified.ref)
            dependencies[ref.key()] = (state, refs)
        results = []
        for condition in conditions:
            complete = keys(condition.evidence_refs_required) <= keys(action_input.evidence_refs)
            data_refs = [permit.ref, action.ref, rule.ref, condition.ref, *condition.evidence_refs_required]
            measured, code = None, None
            actual = False
            if condition.fact_ref is not None:
                fact = read(condition.fact_ref, GovPermitFactView); bound(fact); author(fact, condition.scope)
                if fact.condition_ref != condition.ref or not scope_covers(fact.scope, condition.scope):
                    raise ValueError('Fulfillment fact substitutes original condition coverage')
                actual = fact.fulfillment == 'actual' and fact.effective_window.contains(now)
                complete &= keys(fact.evidence_refs) <= keys(action_input.evidence_refs)
                actual &= not any(sources[r.key()].basis_kind == 'assumed' for r in fact.evidence_refs)
                if actual:
                    measured, code = fact.measured_value, fact.code_value
                    if measured is not None and measured.state == 'known' and measured.value.basis_ref not in fact.evidence_refs:
                        raise ValueError('Condition quantity has no original verified fact basis')
                data_refs += [fact.ref, *fact.evidence_refs]
            states = []
            for ref in list({ref.key(): ref for ref in [*action.dependency_refs, *condition.dependency_refs]}.values()):
                state, refs = dependencies[ref.key()]; states.append(state); data_refs += refs
            data_refs = list({ref.key(): ref for ref in data_refs}.values())
            status, result_ref = 'undetermined', None
            if condition.criterion == 'unmodeled' or condition.method_ref != GOV_RULE_METHOD:
                _unsupported('government-permit-unmodeled-condition')
            if condition.result_ref is not None:
                saved = read(condition.result_ref, GovPermitResultView); bound(saved); grant = author(saved, condition.scope)
                if saved.condition_ref != condition.ref or saved.method_ref != GOV_RULE_METHOD or saved.scope != condition.scope:
                    raise ValueError('Saved condition result substitutes original condition or coverage')
                if saved.status == 'failed':
                    technical()
                if saved.status == 'unsupported':
                    _unsupported('government-permit-saved-verification')
                if saved.status == 'ok' and complete and saved.effective_window.contains(now):
                    data = GovRuleInput(criterion=condition.criterion, applicable=condition.applicable, measured_value=measured,
                        code_value=code, unit=condition.unit, minimum=condition.minimum, maximum=condition.maximum,
                        expected_code=condition.expected_code, professional_findings=states, professional_complete=True, source_refs=data_refs)
                    if saved.input_sha256 != content_digest(data) or not keys(data_refs) <= keys(grant.readable_refs):
                        raise ValueError('Saved condition verification changes original inputs or execution read authority')
                    if any(hasattr(sources[r.key()], 'available_at') and sources[r.key()].available_at.offset > saved.authored_at.offset for r in data_refs):
                        _needs('condition_verification_after_original_input_versions', [saved.ref])
                    report = reading.calculate(GOV_RULE_METHOD, data)
                    if report.kind != 'ok':
                        if report.kind == 'invalid_input':
                            raise ValueError('Condition arithmetic violates declared original rule domain')
                        raw = report.model_dump(mode='python')
                        if report.kind == 'needs_information':
                            raw['requested_refs'] = []
                        raise ObservationGap(raw)
                    if saved.report != report.value:
                        raise ValueError('Saved condition result differs from actual fulfillment and cross-scope dependencies')
                    result_ref = saved.ref
                    if isinstance(condition.applicable, Known) and condition.applicable.value:
                        status = {'conforms': 'satisfied', 'nonconforms': 'not_satisfied'}.get(report.value.finding, 'undetermined')
            results.append({'condition_ref': condition.ref, 'action_ref': action.ref, 'covered_scope': condition.scope,
                'result': status, 'evidence_refs': [ref for ref in condition.evidence_refs_required if ref in action_input.evidence_refs],
                'verification_result_ref': result_ref,
                'remaining_questions': questions(condition.question_refs, condition) if status == 'undetermined' else []})
        if not results:
            _needs('nonempty_original_conditions_for_this_verification')
        return completed('verify', results=results)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
