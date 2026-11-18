"""CONTRACTOR-A10 produces bounded requests without posting work, cash or debt."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known, TimeWindow
from src.actions.contracts import contractor_payment_objects as payment_objects
from src.actions.contracts.contractor_payment_objects import (
    ContractorPaymentContractView, ContractorSettlementRuleView,
    ContractorSettlementProcedureView,
    ContractorValuationBasisView, ContractorMeasurementApplicationView,
    ContractorPaymentCertificateView, ContractorRequestableComponentView,
    ContractorPaymentIssueView, ContractorWorkRecordView, ContractorMeasurementWorkRecordView,
    OwnerPaymentAccountView, OwnerPaymentSourceView, OwnerPaymentReservationView,
    OwnerPaymentObligationView, OwnerPaymentExecutionView, OwnerPaymentReceiptView,
    FundingPurposeView, FinanceProductProfileView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _known, _unsupported
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def request_measurement_and_cash(context, action_input, reading):
    now, org, scope = context.business_time, reading.organization_id, context.scope

    def keys(refs):
        unique_refs(refs)
        return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('contractor-payment-clock-alignment')

    def evidence(refs, *, at=None, historic=False):
        point = now if at is None else at
        clock(point)
        if point.offset > now.offset:
            _needs('received_original_payment_evidence_time')
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord) or row.ref != ref:
                _unsupported('contractor-payment-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                clock(row.effective_window.end)
                if row.effective_window.start.offset > now.offset:
                    _needs('received_original_payment_evidence', [ref])
                if (at is not None or not historic) and not row.effective_window.contains(point):
                    _needs('original_payment_evidence_valid_at_use', [ref])

    def read(ref, schema, historic=False, linked=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', ref)) != ref:
            _unsupported('contractor-payment-projection:' + ref.kind)
        if hasattr(row, 'scope') and not linked and not scope_covers(scope, row.scope):
            raise ValueError('Payment source widens original authorized scope')
        evidence(getattr(row, 'evidence_refs', []), historic=historic)
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset:
                _needs('received_original_payment_source', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            clock(row.effective_window.end)
            if not historic and not row.effective_window.contains(now):
                _needs('current_original_payment_source', [ref])
        return row

    def true(value):
        return isinstance(value, Known) and value.value is True

    def authorize(ref):
        grant = read(ref, Authorization, linked=True)
        function = read(context.function_ref, RoleAssignment, linked=True)
        if (ref not in context.authorization_refs or grant.actor_id != context.actor_id
                or grant.organization_id != org or grant.function_ref != context.function_ref
                or function.function_ref != context.function_ref
                or function.role != 'Contractor' or 'CONTRACTOR-A10' not in grant.action_ids
                or not any(scope_covers(s, scope) for s in grant.scopes)):
            raise ValueError('Payment request substitutes actor, organization or authority')
        clock(grant.validity.start); clock(grant.validity.end)
        if not grant.validity.contains(now):
            _needs('current_original_contractor_payment_authority', [ref])
        for basis_ref in (*grant.basis_refs, *function.basis_refs):
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref], at=now)
            else:
                basis = reading.resolve(basis_ref)
                if hasattr(basis, 'available_at'):
                    clock(basis.available_at)
                    if basis.available_at.offset > now.offset:
                        _needs('original_contractor_payment_authority_basis_available', [basis_ref])

    def cash(value, *, historic=False):
        evidence([value.basis_ref], historic=historic)
        if value.currency != contract.currency or decimal_fraction(value.value) < 0:
            raise ValueError('Payment amount changes original currency or is negative')
        return decimal_fraction(value.value)

    def amount(state, field):
        return cash(_known(state, field))

    def complete(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, **fields,
            'note': rule.note + ' Request only; measurement, certification, due debt and received cash remain separate. Upstream delay does not waive downstream debt. Core posts allocations and noncash offsets once.'}}

    def wait(code, refs):
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
            'trigger': 'dependency_change', 'object_refs': refs, 'earliest_time': None,
            'condition_code': code}}

    def execution(ref):
        row = read(ref, OwnerPaymentExecutionView, historic=True, linked=True)
        if row.organization_id != org and not (row.organization_id == contract.client_id and row.beneficiary_id == org):
            raise ValueError('Execution belongs to another payer or beneficiary')
        if cash(row.amount, historic=True) <= 0:
            raise ValueError('Payment execution requires a positive original amount')
        if row.account_ref is not None and row.organization_id == org:
            account = read(row.account_ref, OwnerPaymentAccountView, historic=True, linked=True)
            if account.organization_id != org:
                raise ValueError('Contractor execution uses another organization cash')
        if row.status in {'succeeded', 'failed', 'rejected'}:
            if row.receipt_ref is None:
                _needs('original_payment_execution_receipt', [ref])
            receipt = read(row.receipt_ref, OwnerPaymentReceiptView, historic=True, linked=True)
            if (receipt.execution_ref != row.ref or receipt.command_id != row.command_id
                    or receipt.business_key != row.business_key or receipt.amount != row.amount
                    or receipt.beneficiary_id != row.beneficiary_id or receipt.status != row.status):
                raise ValueError('Receipt changes original execution identity or result')
        return row

    def obligation(ref, debtor=None):
        row = read(ref, OwnerPaymentObligationView, linked=True)
        clock(row.as_of); clock(row.due_at)
        if (not scope_covers(scope, row.origin_scope) or org not in {row.debtor_id, row.payee_id}
                or debtor is not None and row.debtor_id != debtor):
            raise ValueError('Payment targets another original obligation or legal debtor')
        if row.as_of != now:
            _needs('current_original_payment_obligation', [ref])
        evidence(row.verification_evidence_refs)
        return row

    def components(row):
        keys(row.component_refs)
        due = paid = offset = Fraction(0)
        result = {}
        for ref in row.component_refs:
            component = read(ref, ContractorRequestableComponentView, linked=True)
            if (component.contract_ref != contract.ref or component.obligation_ref != row.ref
                    or component.debtor_id != row.debtor_id or component.payee_id != row.payee_id
                    or component.source_ref != row.source_ref or component.debt_ref != row.debt_ref
                    or component.as_of != now):
                raise ValueError('Settlement component substitutes original obligation, loan, parties or funding source')
            d = amount(component.actual_due, 'component_due')
            p = amount(component.actual_cash_paid, 'component_actual_cash_paid')
            o = amount(component.actual_offset, 'component_actual_noncash_offset')
            if p + o > d:
                raise ValueError('Cash and noncash settlement exceed original component due')
            due += d; paid += p; offset += o
            result[ref.key()] = (component, d - p - o)
        if (due != amount(row.actual_due, 'obligation_due')
                or paid != amount(row.actual_paid, 'obligation_actual_cash_paid')
                or offset != amount(row.actual_offset, 'obligation_actual_noncash_offset')):
            raise ValueError('Obligation totals differ from complete original settlement components')
        return result

    def measured_lines(draft):
        if draft.contract_ref != contract.ref or not draft.lines or not draft.basis_refs:
            raise ValueError('Measurement requires original contract, concrete work and evidence')
        evidence(draft.basis_refs)
        window = read(draft.measurement_window_ref, TimeWindow, historic=True)
        clock(window.start); clock(window.end)
        if window.end.offset > now.offset:
            raise ValueError('Measurement window includes future work')
        result = {}; physical = set(); quantities = {}
        for line in draft.lines:
            if not scope_covers(scope, line.scope_ref) or not line.work_record_refs:
                raise ValueError('Measurement line widens scope or omits actual work')
            basis = read(line.valuation_basis_ref, ContractorValuationBasisView)
            if (basis.contract_ref != contract.ref or not scope_covers(basis.scope, line.scope_ref)
                    or basis.ref.key() not in keys(procedure.valuation_basis_refs) or not true(basis.effective)):
                _needs('effective_original_contract_valuation_basis', [basis.ref])
            if line.quantity.unit != basis.quantity_unit or decimal_fraction(line.quantity.value) <= 0:
                raise ValueError('Measurement quantity must be positive in original valuation units')
            evidence([line.quantity.basis_ref]); total = Fraction(0)
            for ref in line.work_record_refs:
                keys(line.work_record_refs)
                work = read(ref, ContractorWorkRecordView, historic=True)
                if ref.key() in result or work.physical_work_key in physical:
                    raise ValueError('Measurement repeats an original work record or physical slice')
                if not scope_covers(line.scope_ref, work.scope):
                    raise ValueError('Measured work leaves original line scope or measurement window')
                if (not isinstance(work, ContractorMeasurementWorkRecordView) or work.occurred_at is None
                        or not work.occurrence_evidence_refs):
                    _needs('actual_original_measured_work_occurrence_and_evidence', [ref])
                clock(work.occurred_at)
                if work.occurred_at.offset > work.available_at.offset or not window.contains(work.occurred_at):
                    raise ValueError('Measured work occurs outside original window or after its record was available')
                keys(work.occurrence_evidence_refs)
                evidence(work.occurrence_evidence_refs, at=work.occurred_at)
                for evidence_ref in work.occurrence_evidence_refs:
                    occurrence = reading.resolve(evidence_ref)
                    if occurrence.basis_kind != 'observed' or (reading._resolver.source_mode == 'formal'
                            and occurrence.source_kind == 'synthetic'):
                        _needs('actual_observed_original_measured_work_occurrence', [ref, evidence_ref])
                gross, net = work.gross_quantity, work.net_quantity
                evidence([gross.basis_ref, net.basis_ref], at=work.occurred_at)
                g, n = decimal_fraction(gross.value), decimal_fraction(net.value)
                if gross.unit != basis.quantity_unit or net.unit != gross.unit or not 0 <= n <= g:
                    raise ValueError('Gross and net actual work units or amounts are inconsistent')
                if work.work_kind == 'rework':
                    if work.original_work_record_ref is None or n != 0:
                        raise ValueError('Rework cannot create net new measurement')
                    original = read(work.original_work_record_ref, ContractorWorkRecordView, historic=True)
                    if original.ref == work.ref or original.work_kind != 'new_work' or not scope_covers(line.scope_ref, original.scope):
                        raise ValueError('Rework changes original physical work provenance')
                elif work.original_work_record_ref is not None:
                    raise ValueError('New work substitutes a rework reference')
                physical.add(work.physical_work_key)
                result[ref.key()] = work; total += n
            if decimal_fraction(line.quantity.value) > total:
                raise ValueError('Measurement exceeds actual original net work')
            if len(line.work_record_refs) > 1 and decimal_fraction(line.quantity.value) != total:
                _needs('explicit_per_work_slice_partial_measurement_lines')
            for ref in line.work_record_refs:
                work = result[ref.key()]
                quantities[work.physical_work_key] = (line.quantity.unit,
                    decimal_fraction(line.quantity.value) if len(line.work_record_refs) == 1
                    else decimal_fraction(work.net_quantity.value))
        payment_objects.validate_contractor_measurement_work_events(result.values())
        return result, quantities

    try:
        contract = read(action_input.contract_ref, ContractorPaymentContractView, linked=True)
        rule = read(action_input.settlement_rule_ref, ContractorSettlementRuleView)
        if (contract.contractor_id != org or not scope_covers(contract.scope, scope)
                or contract.settlement_rule_ref != rule.ref or rule.contract_ref != contract.ref
                or rule.organization_id != org or rule.actor_id != context.actor_id
                or rule.function_ref != context.function_ref or rule.scope != scope):
            raise ValueError('Settlement request changes original contract, organization or invocation')
        authorize(rule.authority_ref)
        procedure = read(rule.procedure_ref, ContractorSettlementProcedureView)
        if (procedure.contract_ref != contract.ref or rule.choice not in procedure.permitted_choices
                or not true(procedure.permitted) or not procedure.recipient_ids):
            _needs('independent_original_settlement_procedure', [procedure.ref])
        evidence(rule.basis_refs)
        for refs in (action_input.work_record_refs, action_input.certificate_refs, action_input.obligation_refs,
                action_input.account_refs, action_input.execution_refs):
            keys(refs)

        if rule.choice == 'apply_measurement':
            if not true(contract.effective) or rule.measurement is None:
                _needs('effective_contract_and_original_measurement_draft')
            if not contract.measurement_history_complete or contract.as_of != now:
                _needs('complete_current_original_measurement_history')
            draft = rule.measurement
            if keys(draft.prior_application_refs) != keys(contract.measurement_application_refs):
                _needs('complete_original_prior_measurement_applications')
            current, quantities = measured_lines(draft)
            if set(current) != keys(action_input.work_record_refs):
                raise ValueError('Measurement does not use exactly the original supplied work')
            business = set(); allocations = {}; source_versions = {}
            for ref in draft.prior_application_refs:
                prior = read(ref, ContractorMeasurementApplicationView, historic=True)
                if prior.organization_id != org or prior.request.contract_ref != contract.ref or prior.business_key in business:
                    raise ValueError('Measurement history substitutes contractor or repeats business application')
                business.add(prior.business_key)
                if prior.business_key == rule.business_key:
                    if prior.request.model_dump(exclude={'prior_application_refs'}) != draft.model_dump(exclude={'prior_application_refs'}):
                        raise ValueError('Existing measurement business identity changes original request')
                    return wait('continue_original_measurement_application', [prior.ref])
                if prior.status not in {'withdrawn', 'rejected'}:
                    for line in prior.request.lines:
                        keys(line.work_record_refs)
                        evidence([line.quantity.basis_ref], historic=True)
                        q = decimal_fraction(line.quantity.value)
                        if q < 0:
                            raise ValueError('Original applied work quantity is negative')
                        works = [read(r, ContractorWorkRecordView, historic=True) for r in line.work_record_refs]
                        for work in works:
                            evidence([work.gross_quantity.basis_ref, work.net_quantity.basis_ref], historic=True)
                        if not works or len({w.physical_work_key for w in works}) != len(works):
                            raise ValueError('Original measurement omits or repeats physical work')
                        if any(w.net_quantity.unit != line.quantity.unit for w in works):
                            raise ValueError('Prior measurement changes original work units')
                        total = sum((decimal_fraction(w.net_quantity.value) for w in works), Fraction(0))
                        if q > total or len(works) > 1 and q != total:
                            _needs('original_per_work_slice_measurement_allocations', [prior.ref])
                        for work in works:
                            physical = work.physical_work_key
                            if physical in source_versions and source_versions[physical] != work.ref.key():
                                raise ValueError('Measurement history repeats a physical slice under another version')
                            source_versions[physical] = work.ref.key()
                            allocation = q if len(works) == 1 else decimal_fraction(work.net_quantity.value)
                            allocations[physical] = allocations.get(physical, Fraction(0)) + allocation
                            if allocations[physical] > decimal_fraction(work.net_quantity.value):
                                raise ValueError('Prior applications exceed original net work coverage')
            for work in current.values():
                physical = work.physical_work_key
                if physical in source_versions and source_versions[physical] != work.ref.key():
                    raise ValueError('Current measurement substitutes an already applied physical source version')
                if allocations.get(physical, Fraction(0)) + quantities[physical][1] > decimal_fraction(work.net_quantity.value):
                    raise ValueError('Current and prior applications exceed original net work coverage')
            return complete('apply_measurement', request=draft.model_dump(mode='python'))

        if rule.choice == 'seek_finance':
            draft = rule.financing
            if draft is None:
                _needs('original_contractor_financing_application_draft')
            if (draft.borrower_id != org or draft.scope_ref != scope
                    or draft.applicant_authority_ref != rule.authority_ref or draft.lender_id == org):
                raise ValueError('Financing draft changes borrower, scope or applicant authority')
            if cash(draft.requested) <= 0:
                raise ValueError('Financing request must be positive')
            purpose = read(draft.purpose_ref, FundingPurposeView, linked=True)
            if purpose.borrower_ref.id != org or purpose.scope_ref != scope:
                raise ValueError('Finance purpose belongs to another borrower or scope')
            evidence(draft.disclosure_refs)
            keys(draft.product_candidates); keys(draft.disclosure_refs)
            for ref in draft.product_candidates:
                product = read(ref, FinanceProductProfileView, linked=True)
                if product.lender_id != draft.lender_id:
                    raise ValueError('Finance candidate belongs to another lender')
            return complete('seek_finance', application=draft.model_dump(mode='python'))

        if not contract.payment_history_complete or contract.as_of != now:
            _needs('complete_current_original_payment_history')
        contract_executions = keys(contract.execution_refs)
        if (not contract_executions <= keys(action_input.execution_refs)
                or keys(action_input.obligation_refs) != keys(contract.obligation_refs)
                or keys(action_input.certificate_refs) != keys(contract.certificate_refs)):
            _needs('complete_original_contract_payment_inputs')
        executions = [execution(ref) for ref in action_input.execution_refs]
        if (len({(r.organization_id, r.command_id) for r in executions}) != len(executions)
                or len({(r.organization_id, r.business_key) for r in executions}) != len(executions)):
            raise ValueError('Payment history repeats original command or business payment')
        by_execution = {row.ref.key(): row for row in executions}
        account_pending = {}
        for ref in action_input.account_refs:
            own_account = read(ref, OwnerPaymentAccountView, historic=True, linked=True)
            if own_account.organization_id != org:
                raise ValueError('Payment history uses another organization account')
            keys(own_account.pending_execution_refs)
            for pending_ref in own_account.pending_execution_refs:
                key = pending_ref.key()
                if key in account_pending and account_pending[key] != own_account.ref:
                    raise ValueError('Original pending payment is attributed to multiple accounts')
                account_pending[key] = own_account.ref
                prior = by_execution.get(key)
                if prior is not None and (prior.organization_id != org or prior.account_ref != own_account.ref):
                    raise ValueError('Account pending payment changes original legal payer or exact account')
        for key in keys(action_input.execution_refs) - contract_executions:
            # A shared own account can retain a command from another project.
            # It must be an explicit input and declared by that exact account;
            # the action never widens the contract's business obligations.
            if key not in account_pending:
                raise ValueError('Extra payment execution is absent from original own-account pending history')
        if rule.choice == 'reconcile':
            if not rule.execution_refs or not keys(rule.execution_refs) <= keys(action_input.execution_refs):
                raise ValueError('Reconciliation must query original existing executions')
            return complete('reconcile', execution_refs=rule.execution_refs)

        if rule.choice == 'dispute':
            if not rule.obligation_refs or not rule.issue_refs or not keys(rule.obligation_refs) <= keys(action_input.obligation_refs):
                raise ValueError('Dispute requires original existing obligations and concrete issues')
            for ref in rule.obligation_refs:
                obligation(ref)
            covered = set()
            for ref in rule.issue_refs:
                issue = read(ref, ContractorPaymentIssueView)
                if issue.contract_ref != contract.ref or issue.status == 'resolved':
                    raise ValueError('Dispute changes original contract or resolved issue')
                covered.update(keys(issue.obligation_refs))
            if not keys(rule.obligation_refs) <= covered:
                raise ValueError('Payment dispute omits original obligation-specific issues')
            return complete('dispute', obligation_refs=rule.obligation_refs, issue_refs=rule.issue_refs)

        existing = [row for row in executions if row.organization_id == org and row.business_key == rule.business_key]
        unresolved = [row.ref for row in executions if row.status in {'unknown', 'pending'}]
        if rule.choice == 'authorize_payment' and (existing or unresolved):
            return complete('reconcile', execution_refs=[row.ref for row in existing] or unresolved)

        if rule.choice == 'request_payment':
            if not rule.component_refs or not rule.basis_refs:
                _needs('original_requestable_components_and_evidence')
            keys(rule.basis_refs)
            selected = keys(rule.component_refs); available = {}
            for ref in action_input.obligation_refs:
                row = obligation(ref)
                if row.payee_id == org:
                    available.update(components(row))
            if not selected <= set(available):
                raise ValueError('Payment request changes original receivable components')
            for ref in rule.component_refs:
                component, remaining = available[ref.key()]
                if not true(component.requestable) or remaining <= 0 or component.settlement_mode != 'cash':
                    _needs('original_unpaid_cash_requestable_component', [ref])
                if component.certificate_ref is not None:
                    if component.certificate_ref.key() not in keys(action_input.certificate_refs):
                        raise ValueError('Payment request omits its original certificate')
                    certificate = read(component.certificate_ref, ContractorPaymentCertificateView)
                    if certificate.contract_ref != contract.ref or certificate.status != 'effective' or ref.key() not in keys(certificate.component_refs):
                        _needs('effective_original_payment_certificate', [certificate.ref])
            return complete('request_payment', basis_refs=rule.basis_refs, component_refs=rule.component_refs)

        if rule.choice != 'authorize_payment':
            _unsupported('contractor-settlement-choice')
        if rule.account_ref is None or not rule.lines or rule.account_ref.key() not in keys(action_input.account_refs):
            _needs('own_original_account_and_explicit_payment_allocation')
        account = read(rule.account_ref, OwnerPaymentAccountView, linked=True)
        if account.organization_id != org or account.currency != contract.currency:
            raise ValueError('Contractor cannot use Owner or other organization cash')
        if account.as_of != now or account.coverage != 'complete' or account.execution_coverage != 'complete':
            _needs('complete_current_actual_own_cash_ledger', [account.ref])
        if account.pending_execution_refs:
            if not keys(account.pending_execution_refs) <= keys(action_input.execution_refs):
                _needs('original_pending_own_account_executions', account.pending_execution_refs)
            for ref in account.pending_execution_refs:
                prior = by_execution[ref.key()]
                if prior.organization_id != org or prior.account_ref != account.ref:
                    raise ValueError('Pending own-account payment changes original payer or exact account')
            return complete('reconcile', execution_refs=account.pending_execution_refs)
        source = read(account.source_ref, OwnerPaymentSourceView, linked=True)
        if (source.organization_id != org or source.account_ref != account.ref or source.as_of != now
                or source.coverage != 'complete' or source.actual_cash != account.actual_cash
                or source.restricted_cash != account.restricted_cash):
            _needs('matching_current_actual_own_funding_source', [source.ref])
        held = Fraction(0)
        keys(account.reservation_refs)
        for ref in account.reservation_refs:
            reservation = read(ref, OwnerPaymentReservationView, linked=True)
            if reservation.account_ref != account.ref or reservation.organization_id != org or reservation.as_of != now:
                raise ValueError('Cash reservation changes original account, owner or snapshot')
            evidence([reservation.disposition_basis_ref])
            if reservation.status == 'held':
                held += amount(reservation.amount, 'held_cash_reservation')
        if held != amount(account.reserved_cash, 'account_reserved_cash'):
            raise ValueError('Own cash reservation total differs from original complete ledger')
        available = amount(account.actual_cash, 'actual_own_cash') - amount(account.restricted_cash, 'restricted_own_cash') - held
        if available < 0:
            raise ValueError('Restricted and reserved cash exceed actual own cash')
        keys([line.obligation_ref for line in rule.lines])
        if len({line.priority for line in rule.lines}) != len(rule.lines):
            raise ValueError('Cash allocation requires explicit independent priorities')
        total = Fraction(0); used = set(); output = []
        for line in rule.lines:
            if line.obligation_ref.key() not in keys(action_input.obligation_refs) or line.obligation_ref.key() not in keys(account.obligation_refs):
                raise ValueError('Payment line leaves original own account obligation coverage')
            row = obligation(line.obligation_ref, org)
            if row.status != 'effective' or not true(row.payable) or row.due_at.offset > now.offset:
                _needs('actual_due_payable_downstream_obligation', [row.ref])
            if row.source_ref != account.source_ref or line.payee_id != row.payee_id:
                raise ValueError('Payment changes original funding source or downstream payee')
            outstanding = components(row); allocated = Fraction(0); selected = []
            keys([entry.component_ref for entry in line.component_amounts])
            for entry in line.component_amounts:
                key = entry.component_ref.key()
                if key in used or key not in outstanding:
                    raise ValueError('Cash payment repeats or substitutes a settlement component')
                component, remaining = outstanding[key]; proposed = cash(entry.amount)
                if component.settlement_mode != 'cash' or not 0 < proposed <= remaining:
                    raise ValueError('Cash payment repeats noncash offset or exceeds unpaid component')
                if proposed < remaining and not rule.allow_partial:
                    _needs('explicit_original_partial_payment_authority', [rule.ref])
                allocated += proposed; used.add(key); selected.append(entry.component_ref)
            if allocated != cash(line.amount) or allocated <= 0:
                raise ValueError('Payment amount differs from explicit original component allocation')
            unpaid_cash = {key for key, (component, remaining) in outstanding.items()
                if component.settlement_mode == 'cash' and remaining > 0}
            if not rule.allow_partial and keys(selected) != unpaid_cash:
                _needs('explicit_original_partial_obligation_payment_authority', [rule.ref])
            total += allocated
            output.append({'obligation_ref': row.ref, 'payee_id': row.payee_id,
                'amount': line.amount, 'component_refs': selected})
        if total > available:
            _needs('explicit_revised_priority_or_partial_allocation_within_actual_own_cash', [rule.ref, account.ref])
        return complete('authorize_payment', account_ref=account.ref, lines=output)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
