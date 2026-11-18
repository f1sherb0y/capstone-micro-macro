"""Re-read original QS-A07 quantity, rate and history versions without execution."""
from integration.qs_cost_calculation_validation import QSCostCalculationSourceValidator
from src.actions.contracts.common import ActionContext, Reference, ref_type, walk_references
from src.actions.contracts.qs_change_objects import QSChangeResultView, qs_change_schemas
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import prepare_change_arithmetic
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class QSChangeCalculationSourceValidator(QSCostCalculationSourceValidator):
    """Use the original provider beneath all calculation publication wrappers.

    Caller holds the actual source and authorization writer guard. Exact
    versions and permissions are checked; historical author/statement evidence
    retains its original dates, while numeric and current author bases must be
    current. This does not prove measurement, rate calibration, entitlement,
    physical work or native acceptance, and never executes a method or model.
    """
    VERSION = 'qs-change-calculation-source-validator.v1'
    ACTION_ID = 'QS-A07'
    SOURCE_SCHEMAS = staticmethod(qs_change_schemas)

    def _prepare(self, context, action_input, *, calculation_ref):
        self._check()
        context = ActionContext.model_validate(context).model_copy(deep=True)
        expected_mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
        if (context.run_id != self.organizations.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != 'QS-A07' or expected_mode != self._views.source_mode):
            raise TaskConflict('QS change validation changes its original run, action or explicit source mode')
        registration = self.registry.get('QS-A07')
        if not registration.implemented or registration.role != 'QS' or registration.skill is None:
            raise TaskConflict('QS change validation requires its original implemented contract and Skill')
        action_input = registration.contract.validate_input(action_input)
        resolver = self._views.build_resolver(context, 'QS-A07', 'QS')
        reading = ActionReadView(context, resolver, self.organizations, 'QS-A07', 'QS')
        prepared = prepare_change_arithmetic(context, action_input, reading, calculation_ref=calculation_ref)
        if prepared['kind'] != 'prepared':
            raise TaskConflict('Current original QS change sources no longer support their prepared arithmetic')
        return context, reading, prepared

    def _current_evidence(self, context, reading, arithmetic, *, author_authority_ref=None):
        required = {ref.key() for ref in walk_references(arithmetic) if ref.kind == 'Evidence'}
        author_refs = [grant.ref for grant in self.organizations.grants(context, self.ACTION_ID, 'QS')]
        if author_authority_ref is not None:
            author_refs.append(author_authority_ref)
        for ref in {ref.key(): ref for ref in author_refs}.values():
            grant = reading.resolve(ref)
            if (not isinstance(grant, Authorization) or grant.actor_id != context.actor_id
                    or grant.function_ref != context.function_ref or grant.organization_id != reading.organization_id):
                raise TaskConflict('QS change evidence substitutes its current original author grant')
            required.update(ref.key() for ref in grant.basis_refs)
        assignment = reading.resolve(context.function_ref)
        if (not isinstance(assignment, RoleAssignment) or assignment.role != 'QS'
                or assignment.function_ref != context.function_ref):
            raise TaskConflict('QS change evidence substitutes its current original author function')
        required.update(ref.key() for ref in assignment.basis_refs)
        for key in required:
            reading.resolve(Reference(kind=key[0], id=key[1], version=key[2]))
        return required

    def validate_current(self, *, context, action_input, arithmetic_input, reading, calculation_ref):
        """Producer gate: validate actual sources before its one arithmetic call."""
        if not isinstance(reading, ActionReadView) or reading._organizations is not self.organizations:
            raise TaskConflict('QS change production changes its original authorized reading')
        reading.check_method_context(context, self.ACTION_ID)
        calculation_ref = ref_type('MethodResult').model_validate(calculation_ref)
        if calculation_ref not in context.visible_refs:
            raise TaskConflict('QS change production changes its explicitly authorized calculation target')
        current, fresh, prepared = self._prepare(context, action_input, calculation_ref=calculation_ref)
        if (fresh.organization_id != reading.organization_id
                or prepared['input'].model_dump(mode='json') != arithmetic_input.model_dump(mode='json')):
            raise TaskConflict('QS change production changes original quantities, rates or complete history')
        required = self._current_evidence(current, fresh, prepared['input'])
        self._compare(current, fresh, reading.evidence(), current_evidence_refs=required)
        if fresh.method_evidence():
            raise TaskConflict('QS change source validation unexpectedly executed a method')
        reading.recheck()

    def validate_source(self, record, context):
        """Persistence/read gate: reassemble sources and preserve historical dates."""
        original = ActionContext.model_validate(record['context'])
        saved = record['prepared']
        projection = QSChangeResultView.model_validate(saved['projection'])
        current, reading, prepared = self._prepare(context, record['action_input'], calculation_ref=projection.ref)
        if (record['organization_id'] != reading.organization_id
                or any(getattr(original, name) != getattr(current, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))
                or projection.author_actor_id != original.actor_id or projection.author_function_ref != original.function_ref
                or projection.author_action_id != 'QS-A07' or projection.authored_at != original.business_time):
            raise TaskConflict('QS change publication substitutes its original author, scope, time or source mode')
        if (saved['context_sha256'] != task_digest(original.model_dump(mode='json'))
                or saved['input_sha256'] != task_digest(record['action_input'])
                or prepared['input'].model_dump(mode='json') != saved['method_execution']['input']
                or prepared['contract_ref'] != projection.contract_ref or prepared['claim_ref'] != projection.claim_ref
                or saved['reading_sha256'] != task_digest(saved['source_reading'])):
            raise TaskConflict('Current QS change inputs differ from their original saved execution')
        cache = {}
        for item in saved['source_reading']:
            if not isinstance(item, dict) or set(item) != {'ref', 'projection'}:
                raise TaskConflict('Saved QS change cache requires exact original ref/projection records')
            ref = Reference.model_validate(item['ref'])
            if ref.key() in cache:
                raise TaskConflict('Saved QS change cache repeats a full reference')
            cache[ref.key()] = item
        required = self._current_evidence(current, reading, prepared['input'],
            author_authority_ref=projection.author_authority_ref)
        refs = [*walk_references(prepared['input']), *projection.evidence_refs,
            projection.author_authority_ref, projection.author_function_ref,
            *[Reference.model_validate(item['ref']) for item in reading.evidence()]]
        refs = {ref.key(): ref for ref in refs}
        if not refs.keys() <= cache.keys():
            raise TaskConflict('Saved QS change omits original quantities, history, numeric or author evidence')
        self._compare(current, reading, [cache[key] for key in refs], current_evidence_refs=required)
        grant = reading.resolve(projection.author_authority_ref)
        if (not isinstance(grant, Authorization) or grant.organization_id != reading.organization_id
                or grant.actor_id != projection.author_actor_id or grant.function_ref != projection.author_function_ref
                or 'QS-A07' not in grant.action_ids or not grant.validity.contains(projection.authored_at)
                or not any(scope_covers(scope, projection.scope) for scope in grant.scopes)
                or not {ref.key() for ref in [projection.ref, *prepared['input'].source_refs]}
                    <= {ref.key() for ref in grant.readable_refs}):
            raise TaskConflict('Saved QS change lost its original author authority or input read permissions')
        if reading.method_evidence():
            raise TaskConflict('QS change publication validation unexpectedly executed a method')
        reading.recheck()
        self._check()
        return True
