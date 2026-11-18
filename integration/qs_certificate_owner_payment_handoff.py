"""Bind original QS A08 certification to an actually received Owner A06 obligation."""
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction

from integration.qs_payment_results import SavedQSPayment
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.owner_payment_objects import (
    OwnerPaymentCertificateReceiptView, OwnerPaymentComponentView, OwnerPaymentObligationView,
)
from src.actions.contracts.qs_payment_objects import (
    QSPaymentCertificationView, QSPaymentContractView, QSPaymentCorrectionView, QSPaymentResultView,
)
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.registry import scope_covers


def read_received_payment_certificate(prepared, *, source_task_sha256, receipt_ref,
        read_qs_payment, validate_reception, receipt_sha256=None):
    """Select the original QS decision through the application's authorized reader."""
    if not callable(read_qs_payment) or not callable(validate_reception):
        raise TaskConflict('Payment certificate requires original QS journal reader and receiver validator')
    try:
        saved = read_qs_payment(context=prepared.context.model_copy(deep=True),
            source_task_sha256=source_task_sha256)
        if not isinstance(saved, SavedQSPayment) or saved.identity.key != source_task_sha256:
            raise TaskConflict('Certificate reader substituted the explicitly selected original QS task')
        actual_sha256 = validate_received_payment_certificate(saved, prepared=prepared, receipt_ref=receipt_ref,
            validate_reception=validate_reception)
        if receipt_sha256 is not None and receipt_sha256 != actual_sha256:
            raise TaskConflict('Certificate receipt replaces the explicitly retained original reception')
        provenance = {'source_task_sha256': saved.identity.key, 'source_record_sha256': saved.record_sha256,
            'source_result_sha256': task_digest(saved.result.model_dump(mode='json')),
            'source_reading_sha256': saved.source_reading_sha256,
            'receipt_ref': Reference.model_validate(receipt_ref).model_dump(mode='json'),
            'execution_source_reading_sha256': prepared.reading_sha256}
        if receipt_sha256 is not None:
            provenance['receipt_sha256'] = actual_sha256
        return provenance
    finally:
        prepared.reading.recheck()
        if (task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256
                or task_digest(prepared.reading.evidence()) != prepared.reading_sha256):
            raise TaskConflict('QS certificate reader changed original Owner payment input or sources')


