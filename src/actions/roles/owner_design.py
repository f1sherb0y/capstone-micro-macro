"""OWN-A07 original owner choices; professional/authority gates stay independent."""
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.owner_design_objects import (
    OwnerDesignBriefView, OwnerDesignProfileView, OwnerDesignOptionView, OwnerDesignComparisonView,
    OwnerDesignSubmissionView, OwnerDesignDeliverableView, OwnerDesignServiceTermsView,
    OwnerDesignUseView, OwnerDesignUseRuleView, OwnerDesignRequirementView, OwnerDesignDependencyView, OwnerDesignIssueView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def decide_design(context, action_input, reading):
    now, owner = context.business_time, reading.organization_id

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('owner-design-clock-alignment')

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('owner-design-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not row.effective_window.contains(now): _needs('current_original_owner_design_evidence', [ref])

    def read(ref, schema, scope=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'owner-design-projection:{ref.kind}')
        if hasattr(row, 'scope') and not scope_covers(row.scope, scope or context.scope):
            raise ValueError('Design decision input leaves original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at); clock(row.effective_window.start)
            if row.available_at.offset > now.offset or not row.effective_window.contains(now):
                _needs('received_current_original_design_decision_input', [ref])
        evidence(getattr(row, 'evidence_refs', [])); return row

    def authorize(ref, actor, function_ref, organization, action, roles, scope=None):
        grant = read(ref, Authorization); function = read(function_ref, RoleAssignment)
        if (grant.actor_id != actor or grant.function_ref != function_ref or grant.organization_id != organization
                or function.role not in roles or action not in grant.action_ids
                or not any(scope_covers(s, scope or context.scope) for s in grant.scopes)):
            raise ValueError('Design author/decision lacks independent original action, party or scope authority')
        clock(grant.validity.start)
        if not grant.validity.contains(now): _needs('current_original_design_authority', [ref])
        evidence([*grant.basis_refs, *function.basis_refs])

    def authored(row, roles, scope=None):
        assignment = read(row.author_function_ref, RoleAssignment)
        prefix = {'Owner': 'OWN-', 'Architect': 'ARCHITECT-', 'Engineer': 'ENGINEER-',
                  'QS': 'QS-', 'Government': 'GOV-', 'Bank': 'BANK-'}
        if assignment.role not in roles or not row.author_action_id.startswith(prefix.get(assignment.role, '!')):
            raise ValueError('Professional/design source action disagrees with the actual author role')
        authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
                  row.author_organization_id, row.author_action_id, roles, scope)
        return assignment.role

    def requirement(ref, *, purpose=None, scope=None, submission=None, deliverables=None, satisfy=False):
        row = read(ref, OwnerDesignRequirementView, scope)
        if not same(row.brief_ref, brief.ref) or (purpose is not None and row.purpose != purpose):
            raise ValueError('Design requirement changes original brief or purpose')
        if submission is not None and (row.submission_ref is None or not same(row.submission_ref, submission.ref)):
            raise ValueError('Design condition changes original submission version')
        if deliverables is not None and keys(row.evaluated_deliverable_refs) != keys(deliverables):
            _needs('independent_conditions_for_exact_deliverable_versions', [ref])
        roles = {'professional': {'Architect', 'Engineer', 'QS'}, 'regulatory': {'Government'},
                 'rights': {'Owner', 'Government'}, 'funding': {'Owner', 'Bank'},
                 'service_acceptance': {'Owner', 'Architect', 'Engineer', 'QS'},
                 'other': {'Owner', 'Architect', 'Engineer', 'QS', 'Government', 'Bank'}}
        authored(row, {'Owner'} if row.purpose in {'owner_need', 'change_request'} else roles[row.condition_kind], scope)
        if row.purpose in {'owner_need', 'change_request'} and row.author_organization_id != owner:
            raise ValueError('Need/change request cannot impersonate this owner')
        if not _known(row.permission, 'original_design_requirement_permission'):
            _needs('original_design_requirement_permission', [ref])
        if satisfy and not _known(row.satisfied, 'original_independent_design_condition'):
            _needs('original_independent_design_condition', [ref])
        return row

    def issue(ref, scope=None):
        row = read(ref, OwnerDesignIssueView, scope)
        if not same(row.brief_ref, brief.ref): raise ValueError('Design issue belongs to another brief version')
        authored(row, {'Owner', 'Architect', 'Engineer', 'QS', 'Government', 'Bank'}, scope)
        if row.status == 'resolved':
            if row.resolution_basis_ref is None: _needs('original_issue_resolution_basis', [ref])
            evidence([row.resolution_basis_ref])
        return row

    def acknowledge(refs, scope=None, blocking_use=None):
        if not keys(refs) <= keys(action_input.issue_refs) or not keys(refs) <= keys(profile.acknowledged_issue_refs):
            _needs('all_original_design_conflicts_and_issues_received_and_acknowledged', refs)
        for ref in refs:
            row = issue(ref, scope)
            if row.status == 'open' and blocking_use is not None and blocking_use in row.blocking_use_codes:
                _needs('original_blocking_design_issue_resolution', [ref])

    def completed(choice, **fields):
        reading.recheck(); return {'kind': 'completed', 'payload': {'choice': choice, 'note': profile.note, **fields}}

    try:
        brief = read(action_input.brief_ref, OwnerDesignBriefView)
        profile = read(brief.decision_profile_ref, OwnerDesignProfileView)
        if (brief.organization_id != owner or profile.organization_id != owner or not same(profile.brief_ref, brief.ref)
                or not same(profile.authority_ref, action_input.authority_ref)):
            raise ValueError('Design decision changes original owner, brief or authority')
        authorize(action_input.authority_ref, context.actor_id, context.function_ref, owner, 'OWN-A07', {'Owner'})
        if brief.status != 'current': _needs('current_unsuperseded_original_owner_brief')
        choice = profile.choice
        if choice == 'confirm_need':
            keys(brief.requirement_refs)
            for ref in brief.requirement_refs: requirement(ref, purpose='owner_need')
            return completed('confirm_need', brief_ref=brief.ref)
        scoped = profile.scope_choice
        if not scope_covers(context.scope, scoped.scope_ref): raise ValueError('Owner decision expands original authorized partial scope')
        if scoped.scope_ref.ref.key() != context.scope.ref.key() or not scoped.basis_refs:
            _needs('original_explicit_partial_scope_and_decision_basis')
        evidence(scoped.basis_refs); keys(scoped.condition_refs)
        for ref in scoped.condition_refs: requirement(ref, scope=scoped.scope_ref)
        if choice == 'choose_option':
            if profile.comparison_ref is None or profile.option_ref is None: _needs('original_option_choice_and_comparison')
            if profile.comparison_ref.key() not in keys(action_input.comparison_refs): raise ValueError('Owner chooses an undeclared comparison')
            comparison = read(profile.comparison_ref, OwnerDesignComparisonView)
            authored(comparison, {'Owner', 'Architect', 'Engineer', 'QS'})
            if not same(comparison.brief_ref, brief.ref) or profile.option_ref.key() not in keys(comparison.option_refs):
                raise ValueError('Owner option/comparison has another original brief or candidate version')
            if comparison.status == 'failed':
                reading.recheck(); return {'kind': 'technical_error', 'error': {'kind': 'unrecorded',
                    'correlation_id': context.operation_id, 'code': 'original_owner_option_comparison_failed'}, 'retryability': 'unknown'}
            if comparison.status != 'comparable': _needs('same_version_comparable_original_options')
            evidence(comparison.comparison_basis_refs)
            option = read(profile.option_ref, OwnerDesignOptionView)
            authored(option, {'Owner', 'Architect', 'Engineer', 'QS'})
            if not same(option.brief_ref, brief.ref) or option.status != 'current': _needs('current_original_chosen_option_version')
            evidence(option.evidence_refs_for_choice)
            acknowledge(list({ref.key(): ref for ref in [*comparison.issue_refs, *option.issue_refs]}.values()))
            desired, possible = brief.desired_delivery_at, option.earliest_supported_delivery_at
            if desired.state == possible.state == 'known':
                clock(desired.value); clock(possible.value)
                if possible.value.offset > desired.value.offset:
                    if not option.issue_refs or not profile.accepted_delivery_conflict:
                        _needs('explicit_owner_delivery_conflict_choice_without_changing_supply_commitments')
            return completed('choose_option', option_ref=option.ref, comparison_ref=comparison.ref)
        if choice == 'request_revision':
            if not profile.requirement_refs: _needs('explicit_original_owner_revision_requirements')
            keys(profile.requirement_refs); dependency_ids = set()
            for ref in profile.requirement_refs:
                change = requirement(ref, purpose='change_request', scope=scoped.scope_ref)
                if change.dependency_coverage != 'complete': _needs('complete_original_affected_and_reusable_dependency_assessment')
                keys([*change.affected_dependency_refs, *change.reuse_dependency_refs])
                for dependency_ref, affected in [(r, True) for r in change.affected_dependency_refs] + [(r, False) for r in change.reuse_dependency_refs]:
                    if dependency_ref.key() in dependency_ids: raise ValueError('Revision repeats a dependency disposition')
                    dependency_ids.add(dependency_ref.key())
                    dependency = read(dependency_ref, OwnerDesignDependencyView, scoped.scope_ref)
                    if not same(dependency.brief_ref, brief.ref) or not same(dependency.requirement_ref, change.ref) or dependency.affected != affected:
                        raise ValueError('Revision changes original affected/reusable dependency attribution')
                    authored(dependency, {'Architect', 'Engineer', 'QS'}, scoped.scope_ref)
                    for source_ref in dependency.source_deliverable_refs:
                        read(source_ref, OwnerDesignDeliverableView, scoped.scope_ref)
                    if not affected:
                        if dependency.reuse_basis_ref is None: _needs('independent_original_unchanged_scope_reuse_basis')
                        evidence([dependency.reuse_basis_ref])
                    acknowledge(dependency.issue_refs, scoped.scope_ref)
            return completed('request_revision', change_scope=scoped.model_dump(mode='python'), requirement_refs=profile.requirement_refs)
        if profile.submission_ref is None or profile.submission_ref.key() not in keys(action_input.submission_refs):
            _needs('original_professional_submission_for_owner_decision')
        submission = read(profile.submission_ref, OwnerDesignSubmissionView, scoped.scope_ref)
        authored(submission, {'Architect', 'Engineer', 'QS'}, scoped.scope_ref)
        if (submission.owner_organization_id != owner or not same(submission.brief_ref, brief.ref)
                or submission.status != 'submitted'): _needs('current_original_submission_for_this_owner')
        if not submission.deliverable_refs: _needs('original_nonempty_professional_deliverables')
        keys(submission.deliverable_refs)
        for ref in submission.deliverable_refs:
            deliverable = read(ref, OwnerDesignDeliverableView, scoped.scope_ref)
            authored(deliverable, {'Architect', 'Engineer', 'QS'}, scoped.scope_ref)
            if (not same(deliverable.submission_ref, submission.ref) or not same(deliverable.brief_ref, brief.ref)
                    or deliverable.author_organization_id != submission.author_organization_id or deliverable.status != 'current'):
                _needs('same_original_current_professional_submission_and_deliverables')
        if choice == 'accept_service':
            terms = read(submission.service_terms_ref, OwnerDesignServiceTermsView, scoped.scope_ref)
            if (terms.owner_organization_id != owner or terms.service_organization_id != submission.author_organization_id
                    or not same(terms.submission_ref, submission.ref) or terms.status != 'effective'):
                _needs('original_effective_service_terms_for_this_submission')
            if not keys(terms.required_deliverable_refs) <= keys(submission.deliverable_refs):
                _needs('contract_required_original_service_deliverables')
            keys(terms.acceptance_condition_refs)
            for ref in terms.acceptance_condition_refs:
                requirement(ref, purpose='condition', scope=scoped.scope_ref, submission=submission,
                            deliverables=submission.deliverable_refs, satisfy=True)
            acknowledge(submission.issue_refs, scoped.scope_ref, 'service_acceptance')
            return completed('accept_service', submission_ref=submission.ref, scope=scoped.model_dump(mode='python'))
        if profile.use_ref is None: _needs('original_requested_use_for_exact_submission_scope')
        use = read(profile.use_ref, OwnerDesignUseView, scoped.scope_ref)
        if (use.organization_id != owner or not same(use.submission_ref, submission.ref) or not same(use.brief_ref, brief.ref)
                or use.scope != scoped.scope_ref or not keys(use.deliverable_refs) <= keys(submission.deliverable_refs)):
            raise ValueError('Requested use changes owner, submission, scope or original deliverable versions')
        if not use.deliverable_refs: _needs('original_deliverable_versions_for_requested_use')
        rule = read(use.use_rule_ref, OwnerDesignUseRuleView, scoped.scope_ref)
        authored(rule, {'Architect', 'Engineer', 'QS', 'Government'}, scoped.scope_ref)
        if not same(rule.submission_ref, submission.ref) or rule.use_code != use.use_code:
            raise ValueError('Use rule applies to another original professional submission or activity')
        if not _known(rule.allowed, 'original_requested_use_permission'): _needs('original_requested_use_permission')
        if keys(use.condition_refs) != keys(rule.required_condition_refs): _needs('all_original_independent_use_gates')
        kinds = set()
        for ref in use.condition_refs:
            gate = requirement(ref, purpose='condition', scope=scoped.scope_ref, submission=submission,
                               deliverables=use.deliverable_refs, satisfy=True)
            kinds.add(gate.condition_kind)
        if not set(rule.required_condition_kinds) <= kinds: _needs('complete_original_professional_regulatory_and_scope_gate_kinds')
        if use.use_code in {'construction', 'operation'} and not {'professional', 'regulatory'} <= kinds:
            _needs('independent_professional_and_statutory_gates_for_requested_activity')
        for ref in use.deliverable_refs:
            deliverable = read(ref, OwnerDesignDeliverableView, scoped.scope_ref)
            if deliverable.maturity not in rule.permitted_maturities or use.use_code not in deliverable.allowed_use_codes:
                _needs('original_professional_maturity_and_declared_use_permission')
        acknowledge(submission.issue_refs, scoped.scope_ref, use.use_code)
        return completed('authorize_use', submission_ref=submission.ref, scope=scoped.model_dump(mode='python'), use_ref=use.ref)
    except ObservationGap as gap:
        reading.recheck(); return gap.result
