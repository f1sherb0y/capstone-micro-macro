"""Reconcile actual Owner command receipts with independent native ledger effects."""
from copy import deepcopy
from fractions import Fraction
from typing import Annotated, Callable, Literal

from pydantic import Field

from integration.owner_payment_submission import OwnerPaymentExecutionObservation, OwnerPaymentSubmission
from src.actions.contracts.common import EvidenceRecord, Money, Reference, StrictRecord, TextId, TimePoint
from src.actions.contracts.owner_financing_objects import FinancingDebtView
from src.actions.contracts.owner_payment_objects import (
    OwnerPaymentAccountView, OwnerPaymentComponentView, OwnerPaymentObligationView, OwnerPaymentSourceView,
)
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.models import Digest
from src.methods.pricing import exact_decimal


class OwnerNativeBalancePair(StrictRecord):
    before: dict
    after: dict


class OwnerNativeSettlementPosting(StrictRecord):
    effect_id: TextId
    source_task_sha256: Digest
    command_id: TextId
    business_key: TextId
    receipt_ref: Reference
    target_ref: Reference
    field: Literal['actual_cash', 'restricted_cash', 'reserved_cash', 'actual_paid',
        'actual_cash_paid', 'actual_due', 'actual_offset', 'outstanding_principal']
    delta: Money


class OwnerNativeSettlementObservation(StrictRecord):
    schema_version: Literal['owner-payment-native-settlement-observation.v1']
    observed_at: TimePoint
    coverage: Literal['complete']
    balances: Annotated[list[OwnerNativeBalancePair], Field(min_length=1)]
    postings: list[OwnerNativeSettlementPosting]
    native_payload: dict
    native_evidence: EvidenceRecord


_BALANCES = {
    'Account': (OwnerPaymentAccountView, ('actual_cash', 'restricted_cash', 'reserved_cash')),
    'FundingSource': (OwnerPaymentSourceView, ('actual_cash', 'restricted_cash')),
    'Obligation': (OwnerPaymentObligationView, ('actual_due', 'actual_paid', 'actual_offset')),
    'SettlementComponent': (OwnerPaymentComponentView, ('actual_due', 'actual_cash_paid', 'actual_offset')),
    'Debt': (FinancingDebtView, ('outstanding_principal',)),
}


def _known(state):
    if state.state != 'known' or Fraction(state.value.value) < 0:
        raise TaskConflict('Settlement requires independent known nonnegative ledger balances')
    return state.value.currency, Fraction(state.value.value)


