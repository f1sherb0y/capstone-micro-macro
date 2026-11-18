"""Persist original bank intake decisions without creating formal review or finance effects."""
from copy import deepcopy
from dataclasses import dataclass

from integration.bank_intake_actions import PreparedBankIntake
from integration.contractor_bid_results import ContractorBidResultWorker
from src.actions.contracts.bank_objects import FinanceApplicationView, bank_intake_schemas
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


@dataclass(frozen=True)
class SavedBankIntake:
    identity: TaskIdentity
    context: ActionContext
    current_context: ActionContext
    action_input: object
    result: object
    audit: dict
    source_reading: tuple[dict, ...]
    source_reading_sha256: str
    record_sha256: str


class BankIntakeResultWorker(ContractorBidResultWorker):
    """Reuse claim-once and result-first recovery with a distinct bank schema/table."""
    SCHEMA = 'bank-intake-result.v1'
    ACTION_ID = 'BANK-A02'
    ROLE = 'Bank'
    PREPARED_TYPE = PreparedBankIntake
    RESULT_TABLE = 'bank_intake_results'
    WAIT_KIND = 'manual_bank_intake_result_review'
    EXECUTION_ERROR_CODE = 'bank_intake_execution_exception'
    EXTRA_FIELDS = frozenset({'source_reading', 'source_reading_sha256'})
    SOURCE_SCHEMAS = staticmethod(bank_intake_schemas)
    SAVED_TYPE = SavedBankIntake
    READ_ACTION_IDS = frozenset({'BANK-A02', 'BANK-A03'})

    def _result_extras(self, prepared):
        prepared.reading.recheck()
        sources = prepared.reading.evidence()
        if task_digest(sources) != prepared.reading_sha256:
            raise TaskConflict('Original bank intake assembly sources changed')
        return {'source_reading': sources, 'source_reading_sha256': prepared.reading_sha256}

    def _validate_record(self, identity, record):
        snapshot = super()._validate_record(identity, record)
        sources = record['source_reading']
        if not isinstance(sources, list) or task_digest(sources) != record['source_reading_sha256']:
            raise TaskConflict('Saved bank intake source digest changed')
        context = ActionContext.model_validate(snapshot['context'])
        permitted = {ref.key() for ref in context.visible_refs}
        schemas, seen = self.SOURCE_SCHEMAS(), set()
        originals = {}
        for item in sources:
            if not isinstance(item, dict) or set(item) != {'ref', 'projection'}:
                raise TaskConflict('Saved bank intake sources change their original closed evidence schema')
            ref = Reference.model_validate(item['ref'])
            if ref.key() in seen or ref.key() not in permitted:
                raise TaskConflict('Saved bank intake source is duplicated or outside original visibility')
            seen.add(ref.key())
            originals[ref.key()] = schemas.validate_projection(ref, item['projection'])
        self._validate_primary_sources(snapshot, identity, originals)
        return snapshot

    def _validate_primary_sources(self, snapshot, identity, originals):
        action_input = snapshot['action_input']
        application = originals.get(Reference.model_validate(action_input['application_ref']).key())
        if not isinstance(application, FinanceApplicationView) or application.lender_id != identity.organization_id:
            raise TaskConflict('Saved bank intake lacks its exact original lender application')
        expected = {'application_ref': application.ref.model_dump(mode='json'), 'borrower_id': application.borrower_id,
            'applicant_authority_ref': application.applicant_authority_ref.model_dump(mode='json'),
            'requested': application.requested.model_dump(mode='json'), 'purpose_ref': application.purpose_ref.model_dump(mode='json'),
            'product_candidates': [ref.model_dump(mode='json') for ref in application.product_candidates],
            'disclosure_refs': [ref.model_dump(mode='json') for ref in application.disclosure_refs]}
        if action_input != expected:
            raise TaskConflict('Saved bank intake input substitutes its original submitted application facts')

    def read_completed(self, identity, *, current_context, reading, execution_versions, validate_current):
        """Read own finalized local decision through submission states, independently of receipt.

        Submission or reconciliation never upgrades this result to native
        acceptance. Actual source handoffs still require their host evidence.
        """
        identity = TaskIdentity(**identity.as_dict())
        current = ActionContext.model_validate(current_context).model_copy(deep=True)
        if (not isinstance(reading, ActionReadView) or not callable(validate_current)
                or current.run_id != identity.run_id or current.contract_ref.kind != 'ActionContract'
                or current.contract_ref.id not in self.READ_ACTION_IDS or reading.organization_id != identity.organization_id
                or execution_versions != identity.versions):
            raise TaskConflict('Bank history requires current own original-action authority and all original execution versions')
        reading.check_method_context(current, current.contract_ref.id)
        record = self.get_record(identity)
        task = self.store.get(identity)
        if (record is None or record['result']['kind'] != 'completed'
                or task['state'] not in {'output_formed', 'waiting_receipt', 'receipt_unknown', 'reconciled'}
                or task['output'] != record['result'] or task['output_sha256'] != record['result_sha256']
                or task['revision'] < record['attempt_revision']):
            raise TaskConflict('Bank history requires its finalized completed original result')
        snapshot = self.snapshots.get(identity)
        context = ActionContext.model_validate(snapshot['context'])
        original_fields = ('run_id', 'actor_id', 'scope')
        if current.contract_ref.id == self.ACTION_ID:
            original_fields += ('function_ref', 'contract_ref')
        if (any(getattr(context, name) != getattr(current, name) for name in original_fields)
                or context.business_time.clock_ref != current.business_time.clock_ref
                or context.business_time.offset > current.business_time.offset
                or (context.execution_mode == 'offline_fixture') != (current.execution_mode == 'offline_fixture')):
            raise TaskConflict('Bank history changes original actor, function, scope, clock or source mode')
        contract = self.registry.get(self.ACTION_ID).contract
        saved = self.SAVED_TYPE(identity, context, current, contract.validate_input(snapshot['action_input']),
            contract.result_adapter.validate_python(record['result']), deepcopy(record['audit']),
            tuple(deepcopy(record['source_reading'])), record['source_reading_sha256'], record['record_sha256'])
        if validate_current(deepcopy(saved)) is not True:
            raise TaskConflict('Bank history requires explicit current host validation of original sources and authorization')
        reading.recheck()
        return saved
