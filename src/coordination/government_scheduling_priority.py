"""Read independently authorized priority exceptions; never change queue order."""
from src.actions.contracts.common import Known
from src.actions.contracts.government_scheduling_objects import GovSchedulingPriorityView, GovPriorityAuthorityView
from src.coordination.tasks import TaskConflict
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def government_scheduling_priority_history(*, original, current, waited, context, read, resolve, proof_refs):
    histories, priorities, permissions, selected_entries = [], [], [], []
    for version, time, is_current in ((original, original['queue_ref'].as_of, False),
            (current, context.business_time, True)):
        case, queue, rule, profile = (version[field] for field in ('case_ref', 'queue_ref', 'rule', 'ordering_profile_ref'))
        if (profile.choice != 'reprioritize' or profile.priority_basis_ref is None
                or not rule.allows_priority_exception):
            raise TaskConflict('Government priority recovery lacks original independent exception choice/rule')
        if case.status in {'closed', 'withdrawn'} or queue.coverage != 'complete' or queue.as_of != time:
            if is_current:
                return 'waiting', None
            raise TaskConflict('Government priority wait lacks its original open case and complete lawful queue')
        entries = sorted(queue.entries, key=lambda row: (row.entered_at.offset, repr(row.case_ref.key())))
        if (len({row.case_ref.key()[:2] for row in entries}) != len(entries)
                or any(row.entered_at.clock_ref != time.clock_ref or row.entered_at.offset > time.offset for row in entries)):
            raise TaskConflict('Government priority recovery duplicates cases or rewrites received queue time/clock')
        selected = next((row for row in entries if row.case_ref == case.ref), None)
        if selected is None or selected.status not in {'ready', 'assigned'}:
            if is_current:
                return 'waiting', None
            raise TaskConflict('Government priority wait lacks an original input-ready queue case')
        selected_entries.append(selected)
        earlier = [row.case_ref for row in entries if row.status == 'ready'
            and row.entered_at.offset < selected.entered_at.offset]
        priority = read(profile.priority_basis_ref, GovSchedulingPriorityView)
        if (priority.organization_id != case.organization_id or priority.case_ref != case.ref
                or priority.queue_ref != queue.ref or priority.ordering_rule_ref != rule.ref
                or len({ref.key()[:2] for ref in priority.bypassed_case_refs}) != len(priority.bypassed_case_refs)
                or {ref.key() for ref in priority.bypassed_case_refs} != {ref.key() for ref in earlier}):
            raise TaskConflict('Government priority recovery substitutes original case/queue/rule or bypassed cases')
        permission = read(priority.priority_authority_ref, GovPriorityAuthorityView)
        grant, function = resolve(priority.authority_ref), None
        if isinstance(grant, Authorization):
            function = resolve(grant.function_ref)
        if (not isinstance(grant, Authorization) or grant.ref != priority.authority_ref
                or not isinstance(function, RoleAssignment) or function.function_ref != grant.function_ref
                or function.role != 'Government' or grant.organization_id != case.organization_id
                or permission.organization_id != case.organization_id or permission.actor_id != grant.actor_id
                or permission.function_ref != grant.function_ref or permission.case_ref != case.ref
                or permission.queue_ref != queue.ref or permission.ordering_rule_ref != rule.ref):
            raise TaskConflict('Government priority recovery borrows another actor/function independent legal authority')
        proof_refs.extend([*grant.basis_refs, *function.basis_refs])
        if ('GOV-A03' not in grant.action_ids or not grant.validity.contains(time)
                or not any(scope_covers(scope, context.scope) for scope in grant.scopes)):
            if is_current:
                return 'waiting', None
            raise TaskConflict('Government priority wait lacks its original agency action/scope authority')
        if is_current and (grant.actor_id != context.actor_id or grant.function_ref != context.function_ref):
            raise TaskConflict('Government priority recovery replaces current actual actor/function')
        if (priority.available_at.clock_ref != time.clock_ref or priority.available_at.offset > time.offset
                or permission.available_at.clock_ref != time.clock_ref or permission.available_at.offset > time.offset
                or not priority.effective_window.contains(time) or not permission.effective_window.contains(time)):
            if is_current:
                return 'unavailable', None
            raise TaskConflict('Government priority wait lacks its original received effective legal sources')
        priorities.append(priority)
        permissions.append(permission)
        histories.append(dict(priority=priority.model_dump(mode='json'), permission=permission.model_dump(mode='json'),
            agency_authority=grant.model_dump(mode='json'), agency_function=function.model_dump(mode='json'),
            selected_entry=selected.model_dump(mode='json'), earlier_case_refs=[ref.model_dump(mode='json') for ref in earlier]))
    if priorities[0].ref != waited[1] or waited[0] != original['case_ref'].ref:
        raise TaskConflict('Government priority wait differs from its exact original case/priority sources')
    if (priorities[0].ref.key()[:2] != priorities[1].ref.key()[:2]
            or permissions[0].ref.key()[:2] != permissions[1].ref.key()[:2]
            or selected_entries[0].entered_at != selected_entries[1].entered_at):
        raise TaskConflict('Government priority recovery replaces original legal source identity or queue receipt time')
    if not isinstance(permissions[0].permitted, Known) or permissions[0].permitted.value is not False:
        raise TaskConflict('Government priority recovery does not match an original known refused exception')
    if not isinstance(permissions[1].permitted, Known) or permissions[1].permitted.value is not True:
        return 'waiting', None
    return 'ready', dict(original=histories[0], current=histories[1])
