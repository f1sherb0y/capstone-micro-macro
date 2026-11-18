"""Re-read original QS quantity/price sources without repeating arithmetic execution."""
from integration.macro_views import AuthorizedMacroViewAssembler
from integration.module_host import module_factory_descriptor
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.qs_cost_objects import QSCostCalculationView, qs_cost_schemas
from src.actions.contracts.references import ActionReadView
from src.actions.registry import ActionRegistry
from src.actions.roles.qs_cost import prepare_cost_arithmetic
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization
from src.organization.registry import OrganizationRegistry, scope_covers


class QSCostCalculationSourceValidator:
    """Concrete source gates for cost production and save/publication/read.

    Use the original source provider beneath the publication wrapper. Caller
    holds the actual source/authorization writer guard. Reads certify exact
    current supplied versions only, not geometry, market calibration, physical
    work or native acceptance. No method, processor or model is executed here.
    """
    VERSION = 'qs-cost-calculation-source-validator.v1'
    SOURCE_SCHEMAS = staticmethod(qs_cost_schemas)

    def __init__(self, *, registry, organizations, provider, macro_version, source_mode):
        if (not isinstance(registry, ActionRegistry) or not isinstance(organizations, OrganizationRegistry)
                or not callable(getattr(provider, 'project', None))):
            raise ValueError('QS source validation requires original registry, authority and actual provider')
        self.registry, self.organizations, self.provider = registry, organizations, provider
        self._views = AuthorizedMacroViewAssembler(organizations, provider, self.SOURCE_SCHEMAS(),
            macro_version=macro_version, source_mode=source_mode)
        self._components = (registry, organizations, provider, self._views)
        self._declared = {'version': self.VERSION, 'run_id': organizations.run_id,
            'macro_version': macro_version, 'source_mode': source_mode,
            'provider': module_factory_descriptor(provider.project, 'QS.original_source_provider.project'),
            'validator': module_factory_descriptor(type(self).validate_source, self.VERSION)}

    def _check(self):
        if (any(actual is not original for actual, original in zip(
                (self.registry, self.organizations, self.provider, self._views), self._components))
                or self._views.provider is not self.provider or self._views.organizations is not self.organizations
                or self._views.macro_version != self._declared['macro_version']
                or self._views.source_mode != self._declared['source_mode']
                or module_factory_descriptor(self.provider.project, 'QS.original_source_provider.project') != self._declared['provider']
                or module_factory_descriptor(type(self).validate_source, self.VERSION) != self._declared['validator']):
            raise TaskConflict('QS calculation source validator changed its original provider or code binding')

    def _prepare(self, context, action_input):
        self._check()
        context = ActionContext.model_validate(context).model_copy(deep=True)
        expected_mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
        if (context.run_id != self.organizations.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != 'QS-A04' or expected_mode != self._views.source_mode):
            raise TaskConflict('QS source validation changes its original run, action or explicit source mode')
        registration = self.registry.get('QS-A04')
        if not registration.implemented or registration.role != 'QS' or registration.skill is None:
            raise TaskConflict('QS source validation requires its original implemented contract and Skill')
        action_input = registration.contract.validate_input(action_input)
        resolver = self._views.build_resolver(context, 'QS-A04', 'QS')
        reading = ActionReadView(context, resolver, self.organizations, 'QS-A04', 'QS')
        prepared = prepare_cost_arithmetic(context, action_input, reading)
        if prepared['kind'] != 'prepared':
            raise TaskConflict('Current original QS sources no longer support their prepared arithmetic input')
        return context, reading, prepared

    def _compare(self, context, reading, originals, *, current_evidence_refs=None):
        schemas = self.SOURCE_SCHEMAS()
        seen = set()
        for item in originals:
            if not isinstance(item, dict) or set(item) != {'ref', 'projection'}:
                raise TaskConflict('QS source validation requires exact original ref/projection records')
            ref = Reference.model_validate(item['ref'])
            if ref.key() in seen:
                raise TaskConflict('QS source validation repeats an original reference version')
            seen.add(ref.key())
            original = schemas.validate_projection(ref, item['projection'])
            current = reading.resolve(ref)
            if current != original:
                raise TaskConflict('QS calculation source differs from its original supplied projection version')
            if isinstance(current, EvidenceRecord):
                if (self._views.source_mode == 'formal' and current.source_kind == 'synthetic'
                        or (current_evidence_refs is None or ref.key() in current_evidence_refs)
                        and current.effective_window is not None and not current.effective_window.contains(context.business_time)):
                    raise TaskConflict('QS calculation evidence changes its current real source mode or validity')
        reading.recheck()
        self._check()

    def validate_current(self, *, context, action_input, arithmetic_input, reading):
        """Producer gate: compare current originals before its one actual method call."""
        if not isinstance(reading, ActionReadView) or reading._organizations is not self.organizations:
            raise TaskConflict('QS production changes its original authorized reading')
        reading.check_method_context(context, 'QS-A04')
        current, fresh, prepared = self._prepare(context, action_input)
        if (fresh.organization_id != reading.organization_id
                or prepared['input'].model_dump(mode='json') != arithmetic_input.model_dump(mode='json')):
            raise TaskConflict('QS production changes original arithmetic quantity/rate/coverage or source references')
        self._compare(current, fresh, reading.evidence())
        reading.recheck()

    def validate_source(self, record, context):
        """Persistence gate: reassemble input only; never rerun the saved method."""
        original = ActionContext.model_validate(record['context'])
        current, reading, prepared = self._prepare(context, record['action_input'])
        if (record['organization_id'] != reading.organization_id
                or any(getattr(original, name) != getattr(current, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))):
            raise TaskConflict('QS calculation publication changes its original author, scope, time or source mode')
        saved = record['prepared']
        projection = QSCostCalculationView.model_validate(saved['projection'])
        if (saved['context_sha256'] != task_digest(original.model_dump(mode='json'))
                or saved['input_sha256'] != task_digest(record['action_input'])
                or prepared['input'].model_dump(mode='json') != saved['method_execution']['input']
                or prepared['quantity_schedule_ref'] != projection.quantity_schedule_ref):
            raise TaskConflict('Current QS quantity/price/schedule input differs from its original saved execution')
        cache = {}
        for item in saved['source_reading']:
            ref = Reference.model_validate(item['ref'])
            if ref.key() in cache:
                raise TaskConflict('Saved QS source cache repeats a full reference')
            cache[ref.key()] = item
        refs = [*prepared['input'].source_refs, *projection.evidence_refs,
            projection.author_authority_ref, projection.author_function_ref]
        refs = {ref.key(): ref for ref in refs}
        if not refs.keys() <= cache.keys():
            raise TaskConflict('Saved QS execution omits its original numeric or author evidence')
        self._compare(current, reading, [cache[key] for key in refs])
        grant = reading.resolve(projection.author_authority_ref)
        if (not isinstance(grant, Authorization) or grant.organization_id != reading.organization_id
                or grant.actor_id != projection.author_actor_id or grant.function_ref != projection.author_function_ref
                or projection.author_action_id not in grant.action_ids or not grant.validity.contains(projection.calculated_at)
                or not any(scope_covers(scope, projection.scope) for scope in grant.scopes)):
            raise TaskConflict('Saved QS calculation lost its original independent author authority')
        reading.recheck()
        self._check()
        return True
