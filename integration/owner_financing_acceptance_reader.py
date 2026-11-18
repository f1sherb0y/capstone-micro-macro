"""Read original Owner acceptance of exact Bank offer terms for independent arrangement."""
from integration.owner_financing_application_reader import (
    OwnerFinancingApplicationReader, OwnerFinancingApplicationReaderSettings, _bind_owner_financing_bank_sources,
)
from src.coordination.tasks import TaskConflict


class OwnerFinancingAcceptanceReaderSettings(OwnerFinancingApplicationReaderSettings):
    """Original Owner A05 history and exact current Bank A05 recipient context."""


class OwnerFinancingAcceptanceReader(OwnerFinancingApplicationReader):
    """Reuse original journal, full snapshots, source guard and sharing validator.

    Only accept_offer supplies this history. Actual party acceptance, recorded
    decision, original terms/reservation and withdrawal history still require
    independently observed Bank reception. Reading performs no registration,
    confirmation, signature, arrangement formation or model invocation.
    """
    SETTINGS_TYPE = OwnerFinancingAcceptanceReaderSettings
    RECIPIENT_ACTION_ID = 'BANK-A05'
    EXPECTED_CHOICES = frozenset({'accept_offer'})

    def required_shared_refs(self, saved):
        offer = saved.result.payload.offer_ref
        if offer is None or offer not in saved.action_input.offers:
            raise TaskConflict('Original Owner acceptance lacks its exact selected offer version')
        return {saved.action_input.scope_ref.ref.key(), saved.action_input.funding_profile_ref.key(), offer.key()}


def bind_owner_financing_acceptance_sources(*, sources, reader, validate_reception, version):
    if not isinstance(reader, OwnerFinancingAcceptanceReader):
        raise ValueError('Owner acceptance binding requires the concrete original acceptance reader')
    return _bind_owner_financing_bank_sources(sources=sources, reader=reader,
        validate_reception=validate_reception, version=version, recipient_action='BANK-A05',
        validator_field='validate_owner_acceptance_reception', evidence_field='v5_owner_acceptance_binding')
