"""Recover GOV-A08 permit effect without treating it as fulfillment or execution permission."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Known, ref_type, walk_references
from src.actions.contracts.government_permit_objects import (
    GovPermitView, GovPermitActionView, GovPermitRuleView, GovPermitAuthorityView,
    GovPermitDecisionView, GovPermitEffectView,
)
from src.actions.contracts.government_decision_objects import GovDecisionNotificationView
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


_CODE = 'government_permit_not_currently_effective_for_intended_action'
_CODES = (_CODE,)
_FIELDS = frozenset({'scope', 'permit_ref', 'intended_action_ref', 'condition_refs', 'evidence_refs', 'verification_rule_ref'})
_BASES = (('permit_ref', 'Permit', GovPermitView), ('intended_action_ref', 'ActionDefinition', GovPermitActionView),
    ('verification_rule_ref', 'Rule', GovPermitRuleView))


@dataclass(frozen=True)
class GovernmentPermitConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict
    original_context: ActionContext
    permit_sources: list[dict] | None = None
    unavailable_targets: list[dict] | None = None


def government_original_permit_effect_profile(read_current, validate_relation):
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Permit effect recovery requires guarded sources and independent native validation')

    def identities(refs):
        result = {ref.key()[:2] for ref in refs}
        if len(result) != len(refs):
            raise TaskConflict('Permit effect recovery duplicates a physical source')
        return result

    def physical(value):
        if isinstance(value, dict):
            return {key: physical(item) for key, item in value.items()
                if not (key == 'version' and set(value) == {'kind', 'id', 'version'})}
        if isinstance(value, list):
            return [physical(item) for item in value]
        return value

    def evaluate(check):
        source = check.source['identity']
        if (source['action_id'] != 'GOV-A08' or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in check.condition.object_refs) != ('Permit',)
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Permit effect recovery replaces original action/permit wait/agency')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, GovernmentPermitConditionReading) or not isinstance(selected.context, ActionContext)
                or not isinstance(selected.original_context, ActionContext) or not isinstance(selected.reading, ActionReadView)):
            raise TaskConflict('Permit effect recovery requires typed original/current sources and contexts')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
        try:
            if (set(raw) != _FIELDS or set(current_raw) != _FIELDS or task_digest(raw) != source['input_sha256']
                    or task_digest(selected.original_context.model_dump(mode='json')) != source['context_sha256']
                    or raw['scope'] != current_raw['scope'] or context.run_id != source['run_id']
                    or context.contract_ref.id != 'GOV-A08' or context.execution_mode != 'llm'
                    or context.operation_id == source['request_id'] or context.business_time != check.signal.business_time
                    or reading._resolver.source_mode != 'formal' or reading.organization_id != source['organization_id']
                    or context.scope != selected.original_context.scope
                    or context.business_time.clock_ref != selected.original_context.business_time.clock_ref
                    or context.business_time.offset < selected.original_context.business_time.offset):
                raise TaskConflict('Permit effect recovery changes original scope/snapshot or current invocation')
            reading.check_method_context(context, 'GOV-A08')
            proof_rows, proof_refs, versions = [], [], []

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref:
                    raise TaskConflict('Permit effect recovery lacks exact original/current source versions')
                proof_rows.append(row)
                return row

            def effect_state(permit, at):
                if (permit.status != 'valid' or not permit.effective_window.contains(at)
                        or not isinstance(permit.effective, Known) or not permit.effective.value):
                    return False
                decision = read(permit.decision_ref, GovPermitDecisionView)
                if (decision.permit_ref != permit.ref or decision.outcome not in {'approve', 'approve_with_conditions'}
                        or not scope_covers(decision.scope, permit.scope)):
                    raise TaskConflict('Permit effect recovery substitutes original scoped formal approval')
                if (decision.available_at.clock_ref != at.clock_ref or decision.available_at.offset > at.offset
                        or not isinstance(decision.effective, Known) or not decision.effective.value):
                    return False
                effect = read(decision.effect_rule_ref, GovPermitEffectView)
                if effect.decision_ref != decision.ref:
                    raise TaskConflict('Permit effect recovery substitutes the original legal effect rule')
                if effect.available_at.clock_ref != at.clock_ref or effect.available_at.offset > at.offset:
                    return False
                if effect.mode == 'on_actual_delivery':
                    identities(decision.notification_refs)
                    delivered = set()
                    for ref in decision.notification_refs:
                        row = read(ref, GovDecisionNotificationView)
                        if row.decision_ref != decision.ref or row.recipient_id not in effect.notification_recipient_ids:
                            raise TaskConflict('Permit effect recovery borrows another original notification or recipient')
                        if row.status == 'delivered':
                            if (row.delivered_at is None or row.delivered_at.clock_ref != at.clock_ref
                                    or row.available_at.clock_ref != at.clock_ref or row.delivered_at.offset > row.available_at.offset
                                    or row.available_at.offset > at.offset or not row.evidence_refs):
                                raise TaskConflict('Permit effect recovery lacks observed actual delivery at the original time')
                            delivered.add(row.recipient_id)
                    if (not effect.notification_recipient_ids or len(set(effect.notification_recipient_ids)) != len(effect.notification_recipient_ids)
                            or delivered != set(effect.notification_recipient_ids)):
                        return False
                return True

            for action_input, invocation in ((raw, selected.original_context), (current_raw, context)):
                rows = {field: read(ref_type(kind).model_validate(action_input[field]), schema) for field, kind, schema in _BASES}
                permit, action, rule = (rows[field] for field, _, _ in _BASES)
                profile = rule.verification
                if (permit.organization_id != source['organization_id'] or action.permit_ref != permit.ref
                        or rule.permit_ref != permit.ref or rule.action_ref != action.ref or profile is None
                        or profile.organization_id != source['organization_id'] or action.scope.model_dump(mode='json') != action_input['scope']
                        or not scope_covers(permit.scope, action.scope) or not scope_covers(invocation.scope, action.scope)
                        or not scope_covers(action.scope, rule.scope) or action.coverage != 'complete'
                        or action.ref not in permit.allowed_action_refs):
                    raise TaskConflict('Permit effect recovery changes original agency/action coverage/rule purpose')
                condition_refs = [ref_type('PermitCondition').model_validate(ref) for ref in action_input['condition_refs']]
                evidence_refs = [ref_type('Evidence').model_validate(ref) for ref in action_input['evidence_refs']]
                if ({ref.key() for ref in condition_refs} != {ref.key() for ref in action.applicable_condition_refs}
                        or not {ref.key() for ref in condition_refs} <= {ref.key() for ref in permit.condition_refs}):
                    raise TaskConflict('Permit effect recovery loses original complete action-specific conditions')
                for refs in (permit.condition_refs, permit.allowed_action_refs, action.applicable_condition_refs,
                        action.dependency_refs, condition_refs, evidence_refs):
                    identities(refs)
                authority = read(profile.verification_authority_ref, GovPermitAuthorityView)
                grant, function = reading.resolve(profile.authority_ref), reading.resolve(invocation.function_ref)
                if (authority.permit_ref != permit.ref or authority.action_ref != action.ref
                        or authority.organization_id != source['organization_id'] or authority.actor_id != invocation.actor_id
                        or authority.function_ref != invocation.function_ref
                        or not {ref.key() for ref in condition_refs} <= {ref.key() for ref in authority.condition_refs}
                        or not isinstance(authority.permitted, Known) or not authority.permitted.value
                        or not isinstance(grant, Authorization) or grant.ref != profile.authority_ref
                        or not isinstance(function, RoleAssignment) or function.function_ref != invocation.function_ref
                        or function.role != 'Government' or grant.actor_id != invocation.actor_id
                        or grant.organization_id != source['organization_id'] or grant.function_ref != invocation.function_ref
                        or 'GOV-A08' not in grant.action_ids or not grant.validity.contains(invocation.business_time)
                        or not any(scope_covers(covered, action.scope) for covered in grant.scopes)
                        or any(row.available_at.clock_ref != invocation.business_time.clock_ref
                            or row.available_at.offset > invocation.business_time.offset for row in (permit, action, rule, authority))
                        or not rule.effective_window.contains(invocation.business_time)
                        or not authority.effective_window.contains(invocation.business_time)):
                    raise TaskConflict('Permit effect recovery lacks actual independent original/current verifier authority')
                proof_refs.extend([*evidence_refs, *grant.basis_refs, *function.basis_refs])
                versions.append(dict(**rows, authority=authority, conditions=condition_refs, evidence=evidence_refs,
                    effective=effect_state(permit, invocation.business_time)))
            old, current = versions
            permit, action, rule = (current[field] for field, _, _ in _BASES)
            if tuple(check.condition.object_refs) != (old['permit_ref'].ref,) or old['effective']:
                raise TaskConflict('Permit effect recovery differs from original emitted ineffective-permit wait')
            if (any(old[field].ref.key()[:2] != current[field].ref.key()[:2] for field, _, _ in _BASES)
                    or old['permit_ref'].scope != permit.scope
                    or old['permit_ref'].decision_ref.key()[:2] != permit.decision_ref.key()[:2]
                    or identities(old['permit_ref'].condition_refs) != identities(permit.condition_refs)
                    or identities(old['permit_ref'].allowed_action_refs) != identities(permit.allowed_action_refs)
                    or identities(old['intended_action_ref'].dependency_refs) != identities(action.dependency_refs)
                    or identities(old['conditions']) != identities(current['conditions'])
                    or identities(old['evidence']) - identities(current['evidence'])
                    or physical(old['verification_rule_ref'].verification.model_dump(mode='json')) != physical(rule.verification.model_dump(mode='json'))
                    or old['authority'].ref.key()[:2] != current['authority'].ref.key()[:2]):
                raise TaskConflict('Permit effect recovery rewrites original intended action/conditions/dependencies/legal rule')
            if not current['effective']:
                return 'waiting'
            proof_refs.extend(ref for row in proof_rows for ref in walk_references(row) if ref.kind == 'Evidence')
            evidence = {}
            for ref in proof_refs:
                row = reading.resolve(ref)
                if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                    raise TaskConflict('Permit effect recovery requires observed original approval, actual delivery and authority evidence')
                evidence[ref.key()] = row.model_dump(mode='json')
            if validate_relation(source_identity=deepcopy(source), condition_code=_CODE,
                    original_action_input=raw, action_input=current_raw,
                    original_context=selected.original_context.model_dump(mode='json'),
                    permit_sources=deepcopy(selected.permit_sources), unavailable_targets=deepcopy(selected.unavailable_targets),
                    evidence=list(evidence.values()), context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('Permit effect recovery lacks native original approval/history/effect and retained fulfillment authentication')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('GOV-A08', _CODE, '1', frozenset({'dependency_change'}), evaluate)
