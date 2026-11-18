"""Query actual original notices before independent contractual Bank measures."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.bank_monitoring_objects import (
    BankMonitoringArrangementView, BankMonitoringProfileView, BankMonitoringNoticeView,
)
from src.actions.contracts.common import ActionContext, EvidenceRecord, walk_references
from src.actions.contracts.references import ActionReadView
from src.actions.roles.bank_monitoring import monitor_arrangement
from src.coordination.bank_debt_conditions import BankDebtConditionReading
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest


NOTICE_CODE = 'query_original_notice_delivery_before_new_measure'


@dataclass(frozen=True)
class BankMonitoringConditionReading(BankDebtConditionReading):
    """Original and current complete monitoring inputs in one authorized read point."""


def bank_original_notice_delivery_profile(read_current, validate_relation):
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Notice recovery requires actual guarded reading and native delivery authentication')

    def evaluate(check):
        source = check.source['identity']
        waited = check.condition.object_refs
        if (source['action_id'] != 'BANK-A08' or source['role'] != 'Bank' or source['purpose'] != 'action'
                or check.condition.condition_code != NOTICE_CODE or check.condition.trigger != 'event'
                or not waited or any(ref.kind != 'CovenantNotice' for ref in waited)
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Notice recovery changes original task, recipient or explicit notice wait')
        selected = read_current(deepcopy(check))
        if not isinstance(selected, BankMonitoringConditionReading) or not isinstance(selected.reading, ActionReadView):
            raise TaskConflict('Notice recovery requires typed actual original/current monitoring sources')
        context, reading, original_context = selected.context, selected.reading, selected.original_context
        old_input, action_input = selected.original_action_input, selected.action_input
        if (not isinstance(context, ActionContext) or not isinstance(original_context, ActionContext)
                or task_digest(old_input.model_dump(mode='json')) != source['input_sha256']
                or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
                or original_context.operation_id != source['request_id']
                or context.run_id != source['run_id'] or context.contract_ref != original_context.contract_ref
                or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'BANK-A08'
                or context.scope != original_context.scope or context.business_time != check.signal.business_time
                or context.business_time.clock_ref != original_context.business_time.clock_ref
                or context.business_time.offset < original_context.business_time.offset
                or context.operation_id == source['request_id'] or context.execution_mode != 'llm'
                or reading._resolver.source_mode != 'formal' or reading.organization_id != source['organization_id']
                or action_input.arrangement_ref.key()[:2] != old_input.arrangement_ref.key()[:2]):
            raise TaskConflict('Notice recovery replaces original snapshot, facility, scope or current invocation')
        reading.check_method_context(context, 'BANK-A08')
        try:
            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref:
                    raise TaskConflict('Notice recovery lacks exact typed original/current sources')
                return row

            old = read(old_input.arrangement_ref, BankMonitoringArrangementView)
            current = read(action_input.arrangement_ref, BankMonitoringArrangementView)
            old_profile = read(old_input.monitoring_profile_ref, BankMonitoringProfileView)
            profile = read(action_input.monitoring_profile_ref, BankMonitoringProfileView)
            if (old.lender_id != source['organization_id'] or current.lender_id != old.lender_id
                    or current.borrower_id != old.borrower_id or current.scope != old.scope
                    or current.terms_ref.key()[:2] != old.terms_ref.key()[:2]
                    or old.coverage != 'complete' or current.coverage != 'complete'
                    or old_profile.organization_id != old.lender_id or profile.organization_id != old.lender_id
                    or old_profile.arrangement_ref != old.ref or profile.arrangement_ref != current.ref
                    or old_profile.choice not in {'issue_notice', 'restrict_scope', 'release_restriction'}
                    or profile.choice != old_profile.choice or profile.affected_scope != old_profile.affected_scope
                    or old_profile.target_covenant_ref is None or profile.target_covenant_ref is None
                    or profile.target_covenant_ref.key()[:2] != old_profile.target_covenant_ref.key()[:2]):
                raise TaskConflict('Notice recovery changes original parties, terms, intended measure or affected scope')
            for field in ('covenant_refs', 'notice_refs', 'disclosure_refs'):
                before_refs, after_refs = getattr(old_input, field), getattr(action_input, field)
                before, after = {ref.key()[:2] for ref in before_refs}, {ref.key()[:2] for ref in after_refs}
                if (len(before) != len(before_refs) or len(after) != len(after_refs) or not before <= after
                        or {ref.key() for ref in before_refs} != {ref.key() for ref in getattr(old, field)}
                        or {ref.key() for ref in after_refs} != {ref.key() for ref in getattr(current, field)}):
                    raise TaskConflict('Notice recovery drops or duplicates original covenant/report/notice history')
            old_notices = [read(ref, BankMonitoringNoticeView) for ref in old_input.notice_refs]
            notices = {ref.key()[:2]: read(ref, BankMonitoringNoticeView) for ref in action_input.notice_refs}
            original_unsettled = [notice.ref for notice in old_notices
                if notice.covenant_ref == old_profile.target_covenant_ref and notice.status == 'active'
                and notice.affected_scope == old_profile.affected_scope and notice.delivery != 'verified_served']
            if tuple(waited) != tuple(original_unsettled):
                raise TaskConflict('Notice recovery differs from the original complete unsettled-notice gate')
            for before in old_notices:
                after = notices[before.ref.key()[:2]]
                if (any(getattr(before, field) != getattr(after, field)
                        for field in ('lender_id', 'borrower_id', 'choice', 'affected_scope', 'scope'))
                        or any(getattr(before, field).key()[:2] != getattr(after, field).key()[:2]
                            for field in ('arrangement_ref', 'covenant_ref', 'terms_ref'))
                        or before.remedy_deadline is not None and before.remedy_deadline != after.remedy_deadline
                        or before.delivery == 'verified_served' and (
                            after.delivery != before.delivery or after.served_at != before.served_at)):
                    raise TaskConflict('Notice recovery rewrites original measure, service identity or remedy deadline')
            observed = []
            for ref in waited:
                notice = notices[ref.key()[:2]]
                now = context.business_time
                if notice.available_at.clock_ref != now.clock_ref or notice.available_at.offset > now.offset:
                    return 'unavailable'
                if notice.delivery != 'verified_served':
                    return 'waiting'
                if (notice.served_at is None or notice.served_at.clock_ref != now.clock_ref
                        or notice.served_at.offset > min(now.offset, notice.available_at.offset)
                        or not notice.delivery_evidence_refs):
                    return 'unavailable'
                for evidence_ref in notice.delivery_evidence_refs:
                    evidence = reading.resolve(evidence_ref)
                    if not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic' or evidence.basis_kind != 'observed':
                        raise TaskConflict('Notice recovery requires actual independently observed delivery evidence')
                    observed.append(evidence.model_dump(mode='json'))
            for ref in (*walk_references(old_input), *walk_references(action_input)):
                reading.resolve(ref)
            # This processor proposes a measure; it cannot serve a notice,
            # impose a restriction or replace contractual facts with risk scores.
            result = monitor_arrangement(context, action_input, reading)
            if result['kind'] != 'completed':
                return 'unavailable' if result['kind'] == 'unsupported' else 'waiting'
            if validate_relation(source_identity=deepcopy(source), condition_code=NOTICE_CODE,
                    original_context=original_context.model_copy(deep=True), original_action_input=old_input.model_dump(mode='json'),
                    context=context.model_copy(deep=True), action_input=action_input.model_dump(mode='json'),
                    notices=[notices[ref.key()[:2]].model_dump(mode='json') for ref in waited],
                    delivery_evidence=observed, proposal=deepcopy(result['payload']), reading=reading) is not True:
                raise TaskConflict('Notice recovery lacks native original notice/service/covenant history authentication')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('BANK-A08', NOTICE_CODE, '1', frozenset({'event'}), evaluate)
