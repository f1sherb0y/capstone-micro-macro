"""ARCHITECT-A09 explanations cannot silently alter design, works or fee liability."""
import hashlib
import json

from src.actions.contracts.common import EvidenceRecord, Known, Measured
from src.actions.contracts.architect_change_objects import (
    ArchitectChangeDeliverableView, ArchitectChangeIssueView, ArchitectChangeObligationView,
    ArchitectChangeProfileView, ArchitectChangeInstructionView, ArchitectChangeDependencyView,
    ArchitectChangeImpactMethodView, ArchitectChangeImpactResultView, ArchitectChangeEntitlementView,
    ArchitectChangeQuestionView, ArchitectDesignVariableView, ArchitectDesignReferenceView,
    ArchitectChangeImpactInput, ArchitectChangeImpactPreparation,
    ArchitectChangeImpactBasisView,
)
from src.actions.contracts.service_objects import ServiceResponseRequirementView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.methods.pricing import decimal_fraction
from src.methods.architect_change_impact import ARCHITECT_CHANGE_IMPACT_METHOD, calculate_declared_change_impact
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def support_design_change(context, action_input, reading):
    return _support_design_change(context, action_input, reading)


def prepare_architect_change_impact_input(context, action_input, reading, preparation):
    """Retain authorized original change sources without consuming impact outputs."""
    preparation = ArchitectChangeImpactPreparation.model_validate(preparation).model_copy(deep=True)
    if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'ARCHITECT-A09':
        raise ValueError('Change impact preparation requires original Architect A09 contract')
    reading.check_method_context(context, 'ARCHITECT-A09')
    before = reading.method_evidence()
    future = {ref.key() for ref in action_input.impact_result_refs}

    def recheck_preparation():
        if reading.method_evidence() != before or future.intersection(reading._reads):
            raise ValueError('Impact preparation cannot execute methods or consume reserved results')

    recheck_preparation()
    try:
        return _support_design_change(context, action_input, reading, impact_preparation=preparation)
    finally:
        reading.recheck()
        recheck_preparation()


