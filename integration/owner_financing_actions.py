"""Assemble authorized OWN-A05 funding inputs without creating financial effects."""
from dataclasses import dataclass
from typing import ClassVar

from integration.owner_observation_actions import OwnerObservationActionAssembler, PreparedOwnerObservation
from src.actions.contracts.owner_financing_objects import (
    FinancingArrangementView, FinancingCaseView, FinancingDebtView, FinancingOfferView,
    FinancingProfileView, FinancingProjectView, FinancingSourceView, owner_financing_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedOwnerFinancing(PreparedOwnerObservation):
    ACTION_ID: ClassVar[str] = 'OWN-A05'


class OwnerFinancingActionAssembler(OwnerObservationActionAssembler):
    """Preserve complete funding lines, debt identities and received offers.

    Owner and borrower identities remain distinct. The processor validates
    borrower authority, terms, cash timing and financing branches. Application
    code holds the current source/authorization guard; assembly forms no loan,
    application, acceptance, arrangement, reservation or cash movement.
    """
    ACTION_ID = 'OWN-A05'
    SOURCE_SCHEMAS = staticmethod(owner_financing_schemas)

    def build(self, context, *, scope_ref, borrower_id, funding_lines, debt_refs, offers, funding_profile_ref):
        return self._prepare_supplied_snapshot(context,
            input_values={'scope_ref': scope_ref, 'borrower_id': borrower_id, 'funding_lines': funding_lines,
                'debt_refs': debt_refs, 'offers': offers, 'funding_profile_ref': funding_profile_ref},
            prepared_type=PreparedOwnerFinancing, validate_sources=self._validate_financing_sources)

    def build_from_bank_quote(self, context, *, bank_quote, receipt_ref, validate_reception, **financing_inputs):
        """Bind a received actual offer to its original bank decision before Owner evaluation."""
        from integration.bank_quote_owner_financing_handoff import validate_received_financing_offer

        prepared = self.build(context, **financing_inputs)
        validate_received_financing_offer(bank_quote, prepared=prepared, receipt_ref=receipt_ref,
            validate_reception=validate_reception)
        return prepared

    @staticmethod
    def _validate_financing_sources(action_input, *, context, reading):
        validate_owner_financing_sources(action_input, context=context,
            organization_id=reading.organization_id, sources=reading._reads)


def validate_owner_financing_sources(action_input, *, context, organization_id, sources):
    """Check original supplied identities without evaluating financial feasibility."""
    profile = sources.get(action_input.funding_profile_ref.key())
    scope = action_input.scope_ref
    if (not isinstance(profile, FinancingProfileView) or profile.organization_id != organization_id
            or profile.borrower_id != action_input.borrower_id or profile.scope_ref != scope
            or not scope_covers(context.scope, scope)):
        raise TaskConflict('Owner financing changes its original owner, borrower, profile or scope')
    unique_refs(action_input.debt_refs)
    unique_refs(action_input.offers)
    if ({ref.key() for ref in action_input.debt_refs} != {ref.key() for ref in profile.debt_refs}
            or [line.model_dump(mode='json') for line in action_input.funding_lines]
                != [line.model_dump(mode='json') for line in profile.funding_lines]):
        raise TaskConflict('Owner financing omits or changes the complete original debt portfolio or funding lines')
    if scope.kind == 'organization':
        if scope.ref.id != organization_id:
            raise TaskConflict('Owner financing changes the original owner organization scope')
    else:
        parent = sources.get(scope.ref.key())
        schema, field = (FinancingCaseView, 'organization_id') if scope.kind == 'assessment_case' else (
            FinancingProjectView, 'owner_organization_id')
        if not isinstance(parent, schema) or getattr(parent, field) != organization_id:
            raise TaskConflict('Owner financing parent belongs to another owner')
    for ref in action_input.debt_refs:
        debt = sources.get(ref.key())
        if not isinstance(debt, FinancingDebtView) or debt.borrower_id != action_input.borrower_id:
            raise TaskConflict('Owner financing substitutes another borrower debt')
    for ref in action_input.offers:
        offer = sources.get(ref.key())
        if not isinstance(offer, FinancingOfferView):
            raise TaskConflict('Owner financing changes the original received offer projection')
    # Only check private output dependencies actually supplied. The processor
    # retains no_finance/defer and missing-information branches unchanged.
    for refs, schema, field in ((profile.source_refs, FinancingSourceView, 'organization_id'),
            (profile.arrangement_refs, FinancingArrangementView, 'borrower_id')):
        for ref in refs:
            source = sources.get(ref.key())
            if source is not None and (not isinstance(source, schema) or getattr(source, field) != action_input.borrower_id):
                raise TaskConflict('Owner financing imports another borrower source or arrangement')
