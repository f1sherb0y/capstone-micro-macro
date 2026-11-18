"""Authenticate actual same-business operating outcome and preserve the original portfolio."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, walk_references
from src.actions.contracts.owner_operating_objects import (
    OwnerOperatingPortfolioView, OwnerOperatingProfileView, OwnerOperatingExecutionView,
    OwnerOperatingProjectView, OwnerOperatingObservationView, OwnerPaymentObligationView,
)
from src.actions.contracts.service_objects import ServiceScopeOrganizationView
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.owner_continuation_terminal import OwnerContinuationTerminalReading
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


EXECUTION_CODE = 'query_original_owner_operating_execution'
_TERMINAL = {'succeeded', 'failed', 'rejected'}
_PROFILE_METADATA = {'ref', 'portfolio_ref', 'available_at', 'effective_window'}
_ROLES = {'OWN': 'Owner', 'BANK': 'Bank', 'CONTRACTOR': 'Contractor', 'SUPPLIER': 'Supplier',
    'QS': 'QS', 'ENGINEER': 'Engineer', 'ARCHITECT': 'Architect', 'GOV': 'Government'}


@dataclass(frozen=True)
class OwnerOperatingTerminalReading(OwnerContinuationTerminalReading):
    """Original exact operating input and an independently selected actual execution version."""


def check_owner_operating_terminal(check, selected, validate_relation, *, terminal=False):
    source = check.source['identity']
    if (terminal is not True or source['action_id'] != 'OWN-A15' or source['role'] != 'Owner'
            or source['purpose'] != 'action' or check.condition.condition_code != EXECUTION_CODE
            or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != ('OwnerOperatingExecution',)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, OwnerOperatingTerminalReading) or not isinstance(selected.reading, ActionReadView)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.execution_ref, Reference) or not callable(validate_relation)):
        raise TaskConflict('Operating terminal archive requires original same-business wait and typed actual query sources')
    context, original_context, reading = selected.context, selected.original_context, selected.reading
    action_input = selected.original_action_input
    raw = action_input.model_dump(mode='json')
    if (task_digest(raw) != source['input_sha256'] or raw != selected.action_input.model_dump(mode='json')
            or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
            or original_context.operation_id != source['request_id'] or context.operation_id != source['request_id']
            or context.run_id != source['run_id'] or context.contract_ref != original_context.contract_ref
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'OWN-A15'
            or context.scope != original_context.scope or context.actor_id != original_context.actor_id
            or context.function_ref != original_context.function_ref or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time
            or context.business_time.clock_ref != original_context.business_time.clock_ref
            or context.business_time.offset < original_context.business_time.offset
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Operating terminal archive replaces original input, private actor or current read authorization')
    reading.check_method_context(context, 'OWN-A15')

    def read(ref, schema, *, original=False, effective=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref:
            raise TaskConflict('Operating terminal archive lacks exact typed original/query sources')
        at = original_context.business_time if original else context.business_time
        if hasattr(row, 'available_at') and (row.available_at.clock_ref != at.clock_ref or row.available_at.offset > at.offset):
            raise TaskConflict('Operating terminal archive injects a source unavailable at original/query time')
        if effective and hasattr(row, 'effective_window') and (row.effective_window.start.clock_ref != at.clock_ref
                or row.effective_window.end.clock_ref != at.clock_ref or not row.effective_window.contains(at)):
            raise TaskConflict('Operating terminal archive substitutes an ineffective original source')
        return row

    def keys(refs):
        values = {ref.key() for ref in refs}
        if len(values) != len(refs):
            raise TaskConflict('Operating terminal archive repeats original source versions')
        return values

    def authorize(ref, actor, function_ref, organization_id, action_id, at, scope):
        grant = read(ref, Authorization)
        function = read(function_ref, RoleAssignment)
        if (grant.organization_id != organization_id or grant.actor_id != actor or grant.function_ref != function_ref
                or action_id not in grant.action_ids or function.role != _ROLES.get(action_id.split('-')[0])
                or grant.validity.start.clock_ref != at.clock_ref or grant.validity.end.clock_ref != at.clock_ref
                or not grant.validity.contains(at) or not any(scope_covers(item, scope) for item in grant.scopes)):
            raise TaskConflict('Operating terminal archive lacks original independent author action authority')
        for evidence_ref in (*grant.basis_refs, *function.basis_refs):
            read(evidence_ref, EvidenceRecord)

    organization = read(action_input.organization_ref, ServiceScopeOrganizationView, original=True, effective=True)
    portfolio = read(action_input.portfolio_ref, OwnerOperatingPortfolioView, original=True, effective=True)
    profile = read(action_input.operating_profile_ref, OwnerOperatingProfileView, original=True, effective=True)
    if (organization.ref.id != source['organization_id'] or portfolio.organization_id != source['organization_id']
            or portfolio.coverage != 'complete' or portfolio.producer != 'core'
            or portfolio.as_of != original_context.business_time or portfolio.scope != original_context.scope
            or profile.organization_id != source['organization_id'] or profile.portfolio_ref != portfolio.ref
            or profile.actor_id != original_context.actor_id or profile.function_ref != original_context.function_ref
            or profile.authority_ref not in original_context.authorization_refs or profile.scope != original_context.scope):
        raise TaskConflict('Operating terminal archive changes original complete core portfolio, profile or private actor')
    authorize(profile.authority_ref, original_context.actor_id, original_context.function_ref,
        source['organization_id'], 'OWN-A15', original_context.business_time, original_context.scope)
    for field in ('obligation_refs', 'observation_refs'):
        if keys(getattr(action_input, field)) != keys(getattr(portfolio, field)):
            raise TaskConflict('Operating terminal archive drops original debts or received observations')
    if not keys(profile.basis_refs) <= keys(portfolio.observation_refs):
        raise TaskConflict('Operating terminal archive invents original private observation basis')
    for ref in portfolio.project_refs:
        project = read(ref, OwnerOperatingProjectView, original=True, effective=True)
        if project.organization_id != source['organization_id'] or not keys(project.obligation_refs) <= keys(portfolio.obligation_refs):
            raise TaskConflict('Operating terminal archive substitutes projects or omits original project debt')
    keys(portfolio.project_refs)
    for ref in portfolio.obligation_refs:
        obligation = read(ref, OwnerPaymentObligationView, original=True, effective=True)
        if (obligation.debtor_id != source['organization_id'] or obligation.as_of != original_context.business_time
                or obligation.due_at.clock_ref != original_context.business_time.clock_ref):
            raise TaskConflict('Operating terminal archive substitutes original whole-organization obligations')
    original_events = set()
    for ref in portfolio.observation_refs:
        observation = read(ref, OwnerOperatingObservationView, original=True)
        if (observation.recipient_organization_id != source['organization_id'] or observation.event_id in original_events
                or any(point.clock_ref != original_context.business_time.clock_ref for point in
                    (observation.observed_at, observation.authored_at, observation.available_at))
                or not observation.observed_at.offset <= observation.authored_at.offset <= observation.available_at.offset
                or not observation.effective_window.contains(observation.authored_at)):
            raise TaskConflict('Operating terminal archive changes original received private observation chronology')
        original_events.add(observation.event_id)
        authorize(observation.author_authority_ref, observation.author_actor_id, observation.author_function_ref,
            observation.author_organization_id, observation.author_action_id, observation.authored_at, observation.scope)
    businesses, first = set(), None
    keys(portfolio.execution_refs)
    for ref in portfolio.execution_refs:
        execution = read(ref, OwnerOperatingExecutionView, original=True)
        if (execution.organization_id != source['organization_id'] or execution.run_id != source['run_id']
                or execution.business_key in businesses):
            raise TaskConflict('Operating terminal archive duplicates or substitutes original run/business history')
        businesses.add(execution.business_key)
        if execution.business_key == profile.business_key:
            first = execution
            break
        if execution.status == 'succeeded':
            for applied_ref in execution.applied_observation_refs:
                observation = read(applied_ref, OwnerOperatingObservationView, original=True)
                if observation.recipient_organization_id != source['organization_id']:
                    raise TaskConflict('Operating terminal archive substitutes original previously applied private outcomes')
    if first is None or tuple(check.condition.object_refs) != (first.ref,):
        raise TaskConflict('Operating terminal archive differs from original first same-business execution gate')
    executed_profile = read(first.profile_ref, OwnerOperatingProfileView, original=True)
    if (executed_profile.organization_id != first.organization_id or executed_profile.scope != first.scope
            or executed_profile.business_key != first.business_key or content_digest(executed_profile) != first.profile_sha256
            or executed_profile.model_dump(exclude=_PROFILE_METADATA) != profile.model_dump(exclude=_PROFILE_METADATA)):
        raise TaskConflict('Operating terminal archive rewrites original executed profile digest/business content')
    if selected.execution_ref.key()[:2] != first.ref.key()[:2]:
        raise TaskConflict('Operating terminal archive replaces original physical execution identity')
    current = read(selected.execution_ref, OwnerOperatingExecutionView)
    if (any(getattr(first, field) != getattr(current, field) for field in
            ('organization_id', 'run_id', 'business_key', 'profile_ref', 'profile_sha256', 'scope'))
            or first.status in _TERMINAL and first.status != current.status
            or not keys(first.applied_observation_refs) <= keys(current.applied_observation_refs)):
        raise TaskConflict('Operating terminal archive changes original operation, actual outcome or applied history')
    now = context.business_time
    if (current.effective_window.start.clock_ref != now.clock_ref or current.effective_window.end.clock_ref != now.clock_ref
            or not current.effective_window.contains(now)):
        return 'unavailable', None
    if current.status not in _TERMINAL or not current.evidence_refs:
        return 'waiting', None
    applied, events, physical = [], set(), set()
    for ref in current.applied_observation_refs:
        observation = read(ref, OwnerOperatingObservationView)
        if (observation.recipient_organization_id != source['organization_id'] or observation.event_id in events
                or ref.key()[:2] in physical):
            raise TaskConflict('Operating terminal archive substitutes or repeats an actually applied private outcome')
        if (any(point.clock_ref != now.clock_ref for point in
                (observation.observed_at, observation.authored_at, observation.available_at))
                or not observation.observed_at.offset <= observation.authored_at.offset <= observation.available_at.offset
                or not observation.effective_window.contains(observation.authored_at)):
            return 'unavailable', None
        events.add(observation.event_id)
        physical.add(ref.key()[:2])
        applied.append(observation.model_dump(mode='json'))
    evidence = []
    for ref in current.evidence_refs:
        row = read(ref, EvidenceRecord)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Operating terminal archive requires actual independently observed execution query evidence')
        if row.effective_window is not None and (row.effective_window.start.clock_ref != now.clock_ref
                or row.effective_window.end.clock_ref != now.clock_ref or not row.effective_window.contains(now)):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    for ref in (*walk_references(action_input), *walk_references(portfolio)):
        reading.resolve(ref)
    resolution = dict(schema_version='owner-operating-execution-resolution.v1', disposition=current.status,
        execution=current.model_dump(mode='json'), original_action_input=raw, action_input=raw,
        original_context=original_context.model_dump(mode='json'), context=context.model_dump(mode='json'),
        sources=reading.evidence(), evidence=evidence, applied_observations=applied)
    if validate_relation(source_identity=deepcopy(source), condition_code=EXECUTION_CODE, terminal_operating_execution=True,
            original_context=original_context.model_copy(deep=True), original_action_input=raw,
            context=context.model_copy(deep=True), resolution=deepcopy(resolution), reading=reading) is not True:
        raise TaskConflict('Operating terminal archive lacks native original portfolio/debt/observation/current authority authentication')
    return 'ready', resolution
