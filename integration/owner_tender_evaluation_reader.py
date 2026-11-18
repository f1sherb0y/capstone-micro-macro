"""Read an original formal tender evaluation for an explicit same-Owner selection."""
from integration.owner_contractor_tender_handoff import OwnerTenderPublicationSource
from integration.owner_publication_reader import OwnerPublicationReader, OwnerPublicationReaderSettings
from integration.owner_tender_actions import OwnerTenderActionAssembler
from integration.owner_tender_results import OwnerTenderResultWorker
from src.actions.contracts.common import ref_type
from src.coordination.tasks import TaskConflict


class OwnerTenderEvaluationReaderSettings(OwnerPublicationReaderSettings):
    selected_bid_ref: ref_type('Bid')
    selection_authorized: bool


class OwnerTenderEvaluationReader(OwnerPublicationReader):
    """Wire ``read`` to OwnerRoleContractSources.read_tender_evaluation.

    Ranking membership permits reading the candidate, not awarding it. Current
    same-Owner permission, explicit selection and original accepted evaluation
    receipt are required. Native Offer/terms mapping and tie treatment remain
    independently validated by validate_tender_award_selection at reception.
    """

    ACTION_ID = 'OWN-A09'
    RECIPIENT_ACTION_ID = 'OWN-A10'
    EXPECTED_CHOICES = frozenset({'evaluate'})
    RECEIPT_SCHEMA = 'owner-tender-saved-receipt.v1'
    PUBLICATION_SOURCE_TYPE = OwnerTenderPublicationSource
    SETTINGS_TYPE = OwnerTenderEvaluationReaderSettings
    WORKER_TYPE = OwnerTenderResultWorker
    ASSEMBLER_TYPE = OwnerTenderActionAssembler

    def required_shared_refs(self, saved):
        return {self.settings.selected_bid_ref.key()}

    def _validate_saved(self, saved, reading):
        settings = self.settings
        recipient = self.assembler.organizations.grants(settings.recipient_context, 'OWN-A10', 'Owner')
        if (settings.selection_authorized is not True or not recipient
                or recipient[0].organization_id != settings.identity.organization_id
                or saved.action_input.package_context.kind != 'published'
                or saved.result.kind != 'completed' or saved.result.payload.choice != 'evaluate'
                or settings.selected_bid_ref not in saved.action_input.bid_refs
                or settings.selected_bid_ref not in saved.result.payload.ranked_bid_refs
                or settings.selected_bid_ref in saved.result.payload.rejected_bid_refs):
            raise TaskConflict('Evaluation reader requires explicit eligible selection and current same-Owner authority')
        return super()._validate_saved(saved, reading)
