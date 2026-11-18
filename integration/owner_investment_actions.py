"""Assemble explicit authorized OWN-A03 investment comparison inputs."""
from dataclasses import dataclass
from typing import ClassVar

from integration.owner_observation_actions import OwnerObservationActionAssembler, PreparedOwnerObservation
from src.actions.contracts.owner_investment_objects import (
    InvestmentCaseView, InvestmentComparisonView, InvestmentFundingSourceView, InvestmentObjectiveView,
    InvestmentObligationView, InvestmentOptionView, InvestmentPortfolioView, InvestmentRegistrationView,
    InvestmentResourceView, owner_investment_schemas,
)
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class PreparedOwnerInvestment(PreparedOwnerObservation):
    ACTION_ID: ClassVar[str] = 'OWN-A03'


class OwnerInvestmentActionAssembler(OwnerObservationActionAssembler):
    """Keep complete funding lines and independently supplied current portfolio.

    Preparing creates no project, investment, rights, reservation or financing.
    Original A03 methods retain all comparison, timing and resource decisions.
    The application holds its actual source/authorization guard.
    """
    ACTION_ID = 'OWN-A03'
    SOURCE_SCHEMAS = staticmethod(owner_investment_schemas)

    def build(self, context, *, case_ref, comparison_ref, objective_ref, funding_lines,
            portfolio_ref, registration_profile_ref):
        return self._prepare_supplied_snapshot(context,
            input_values={'case_ref': case_ref, 'comparison_ref': comparison_ref, 'objective_ref': objective_ref,
                'funding_lines': funding_lines, 'portfolio_ref': portfolio_ref,
                'registration_profile_ref': registration_profile_ref}, prepared_type=PreparedOwnerInvestment,
            validate_sources=self._validate_investment_sources)

    def build_from_qs_research(self, context, *, saved_research, receipt_ref,
            validate_reception, **investment_inputs):
        """Consume a separately received QS report with supplied A03 analyses.

        The application holds its existing source guard. No QS cost, rank or
        limited report is converted into a lifecycle forecast or owner choice.
        """
        from integration.qs_research_investment_handoff import validate_received_qs_research

        prepared = self.build(context, **investment_inputs)
        validate_received_qs_research(saved_research, prepared=prepared,
            receipt_ref=receipt_ref, validate_reception=validate_reception)
        return prepared

    @staticmethod
    def _validate_investment_sources(action_input, *, context, reading):
        validate_owner_investment_sources(action_input, context=context,
            organization_id=reading.organization_id, sources=reading._reads)


def validate_owner_investment_sources(action_input, *, context, organization_id, sources):
    """Check original input/source relations without calculating an investment."""
    case = sources.get(action_input.case_ref.key())
    comparison = sources.get(action_input.comparison_ref.key())
    objective = sources.get(action_input.objective_ref.key())
    portfolio = sources.get(action_input.portfolio_ref.key())
    profile = sources.get(action_input.registration_profile_ref.key())
    for source, schema in ((case, InvestmentCaseView), (comparison, InvestmentComparisonView),
            (objective, InvestmentObjectiveView), (portfolio, InvestmentPortfolioView),
            (profile, InvestmentRegistrationView)):
        if not isinstance(source, schema) or source.organization_id != organization_id:
            raise TaskConflict('Owner investment changes its original private case/comparison/objective/portfolio/profile owner')
    if (case.objective_ref.key() != objective.ref.key() or comparison.case_ref.key() != case.ref.key()
            or comparison.objective_ref.key() != objective.ref.key() or profile.case_ref.key() != case.ref.key()
            or profile.comparison_ref.key() != comparison.ref.key()
            or comparison.ref.key() not in {ref.key() for ref in case.comparison_refs}
            or context.scope.kind != 'assessment_case' or context.scope.ref.key() != case.ref.key()
            or comparison.scope.kind != 'assessment_case' or comparison.scope.ref.key() != case.ref.key()):
        raise TaskConflict('Owner investment changes its original case/objective/comparison relation or invocation scope')
    supplied = [line.model_dump(mode='json') for line in action_input.funding_lines]
    if supplied != [line.model_dump(mode='json') for line in portfolio.funding_lines]:
        raise TaskConflict('Owner investment input omits or changes the complete original portfolio funding lines')
    # Preserve supplied dependencies; reject/defer/followup can remain valid
    # without dependencies used only by later investment branches.
    for refs, schema, owner_field in ((portfolio.source_refs, InvestmentFundingSourceView, 'organization_id'),
            (portfolio.resource_refs, InvestmentResourceView, 'organization_id'),
            (portfolio.obligation_refs, InvestmentObligationView, 'debtor_organization_id')):
        for ref in refs:
            source = sources.get(ref.key())
            if source is not None and (not isinstance(source, schema) or getattr(source, owner_field) != organization_id):
                raise TaskConflict('Owner investment portfolio substitutes another owner cash, resource or debt')
    for ref in comparison.option_refs:
        option = sources.get(ref.key())
        if option is not None and (not isinstance(option, InvestmentOptionView)
                or option.organization_id != organization_id or option.case_ref.key() != case.ref.key()
                or option.comparison_ref.key() != comparison.ref.key() or option.objective_ref.key() != objective.ref.key()):
            raise TaskConflict('Owner investment option changes its original owner/case/comparison/objective')
