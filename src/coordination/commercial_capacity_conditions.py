"""A changed current calendar may wake A12 without reserving any capacity."""
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Known, Reference, walk_references
from src.actions.contracts.commercial_continuation_objects import commercial_continuation_types
from src.actions.contracts.supplier_continuation_objects import supplier_continuation_types
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict
from src.methods.capacity import CapacityInput
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class CapacityConditionReading:
    """Host's exact fresh invocation and profile linking its saved assessment."""
    context: ActionContext
    reading: ActionReadView
    calendar_ref: Reference
    profile_ref: Reference


def commercial_capacity_profiles(read_current):
    """Capacity waits require CapacityConditionReading from the host callback.

    A saved feasible report is a scheduling hint. The successor action still
    recomputes capacity and checks every readiness family, rights and authority.
    Other commercial conditions retain their existing three-item read contract.
    """
    if not callable(read_current):
        raise ValueError('A current authorized calendar reader is required')

    def valid_evidence(reading, refs, at, now):
        if at.clock_ref != now.clock_ref or at.offset > now.offset:
            return False
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord) or row.ref != ref:
                raise TaskConflict('Capacity condition lacks exact typed original/current evidence')
            if row.effective_window is not None and not row.effective_window.contains(at):
                return False
        return True

    def authorize(reading, ref, actor, function_ref, organization, action, at, scope, now):
        grant, function = reading.resolve(ref), reading.resolve(function_ref)
        roles = {'CONTRACTOR': 'Contractor', 'SUPPLIER': 'Supplier', 'OWN': 'Owner', 'BANK': 'Bank',
            'GOV': 'Government', 'ARCHITECT': 'Architect', 'ENGINEER': 'Engineer', 'QS': 'QS'}
        if (not isinstance(grant, Authorization) or grant.ref != ref
                or not isinstance(function, RoleAssignment) or function.function_ref != function_ref
                or grant.actor_id != actor or grant.function_ref != function_ref or grant.organization_id != organization
                or function.role != roles.get(action.split('-')[0]) or action not in grant.action_ids
                or not any(scope_covers(item, scope) for item in grant.scopes)):
            raise TaskConflict('Capacity condition substitutes original independent actor/function/scope authority')
        if at.clock_ref != now.clock_ref or at.offset > now.offset or not grant.validity.contains(at):
            return None
        for basis_ref in [*grant.basis_refs, *function.basis_refs]:
            if basis_ref.kind == 'Evidence':
                if not valid_evidence(reading, [basis_ref], at, now):
                    return None
            else:
                basis = reading.resolve(basis_ref)
                if hasattr(basis, 'available_at') and (basis.available_at.clock_ref != at.clock_ref
                        or basis.available_at.offset > at.offset):
                    return None
        return grant

    def author(reading, row, now):
        if (row.authored_at.clock_ref != now.clock_ref or row.available_at.clock_ref != now.clock_ref
                or not row.authored_at.offset <= row.available_at.offset <= now.offset
                or not row.effective_window.contains(row.authored_at)
                or not valid_evidence(reading, row.evidence_refs, row.authored_at, now)):
            return None
        return authorize(reading, row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_organization_id, row.author_action_id, row.authored_at, row.scope, now)

    def profile(action_id, types):
        code = 'commercial_resume_capacity_unavailable'

        def evaluate(check):
            source = check.source['identity']
            if (source['action_id'] != action_id or check.condition.condition_code != code
                    or check.condition.trigger != 'dependency_change'
                    or check.signal.run_id != source['run_id']
                    or check.signal.organization_id != source['organization_id']):
                raise TaskConflict('Capacity condition changes original task, run or recipient')
            old_refs = check.condition.object_refs
            if len(old_refs) != 1 or old_refs[0].kind != 'ResourceCalendar':
                raise TaskConflict('Capacity wait requires one original resource calendar')
            fresh = read_current(check)
            if not isinstance(fresh, CapacityConditionReading):
                raise TaskConflict('Capacity condition requires an explicit fresh calendar/profile reading')
            context, reading, ref = fresh.context, fresh.reading, fresh.calendar_ref
            if (not isinstance(context, ActionContext) or not isinstance(reading, ActionReadView)
                    or not isinstance(ref, Reference) or not isinstance(fresh.profile_ref, Reference)):
                raise TaskConflict('Capacity condition requires typed current invocation references')
            if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != action_id
                    or context.business_time != check.signal.business_time):
                raise TaskConflict('Capacity condition changes action, run, recipient or current time')
            reading.check_method_context(context, action_id)
            old_ref = old_refs[0]
            if (ref.kind,ref.id) != (old_ref.kind,old_ref.id):
                raise TaskConflict('Capacity condition substitutes another resource calendar')
            try:
                if ref.version == old_ref.version:
                    return 'unavailable'
                original, calendar = reading.resolve(old_ref), reading.resolve(ref)
                proposal = reading.resolve(fresh.profile_ref)
                if (not isinstance(original, types['ResourceCalendar'])
                        or not isinstance(calendar, types['ResourceCalendar'])
                        or not isinstance(proposal, types['ContinuationProfile'])
                        or proposal.ref != fresh.profile_ref):
                    raise TaskConflict('Capacity condition lacks original calendar and current profile schemas')
                if (original.ref != old_ref or calendar.ref != ref
                        or original.organization_id != calendar.organization_id or original.scope != calendar.scope
                        or calendar.organization_id != source['organization_id']
                        or not scope_covers(context.scope, calendar.scope)
                        or proposal.organization_id != source['organization_id']
                        or proposal.choice != 'resume' or proposal.scope != context.scope
                        or proposal.actor_id != context.actor_id or proposal.function_ref != context.function_ref
                        or proposal.authority_ref not in context.authorization_refs):
                    raise TaskConflict('Capacity condition substitutes original firm, scope or current actor')
                state = reading.resolve(proposal.state_ref)
                if (not isinstance(state, types['ContinuationState']) or state.ref != proposal.state_ref
                        or state.organization_id != source['organization_id'] or state.run_id != source['run_id']
                        or state.scope != context.scope or state.resource_calendar_ref != ref):
                    raise TaskConflict('Capacity condition changes current state/calendar identity')
                now = context.business_time
                if state.coverage != 'complete' or calendar.coverage != 'complete' or state.as_of != now or calendar.as_of != now:
                    return 'unavailable'
                for row in (calendar,proposal,state):
                    if hasattr(row,'author_organization_id') and row.author_organization_id != source['organization_id']:
                        raise TaskConflict('Capacity condition substitutes the original firm author')
                    if (row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                            or row.effective_window.start.clock_ref != now.clock_ref
                            or row.effective_window.end.clock_ref != now.clock_ref
                            or not row.effective_window.contains(now)):
                        return 'unavailable'
                if (author(reading, calendar, now) is None or author(reading, proposal, now) is None
                        or not valid_evidence(reading, state.evidence_refs, now, now)
                        or authorize(reading, proposal.authority_ref, context.actor_id, context.function_ref,
                            source['organization_id'], action_id, now, context.scope, now) is None):
                    return 'unavailable'
                resource_ids = [row.resource_ref.id for row in calendar.resources]
                if (len(set(resource_ids)) != len(resource_ids) or set(resource_ids) != set(calendar.actual_resource_keys)
                        or len(set(calendar.actual_resource_keys.values())) != len(resource_ids)):
                    raise TaskConflict('Capacity calendar duplicates or substitutes physical resources')
                unique_refs(state.commitment_refs)
                unique_refs(proposal.retain_resource_refs)
                unique_refs(calendar.existing_work_commitment_refs)
                retained = {r.key() for r in proposal.retain_resource_refs}
                existing = {r.key() for r in calendar.existing_work_commitment_refs}
                if not existing <= retained:
                    raise TaskConflict('Capacity calendar releases resources needed for existing work')
                held = set()
                for commitment_ref in state.commitment_refs:
                    commitment = reading.resolve(commitment_ref)
                    if (not isinstance(commitment, types['ResourceCommitment']) or commitment.as_of != now
                            or commitment.ref != commitment_ref or commitment.organization_id != source['organization_id']
                            or commitment.available_at.clock_ref != now.clock_ref or commitment.available_at.offset > now.offset
                            or not commitment.effective_window.contains(now)
                            or not valid_evidence(reading, commitment.evidence_refs, now, now)):
                        return 'unavailable'
                    if commitment.status == 'unknown': return 'waiting'
                    if commitment.status == 'held':
                        held.add(commitment.ref.key())
                        if not any(row.commitment_ref == commitment.ref and row.resource_ref == commitment.resource_ref
                                and row.quantity == commitment.quantity and row.window == commitment.window
                                for row in calendar.commitments):
                            raise TaskConflict('Capacity calendar omits actual original occupied resources')
                if not existing <= held: return 'waiting'
                for resource in calendar.resources:
                    if not valid_evidence(reading, [resource.total.basis_ref], now, now):
                        return 'unavailable'
                if not calendar.authorized_new_demands:
                    return 'ready' if existing else 'unavailable'
                for demand in calendar.authorized_new_demands:
                    if (demand.window.start.clock_ref != now.clock_ref or demand.window.end.clock_ref != now.clock_ref
                            or demand.window.start.offset < now.offset
                            or demand.window.end.offset <= demand.window.start.offset
                            or not valid_evidence(reading, demand.basis_refs, now, now)):
                        return 'unavailable'
                unique_refs(proposal.readiness_refs)
                verifications = [reading.resolve(r) for r in proposal.readiness_refs]
                resource_checks = [r for r in verifications if isinstance(r,types['Verification']) and r.family == 'resources']
                if len(resource_checks) != 1: return 'unavailable'
                verification = resource_checks[0]
                if (not isinstance(verification.supported,Known) or verification.supported.value is not True
                        or not isinstance(verification.ready,Known) or verification.ready.value is not True):
                    return 'waiting'
                if (verification.organization_id != source['organization_id'] or verification.state_ref != state.ref
                        or verification.state_sha256 != content_digest(state) or verification.as_of != now
                        or verification.capacity_assessment_ref is None):
                    return 'unavailable'
                if (verification.ref not in proposal.readiness_refs
                        or not scope_covers(context.scope, verification.scope)
                        or verification.available_at.clock_ref != now.clock_ref or verification.available_at.offset > now.offset
                        or not verification.effective_window.contains(now)
                        or verification.authored_at.clock_ref != now.clock_ref
                        or verification.authored_at.offset < state.available_at.offset
                        or author(reading, verification, now) is None):
                    return 'unavailable'
                saved = reading.resolve(verification.capacity_assessment_ref)
                if not isinstance(saved,types['ContinuationCapacityAssessment']) or saved.ref != verification.capacity_assessment_ref:
                    raise TaskConflict('Capacity condition lacks its original saved assessment schema')
                data = CapacityInput(clock_ref=now.clock_ref,resources=calendar.resources,commitments=calendar.commitments,
                    demands=calendar.authorized_new_demands,source_refs=[state.ref,calendar.ref,*state.commitment_refs])
                if (saved.organization_id != source['organization_id'] or saved.author_organization_id != source['organization_id']
                        or saved.state_ref != state.ref
                        or not scope_covers(context.scope, saved.scope)
                        or saved.data != data or saved.input_sha256 != content_digest(data)):
                    raise TaskConflict('Capacity assessment substitutes current calendar, occupancy or authorized demand')
                if (saved.executed_at.clock_ref != now.clock_ref or saved.authored_at.clock_ref != now.clock_ref
                        or saved.available_at.clock_ref != now.clock_ref or saved.available_at.offset > now.offset
                        or saved.executed_at.offset < max(calendar.available_at.offset,state.available_at.offset)
                        or saved.executed_at.offset > saved.authored_at.offset
                        or saved.authored_at.offset > saved.available_at.offset):
                    return 'unavailable'
                if (saved.effective_window.start.clock_ref != now.clock_ref
                        or saved.effective_window.end.clock_ref != now.clock_ref
                        or not saved.effective_window.contains(now)):
                    return 'unavailable'
                saved_authority = author(reading, saved, now)
                if saved_authority is None:
                    return 'unavailable'
                if not {ref.key() for ref in data.source_refs} <= {ref.key() for ref in saved_authority.readable_refs}:
                    raise TaskConflict('Saved capacity author lacked original method source read rights')
                for source_ref in data.source_refs:
                    original_source = reading.resolve(source_ref)
                    if hasattr(original_source, 'available_at') and (original_source.available_at.clock_ref != now.clock_ref
                            or original_source.available_at.offset > saved.executed_at.offset):
                        return 'unavailable'
                method_basis = [ref for ref in walk_references(data) if ref.kind == 'Evidence']
                if not valid_evidence(reading, method_basis, saved.executed_at, now):
                    return 'unavailable'
                if saved.status != 'ok' or saved.report is None: return 'unavailable'
                return 'ready' if saved.report.feasible else 'waiting'
            finally:
                reading.recheck()

        return ConditionProfile(action_id,code,'2',frozenset({'dependency_change'}),evaluate)

    return [profile('CONTRACTOR-A12',commercial_continuation_types()),
            profile('SUPPLIER-A12',supplier_continuation_types())]
