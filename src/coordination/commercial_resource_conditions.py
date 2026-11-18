"""Wake A12 resource waits only from current original commitment facts."""
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.commercial_continuation_objects import CommercialCommitmentView
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict


def commercial_resource_profiles(read_current):
    """Host supplies a fresh context, authorized read view and commitment ref.

    Resolved occupancy allows a new decision, never a resource release. A held
    production line still requires all A12 readiness and shared-calendar checks
    during the successor action. Elapsed time alone cannot clear occupancy.
    """
    if not callable(read_current):
        raise ValueError('A current authorized commitment reader is required')

    def profile(action_id, code, ready_statuses):
        def evaluate(check):
            source = check.source['identity']
            if (source['action_id'] != action_id or check.condition.condition_code != code
                    or check.condition.trigger != 'dependency_change'
                    or check.signal.run_id != source['run_id']
                    or check.signal.organization_id != source['organization_id']):
                raise TaskConflict('Resource condition changes original task, run or recipient')
            old_refs = check.condition.object_refs
            if len(old_refs) != 1 or old_refs[0].kind != 'ResourceCommitment':
                raise TaskConflict('Resource wait requires one original commitment')
            context, reading, ref = read_current(check)
            if (not isinstance(context, ActionContext) or not isinstance(reading, ActionReadView)
                    or not isinstance(ref, Reference)):
                raise TaskConflict('Resource condition requires a typed current authorized reading')
            if (context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != action_id
                    or context.business_time != check.signal.business_time):
                raise TaskConflict('Resource condition changes action, run, recipient or current time')
            reading.check_method_context(context, action_id)
            old_ref = old_refs[0]
            if (ref.kind, ref.id) != (old_ref.kind, old_ref.id):
                raise TaskConflict('Resource condition substitutes another physical commitment')
            try:
                if ref.version == old_ref.version:
                    return 'unavailable'
                original, current = reading.resolve(old_ref), reading.resolve(ref)
                if not isinstance(original, CommercialCommitmentView) or not isinstance(current, CommercialCommitmentView):
                    raise TaskConflict('Resource condition lacks original commercial commitment schema')
                if original.ref != old_ref or current.ref != ref:
                    raise TaskConflict('Resource condition projection reference mismatch')
                fields = ('organization_id','resource_ref','quantity','window',
                          'physical_commitment_key','release_rule_ref','scope')
                if (current.organization_id != source['organization_id']
                        or any(getattr(original, field) != getattr(current, field) for field in fields)):
                    raise TaskConflict('Resource condition changes original physical occupancy or release identity')
                now = context.business_time
                if (current.as_of != now or current.available_at.clock_ref != now.clock_ref
                        or current.available_at.offset > now.offset
                        or current.effective_window.start.clock_ref != now.clock_ref
                        or current.effective_window.end.clock_ref != now.clock_ref
                        or not current.effective_window.contains(now)
                        or current.window.start.clock_ref != now.clock_ref
                        or current.window.end.clock_ref != now.clock_ref):
                    return 'unavailable'
                observed = False
                for evidence_ref in current.evidence_refs:
                    evidence = reading.resolve(evidence_ref)
                    if not isinstance(evidence, EvidenceRecord):
                        raise TaskConflict('Resource occupancy lacks typed evidence')
                    if evidence.effective_window is not None and (
                            evidence.effective_window.start.clock_ref != now.clock_ref
                            or evidence.effective_window.end.clock_ref != now.clock_ref
                            or not evidence.effective_window.contains(now)):
                        return 'unavailable'
                    observed = observed or evidence.basis_kind == 'observed'
                if not observed:
                    return 'unavailable'
                if current.status not in ready_statuses:
                    return 'waiting'
                return 'ready'
            finally:
                reading.recheck()

        return ConditionProfile(action_id, code, '1', frozenset({'dependency_change'}), evaluate)

    return [
        *[profile(action_id, 'query_original_commercial_resource_commitment', {'held','released','consumed'})
          for action_id in ('CONTRACTOR-A12','SUPPLIER-A12')],
        profile('SUPPLIER-A12', 'supplier_scope_has_actual_occupied_resources', {'released','consumed'}),
        profile('SUPPLIER-A12', 'supplier_resume_original_production_line_unavailable', {'held'}),
    ]
