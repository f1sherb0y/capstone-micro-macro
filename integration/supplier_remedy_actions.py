"""Assemble Supplier A11 from original contract, defect and disposition sources."""
from dataclasses import dataclass

from integration.supplier_quote_actions import PreparedSupplierQuote, SupplierQuoteActionAssembler
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.contracts.supplier_remedy_objects import (
    SupplierInstalledUseView, SupplierQualityBatchView, SupplierQualityEvidenceView, SupplierRemedyOrderView,
    SupplierRemedyProfileView, SupplierSupplyChangeRequestView,
    SupplierVisibleDefectView, supplier_remedy_schemas,
)
from src.actions.runner import ActionRunner
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedSupplierRemedy(PreparedSupplierQuote):
    """Original remedy proposal; no removal, replacement, liability or cash effect."""


class SupplierRemedyActionAssembler(SupplierQuoteActionAssembler):
    """Reuse explicit host setup while preserving A11's original source schemas.

    Original orders, batches, installed uses, change requests, visible defects
    and authorizations are selected by the host. Independent contract remedy
    procedure, ownership/site rights, physical removal and refund histories,
    quantities and remedy dependencies remain processor checks. Repair,
    replacement, change, refund, claim and decline retain their branches; no
    local receipt or dispute is converted into responsibility or disposition
    rights, replacement stock, physical removal or a refund transaction.
    """
    ACTION_ID = 'SUPPLIER-A11'
    SOURCE_SCHEMAS = staticmethod(supplier_remedy_schemas)

    def build(self, context, *, order_ref, batch_refs, installed_use_refs, change_refs,
            defect_refs, authority_refs, remedy_profile_ref):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A11':
            raise ValueError('Supply remedy assembly requires its original A11 context')
        if self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture':
            raise ValueError('Fixture remedy sources require explicit offline_fixture execution')
        registration = self.registry.get('SUPPLIER-A11')
        if not registration.implemented or registration.skill is None or registration.role != 'Supplier':
            raise ValueError('Supply remedy assembly requires its original Supplier Skill and processor')
        projection = self._views.assemble(context, registration.action_id, registration.role)
        resolver = ReferenceResolver(context.run_id, source_mode=self.source_mode, schemas=self.SOURCE_SCHEMAS())
        for original in projection.objects:
            resolver.register_projection(original.ref, original.value)
        resolver.freeze_read(context.read_token, [original.ref for original in projection.objects])
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        reading = ActionReadView(context, resolver, self.organizations, registration.action_id, registration.role,
            methods=runner.methods, method_refs=registration.skill.manifest.method_refs)
        selected = {name: [Reference.model_validate(ref) for ref in refs] for name, refs in (
            ('batch_refs', batch_refs), ('installed_use_refs', installed_use_refs), ('change_refs', change_refs),
            ('defect_refs', defect_refs), ('authority_refs', authority_refs))}
        for refs in selected.values():
            unique_refs(refs)
        action_input = registration.contract.validate_input({**selected,
            'order_ref': Reference.model_validate(order_ref), 'remedy_profile_ref': Reference.model_validate(remedy_profile_ref)})

        try:
            # Retain the actual supplied observations and their provenance in
            # the original assembly witness, without executing quality work.
            for original in projection.objects:
                reading.resolve(original.ref)
            for ref in walk_references(action_input):
                reading.resolve(ref)
            validate_supplier_remedy_sources(action_input, context=context,
                organization_id=reading.organization_id, sources=reading._reads)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Supply remedy requires its actual current authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            reading.recheck()
            return PreparedSupplierRemedy(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')), task_digest(context.model_dump(mode='json')),
                task_digest(reading.evidence()))
        finally:
            reading.recheck()


def validate_supplier_remedy_sources(action_input, *, context, organization_id, sources):
    """Keep supplied original batch/observation relationships in saved evidence.

    Missing observation dependencies and actual versus inferred evidence remain
    processor exits. An observation may describe installed stock at its actual
    site; the factory batch scope does not replace that original site scope.
    """
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Supply remedy lacks its exact original concrete source version')
        return row

    order = read(action_input.order_ref, SupplierRemedyOrderView)
    profile = read(action_input.remedy_profile_ref, SupplierRemedyProfileView)
    if (order.supplier_id != organization_id or not scope_covers(order.scope, context.scope)
            or profile.order_ref != order.ref or profile.organization_id != organization_id
            or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
            or profile.scope != context.scope or profile.authority_ref not in context.authorization_refs):
        raise TaskConflict('Supply remedy changes original order, Supplier, scope or profile authority')
    for refs, schema in ((action_input.installed_use_refs, SupplierInstalledUseView),
            (action_input.change_refs, SupplierSupplyChangeRequestView)):
        for ref in refs:
            if read(ref, schema).order_ref != order.ref:
                raise TaskConflict('Remedy installed use or request names another original order')
    batches = {ref.key(): read(ref, SupplierQualityBatchView) for ref in action_input.batch_refs}
    for ref in action_input.defect_refs:
        defect = read(ref, SupplierVisibleDefectView)
        batch = batches.get(defect.batch_ref.key())
        if batch is None or defect.physical_batch_key != batch.physical_batch_key:
            raise TaskConflict('Remedy defect changes its original supplied physical batch')
        observed = sources.get(defect.observation_ref.key())
        if observed is not None and (not isinstance(observed, SupplierQualityEvidenceView)
                or observed.ref != defect.observation_ref or observed.batch_ref != batch.ref
                or observed.physical_batch_key != defect.physical_batch_key
                or not scope_covers(observed.scope, defect.scope)):
            raise TaskConflict('Remedy defect changes its original observed physical batch or scope')
    for ref in action_input.authority_refs:
        read(ref, Authorization)
