"""Assemble original OWN-A13 inputs without releasing resources or extinguishing debt."""
from dataclasses import dataclass
from typing import ClassVar

from integration.owner_observation_actions import OwnerObservationActionAssembler, PreparedOwnerObservation
from src.actions.contracts.owner_continuation_objects import (
    OwnerContinuationCommitmentView, OwnerContinuationContractView,
    OwnerContinuationExecutionView, OwnerContinuationProfileView,
    OwnerContinuationRiskView, OwnerContinuationRuleView, OwnerContinuationStateView,
    OwnerContinuationTransferPlanView, OwnerPaymentObligationView,
    OwnerResourceReleaseRuleView, owner_continuation_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class PreparedOwnerContinuation(PreparedOwnerObservation):
    ACTION_ID: ClassVar[str] = 'OWN-A13'


class OwnerContinuationActionAssembler(OwnerObservationActionAssembler):
    """Keep exact risks, contracts, commitments, obligations and decision profile.

    Applications hold their current source/authorization guard. Completeness,
    continuing duties, unknown executions and exit/resume conditions remain
    original processor checks. Assembly changes no ledger or business status.
    """
    ACTION_ID = 'OWN-A13'
    SOURCE_SCHEMAS = staticmethod(owner_continuation_schemas)

    def build(self, context, *, scope_ref, risk_refs, contract_refs, resource_refs,
            obligation_refs, continuation_profile_ref):
        return self._prepare_supplied_snapshot(context,
            input_values={'scope_ref': scope_ref, 'risk_refs': risk_refs,
                'contract_refs': contract_refs, 'resource_refs': resource_refs,
                'obligation_refs': obligation_refs, 'continuation_profile_ref': continuation_profile_ref},
            prepared_type=PreparedOwnerContinuation, validate_sources=self._validate_continuation_sources)

    @staticmethod
    def _validate_continuation_sources(action_input, *, context, reading):
        validate_owner_continuation_sources(action_input, context=context,
            organization_id=reading.organization_id, sources=reading._reads)


def validate_owner_continuation_sources(action_input, *, context, organization_id, sources):
    """Validate supplied original identities without deciding exit or release."""
    profile = sources.get(action_input.continuation_profile_ref.key())
    if (action_input.scope_ref != context.scope or not isinstance(profile, OwnerContinuationProfileView)
            or profile.organization_id != organization_id or profile.actor_id != context.actor_id
            or profile.function_ref.key() != context.function_ref.key() or profile.scope != context.scope
            or profile.authority_ref.key() not in {ref.key() for ref in context.authorization_refs}):
        raise TaskConflict('Owner continuation changes the original scope, profile owner, actor or authority')
    state = sources.get(profile.state_ref.key())
    if state is not None and (not isinstance(state, OwnerContinuationStateView)
            or state.organization_id != organization_id or state.scope != context.scope):
        raise TaskConflict('Owner continuation changes its original ledger owner or scope')
    for refs in (action_input.risk_refs, action_input.contract_refs,
            action_input.resource_refs, action_input.obligation_refs):
        unique_refs(refs)
    for ref in action_input.risk_refs:
        risk = sources.get(ref.key())
        if not isinstance(risk, OwnerContinuationRiskView) or risk.organization_id != organization_id:
            raise TaskConflict('Owner continuation risk changes the original owner')
    for ref in action_input.contract_refs:
        contract = sources.get(ref.key())
        if not isinstance(contract, OwnerContinuationContractView) or contract.owner_id != organization_id:
            raise TaskConflict('Owner continuation substitutes another owner contract')
        rule = sources.get(contract.rule_ref.key())
        if rule is not None and (not isinstance(rule, OwnerContinuationRuleView)
                or rule.contract_ref is None or rule.contract_ref.key() != contract.ref.key()):
            raise TaskConflict('Owner continuation contract rule changes its original contract')
    for ref in action_input.resource_refs:
        commitment = sources.get(ref.key())
        if not isinstance(commitment, OwnerContinuationCommitmentView) or commitment.owner_id != organization_id:
            raise TaskConflict('Owner continuation substitutes another owner resource commitment')
        rule = sources.get(commitment.release_rule_ref.key())
        if rule is not None and (not isinstance(rule, OwnerResourceReleaseRuleView)
                or rule.commitment_ref.key() != commitment.ref.key()):
            raise TaskConflict('Owner continuation release rule changes the original commitment')
    for ref in action_input.obligation_refs:
        if not isinstance(sources.get(ref.key()), OwnerPaymentObligationView):
            raise TaskConflict('Owner continuation changes an original obligation projection')
    if isinstance(state, OwnerContinuationStateView):
        rule = sources.get(state.scope_rule_ref.key())
        if rule is not None and (not isinstance(rule, OwnerContinuationRuleView) or rule.contract_ref is not None):
            raise TaskConflict('Owner continuation scope rule substitutes a contract-specific rule')
        for ref in state.execution_refs:
            execution = sources.get(ref.key())
            if execution is not None and (not isinstance(execution, OwnerContinuationExecutionView)
                    or execution.organization_id != organization_id or execution.run_id != context.run_id
                    or (execution.state_ref.kind, execution.state_ref.id) != (state.ref.kind, state.ref.id)):
                raise TaskConflict('Owner continuation history changes its original owner, run or physical state')
            if execution is not None and execution.business_key == profile.business_key:
                original = sources.get(execution.profile_ref.key())
                if original is not None and (not isinstance(original, OwnerContinuationProfileView)
                        or original.state_ref != execution.state_ref or original.organization_id != execution.organization_id
                        or original.scope != execution.scope or original.business_key != execution.business_key):
                    raise TaskConflict('Owner continuation execution changes its original profile state or scope')
    if profile.transfer_plan_ref is not None:
        plan = sources.get(profile.transfer_plan_ref.key())
        if plan is not None and (not isinstance(plan, OwnerContinuationTransferPlanView)
                or plan.state_ref.key() != profile.state_ref.key()):
            raise TaskConflict('Owner continuation transfer plan substitutes another original state')
    # Original processor retains incomplete histories, unconfirmed executions,
    # current readiness/authority and all suspend/reduce/remedy/replace/transfer/
    # terminate/resume branches; none of these source identities proves release.
