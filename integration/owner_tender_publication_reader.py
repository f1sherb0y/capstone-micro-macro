"""Read original formal Owner publication/invitation for Contractor tender intake."""
from integration.owner_tender_actions import OwnerTenderActionAssembler
from integration.owner_tender_results import OwnerTenderResultWorker
from integration.owner_contractor_tender_handoff import OwnerTenderPublicationSource
from integration.owner_publication_reader import OwnerPublicationReader, OwnerPublicationReaderSettings


class OwnerTenderPublicationReaderSettings(OwnerPublicationReaderSettings):
    pass


class OwnerTenderPublicationReader(OwnerPublicationReader):
    ACTION_ID = 'OWN-A09'
    RECIPIENT_ACTION_ID = 'CONTRACTOR-A02'
    EXPECTED_CHOICES = frozenset({'publish_package', 'invite'})
    RECEIPT_SCHEMA = 'owner-tender-saved-receipt.v1'
    PUBLICATION_SOURCE_TYPE = OwnerTenderPublicationSource
    SETTINGS_TYPE = OwnerTenderPublicationReaderSettings
    WORKER_TYPE = OwnerTenderResultWorker
    ASSEMBLER_TYPE = OwnerTenderActionAssembler

    def required_shared_refs(self, saved):
        if saved.result.payload.choice == 'publish_package':
            return {saved.result.payload.package.submission_window_ref.key()}
        return {saved.action_input.package_context.package_ref.key()}
