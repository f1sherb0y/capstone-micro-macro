"""ARCHITECT-A07 requests submission/review/release; host alone records those effects."""
import hashlib
import json
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.architect_submission_objects import (
    ArchitectSubmissionDeliverableView, ArchitectSubmissionProfileView, ArchitectPublicationAuthorityView,
    ArchitectTaskCompletionView, ArchitectSubmissionCheckView, ArchitectSubmissionRecipientView,
    ArchitectSubmissionReviewView, ArchitectSubmissionIssueView, ArchitectSubmissionReleaseBasisView,
    ArchitectSubmissionReleaseRecordView, ArchitectSubmissionSavedView, ArchitectPlanningWorkFactView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def submit_deliverable(context, action_input, reading):
    now, organization = context.business_time, reading.organization_id

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('architect-submission-clock-alignment')

    def evidence(refs, historical=False, observed=False):
        keys(refs)
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('architect-submission-evidence-schema')
            if observed and row.basis_kind != 'observed': _needs('verified_original_release_fact', [ref])
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not historical and not row.effective_window.contains(now): _needs('current_original_submission_evidence', [ref])

    def read(ref, schema, historical=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'architect-submission-projection:{ref.kind}')
        if hasattr(row, 'scope') and not scope_covers(action_input.scope, row.scope):
            raise ValueError('Submission input widens original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_original_submission_input', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historical and not row.effective_window.contains(now): _needs('currently_effective_submission_input', [ref])
        evidence(getattr(row, 'evidence_refs', []), historical)
        return row

    def authorize(ref, actor, function_ref, org, action, at):
        grant = read(ref, Authorization); function = read(function_ref, RoleAssignment)
        roles = {'ARCHITECT': 'Architect', 'ENGINEER': 'Engineer', 'QS': 'QS', 'SUPPLIER': 'Supplier',
                 'OWN': 'Owner', 'CONTRACTOR': 'Contractor', 'GOV': 'Government', 'BANK': 'Bank'}
        if (grant.actor_id != actor or grant.function_ref != function_ref or grant.organization_id != org
                or action not in grant.action_ids or function.role != roles.get(action.split('-')[0])
                or not any(scope_covers(scope, action_input.scope) for scope in grant.scopes)):
            raise ValueError('Submission input lacks original independent author/action/scope authority')
        clock(at); clock(grant.validity.start)
        if not grant.validity.contains(at): _needs('valid_original_submission_authority', [ref])
        evidence([*grant.basis_refs, *function.basis_refs], at != now)

    def canonical(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()

    try:
        if action_input.scope != context.scope: raise ValueError('Submission changes original authorized scope')
        deliverable = read(action_input.deliverable_ref, ArchitectSubmissionDeliverableView)
        if deliverable.author_organization_id != organization: raise ValueError('Submission borrows another organization authored deliverable')
        clock(deliverable.authored_at)
        if deliverable.authored_at.offset > min(now.offset, deliverable.available_at.offset): _needs('deliverable_authored_before_received')
        authorize(deliverable.author_authority_ref, deliverable.author_actor_id, deliverable.author_function_ref,
                  deliverable.author_organization_id, deliverable.author_action_id, deliverable.authored_at)
        profile = read(deliverable.submission_profile_ref, ArchitectSubmissionProfileView)
        if (profile.organization_id != organization or not same(profile.deliverable_ref, deliverable.ref)
                or profile.operation_id != context.operation_id): raise ValueError('Submission profile changes original organization, version or operation identity')
        authorize(profile.authority_ref, context.actor_id, context.function_ref, organization, 'ARCHITECT-A07', now)
        if deliverable.status != 'compiled': _needs('original_compiled_deliverable_before_submission')
        if action_input.requested_use not in deliverable.intended_uses: raise ValueError('Submission invents an undeclared intended use')
        publication = read(profile.publication_authority_ref, ArchitectPublicationAuthorityView)
        if (publication.organization_id != organization or publication.actor_id != context.actor_id
                or publication.function_ref != context.function_ref or not same(publication.deliverable_ref, deliverable.ref)
                or profile.choice not in publication.permitted_choices or action_input.requested_use not in publication.permitted_uses):
            raise ValueError('Submission/review/release exceeds original independent publication authority')
        clock(publication.granted_at)
        if publication.granted_at.offset > min(now.offset, publication.available_at.offset): _needs('received_original_publication_authority')
        authorize(publication.issuer_authority_ref, publication.issuer_actor_id, publication.issuer_function_ref,
                  publication.issuer_organization_id, publication.issuer_action_id, publication.granted_at)
        if not action_input.recipient_ids or len(set(action_input.recipient_ids)) != len(action_input.recipient_ids):
            _needs('distinct_original_legal_submission_recipients')
        if not set(action_input.recipient_ids) <= set(publication.recipient_ids): raise ValueError('Submission invents a recipient outside original authority')
        recipients = {}
        keys(profile.recipient_refs)
        for ref in profile.recipient_refs:
            row = read(ref, ArchitectSubmissionRecipientView)
            if row.recipient_id in recipients: raise ValueError('Submission profile duplicates a recipient identity')
            recipients[row.recipient_id] = row
        for identity in action_input.recipient_ids:
            recipient = recipients.get(identity)
            if recipient is None or action_input.requested_use not in recipient.permitted_uses: _needs('original_recipient_authorized_for_requested_use')
            authorize(recipient.authority_ref, recipient.actor_id, recipient.function_ref, recipient.organization_id, recipient.intake_action_id, now)
        completion = read(action_input.task_completion_ref, ArchitectTaskCompletionView, True)
        if (completion.organization_id != organization or not same(completion.task_ref, deliverable.task_ref)
                or not same(completion.deliverable_ref, deliverable.ref) or completion.content_sha256 != deliverable.content_sha256):
            raise ValueError('Task completion borrows another task, deliverable version or content')
        clock(completion.completed_at)
        if (completion.status != 'completed' or completion.investment_coverage != 'complete'
                or completion.completed_at.offset > min(now.offset, completion.available_at.offset)):
            _needs('verified_actual_task_completion_for_original_deliverable')
        required = decimal_fraction(completion.required_effort.value)
        if required <= 0: raise ValueError('Original deliverable compilation requires positive task investment')
        evidence([completion.required_effort.basis_ref], True)
        keys(completion.work_fact_refs); invested, slices = Fraction(), set()
        for ref in completion.work_fact_refs:
            fact = read(ref, ArchitectPlanningWorkFactView, True); clock(fact.window.start)
            if (not same(fact.task_ref, completion.task_ref) or fact.organization_id != organization or fact.investment_key in slices):
                raise ValueError('Task completion duplicates an investment or borrows another task/organization')
            if fact.status != 'committed' or fact.window.end.offset > completion.completed_at.offset:
                _needs('confirmed_original_work_finished_before_task_completion')
            if fact.effort.unit != completion.required_effort.unit: _unsupported('architect-submission-effort-unit-conversion')
            amount = decimal_fraction(fact.effort.value)
            if amount < 0 or decimal_fraction(fact.internal_cost.value) < 0: raise ValueError('Actual work/cost cannot be negative')
            evidence([fact.effort.basis_ref, fact.internal_cost.basis_ref], True); invested += amount; slices.add(fact.investment_key)
        if invested < required: _needs('actual_original_task_investment_before_submission')
        if keys(completion.check_refs) != keys(profile.completion_check_refs): _needs('all_original_required_compilation_checks')
        for ref in completion.check_refs:
            check = read(ref, ArchitectSubmissionCheckView, True); clock(check.executed_at)
            if (not same(check.task_ref, completion.task_ref) or not same(check.deliverable_ref, deliverable.ref)
                    or check.content_sha256 != deliverable.content_sha256 or check.executed_at.offset > completion.completed_at.offset):
                raise ValueError('Completion check changes original task/content/version or executed time')
            if check.status == 'unsupported': _unsupported('architect-submission-compilation-method')
            if check.status != 'ok' or not isinstance(check.passed, Known) or not check.passed.value: _needs('original_passed_compilation_check')
        if keys(action_input.dependency_refs) != keys(deliverable.dependency_refs): _needs('all_original_deliverable_dependency_versions')
        unresolved = {}
        for row in [deliverable] + [read(ref, ArchitectSubmissionDeliverableView, True) for ref in action_input.dependency_refs]:
            if row.issue_coverage != 'complete': _needs('complete_original_deliverable_unresolved_issues')
            if row.ref.key() != deliverable.ref.key():
                clock(row.authored_at)
                if row.authored_at.offset > min(now.offset, row.available_at.offset): _needs('dependency_authored_before_received')
                authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref, row.author_organization_id, row.author_action_id, row.authored_at)
            if action_input.requested_use in row.invalidated_uses:
                evidence(row.invalidation_evidence_refs)
                _needs('original_dependency_valid_for_requested_use', [row.ref])
            if profile.choice == 'release_for_use' and (row.status != 'compiled' or not row.effective_window.contains(now)
                    or action_input.requested_use not in row.valid_for_uses): _needs('original_valid_dependency_for_release_use', [row.ref])
            keys(row.unresolved_issue_refs)
            for ref in row.unresolved_issue_refs:
                issue = read(ref, ArchitectSubmissionIssueView)
                if not same(issue.deliverable_ref, row.ref) or issue.status == 'closed': raise ValueError('Open deliverable issue changes original version or claims closure')
                unresolved[ref.key()] = issue
        fields = {'deliverable_ref': deliverable.ref, 'requested_use': action_input.requested_use,
                  'recipient_ids': action_input.recipient_ids, 'unresolved_issue_refs': [row.ref for row in unresolved.values()]}
        if profile.choice == 'request_review':
            if action_input.review_requirement_ref is None: _needs('input.review_requirement_ref')
            requirement = read(action_input.review_requirement_ref, ArchitectSubmissionReviewView)
            if (not same(requirement.deliverable_ref, deliverable.ref) or requirement.requested_use != action_input.requested_use
                    or not set(action_input.recipient_ids) <= set(requirement.recipient_ids)
                    or any(recipients[identity].intake_action_id not in requirement.intake_action_ids for identity in action_input.recipient_ids)):
                raise ValueError('Review request changes original deliverable/use or independent recipient intake responsibility')
            if unresolved and not requirement.allow_unresolved_issues: _needs('original_review_mode_accepting_unresolved_items')
            fields['review_requirement_ref'] = requirement.ref
        if profile.choice == 'release_for_use':
            if not action_input.release_basis_refs: _needs('input.release_basis_refs')
            if len(set(profile.required_release_codes)) != len(profile.required_release_codes):
                raise ValueError('Publication profile repeats an original release condition code')
            if any(action_input.requested_use in row.blocking_uses for row in unresolved.values()): _needs('verified_closure_of_original_use_blocking_issues')
            keys(action_input.release_basis_refs); codes = set()
            for ref in action_input.release_basis_refs:
                basis = read(ref, ArchitectSubmissionReleaseBasisView)
                record = read(basis.original_record_ref, ArchitectSubmissionReleaseRecordView)
                if (not same(basis.deliverable_ref, deliverable.ref) or not same(record.deliverable_ref, deliverable.ref)
                        or basis.requested_use != action_input.requested_use or record.requested_use != action_input.requested_use
                        or record.code != basis.code or basis.code in codes or canonical(record.model_dump(mode='json')) != basis.content_sha256):
                    raise ValueError('Release basis changes original target/use/check identity/content')
                clock(record.verified_at)
                if record.verified_at.offset > min(now.offset, record.available_at.offset): _needs('release_verification_received_before_publication')
                authorize(record.author_authority_ref, record.author_actor_id, record.author_function_ref,
                          record.author_organization_id, record.author_action_id, record.verified_at)
                if record.record_kind == 'regulatory_permission' and not record.author_action_id.startswith('GOV-'):
                    raise ValueError('Architect release cannot invent a regulatory permission')
                if record.record_kind == 'owner_use' and not record.author_action_id.startswith('OWN-'):
                    raise ValueError('Architect release cannot invent an owner use decision')
                if not isinstance(record.satisfied, Known) or not record.satisfied.value: _needs('all_original_verified_release_conditions')
                evidence(record.evidence_refs, observed=True); codes.add(basis.code)
            if not profile.required_release_codes or codes != set(profile.required_release_codes): _needs('all_original_required_use_release_codes')
            fields['release_basis_refs'] = action_input.release_basis_refs
        payload = {'choice': profile.choice, 'scope': action_input.scope, 'note': profile.note, **fields}
        if profile.history_coverage != 'complete': _needs('complete_original_submission_command_history')
        keys(profile.submission_refs)
        payload_hash = canonical(json.loads(json.dumps(payload, default=lambda value: value.model_dump(mode='json'))))
        for ref in profile.submission_refs:
            saved = read(ref, ArchitectSubmissionSavedView, True)
            if saved.organization_id != organization or not same(saved.deliverable_ref, deliverable.ref): raise ValueError('Submission history borrows another author/version')
            if saved.command_id != profile.command_id and saved.business_key != profile.business_key: continue
            if saved.command_id != profile.command_id or saved.business_key != profile.business_key or saved.payload_sha256 != payload_hash:
                raise ValueError('Original submission command/business identity conflicts with changed payload')
            if saved.status != 'confirmed_uncommitted':
                reading.recheck(); return {'kind': 'deferred', 'reason_code': 'query_original_submission_receipt_before_retry',
                    'resume_condition': {'trigger': 'event', 'object_refs': [saved.ref], 'earliest_time': None,
                        'condition_code': 'original_command_receipt_resolved_without_duplicate_version_work_or_fee'}}
        reading.recheck(); return {'kind': 'completed', 'payload': payload}
    except ObservationGap as gap:
        reading.recheck(); return gap.result
