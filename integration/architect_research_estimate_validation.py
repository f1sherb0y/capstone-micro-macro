"""Reread original A13 work and rate sources without running estimate arithmetic."""
from copy import deepcopy

from integration.architect_area_calculation_validation import ArchitectAreaCalculationSourceValidator
from integration.architect_research_actions import validate_architect_research_estimate_preparation_sources
from integration.module_host import module_factory_descriptor
from integration.qs_cost_calculation_validation import QSCostCalculationSourceValidator
from src.actions.contracts.architect_research_objects import (
    ArchitectResearchEstimatePreparation, ArchitectResearchEstimateView, architect_research_schemas,
)
from src.actions.contracts.common import ActionContext, EvidenceRecord
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.roles.architect_research import prepare_architect_research_estimate_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.architect_research_estimates import ARCHITECT_RESEARCH_ESTIMATE_METHOD, ArchitectResearchEstimateReport
from src.methods.models import MethodOk
from src.organization.models import Authorization


class ArchitectResearchEstimateSourceValidator(ArchitectAreaCalculationSourceValidator):
    """Reconstruct original A13 sources beneath every publication wrapper.

    Caller holds the actual source guard. Check the original research delegation,
    task, expense/work facts, limits, request, work quantity and rate sources.
    An explicit actual verifier must confirm numeric coverage and conventions.
    Isolate the future estimate and preserve the exact original cache. No
    comparison, estimate formula, task, resource, fee or cash effect runs here.
    """
    VERSION = 'architect-research-estimate-source-validator.v1'
    ACTION_ID = 'ARCHITECT-A13'
    ROLE = 'Architect'
    SOURCE_SCHEMAS = staticmethod(architect_research_schemas)

    def __init__(self, *, validate_estimate_basis, **components):
        if not callable(validate_estimate_basis):
            raise ValueError('Research estimate source validation requires an explicit actual work quantity/effort/rate coverage verifier')
        super().__init__(**components)
        self.validate_estimate_basis = validate_estimate_basis
        self._numeric_verifier = validate_estimate_basis
        self._declared['numeric_scope_verifier'] = module_factory_descriptor(
            validate_estimate_basis, 'Architect.research_estimate_numeric_scope')
        self._declared['current_runtime'] = module_factory_descriptor(
            ArchitectAreaCalculationSourceValidator.validate_current, 'Architect.research_estimate_current_runtime')
        self._declared['compare_runtime'] = module_factory_descriptor(
            QSCostCalculationSourceValidator._compare, 'Architect.research_estimate_compare_runtime')

    def _check(self):
        super()._check()
        if (self.validate_estimate_basis is not self._numeric_verifier
                or module_factory_descriptor(self.validate_estimate_basis, 'Architect.research_estimate_numeric_scope')
                    != self._declared['numeric_scope_verifier']
                or module_factory_descriptor(ArchitectAreaCalculationSourceValidator.validate_current,
                    'Architect.research_estimate_current_runtime') != self._declared['current_runtime']
                or module_factory_descriptor(QSCostCalculationSourceValidator._compare,
                    'Architect.research_estimate_compare_runtime') != self._declared['compare_runtime']):
            raise TaskConflict('Research estimate numeric verifier or original source runtime changed')

    def _reading(self, context, action_input, preparation, originals, *, saved_projection=None):
        self._check()
        context = ActionContext.model_validate(context).model_copy(deep=True)
        mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
        if (context.run_id != self.organizations.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or self._views.source_mode != mode):
            raise TaskConflict('Research estimate source validation replaces original run, action or source mode')
        registration = self.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.role != self.ROLE or registration.skill is None:
            raise TaskConflict('Research estimate source validation requires original implemented Architect action and Skill')
        action_input = registration.contract.validate_input(action_input)
        preparation = ArchitectResearchEstimatePreparation.model_validate(preparation).model_copy(deep=True)
        future = {preparation.calculation_ref.key()}
        if action_input.scope != context.scope or not isinstance(originals, list):
            raise TaskConflict('Research estimate source validation requires original scope and exact source cache')
        projection = self._views.assemble(context, self.ACTION_ID, self.ROLE)
        for row in projection.objects:
            if row.ref == preparation.calculation_ref and (saved_projection is None or row.value != saved_projection):
                raise TaskConflict('Original estimate provider already supplies or replaces the reserved result')
        resolver = ReferenceResolver(context.run_id, source_mode=mode, schemas=self.SOURCE_SCHEMAS())
        refs = []
        for row in projection.objects:
            if row.ref.key() not in future:
                resolver.register_projection(row.ref, row.value)
                refs.append(row.ref)
        resolver.freeze_read(context.read_token, refs)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, self.ROLE)
        self._compare(context, reading, originals, current_evidence_refs=set())
        validate_architect_research_estimate_preparation_sources(action_input, preparation=preparation,
            context=context, organization_id=reading.organization_id, sources=reading._reads)
        original = prepare_architect_research_estimate_input(context, action_input, reading, preparation)
        if (original['kind'] != 'prepared' or original['preparation'] != preparation
                or original['work'].estimate_basis is None
                or original['method'].ref != ARCHITECT_RESEARCH_ESTIMATE_METHOD
                or reading.method_evidence() or reading.evidence() != originals):
            raise TaskConflict('Actual estimate sources no longer support the same request, work basis or cache')
        if self.validate_estimate_basis(context=context.model_copy(deep=True),
                action_input=action_input.model_copy(deep=True), preparation=preparation.model_copy(deep=True),
                request=original['request'].model_copy(deep=True), work=original['work'].model_copy(deep=True),
                estimate_basis=original['work'].estimate_basis.model_copy(deep=True),
                arithmetic=preparation.input.model_copy(deep=True), original_sources=deepcopy(reading._reads),
                reading=reading) is not True:
            raise TaskConflict('Research estimate inputs lack independent actual work quantity/effort/rate convention verification')
        if reading.method_evidence() or reading.evidence() != originals:
            raise TaskConflict('Research estimate numeric verifier changed original cache or executed a method')
        reading.recheck()
        self._check()
        return context, action_input, reading, original

    def validate_source(self, record, context):
        """Save/publication/read gate: compare actual originals and current author."""
        original_context = ActionContext.model_validate(record['context'])
        saved = record['prepared']
        preparation = ArchitectResearchEstimatePreparation.model_validate(saved['preparation'])
        projection = ArchitectResearchEstimateView.model_validate(saved['projection'])
        current, _, reading, original = self._reading(context, record['action_input'], preparation,
            saved['source_reading'], saved_projection=projection)
        data = preparation.input
        execution = saved['method_execution']
        if not isinstance(execution, dict) or set(execution) != {'method_ref', 'registry_digest', 'input', 'result'}:
            raise TaskConflict('Research source gate requires complete original execution proof')
        result = MethodOk[ArchitectResearchEstimateReport].model_validate(execution['result'])
        report, task, request = result.value, original['task'], original['request']
        if (record['organization_id'] != reading.organization_id
                or any(getattr(original_context, name) != getattr(current, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))
                or saved['context_sha256'] != task_digest(record['context'])
                or saved['input_sha256'] != task_digest(record['action_input'])
                or saved['preparation_sha256'] != task_digest(saved['preparation'])
                or saved['reading_sha256'] != task_digest(saved['source_reading'])
                or saved['projection_sha256'] != task_digest(saved['projection'])
                or saved['estimate_input_sha256'] != task_digest(data.model_dump(mode='json'))
                or saved['source_mode'] != self._views.source_mode or saved['kind'] != 'prepared'
                or projection.model_dump(mode='json') != saved['projection']
                or projection.ref != preparation.calculation_ref or type(projection.ref.version) is not str
                or projection.task_ref != task.ref or projection.request_profile_ref != request.ref
                or projection.work_profile_ref != request.work_profile_ref or projection.ref != request.estimate_ref
                or projection.input_refs != request.input_refs or report.source_refs != data.source_refs
                or projection.effort_estimate.state != 'known' or projection.incremental_cost.state != 'known'
                or projection.effort_estimate.value != report.effort
                or projection.incremental_cost.value != report.estimated_cost
                or projection.effort_estimate != request.effort_estimate
                or projection.incremental_cost != request.incremental_cost
                or projection.scope != current.scope or projection.status != 'ok'
                or projection.method_ref != ARCHITECT_RESEARCH_ESTIMATE_METHOD
                or projection.available_at != current.business_time
                or projection.effective_window.model_dump(mode='json') != {
                    'start': current.business_time.model_dump(mode='json'),
                    'end': current.business_time.model_dump(mode='json'), 'bounds': 'closed_closed'}
                or execution['method_ref'] != ARCHITECT_RESEARCH_ESTIMATE_METHOD.model_dump(mode='json')
                or result.method_ref != ARCHITECT_RESEARCH_ESTIMATE_METHOD
                or execution['input'] != data.model_dump(mode='json')
                or execution['registry_digest'] != saved['method_registry_sha256']
                or projection.author_actor_id != current.actor_id or projection.author_function_ref != current.function_ref
                or projection.author_authority_ref != task.authority_ref
                or projection.author_authority_ref.model_dump(mode='json') != saved['author_authority_ref']):
            raise TaskConflict('Research source gate replaces original request, numeric inputs, report or author')
        grant = reading.resolve(projection.author_authority_ref)
        if (not isinstance(grant, Authorization) or projection.author_authority_ref not in current.authorization_refs
                or grant not in self.organizations.grants(current, self.ACTION_ID, self.ROLE)
                or projection.ref not in current.visible_refs or projection.ref not in grant.readable_refs):
            raise TaskConflict('Research source gate lacks current original author and target read authority')
        for ref in grant.basis_refs:
            evidence = reading.resolve(ref)
            if (not isinstance(evidence, EvidenceRecord)
                    or self._views.source_mode == 'formal' and evidence.source_kind == 'synthetic'
                    or evidence.effective_window is not None and not evidence.effective_window.contains(current.business_time)):
                raise TaskConflict('Research estimate author lacks current original authority evidence')
        if (projection.evidence_refs != [row.ref for row in reading._reads.values() if isinstance(row, EvidenceRecord)]
                or reading.evidence() != saved['source_reading'] or reading.method_evidence()):
            raise TaskConflict('Research source validation changes original evidence/cache or executes a method')
        reading.recheck()
        self._check()
        return True
