"""Persist original Supplier A13 advice with private source and public result boundaries."""
from dataclasses import dataclass

from integration.supplier_advice_actions import PreparedSupplierAdvice
from integration.supplier_quote_results import SavedSupplierQuote, SupplierQuoteResultWorker
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.supplier_advice_objects import (
    ContractorAdviceAuthorityView, ContractorAdviceBriefView, ContractorAdviceOptionView,
    SupplierAdviceCapabilityView, SupplierAdviceDisclosureView, SupplierAdviceMethodView,
    SupplierAdviceProfessionalView, SupplierAdviceRequestView, supplier_advice_schemas,
)
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedSupplierAdvice(SavedSupplierQuote):
    """Historical own consultation evidence; this is not a public disclosure payload."""


class SupplierAdviceResultWorker(SupplierQuoteResultWorker):
    """Reuse original result-first, pending and recovery rules in a distinct A13 table.

    The source cache remains private historical evidence. Public advice is the
    original typed result; persisting sources does not grant disclosure rights,
    bounded study authority, a formal supply offer or design/use approval.
    """
    SCHEMA = 'supplier-advice-result.v1'
    ACTION_ID = 'SUPPLIER-A13'
    PREPARED_TYPE = PreparedSupplierAdvice
    RESULT_TABLE = 'supplier_advice_results'
    WAIT_KIND = 'manual_supplier_advice_result_review'
    EXECUTION_ERROR_CODE = 'supplier_advice_execution_exception'
    SOURCE_SCHEMAS = staticmethod(supplier_advice_schemas)
    READ_ACTION_IDS = frozenset({'SUPPLIER-A13', 'SUPPLIER-A12'})
    SAVED_TYPE = SavedSupplierAdvice

    @staticmethod
    def _original(sources, ref, schema):
        originals = [row for row in sources if Reference.model_validate(row['ref']) == ref]
        if len(originals) != 1:
            raise TaskConflict('Saved advice lacks its exact original request or source version')
        row = schema.model_validate(originals[0]['projection'])
        if row.ref != ref:
            raise TaskConflict('Saved advice projection changes its original reference')
        return row

    def _validate_primary_sources(self, snapshot, identity, sources):
        context = ActionContext.model_validate(snapshot['context'])
        action_input = snapshot['action_input']
        request = self._original(sources, Reference.model_validate(action_input['advisory_request_ref']), SupplierAdviceRequestView)
        profile = self._original(sources, Reference.model_validate(action_input['disclosure_profile_ref']), SupplierAdviceDisclosureView)
        if (request.recipient_organization_id != identity.organization_id
                or profile.organization_id != identity.organization_id or profile.request_ref != request.ref
                or profile.authority_ref not in context.authorization_refs):
            raise TaskConflict('Saved advice changes original Supplier, request or disclosure authority')
        brief = self._original(sources, Reference.model_validate(action_input['brief_ref']), ContractorAdviceBriefView)
        if profile.choice != 'decline' and request.brief_ref != brief.ref:
            raise TaskConflict('Saved advice request changes its original brief')
        self._original(sources, Reference.model_validate(action_input['capability_ref']), SupplierAdviceCapabilityView)
        for field, schema in (('option_refs', ContractorAdviceOptionView),
                ('professional_advice_refs', SupplierAdviceProfessionalView), ('feasibility_method_refs', SupplierAdviceMethodView)):
            for raw_ref in action_input[field]:
                self._original(sources, Reference.model_validate(raw_ref), schema)
        if action_input['advisory_scope_ref'] is not None:
            self._original(sources, Reference.model_validate(action_input['advisory_scope_ref']), ContractorAdviceAuthorityView)

    def prepare_order_handoff(self, *args, **kwargs):
        raise ValueError('A13 saved advice is not an A03 quote, formal offer or professional approval')
