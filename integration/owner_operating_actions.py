"""Assemble original OWN-A15 private operating inputs without applying policy or budgets."""
from dataclasses import dataclass
from typing import ClassVar

from integration.owner_observation_actions import OwnerObservationActionAssembler, PreparedOwnerObservation
from src.actions.contracts.owner_operating_objects import (
    OwnerAllocationRevisionView, OwnerLearningAssessmentView, OwnerLearningMethodView,
    OwnerOperatingCommitmentView, OwnerOperatingExecutionView, OwnerOperatingObservationView,
    OwnerOperatingPortfolioView, OwnerOperatingPreferenceView, OwnerOperatingProfileView,
    OwnerOperatingProjectView, OwnerOperatingResourceView, OwnerOperatingTaskView,
    OwnerPaymentObligationView, OwnerResearchBudgetView, owner_operating_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.service_objects import ServiceScopeOrganizationView
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class PreparedOwnerOperating(PreparedOwnerObservation):
    ACTION_ID: ClassVar[str] = 'OWN-A15'


class OwnerOperatingActionAssembler(OwnerObservationActionAssembler):
    """Keep the whole supplied portfolio, private observations and optional method.

    Applications hold their current source/authorization guard. Completeness,
    outcome maturity, prior applications, learning and rebalance calculations
    remain original processor checks. Assembly applies no preference, research
    limit, task allocation, resource commitment or cash change.
    """
    ACTION_ID = 'OWN-A15'
    SOURCE_SCHEMAS = staticmethod(owner_operating_schemas)

    def build(self, context, *, organization_ref, portfolio_ref, obligation_refs,
            observation_refs, operating_profile_ref, learning_method_ref):
        return self._prepare_supplied_snapshot(context,
            input_values={'organization_ref': organization_ref, 'portfolio_ref': portfolio_ref,
                'obligation_refs': obligation_refs, 'observation_refs': observation_refs,
                'operating_profile_ref': operating_profile_ref, 'learning_method_ref': learning_method_ref},
            prepared_type=PreparedOwnerOperating, validate_sources=self._validate_operating_sources)

    @staticmethod
    def _validate_operating_sources(action_input, *, context, reading):
        validate_owner_operating_sources(action_input, context=context,
            organization_id=reading.organization_id, sources=reading._reads)


def validate_owner_operating_sources(action_input, *, context, organization_id, sources):
    """Check original private source identities without claiming effective learning."""
    organization = sources.get(action_input.organization_ref.key())
    portfolio = sources.get(action_input.portfolio_ref.key())
    profile = sources.get(action_input.operating_profile_ref.key())
    if (not isinstance(organization, ServiceScopeOrganizationView) or organization.ref.id != organization_id
            or not isinstance(portfolio, OwnerOperatingPortfolioView) or portfolio.organization_id != organization_id
            or not isinstance(profile, OwnerOperatingProfileView) or profile.organization_id != organization_id
            or profile.portfolio_ref.key() != portfolio.ref.key() or profile.actor_id != context.actor_id
            or profile.function_ref.key() != context.function_ref.key()
            or profile.authority_ref.key() not in {ref.key() for ref in context.authorization_refs}
            or profile.scope != context.scope or portfolio.scope != context.scope):
        raise TaskConflict('Owner operations change the original organization, portfolio, actor, scope or authority')

    def own_source(ref, schema, *, required=False):
        source = sources.get(ref.key())
        if source is None and not required:
            return None
        if not isinstance(source, schema) or source.organization_id != organization_id:
            raise TaskConflict('Owner operating source substitutes another original private organization or projection')
        return source

    unique_refs(action_input.obligation_refs)
    unique_refs(action_input.observation_refs)
    for ref in action_input.obligation_refs:
        if not isinstance(sources.get(ref.key()), OwnerPaymentObligationView):
            raise TaskConflict('Owner operations change an original obligation projection')
    for ref in action_input.observation_refs:
        observation = sources.get(ref.key())
        if not isinstance(observation, OwnerOperatingObservationView) or observation.recipient_organization_id != organization_id:
            raise TaskConflict('Owner operations substitute another recipient private observation')
    if action_input.learning_method_ref is not None:
        own_source(action_input.learning_method_ref, OwnerLearningMethodView, required=True)
    for refs, schema in ((portfolio.project_refs, OwnerOperatingProjectView),
            (portfolio.task_refs, OwnerOperatingTaskView), (portfolio.resource_refs, OwnerOperatingResourceView)):
        for ref in refs:
            source = own_source(ref, schema)
            if isinstance(source, OwnerOperatingResourceView):
                for commitment_ref in source.commitment_refs:
                    commitment = own_source(commitment_ref, OwnerOperatingCommitmentView)
                    if commitment is not None and commitment.resource_ref.key() != source.ref.key():
                        raise TaskConflict('Owner operating commitment changes its original resource pool')
    own_source(portfolio.current_preference_ref, OwnerOperatingPreferenceView)
    if profile.preference_profile_ref is not None:
        proposed = own_source(profile.preference_profile_ref, OwnerOperatingPreferenceView)
        if proposed is not None and proposed.learning_assessment_ref is not None:
            assessment = own_source(proposed.learning_assessment_ref, OwnerLearningAssessmentView)
            if assessment is not None and assessment.preference_profile_ref.key() != proposed.ref.key():
                raise TaskConflict('Owner learning assessment changes its original proposed preference profile')
    if profile.budget_authority_ref is not None:
        own_source(profile.budget_authority_ref, OwnerResearchBudgetView)
    if profile.allocation_revision_ref is not None:
        revision = own_source(profile.allocation_revision_ref, OwnerAllocationRevisionView)
        if revision is not None and revision.portfolio_ref.key() != portfolio.ref.key():
            raise TaskConflict('Owner allocation revision changes its original portfolio')
    for ref in portfolio.execution_refs:
        execution = own_source(ref, OwnerOperatingExecutionView)
        if execution is not None and execution.run_id != context.run_id:
            raise TaskConflict('Owner operating execution changes its original run')
        if execution is not None and execution.business_key == profile.business_key:
            original = sources.get(execution.profile_ref.key())
            if original is not None and (not isinstance(original, OwnerOperatingProfileView)
                    or original.organization_id != execution.organization_id or original.scope != execution.scope
                    or original.business_key != execution.business_key):
                raise TaskConflict('Owner operating execution changes its original profile organization or scope')
    # Original processor retains all debts, complete/current histories, native
    # applied observations and future-only policy/budget/allocation semantics.
