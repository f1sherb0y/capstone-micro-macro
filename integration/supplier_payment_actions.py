"""Assemble Supplier A10 from actual settlement rights and payment projections."""
from dataclasses import dataclass, replace

from integration.supplier_receiving_handoff import supplier_receiving_handoff_schemas
from integration.supplier_quote_actions import PreparedSupplierQuote, SupplierQuoteActionAssembler
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_payment_objects import (
    OwnerPaymentAccountView, OwnerPaymentExecutionView, OwnerPaymentObligationView,
    SupplierPaymentDeliveryView, SupplierPaymentOrderView,
    SupplierSettlementRuleView, supplier_payment_schemas,
)
from src.actions.runner import ActionRunner
from src.coordination.tasks import task_digest


@dataclass(frozen=True)
class PreparedSupplierPayment(PreparedSupplierQuote):
    """Original claim/authorization/query; no cash or certified entitlement is generated."""


class SupplierPaymentActionAssembler(SupplierQuoteActionAssembler):
    """Reuse explicit host configuration with the original A10 source schemas.

    Orders, obligations, contract-node delivery facts, accounts and execution
    history remain host-selected actual versions. The processor checks
    independent node authority, claim valuation, prior claims, offsets, source
    restrictions, reservations and actual receipts. Incoming customer cash and
    outgoing upstream payments remain distinct. Financing follows its original
    branch without requiring a payment ledger that the branch does not use.
    """
    ACTION_ID = 'SUPPLIER-A10'
    SOURCE_SCHEMAS = staticmethod(supplier_receiving_handoff_schemas)

    def build(self, context, *, order_refs, obligation_refs, delivery_evidence_refs,
            account_refs, execution_refs, settlement_rule_ref):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A10':
            raise ValueError('Supplier payment assembly requires its original A10 context')
        if self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture':
            raise ValueError('Fixture payment sources require explicit offline_fixture execution')
        registration = self.registry.get('SUPPLIER-A10')
        if not registration.implemented or registration.skill is None or registration.role != 'Supplier':
            raise ValueError('Supplier payment assembly requires its original Skill and processor')
        resolver = self._views.build_resolver(context, registration.action_id, registration.role)
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        reading = ActionReadView(context, resolver, self.organizations, registration.action_id, registration.role,
            methods=runner.methods, method_refs=registration.skill.manifest.method_refs)
        selected = {name: [Reference.model_validate(ref) for ref in refs] for name, refs in (
            ('order_refs', order_refs), ('obligation_refs', obligation_refs),
            ('delivery_evidence_refs', delivery_evidence_refs), ('account_refs', account_refs), ('execution_refs', execution_refs))}
        for refs in selected.values():
            unique_refs(refs)
        action_input = registration.contract.validate_input({**selected,
            'settlement_rule_ref': Reference.model_validate(settlement_rule_ref)})

        def read(ref, schema):
            row = reading.resolve(ref)
            if not isinstance(row, schema) or row.ref != ref:
                raise ValueError('Supplier payment requires its exact original concrete source version')
            return row

        try:
            rule = read(action_input.settlement_rule_ref, SupplierSettlementRuleView)
            if (rule.organization_id != reading.organization_id or rule.actor_id != context.actor_id
                    or rule.function_ref != context.function_ref or rule.scope != context.scope
                    or rule.authority_ref not in context.authorization_refs):
                raise ValueError('Supplier payment changes original organization, scope or settlement authority')
            for refs, schema in ((action_input.order_refs, SupplierPaymentOrderView),
                    (action_input.obligation_refs, OwnerPaymentObligationView),
                    (action_input.delivery_evidence_refs, SupplierPaymentDeliveryView),
                    (action_input.account_refs, OwnerPaymentAccountView),
                    (action_input.execution_refs, OwnerPaymentExecutionView)):
                for ref in refs:
                    read(ref, schema)
            for ref in walk_references(action_input):
                reading.resolve(ref)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Supplier payment requires its actual current authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            reading.recheck()
            return PreparedSupplierPayment(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')), task_digest(context.model_dump(mode='json')),
                task_digest(reading.evidence()))
        finally:
            reading.recheck()

    def build_from_receiving(self, context, *, receiving_worker, receiving_identity,
            receiving_execution_versions, basis_ref, handoff_delivery_refs, validate_history, validate_current, **payment_refs):
        """Relate an explicit delivery subset to actual original A09 receiving sources."""
        from integration.supplier_receiving_results import SupplierReceivingResultWorker

        if (not isinstance(receiving_worker, SupplierReceivingResultWorker) or receiving_worker.registry is not self.registry
                or receiving_worker.store.run_id != self.organizations.run_id
                or not callable(validate_history) or not callable(validate_current)):
            raise ValueError('Payment receiving source requires original worker/registry and explicit host checks')
        invocation = self.build(context, **payment_refs)
        selected = [Reference.model_validate(ref) for ref in handoff_delivery_refs]
        unique_refs(selected)
        if not set(selected) <= set(invocation.action_input.delivery_evidence_refs):
            raise ValueError('Receiving handoff selects delivery evidence absent from original payment input')
        handoff = receiving_worker.prepare_payment_handoff(receiving_identity, current_context=invocation.context,
            reading=invocation.reading, execution_versions=receiving_execution_versions, basis_ref=basis_ref,
            delivery_refs=selected, order_refs=invocation.action_input.order_refs,
            validate_history=validate_history, validate_current=validate_current)
        if handoff['kind'] != 'prepared':
            return handoff
        invocation.reading.recheck()
        return {**handoff, 'invocation': replace(invocation,
            reading_sha256=task_digest(invocation.reading.evidence()))}
