"""Assemble Supplier A01 from original inquiries and own capability/capacity sources."""
from dataclasses import dataclass

from integration.supplier_quote_actions import PreparedSupplierQuote, SupplierQuoteActionAssembler
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_objects import (
    SupplierCapabilityView, SupplierCapacityView, SupplyInquiryView,
    SupplyMarketObservationView, SupplyScreeningProfileView, supplier_screening_schemas,
)
from src.actions.runner import ActionRunner
from src.coordination.tasks import task_digest


@dataclass(frozen=True)
class PreparedSupplierScreening(PreparedSupplierQuote):
    """Original screening invocation; responding creates no offer, order or reservation."""


class SupplierScreeningActionAssembler(SupplierQuoteActionAssembler):
    """Reuse explicit host setup with A01's original screening schemas.

    Inquiries, market observations, own capability, actual capacity and
    commercial policy are host-selected versions. The original processor
    checks product/function/method support, geography, complete shared
    commitments, partial scope, priorities and response windows. Empty inquiry
    selections retain market tracking or needs-information branches. Assembly
    creates no qualification, demand, productivity or formal intention receipt.
    """
    ACTION_ID = 'SUPPLIER-A01'
    SOURCE_SCHEMAS = staticmethod(supplier_screening_schemas)

    def build(self, context, *, inquiry_refs, market_refs, capability_ref,
            capacity_ref, screening_profile_ref):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A01':
            raise ValueError('Supplier screening assembly requires its original A01 context')
        if self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture':
            raise ValueError('Fixture screening sources require explicit offline_fixture execution')
        registration = self.registry.get('SUPPLIER-A01')
        if not registration.implemented or registration.skill is None or registration.role != 'Supplier':
            raise ValueError('Supplier screening assembly requires its original Skill and processor')
        resolver = self._views.build_resolver(context, registration.action_id, registration.role)
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        reading = ActionReadView(context, resolver, self.organizations, registration.action_id, registration.role,
            methods=runner.methods, method_refs=registration.skill.manifest.method_refs)
        selected = {name: [Reference.model_validate(ref) for ref in refs] for name, refs in (
            ('inquiry_refs', inquiry_refs), ('market_refs', market_refs))}
        for refs in selected.values():
            unique_refs(refs)
        action_input = registration.contract.validate_input({**selected,
            'capability_ref': Reference.model_validate(capability_ref), 'capacity_ref': Reference.model_validate(capacity_ref),
            'screening_profile_ref': Reference.model_validate(screening_profile_ref)})

        def read(ref, schema):
            row = reading.resolve(ref)
            if not isinstance(row, schema) or row.ref != ref:
                raise ValueError('Supplier screening requires its exact original concrete source version')
            return row

        try:
            private = [read(action_input.capability_ref, SupplierCapabilityView),
                read(action_input.capacity_ref, SupplierCapacityView),
                read(action_input.screening_profile_ref, SupplyScreeningProfileView)]
            # Retain the exact optional policy inputs in the prepared source
            # cache as well as the original runner's separately audited reads.
            limits = private[-1].outreach_limits
            if limits is not None:
                observation = reading.resolve(limits.observation_ref)
                reading.resolve(limits.minimum_market_demand.basis_ref)
                reading.resolve(observation.market_demand.basis_ref)
                for evidence_ref in observation.evidence_refs:
                    reading.resolve(evidence_ref)
            if (any(row.organization_id != reading.organization_id for row in private)
                    or context.scope.kind == 'organization' and context.scope.ref.id != reading.organization_id):
                raise ValueError('Supplier screening changes original private source organization or own scope')
            for ref in action_input.inquiry_refs:
                inquiry = read(ref, SupplyInquiryView)
                if (inquiry.recipient_id != context.actor_id
                        or inquiry.recipient_organization_id != reading.organization_id):
                    raise ValueError('Supplier screening changes the original inquiry recipient')
            for ref in action_input.market_refs:
                read(ref, SupplyMarketObservationView)
            for ref in walk_references(action_input):
                reading.resolve(ref)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Supplier screening requires its actual current authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            reading.recheck()
            return PreparedSupplierScreening(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')), task_digest(context.model_dump(mode='json')),
                task_digest(reading.evidence()))
        finally:
            reading.recheck()
