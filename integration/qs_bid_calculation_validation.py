"""Re-read original QS-A06 bids and adjustment sources without recalculation."""
from integration.qs_cost_calculation_validation import QSCostCalculationSourceValidator
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, ref_type, walk_references
from src.actions.contracts.qs_bid_objects import QSBidMethodResultView, qs_bid_schemas
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_bid import prepare_bid_normalization
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.qs_bid import NORMALIZE_METHOD
from src.organization.models import Authorization, RoleAssignment


class QSBidNormalizationSourceValidator(QSCostCalculationSourceValidator):
    """Validate against the original provider beneath the publication wrapper.

    The caller holds the real source and authorization writer guard. Original
    bid prices, eligibility, clarifications, declared FX and adjustments must
    retain their exact supplied versions. Current numeric/author evidence must
    be valid now; unused historical evidence keeps its original dates. No
    arithmetic executor, evaluation processor or model is invoked here.
    """
    VERSION = 'qs-bid-normalization-source-validator.v1'
    ACTION_ID = 'QS-A06'
    SOURCE_SCHEMAS = staticmethod(qs_bid_schemas)
    RESULT_KIND = 'normalization'
    METHOD_REF = NORMALIZE_METHOD
    PREPARE_INPUT = staticmethod(prepare_bid_normalization)

    def _prepare(self, context, action_input):
        self._check()
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if (context.run_id != self.organizations.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID
                or self._views.source_mode != ('fixture' if context.execution_mode == 'offline_fixture' else 'formal')):
            raise TaskConflict('Bid normalization validation changes its run, action or source mode')
        registration = self.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.role != 'QS' or registration.skill is None:
            raise TaskConflict('Bid normalization validation requires its original implemented contract and Skill')
        action_input = registration.contract.validate_input(action_input)
        resolver = self._views.build_resolver(context, self.ACTION_ID, 'QS')
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'QS')
        prepared = self.PREPARE_INPUT(context, action_input, reading)
        if prepared['kind'] != 'prepared' or reading.method_evidence():
            raise TaskConflict('Current original bid sources no longer support their saved normalization input')
        return context, reading, prepared

    def _current_evidence(self, context, reading):
        required = {Reference.model_validate(row['ref']).key() for row in reading.evidence()
            if row['ref']['kind'] == 'Evidence'}
        for grant in self.organizations.grants(context, self.ACTION_ID, 'QS'):
            supplied = reading.resolve(grant.ref)
            if not isinstance(supplied, Authorization) or supplied != grant:
                raise TaskConflict('Bid normalization changes its actual current QS author grant')
            required.update(ref.key() for ref in grant.basis_refs)
        assignment = reading.resolve(context.function_ref)
        if (not isinstance(assignment, RoleAssignment) or assignment.role != 'QS'
                or assignment.function_ref != context.function_ref):
            raise TaskConflict('Bid normalization changes its current original author function')
        required.update(ref.key() for ref in assignment.basis_refs)
        for key in required:
            evidence = reading.resolve(Reference(kind=key[0], id=key[1], version=key[2]))
            if (not isinstance(evidence, EvidenceRecord)
                    or self._views.source_mode == 'formal' and evidence.source_kind == 'synthetic'
                    or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
                raise TaskConflict('Bid normalization lacks current original numeric or author evidence')
        return required

    def validate_current(self, *, context, action_input, arithmetic_input, reading, calculation_ref):
        """Producer gate before the one actual registered normalization execution."""
        if not isinstance(reading, ActionReadView) or reading._organizations is not self.organizations:
            raise TaskConflict('Bid normalization production changes its authorized source reading')
        reading.check_method_context(context, self.ACTION_ID)
        current, fresh, prepared = self._prepare(context, action_input)
        calculation_ref = ref_type('MethodResult').model_validate(calculation_ref)
        if (fresh.organization_id != reading.organization_id or prepared['calculation_ref'] != calculation_ref
                or prepared['input'].model_dump(mode='json') != arithmetic_input.model_dump(mode='json')):
            raise TaskConflict('Bid normalization substitutes original price, comparison domain or calculation target')
        required = self._current_evidence(current, fresh)
        self._compare(current, fresh, reading.evidence(), current_evidence_refs=required)
        reading.recheck()

    def validate_source(self, record, context):
        """Save/publication/read gate: rebuild original inputs, never recompute output."""
        original = ActionContext.model_validate(record['context'])
        current, reading, prepared = self._prepare(context, record['action_input'])
        saved = record['prepared']
        projection = QSBidMethodResultView.model_validate(saved['projection'])
        if (record['organization_id'] != reading.organization_id
                or any(getattr(original, name) != getattr(current, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))
                or saved['context_sha256'] != task_digest(record['context'])
                or saved['input_sha256'] != task_digest(record['action_input'])
                or saved['source_mode'] != self._views.source_mode
                or saved['reading_sha256'] != task_digest(saved['source_reading'])
                or prepared['input'].model_dump(mode='json') != saved['method_execution']['input']
                or prepared['calculation_ref'] != projection.ref or projection.kind != self.RESULT_KIND
                or projection.method_ref != self.METHOD_REF or projection.status != 'ok'
                or projection.round_ref != prepared['round_ref'] or projection.document_ref != prepared['document_ref']
                or projection.profile_ref != prepared['profile_ref'] or projection.basis_refs != prepared['basis_refs']
                or projection.bid_refs != [row.bid_ref for row in prepared['input'].bids]
                or projection.author_actor_id != original.actor_id or projection.author_function_ref != original.function_ref
                or projection.author_action_id != self.ACTION_ID or projection.calculated_at != original.business_time
                or projection.author_authority_ref not in current.authorization_refs):
            raise TaskConflict('Bid normalization publication changes its original input, author or comparison domain')
        required = self._current_evidence(current, reading)
        cache = {}
        for row in saved['source_reading']:
            if not isinstance(row, dict) or set(row) != {'ref', 'projection'}:
                raise TaskConflict('Saved bid normalization requires exact original ref/projection records')
            ref = Reference.model_validate(row['ref'])
            if ref.key() in cache:
                raise TaskConflict('Saved bid normalization repeats an original source version')
            cache[ref.key()] = row
        refs = [*walk_references(prepared['input']), *projection.evidence_refs,
            projection.author_authority_ref, projection.author_function_ref,
            *(Reference.model_validate(row['ref']) for row in reading.evidence())]
        if not {ref.key() for ref in refs} <= cache.keys():
            raise TaskConflict('Saved bid normalization omits original numeric, eligibility or author evidence')
        self._compare(current, reading, saved['source_reading'], current_evidence_refs=required)
        grant = reading.resolve(projection.author_authority_ref)
        if not isinstance(grant, Authorization) or grant not in self.organizations.grants(current, self.ACTION_ID, 'QS'):
            raise TaskConflict('Saved bid normalization lost its actual original current author authority')
        if reading.method_evidence():
            raise TaskConflict('Bid normalization source validation unexpectedly executed a method')
        reading.recheck()
        self._check()
        return True