def _validate_certificate_source(saved, *, prepared, receipt_ref):
    """Validate original decision, actual issuance and reception before allocating debt."""
    context, reading = prepared.context, prepared.reading
    if (not isinstance(saved, SavedQSPayment) or prepared.ACTION_ID != 'OWN-A06'
            or saved.identity.action_id != 'QS-A08' or saved.identity.role != 'QS'
            or saved.identity.run_id != context.run_id or saved.context.run_id != context.run_id
            or saved.context.contract_ref.id != 'QS-A08' or saved.context.execution_mode != context.execution_mode
            or saved.result.kind != 'completed' or saved.result.payload.choice not in {'certify', 'correct_certificate'}
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
        raise TaskConflict('Payment certificate relation requires original QS certification and actual receiver validation')
    reading.check_method_context(context, 'OWN-A06')
    before = task_digest(reading.evidence())
    if before != prepared.reading_sha256:
        raise TaskConflict('Certificate reception changed original payment source snapshot')
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    if any(saved.audit.get(k) != v for k, v in {'run_id': context.run_id, 'action_id': 'QS-A08',
            'operation_id': saved.context.operation_id, 'input_sha256': saved.identity.input_sha256,
            'result_sha256': result_sha, 'result_kind': 'completed'}.items()):
        raise TaskConflict('Certificate relation lacks original successful QS audit')
    originals = {}
    for row in saved.source_reading:
        key = Reference.model_validate(row['ref']).key()
        if key in originals:
            raise TaskConflict('Certificate relation repeats an original QS source')
        originals[key] = row['projection']
    try:
        receipt = reading.resolve(Reference.model_validate(receipt_ref))
        if (not isinstance(receipt, OwnerPaymentCertificateReceiptView)
                or receipt.run_id != context.run_id or receipt.recipient_organization_id != reading.organization_id
                or receipt.author_organization_id != saved.identity.organization_id
                or receipt.source_task_sha256 != saved.identity.key or receipt.source_record_sha256 != saved.record_sha256
                or receipt.source_result_sha256 != result_sha or receipt.source_reading_sha256 != saved.source_reading_sha256
                or not scope_covers(context.scope, receipt.scope) or not receipt.effective_window.contains(context.business_time)):
            raise TaskConflict('Certificate reception substitutes original QS, recipient, decision or obligation')
        statement = saved.result.payload.statement
        certificate = receipt.certificate
        contract = QSPaymentContractView.model_validate(originals[saved.action_input.contract_ref.key()])
        calculation = QSPaymentResultView.model_validate(originals[statement.calculation_ref.key()])
        correction = saved.result.payload.choice == 'correct_certificate'
        basis_ref = saved.result.payload.correction_basis_ref if correction else saved.result.payload.certification_basis_ref
        basis_type = QSPaymentCorrectionView if correction else QSPaymentCertificationView
        basis = basis_type.model_validate(originals[basis_ref.key()])
        if (contract.payer_id != reading.organization_id or certificate.contract_ref != contract.ref
                or certificate.application_ref != saved.action_input.application_ref
                or statement.contract_ref != contract.ref or statement.source_application_ref != certificate.application_ref
                or statement.covered_scope != receipt.scope or certificate.scope != receipt.scope
                or certificate.status != 'active' or certificate.certificate_key != basis.certificate_key
                or certificate.certification_authority_ref != basis.authority_ref
                or certificate.author_actor_id != saved.context.actor_id
                or certificate.author_function_ref != saved.context.function_ref
                or certificate.author_action_id != 'QS-A08'
                or certificate.author_authority_ref not in saved.context.authorization_refs
                or certificate.calculation_ref != statement.calculation_ref
                or not certificate.effective_window.contains(context.business_time)
                or calculation.contract_ref != contract.ref or calculation.application_ref != certificate.application_ref
                or calculation.status != 'ok' or calculation.result_kind != 'valuation' or calculation.report is None
                or calculation.valuation_basis != statement.basis
                or basis.statement_sha256 != task_digest(statement.model_dump(mode='json'))
                or basis.contract_ref != contract.ref or basis.application_ref != certificate.application_ref
                or basis.actor_id != saved.context.actor_id or basis.function_ref != saved.context.function_ref
                or correction and (certificate.predecessor_ref != saved.result.payload.prior_certificate_ref
                    or basis.prior_certificate_ref != certificate.predecessor_ref)
                or not correction and certificate.predecessor_ref is not None):
            raise TaskConflict('Issued certificate changes original statement, independent authority, parties or correction lineage')
        report = calculation.report
        if (statement.assessed_amount != report.assessed_amount
                or statement.recognized_amount != report.recognized_amount
                or statement.disputed_amount != report.disputed_amount):
            raise TaskConflict('Certificate statement changes original assessed, recognized or disputed valuation')
        for amount, expected in [(certificate.assessed_contribution, report.assessed_period_delta),
                (certificate.net_contribution, report.net_period_delta),
                (certificate.retention_contribution, report.retention_period_delta)]:
            value = expected.value if hasattr(expected, 'state') and expected.state == 'known' else expected
            if hasattr(expected, 'state') and expected.state != 'known':
                raise TaskConflict('Certificate contribution requires original known valuation amounts')
            if amount.currency != value.currency or Decimal(amount.value) != Decimal(value.value):
                raise TaskConflict('Certificate contribution changes original assessed/net/retained valuation')
        points = [saved.context.business_time, certificate.authored_at, certificate.available_at, receipt.received_at,
            receipt.available_at, context.business_time]
        if (any(p.clock_ref != context.business_time.clock_ref for p in points)
                or any(a.offset > b.offset for a, b in zip(points, points[1:]))):
            raise TaskConflict('Certificate relation changes original certification/issuance/reception chronology')
        native = reading.resolve(receipt.native_evidence_ref)
        if (not isinstance(native, EvidenceRecord) or native.basis_kind != 'observed'
                or native.content_hash != receipt.native_record_sha256
                or (native.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')
                or native.effective_window is not None and not native.effective_window.contains(context.business_time)):
            raise TaskConflict('Payment obligation lacks original observed actual certificate evidence')
        return receipt, contract
    finally:
        reading.recheck()
        if (task_digest(reading.evidence()) != before
                or task_digest(context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Certificate reception changed original payment inputs or sources')


def _recheck_payment_input(prepared):
    prepared.reading.recheck()
    if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
            or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
            or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
        raise TaskConflict('Certificate mapping changed original payment inputs or sources')


def _check_obligation(receipt, contract, obligation, prepared, *, allocated=False):
    if (not isinstance(obligation, OwnerPaymentObligationView)
            or obligation.ref not in prepared.action_input.due_refs
            or obligation.debtor_id != contract.payer_id or obligation.payee_id != contract.beneficiary_id
            or obligation.kind != 'works'
            or (not scope_covers(obligation.origin_scope, receipt.scope) if allocated
                else obligation.origin_scope != receipt.scope)
            or obligation.as_of != prepared.context.business_time
            or receipt.native_evidence_ref not in obligation.verification_evidence_refs):
        raise TaskConflict('Certificate mapping substitutes original works obligation, parties or observed issuance')


def _check_component(component, obligation, prepared):
    if (not isinstance(component, OwnerPaymentComponentView) or component.obligation_ref != obligation.ref
            or component.ref not in obligation.component_refs
            or component.debtor_id != obligation.debtor_id or component.payee_id != obligation.payee_id
            or component.source_ref != obligation.source_ref or component.debt_ref != obligation.debt_ref
            or component.as_of != prepared.context.business_time):
        raise TaskConflict('Certificate mapping borrows another original settlement component')


def validate_received_payment_certificate(saved, *, prepared, receipt_ref, validate_reception):
    """Retain the original single-certificate/single-obligation reception protocol."""
    if not callable(validate_reception):
        raise TaskConflict('Certificate reception requires actual application validation')
    try:
        receipt, contract = _validate_certificate_source(saved, prepared=prepared, receipt_ref=receipt_ref)
        if receipt.allocations is not None or receipt.obligation_ref is None:
            raise TaskConflict('Allocated certificate receipts require the complete mapping protocol')
        obligation = prepared.reading.resolve(receipt.obligation_ref)
        _check_obligation(receipt, contract, obligation, prepared)
        contribution = receipt.certificate.net_contribution
        if (obligation.actual_due.state != 'known'
                or obligation.actual_due.value.currency != contribution.currency
                or Decimal(obligation.actual_due.value.value) != Decimal(contribution.value)
                or len({r.key() for r in receipt.component_refs}) != len(receipt.component_refs)
                or set(receipt.component_refs) != set(obligation.component_refs)):
            raise TaskConflict('Certificate relation changes full original obligation or contribution')
        for ref in receipt.component_refs:
            _check_component(prepared.reading.resolve(ref), obligation, prepared)
        if validate_reception(saved=deepcopy(saved), receipt=receipt.model_copy(deep=True),
                certificate=receipt.certificate.model_copy(deep=True), obligation=obligation.model_copy(deep=True),
                context=prepared.context.model_copy(deep=True)) is not True:
            raise TaskConflict('Receiver did not confirm actual issuance, full obligation/cash history and lawful mapping')
        return task_digest(receipt.model_dump(mode='json'))
    finally:
        _recheck_payment_input(prepared)


def _known_amount(state, currency):
    if state.state != 'known' or state.value.currency != currency:
        raise TaskConflict('Certificate mapping requires original known amounts in the same currency')
    return Fraction(Decimal(state.value.value))


def validate_received_payment_certificate_mapping(saved_decisions, *, prepared, receipt_refs, validate_mapping):
    """Check complete signed contributions across split or merged original obligations.

    Each source certificate and every touched settlement component is accounted
    for exactly. The application validates the complete native relation, including
    correction history and contributions excluded from this selected group.
    This protocol does not infer contributions from a remaining cash balance.
    """
    if (not callable(validate_mapping) or not saved_decisions or len(saved_decisions) != len(receipt_refs)
            or len({r.key() for r in map(Reference.model_validate, receipt_refs)}) != len(receipt_refs)):
        raise TaskConflict('Certificate mapping requires unique complete receipts and actual application validation')
    try:
        receipts, obligations, components, totals = [], {}, {}, {}
        tasks, certificates = set(), set()
        for saved, ref in zip(saved_decisions, receipt_refs):
            receipt, contract = _validate_certificate_source(saved, prepared=prepared, receipt_ref=ref)
            certificate = receipt.certificate
            certificate_key = (certificate.contract_ref.key(), certificate.certificate_key)
            if (saved.identity.key in tasks or certificate_key in certificates
                    or receipt.obligation_ref is not None or not receipt.allocations
                    or len({r.key() for r in receipt.component_refs}) != len(receipt.component_refs)):
                raise TaskConflict('Certificate mapping duplicates a contribution or lacks explicit allocation rows')
            tasks.add(saved.identity.key)
            certificates.add(certificate_key)
            receipts.append(receipt)
            allocated, seen = Fraction(), set()
            for allocation in receipt.allocations:
                key = allocation.component_ref.key()
                if key in seen or allocation.amount.currency != certificate.net_contribution.currency:
                    raise TaskConflict('Certificate allocation duplicates a component or changes contribution currency')
                seen.add(key)
                obligation = prepared.reading.resolve(allocation.obligation_ref)
                _check_obligation(receipt, contract, obligation, prepared, allocated=True)
                component = prepared.reading.resolve(allocation.component_ref)
                _check_component(component, obligation, prepared)
                currency = allocation.amount.currency
                _known_amount(component.actual_due, currency)
                value = Fraction(Decimal(allocation.amount.value))
                allocated += value
                if key in totals and totals[key][0] != currency:
                    raise TaskConflict('Merged certificate contributions change original component currency')
                totals[key] = (currency, totals.get(key, (currency, Fraction()))[1] + value)
                obligations[obligation.ref.key()] = obligation
                components[key] = component
            if (seen != {r.key() for r in receipt.component_refs}
                    or allocated != Fraction(Decimal(certificate.net_contribution.value))):
                raise TaskConflict('Certificate allocation omits a component or changes the full signed net contribution')
        for key, component in components.items():
            currency, value = totals[key]
            if value != _known_amount(component.actual_due, currency):
                raise TaskConflict('Complete certificate contributions differ from original component due')
        for obligation in obligations.values():
            if any(ref.key() not in components for ref in obligation.component_refs):
                raise TaskConflict('Certificate mapping omits an original obligation component')
            currency = totals[obligation.component_refs[0].key()][0]
            rows = [components[ref.key()] for ref in obligation.component_refs]
            for original, field in ((obligation.actual_due, 'actual_due'),
                    (obligation.actual_paid, 'actual_cash_paid'), (obligation.actual_offset, 'actual_offset')):
                if sum((_known_amount(getattr(row, field), currency) for row in rows), Fraction()) != _known_amount(original, currency):
                    raise TaskConflict('Mapped obligation changes separate original due, cash paid or noncash offset totals')
        if validate_mapping(saved_decisions=deepcopy(saved_decisions),
                receipts=[receipt.model_copy(deep=True) for receipt in receipts],
                obligations=[value.model_copy(deep=True) for value in obligations.values()],
                components=[value.model_copy(deep=True) for value in components.values()],
                context=prepared.context.model_copy(deep=True)) is not True:
            raise TaskConflict('Receiver did not confirm complete native certificate allocation and correction/cash history')
        return [task_digest(receipt.model_dump(mode='json')) for receipt in receipts]
    finally:
        _recheck_payment_input(prepared)


def read_received_payment_certificate_mapping(prepared, *, certificates, read_qs_payment, validate_mapping):
    """Read each explicitly selected original QS record before checking the complete group."""
    if not callable(read_qs_payment) or not callable(validate_mapping) or not certificates:
        raise TaskConflict('Allocated certificates require original QS journal reader and mapping validator')
    try:
        saved_decisions, receipt_refs, provenance = [], [], []
        for selection in certificates:
            if not isinstance(selection, dict) or set(selection) not in (
                    {'source_task_sha256', 'receipt_ref'}, {'source_task_sha256', 'receipt_ref', 'receipt_sha256'}):
                raise TaskConflict('Certificate mapping requires explicit original task and receipt selections')
            saved = read_qs_payment(context=prepared.context.model_copy(deep=True),
                source_task_sha256=selection['source_task_sha256'])
            if not isinstance(saved, SavedQSPayment) or saved.identity.key != selection['source_task_sha256']:
                raise TaskConflict('Mapping reader substituted an explicitly selected original QS task')
            ref = Reference.model_validate(selection['receipt_ref'])
            saved_decisions.append(saved)
            receipt_refs.append(ref)
            provenance.append({'source_task_sha256': saved.identity.key, 'source_record_sha256': saved.record_sha256,
                'source_result_sha256': task_digest(saved.result.model_dump(mode='json')),
                'source_reading_sha256': saved.source_reading_sha256, 'receipt_ref': ref.model_dump(mode='json')})
        actual_sha256 = validate_received_payment_certificate_mapping(saved_decisions, prepared=prepared,
            receipt_refs=receipt_refs, validate_mapping=validate_mapping)
        for selected, actual, row in zip(certificates, actual_sha256, provenance):
            if selected.get('receipt_sha256') is not None:
                if selected['receipt_sha256'] != actual:
                    raise TaskConflict('Allocated certificate replaces an explicitly retained original receipt')
                row['receipt_sha256'] = actual
        return {'certificates': provenance, 'execution_source_reading_sha256': prepared.reading_sha256}
    finally:
        _recheck_payment_input(prepared)
