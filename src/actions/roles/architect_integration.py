"""ARCHITECT-A06 assembles original references without overriding their authors."""
import hashlib
import json

from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.architect_integration_objects import (
    ArchitectIntegrationOptionView, ArchitectIntegrationProfileView, ArchitectIntegrationSourceView,
    ArchitectIntegrationAuthorityView, ArchitectIntegrationIssueView, ArchitectIntegrationInterfaceView,
    ArchitectIntegrationQuestionView, ArchitectIntegrationConsistencyView, ArchitectIntegrationMethodView,
    ArchitectIntegrationConsistencyInput, ArchitectIntegrationConsistencyPreparation,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.service_objects import ServiceResponseRequirementView
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def integrate_interfaces(context, action_input, reading):
    return _integrate_interfaces(context, action_input, reading)


def prepare_architect_interface_consistency_input(context, action_input, reading, preparation):
    """Reuse original integration gates without consuming any future report.

    Direct authorized reading is required. Ordinary integration assembly still
    requires supplied reports; dedicated production assembly remains separate.
    """
    preparation = ArchitectIntegrationConsistencyPreparation.model_validate(preparation)
    return _integrate_interfaces(context, action_input, reading, consistency_preparation=preparation)


def _integrate_interfaces(context, action_input, reading, *, consistency_preparation=None):
    now, organization = context.business_time, reading.organization_id

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('architect-integration-clock-alignment')

    def evidence(refs, historical=False):
        keys(refs)
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('architect-integration-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not historical and not row.effective_window.contains(now): _needs('current_original_interface_evidence', [ref])

    def read(ref, schema, historical=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'architect-integration-projection:{ref.kind}')
        if hasattr(row, 'scope') and not scope_covers(action_input.scope, row.scope):
            raise ValueError('Interface input widens original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_original_interface_input', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historical and not row.effective_window.contains(now): _needs('current_original_interface_input', [ref])
        evidence(getattr(row, 'evidence_refs', []), historical)
        return row

    def authorize(ref, actor, function_ref, org, action, at):
        grant = read(ref, Authorization); function = read(function_ref, RoleAssignment)
        roles = {'ARCHITECT': 'Architect', 'ENGINEER': 'Engineer', 'QS': 'QS', 'SUPPLIER': 'Supplier',
                 'OWN': 'Owner', 'CONTRACTOR': 'Contractor', 'GOV': 'Government', 'BANK': 'Bank'}
        if (grant.actor_id != actor or grant.function_ref != function_ref or grant.organization_id != org
                or action not in grant.action_ids or function.role != roles.get(action.split('-')[0])
                or not any(scope_covers(scope, action_input.scope) for scope in grant.scopes)):
            raise ValueError('Interface input lacks independent original author/action/scope authority')
        clock(at); clock(grant.validity.start)
        if not grant.validity.contains(at): _needs('valid_original_interface_authority', [ref])
        evidence([*grant.basis_refs, *function.basis_refs], at != now)

    def completed(choice, **fields):
        reading.recheck(); return {'kind': 'completed', 'payload': {'choice': choice, 'scope': action_input.scope,
            'note': profile.reason, **fields}}

    def consistency_method(ref):
        method = read(ref, ArchitectIntegrationMethodView)
        if (not same(method.option_ref, option.ref)
                or set(method.checked_fields) != {'original_option_version', 'original_author_content', 'retained_open_issues'}):
            _unsupported('architect-integration-reference-consistency-method-domain')
        return method

    def original_digest(row):
        raw = json.dumps(row.model_dump(mode='json'), sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
        return hashlib.sha256(raw.encode()).hexdigest()

    def make_questions():
        questions = []
        keys(profile.question_refs)
        for ref in profile.question_refs:
            row = read(ref, ArchitectIntegrationQuestionView); question = row.question
            if not same(row.option_ref, option.ref) or question.scope != action_input.scope or ref.key() not in keys(question.target_refs):
                raise ValueError('Interface question changes original option/scope/target')
            if (not question.recipient_ids or not set(question.recipient_ids) <= set(profile.allowed_recipient_ids)
                    or not question.target_refs): raise ValueError('Interface question lacks original permitted recipients/targets')
            response = read(question.response_requirement_ref, ServiceResponseRequirementView)
            if not set(question.recipient_ids) <= set(response.recipient_ids): raise ValueError('Interface question exceeds original response authority')
            for target_ref in question.target_refs:
                target = read(target_ref, ArchitectIntegrationQuestionView)
                if not same(target.option_ref, option.ref) or target.question != question:
                    raise ValueError('Interface question mixes original registered targets')
            evidence(question.evidence_refs); questions.append(question.model_dump(mode='python'))
        if not questions: _needs('specific_original_interface_or_input_questions')
        return questions

    try:
        if action_input.scope != context.scope: raise ValueError('Interface action changes original authorized scope')
        option = read(action_input.option_ref, ArchitectIntegrationOptionView)
        option_grant = read(option.author_authority_ref, Authorization)
        authorize(option.author_authority_ref, option.author_actor_id, option.author_function_ref,
                  option_grant.organization_id, 'ARCHITECT-A05', option.available_at)
        profile = read(option.integration_profile_ref, ArchitectIntegrationProfileView)
        if consistency_preparation is not None and profile.choice != 'integrate':
            raise ValueError('Consistency preparation requires original integrate work; other choices are separate')
        if not same(profile.option_ref, option.ref) or profile.organization_id != organization:
            raise ValueError('Interface profile borrows another option version/organization')
        authorize(profile.authority_ref, context.actor_id, context.function_ref, organization, 'ARCHITECT-A06', now)
        if profile.coverage != 'complete': _needs('complete_received_original_interface_history')
        for field in ('professional_refs', 'cost_refs', 'supply_refs', 'open_issue_refs'):
            if keys(getattr(action_input, field)) != keys(getattr(profile, field)): _needs(f'all_original_interface_{field}')
        originals = {option.ref.key(): option}
        required_issues = set()
        kinds = (('professional_refs', 'ENGINEER'), ('cost_refs', 'QS'), ('supply_refs', 'SUPPLIER'))
        for field, prefix in kinds:
            for ref in getattr(action_input, field):
                source = read(ref, ArchitectIntegrationSourceView)
                if not same(source.option_ref, option.ref) or source.author_action_id.split('-')[0] != prefix:
                    raise ValueError('Interface source changes original option version or professional author function')
                clock(source.authored_at)
                if source.authored_at.offset > min(now.offset, source.available_at.offset): _needs('interface_authored_before_received')
                authorize(source.author_authority_ref, source.author_actor_id, source.author_function_ref,
                          source.author_organization_id, source.author_action_id, source.authored_at)
                keys(source.unresolved_issue_refs); required_issues.update(ref.key() for ref in source.unresolved_issue_refs)
                if source.status != 'recorded' or not isinstance(source.conclusion, Known) or source.conclusion.value == 'conflict':
                    if not source.unresolved_issue_refs: _needs('original_issue_for_unknown_or_conflicting_professional_input', [source.ref])
                originals[source.ref.key()] = source
        keys(profile.interface_refs)
        for ref in profile.interface_refs:
            interface = read(ref, ArchitectIntegrationInterfaceView)
            if not same(interface.option_ref, option.ref) or not keys(interface.input_refs) <= set(originals):
                raise ValueError('Interface changes original option or borrows undeclared author inputs')
            required_issues.update(keys(interface.unresolved_issue_refs)); originals[ref.key()] = interface
        if not required_issues <= keys(action_input.open_issue_refs): _needs('retain_all_original_unresolved_author_interface_issues')
        for ref in action_input.open_issue_refs:
            issue = read(ref, ArchitectIntegrationIssueView)
            if (not same(issue.option_ref, option.ref) or issue.status == 'closed'
                    or not keys(issue.author_reference_refs) <= set(originals)
                    or not keys(issue.interface_refs) <= keys(profile.interface_refs)):
                raise ValueError('Open interface issue changes original option/authors/interfaces or claims closure')
            originals[ref.key()] = issue
        choice = profile.choice
        delegation = None
        if choice == 'integrate' and action_input.integration_authority_ref is None: choice = profile.without_authority_choice
        if choice == 'integrate':
            delegation = read(action_input.integration_authority_ref, ArchitectIntegrationAuthorityView, True)
            clock(delegation.granted_at)
            if delegation.granted_at.offset > min(now.offset, delegation.available_at.offset): _needs('received_original_integration_delegation')
            if (not same(delegation.option_ref, option.ref) or delegation.grantee_organization_id != organization
                    or delegation.grantee_actor_id != context.actor_id or delegation.grantee_function_ref != context.function_ref):
                raise ValueError('Integration delegation changes original grantee/option/function')
            authorize(delegation.issuer_authority_ref, delegation.issuer_actor_id, delegation.issuer_function_ref,
                      delegation.issuer_organization_id, delegation.issuer_action_id, delegation.granted_at)
            if (not delegation.effective_window.contains(now) or not isinstance(delegation.permission, Known)
                    or not delegation.permission.value):
                choice = profile.without_authority_choice
            elif (not (keys(action_input.professional_refs) | keys(action_input.cost_refs) | keys(action_input.supply_refs)) <= keys(delegation.permitted_input_refs)
                    or not keys(profile.interface_refs) <= keys(delegation.permitted_interface_refs)):
                raise ValueError('Integration exceeds independently delegated author input/interface scope')
        if consistency_preparation is not None and choice != 'integrate':
            _needs('original_authorized_integration_for_consistency_preparation')
        if choice in {'raise_interfaces', 'request_inputs'}:
            return completed(choice, **{('issues' if choice == 'raise_interfaces' else 'questions'): make_questions()})
        if choice == 'escalate':
            if not action_input.open_issue_refs: _needs('original_open_issues_for_authorized_escalation')
            if profile.recipient_authority_ref is None or profile.recipient_action_id is None:
                _needs('independently_authorized_interface_coordination_recipient')
            recipient = read(profile.recipient_authority_ref, Authorization)
            if recipient.actor_id not in profile.allowed_recipient_ids: raise ValueError('Interface escalation invents an unauthorized recipient')
            authorize(recipient.ref, recipient.actor_id, recipient.function_ref, recipient.organization_id, profile.recipient_action_id, now)
            return completed('escalate', issue_refs=action_input.open_issue_refs, recipient_id=recipient.actor_id, reason=profile.reason)
        if not profile.consistency_result_refs: _needs('executed_original_reference_consistency_results')
        keys(profile.consistency_result_refs)
        if consistency_preparation is not None:
            target = consistency_preparation.calculation_ref
            future_keys = keys(profile.consistency_result_refs)
            if target.key() not in future_keys or type(target.version) is not str:
                raise ValueError('Consistency preparation changes the original predeclared immutable report target')
            method = consistency_method(consistency_preparation.method_ref)
            data = ArchitectIntegrationConsistencyInput(option_ref=option.ref,
                input_digests=[{'input_ref': row.ref, 'content_sha256': original_digest(row)} for row in originals.values()],
                original_objects=list(originals.values()),
                interface_refs=profile.interface_refs, retained_issue_refs=action_input.open_issue_refs,
                source_refs=[row.ref for row in originals.values()] + [profile.ref, method.ref, delegation.ref],
                basis_refs=list({ref.key(): ref for row in [*originals.values(), profile, method, delegation]
                    for ref in row.evidence_refs}.values()))
            keys(data.source_refs)
            if any((row['ref']['kind'], row['ref']['id'], row['ref']['version']) in future_keys
                    for row in reading.evidence()):
                raise ValueError('Consistency preparation cannot consume its future report outputs')
            reading.recheck()
            return {'kind': 'prepared', 'preparation': consistency_preparation, 'input': data,
                'option': option, 'profile': profile, 'method': method, 'delegation': delegation}
        for ref in profile.consistency_result_refs:
            result = read(ref, ArchitectIntegrationConsistencyView)
            clock(result.executed_at)
            if not same(result.option_ref, option.ref) or result.executed_at.offset > min(now.offset, result.available_at.offset):
                raise ValueError('Integration consistency changes original option/executed time')
            grant = read(result.author_authority_ref, Authorization)
            authorize(grant.ref, result.author_actor_id, result.author_function_ref, grant.organization_id, 'ARCHITECT-A06', result.executed_at)
            consistency_method(result.method_ref)
            if result.status == 'unsupported': _unsupported('architect-integration-upstream-consistency-method')
            if result.status != 'ok': _needs('successful_original_reference_consistency_execution')
            keys([row.input_ref for row in result.input_digests])
            if (set(row.input_ref.key() for row in result.input_digests) != set(originals)
                    or keys(result.interface_refs) != keys(profile.interface_refs)
                    or keys(result.retained_issue_refs) != keys(action_input.open_issue_refs)):
                raise ValueError('Consistency result drops or changes original authors, interfaces or unresolved issues')
            for item in result.input_digests:
                original = originals[item.input_ref.key()]
                if original_digest(original) != item.content_sha256:
                    raise ValueError('Integration consistency result changes original author content')
        return completed('integrate', draft={'option_ref': option.ref, 'included_assessment_refs': action_input.professional_refs,
            'included_cost_refs': action_input.cost_refs, 'interface_refs': profile.interface_refs, 'open_issue_refs': action_input.open_issue_refs,
            'integration_authority_ref': delegation.ref, 'consistency_result_refs': profile.consistency_result_refs})
    except ObservationGap as gap:
        reading.recheck(); return gap.result
