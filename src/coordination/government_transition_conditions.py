"""Resolve the original GOV-A09 command uncertainty before fresh change judgment."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Known, ref_type, walk_references
from src.actions.contracts.government_transition_objects import (
    GovTransitionDecisionView, GovTransitionPermitView, GovTransitionApplicationView,
    GovReviewSubmissionView, GovTransitionRuleView, GovChangeBasisView, GovChangeAuthorityView,
    GovDecisionCommandView,
)
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionProfile
from src.coordination.government_decision_query import GovernmentDecisionQueryRecord
from src.coordination.government_transition_notification import NOTIFICATION_CODE
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


_CODE = 'government-transition-query-original-command'
_CODES = (_CODE, NOTIFICATION_CODE)
_FIELDS = frozenset({'scope', 'application_ref', 'prior_decision_ref', 'permit_ref',
    'affected_submission_ref', 'evidence_refs', 'transition_rule_ref'})
_BASES = (('prior_decision_ref', 'Decision', GovTransitionDecisionView),
    ('transition_rule_ref', 'Rule', GovTransitionRuleView))
_OPTIONAL = (('permit_ref', 'Permit', GovTransitionPermitView),
    ('application_ref', 'RegulatoryApplication', GovTransitionApplicationView),
    ('affected_submission_ref', 'Submission', GovReviewSubmissionView))


@dataclass(frozen=True)
class GovernmentTransitionConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict
    original_context: ActionContext
    transition_sources: list[dict] | None = None
    unavailable_targets: list[dict] | None = None
    command_query: dict | None = None
    notification_completion: dict | None = None
    notification_snapshot: dict | None = None


def government_original_transition_query_profile(read_current, validate_relation):
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Transition query recovery requires guarded original sources and native validation')

    def physical(value):
        if isinstance(value, dict):
            return {key: physical(item) for key, item in value.items()
                if not (key == 'version' and set(value) == {'kind', 'id', 'version'})}
        if isinstance(value, list):
            return [physical(item) for item in value]
        return value

    def identities(refs):
        keys = {ref.key()[:2] for ref in refs}
        if len(keys) != len(refs):
            raise TaskConflict('Transition recovery duplicates a physical historical source')
        return keys

    def evaluate(check):
        source = check.source['identity']
        if (source['action_id'] != 'GOV-A09' or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in check.condition.object_refs) != ('DecisionCommand',)
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Transition recovery replaces original command wait/run/agency')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, GovernmentTransitionConditionReading) or not isinstance(selected.context, ActionContext)
                or not isinstance(selected.original_context, ActionContext) or not isinstance(selected.reading, ActionReadView)):
            raise TaskConflict('Transition recovery requires typed original/current invocation sources')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
        try:
            if (set(raw) != _FIELDS or set(current_raw) != _FIELDS or task_digest(raw) != source['input_sha256']
                    or task_digest(selected.original_context.model_dump(mode='json')) != source['context_sha256']
                    or raw['scope'] != current_raw['scope'] or context.scope != selected.original_context.scope
                    or context.run_id != source['run_id'] or context.contract_ref.id != 'GOV-A09'
                    or context.execution_mode != 'llm' or context.operation_id == source['request_id']
                    or context.business_time != check.signal.business_time or reading._resolver.source_mode != 'formal'
                    or reading.organization_id != source['organization_id']):
                raise TaskConflict('Transition recovery changes original snapshot/scope/current operation')
            reading.check_method_context(context, 'GOV-A09')
            versions, proof_rows, proof_refs = [], [], []

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref:
                    raise TaskConflict('Transition recovery lacks exact original/current source versions')
                proof_rows.append(row)
                return row

            for action_input, invocation in ((raw, selected.original_context), (current_raw, context)):
                rows = {field: read(ref_type(kind).model_validate(action_input[field]), schema)
                    for field, kind, schema in (*_BASES, *_OPTIONAL) if action_input[field] is not None}
                prior, rule = rows['prior_decision_ref'], rows['transition_rule_ref']
                if rule.decision_basis_ref is None or 'affected_submission_ref' not in rows:
                    raise TaskConflict('Transition recovery loses original actual change basis/final submission')
                basis = read(rule.decision_basis_ref, GovChangeBasisView)
                command = read(basis.command_ref, GovDecisionCommandView)
                authority = read(basis.authority_ref, GovChangeAuthorityView)
                submission = rows['affected_submission_ref']
                if (prior.organization_id != source['organization_id'] or not scope_covers(prior.scope, context.scope)
                        or rule.choice not in {'renew', 'suspend', 'revoke', 'restore'} or rule.purpose != 'transition'
                        or rule.organization_id != source['organization_id'] or rule.prior_decision_ref != prior.ref
                        or rule.permit_ref != prior.permit_ref or rule.application_ref != getattr(rows.get('application_ref'), 'ref', None)
                        or rule.affected_submission_ref != submission.ref or rule.content_sha256 != submission.content_sha256
                        or basis.transition_rule_ref != rule.ref or basis.content_sha256 != submission.content_sha256
                        or basis.application_ref != rule.application_ref or basis.draft.outcome != rule.choice
                        or basis.draft.prior_decision_ref != prior.ref or basis.draft.case_ref != prior.case_ref
                        or basis.draft.submission_ref != submission.ref or basis.draft.decision_basis_ref != basis.ref
                        or basis.draft.covered_scope.model_dump(mode='json') != action_input['scope']
                        or command.case_ref != prior.case_ref or command.submission_ref != submission.ref
                        or command.decision_basis_ref != basis.ref or command.operation_id != invocation.operation_id
                        or command.draft_sha256 != content_digest(basis.draft)
                        or prior.history_coverage != 'complete' or prior.as_of != invocation.business_time):
                    raise TaskConflict('Transition recovery substitutes prior formal decision, agency, draft, content or command')
                identities(prior.history_refs)
                history = [read(ref, GovTransitionDecisionView) for ref in prior.history_refs]
                if any(row.case_ref != prior.case_ref for row in history):
                    raise TaskConflict('Transition recovery borrows another original case change history')
                grant, function = reading.resolve(basis.signer_authorization_ref), reading.resolve(invocation.function_ref)
                if (authority.organization_id != source['organization_id'] or authority.actor_id != invocation.actor_id
                        or authority.function_ref != invocation.function_ref or authority.prior_decision_ref != prior.ref
                        or authority.permit_ref != prior.permit_ref or authority.decision_basis_ref != basis.ref
                        or rule.choice not in authority.outcomes or not isinstance(authority.permitted, Known) or not authority.permitted.value
                        or basis.signer_authorization_ref not in invocation.authorization_refs
                        or not isinstance(grant, Authorization) or grant.ref != basis.signer_authorization_ref
                        or not isinstance(function, RoleAssignment) or function.function_ref != invocation.function_ref
                        or function.role != 'Government' or grant.actor_id != invocation.actor_id
                        or grant.organization_id != source['organization_id'] or grant.function_ref != invocation.function_ref
                        or 'GOV-A09' not in grant.action_ids or not grant.validity.contains(invocation.business_time)
                        or not any(scope_covers(covered, context.scope) for covered in grant.scopes)):
                    raise TaskConflict('Transition recovery lacks independently authorized original/current change signer')
                refs = [ref_type('Evidence').model_validate(ref) for ref in action_input['evidence_refs']]
                identities(refs)
                proof_refs.extend([*refs, *grant.basis_refs, *function.basis_refs])
                versions.append(dict(**rows, basis=basis, command=command, authority=authority,
                    evidence=refs, same=[row for row in history if row.business_key == command.business_key]))
            old, current = versions
            old_command, command = old['command'], current['command']
            if (tuple(check.condition.object_refs) != (old_command.ref,) or old['same']
                    or old_command.official_decision_ref is not None or old_command.status == 'recorded'
                    or old_command.lookup_status == 'present'
                    or not (old_command.status == 'submitted_unknown' or old_command.lookup_status == 'unknown')):
                raise TaskConflict('Transition recovery differs from original uncertain-command gate order')
            if selected.command_query is None:
                return 'waiting'
            query = GovernmentDecisionQueryRecord.model_validate(deepcopy(selected.command_query))
            if (query.source_identity_sha256 != task_digest(source) or query.run_id != source['run_id']
                    or query.organization_id != source['organization_id'] or query.command_ref != old_command.ref
                    or query.operation_id != old_command.operation_id or query.business_key != old_command.business_key
                    or query.draft_sha256 != old_command.draft_sha256 or query.queried_at != context.business_time
                    or query.queried_at.clock_ref != selected.original_context.business_time.clock_ref
                    or query.queried_at.offset < selected.original_context.business_time.offset):
                raise TaskConflict('Transition query changes original command/business/draft/actual lookup time')
            if query.result != 'absent':
                return 'waiting'
            if (any((field in old) != (field in current) or field in old and old[field].ref.key()[:2] != current[field].ref.key()[:2]
                        for field, _, _ in (*_BASES, *_OPTIONAL))
                    or old_command.ref.key()[:2] != command.ref.key()[:2] or old_command.business_key != command.business_key
                    or old['affected_submission_ref'].content_sha256 != current['affected_submission_ref'].content_sha256
                    or old['basis'].ref.key()[:2] != current['basis'].ref.key()[:2]
                    or any(getattr(old['basis'], field).key()[:2] != getattr(current['basis'], field).key()[:2]
                        for field in ('outcome_rule_ref', 'authority_ref', 'signer_authorization_ref', 'procedure_ref'))
                    or physical(old['basis'].draft.model_dump(mode='json')) != physical(current['basis'].draft.model_dump(mode='json'))
                    or any(physical(getattr(old['prior_decision_ref'], field).model_dump(mode='json')) != physical(
                        getattr(current['prior_decision_ref'], field).model_dump(mode='json'))
                        for field in ('case_ref', 'submission_ref', 'command_ref', 'signer_function_ref', 'effect_rule_ref', 'scope'))
                    or any(getattr(old['prior_decision_ref'], field) != getattr(current['prior_decision_ref'], field)
                        for field in ('applicant_id', 'organization_id', 'business_key', 'draft_sha256', 'signer_actor_id', 'outcome'))
                    or physical([row.model_dump(mode='json') for row in old['prior_decision_ref'].conditions]) != physical(
                        [row.model_dump(mode='json') for row in current['prior_decision_ref'].conditions])
                    or identities(old['prior_decision_ref'].history_refs) - identities(current['prior_decision_ref'].history_refs)
                    or identities(old['prior_decision_ref'].notification_refs) - identities(current['prior_decision_ref'].notification_refs)
                    or identities(old['basis'].condition_basis_refs) != identities(current['basis'].condition_basis_refs)
                    or identities(old['basis'].removed_condition_rule_refs) != identities(current['basis'].removed_condition_rule_refs)
                    or identities(old['evidence']) - identities(current['evidence'])
                    or old['transition_rule_ref'].choice != current['transition_rule_ref'].choice):
                raise TaskConflict('Transition recovery rewrites original terms/conditions/retained notification or change history')
            if (current['same'] or command.official_decision_ref is not None or command.lookup_status != 'absent'
                    or command.status != 'not_submitted'):
                return 'waiting'
            if any(row.available_at.clock_ref != context.business_time.clock_ref or row.available_at.offset > context.business_time.offset
                    or not row.effective_window.contains(context.business_time) for row in (
                        current['transition_rule_ref'], current['basis'], current['authority'], command)):
                return 'unavailable'
            proof_refs.extend(query.evidence_refs)
            proof_refs.extend(ref for row in proof_rows for ref in walk_references(row) if ref.kind == 'Evidence')
            evidence = {}
            for ref in proof_refs:
                row = reading.resolve(ref)
                if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                    raise TaskConflict('Transition recovery requires observed original draft/history and actual lookup evidence')
                evidence[ref.key()] = row.model_dump(mode='json')
            if validate_relation(source_identity=deepcopy(source), condition_code=_CODE,
                    original_action_input=raw, action_input=current_raw,
                    original_context=selected.original_context.model_dump(mode='json'),
                    original_command=old_command.model_dump(mode='json'), command=command.model_dump(mode='json'),
                    command_query=query.model_dump(mode='json'), transition_sources=deepcopy(selected.transition_sources),
                    unavailable_targets=deepcopy(selected.unavailable_targets), evidence=list(evidence.values()),
                    context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('Transition recovery lacks native absence, fresh command binding and original legal/history authentication')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('GOV-A09', _CODE, '1', frozenset({'dependency_change'}), evaluate)
