"""Re-read original QS-A10 clauses, actual work and advance receipt histories."""
from integration.module_host import module_factory_descriptor
from integration.qs_billing_actions import validate_qs_billing_sources
from integration.qs_cost_calculation_validation import QSCostCalculationSourceValidator
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, ref_type
from src.actions.contracts.qs_billing_objects import QSBillingCalculationView, qs_billing_schemas, qs_billing_types
from src.actions.contracts.references import ActionReadView
from src.actions.roles.service_billing import prepare_service_fee_calculation
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization


class QSBillingCalculationSourceValidator(QSCostCalculationSourceValidator):
    """Use the original provider beneath fee publication wrappers.

    Caller holds the actual source/authorization writer guard. Historical work,
    advances and receipts keep their original dates; current billing conditions
    and author evidence are checked by the original declared billing rules.
    Production source validation reads only; saved-output validation checks the
    existing formula without invoking a processor, method registry or model.
    """
    VERSION = 'qs-billing-calculation-source-validator.v1'
    ACTION_ID = 'QS-A10'
    SOURCE_SCHEMAS = staticmethod(qs_billing_schemas)

    def _reading(self, context, action_input, originals):
        self._check()
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if (context.run_id != self.organizations.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID
                or self._views.source_mode != ('fixture' if context.execution_mode == 'offline_fixture' else 'formal')):
            raise TaskConflict('Fee validation changes its original run, action or explicit source mode')
        registration = self.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.role != 'QS' or registration.skill is None:
            raise TaskConflict('Fee validation requires its original implemented QS contract and Skill')
        action_input = registration.contract.validate_input(action_input)
        if action_input.scope != context.scope or action_input.calculation_ref is not None:
            raise TaskConflict('Fee validation changes its original scope or consumes an existing calculation')
        resolver = self._views.build_resolver(context, self.ACTION_ID, 'QS')
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'QS')
        # Preserve historical validity windows. The shared billing rules check
        # only the work, receipt and current condition evidence actually used.
        self._compare(context, reading, originals, current_evidence_refs=set())
        validate_qs_billing_sources(action_input, context=context,
            organization_id=reading.organization_id, sources=reading._reads)
        return context, action_input, reading

    def validate_current(self, *, context, action_input, reading, calculation_ref):
        """Producer gate: verify actual source versions before computing the fee."""
        if not isinstance(reading, ActionReadView) or reading._organizations is not self.organizations:
            raise TaskConflict('Fee production changes its original authorized source reading')
        reading.check_method_context(context, self.ACTION_ID)
        current, _, fresh = self._reading(context, action_input, reading.evidence())
        target = ref_type('FeeCalculation').model_validate(calculation_ref)
        grants = self.organizations.grants(current, self.ACTION_ID, 'QS')
        if (type(target.version) is not str or fresh.organization_id != reading.organization_id
                or target not in current.visible_refs or not any(target in grant.readable_refs for grant in grants)
                or fresh.method_evidence()):
            raise TaskConflict('Fee production changes its original target, organization or declared formula path')
        reading.recheck()
        self._check()

    def validate_source(self, record, context):
        """Save/publication/read gate: match current originals to the saved formula output."""
        original = ActionContext.model_validate(record['context'])
        saved = record['prepared']
        projection = QSBillingCalculationView.model_validate(saved['projection'])
        current, action_input, reading = self._reading(context, record['action_input'], saved['source_reading'])
        if (record['organization_id'] != reading.organization_id
                or any(getattr(original, name) != getattr(current, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))
                or saved['context_sha256'] != task_digest(record['context'])
                or saved['input_sha256'] != task_digest(record['action_input'])
                or saved['reading_sha256'] != task_digest(saved['source_reading'])
                or saved['source_mode'] != self._views.source_mode
                or saved['formula'] != module_factory_descriptor(prepare_service_fee_calculation, 'service_fee.declared_formula')
                or saved['projection_sha256'] != task_digest(saved['projection'])):
            raise TaskConflict('Fee publication changes its original input, source cache, context or formula')
        author_ref = ref_type('Authorization').model_validate(saved['author_authority_ref'])
        grant = reading.resolve(author_ref)
        if (not isinstance(grant, Authorization) or author_ref not in current.authorization_refs
                or grant not in self.organizations.grants(current, self.ACTION_ID, 'QS')
                or projection.ref not in current.visible_refs or projection.ref not in grant.readable_refs):
            raise TaskConflict('Saved fee calculation lost its actual current author or target read authority')
        for ref in grant.basis_refs:
            evidence = reading.resolve(ref)
            if (not isinstance(evidence, EvidenceRecord)
                    or self._views.source_mode == 'formal' and evidence.source_kind == 'synthetic'
                    or evidence.effective_window is not None and not evidence.effective_window.contains(current.business_time)):
                raise TaskConflict('Saved fee calculation author lacks current original source evidence')
        prepared = prepare_service_fee_calculation(current, action_input, reading,
            role='QS', action_id=self.ACTION_ID, billing_types=qs_billing_types(), calculation_ref=projection.ref)
        if (prepared['kind'] != 'prepared' or prepared['projection'] != projection
                or reading.evidence() != saved['source_reading'] or reading.method_evidence()):
            raise TaskConflict('Current fee work, credit, correction or limit sources differ from the saved original calculation')
        reading.recheck()
        self._check()
        return True