class OwnerPaymentSettlementReconciler:
    """Read and verify native effects; never post a ledger or infer cash arrival.

    Caller holds the application's current source/authorization guard. The
    native reader supplies original before/current after snapshots and the
    complete intervening posting journal, including other authorized commands.
    validate_native_settlement verifies authenticity, completeness, actual
    beneficiary transfer and lawful access to that journal. Foreign recipients'
    private account projections need not be disclosed to the Owner.
    """
    VERSION = 'owner-payment-settlement-reconciler.v1'

    def __init__(self, *, submission: OwnerPaymentSubmission, read_native_settlement: Callable,
            validate_native_settlement: Callable):
        if (not isinstance(submission, OwnerPaymentSubmission) or not callable(read_native_settlement)
                or not callable(validate_native_settlement)):
            raise ValueError('Settlement requires original payment submission and independent native reader/validator')
        self.submission = submission
        self.read_native_settlement = read_native_settlement
        self.validate_native_settlement = validate_native_settlement
        self._original_components = (submission, read_native_settlement, validate_native_settlement)

    def _check(self):
        if any(current is not original for current, original in zip((self.submission,
                self.read_native_settlement, self.validate_native_settlement), self._original_components)):
            raise TaskConflict('Native settlement substituted its original submission or observation callbacks')
        self.submission._check_binding()

    def query(self, identity):
        """Return verified financial effects or None while command outcomes are unknown."""
        self._check()
        reception = self.submission.query_execution(identity)
        if reception is None:
            return None
        executions = OwnerPaymentExecutionObservation.model_validate(reception['observation'])
        if any(line.execution.status in {'unknown', 'pending'} for line in executions.lines):
            return None
        request, record, snapshot, _ = self.submission._original(identity)
        self.submission._submission._check_receipt_observation(request, reception['submission_receipt'])
        observed = self.read_native_settlement(request=deepcopy(request), record=deepcopy(record),
            snapshot=deepcopy(snapshot), reception=deepcopy(reception))
        if observed is None:
            return None
        observation = OwnerNativeSettlementObservation.model_validate(observed).model_copy(deep=True)
        original_time = TimePoint.model_validate(snapshot['context']['business_time'])
        if (observation.observed_at.clock_ref != original_time.clock_ref
                or observation.observed_at.offset < original_time.offset
                or any(line.receipt.available_at.clock_ref != observation.observed_at.clock_ref
                    or line.receipt.available_at.offset > observation.observed_at.offset for line in executions.lines)):
            raise TaskConflict('Native settlement changes original command/receipt observation interval')
        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in record['source_reading']}
        pairs, differences, currencies, balance_ids = {}, {}, {}, set()
        for pair in observation.balances:
            ref = Reference.model_validate(pair.before['ref'])
            if ref.kind not in _BALANCES or (ref.kind, ref.id) in balance_ids:
                raise TaskConflict('Native settlement repeats a balance or supplies an unsupported financial source')
            balance_ids.add((ref.kind, ref.id))
            schema, fields = _BALANCES[ref.kind]
            before, after = schema.model_validate(pair.before), schema.model_validate(pair.after)
            party = 'borrower_id' if ref.kind == 'Debt' else 'debtor_id' if ref.kind in {'Obligation', 'SettlementComponent'} else 'organization_id'
            if (after.ref.kind != ref.kind or after.ref.id != ref.id
                    or getattr(before, party) != request.identity.organization_id
                    or getattr(after, party) != request.identity.organization_id
                    or before.as_of != original_time or after.as_of != observation.observed_at
                    or observation.native_evidence.ref not in after.evidence_refs):
                raise TaskConflict('Native balance substitutes its legal owner, object or complete observation interval')
            for source, point in ((before, original_time), (after, observation.observed_at)):
                available = getattr(source, 'available_at', None)
                window = getattr(source, 'effective_window', None)
                if (getattr(source, 'coverage', 'complete') != 'complete'
                        or available is not None and (available.clock_ref != point.clock_ref or available.offset > point.offset)
                        or window is not None and not window.contains(point)):
                    raise TaskConflict('Native balance is incomplete, unavailable or ineffective at its observation time')
            original = originals.get(ref.key())
            if original is not None:
                keys = ('ref', 'borrower_id', 'lender_id', 'arrangement_ref', 'obligation_refs', 'as_of', 'coverage') if ref.kind == 'Debt' else original.keys()
                if any(pair.before.get(key) != original[key] for key in keys):
                    raise TaskConflict('Native settlement replaces original before balances or loan identity')
            changed = False
            for field in fields:
                currency, amount = _known(getattr(before, field))
                after_currency, after_amount = _known(getattr(after, field))
                if currency != after_currency:
                    raise TaskConflict('Native settlement changes original balance currency')
                key = (ref.key(), field)
                differences[key], currencies[key] = after_amount - amount, currency
                changed |= after_amount != amount
            if (changed or before != after) and before.ref == after.ref:
                raise TaskConflict('Native settlement overwrites an immutable original balance version')
            pairs[ref.key()] = (before, after)
        plan = reception['payment_plan']
        expected, selected = {}, {}
        required = set()
        for issued in executions.lines:
            execution, receipt = issued.execution, issued.receipt
            selected[execution.command_id] = issued
            line = plan['lines'][issued.line_index]
            account_key = Reference.model_validate(plan['account_ref']).key()
            if account_key not in pairs or account_key not in originals:
                raise TaskConflict('Settlement omits original selected account balance')
            account = pairs[account_key][0]
            source_key = account.source_ref.key()
            obligation_key = Reference.model_validate(line['obligation_ref']).key()
            required.update((account_key, source_key, obligation_key))
            values = [(account_key, 'actual_cash', -Fraction(execution.amount.value)),
                (source_key, 'actual_cash', -Fraction(execution.amount.value)),
                (obligation_key, 'actual_paid', Fraction(execution.amount.value))]
            principal = Fraction()
            for allocation in issued.component_amounts:
                key = allocation.component_ref.key()
                required.add(key)
                if key not in pairs or key not in originals:
                    raise TaskConflict('Settlement omits an original selected cash component')
                component = pairs[key][0]
                if (component.obligation_ref.key() != obligation_key or component.settlement_mode != 'cash'
                        or component.payee_id != execution.beneficiary_id
                        or (component.debt_ref.model_dump(mode='json') if component.debt_ref else None) != line['debt_ref']):
                    raise TaskConflict('Native settlement changes original cash component, payee or debt allocation')
                value = Fraction(allocation.amount.value)
                values.append((key, 'actual_cash_paid', value))
                if component.category == 'principal':
                    principal += value
            if line['debt_ref'] is not None:
                debt_key = Reference.model_validate(line['debt_ref']).key()
                required.add(debt_key)
                if principal:
                    values.append((debt_key, 'outstanding_principal', -principal))
            elif principal:
                raise TaskConflict('Principal settlement has no original loan identity')
            if execution.status == 'succeeded':
                for key, field, value in values:
                    expected[(execution.command_id, key, field)] = value
        if not required <= set(pairs) or not required <= set(originals):
            raise TaskConflict('Settlement omits original funding, obligation, component or loan sources')
        for key, (before, after) in pairs.items():
            for field in ('source_ref', 'account_ref', 'obligation_ref', 'debt_ref', 'terms_ref', 'arrangement_ref'):
                old, new = getattr(before, field, None), getattr(after, field, None)
                if (old is None) != (new is None) or old is not None and (
                        (old.kind, old.id) != (new.kind, new.id)
                        or old.key() in pairs and new != pairs[old.key()][1].ref):
                    raise TaskConflict('Native settlement changes original financial source or loan linkage')
            for field in ('currency', 'region_id', 'payee_id', 'lender_id', 'category', 'settlement_mode', 'kind', 'origin_scope'):
                if getattr(before, field, None) != getattr(after, field, None):
                    raise TaskConflict('Native settlement changes original financial parties, currency or component meaning')
            if before.ref.kind == 'Account':
                source_pair = pairs.get(before.source_ref.key())
                if source_pair is None:
                    raise TaskConflict('Native account omits its matching independently observed funding source')
                for account_row, source_row in zip((before, after), source_pair):
                    if (source_row.account_ref != account_row.ref
                            or any(_known(getattr(account_row, field)) != _known(getattr(source_row, field))
                                for field in ('actual_cash', 'restricted_cash'))):
                        raise TaskConflict('Native account and funding source disagree on actual cash or restrictions')
            if before.ref.kind == 'Obligation':
                if any(ref.key() not in pairs for ref in before.component_refs):
                    raise TaskConflict('Native settlement omits an unselected component of the original obligation')
                if after.component_refs != [pairs[ref.key()][1].ref for ref in before.component_refs]:
                    raise TaskConflict('Native obligation replaces or omits its original complete components')
                for index, obligation_row in enumerate((before, after)):
                    rows = [pairs[ref.key()][index] for ref in before.component_refs]
                    for total_field, part_field in (('actual_due', 'actual_due'),
                            ('actual_paid', 'actual_cash_paid'), ('actual_offset', 'actual_offset')):
                        currency, total = _known(getattr(obligation_row, total_field))
                        parts = [_known(getattr(component, part_field)) for component in rows]
                        if (any(component.obligation_ref != obligation_row.ref or component.debtor_id != obligation_row.debtor_id
                                or component.payee_id != obligation_row.payee_id for component in rows)
                                or any(part_currency != currency for part_currency, _ in parts)
                                or sum((value for _, value in parts), Fraction()) != total):
                            raise TaskConflict('Native obligation changes separate complete due, cash-paid or noncash-offset totals')
        actual, all_postings, effect_ids = {}, {}, set()
        selected_business = {line.execution.business_key for line in executions.lines}
        selected_receipts = {line.receipt.ref for line in executions.lines}
        for posting in observation.postings:
            key = (posting.target_ref.key(), posting.field)
            if posting.effect_id in effect_ids or key not in differences or posting.delta.currency != currencies[key]:
                raise TaskConflict('Native journal repeats an effect or changes target balance/currency')
            effect_ids.add(posting.effect_id)
            value = Fraction(posting.delta.value)
            all_postings[key] = all_postings.get(key, Fraction()) + value
            belongs = (posting.source_task_sha256 == request.identity.key or posting.command_id in selected
                or posting.business_key in selected_business or posting.receipt_ref in selected_receipts)
            if belongs:
                issued = selected.get(posting.command_id)
                if (issued is None or posting.source_task_sha256 != request.identity.key
                        or posting.business_key != issued.execution.business_key or posting.receipt_ref != issued.receipt.ref
                        or issued.execution.status != 'succeeded'):
                    raise TaskConflict('Native posting borrows another command/receipt or charges an unsuccessful payment')
                effect_key = (posting.command_id, *key)
                actual[effect_key] = actual.get(effect_key, Fraction()) + value
        if actual != expected or any(all_postings.get(key, Fraction()) != value for key, value in differences.items()):
            raise TaskConflict('Complete native postings disagree with original successful payment allocation or actual balance changes')
        native = {'schema_version': 'owner-payment-native-settlement.v1',
            'issued_reception_sha256': task_digest(reception), 'source_identity': request.identity.as_dict(),
            'source_record_sha256': record['record_sha256'], 'source_reading_sha256': record['source_reading_sha256'],
            'interval_start': original_time.model_dump(mode='json'), 'observed_at': observation.observed_at.model_dump(mode='json'),
            'balances': [pair.model_dump(mode='json') for pair in observation.balances],
            'postings': [posting.model_dump(mode='json') for posting in observation.postings], 'coverage': 'complete'}
        evidence = observation.native_evidence
        if (task_digest(observation.native_payload) != task_digest(native) or evidence.source_kind == 'synthetic'
                or evidence.basis_kind != 'observed' or evidence.content_hash != task_digest(native)
                or evidence.effective_window is not None and not evidence.effective_window.contains(observation.observed_at)
                or self.validate_native_settlement(request=deepcopy(request), record=deepcopy(record),
                    snapshot=deepcopy(snapshot), reception=deepcopy(reception),
                    observation=observation.model_dump(mode='json')) is not True):
            raise TaskConflict('Settlement lacks authentic complete native ledger effects, beneficiary transfer or lawful source access')
        self.submission._check_request(request)
        if self.submission.callbacks.validate_query(deepcopy(request)) is not True:
            raise TaskConflict('Owner settlement-read authority changed during native reconciliation')
        self.submission._submission._check_receipt_observation(request, reception['submission_receipt'])
        self._check()
        return {'schema_version': self.VERSION, 'source_identity': request.identity.as_dict(),
            'source_record_sha256': record['record_sha256'], 'source_result_sha256': request.output_sha256,
            'source_reading_sha256': record['source_reading_sha256'], 'issued_reception_sha256': task_digest(reception),
            'native_settlement_sha256': task_digest(native), 'observation': observation.model_dump(mode='json'),
            'issued_reception': deepcopy(reception),
            'effects': [{'command_id': command, 'target_ref': pairs[key][0].ref.model_dump(mode='json'),
                'field': field, 'delta': exact_decimal(value), 'currency': currencies[(key, field)]}
                for (command, key, field), value in expected.items()]}
