"""Re-read QS-A08 work, certificate and cash history without recalculation."""
from integration.qs_change_calculation_validation import QSChangeCalculationSourceValidator
from src.actions.contracts.common import ActionContext, Reference, ref_type, walk_references
from src.actions.contracts.qs_payment_objects import QSPaymentResultView, qs_payment_schemas
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_payment import prepare_payment_arithmetic
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization
from src.organization.registry import scope_covers


class QSPaymentCalculationSourceValidator(QSChangeCalculationSourceValidator):
    """Concrete production/save/publication/read gates over the original provider.

    Caller holds the actual source and authorization writer guard. Historical
    authors and receipts retain their original evidence dates. Numeric and
    current QS authority bases must be current; formal synthetic sources are
    rejected. These checks do not measure physical work, calibrate rates, issue
    a certificate or infer received cash from unknown records.
    """
    VERSION = 'qs-payment-calculation-source-validator.v1'
    ACTION_ID = 'QS-A08'
    SOURCE_SCHEMAS = staticmethod(qs_payment_schemas)

    def _prepare(self, context, action_input):
        self._check()
        context = ActionContext.model_validate(context).model_copy(deep=True)
        expected_mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
        if (context.run_id != self.organizations.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or expected_mode != self._views.source_mode):
            raise TaskConflict('QS payment validation changes its original run, action or explicit source mode')
        registration = self.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.role != 'QS' or registration.skill is None:
            raise TaskConflict('QS payment validation requires its original implemented contract and Skill')
        action_input = registration.contract.validate_input(action_input)
        resolver = self._views.build_resolver(context, self.ACTION_ID, 'QS')
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'QS')
        prepared = prepare_payment_arithmetic(context, action_input, reading)
        if prepared['kind'] != 'prepared':
            raise TaskConflict('Current original QS payment sources no longer support their prepared arithmetic')
        return context, reading, prepared

    def validate_current(self, *, context, action_input, arithmetic_input, reading, result_refs):
        """Check the entire original result target set before its one method call."""
        if not isinstance(reading, ActionReadView) or reading._organizations is not self.organizations:
            raise TaskConflict('QS payment production changes its original authorized reading')
        reading.check_method_context(context, self.ACTION_ID)
        if not isinstance(result_refs, dict):
            raise TaskConflict('QS payment production requires its complete original result target mapping')
        targets = {kind: ref_type('MethodResult').model_validate(ref) for kind, ref in result_refs.items()}
        current, fresh, prepared = self._prepare(context, action_input)
        if (fresh.organization_id != reading.organization_id or targets != prepared['result_refs']
                or not {ref.key() for ref in targets.values()} <= {ref.key() for ref in current.visible_refs}
                or prepared['input'].model_dump(mode='json') != arithmetic_input.model_dump(mode='json')):
            raise TaskConflict('QS payment production changes its original targets, work, offsets or full history')
        required = self._current_evidence(current, fresh, prepared['input'])
        self._compare(current, fresh, reading.evidence(), current_evidence_refs=required)
        if fresh.method_evidence():
            raise TaskConflict('QS payment source validation unexpectedly executed a method')
        reading.recheck()

    def validate_source(self, record, context):
        """Reassemble full work/cash/credit history; never rerun the saved executor."""
        original = ActionContext.model_validate(record['context'])
        saved = record['prepared']
        projections = [QSPaymentResultView.model_validate(row) for row in saved['projections']]
        current, reading, prepared = self._prepare(context, record['action_input'])
        if (not projections or record['organization_id'] != reading.organization_id
                or any(getattr(original, name) != getattr(current, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))
                or [(row.result_kind, row.ref) for row in projections] != list(prepared['result_refs'].items())
                or saved['context_sha256'] != task_digest(original.model_dump(mode='json'))
                or saved['input_sha256'] != task_digest(record['action_input'])
                or saved['reading_sha256'] != task_digest(saved['source_reading'])
                or saved['projections_sha256'] != task_digest(saved['projections'])
                or prepared['input'].model_dump(mode='json') != saved['method_execution']['input']):
            raise TaskConflict('Current QS payment bundle differs from its original author, targets or full input history')
        author = projections[0].author_authority_ref
        for row in projections:
            if (row.author_authority_ref != author or row.author_actor_id != original.actor_id
                    or row.author_function_ref != original.function_ref or row.author_action_id != self.ACTION_ID
                    or row.authored_at != original.business_time or row.scope != original.scope
                    or row.contract_ref != prepared['contract_ref'] or row.application_ref != prepared['application_ref']
                    or row.valuation_basis != prepared['valuation_basis'] or row.correction_of != prepared['correction_of']):
                raise TaskConflict('QS payment bundle substitutes original source versions, author or correction target')
        cache = {}
        for item in saved['source_reading']:
            if not isinstance(item, dict) or set(item) != {'ref', 'projection'}:
                raise TaskConflict('Saved QS payment cache requires exact original ref/projection records')
            ref = Reference.model_validate(item['ref'])
            if ref.key() in cache:
                raise TaskConflict('Saved QS payment cache repeats a full reference')
            cache[ref.key()] = item
        required = self._current_evidence(current, reading, prepared['input'], author_authority_ref=author)
        refs = [*walk_references(prepared['input']), author, original.function_ref,
            *[ref for row in projections for ref in row.evidence_refs],
            *[Reference.model_validate(item['ref']) for item in reading.evidence()]]
        refs = {ref.key(): ref for ref in refs}
        if not refs.keys() <= cache.keys():
            raise TaskConflict('Saved QS payment omits original work, cash/credit history, numeric or author evidence')
        self._compare(current, reading, [cache[key] for key in refs], current_evidence_refs=required)
        grant = reading.resolve(author)
        if (not isinstance(grant, Authorization) or author not in current.authorization_refs
                or grant.organization_id != reading.organization_id or grant.actor_id != original.actor_id
                or grant.function_ref != original.function_ref or self.ACTION_ID not in grant.action_ids
                or not grant.validity.contains(original.business_time)
                or not any(scope_covers(scope, original.scope) for scope in grant.scopes)
                or not {ref.key() for ref in [*prepared['result_refs'].values(), *prepared['input'].source_refs]}
                    <= {ref.key() for ref in grant.readable_refs}):
            raise TaskConflict('Saved QS payment lost original author authority or complete result/input read permissions')
        if reading.method_evidence():
            raise TaskConflict('QS payment publication validation unexpectedly executed a method')
        reading.recheck()
        self._check()
        return True