def _support_design_change(context, action_input, reading, *, impact_preparation=None):
    now, organization = context.business_time, reading.organization_id

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('architect-change-clock-alignment')

    def evidence(refs, historical=False):
        keys(refs)
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('architect-change-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not historical and not row.effective_window.contains(now): _needs('current_original_design_change_evidence', [ref])

    def read(ref, schema, historical=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'architect-change-projection:{ref.kind}')
        if hasattr(row, 'scope') and not scope_covers(action_input.scope, row.scope):
            raise ValueError('Design change widens original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_original_design_change_input', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historical and not row.effective_window.contains(now): _needs('effective_original_design_change_input', [ref])
        evidence(getattr(row, 'evidence_refs', []), historical)
        return row

    def authorize(ref, actor, function_ref, org, action, at):
        grant = read(ref, Authorization); function = read(function_ref, RoleAssignment)
        roles = {'ARCHITECT': 'Architect', 'ENGINEER': 'Engineer', 'QS': 'QS', 'SUPPLIER': 'Supplier',
                 'OWN': 'Owner', 'CONTRACTOR': 'Contractor', 'GOV': 'Government', 'BANK': 'Bank'}
        if (grant.actor_id != actor or grant.organization_id != org or grant.function_ref != function_ref
                or action not in grant.action_ids or function.role != roles.get(action.split('-')[0])
                or not any(scope_covers(scope, action_input.scope) for scope in grant.scopes)):
            raise ValueError('Design change lacks independent original author/action/scope authority')
        clock(at); clock(grant.validity.start)
        if not grant.validity.contains(at): _needs('valid_original_design_change_authority', [ref])
        evidence([*grant.basis_refs, *function.basis_refs], at != now)

    def completed(choice, **fields):
        reading.recheck(); return {'kind': 'completed', 'payload': {'choice': choice, 'scope': action_input.scope,
            'note': profile.note, **fields}}

    def questions(refs):
        keys(refs); output = []
        for ref in refs:
            row = read(ref, ArchitectChangeQuestionView); question = row.question
            if (not same(row.issue_ref, issue.ref) or not same(row.used_deliverable_ref, original.ref)
                    or question.scope != action_input.scope or not question.recipient_ids
                    or ref.key() not in keys(question.target_refs)):
                raise ValueError('Design change question changes original issue/version/scope/target')
            response = read(question.response_requirement_ref, ServiceResponseRequirementView)
            if not set(question.recipient_ids) <= set(response.recipient_ids): raise ValueError('Design change question exceeds original response recipients')
            for target_ref in question.target_refs:
                target = read(target_ref, ArchitectChangeQuestionView)
                if not same(target.issue_ref, issue.ref) or not same(target.used_deliverable_ref, original.ref) or target.question != question:
                    raise ValueError('Design change question mixes original issue targets')
            evidence(question.evidence_refs); output.append(question.model_dump(mode='python'))
        return output

    def request_authority():
        rows = questions(profile.question_refs)
        if not rows: _needs('specific_original_design_change_authority_questions')
        return completed('request_authority', questions=rows)

    try:
        if action_input.scope != context.scope: raise ValueError('Design support changes original action scope')
        original = read(action_input.used_deliverable_ref, ArchitectChangeDeliverableView, True)
        issue = read(action_input.issue_ref, ArchitectChangeIssueView)
        obligation = read(action_input.obligation_ref, ArchitectChangeObligationView)
        profile = read(issue.change_profile_ref, ArchitectChangeProfileView)
        if (not same(issue.used_deliverable_ref, original.ref) or not same(issue.obligation_ref, obligation.ref)
                or not same(obligation.deliverable_ref, original.ref) or obligation.organization_id != organization
                or not same(profile.issue_ref, issue.ref) or not same(profile.obligation_ref, obligation.ref)):
            raise ValueError('Design support borrows another issue, original version or contract obligation')
        if issue.status == 'closed' or obligation.status == 'terminated': _needs('original_applicable_open_design_support_obligation')
        clock(original.authored_at)
        if original.authored_at.offset > min(now.offset, original.available_at.offset): _needs('original_design_authored_before_received')
        authorize(original.author_authority_ref, original.author_actor_id, original.author_function_ref,
                  original.author_organization_id, original.author_action_id, original.authored_at)
        authorize(profile.authority_ref, context.actor_id, context.function_ref, organization, 'ARCHITECT-A09', now)
        if not scope_covers(action_input.scope, profile.affected_scope): raise ValueError('Design support widens original affected scope')
        choice = profile.choice
        old = {row.variable_ref.key(): row.value for row in original.variables}; keys([row.variable_ref for row in original.variables])
        keys([row.variable_ref for row in profile.proposed_variable_changes])
        changed = any(old.get(row.variable_ref.key()) != row.value for row in profile.proposed_variable_changes)
        if choice == 'explain' and (changed or (isinstance(profile.response_preserves_content, Known) and not profile.response_preserves_content.value)):
            choice = 'propose_change'
        if choice == 'explain' and not isinstance(profile.response_preserves_content, Known): _needs('verified_explanation_preserves_original_content')
        if choice not in obligation.permitted_choices: return request_authority()
        if choice == 'request_authority': return request_authority()
        if impact_preparation is not None and choice != 'propose_change':
            raise ValueError('Impact preparation requires an original permitted change proposal')
        if choice == 'explain':
            if not profile.response_basis_refs: _needs('original_design_explanation_evidence')
            evidence(profile.response_basis_refs)
            return completed('explain', issue_ref=issue.ref, response=profile.response, basis_refs=profile.response_basis_refs)
        instruction = None
        if action_input.instruction_ref is not None:
            instruction = read(action_input.instruction_ref, ArchitectChangeInstructionView)
            clock(instruction.issued_at)
            if (not same(instruction.issue_ref, issue.ref) or not same(instruction.obligation_ref, obligation.ref)
                    or not same(instruction.used_deliverable_ref, original.ref) or not same(instruction.contract_ref, obligation.contract_ref)
                    or instruction.issuer_organization_id not in obligation.permitted_instruction_issuer_ids
                    or instruction.issuer_action_id not in obligation.permitted_instruction_action_ids):
                raise ValueError('Design instruction changes original issue/version/contract or authorized issuer')
            if instruction.issued_at.offset > min(now.offset, instruction.available_at.offset): _needs('design_instruction_issued_before_received')
            authorize(instruction.issuer_authority_ref, instruction.issuer_actor_id, instruction.issuer_function_ref,
                      instruction.issuer_organization_id, instruction.issuer_action_id, instruction.issued_at)
            if instruction.status != 'authorized': return request_authority()
        remedy = issue.kind == 'defect_remedy' and obligation.defect_remedy_authorized
        if obligation.instruction_required_for_change and instruction is None and not remedy: return request_authority()
        if instruction is not None and not scope_covers(instruction.scope, profile.affected_scope):
            return request_authority()
        for row in profile.proposed_variable_changes:
            if row.variable_ref.key() not in keys(obligation.variable_refs): return request_authority()
            if instruction is not None and row.variable_ref.key() not in keys(instruction.authorized_variable_refs): return request_authority()
            catalog = read(row.variable_ref, ArchitectDesignVariableView)
            if not same(catalog.design_profile_ref, original.design_profile_ref): raise ValueError('Design change variable belongs to another catalog')
            evidence(row.source_refs)
            if row.value.state == 'unknown':
                if not catalog.allow_unknown: _needs('required_original_design_change_variable', row.value.missing_refs)
                continue
            if not isinstance(row.value, Known): _unsupported('architect-change-variable-value-state')
            value = row.value.value
            if catalog.value_kind == 'measured':
                if not isinstance(value, Measured) or value.unit != catalog.unit: _unsupported('architect-change-variable-unit')
                if value.basis_ref.key() not in keys(row.source_refs): raise ValueError('Design change number loses its original evidence')
                if any(bound is None for bound in (catalog.minimum, catalog.maximum, catalog.step)): _needs('original_change_variable_bounds_and_precision')
                for bound in (catalog.minimum, catalog.maximum, catalog.step):
                    if bound.unit != value.unit: _unsupported('architect-change-variable-bound-unit')
                    evidence([bound.basis_ref])
                low, high, step = (decimal_fraction(bound.value) for bound in (catalog.minimum, catalog.maximum, catalog.step))
                number = decimal_fraction(value.value)
                if low > high or step <= 0 or not low <= number <= high or ((number - low) / step).denominator != 1:
                    raise ValueError('Design change leaves original variable range or precision')
            else:
                if not hasattr(value, 'kind') or value.kind != 'CatalogOption' or value.key() not in keys(catalog.catalog_option_refs):
                    raise ValueError('Design change invents an undeclared catalog option')
                selected = read(value, ArchitectDesignReferenceView)
                if not same(selected.design_profile_ref, original.design_profile_ref): raise ValueError('Design change selection changes its original catalog')
        keys(original.dependency_refs); dependencies = {}
        change_refs = keys([row.variable_ref for row in profile.proposed_variable_changes])
        for ref in original.dependency_refs:
            dependency = read(ref, ArchitectChangeDependencyView, True)
            if not same(dependency.used_deliverable_ref, original.ref): raise ValueError('Design dependency changes original used version')
            if dependency.status != 'released' and keys(dependency.depends_on_variable_refs).intersection(change_refs): dependencies[ref.key()] = ref
        affected = keys(profile.affected_dependency_refs)
        if not set(dependencies) <= affected or not affected <= keys(original.dependency_refs):
            raise ValueError('Design change drops or invents original affected dependencies')
        unresolved = questions(profile.question_refs)
        impact_ref = None
        keys(action_input.impact_result_refs)
        if len(action_input.impact_result_refs) > 1: _needs('unique_original_design_change_impact_result')
        if impact_preparation is not None and (
                action_input.impact_result_refs != [impact_preparation.calculation_ref]
                or type(impact_preparation.calculation_ref.version) is not str):
            raise ValueError('Impact preparation replaces the original immutable result target')
        if action_input.impact_result_refs:
            if action_input.impact_method_ref is None or action_input.impact_method_ref.key() not in keys(obligation.permitted_impact_method_refs):
                _unsupported('architect-change-original-impact-method')
            method = read(action_input.impact_method_ref, ArchitectChangeImpactMethodView)
            if not same(method.obligation_ref, obligation.ref): raise ValueError('Impact method borrows another contract obligation')
            if not isinstance(method.supported, Known): _needs('known_original_change_impact_method_support')
            if not method.supported.value: _unsupported('architect-change-impact-domain')
            data = {'issue_ref': issue.ref.model_dump(mode='json'), 'used_deliverable_ref': original.ref.model_dump(mode='json'),
                'original_content_sha256': original.content_sha256, 'obligation_ref': obligation.ref.model_dump(mode='json'),
                'instruction_ref': action_input.instruction_ref.model_dump(mode='json') if action_input.instruction_ref is not None else None,
                'instruction_content': instruction.model_dump(mode='json') if instruction is not None else None,
                'affected_scope': profile.affected_scope.model_dump(mode='json'),
                'affected_dependency_refs': [ref.model_dump(mode='json') for ref in profile.affected_dependency_refs],
                'proposed_variable_changes': [row.model_dump(mode='json') for row in profile.proposed_variable_changes]}
            digest = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
            impact_basis = None
            if same(method.ref, ARCHITECT_CHANGE_IMPACT_METHOD):
                if profile.impact_basis_ref is None:
                    _needs('original_declared_design_change_cost_and_duration_basis')
                impact_basis = read(profile.impact_basis_ref, ArchitectChangeImpactBasisView)
                if impact_basis.input.basis_ref != impact_basis.ref or impact_basis.input.input_sha256 != digest:
                    raise ValueError('Declared impact totals replace original basis or issue/content/instruction/variable input')
                for ref in impact_basis.input.source_refs:
                    if ref != impact_basis.ref:
                        evidence([ref])
            if impact_preparation is not None:
                original_input = ArchitectChangeImpactInput.model_validate(data)
                if impact_preparation.input != original_input:
                    raise ValueError('Impact preparation changes original issue/content/instruction/scope/dependencies or variables')
                reading.recheck()
                return {'kind': 'prepared', 'preparation': impact_preparation, 'issue': issue,
                    'original': original, 'obligation': obligation, 'profile': profile,
                    'instruction': instruction, 'method': method, 'input_sha256': digest,
                    'impact_basis': impact_basis,
                    'arithmetic': impact_basis.input if impact_basis is not None else None}
            result = read(action_input.impact_result_refs[0], ArchitectChangeImpactResultView)
            clock(result.executed_at)
            if (not same(result.issue_ref, issue.ref) or not same(result.used_deliverable_ref, original.ref)
                    or not same(result.method_ref, method.ref) or result.instruction_ref != action_input.instruction_ref
                    or result.input_sha256 != digest or result.author_organization_id not in method.permitted_author_ids
                    or result.executed_at.offset > min(now.offset, result.available_at.offset)):
                raise ValueError('Design impact result changes original instruction/version/proposed content or execution')
            authorize(result.author_authority_ref, result.author_actor_id, result.author_function_ref,
                      result.author_organization_id, result.author_action_id, result.executed_at)
            if not method.effective_window.contains(result.executed_at): _needs('impact_method_valid_when_executed')
            if result.status == 'unsupported': _unsupported('architect-change-upstream-impact-method')
            if result.status == 'ok':
                if impact_basis is not None:
                    report = calculate_declared_change_impact(impact_basis.input)
                    if result.cost_delta != report.cost_delta or result.duration_delta != report.duration_delta:
                        raise ValueError('Saved declared impact differs from original sourced cost or duration inputs')
                impact_ref = result.ref
                for state in (result.cost_delta, result.duration_delta):
                    if isinstance(state, Known): evidence([state.value.basis_ref])
            if result.status != 'ok' or result.cost_delta.state != 'known' or result.duration_delta.state != 'known':
                gaps = questions(profile.impact_question_refs)
                if not gaps: _needs('explicit_unverified_design_impact_questions')
                unresolved.extend(gaps)
        else:
            gaps = questions(profile.impact_question_refs)
            if not gaps: _needs('explicit_scope_waiting_for_design_change_impact_assessment')
            unresolved.extend(gaps)
        entitlement_ref = None
        if profile.fee_entitlement_ref is not None:
            entitlement = read(profile.fee_entitlement_ref, ArchitectChangeEntitlementView)
            clock(entitlement.decided_at)
            if (not same(entitlement.issue_ref, issue.ref) or not same(entitlement.obligation_ref, obligation.ref)
                    or not same(entitlement.contract_ref, obligation.contract_ref) or not same(entitlement.used_deliverable_ref, original.ref)
                    or entitlement.cause != issue.kind or entitlement.resolver_organization_id not in obligation.permitted_entitlement_resolver_ids
                    or entitlement.resolver_action_id not in obligation.permitted_entitlement_action_ids
                    or entitlement.decided_at.offset > min(now.offset, entitlement.available_at.offset)):
                raise ValueError('Design fee entitlement changes original cause/contract/version or deciding authority')
            authorize(entitlement.resolver_authority_ref, entitlement.resolver_actor_id, entitlement.resolver_function_ref,
                      entitlement.resolver_organization_id, entitlement.resolver_action_id, entitlement.decided_at)
            if isinstance(entitlement.fee_right, Known): entitlement_ref = entitlement.ref
        unique_questions = {json.dumps(row, sort_keys=True, default=lambda value: value.model_dump(mode='json')): row for row in unresolved}
        return completed('propose_change', draft={'prior_deliverable_ref': original.ref, 'instruction_ref': action_input.instruction_ref,
            'affected_scope': profile.affected_scope, 'affected_dependency_refs': profile.affected_dependency_refs,
            'proposed_variable_changes': [row.model_dump(mode='python') for row in profile.proposed_variable_changes],
            'impact_result_ref': impact_ref, 'fee_entitlement_ref': entitlement_ref, 'unresolved_questions': list(unique_questions.values())})
    except ObservationGap as gap:
        reading.recheck(); return gap.result
