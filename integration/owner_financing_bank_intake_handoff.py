"""Original Owner apply decision to actually registered application received by Bank A02."""
from copy import deepcopy

from integration.bank_intake_actions import PreparedBankIntake
from integration.owner_financing_results import SavedOwnerFinancing
from src.actions.contracts.bank_objects import FinanceApplicationView, OwnerFinanceApplicationReceiptView
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.owner_financing_objects import FinancingProfileView
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def _recheck(prepared):
    # A02 initially reads its application dependencies only; caller freezes
    # these explicit reception reads before registration, including feedback.
    prepared.reading.recheck()
    if (task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
            or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
        raise TaskConflict('Owner application reception changed original Bank input or context')


def read_received_owner_application(prepared, *, source_task_sha256, receipt_ref,
        read_owner_financing, validate_reception, receipt_sha256=None):
    if not callable(read_owner_financing) or not callable(validate_reception):
        raise TaskConflict('Bank intake requires original Owner journal reader and actual application receiver validation')
    try:
        saved = read_owner_financing(context=prepared.context.model_copy(deep=True),
            source_task_sha256=source_task_sha256)
        if not isinstance(saved, SavedOwnerFinancing) or saved.identity.key != source_task_sha256:
            raise TaskConflict('Application reader substituted the explicitly selected original Owner task')
        actual_sha256 = validate_received_owner_application(saved, prepared=prepared, receipt_ref=receipt_ref,
            validate_reception=validate_reception)
        if receipt_sha256 is not None and receipt_sha256 != actual_sha256:
            raise TaskConflict('Application receipt replaces the explicitly retained original reception')
        provenance = {'source_task_sha256': saved.identity.key, 'source_record_sha256': saved.record_sha256,
            'source_result_sha256': task_digest(saved.result.model_dump(mode='json')),
            'source_reading_sha256': saved.source_reading_sha256,
            'receipt_ref': Reference.model_validate(receipt_ref).model_dump(mode='json')}
        if receipt_sha256 is not None:
            provenance['receipt_sha256'] = actual_sha256
        return provenance
    finally:
        _recheck(prepared)


def validate_received_owner_application(saved, *, prepared, receipt_ref, validate_reception):
    """Require actual registration, exact draft and independently received native evidence.

    The application validates original journal/disclosure rights, native
    registration/receipt, complete disclosure categories and current history.
    No local apply result becomes a registered application or credit approval.
    """
    context, reading = prepared.context, prepared.reading
    if (not isinstance(saved, SavedOwnerFinancing) or not isinstance(prepared, PreparedBankIntake)
            or context.contract_ref.id != 'BANK-A02'
            or saved.identity.action_id != 'OWN-A05' or saved.identity.role != 'Owner'
            or saved.identity.run_id != context.run_id or saved.context.run_id != context.run_id
            or saved.context.contract_ref.id != 'OWN-A05' or saved.context.execution_mode != context.execution_mode
            or saved.result.kind != 'completed' or saved.result.payload.choice != 'apply'
            or not callable(validate_reception)
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
        raise TaskConflict('Application reception requires original successful Owner apply and actual Bank source validation')
    reading.check_method_context(context, 'BANK-A02')
    _recheck(prepared)
    try:
        result_sha = task_digest(saved.result.model_dump(mode='json'))
        if any(saved.audit.get(key) != value for key, value in {
                'run_id': context.run_id, 'action_id': 'OWN-A05', 'operation_id': saved.context.operation_id,
                'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha,
                'result_kind': 'completed'}.items()):
            raise TaskConflict('Registered application lacks original successful Owner apply audit')
        originals = {}
        for row in saved.source_reading:
            key = Reference.model_validate(row['ref']).key()
            if key in originals:
                raise TaskConflict('Application relation repeats an original Owner source')
            originals[key] = row['projection']
        receipt = reading.resolve(Reference.model_validate(receipt_ref))
        if (not isinstance(receipt, OwnerFinanceApplicationReceiptView)
                or receipt.run_id != context.run_id or receipt.recipient_organization_id != reading.organization_id
                or receipt.author_organization_id != saved.identity.organization_id
                or receipt.source_task_sha256 != saved.identity.key or receipt.source_record_sha256 != saved.record_sha256
                or receipt.source_result_sha256 != result_sha or receipt.source_reading_sha256 != saved.source_reading_sha256
                or receipt.application_ref != prepared.action_input.application_ref
                or not scope_covers(context.scope, receipt.scope) or not receipt.effective_window.contains(context.business_time)):
            raise TaskConflict('Application receipt substitutes original Owner, Bank recipient, draft or registered application')
        application = reading.resolve(receipt.application_ref)
        draft = saved.result.payload.application
        draft_data = draft.model_dump(mode='json')
        profile = FinancingProfileView.model_validate(originals[saved.action_input.funding_profile_ref.key()])
        if (not isinstance(application, FinanceApplicationView)
                or receipt.application_sha256 != task_digest(application.model_dump(mode='json'))
                or profile.application is None or profile.application.model_dump(mode='json') != draft_data
                or application.borrower_id != saved.identity.organization_id
                or application.borrower_id != saved.action_input.borrower_id or application.lender_id != reading.organization_id
                or application.scope_ref != receipt.scope or not scope_covers(saved.context.scope, receipt.scope)
                or application.applicant_actor_id != saved.context.actor_id
                or application.applicant_function_ref != saved.context.function_ref
                or application.originating_action_id != 'OWN-A05'
                or application.applicant_authority_ref not in saved.context.authorization_refs
                or any(application.model_dump(mode='json')[field] != draft_data[field] for field in (
                    'borrower_id', 'lender_id', 'scope_ref', 'requested', 'purpose_ref',
                    'product_candidates', 'disclosure_refs', 'applicant_authority_ref'))):
            raise TaskConflict('Actual registration changes original complete draft, borrower, products, disclosure or author')
        expected = {'borrower_id': application.borrower_id, 'applicant_authority_ref': application.applicant_authority_ref,
            'requested': application.requested, 'purpose_ref': application.purpose_ref,
            'product_candidates': application.product_candidates, 'disclosure_refs': application.disclosure_refs}
        if any(getattr(prepared.action_input, field) != value for field, value in expected.items()):
            raise TaskConflict('Bank intake substitutes the actually received registered application fields')
        grant = reading.resolve(application.applicant_authority_ref)
        original_grant = Authorization.model_validate(originals[application.applicant_authority_ref.key()])
        assignment = reading.resolve(application.applicant_function_ref)
        original_assignment = RoleAssignment.model_validate(originals[application.applicant_function_ref.key()])
        if (not isinstance(grant, Authorization) or grant != original_grant
                or not isinstance(assignment, RoleAssignment) or assignment != original_assignment
                or assignment.role != 'Owner' or assignment.function_ref != saved.context.function_ref
                or grant.actor_id != saved.context.actor_id or grant.function_ref != saved.context.function_ref
                or grant.organization_id != application.borrower_id or 'OWN-A05' not in grant.action_ids
                or not grant.validity.contains(saved.context.business_time)
                or not grant.validity.contains(application.submitted_at)
                or not any(scope_covers(scope, application.scope_ref) for scope in grant.scopes)):
            raise TaskConflict('Registered application lacks original independent borrower submission authority')
        for ref in application.disclosure_refs:
            observed = reading.resolve(ref)
            if not isinstance(observed, EvidenceRecord) or originals.get(ref.key()) != observed.model_dump(mode='json'):
                raise TaskConflict('Registration substitutes original disclosed evidence content or version')
        points = [saved.context.business_time, application.submitted_at, receipt.received_at,
            receipt.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or any(left.offset > right.offset for left, right in zip(points, points[1:]))):
            raise TaskConflict('Application reception changes original decision, submission or reception chronology')
        for ref in [*grant.basis_refs, *assignment.basis_refs]:
            source = reading.resolve(ref)
            if originals.get(ref.key()) != source.model_dump(mode='json'):
                raise TaskConflict('Application author basis changes its original saved source content')
            if ref.kind == 'Evidence':
                if (not isinstance(source, EvidenceRecord) or source.effective_window is not None
                        and any(not source.effective_window.contains(point)
                            for point in (saved.context.business_time, application.submitted_at))):
                    raise TaskConflict('Application author evidence was not valid at original decision and submission')
        for ref in receipt.evidence_refs:
            evidence = reading.resolve(ref)
            if (not isinstance(evidence, EvidenceRecord)
                    or evidence.effective_window is not None and not evidence.effective_window.contains(receipt.received_at)):
                raise TaskConflict('Application receipt evidence was not applicable at actual reception')
        native = reading.resolve(receipt.native_evidence_ref)
        if (not isinstance(native, EvidenceRecord) or native.basis_kind != 'observed'
                or native.content_hash != receipt.native_record_sha256
                or (native.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')
                or native.effective_window is not None and not native.effective_window.contains(receipt.received_at)):
            raise TaskConflict('Application receipt lacks observed actual independent native registration')
        if validate_reception(saved=deepcopy(saved), receipt=receipt.model_copy(deep=True),
                application=application.model_copy(deep=True), context=context.model_copy(deep=True)) is not True:
            raise TaskConflict('Bank did not confirm actual registration, original disclosure mapping/history and lawful access')
        return task_digest(receipt.model_dump(mode='json'))
    finally:
        _recheck(prepared)
