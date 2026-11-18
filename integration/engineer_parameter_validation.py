"""Reread original Engineer task, parameter catalog and invested work without execution."""
from integration.engineer_design_actions import validate_engineer_parameter_preparation_sources
from integration.qs_cost_calculation_validation import QSCostCalculationSourceValidator
from src.actions.contracts.common import ActionContext, EvidenceRecord
from src.actions.contracts.engineer_design_objects import (
    EngineerDesignParameterPreparation, EngineerDesignMethodProjection, EngineerParameterResultView,
    engineer_design_schemas,
)
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.roles.engineer_design import prepare_engineer_parameter_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.engineer_parameters import PARAMETER_METHOD
from src.organization.models import Authorization


class EngineerParameterSourceValidator(QSCostCalculationSourceValidator):
    """Read the original provider beneath the parameter publication wrapper.

    Caller holds its actual source guard. Original task, parameter values,
    finite catalogs, evidence, prior design, invested work and authority are
    revalidated. No parameter formula or registered method executes here; the
    publication store separately verifies the full retained method proof.
    """
    VERSION = 'engineer-parameter-source-validator.v1'
    ACTION_ID = 'ENGINEER-A05'
    ROLE = 'Engineer'
    SOURCE_SCHEMAS = staticmethod(engineer_design_schemas)
    PREPARATION_MODEL = EngineerDesignParameterPreparation
    RESULT_MODEL = EngineerParameterResultView
    PROJECTION_MODEL = EngineerDesignMethodProjection
    METHOD_REF = PARAMETER_METHOD
    INPUT_SHA_FIELD = 'parameter_input_sha256'
    VALIDATE_SOURCES = staticmethod(validate_engineer_parameter_preparation_sources)
    PREPARE_INPUT = staticmethod(prepare_engineer_parameter_input)

    def _projection_result(self, projection):
        return projection.record

    def _result_matches_input(self, value, original, preparation):
        return value.engineering_profile_ref == original['profile'].ref and value.input == preparation.input

    def _future_result_keys(self, action_input, preparation):
        return {ref.key() for ref in action_input.method_result_refs}

    def _result_author_matches(self, value, context):
        return value.author_action_id == self.ACTION_ID

    def _reading(self, context, action_input, preparation, originals, *, saved_projection=None):
        self._check()
        context = ActionContext.model_validate(context).model_copy(deep=True)
        mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
        if (context.run_id != self.organizations.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or self._views.source_mode != mode):
            raise TaskConflict('Parameter source validation substitutes original run, action or source mode')
        registration = self.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.role != self.ROLE or registration.skill is None:
            raise TaskConflict('Parameter source validation requires original implemented Engineer action and Skill')
        action_input = registration.contract.validate_input(action_input)
        preparation = self.PREPARATION_MODEL.model_validate(preparation).model_copy(deep=True)
        future_keys = self._future_result_keys(action_input, preparation)
        if action_input.scope != context.scope or not isinstance(originals, list):
            raise TaskConflict('Parameter source validation requires original scope and exact source cache records')
        projection = self._views.assemble(context, self.ACTION_ID, self.ROLE)
        for row in projection.objects:
            if row.ref == preparation.calculation_ref and (saved_projection is None or row.value != saved_projection):
                raise TaskConflict('Parameter source provider already supplies or substitutes the original result target')
        resolver = ReferenceResolver(context.run_id, source_mode=mode, schemas=self.SOURCE_SCHEMAS())
        refs = []
        for row in projection.objects:
            if row.ref.key() not in future_keys:
                resolver.register_projection(row.ref, row.value)
                refs.append(row.ref)
        resolver.freeze_read(context.read_token, refs)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, self.ROLE)
        # Historical invested work keeps its dates; preparation checks current
        # evidence and the original task/author chronology independently.
        self._compare(context, reading, originals, current_evidence_refs=set())
        self.VALIDATE_SOURCES(action_input, preparation=preparation,
            context=context, organization_id=reading.organization_id, sources=reading._reads)
        original = self.PREPARE_INPUT(context, action_input, reading, preparation)
        if (original['kind'] != 'prepared' or original['preparation'] != preparation
                or reading.method_evidence() or reading.evidence() != originals):
            raise TaskConflict('Current sources no longer support the same parameter input and original cache')
        reading.recheck()
        self._check()
        return context, action_input, reading, original

    def validate_current(self, *, context, action_input, preparation, reading):
        """Producer gate: independently rebuild the exact predeclared input."""
        if not isinstance(reading, ActionReadView) or reading._organizations is not self.organizations:
            raise TaskConflict('Parameter production changes its original authorized reading')
        reading.check_method_context(context, self.ACTION_ID)
        before = reading.method_evidence()
        current, _, fresh, original = self._reading(context, action_input, preparation, reading.evidence())
        target = original['preparation'].calculation_ref
        grants = self.organizations.grants(current, self.ACTION_ID, self.ROLE)
        if (fresh.organization_id != reading.organization_id or type(target.version) is not str
                or target not in current.visible_refs or not any(target in grant.readable_refs for grant in grants)
                or reading.method_evidence() != before or fresh.method_evidence()):
            raise TaskConflict('Parameter production changes original target authority or executes a method in its source gate')
        reading.recheck()
        self._check()

    def validate_source(self, record, context):
        """Save/publication/read gate: match actual original sources and author."""
        original_context = ActionContext.model_validate(record['context'])
        saved = record['prepared']
        preparation = self.PREPARATION_MODEL.model_validate(saved['preparation'])
        projection = self.PROJECTION_MODEL.model_validate(saved['projection'])
        value = self._projection_result(projection)
        if not isinstance(value, self.RESULT_MODEL):
            raise TaskConflict('Parameter source gate cannot accept an unrelated professional check')
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
                or saved[self.INPUT_SHA_FIELD] != task_digest(preparation.input.model_dump(mode='json'))
                or saved['source_mode'] != self._views.source_mode or saved['kind'] != 'prepared'
                or projection.model_dump(mode='json') != saved['projection']
                or projection.ref != preparation.calculation_ref or value.ref != projection.ref
                or type(projection.ref.version) is not str or value.task_ref != original['task'].ref
                or not self._result_matches_input(value, original, preparation)
                or value.scope != current.scope or value.status != 'ok' or value.method_ref != self.METHOD_REF
                or value.executed_at != current.business_time or value.available_at != current.business_time
                or not value.effective_window.contains(current.business_time)
                or saved['method_execution']['method_ref'] != self.METHOD_REF.model_dump(mode='json')
                or saved['method_execution']['input'] != preparation.input.model_dump(mode='json')
                or value.author_actor_id != current.actor_id or value.author_function_ref != current.function_ref
                or not self._result_author_matches(value, current) or value.author_authority_ref != original['task'].authority_ref
                or value.author_authority_ref.model_dump(mode='json') != saved['author_authority_ref']):
            raise TaskConflict('Parameter publication substitutes original task/catalog/value/input/context or author')
        grant = reading.resolve(value.author_authority_ref)
        if (not isinstance(grant, Authorization) or value.author_authority_ref not in current.authorization_refs
                or grant not in self.organizations.grants(current, self.ACTION_ID, self.ROLE)
                or projection.ref not in current.visible_refs or projection.ref not in grant.readable_refs):
            raise TaskConflict('Parameter result lost original actual author or current target read authority')
        for ref in grant.basis_refs:
            evidence = reading.resolve(ref)
            if (not isinstance(evidence, EvidenceRecord)
                    or self._views.source_mode == 'formal' and evidence.source_kind == 'synthetic'
                    or evidence.effective_window is not None and not evidence.effective_window.contains(current.business_time)):
                raise TaskConflict('Parameter author lacks current original source evidence')
        if reading.evidence() != saved['source_reading'] or reading.method_evidence():
            raise TaskConflict('Parameter source validation changes original cache or executes a registered method')
        reading.recheck()
        self._check()
        return True
