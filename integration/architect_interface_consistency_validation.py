"""Reread exact original Architect interface sources without executing methods."""
from integration.architect_integration_actions import validate_architect_consistency_preparation_sources
from integration.qs_cost_calculation_validation import QSCostCalculationSourceValidator
from src.actions.contracts.architect_integration_objects import (
    ArchitectIntegrationConsistencyInput, ArchitectIntegrationConsistencyPreparation,
    ArchitectIntegrationConsistencyReport, ArchitectIntegrationConsistencyView,
    ArchitectIntegrationOptionView, ArchitectIntegrationProfileView, architect_integration_schemas,
)
from src.actions.contracts.common import ActionContext, EvidenceRecord
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.roles.architect_integration import prepare_architect_interface_consistency_input
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.architect_interfaces import INTERFACE_CONSISTENCY_METHOD
from src.methods.models import MethodOk
from src.organization.models import Authorization


class ArchitectInterfaceConsistencySourceValidator(QSCostCalculationSourceValidator):
    """Use the original actual provider beneath the report publication wrapper.

    Caller holds the source/authorization guard. Rebuild the original typed
    author objects, content digests, retained issues and independent delegation.
    Exact supplied versions do not prove technical compatibility or approval.
    Complete method proof and report arithmetic remain in the separate store.
    """
    VERSION = 'architect-interface-consistency-source-validator.v1'
    ACTION_ID = 'ARCHITECT-A06'
    ROLE = 'Architect'
    SOURCE_SCHEMAS = staticmethod(architect_integration_schemas)

    def _reading(self, context, action_input, preparation, originals, *, saved_projection=None):
        self._check()
        context = ActionContext.model_validate(context).model_copy(deep=True)
        mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
        if (context.run_id != self.organizations.run_id or context.contract_ref.kind != 'ActionContract'
                or context.contract_ref.id != self.ACTION_ID or self._views.source_mode != mode):
            raise TaskConflict('Consistency source validation substitutes original run, action or source mode')
        registration = self.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.role != self.ROLE or registration.skill is None:
            raise TaskConflict('Consistency source validation requires the original implemented Architect action and Skill')
        action_input = registration.contract.validate_input(action_input)
        preparation = ArchitectIntegrationConsistencyPreparation.model_validate(preparation).model_copy(deep=True)
        if action_input.scope != context.scope or not isinstance(originals, list):
            raise TaskConflict('Consistency source validation requires original scope and exact source cache records')
        projection = self._views.assemble(context, self.ACTION_ID, self.ROLE)
        objects = {row.ref.key(): row.value for row in projection.objects}
        option = objects.get(action_input.option_ref.key())
        profile = objects.get(option.integration_profile_ref.key()) if isinstance(option, ArchitectIntegrationOptionView) else None
        if not isinstance(profile, ArchitectIntegrationProfileView):
            raise TaskConflict('Consistency source validation lacks its original actual option/profile')
        future_keys = {ref.key() for ref in profile.consistency_result_refs}
        for row in projection.objects:
            if row.ref == preparation.calculation_ref and (saved_projection is None or row.value != saved_projection):
                raise TaskConflict('Consistency source provider already supplies or substitutes the original report target')
        resolver = ReferenceResolver(context.run_id, source_mode=mode, schemas=self.SOURCE_SCHEMAS())
        refs = []
        for row in projection.objects:
            if row.ref.key() not in future_keys:
                resolver.register_projection(row.ref, row.value)
                refs.append(row.ref)
        resolver.freeze_read(context.read_token, refs)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, self.ROLE)
        # Original author grants may be historical; role checks independently
        # retain author chronology and the validity of current received evidence.
        self._compare(context, reading, originals, current_evidence_refs=set())
        validate_architect_consistency_preparation_sources(action_input, preparation=preparation,
            context=context, organization_id=reading.organization_id, sources=reading._reads)
        original = prepare_architect_interface_consistency_input(context, action_input, reading, preparation)
        if (original['kind'] != 'prepared' or original['preparation'] != preparation
                or reading.method_evidence() or reading.evidence() != originals):
            raise TaskConflict('Current original sources no longer support the same author objects, issues and delegation cache')
        reading.recheck()
        self._check()
        return context, reading, original

    def validate_current(self, *, context, action_input, preparation, consistency_input, reading):
        """Independently match originals before the producer's one method call."""
        if not isinstance(reading, ActionReadView) or reading._organizations is not self.organizations:
            raise TaskConflict('Consistency production changes its original authorized reading')
        reading.check_method_context(context, self.ACTION_ID)
        before = reading.method_evidence()
        current, fresh, original = self._reading(context, action_input, preparation, reading.evidence())
        target = original['preparation'].calculation_ref
        grants = self.organizations.grants(current, self.ACTION_ID, self.ROLE)
        if (original['input'] != ArchitectIntegrationConsistencyInput.model_validate(consistency_input)
                or fresh.organization_id != reading.organization_id or type(target.version) is not str
                or target not in current.visible_refs or not any(target in grant.readable_refs for grant in grants)
                or reading.method_evidence() != before or fresh.method_evidence()):
            raise TaskConflict('Consistency production changes original input/target authority or executes a method in its source gate')
        reading.recheck()
        self._check()

    def validate_source(self, record, context):
        """Match actual originals at save/publication/read; preserve unknown reports."""
        original_context = ActionContext.model_validate(record['context'])
        saved = record['prepared']
        preparation = ArchitectIntegrationConsistencyPreparation.model_validate(saved['preparation'])
        projection = ArchitectIntegrationConsistencyView.model_validate(saved['projection'])
        current, reading, original = self._reading(context, record['action_input'], preparation,
            saved['source_reading'], saved_projection=projection)
        data = original['input']
        result = MethodOk[ArchitectIntegrationConsistencyReport].model_validate(saved['method_execution']['result'])
        report = result.value
        if (record['organization_id'] != reading.organization_id
                or any(getattr(original_context, name) != getattr(current, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))
                or saved['context_sha256'] != task_digest(record['context'])
                or saved['input_sha256'] != task_digest(record['action_input'])
                or saved['preparation_sha256'] != task_digest(saved['preparation'])
                or saved['reading_sha256'] != task_digest(saved['source_reading'])
                or saved['projection_sha256'] != task_digest(saved['projection'])
                or saved['consistency_input_sha256'] != task_digest(data.model_dump(mode='json'))
                or saved['source_mode'] != self._views.source_mode or saved['kind'] != 'prepared'
                or projection.model_dump(mode='json') != saved['projection']
                or projection.ref != preparation.calculation_ref or type(projection.ref.version) is not str
                or projection.option_ref != original['option'].ref or projection.method_ref != original['method'].ref
                or projection.method_ref != preparation.method_ref or projection.scope != current.scope
                or report.option_ref != data.option_ref or projection.status != report.status
                or report.technical_approval is not False or projection.input_digests != data.input_digests
                or report.input_digests != data.input_digests or projection.interface_refs != data.interface_refs
                or report.interface_refs != data.interface_refs or projection.retained_issue_refs != data.retained_issue_refs
                or report.retained_issue_refs != data.retained_issue_refs
                or projection.executed_at != current.business_time or projection.available_at != current.business_time
                or not projection.effective_window.contains(current.business_time)
                or saved['method_execution']['method_ref'] != INTERFACE_CONSISTENCY_METHOD.model_dump(mode='json')
                or result.method_ref != INTERFACE_CONSISTENCY_METHOD
                or saved['method_execution']['input'] != data.model_dump(mode='json')
                or projection.author_actor_id != current.actor_id or projection.author_function_ref != current.function_ref
                or projection.author_authority_ref.model_dump(mode='json') != saved['author_authority_ref']):
            raise TaskConflict('Consistency publication substitutes original source, authors, issues, context or method declaration')
        grant = reading.resolve(projection.author_authority_ref)
        if (not isinstance(grant, Authorization) or projection.author_authority_ref not in current.authorization_refs
                or grant not in self.organizations.grants(current, self.ACTION_ID, self.ROLE)
                or projection.ref not in current.visible_refs or projection.ref not in grant.readable_refs):
            raise TaskConflict('Consistency report lost its original actual author or current target read authority')
        for ref in grant.basis_refs:
            evidence = reading.resolve(ref)
            if (not isinstance(evidence, EvidenceRecord)
                    or self._views.source_mode == 'formal' and evidence.source_kind == 'synthetic'
                    or evidence.effective_window is not None and not evidence.effective_window.contains(current.business_time)):
                raise TaskConflict('Consistency author lacks current original source evidence')
        if reading.evidence() != saved['source_reading'] or reading.method_evidence():
            raise TaskConflict('Consistency source validation changes original cache or executes a registered method')
        reading.recheck()
        self._check()
        return True
