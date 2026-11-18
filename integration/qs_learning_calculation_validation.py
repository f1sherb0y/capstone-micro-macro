"""Re-read actual immutable predictions and lawfully received QS cost outcomes."""
from integration.qs_cost_calculation_validation import QSCostCalculationSourceValidator
from integration.qs_learning_actions import validate_qs_learning_sources
from src.actions.contracts.common import ActionContext, EvidenceRecord, ref_type
from src.actions.contracts.qs_learning_objects import QSComparisonResultView, qs_learning_schemas
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_learning import prepare_qs_forecast_comparison_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.qs_learning import COMPARABILITY_METHOD, QSForecastComparisonInput
from src.organization.models import Authorization


class QSLearningComparabilitySourceValidator(QSCostCalculationSourceValidator):
    """Compare originals beneath the publication wrapper without executing methods.

    Caller holds the actual source/authorization guard. Frozen predictions,
    information and past outcomes retain historical dates; original learning
    rules enforce authorship, chronology, current state and lawful outcome use.
    Save/publication/read share the same input-source checks. Retained method
    execution and report arithmetic are separately checked by the store.
    """
    VERSION = 'qs-learning-comparability-source-validator.v1'
    ACTION_ID = 'QS-A12'
    ROLE = 'QS'
    SOURCE_SCHEMAS = staticmethod(qs_learning_schemas)
    VALIDATE_SOURCES = staticmethod(validate_qs_learning_sources)
    METHOD_REF = COMPARABILITY_METHOD
    PREPARE_INPUT = staticmethod(prepare_qs_forecast_comparison_input)
    REQUIRE_EMPTY_COMPARISON = True
    PROJECTION_MODEL = QSComparisonResultView

    def _matches_projection_identity(self, projection, action_input):
        return projection.method_ref == self.METHOD_REF

    def _matches_projection_input(self, projection, data):
        return projection.data == data

    def _build_resolver(self,context,action_input):
        return self._views.build_resolver(context,self.ACTION_ID,self.ROLE)

    def _validate_dependency(self,record,reading):
        """Comparability source validation has no predecessor report dependency."""

    def _reading(self, context, action_input, originals):
        self._check()
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if (context.run_id != self.organizations.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID
                or self._views.source_mode != ('fixture' if context.execution_mode == 'offline_fixture' else 'formal')):
            raise TaskConflict('Forecast source validation substitutes original run, action or source mode')
        registration = self.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.role != self.ROLE or registration.skill is None:
            raise TaskConflict('Forecast source validation requires original implemented QS contract and Skill')
        action_input = registration.contract.validate_input(action_input)
        if (action_input.scope != context.scope
                or self.REQUIRE_EMPTY_COMPARISON and action_input.comparability_result_ref is not None):
            raise TaskConflict('Forecast source validation changes original scope or consumes a future comparison')
        resolver = self._build_resolver(context,action_input)
        reading = ActionReadView(context,resolver,self.organizations,self.ACTION_ID,self.ROLE)
        self._compare(context,reading,originals,current_evidence_refs=set())
        self.VALIDATE_SOURCES(action_input,context=context,
            organization_id=reading.organization_id,sources=reading._reads)
        prepared = self.PREPARE_INPUT(context,action_input,reading)
        if prepared['kind'] != 'prepared' or reading.method_evidence():
            raise TaskConflict('Current original prediction/outcome sources no longer support this saved comparison input')
        reading.recheck()
        self._check()
        return context,action_input,reading,prepared['input']

    def validate_current(self, *, context, action_input, comparison_input, calculation_ref, reading):
        """Check current frozen source/input identity before the producer's method call."""
        if not isinstance(reading,ActionReadView) or reading._organizations is not self.organizations:
            raise TaskConflict('Forecast production substitutes original authorized reading')
        reading.check_method_context(context,self.ACTION_ID)
        current,_,fresh,data = self._reading(context,action_input,reading.evidence())
        target = ref_type('MethodResult').model_validate(calculation_ref)
        comparison_input = QSForecastComparisonInput.model_validate(comparison_input)
        grants = self.organizations.grants(current,self.ACTION_ID,self.ROLE)
        if (data != comparison_input or fresh.organization_id != reading.organization_id
                or type(target.version) is not str or target not in current.visible_refs
                or not any(target in grant.readable_refs for grant in grants)):
            raise TaskConflict('Forecast production changes original pair, amounts, comparison basis or target read authority')
        reading.recheck()
        self._check()

    def validate_source(self, record, context):
        """Match actual sources to the retained report input under the current token."""
        original = ActionContext.model_validate(record['context'])
        saved = record['prepared']
        projection = self.PROJECTION_MODEL.model_validate(saved['projection'])
        current,action_input,reading,data = self._reading(context,record['action_input'],saved['source_reading'])
        if (record['organization_id'] != reading.organization_id
                or any(getattr(original,name) != getattr(current,name) for name in
                    ('run_id','actor_id','function_ref','contract_ref','scope','business_time','execution_mode'))
                or saved['context_sha256'] != task_digest(record['context'])
                or saved['input_sha256'] != task_digest(record['action_input'])
                or saved['reading_sha256'] != task_digest(saved['source_reading'])
                or saved['source_mode'] != self._views.source_mode
                or saved['projection_sha256'] != task_digest(saved['projection'])
                or not self._matches_projection_input(projection,data)
                or projection.input_sha256 != task_digest(data.model_dump(mode='json'))
                or not self._matches_projection_identity(projection,action_input)
                or projection.status != 'ok' or projection.report is None
                or saved['method_execution']['input'] != data.model_dump(mode='json')):
            raise TaskConflict('Forecast publication changes original sources, pair, report input or context')
        author_ref = ref_type('Authorization').model_validate(saved['author_authority_ref'])
        grant = reading.resolve(author_ref)
        if (not isinstance(grant,Authorization) or author_ref != projection.author_authority_ref
                or author_ref not in current.authorization_refs
                or grant not in self.organizations.grants(current,self.ACTION_ID,self.ROLE)
                or projection.ref not in current.visible_refs or projection.ref not in grant.readable_refs):
            raise TaskConflict('Saved forecast comparison lost its original actual author or target read authority')
        for ref in grant.basis_refs:
            evidence = reading.resolve(ref)
            if (not isinstance(evidence,EvidenceRecord)
                    or self._views.source_mode == 'formal' and evidence.source_kind == 'synthetic'
                    or evidence.effective_window is not None and not evidence.effective_window.contains(current.business_time)):
                raise TaskConflict('Saved forecast comparison author lacks current actual source evidence')
        self._validate_dependency(record,reading)
        if reading.evidence() != saved['source_reading'] or reading.method_evidence():
            raise TaskConflict('Forecast source validation changes original cache or executes a registered method')
        reading.recheck()
        self._check()
        return True
