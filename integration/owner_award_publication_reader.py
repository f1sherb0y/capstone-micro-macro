"""Read original formal Owner acceptance for Contractor agreement reception."""
from integration.owner_award_actions import OwnerAwardActionAssembler
from integration.owner_award_results import OwnerAwardResultWorker
from integration.owner_contractor_award_handoff import OwnerAwardPublicationSource
from integration.owner_publication_reader import OwnerPublicationReader, OwnerPublicationReaderSettings


class OwnerAwardPublicationReaderSettings(OwnerPublicationReaderSettings):
    pass


class OwnerAwardPublicationReader(OwnerPublicationReader):
    ACTION_ID = 'OWN-A10'
    RECIPIENT_ACTION_ID = 'CONTRACTOR-A04'
    EXPECTED_CHOICES = frozenset({'accept'})
    RECEIPT_SCHEMA = 'owner-award-saved-receipt.v1'
    PUBLICATION_SOURCE_TYPE = OwnerAwardPublicationSource
    SETTINGS_TYPE = OwnerAwardPublicationReaderSettings
    WORKER_TYPE = OwnerAwardResultWorker
    ASSEMBLER_TYPE = OwnerAwardActionAssembler

    def required_shared_refs(self, saved):
        return {saved.result.payload.offer_ref.key(), saved.result.payload.terms_ref.key()}
