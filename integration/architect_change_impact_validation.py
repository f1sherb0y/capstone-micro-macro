"""Reread original A09 impact sources without executing difference arithmetic."""
from copy import deepcopy

from integration.architect_area_calculation_validation import ArchitectAreaCalculationSourceValidator
from integration.architect_change_actions import validate_architect_change_impact_preparation_sources
from integration.module_host import module_factory_descriptor
from integration.qs_cost_calculation_validation import QSCostCalculationSourceValidator
from src.actions.contracts.architect_change_objects import (
    ArchitectChangeImpactPreparation, ArchitectChangeImpactResultView, architect_change_schemas,
)
from src.actions.contracts.common import ActionContext, EvidenceRecord
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.roles.architect_change import prepare_architect_change_impact_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.architect_change_impact import ARCHITECT_CHANGE_IMPACT_METHOD, ArchitectChangeImpactReport
from src.methods.models import MethodOk
from src.organization.models import Authorization


class ArchitectChangeImpactSourceValidator(ArchitectAreaCalculationSourceValidator):
    """Use the original provider beneath every publication wrapper.

    Caller holds the actual source guard. Independently reconstruct issue,
    obligation, content, instruction, affected scope/dependencies/variables,
    original permitted method and sourced numeric basis. An explicit actual
    verifier must confirm totals cover the same scope and cost/time conventions.
    Isolate future results; preserve the exact source cache and A09 author.
    No formula, impact result, change, fee right or use permission is produced.
    """
    VERSION = 'architect-change-impact-source-validator.v1'
    ACTION_ID = 'ARCHITECT-A09'
    ROLE = 'Architect'
    SOURCE_SCHEMAS = staticmethod(architect_change_schemas)

    def __init__(self, *, validate_impact_basis, **components):
        if not callable(validate_impact_basis):
            raise ValueError('Impact source validation requires an explicit actual numeric scope/cost/time verifier')
        super().__init__(**components)
        self.validate_impact_basis = validate_impact_basis
        self._numeric_verifier = validate_impact_basis
        self._declared['numeric_scope_verifier'] = module_factory_descriptor(
            validate_impact_basis, 'Architect.change_impact_numeric_scope')
        self._declared['current_runtime'] = module_factory_descriptor(
            ArchitectAreaCalculationSourceValidator.validate_current, 'Architect.change_impact_current_runtime')
        self._declared['compare_runtime'] = module_factory_descriptor(
            QSCostCalculationSourceValidator._compare, 'Architect.change_impact_compare_runtime')

    def _check(self):
        super()._check()
        if (self.validate_impact_basis is not self._numeric_verifier
                or module_factory_descriptor(self.validate_impact_basis, 'Architect.change_impact_numeric_scope')
                    != self._declared['numeric_scope_verifier']
                or module_factory_descriptor(ArchitectAreaCalculationSourceValidator.validate_current,
                    'Architect.change_impact_current_runtime') != self._declared['current_runtime']
                or module_factory_descriptor(QSCostCalculationSourceValidator._compare,
                    'Architect.change_impact_compare_runtime') != self._declared['compare_runtime']):
            raise TaskConflict('Impact numeric verifier or original source runtime changed')

    def _reading(self, context, action_input, preparation, originals, *, saved_projection=None):
        self._check()
        context = ActionContext.model_validate(context).model_copy(deep=True)
        mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
        if (context.run_id != self.organizations.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or self._views.source_mode != mode):
            raise TaskConflict('Impact source validation replaces original run, action or source mode')
        registration = self.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.role != self.ROLE or registration.skill is None:
            raise TaskConflict('Impact source validation requires original implemented Architect action and Skill')
        action_input = registration.contract.validate_input(action_input)
        preparation = ArchitectChangeImpactPreparation.model_validate(preparation).model_copy(deep=True)
        future = {ref.key() for ref in action_input.impact_result_refs}
        if action_input.scope != context.scope or not isinstance(originals, list):
            raise TaskConflict('Impact source validation requires original scope and exact source cache')
        projection = self._views.assemble(context, self.ACTION_ID, self.ROLE)
        for row in projection.objects:
            if row.ref == preparation.calculation_ref and (saved_projection is None or row.value != saved_projection):
                raise TaskConflict('Original impact provider already supplies or replaces the reserved result')
        resolver = ReferenceResolver(context.run_id, source_mode=mode, schemas=self.SOURCE_SCHEMAS())
        refs = []
        for row in projection.objects:
            if row.ref.key() not in future:
                resolver.register_projection(row.ref, row.value)
                refs.append(row.ref)
        resolver.freeze_read(context.read_token, refs)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, self.ROLE)
        self._compare(context, reading, originals, current_evidence_refs=set())
        validate_architect_change_impact_preparation_sources(action_input, preparation=preparation,
            context=context, organization_id=reading.organization_id, sources=reading._reads)
        original = prepare_architect_change_impact_input(context, action_input, reading, preparation)
        if (original['kind'] != 'prepared' or original['preparation'] != preparation
                or original['arithmetic'] is None or original['impact_basis'] is None
                or original['method'].ref != ARCHITECT_CHANGE_IMPACT_METHOD
                or reading.method_evidence() or reading.evidence() != originals):
            raise TaskConflict('Actual impact sources no longer support the same evaluation, numeric basis or cache')
        if self.validate_impact_basis(context=context.model_copy(deep=True),
                action_input=action_input.model_copy(deep=True), preparation=preparation.model_copy(deep=True),
                impact_basis=original['impact_basis'].model_copy(deep=True),
                arithmetic=original['arithmetic'].model_copy(deep=True), original_sources=deepcopy(reading._reads),
                reading=reading) is not True:
            raise TaskConflict('Impact totals lack independent actual scope/cost/time convention verification')
        if reading.method_evidence() or reading.evidence() != originals:
            raise TaskConflict('Impact numeric verifier changed original cache or executed a method')
        reading.recheck()
        self._check()
        return context, action_input, reading, original

    def validate_source(self, record, context):
        """Save/publication/read gate: compare actual originals and current author."""
        original_context = ActionContext.model_validate(record['context'])
        saved = record['prepared']
        preparation = ArchitectChangeImpactPreparation.model_validate(saved['preparation'])
        projection = ArchitectChangeImpactResultView.model_validate(saved['projection'])
        current, action_input, reading, original = self._reading(context, record['action_input'], preparation,
            saved['source_reading'], saved_projection=projection)
        data = original['arithmetic']
        execution = saved['method_execution']
        if not isinstance(execution, dict) or set(execution) != {'method_ref', 'registry_digest', 'input', 'result'}:
            raise TaskConflict('Impact source gate requires complete original execution proof')
        report = MethodOk[ArchitectChangeImpactReport].model_validate(execution['result']).value
        if (record['organization_id'] != reading.organization_id
                or any(getattr(original_context, name) != getattr(current, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))
                or saved['context_sha256'] != task_digest(record['context'])
                or saved['input_sha256'] != task_digest(record['action_input'])
                or saved['preparation_sha256'] != task_digest(saved['preparation'])
                or saved['reading_sha256'] != task_digest(saved['source_reading'])
                or saved['projection_sha256'] != task_digest(saved['projection'])
                or saved['impact_input_sha256'] != task_digest(data.model_dump(mode='json'))
                or saved['source_mode'] != self._views.source_mode or saved['kind'] != 'prepared'
                or projection.model_dump(mode='json') != saved['projection']
                or projection.ref != preparation.calculation_ref or type(projection.ref.version) is not str
                or projection.issue_ref != original['issue'].ref or projection.used_deliverable_ref != original['original'].ref
                or projection.instruction_ref != action_input.instruction_ref
                or projection.input_sha256 != original['input_sha256'] or projection.input_sha256 != data.input_sha256
                or report.input_sha256 != data.input_sha256 or report.source_refs != data.source_refs
                or projection.cost_delta != report.cost_delta or projection.duration_delta != report.duration_delta
                or projection.scope != current.scope or projection.status != 'ok'
                or projection.method_ref != ARCHITECT_CHANGE_IMPACT_METHOD
                or projection.executed_at != current.business_time or projection.available_at != current.business_time
                or not projection.effective_window.contains(current.business_time)
                or execution['method_ref'] != ARCHITECT_CHANGE_IMPACT_METHOD.model_dump(mode='json')
                or execution['input'] != data.model_dump(mode='json')
                or projection.author_organization_id != reading.organization_id
                or projection.author_organization_id not in original['method'].permitted_author_ids
                or projection.author_action_id != self.ACTION_ID
                or projection.author_actor_id != current.actor_id or projection.author_function_ref != current.function_ref
                or projection.author_authority_ref != original['profile'].authority_ref
                or projection.author_authority_ref.model_dump(mode='json') != saved['author_authority_ref']):
            raise TaskConflict('Impact source gate replaces original evaluation, numeric inputs, report or author')
        grant = reading.resolve(projection.author_authority_ref)
        if (not isinstance(grant, Authorization) or projection.author_authority_ref not in current.authorization_refs
                or grant not in self.organizations.grants(current, self.ACTION_ID, self.ROLE)
                or projection.ref not in current.visible_refs or projection.ref not in grant.readable_refs):
            raise TaskConflict('Impact source gate lacks current original author/target authority')
        for ref in grant.basis_refs:
            evidence = reading.resolve(ref)
            if (not isinstance(evidence, EvidenceRecord)
                    or self._views.source_mode == 'formal' and evidence.source_kind == 'synthetic'
                    or evidence.effective_window is not None and not evidence.effective_window.contains(current.business_time)):
                raise TaskConflict('Impact author lacks current original source evidence')
        if reading.evidence() != saved['source_reading'] or reading.method_evidence():
            raise TaskConflict('Impact source validation changed original cache or executed a method')
        reading.recheck()
        self._check()
        return True
