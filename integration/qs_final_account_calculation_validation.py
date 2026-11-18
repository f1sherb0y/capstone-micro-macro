"""Re-read original QS-A09 settlement sources without repeating reconciliation."""
from integration.qs_change_calculation_validation import QSChangeCalculationSourceValidator
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.qs_final_account_objects import QSFinalResultView, qs_final_account_schemas
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_final_account import prepare_final_account_arithmetic
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization
from src.organization.registry import scope_covers


class QSFinalAccountCalculationSourceValidator(QSChangeCalculationSourceValidator):
    """Concrete production/save/publication/read gate using the original provider.

    Caller holds the actual source and authorization writer guard. Reassembly
    preserves original certificate chains, claims, cash and independent
    adjustment mechanisms. Historical author evidence retains its dates;
    numeric and current QS authority bases must be current. These checks do not
    establish legal settlement, cash clearance or resolved disputes.
    """
    VERSION = 'qs-final-account-calculation-source-validator.v1'
    ACTION_ID = 'QS-A09'
    SOURCE_SCHEMAS = staticmethod(qs_final_account_schemas)

    def _prepare(self, context, action_input, *, calculation_ref):
        self._check()
        context = ActionContext.model_validate(context).model_copy(deep=True)
        expected_mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
        if (context.run_id != self.organizations.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or expected_mode != self._views.source_mode
                or calculation_ref not in context.visible_refs):
            raise TaskConflict('Final-account validation changes its original run, action, target or source mode')
        registration = self.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.role != 'QS' or registration.skill is None:
            raise TaskConflict('Final-account validation requires its original implemented contract and Skill')
        action_input = registration.contract.validate_input(action_input)
        resolver = self._views.build_resolver(context, self.ACTION_ID, 'QS')
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'QS')
        prepared = prepare_final_account_arithmetic(context, action_input, reading)
        if prepared['kind'] != 'prepared':
            raise TaskConflict('Current original final history no longer supports the saved reconciliation input')
        return context, reading, prepared

    def validate_source(self, record, context):
        """Reassemble original sources and compare input; no method or model call."""
        original = ActionContext.model_validate(record['context'])
        saved = record['prepared']
        projection = QSFinalResultView.model_validate(saved['projection'])
        current, reading, prepared = self._prepare(context, record['action_input'], calculation_ref=projection.ref)
        if (record['organization_id'] != reading.organization_id
                or any(getattr(original, name) != getattr(current, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))
                or projection.author_actor_id != original.actor_id or projection.author_function_ref != original.function_ref
                or projection.author_organization_id != record['organization_id'] or projection.author_action_id != self.ACTION_ID
                or projection.authored_at != original.business_time or projection.executed_at != original.business_time
                or projection.scope != original.scope):
            raise TaskConflict('Final reconciliation substitutes its original author, scope, time or source mode')
        if (saved['context_sha256'] != task_digest(original.model_dump(mode='json'))
                or saved['input_sha256'] != task_digest(record['action_input'])
                or saved['reading_sha256'] != task_digest(saved['source_reading'])
                or saved['projection_sha256'] != task_digest(projection.model_dump(mode='json'))
                or prepared['input'].model_dump(mode='json') != saved['method_execution']['input']
                or projection.data != prepared['input'] or prepared['contract_ref'] != projection.contract_ref):
            raise TaskConflict('Current final price, certificates, cash or adjustment history differs from saved execution')
        cache = {}
        for item in saved['source_reading']:
            if not isinstance(item, dict) or set(item) != {'ref', 'projection'}:
                raise TaskConflict('Saved final-account cache requires exact original ref/projection records')
            ref = Reference.model_validate(item['ref'])
            if ref.key() in cache:
                raise TaskConflict('Saved final-account cache repeats a full reference')
            cache[ref.key()] = item
        required = self._current_evidence(current, reading, prepared['input'],
            author_authority_ref=projection.author_authority_ref)
        refs = [*walk_references(prepared['input']), *projection.evidence_refs,
            *prepared['unresolved_claim_refs'], *prepared['source_statement_refs'],
            projection.author_authority_ref, projection.author_function_ref,
            *[Reference.model_validate(item['ref']) for item in reading.evidence()]]
        refs = {ref.key(): ref for ref in refs}
        if not refs.keys() <= cache.keys():
            raise TaskConflict('Saved final account omits original claims, statements, settlement or author evidence')
        self._compare(current, reading, [cache[key] for key in refs], current_evidence_refs=required)
        grant = reading.resolve(projection.author_authority_ref)
        if (not isinstance(grant, Authorization) or projection.author_authority_ref not in current.authorization_refs
                or grant.organization_id != reading.organization_id or grant.actor_id != original.actor_id
                or grant.function_ref != original.function_ref or self.ACTION_ID not in grant.action_ids
                or not grant.validity.contains(original.business_time)
                or not any(scope_covers(scope, original.scope) for scope in grant.scopes)
                or not {ref.key() for ref in [projection.ref, *prepared['input'].source_refs]}
                    <= {ref.key() for ref in grant.readable_refs}):
            raise TaskConflict('Final reconciliation lost original author authority or source read permissions')
        if reading.method_evidence():
            raise TaskConflict('Final-account source validation unexpectedly executed a method')
        reading.recheck()
        self._check()
        return True
