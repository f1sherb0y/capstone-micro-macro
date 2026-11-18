"""Assemble explicit OWN-A06 inputs without issuing payment commands."""
from dataclasses import dataclass
from typing import ClassVar

from integration.owner_observation_actions import OwnerObservationActionAssembler, PreparedOwnerObservation
from src.actions.contracts.owner_payment_objects import (
    OwnerPaymentAccountView, OwnerPaymentArrangementView, OwnerPaymentAuthorizationView,
    OwnerPaymentExecutionView, OwnerPaymentObligationView, OwnerPaymentScopeView, owner_payment_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class PreparedOwnerPayment(PreparedOwnerObservation):
    ACTION_ID: ClassVar[str] = 'OWN-A06'


class OwnerPaymentActionAssembler(OwnerObservationActionAssembler):
    """Preserve the exact accounts, obligations and original execution refs.

    Application code holds its source/authorization guard. The original A06
    processor decides draw/pay/repay/dispute/negotiate/reconcile; preparation
    creates no command, receipt, balance change or release of obligations.
    """
    ACTION_ID = 'OWN-A06'
    SOURCE_SCHEMAS = staticmethod(owner_payment_schemas)

    def build(self, context, *, scope_ref, account_refs, arrangement_refs, due_refs,
            evidence_refs, pending_execution_refs):
        return self._prepare_supplied_snapshot(context,
            input_values={'scope_ref': scope_ref, 'account_refs': account_refs, 'arrangement_refs': arrangement_refs,
                'due_refs': due_refs, 'evidence_refs': evidence_refs, 'pending_execution_refs': pending_execution_refs},
            prepared_type=PreparedOwnerPayment, validate_sources=self._validate_payment_sources)

    def build_from_qs_certificate(self, context, *, qs_decision, receipt_ref,
            validate_reception, **payment_inputs):
        """Relate actual issued certification to independently supplied obligations."""
        from integration.qs_certificate_owner_payment_handoff import validate_received_payment_certificate

        prepared = self.build(context, **payment_inputs)
        validate_received_payment_certificate(qs_decision, prepared=prepared,
            receipt_ref=receipt_ref, validate_reception=validate_reception)
        return prepared

    def build_from_bank_arrangement(self, context, *, bank_decision, receipt_ref,
            validate_reception, **payment_inputs):
        """Bind an actual received signed arrangement to original bank confirmation."""
        from integration.bank_arrangement_owner_payment_handoff import validate_received_payment_arrangement

        prepared = self.build(context, **payment_inputs)
        validate_received_payment_arrangement(bank_decision, prepared=prepared,
            receipt_ref=receipt_ref, validate_reception=validate_reception)
        return prepared

    def build_from_bank_execution(self, context, *, bank_reconciliation, reception_ref,
            validate_reception, **payment_inputs):
        """Link actual Bank receipt history to independently supplied Owner execution."""
        from integration.bank_execution_owner_payment_handoff import validate_received_bank_execution

        prepared = self.build(context, **payment_inputs)
        validate_received_bank_execution(bank_reconciliation, prepared=prepared,
            reception_ref=reception_ref, validate_reception=validate_reception)
        return prepared

    def build_from_qs_certificate_mapping(self, context, *, qs_decisions, receipt_refs,
            validate_mapping, **payment_inputs):
        """Bind an explicit complete certificate allocation group to original obligations."""
        from integration.qs_certificate_owner_payment_handoff import validate_received_payment_certificate_mapping

        prepared = self.build(context, **payment_inputs)
        validate_received_payment_certificate_mapping(qs_decisions, prepared=prepared,
            receipt_refs=receipt_refs, validate_mapping=validate_mapping)
        return prepared

    @staticmethod
    def _validate_payment_sources(action_input, *, context, reading):
        validate_owner_payment_sources(action_input, context=context,
            organization_id=reading.organization_id, sources=reading._reads)


def validate_owner_payment_sources(action_input, *, context, organization_id, sources):
    """Validate supplied ownership without evaluating cash or settlement."""
    subject = sources.get(action_input.scope_ref.ref.key())
    if (action_input.scope_ref != context.scope or not isinstance(subject, OwnerPaymentScopeView)
            or subject.organization_id != organization_id):
        raise TaskConflict('Owner payment changes its original own scope')
    for refs in (action_input.account_refs, action_input.arrangement_refs, action_input.due_refs,
            action_input.evidence_refs, action_input.pending_execution_refs):
        unique_refs(refs)
    for refs, schema, field in ((action_input.account_refs, OwnerPaymentAccountView, 'organization_id'),
            (action_input.arrangement_refs, OwnerPaymentArrangementView, 'borrower_id'),
            (action_input.due_refs, OwnerPaymentObligationView, 'debtor_id'),
            (action_input.pending_execution_refs, OwnerPaymentExecutionView, 'organization_id')):
        for ref in refs:
            source = sources.get(ref.key())
            if not isinstance(source, schema) or getattr(source, field) != organization_id:
                raise TaskConflict('Owner payment substitutes another organization account, arrangement, debt or execution')
    # The processor preserves missing authorization and unknown payment states;
    # never derive a new authorization or command from those missing facts.
    if subject.payment_authorization_ref is not None:
        decision = sources.get(subject.payment_authorization_ref.key())
        if decision is not None and (not isinstance(decision, OwnerPaymentAuthorizationView)
                or decision.organization_id != organization_id or decision.actor_id != context.actor_id
                or decision.function_ref.key() != context.function_ref.key() or decision.scope != context.scope):
            raise TaskConflict('Owner payment changes the original instruction recipient, function or scope')
