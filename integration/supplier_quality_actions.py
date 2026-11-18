"""Assemble Supplier A07 from actual batch quality and disposition sources."""
from dataclasses import dataclass, replace

from integration.supplier_execution_handoff import supplier_execution_handoff_schemas
from integration.supplier_quote_actions import PreparedSupplierQuote, SupplierQuoteActionAssembler
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_quality_objects import (
    SupplierQualityBatchView, SupplierQualityEvidenceView, SupplierQualityProfileView,
    SupplierQualityRequirementView, SupplierVisibleDefectView, supplier_quality_schemas,
)
from src.actions.runner import ActionRunner
from src.coordination.tasks import task_digest
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedSupplierQuality(PreparedSupplierQuote):
    """Original quality request; inspection and stock effects remain independently sourced."""


class SupplierQualityActionAssembler(SupplierQuoteActionAssembler):
    """Reuse explicit provider/model-host configuration with original A07 schemas.

    Host-selected requirements, observations, visible defects and policy keep
    their exact batch and physical lineage. The original processor checks
    completeness, independent inspection authority, disposition rights,
    remaining quantities, remedy dependencies and deviation permissions. No
    observation, passed inspection or usable inventory is manufactured from
    an A06 local request or a Supplier statement.
    """
    SOURCE_SCHEMAS = staticmethod(supplier_execution_handoff_schemas)

    def build(self, context, *, batch_ref, requirement_refs, evidence_refs,
            inspection_profile_ref, known_defect_refs):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A07':
            raise ValueError('Batch quality assembly requires its original A07 context')
        if self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture':
            raise ValueError('Fixture quality sources require explicit offline_fixture execution')
        registration = self.registry.get('SUPPLIER-A07')
        if not registration.implemented or registration.skill is None or registration.role != 'Supplier':
            raise ValueError('Batch quality assembly requires its original Supplier Skill and processor')
        resolver = self._views.build_resolver(context, registration.action_id, registration.role)
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        reading = ActionReadView(context, resolver, self.organizations, registration.action_id, registration.role,
            methods=runner.methods, method_refs=registration.skill.manifest.method_refs)
        selected = {name: [Reference.model_validate(ref) for ref in refs] for name, refs in (
            ('requirement_refs', requirement_refs), ('evidence_refs', evidence_refs), ('known_defect_refs', known_defect_refs))}
        for refs in selected.values():
            unique_refs(refs)
        action_input = registration.contract.validate_input({**selected,
            'batch_ref': Reference.model_validate(batch_ref), 'scope_ref': context.scope,
            'inspection_profile_ref': Reference.model_validate(inspection_profile_ref)})

        def read(ref, schema):
            row = reading.resolve(ref)
            if not isinstance(row, schema) or row.ref != ref:
                raise ValueError('Batch quality requires its exact original concrete source version')
            return row

        try:
            batch = read(action_input.batch_ref, SupplierQualityBatchView)
            profile = read(action_input.inspection_profile_ref, SupplierQualityProfileView)
            if (batch.organization_id != reading.organization_id or profile.organization_id != reading.organization_id
                    or not scope_covers(context.scope, batch.scope) or profile.scope != context.scope
                    or profile.batch_ref != batch.ref or profile.actor_id != context.actor_id
                    or profile.function_ref != context.function_ref
                    or profile.authority_ref not in context.authorization_refs):
                raise ValueError('Batch quality changes original Supplier, batch, scope or authorized profile actor')
            for ref in action_input.requirement_refs:
                row = read(ref, SupplierQualityRequirementView)
                if row.batch_ref != batch.ref or row.product_ref != batch.product_ref:
                    raise ValueError('Quality requirement names another original batch or product')
            for refs, schema in ((action_input.evidence_refs, SupplierQualityEvidenceView),
                    (action_input.known_defect_refs, SupplierVisibleDefectView)):
                for ref in refs:
                    row = read(ref, schema)
                    if row.batch_ref != batch.ref or row.physical_batch_key != batch.physical_batch_key:
                        raise ValueError('Quality observation or defect changes original physical batch lineage')
            for ref in walk_references(action_input):
                reading.resolve(ref)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Batch quality requires its actual current authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            reading.recheck()
            return PreparedSupplierQuality(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')), task_digest(context.model_dump(mode='json')),
                task_digest(reading.evidence()))
        finally:
            reading.recheck()

    def build_from_execution(self, context, *, execution_worker, execution_identity,
            execution_versions, basis_ref, validate_history, validate_current, **quality_refs):
        """Bind a current actual quality batch to selected saved A06 and recorded production."""
        from integration.supplier_execution_results import SupplierExecutionResultWorker

        if (not isinstance(execution_worker, SupplierExecutionResultWorker)
                or execution_worker.registry is not self.registry
                or execution_worker.store.run_id != self.organizations.run_id
                or not callable(validate_history) or not callable(validate_current)):
            raise ValueError('Quality execution source requires original worker/registry and explicit host checks')
        invocation = self.build(context, **quality_refs)
        handoff = execution_worker.prepare_quality_handoff(execution_identity, current_context=invocation.context,
            reading=invocation.reading, execution_versions=execution_versions, basis_ref=basis_ref,
            batch_ref=invocation.action_input.batch_ref, validate_history=validate_history, validate_current=validate_current)
        if handoff['kind'] != 'prepared':
            return handoff
        invocation.reading.recheck()
        return {**handoff, 'invocation': replace(invocation,
            reading_sha256=task_digest(invocation.reading.evidence()))}
