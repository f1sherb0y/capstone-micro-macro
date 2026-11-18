"""Independently reread actual A13 cost and adjustment sources without methods."""
from copy import deepcopy

from integration.module_host import module_factory_descriptor
from integration.qs_cost_calculation_validation import QSCostCalculationSourceValidator
from integration.qs_research_actions import validate_qs_research_sources
from integration.qs_research_normalization_calculations import _normalization_preparation_payload
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, ref_type, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.qs_research_objects import (
    QSResearchBasisView, QSResearchMethodProjection, QSResearchProfileView, qs_research_schemas,
)
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.roles.qs_research import prepare_qs_research_normalization_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.models import MethodOk
from src.methods.qs_research import RESEARCH_NORMALIZE_METHOD, ResearchNormalizationInput, ResearchNormalizationReport
from src.organization.models import Authorization


class QSResearchNormalizationSourceValidator(QSCostCalculationSourceValidator):
    """Use the original provider beneath local comparison publication wrappers.

    Caller holds the actual source guard. Reconstruct independent research
    authorization, current limits and physical cost history. A mandatory actual
    verifier checks FX and adjustment coverage, conventions and source lineage.
    Neither future report is an input; this gate executes no registered method
    or normalization formula. The publication store checks arithmetic proof.
    """
    VERSION = 'qs-research-normalization-source-validator.v1'
    ACTION_ID = 'QS-A13'
    ROLE = 'QS'
    SOURCE_SCHEMAS = staticmethod(qs_research_schemas)
    RESULT_KIND = 'normalization'
    METHOD_REF = RESEARCH_NORMALIZE_METHOD
    INPUT_MODEL = ResearchNormalizationInput
    REPORT_MODEL = ResearchNormalizationReport
    PREPARE_INPUT = staticmethod(prepare_qs_research_normalization_input)
    PREPARATION_PAYLOAD = staticmethod(_normalization_preparation_payload)

    def __init__(self, *, validate_normalization_basis, **components):
        if not callable(validate_normalization_basis):
            raise ValueError('Research normalization requires an explicit actual FX/adjustment coverage and convention verifier')
        super().__init__(**components)
        self.validate_normalization_basis = validate_normalization_basis
        self._basis_verifier = validate_normalization_basis
        self._declared.update(self._runtime_descriptors())

    def _runtime_descriptors(self):
        return {name: module_factory_descriptor(callback, 'QS.research_normalization.' + name)
            for name, callback in {
                'adjustment_basis_verifier': self.validate_normalization_basis,
                'current_runtime': type(self).validate_current,
                'compare_runtime': QSCostCalculationSourceValidator._compare,
                'preparation_runtime': self.PREPARE_INPUT,
                'preparation_payload': self.PREPARATION_PAYLOAD,
                'source_schemas': self.SOURCE_SCHEMAS,
                'local_dependency_sources': self._local_dependency_sources,
            }.items()}

    def _check(self):
        super()._check()
        if (self.validate_normalization_basis is not self._basis_verifier
                or any(self._declared.get(name) != value for name, value in self._runtime_descriptors().items())):
            raise TaskConflict('Research normalization actual verifier or original source runtime changed')

    def _reading(self, context, action_input, preparation, originals, *, saved_projection=None):
        self._check()
        context = ActionContext.model_validate(context).model_copy(deep=True)
        mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
        if (context.run_id != self.organizations.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or self._views.source_mode != mode):
            raise TaskConflict('Research normalization source validation changes original run, contract or source mode')
        registration = self.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.role != self.ROLE or registration.skill is None:
            raise TaskConflict('Research normalization source validation requires original implemented QS A13 and Skill')
        action_input = registration.contract.validate_input(action_input)
        fields = {'input', 'calculation_ref', 'task_ref', 'profile_ref', 'comparison_basis_ref',
            'plan_refs', 'normalization_basis_refs'}
        if self.RESULT_KIND == 'ranking':
            fields.add('normalization_result_ref')
        if (not isinstance(preparation, dict) or set(preparation) != fields
                or action_input.scope != context.scope or not isinstance(originals, list)):
            raise TaskConflict('Research normalization source validation requires closed original preparation and source cache')
        target = ref_type('MethodResult').model_validate(preparation['calculation_ref'])
        arithmetic = self.INPUT_MODEL.model_validate(preparation['input'])
        projection = self._views.assemble(context, self.ACTION_ID, self.ROLE)
        actual = {row.ref.key(): row.value for row in projection.objects}
        basis = actual.get(action_input.comparison_basis_ref.key())
        profile = (actual.get(basis.comparison_profile_ref.key())
            if isinstance(basis, QSResearchBasisView) and basis.comparison_profile_ref is not None else None)
        if (not isinstance(profile, QSResearchProfileView) or profile.task_ref != action_input.task_ref
                or profile.comparison_basis_ref != basis.ref or getattr(profile, self.RESULT_KIND + '_result_ref') != target
                or type(target.version) is not str):
            raise TaskConflict('Actual research normalization replaces original task, profile, basis or result target')
        actual = self._local_dependency_sources(context, action_input, preparation, originals, actual,
            profile=profile, saved_projection=saved_projection)
        targets = [ref for ref in (profile.normalization_result_ref, profile.ranking_result_ref) if ref is not None]
        if len({ref.key() for ref in targets}) != len(targets):
            raise TaskConflict('Research normalization and ranking must retain separate result identities')
        future_keys = {ref.key() for ref in targets if self.RESULT_KIND=='normalization' or ref==target}
        for row in projection.objects:
            if row.ref.key() in future_keys:
                if saved_projection is None or row.ref == target and row.value != saved_projection:
                    raise TaskConflict('Actual provider already supplies or replaces a future research comparison target')
        resolver = ReferenceResolver(context.run_id, source_mode=mode, schemas=self.SOURCE_SCHEMAS())
        refs = []
        for key, value in actual.items():
            if key not in future_keys:
                ref = Reference(kind=key[0], id=key[1], version=key[2])
                resolver.register_projection(ref, value)
                refs.append(ref)
        resolver.freeze_read(context.read_token, refs)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, self.ROLE)
        self._compare(context, reading, originals, current_evidence_refs=set())
        validate_qs_research_sources(action_input, context=context,
            organization_id=reading.organization_id, sources=reading._reads)
        candidates = reading.resolve(context.candidate_set_ref)
        if not isinstance(candidates, CandidateSet):
            raise TaskConflict('Research normalization lacks original actual candidate authority')
        candidates.check_context(context, registration.contract.choices)
        for candidate in candidates.candidates:
            reading.resolve(candidate.ref)
        original = self.PREPARE_INPUT(context, action_input, reading)
        if (original['kind'] != 'prepared' or original['input'] != arithmetic
                or self.PREPARATION_PAYLOAD(original) != preparation
                or reading.method_evidence() or reading.evidence() != originals):
            raise TaskConflict('Actual cost history no longer supports the same normalization preparation and cache')
        task = reading._reads[action_input.task_ref.key()]
        grant = reading.resolve(task.authority_ref)
        if (not isinstance(grant, Authorization) or task.authority_ref not in context.authorization_refs
                or grant not in self.organizations.grants(context, self.ACTION_ID, self.ROLE)
                or target not in context.visible_refs or target not in grant.readable_refs):
            raise TaskConflict('Research normalization lacks independent current task author and target read authority')
        for ref in [*grant.basis_refs, *(ref for ref in walk_references(arithmetic) if ref.kind == 'Evidence')]:
            evidence = reading.resolve(ref)
            if (not isinstance(evidence, EvidenceRecord)
                    or mode == 'formal' and evidence.source_kind == 'synthetic'
                    or evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)):
                raise TaskConflict('Research normalization lacks actual current numeric or authority evidence')
        if self.validate_normalization_basis(context=context.model_copy(deep=True),
                action_input=action_input.model_copy(deep=True), preparation=deepcopy(preparation),
                arithmetic=arithmetic.model_copy(deep=True), task=task.model_copy(deep=True),
                profile=profile.model_copy(deep=True),
                plans=[reading._reads[ref.key()].model_copy(deep=True) for ref in original['plan_refs']],
                normalizations=[reading._reads[ref.key()].model_copy(deep=True) for ref in original['normalization_basis_refs']],
                original_sources=deepcopy(reading._reads), reading=reading) is not True:
            raise TaskConflict('Research normalization lacks independent actual FX/adjustment coverage and convention verification')
        if (future_keys.intersection(reading._reads) or reading.method_evidence() or reading.evidence() != originals):
            raise TaskConflict('Research normalization basis verifier changed cache, consumed future reports or executed a method')
        reading.recheck()
        self._check()
        return context, action_input, reading, original

    def _local_dependency_sources(self, context, action_input, preparation, originals, actual, *, profile, saved_projection):
        """Normalization has no local comparison dependencies to add."""
        return actual

    def validate_current(self, *, context, action_input, preparation, arithmetic_input,
            calculation_ref, original_sources, reading):
        """Producer gate: independently reconstruct actual input before its single call."""
        if (not isinstance(reading, ActionReadView) or reading._organizations is not self.organizations
                or original_sources != reading.evidence()):
            raise TaskConflict('Research normalization production changes its actual authorized reading or source cache')
        reading.check_method_context(context, self.ACTION_ID)
        before = reading.method_evidence()
        _, _, fresh, original = self._reading(context, action_input, preparation, original_sources)
        target = ref_type('MethodResult').model_validate(calculation_ref)
        if (fresh.organization_id != reading.organization_id or original['calculation_ref'] != target
                or original['input'].model_dump(mode='json') != arithmetic_input.model_dump(mode='json')
                or reading.method_evidence() != before or reading.evidence() != original_sources):
            raise TaskConflict('Research normalization production changes original input, target, source cache or method evidence')
        reading.recheck()
        self._check()

    def validate_source(self, record, context):
        """Save/publication/read gate: match actual originals without recomputing amounts."""
        original_context = ActionContext.model_validate(record['context'])
        saved = record['prepared']
        projection = QSResearchMethodProjection.model_validate(saved['projection'])
        row = projection.comparison
        if row is None:
            raise TaskConflict('Research normalization source gate requires its original comparison projection')
        current, _, reading, original = self._reading(context, record['action_input'], saved['preparation'],
            saved['source_reading'], saved_projection=projection)
        execution = saved['method_execution']
        if not isinstance(execution, dict) or set(execution) != {'method_ref', 'registry_digest', 'input', 'result'}:
            raise TaskConflict('Research normalization source gate lacks complete original method proof')
        result = MethodOk[self.REPORT_MODEL].model_validate(execution['result'])
        data = original['input']
        task = reading._reads[original['task_ref'].key()]
        now = current.business_time
        if (record['organization_id'] != reading.organization_id
                or any(getattr(original_context, name) != getattr(current, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))
                or record['record_sha256'] != task_digest({k: v for k, v in record.items() if k != 'record_sha256'})
                or saved['context_sha256'] != task_digest(record['context'])
                or saved['input_sha256'] != task_digest(record['action_input'])
                or saved['preparation_sha256'] != task_digest(saved['preparation'])
                or saved['reading_sha256'] != task_digest(saved['source_reading'])
                or saved['projection_sha256'] != task_digest(saved['projection'])
                or saved[self.RESULT_KIND + '_input_sha256'] != task_digest(data.model_dump(mode='json'))
                or saved['source_mode'] != self._views.source_mode or saved['kind'] != 'prepared'
                or projection.model_dump(mode='json') != saved['projection'] or projection.ref != original['calculation_ref']
                or row.kind != self.RESULT_KIND or row.method_ref != self.METHOD_REF or row.status != 'ok'
                or row.scope != current.scope or row.task_ref != task.ref or row.profile_ref != original['profile_ref']
                or row.comparison_basis_ref != original['comparison_basis_ref']
                or row.plan_refs != original['plan_refs'] or row.normalization_basis_refs != original['normalization_basis_refs']
                or not self._matches_output(row, result.value)
                or row.available_at != now or row.calculated_at != now
                or row.effective_window.model_dump(mode='json') != {
                    'start': now.model_dump(mode='json'), 'end': now.model_dump(mode='json'), 'bounds': 'closed_closed'}
                or execution['method_ref'] != self.METHOD_REF.model_dump(mode='json')
                or result.method_ref != self.METHOD_REF or execution['input'] != data.model_dump(mode='json')
                or execution['registry_digest'] != saved['method_registry_sha256']
                or row.author_actor_id != current.actor_id or row.author_function_ref != current.function_ref
                or row.author_action_id != self.ACTION_ID or row.author_authority_ref != task.authority_ref
                or row.author_authority_ref.model_dump(mode='json') != saved['author_authority_ref']
                or row.evidence_refs != [EvidenceRecord.model_validate(item['projection']).ref
                    for item in saved['source_reading'] if item['ref']['kind'] == 'Evidence']
                or reading.evidence() != saved['source_reading'] or reading.method_evidence()):
            raise TaskConflict('Research normalization source gate replaces original report, inputs, evidence, time or author')
        reading.recheck()
        self._check()
        return True

    def _matches_output(self, row, report):
        return row.normalized_costs == report.normalized_costs and not row.ranked_groups
