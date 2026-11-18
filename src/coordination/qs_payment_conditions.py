"""Resume the same beneficiary's withdrawn payment application for fresh valuation."""
from copy import deepcopy
from dataclasses import dataclass

from pydantic import TypeAdapter

from src.actions.contracts.common import ActionContext, EvidenceRecord, ScopeRef, ref_type
from src.actions.contracts.qs_payment_objects import QSPaymentApplicationView, QSPaymentContractView, QSPaymentWorkView
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


_CODE = 'qs.payment.original_application_submitted'
_FIELDS = frozenset({'scope', 'application_ref', 'contract_ref', 'performed_work_refs', 'prior_certificate_refs',
    'payment_receipt_refs', 'measurement_result_refs', 'certification_authority_ref'})


@dataclass(frozen=True)
class QSPaymentConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict


def qs_original_payment_application_profile(read_current, validate_relation):
    """Rejudge actual resubmission while retaining contract/work/payment history.

    Native validation authenticates the original snapshot and actual beneficiary
    resubmission, complete current histories and independently authorized input.
    Ready does not certify a quantity, create a payment obligation or move cash.
    """
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('QS payment recovery requires actual current sources and native resubmission validation')

    def identities(refs):
        keys = {ref.key()[:2] for ref in refs}
        if len(keys) != len(refs):
            raise TaskConflict('QS payment recovery duplicates an original physical source')
        return keys

    def evaluate(check):
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'QS-A08' or source['role'] != 'QS' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 1 or old_refs[0].kind != 'PaymentApplication'):
            raise TaskConflict('QS payment recovery substitutes original application wait or recipient')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, QSPaymentConditionReading) or not isinstance(selected.context, ActionContext)
                or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.original_action_input, dict)
                or not isinstance(selected.action_input, dict)):
            raise TaskConflict('QS payment recovery requires typed current reading and original snapshot input')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        try:
            old_input, action_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
            if (set(old_input) != _FIELDS or set(action_input) != _FIELDS or task_digest(old_input) != source['input_sha256']
                    or context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'QS-A08'
                    or context.execution_mode == 'offline_fixture' or reading._resolver.source_mode != 'formal'
                    or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                    or old_input['scope'] != action_input['scope']):
                raise TaskConflict('QS payment recovery changes original snapshot, scope or current invocation')
            scope, now = TypeAdapter(ScopeRef).validate_python(action_input['scope']), context.business_time
            if context.scope != scope:
                raise TaskConflict('QS payment recovery changes original valuation coverage')
            reading.check_method_context(context, 'QS-A08')
            versions, proof_rows, proof_refs = [], [], []
            for raw, current in ((old_input, False), (action_input, True)):
                application_ref = ref_type('PaymentApplication').model_validate(raw['application_ref'])
                contract_ref = ref_type('Contract').model_validate(raw['contract_ref'])
                application, contract = reading.resolve(application_ref), reading.resolve(contract_ref)
                if (not isinstance(application, QSPaymentApplicationView) or not isinstance(contract, QSPaymentContractView)
                        or application.ref != application_ref or contract.ref != contract_ref or application.contract_ref != contract.ref
                        or application.scope != scope or contract.scope != scope
                        or application.applicant_id != contract.beneficiary_id or application.author_actor_id != application.applicant_id
                        or contract.valuation_organization_id != source['organization_id']):
                    raise TaskConflict('QS payment recovery changes original contract, beneficiary or valuation organization')
                versions.append((application, contract)); proof_rows.extend([(application, current), (contract, current)])
            original, old_contract = versions[0]; application, contract = versions[1]
            if (original.ref.key() != old_refs[0].key() or original.ref.key()[:2] != application.ref.key()[:2]
                    or old_contract.ref.key()[:2] != contract.ref.key()[:2] or original.status != 'withdrawn'
                    or any(getattr(original, field) != getattr(application, field) for field in ('applicant_id', 'period', 'basis', 'author_actor_id'))
                    or any(getattr(old_contract, field) != getattr(contract, field) for field in (
                        'party_ids', 'payer_id', 'beneficiary_id', 'currency', 'decimal_places', 'retention_fraction', 'retention_cap',
                        'valuation_actor_id', 'valuation_organization_id'))
                    or contract.valuation_actor_id != context.actor_id or contract.valuation_function_ref != context.function_ref
                    or contract.valuation_authority_ref not in context.authorization_refs):
                raise TaskConflict('QS payment recovery substitutes original application period, parties, price terms or acting authority')
            if application.status != 'submitted':
                return 'waiting'
            if any(row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                    or not row.effective_window.contains(now) for row in (application, contract)):
                return 'unavailable'
            if not identities(original.work_refs) <= identities(application.work_refs):
                raise TaskConflict('QS payment resubmission drops original declared actual work')
            # Superseded certificates need not stay in the active set. Native
            # validation receives both contracts and must authenticate every
            # original certificate's successor or retained active status.
            for field in ('receipt_refs', 'advance_credit_refs', 'deduction_refs', 'rate_refs'):
                if not identities(getattr(old_contract, field)) <= identities(getattr(contract, field)):
                    raise TaskConflict('QS payment recovery drops original certificate, receipt, credit, deduction or rate history')
            for field, kind, refs in (
                    ('performed_work_refs', 'WorkFact', application.work_refs),
                    ('prior_certificate_refs', 'Certificate', contract.active_certificate_refs),
                    ('payment_receipt_refs', 'PaymentReceipt', contract.receipt_refs)):
                values = [ref_type(kind).model_validate(raw) for raw in action_input[field]]
                if len(identities(values)) != len(values) or {ref.key() for ref in values} != {ref.key() for ref in refs}:
                    raise TaskConflict('QS payment successor lacks its complete current declared work/certificate/receipt set')
            results = [ref_type('MethodResult').model_validate(raw) for raw in action_input['measurement_result_refs']]
            identities(results)
            expected_results = [ref for ref in (application.valuation_result_ref, application.retention_result_ref, application.deduction_result_ref)
                if ref is not None]
            if {ref.key() for ref in results} != {ref.key() for ref in expected_results}:
                raise TaskConflict('QS payment successor replaces the original current measurement result selection')
            current_work = {ref.key()[:2]: ref for ref in application.work_refs}
            work_history = []
            for old_ref in original.work_refs:
                old, current = reading.resolve(old_ref), reading.resolve(current_work[old_ref.key()[:2]])
                if (not isinstance(old, QSPaymentWorkView) or not isinstance(current, QSPaymentWorkView)
                        or old.contract_ref != old_contract.ref or current.contract_ref != contract.ref
                        or any(getattr(old, field) != getattr(current, field) for field in (
                            'scope', 'work_key', 'period', 'quantity', 'author_actor_id', 'author_action_id', 'authored_at'))
                        or old.rate_ref.key()[:2] != current.rate_ref.key()[:2] or old.condition_ref.key()[:2] != current.condition_ref.key()[:2]):
                    raise TaskConflict('QS payment recovery rewrites original actual work quantity, period or author')
                work_history.append({'original': old.model_dump(mode='json'), 'current': current.model_dump(mode='json')})
                proof_rows.extend([(old, False), (current, False)]); proof_refs.append((current.quantity.basis_ref, False))
            for row in (original, application):
                grant, function = reading.resolve(row.author_authority_ref), reading.resolve(row.author_function_ref)
                if (not isinstance(grant, Authorization) or not isinstance(function, RoleAssignment)
                        or function.function_ref != row.author_function_ref or grant.actor_id != row.author_actor_id
                        or not row.author_action_id.startswith({'Owner': 'OWN-', 'Contractor': 'CONTRACTOR-', 'Supplier': 'SUPPLIER-',
                            'Architect': 'ARCHITECT-', 'Engineer': 'ENGINEER-', 'QS': 'QS-', 'Government': 'GOV-', 'Bank': 'BANK-'}[function.role])
                        or grant.function_ref != row.author_function_ref or row.author_action_id not in grant.action_ids
                        or not row.effective_window.contains(row.authored_at) or not grant.validity.contains(row.authored_at)
                        or row.authored_at.clock_ref != now.clock_ref or row.authored_at.offset > row.available_at.offset
                        or not any(scope_covers(granted, scope) for granted in grant.scopes)):
                    raise TaskConflict('QS payment recovery lacks the beneficiary original/current submission authority')
                proof_refs.extend((ref, False) for ref in [*grant.basis_refs, *function.basis_refs])
            evidence_refs = list(proof_refs)
            for row, current in proof_rows:
                evidence_refs.extend((ref, current) for ref in row.evidence_refs)
            observed = {}
            for ref, current in evidence_refs:
                evidence = reading.resolve(ref)
                if not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic' or evidence.basis_kind != 'observed':
                    raise TaskConflict('QS payment recovery requires actual observed native submission evidence')
                if current and evidence.effective_window is not None and not evidence.effective_window.contains(now):
                    return 'unavailable'
                observed[ref.key()] = evidence.model_dump(mode='json')
            if validate_relation(source_identity=deepcopy(source), original_action_input=old_input, action_input=action_input,
                    original_application=original.model_copy(deep=True), application=application.model_copy(deep=True),
                    original_contract=old_contract.model_copy(deep=True), contract=contract.model_copy(deep=True),
                    work_history=deepcopy(work_history), evidence=deepcopy(list(observed.values())),
                    context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('QS payment recovery lacks native actual resubmission and complete original/current history validation')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('QS-A08', _CODE, '1', frozenset({'dependency_change'}), evaluate)
