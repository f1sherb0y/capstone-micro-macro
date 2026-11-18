"""Only received, verified, unapplied private events wake an A12 lesson wait."""
from src.actions.contracts.common import ActionContext, EvidenceRecord, Known, Reference, StrictRecord
from src.actions.contracts.commercial_continuation_objects import commercial_continuation_types
from src.actions.contracts.supplier_continuation_objects import supplier_continuation_types
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict


def commercial_lesson_profiles(read_current):
    """Host supplies fresh context, authorized view and current original state.

    The event payload never supplies lesson facts. A wake only permits a new
    action: method selection, original author authority, saved exact report and
    actual one-time application still require their normal independent checks.
    """
    if not callable(read_current):
        raise ValueError('A current authorized private observation reader is required')

    def valid_evidence(reading, refs, at, now):
        if at.clock_ref != now.clock_ref or at.offset > now.offset:
            return False
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord) or row.ref != ref:
                raise TaskConflict('Lesson condition lacks exact typed original/current evidence')
            if row.effective_window is not None and not row.effective_window.contains(at):
                return False
        return True

    def profile(action_id, types):
        code = 'commercial_lesson_already_applied'

        def evaluate(check):
            source = check.source['identity']
            if (source['action_id'] != action_id or check.condition.condition_code != code
                    or check.condition.trigger != 'dependency_change'
                    or check.signal.run_id != source['run_id']
                    or check.signal.organization_id != source['organization_id']):
                raise TaskConflict('Lesson condition changes original task, run or recipient')
            old_refs = check.condition.object_refs
            if len(old_refs) != 1 or old_refs[0].kind != 'ContinuationState':
                raise TaskConflict('Lesson wait requires its original state')
            context, reading, ref = read_current(check)
            if (not isinstance(context, ActionContext) or not isinstance(reading, ActionReadView)
                    or not isinstance(ref, Reference)):
                raise TaskConflict('Lesson condition requires a typed authorized reading')
            if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != action_id
                    or context.business_time != check.signal.business_time):
                raise TaskConflict('Lesson condition changes action, run, recipient or current time')
            reading.check_method_context(context, action_id)
            old_ref = old_refs[0]
            if (ref.kind,ref.id) != (old_ref.kind,old_ref.id):
                raise TaskConflict('Lesson condition substitutes another private state')
            try:
                if ref.version == old_ref.version: return 'unavailable'
                original, state = reading.resolve(old_ref), reading.resolve(ref)
                if not isinstance(original,types['ContinuationState']) or not isinstance(state,types['ContinuationState']):
                    raise TaskConflict('Lesson condition lacks original role state schemas')
                if (original.ref != old_ref or state.ref != ref or original.scope != state.scope
                        or state.scope != context.scope or original.organization_id != state.organization_id
                        or state.organization_id != source['organization_id'] or original.run_id != state.run_id
                        or state.run_id != source['run_id']):
                    raise TaskConflict('Lesson condition changes original private run, firm or scope')
                now = context.business_time
                if (state.coverage != 'complete' or state.as_of != now
                        or state.available_at.clock_ref != now.clock_ref or state.available_at.offset > now.offset
                        or state.effective_window.start.clock_ref != now.clock_ref
                        or state.effective_window.end.clock_ref != now.clock_ref
                        or not state.effective_window.contains(now)):
                    return 'unavailable'
                if (original.as_of.clock_ref != now.clock_ref or original.available_at.clock_ref != now.clock_ref
                        or not original.as_of.offset <= original.available_at.offset <= now.offset
                        or not valid_evidence(reading, original.evidence_refs, original.as_of, now)
                        or not valid_evidence(reading, state.evidence_refs, now, now)):
                    return 'unavailable'

                def observations(refs):
                    unique_refs(refs)
                    events, verified = {}, set()
                    for observation_ref in refs:
                        row = reading.resolve(observation_ref)
                        if (not isinstance(row,types['Observation']) or row.ref != observation_ref
                                or row.recipient_organization_id != source['organization_id']):
                            raise TaskConflict('Lesson condition reads another recipient or observation schema')
                        points = (row.observed_at,row.authored_at,row.available_at,row.received_at,
                                  row.effective_window.start,row.effective_window.end)
                        if (any(point.clock_ref != now.clock_ref for point in points)
                                or not row.effective_window.contains(row.authored_at)
                                or not row.observed_at.offset <= row.authored_at.offset <= row.available_at.offset <= row.received_at.offset <= now.offset):
                            raise TaskConflict('Lesson condition changes original event knowledge chronology')
                        original_source = reading.resolve(row.original_source_ref)
                        if not isinstance(original_source,StrictRecord) or content_digest(original_source) != row.source_sha256:
                            raise TaskConflict('Lesson condition changes original outcome source content')
                        if hasattr(original_source,'available_at') and (
                                original_source.available_at.clock_ref != now.clock_ref
                                or original_source.available_at.offset > row.received_at.offset):
                            raise TaskConflict('Lesson event imports a source unavailable when received')
                        if not valid_evidence(reading, row.evidence_refs, row.authored_at, now):
                            raise TaskConflict('Lesson event evidence was not valid at original authorship')
                        identity = (row.source_sha256,row.outcome_code)
                        if row.event_key in events and events[row.event_key] != identity:
                            raise TaskConflict('Lesson repeats an event with a different original outcome')
                        events[row.event_key] = identity
                        if isinstance(row.verified,Known) and row.verified.value is True:
                            verified.add(row.event_key)
                    return events, verified

                previous, _ = observations(original.observation_refs)
                received, verified = observations(state.observation_refs)
                old_applied, _ = observations(original.applied_observation_refs)
                applied, _ = observations(state.applied_observation_refs)
                if (any(received.get(key) != value for key,value in previous.items())
                        or any(applied.get(key) != value for key,value in old_applied.items())
                        or any(received.get(key) != value for key,value in applied.items())):
                    raise TaskConflict('Lesson condition drops or rewrites received/applied event history')
                new_outcomes={received[key] for key in verified}-set(applied.values())
                return 'ready' if new_outcomes else 'waiting'
            finally:
                reading.recheck()

        return ConditionProfile(action_id,code,'2',frozenset({'dependency_change'}),evaluate)

    return [profile('CONTRACTOR-A12',commercial_continuation_types()),
            profile('SUPPLIER-A12',supplier_continuation_types())]
