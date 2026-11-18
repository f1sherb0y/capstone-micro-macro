"""Reread original Architect draft, catalog and invested work without arithmetic."""
from integration.architect_design_actions import validate_architect_area_preparation_sources
from integration.qs_cost_calculation_validation import QSCostCalculationSourceValidator
from src.actions.contracts.architect_design_objects import (
    ArchitectDesignAreaPreparation, ArchitectDesignAreaResultView, architect_design_schemas,
)
from src.actions.contracts.common import ActionContext, EvidenceRecord
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.roles.architect_design import prepare_architect_area_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.architect_area import AREA_METHOD
from src.organization.models import Authorization


class ArchitectAreaCalculationSourceValidator(QSCostCalculationSourceValidator):
    """Use the original provider beneath the area-report publication wrapper.

    Caller holds the actual source/authorization guard. Exact original task,
    drafts, variable mapping, finite catalog and actual work are revalidated.
    This certifies supplied versions, with no measurement, design approval,
    registered method execution or report arithmetic. The store checks proof.
    """
    VERSION = 'architect-area-calculation-source-validator.v1'
    ACTION_ID = 'ARCHITECT-A05'
    ROLE = 'Architect'
    SOURCE_SCHEMAS = staticmethod(architect_design_schemas)

    def _reading(self, context, action_input, preparation, originals, *, saved_projection=None):
        self._check()
        context = ActionContext.model_validate(context).model_copy(deep=True)
        mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
        if (context.run_id != self.organizations.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or self._views.source_mode != mode):
            raise TaskConflict('Area source validation substitutes original run, action or source mode')
        registration = self.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.role != self.ROLE or registration.skill is None:
            raise TaskConflict('Area source validation requires the original implemented Architect action and Skill')
        action_input = registration.contract.validate_input(action_input)
        preparation = ArchitectDesignAreaPreparation.model_validate(preparation).model_copy(deep=True)
        future_keys = {ref.key() for ref in action_input.method_result_refs}
        if action_input.scope != context.scope or not isinstance(originals, list):
            raise TaskConflict('Area source validation requires original scope and exact source cache records')
        projection = self._views.assemble(context, self.ACTION_ID, self.ROLE)
        for row in projection.objects:
            if row.ref == preparation.calculation_ref and (saved_projection is None or row.value != saved_projection):
                raise TaskConflict('Area source provider already supplies or substitutes the original report target')
        resolver = ReferenceResolver(context.run_id, source_mode=mode, schemas=self.SOURCE_SCHEMAS())
        refs = []
        for row in projection.objects:
            if row.ref.key() not in future_keys:
                resolver.register_projection(row.ref, row.value)
                refs.append(row.ref)
        resolver.freeze_read(context.read_token, refs)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, self.ROLE)
        # Historical work retains its dates; the original role checks each
        # current evidence window and each actual work investment's chronology.
        self._compare(context, reading, originals, current_evidence_refs=set())
        validate_architect_area_preparation_sources(action_input, preparation=preparation,
            context=context, organization_id=reading.organization_id, sources=reading._reads)
        original = prepare_architect_area_input(context, action_input, reading, preparation)
        if (original['kind'] != 'prepared' or original['preparation'] != preparation
                or reading.method_evidence() or reading.evidence() != originals):
            raise TaskConflict('Current original sources no longer support the same area draft, mapping and input cache')
        reading.recheck()
        self._check()
        return context, action_input, reading, original

    def validate_current(self, *, context, action_input, preparation, reading):
        """Producer gate: independently reassemble the same predeclared input."""
        if not isinstance(reading, ActionReadView) or reading._organizations is not self.organizations:
            raise TaskConflict('Area production changes its original authorized reading')
        reading.check_method_context(context, self.ACTION_ID)
        before = reading.method_evidence()
        current, _, fresh, original = self._reading(context, action_input, preparation, reading.evidence())
        target = original['preparation'].calculation_ref
        grants = self.organizations.grants(current, self.ACTION_ID, self.ROLE)
        if (fresh.organization_id != reading.organization_id or type(target.version) is not str
                or target not in current.visible_refs or not any(target in grant.readable_refs for grant in grants)
                or reading.method_evidence() != before or fresh.method_evidence()):
            raise TaskConflict('Area production changes original target authority or executes a method in its source gate')
        reading.recheck()
        self._check()

    def validate_source(self, record, context):
        """Save/publication/read gate: match the actual original sources and author."""
        original_context = ActionContext.model_validate(record['context'])
        saved = record['prepared']
        preparation = ArchitectDesignAreaPreparation.model_validate(saved['preparation'])
        projection = ArchitectDesignAreaResultView.model_validate(saved['projection'])
        current, _, reading, original = self._reading(context, record['action_input'], preparation,
            saved['source_reading'], saved_projection=projection)
        if (record['organization_id'] != reading.organization_id
                or any(getattr(original_context, name) != getattr(current, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))
                or saved['context_sha256'] != task_digest(record['context'])
                or saved['input_sha256'] != task_digest(record['action_input'])
                or saved['preparation_sha256'] != task_digest(saved['preparation'])
                or saved['reading_sha256'] != task_digest(saved['source_reading'])
                or saved['projection_sha256'] != task_digest(saved['projection'])
                or saved['area_input_sha256'] != task_digest(preparation.input.model_dump(mode='json'))
                or saved['source_mode'] != self._views.source_mode or saved['kind'] != 'prepared'
                or projection.model_dump(mode='json') != saved['projection']
                or projection.ref != preparation.calculation_ref or type(projection.ref.version) is not str
                or projection.task_ref != original['task'].ref or projection.design_profile_ref != original['profile'].ref
                or projection.draft_index != preparation.draft_index or projection.input != preparation.input
                or projection.area_variable_refs != preparation.area_variable_refs
                or projection.floor_count_variable_refs != preparation.floor_count_variable_refs
                or projection.scope != current.scope or projection.status != 'ok' or projection.method_ref != AREA_METHOD
                or projection.executed_at != current.business_time or projection.available_at != current.business_time
                or not projection.effective_window.contains(current.business_time)
                or saved['method_execution']['method_ref'] != AREA_METHOD.model_dump(mode='json')
                or saved['method_execution']['input'] != preparation.input.model_dump(mode='json')
                or projection.author_actor_id != current.actor_id or projection.author_function_ref != current.function_ref
                or projection.author_authority_ref.model_dump(mode='json') != saved['author_authority_ref']):
            raise TaskConflict('Area publication substitutes original source, draft, mapped input, context or author')
        grant = reading.resolve(projection.author_authority_ref)
        if (not isinstance(grant, Authorization) or projection.author_authority_ref not in current.authorization_refs
                or grant not in self.organizations.grants(current, self.ACTION_ID, self.ROLE)
                or projection.ref not in current.visible_refs or projection.ref not in grant.readable_refs):
            raise TaskConflict('Area report lost its original actual author or current target read authority')
        for ref in grant.basis_refs:
            evidence = reading.resolve(ref)
            if (not isinstance(evidence, EvidenceRecord)
                    or self._views.source_mode == 'formal' and evidence.source_kind == 'synthetic'
                    or evidence.effective_window is not None and not evidence.effective_window.contains(current.business_time)):
                raise TaskConflict('Area author lacks current original source evidence')
        if reading.evidence() != saved['source_reading'] or reading.method_evidence():
            raise TaskConflict('Area source validation changes the original cache or executes a registered method')
        reading.recheck()
        self._check()
        return True
