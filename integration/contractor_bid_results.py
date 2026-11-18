"""Persist original A02 outcomes and read them for the old tender proposal port."""
from copy import deepcopy
from dataclasses import dataclass
import json

from integration.action_versions import prepared_action_execution_versions
from integration.contractor_bid_actions import PreparedContractorBid
from src.actions.contracts.common import ActionContext, Reference
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, TaskIdentity, TaskStore, canonical, task_digest, _text


class ContractorBidResultWorker:
    """Claim each exact prepared invocation once; recovery never reruns A02.

    A result and audit are committed before its task is finalized. Interrupted
    processing without that evidence remains unresolved. Missing/unsupported/
    deferred outcomes retain explicit manual pending conditions, without an
    invented automatic continuation or conversion to a commercial decline.
    """
    SCHEMA = 'contractor-bid-result.v1'
    ACTION_ID = 'CONTRACTOR-A02'
    ROLE = 'Contractor'
    PREPARED_TYPE = PreparedContractorBid
    RESULT_TABLE = 'contractor_bid_results'
    WAIT_KIND = 'manual_bid_result_review'
    EXECUTION_ERROR_CODE = 'bid_execution_exception'
    EXTRA_FIELDS = frozenset()
    EXECUTION_CLAIM_SCHEMA = 'action-execution-claim.v1'

    def __init__(self, *, store, snapshots, registry, client_version, model_version,
            validate_invocation, validate_wait, validate_recovery=None):
        if (not isinstance(store, TaskStore) or not isinstance(snapshots, InvocationSnapshotStore)
                or snapshots.store is not store or not callable(validate_invocation)
                or not callable(validate_wait)
                or validate_recovery is not None and not callable(validate_recovery)):
            raise ValueError('Bid worker requires the original shared stores and explicit host validation')
        _text(client_version); _text(model_version)
        self.store, self.snapshots, self.registry = store, snapshots, registry
        self.client_version, self.model_version = client_version, model_version
        self.validate_invocation, self.validate_wait = validate_invocation, validate_wait
        self.validate_recovery = validate_recovery
        if (self.ACTION_ID, self.ROLE, self.RESULT_TABLE) not in {
                ('CONTRACTOR-A02', 'Contractor', 'contractor_bid_results'),
                ('CONTRACTOR-A01', 'Contractor', 'contractor_screening_results'),
                ('CONTRACTOR-A03', 'Contractor', 'contractor_amendment_results'),
                ('CONTRACTOR-A04', 'Contractor', 'contractor_formation_results'),
                ('CONTRACTOR-A05', 'Contractor', 'contractor_planning_results'),
                ('CONTRACTOR-A06', 'Contractor', 'contractor_readiness_results'),
                ('CONTRACTOR-A07', 'Contractor', 'contractor_execution_results'),
                ('CONTRACTOR-A08', 'Contractor', 'contractor_quality_results'),
                ('CONTRACTOR-A09', 'Contractor', 'contractor_claim_results'),
                ('CONTRACTOR-A10', 'Contractor', 'contractor_payment_results'),
                ('CONTRACTOR-A11', 'Contractor', 'contractor_closeout_results'),
                ('CONTRACTOR-A13', 'Contractor', 'contractor_advice_results'),
                ('ARCHITECT-A01', 'Architect', 'architect_opportunity_results'),
                ('ARCHITECT-A02', 'Architect', 'architect_intake_results'),
                ('ARCHITECT-A03', 'Architect', 'architect_appointment_results'),
                ('ARCHITECT-A04', 'Architect', 'architect_planning_results'),
                ('ARCHITECT-A05', 'Architect', 'architect_design_results'),
                ('ARCHITECT-A06', 'Architect', 'architect_integration_results'),
                ('ARCHITECT-A07', 'Architect', 'architect_deliverable_results'),
                ('ARCHITECT-A08', 'Architect', 'architect_review_results'),
                ('ARCHITECT-A09', 'Architect', 'architect_change_results'),
                ('ARCHITECT-A10', 'Architect', 'architect_billing_results'),
                ('ARCHITECT-A11', 'Architect', 'architect_transition_results'),
                ('ARCHITECT-A12', 'Architect', 'architect_learning_results'),
                ('ARCHITECT-A13', 'Architect', 'architect_research_results'),
                ('ENGINEER-A01', 'Engineer', 'engineer_opportunity_results'),
                ('ENGINEER-A02', 'Engineer', 'engineer_intake_results'),
                ('ENGINEER-A03', 'Engineer', 'engineer_appointment_results'),
                ('ENGINEER-A04', 'Engineer', 'engineer_planning_results'),
                ('ENGINEER-A05', 'Engineer', 'engineer_design_results'),
                ('ENGINEER-A06', 'Engineer', 'engineer_review_results'),
                ('ENGINEER-A07', 'Engineer', 'engineer_deliverable_results'),
                ('ENGINEER-A08', 'Engineer', 'engineer_inspection_results'),
                ('ENGINEER-A09', 'Engineer', 'engineer_change_results'),
                ('ENGINEER-A10', 'Engineer', 'engineer_billing_results'),
                ('ENGINEER-A11', 'Engineer', 'engineer_transition_results'),
                ('ENGINEER-A12', 'Engineer', 'engineer_learning_results'),
                ('ENGINEER-A13', 'Engineer', 'engineer_research_results'),
                ('QS-A01', 'QS', 'qs_market_results'),
                ('QS-A02', 'QS', 'qs_intake_results'),
                ('QS-A03', 'QS', 'qs_appointment_results'),
                ('QS-A04', 'QS', 'qs_cost_results'),
                ('QS-A05', 'QS', 'qs_procurement_results'),
                ('QS-A06', 'QS', 'qs_bid_results'),
                ('QS-A07', 'QS', 'qs_change_results'),
                ('QS-A08', 'QS', 'qs_payment_results'),
                ('QS-A09', 'QS', 'qs_final_account_results'),
                ('QS-A10', 'QS', 'qs_billing_results'),
                ('QS-A11', 'QS', 'qs_transition_results'),
                ('QS-A12', 'QS', 'qs_learning_results'),
                ('QS-A13', 'QS', 'qs_research_results'),
                ('GOV-A01', 'Government', 'government_advice_results'),
                ('GOV-A02', 'Government', 'government_intake_results'),
                ('GOV-A03', 'Government', 'government_scheduling_results'),
                ('GOV-A04', 'Government', 'government_review_results'),
                ('GOV-A05', 'Government', 'government_consultation_results'),
                ('GOV-A06', 'Government', 'government_supplement_results'),
                ('GOV-A07', 'Government', 'government_decision_results'),
                ('GOV-A08', 'Government', 'government_permit_results'),
                ('GOV-A09', 'Government', 'government_transition_results'),
                ('GOV-A10', 'Government', 'government_inspection_results'),
                ('GOV-A11', 'Government', 'government_use_results'),
                ('GOV-A12', 'Government', 'government_feedback_results'),
                ('OWN-A01', 'Owner', 'owner_observation_results'),
                ('OWN-A02', 'Owner', 'owner_study_results'),
                ('OWN-A03', 'Owner', 'owner_investment_results'),
                ('OWN-A04', 'Owner', 'owner_commission_results'),
                ('OWN-A05', 'Owner', 'owner_financing_results'),
                ('OWN-A06', 'Owner', 'owner_payment_results'),
                ('OWN-A07', 'Owner', 'owner_design_results'),
                ('OWN-A08', 'Owner', 'owner_regulatory_results'),
                ('OWN-A09', 'Owner', 'owner_tender_results'),
                ('OWN-A10', 'Owner', 'owner_award_results'),
                ('OWN-A11', 'Owner', 'owner_contract_results'),
                ('OWN-A12', 'Owner', 'owner_closeout_results'),
                ('OWN-A13', 'Owner', 'owner_continuation_results'),
                ('OWN-A14', 'Owner', 'owner_asset_results'),
                ('OWN-A15', 'Owner', 'owner_operating_results'),
                ('OWN-A16', 'Owner', 'owner_proposal_results'),
                ('BANK-A01', 'Bank', 'bank_strategy_results'),
                ('BANK-A02', 'Bank', 'bank_intake_results'),
                ('BANK-A03', 'Bank', 'bank_credit_results'),
                ('BANK-A04', 'Bank', 'bank_quote_results'),
                ('BANK-A05', 'Bank', 'bank_arrangement_results'),
                ('BANK-A06', 'Bank', 'bank_draw_results'),
                ('BANK-A07', 'Bank', 'bank_execution_results'),
                ('BANK-A08', 'Bank', 'bank_monitoring_results'),
                ('BANK-A09', 'Bank', 'bank_debt_results'),
                ('BANK-A10', 'Bank', 'bank_resolution_results'),
                ('BANK-A11', 'Bank', 'bank_closeout_results'),
                ('BANK-A12', 'Bank', 'bank_learning_results'),
                ('BANK-A13', 'Bank', 'bank_advice_results'),
                ('SUPPLIER-A01', 'Supplier', 'supplier_screening_results'),
                ('SUPPLIER-A02', 'Supplier', 'supplier_product_results'),
                ('SUPPLIER-A03', 'Supplier', 'supplier_quote_results'),
                ('SUPPLIER-A04', 'Supplier', 'supplier_order_results'),
                ('SUPPLIER-A05', 'Supplier', 'supplier_planning_results'),
                ('SUPPLIER-A06', 'Supplier', 'supplier_execution_results'),
                ('SUPPLIER-A07', 'Supplier', 'supplier_quality_results'),
                ('SUPPLIER-A08', 'Supplier', 'supplier_logistics_results'),
                ('SUPPLIER-A09', 'Supplier', 'supplier_receiving_results'),
                ('SUPPLIER-A10', 'Supplier', 'supplier_payment_results'),
                ('SUPPLIER-A11', 'Supplier', 'supplier_remedy_results'),
                ('SUPPLIER-A13', 'Supplier', 'supplier_advice_results')}:
            raise ValueError('Result worker requires an explicit supported action table')
        with store._transaction():
            store._db.execute(f'CREATE TABLE IF NOT EXISTS {self.RESULT_TABLE} (task_key TEXT PRIMARY KEY, record TEXT NOT NULL)')

    def _prepared_identity(self, prepared, *, request_id, purpose):
        if (not isinstance(prepared, self.PREPARED_TYPE) or prepared.runner.registry is not self.registry
                or prepared.context.contract_ref.id != self.ACTION_ID
                or self.registry.get(self.ACTION_ID).role != self.ROLE):
            raise TaskConflict('Bid worker requires its actual prepared A02 and registry')
        raw_input = prepared.action_input.model_dump(mode='json')
        raw_context = prepared.context.model_dump(mode='json')
        if task_digest(raw_input) != prepared.input_sha256 or task_digest(raw_context) != prepared.context_sha256:
            raise TaskConflict('Prepared original bid input or context changed')
        return TaskIdentity(run_id=prepared.context.run_id, organization_id=prepared.reading.organization_id,
            role=self.ROLE, action_id=self.ACTION_ID, request_id=request_id, purpose=purpose,
            input_sha256=prepared.input_sha256, context_sha256=prepared.context_sha256,
            versions=prepared_action_execution_versions(prepared,
                client_version=self.client_version, model_version=self.model_version))

    def register(self, prepared, *, request_id, purpose='action'):
        identity = self._prepared_identity(prepared, request_id=request_id, purpose=purpose)
        prepared.reading.recheck()
        snapshot = self.snapshots._record(identity, prepared.action_input.model_dump(mode='json'),
            prepared.context.model_dump(mode='json'))
        # Commit proof of never having entered preparation together with the
        # original task/snapshot. Re-registering an older task cannot create
        # that proof: its preparation may already have run under older code.
        with self.store._transaction():
            new = self.store._read(identity) is None
            self.snapshots._save_in_transaction(identity, snapshot)
            claim = self._read_execution_claim(identity, snapshot['snapshot_sha256'])
            if new:
                if claim is not None:
                    raise TaskConflict('Execution claim is orphaned from its original task')
                claim = self._execution_claim(identity, snapshot['snapshot_sha256'], 'registered')
                self.store._db.execute('INSERT INTO metadata VALUES (?,?)',
                    (self._execution_claim_key(identity), canonical(claim)))
        return identity

    @staticmethod
    def _execution_claim_key(identity):
        return 'action_execution_claim:' + identity.key

    def _execution_claim(self, identity, snapshot_sha256, phase):
        claim = {'schema_version': self.EXECUTION_CLAIM_SCHEMA, 'identity': identity.as_dict(),
            'snapshot_sha256': snapshot_sha256, 'phase': phase}
        claim['claim_sha256'] = task_digest(claim)
        return claim

    def _read_execution_claim(self, identity, snapshot_sha256):
        saved = self.store._db.execute('SELECT value FROM metadata WHERE key=?',
            (self._execution_claim_key(identity),)).fetchone()
        if saved is None:
            return None
        claim = json.loads(saved[0])
        if (not isinstance(claim, dict) or claim.get('phase') not in {'registered', 'preparing'}
                or claim != self._execution_claim(identity, snapshot_sha256, claim['phase'])):
            raise TaskConflict('Original action execution claim changed identity, snapshot or digest')
        return claim

    def _unstarted_claim(self, identity, row, snapshot):
        self.store._check_not_continued(identity)
        if (self.store._read(identity) != row or row['revision'] != 0
                or row['state'] != 'waiting_input' or row['conditions']
                or any(row[name] is not None for name in
                    ('output', 'output_sha256', 'submission', 'receipt', 'error_code'))
                or self.store._db.execute(f'SELECT 1 FROM {self.RESULT_TABLE} WHERE task_key=?',
                    (identity.key,)).fetchone() is not None):
            raise TaskConflict('Only an unchanged unstarted action may prepare its decision')
        claim = self._read_execution_claim(identity, snapshot['snapshot_sha256'])
        if claim is None or claim['phase'] != 'registered':
            raise TaskConflict('Action preparation may already have run; retain unresolved execution')
        return claim

    def unstarted_evidence(self, identity):
        """Read proof at this instant, without authorizing sources or execution."""
        identity = TaskIdentity(**identity.as_dict())
        if identity.action_id != self.ACTION_ID or identity.role != self.ROLE:
            raise TaskConflict('Unstarted evidence changes its original action or role')
        row = self.store.get(identity)
        snapshot = self.snapshots.get(identity)
        with self.store._transaction():
            return deepcopy(self._unstarted_claim(identity, row, snapshot))

    def _claim_preparation(self, identity, row, snapshot):
        with self.store._transaction():
            self._unstarted_claim(identity, row, snapshot)
            self.store._db.execute('UPDATE metadata SET value=? WHERE key=?',
                (canonical(self._execution_claim(identity, snapshot['snapshot_sha256'], 'preparing')),
                    self._execution_claim_key(identity)))

    def _validate_record(self, identity, record):
        return self.validate_saved_record(identity, record, registry=self.registry, snapshots=self.snapshots)

    @classmethod
    def validate_saved_record(cls, identity, record, *, registry, snapshots):
        """Validate existing evidence without constructing an executable worker."""
        fields = {'schema_version', 'identity', 'attempt_revision', 'result', 'result_sha256', 'audit', 'record_sha256'} | cls.EXTRA_FIELDS
        if (identity.action_id != cls.ACTION_ID or identity.role != cls.ROLE
                or not isinstance(record, dict) or set(record) != fields
                or record['schema_version'] != cls.SCHEMA or record['identity'] != identity.as_dict()
                or type(record['attempt_revision']) is not int or record['attempt_revision'] < 1
                or task_digest(record['result']) != record['result_sha256']
                or task_digest({key:value for key,value in record.items() if key != 'record_sha256'}) != record['record_sha256']):
            raise TaskConflict('Saved bid result changed original identity, schema or digest')
        snapshot = snapshots.get(identity)
        context = ActionContext.model_validate(snapshot['context'])
        registration = registry.get(cls.ACTION_ID)
        contract = registration.contract
        contract_hash = task_digest({'ref':context.contract_ref.model_dump(mode='json'),
            'source_sha256':contract.source_sha256, 'input_schema':contract.input_model.model_json_schema(),
            'payload_schema':contract.payload_adapter.json_schema()})
        if contract_hash != identity.versions['contract']:
            raise TaskConflict('Saved bid requires its original contract; no silent migration')
        action_input = contract.validate_input(snapshot['action_input'])
        result = contract.result_adapter.validate_python(record['result'])
        if result.model_dump(mode='json') != record['result']:
            raise TaskConflict('Saved bid result transport is not its original typed output')
        if result.kind == 'completed':
            contract.validate_decision(action_input, result.payload)
        audit = record['audit']
        expected = {'schema_version':'action-audit.v1', 'run_id':identity.run_id, 'action_id':identity.action_id,
            'operation_id':context.operation_id, 'input_version':context.contract_ref.version,
            'input_sha256':identity.input_sha256, 'result_sha256':record['result_sha256'], 'result_kind':result.kind}
        if (not isinstance(audit, dict) or any(audit.get(key) != value for key,value in expected.items())
                or audit.get('authorization_refs') != [list(ref.key()) for ref in context.authorization_refs]
                or audit.get('stages', {}).get('authorization') != 'accepted'
                or audit.get('reading', {}).get('read_token') != context.read_token):
            raise TaskConflict('Saved bid audit changes original input, authority, read point or result')
        return snapshot

    def get_record(self, identity):
        identity = TaskIdentity(**identity.as_dict())
        if identity.action_id != self.ACTION_ID or identity.role != self.ROLE:
            raise TaskConflict('Saved result reading changes its original action or role')
        with self.store._lock:
            self.store.get(identity)
            saved = self.store._db.execute(f'SELECT record FROM {self.RESULT_TABLE} WHERE task_key=?',
                (identity.key,)).fetchone()
            if saved is None:
                return None
            record = json.loads(saved[0])
            self._validate_record(identity, record)
            return deepcopy(record)

    def _finalize(self, identity, record, *, recovered):
        row = self.store.get(identity)
        result = record['result']
        if row['state'] != 'processing':
            if row['revision'] < record['attempt_revision'] or row['output'] is not None and row['output'] != result:
                raise TaskConflict('Bid task lifecycle conflicts with the saved original result')
            return {'task':row, 'result':deepcopy(result)}
        if row['revision'] != record['attempt_revision']:
            raise TaskConflict('Bid processing attempt changed after result persistence')
        if recovered and (self.validate_recovery is None or self.validate_recovery(
                deepcopy(row), deepcopy(record), self.snapshots.get(identity)) is not True):
            raise TaskConflict('Saved bid recovery requires current host approval; no automatic replay')
        if result['kind'] == 'completed':
            row = self.store.finish(identity, row['revision'], output=result)
        elif result['kind'] == 'technical_error':
            row = self.store.fail(identity, row['revision'], error_code=result['error'].get('code', 'recorded_bid_technical_error'))
        else:
            condition = {'kind':self.WAIT_KIND, 'result_kind':result['kind'],
                         'result_sha256':record['result_sha256']}
            if result['kind'] == 'needs_information':
                condition.update(missing_fields=result['missing_fields'], requested_refs=result['requested_refs'])
            elif result['kind'] == 'unsupported':
                condition['capability_ref'] = result['capability_ref']
            elif result['kind'] == 'deferred':
                condition['resume_condition'] = result['resume_condition']
            else:
                raise TaskConflict('Saved bid has no supported lifecycle outcome')
            if self.validate_wait(deepcopy(row), deepcopy(result), [deepcopy(condition)]) is not True:
                raise TaskConflict('Original bid pending conditions require explicit current validation')
            row = self.store.wait_for_input(identity, row['revision'], conditions=[condition])
        return {'task':row, 'result':deepcopy(result)}

    def _result_extras(self, prepared):
        return {}

    def execute(self, identity, prepared):
        identity = TaskIdentity(**identity.as_dict())
        if identity.action_id != self.ACTION_ID or identity.role != self.ROLE:
            raise TaskConflict('Result execution changes its original action or role')
        row = self.store.get(identity)
        if self.store.continuation(identity) is not None:
            raise TaskConflict('An original continued bid cannot execute again')
        saved = self.get_record(identity)
        if saved is not None:
            return self._finalize(identity, saved, recovered=True)
        if row['state'] == 'processing':
            raise TaskConflict('Interrupted bid has no saved result; diagnose it before any replay')
        if row['state'] != 'waiting_input' or row['conditions']:
            raise TaskConflict('Only a new ready bid may execute; waits and failures do not auto-retry')
        current = self._prepared_identity(prepared, request_id=identity.request_id, purpose=identity.purpose)
        if current.as_dict() != identity.as_dict():
            raise TaskConflict('Prepared bid differs from the original task or seven execution versions')
        snapshot = self.snapshots.get(identity)
        if self.validate_invocation(deepcopy(row), prepared) is not True:
            raise TaskConflict('Actual current bid facts and authority require explicit host validation')
        prepared.reading.recheck()
        self._claim_preparation(identity, row, snapshot)
        prepared.runner.prepare_decision(context=prepared.context,
            action_input=prepared.action_input, reading=prepared.reading)
        if (self.store.get(identity) != row or self.get_record(identity) is not None
                or self._prepared_identity(prepared, request_id=identity.request_id,
                    purpose=identity.purpose).as_dict() != identity.as_dict()):
            raise TaskConflict('Decision preparation changed its original ready task or invocation identity')
        prepared.reading.recheck()
        started = self.store.start(identity, row['revision'])
        try:
            result = prepared.execute().model_dump(mode='json')
        except Exception:
            self.store.fail(identity, started['revision'], error_code=self.EXECUTION_ERROR_CODE)
            raise
        if not prepared.runner.audit_records:
            raise TaskConflict('Bid execution lacks an original audit; retain unresolved processing')
        record = {'schema_version':self.SCHEMA, 'identity':identity.as_dict(),
            'attempt_revision':started['revision'], 'result':result, 'result_sha256':task_digest(result),
            'audit':prepared.runner.audit_records[-1].as_dict(), **self._result_extras(prepared)}
        record['record_sha256'] = task_digest(record)
        self._validate_record(identity, record)
        with self.store._transaction():
            self.store._check_not_continued(identity)
            if self.store._read(identity) != started:
                raise TaskConflict('Original bid task changed before its result could be committed')
            self.store._db.execute(f'INSERT INTO {self.RESULT_TABLE} VALUES (?,?)',
                (identity.key, canonical(record)))
            if self.ACTION_ID == 'CONTRACTOR-A02' and self.RESULT_TABLE == 'contractor_bid_results':
                from integration.contractor_bid_source_history import save_bid_source_history
                save_bid_source_history(self, identity, record, prepared, snapshot)
        return self._finalize(identity, record, recovered=False)

    def read_source_history(self, identity, *, current_context, organizations):
        from integration.contractor_bid_source_history import read_bid_source_history
        return read_bid_source_history(self, identity, current_context=current_context, organizations=organizations)

    def read_completed(self, identity, *, current_context, reading, mapping_ref):
        """Return saved originals and a current view; never re-execute or fabricate."""
        from integration.bindings.gba_v1_tender_proposal import SavedContractorBid

        identity = TaskIdentity(**identity.as_dict())
        record = self.get_record(identity)
        if record is None or record['result']['kind'] != 'completed':
            raise TaskConflict('Tender proposal has no saved completed original A02 result')
        row = self.store.get(identity)
        if row['state'] != 'output_formed' or row['output'] != record['result']:
            raise TaskConflict('Tender proposal requires a finalized matching original bid output')
        snapshot = self.snapshots.get(identity)
        current_context = ActionContext.model_validate(current_context).model_copy(deep=True)
        reading.check_method_context(current_context, 'CONTRACTOR-A02')
        if reading.organization_id != identity.organization_id or current_context.run_id != identity.run_id:
            raise TaskConflict('Tender saved-output read changes original run or recipient')
        contract = self.registry.get('CONTRACTOR-A02').contract
        return SavedContractorBid(context=ActionContext.model_validate(snapshot['context']),
            current_context=current_context, action_input=contract.validate_input(snapshot['action_input']),
            result=contract.result_adapter.validate_python(record['result']), audit=deepcopy(record['audit']),
            reading=reading, mapping_ref=Reference.model_validate(mapping_ref))


@dataclass(frozen=True)
class ContractorTenderReadSelection:
    identity: TaskIdentity
    current_context: ActionContext
    mapping_ref: Reference


class ContractorTenderOutputReader:
    """Bridge the host's exact task selection to current authorized source reads."""
    def __init__(self, *, worker, assembler, select_current):
        from integration.contractor_bid_actions import ContractorBidActionAssembler

        if (not isinstance(worker, ContractorBidResultWorker)
                or not isinstance(assembler, ContractorBidActionAssembler)
                or worker.registry is not assembler.registry or not callable(select_current)):
            raise ValueError('Actual bid worker/assembler and explicit current task selector required')
        self.worker, self.assembler, self.select_current = worker, assembler, select_current

    def __call__(self, request):
        selected = self.select_current(request.model_copy(deep=True))
        if not isinstance(selected, ContractorTenderReadSelection):
            raise TaskConflict('Tender read selector must return an explicit typed original-task selection')
        if selected.identity.organization_id != request.agent.agent_id:
            raise TaskConflict('Tender task selection changes the original request enterprise')
        reading = self.assembler.build_result_reading(selected.current_context)
        return self.worker.read_completed(selected.identity, current_context=selected.current_context,
            reading=reading, mapping_ref=selected.mapping_ref)
