"""Archive observed original monitoring measures without proposing them again."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.bank_monitoring_objects import (
    BankMonitoringArrangementView, BankMonitoringProfileView, BankMonitoringNoticeView,
)
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference
from src.actions.contracts.references import ActionReadView
from src.coordination.bank_debt_conditions import BankDebtConditionReading
from src.coordination.bank_monitoring_conditions import NOTICE_CODE
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


EXISTING_CODE = 'query_existing_original_monitoring_measure_without_duplicate'


@dataclass(frozen=True)
class BankExistingMeasureReading(BankDebtConditionReading):
    queried_notice_refs: tuple[Reference, ...] = ()


def bank_existing_measure_profile():
    def evaluate(check):
        source = check.source['identity']
        if (source['action_id'] != 'BANK-A08' or source['role'] != 'Bank' or source['purpose'] != 'action'
                or check.condition.condition_code != EXISTING_CODE or check.condition.trigger != 'event'
                or not check.condition.object_refs or any(ref.kind != 'CovenantNotice' for ref in check.condition.object_refs)
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Existing monitoring measure wait changes original task, notices or recipient')
        # Existing measures require the explicit actual-observation archive route.
        # A normal wake must never queue the same contractual measure again.
        return 'waiting'

    return ConditionProfile('BANK-A08', EXISTING_CODE, '1', frozenset({'event'}), evaluate)


def check_existing_monitoring_measure(check, selected, validate_relation, *, terminal=False):
    source = check.source['identity']
    if (terminal is not True or source['action_id'] != 'BANK-A08' or source['role'] != 'Bank'
            or source['purpose'] != 'action' or check.condition.condition_code not in {NOTICE_CODE, EXISTING_CODE}
            or check.condition.trigger != 'event' or check.signal.run_id != source['run_id']
            or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, BankExistingMeasureReading) or not isinstance(selected.reading, ActionReadView)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not callable(validate_relation)):
        raise TaskConflict('Existing measure archive requires original wait and explicit actual terminal reading')
    context, original_context, reading = selected.context, selected.original_context, selected.reading
    original_input, action_input = selected.original_action_input, selected.action_input
    raw = original_input.model_dump(mode='json')
    if (task_digest(raw) != source['input_sha256'] or raw != action_input.model_dump(mode='json')
            or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
            or original_context.operation_id != source['request_id'] or context.operation_id != source['request_id']
            or context.run_id != source['run_id'] or context.contract_ref != original_context.contract_ref
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'BANK-A08'
            or context.actor_id != original_context.actor_id or context.function_ref != original_context.function_ref
            or context.scope != original_context.scope or context.business_time != check.signal.business_time
            or context.business_time.clock_ref != original_context.business_time.clock_ref
            or context.business_time.offset < original_context.business_time.offset
            or context.execution_mode != 'llm' or reading._resolver.source_mode != 'formal'
            or reading.organization_id != source['organization_id']):
        raise TaskConflict('Existing measure archive replaces original invocation, firm, scope or input')
    reading.check_method_context(context, 'BANK-A08')
    rows = {}

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref:
            raise TaskConflict('Existing measure archive lacks exact typed original/query sources')
        rows[ref.key()] = row
        return row

    arrangement = read(original_input.arrangement_ref, BankMonitoringArrangementView)
    profile = read(original_input.monitoring_profile_ref, BankMonitoringProfileView)
    if (arrangement.lender_id != source['organization_id'] or arrangement.coverage != 'complete'
            or profile.organization_id != arrangement.lender_id or profile.arrangement_ref != arrangement.ref
            or profile.choice not in {'issue_notice', 'restrict_scope'} or profile.target_covenant_ref is None
            or profile.target_covenant_ref not in original_input.covenant_refs
            or not scope_covers(original_context.scope, profile.affected_scope)
            or profile.available_at.clock_ref != original_context.business_time.clock_ref
            or profile.available_at.offset > original_context.business_time.offset):
        raise TaskConflict('Existing measure archive changes original facility or contractual measure')
    grant = read(profile.authority_ref, Authorization)
    function = read(original_context.function_ref, RoleAssignment)
    if (grant.organization_id != arrangement.lender_id or grant.actor_id != original_context.actor_id
            or grant.function_ref != original_context.function_ref or 'BANK-A08' not in grant.action_ids
            or grant.validity.start.clock_ref != original_context.business_time.clock_ref
            or grant.validity.end.clock_ref != original_context.business_time.clock_ref
            or not grant.validity.contains(original_context.business_time)
            or not any(scope_covers(scope, original_context.scope) for scope in grant.scopes) or function.role != 'Bank'):
        raise TaskConflict('Existing measure archive lacks original Bank action authority')
    for field in ('covenant_refs', 'notice_refs', 'disclosure_refs'):
        refs = getattr(original_input, field)
        if (len({ref.key()[:2] for ref in refs}) != len(refs)
                or {ref.key() for ref in refs} != {ref.key() for ref in getattr(arrangement, field)}):
            raise TaskConflict('Existing measure archive replaces original complete monitoring history')
    original_notices = [read(ref, BankMonitoringNoticeView) for ref in original_input.notice_refs]
    relevant = [notice for notice in original_notices if notice.covenant_ref == profile.target_covenant_ref
        and notice.status == 'active' and notice.affected_scope == profile.affected_scope]
    unsettled = [notice.ref for notice in relevant if notice.delivery != 'verified_served']
    existing = [notice.ref for notice in relevant if notice.choice == profile.choice]
    expected_code, expected_refs = (NOTICE_CODE, unsettled) if unsettled else (EXISTING_CODE, existing)
    if (not existing or check.condition.condition_code != expected_code
            or tuple(check.condition.object_refs) != tuple(expected_refs)):
        raise TaskConflict('Existing measure archive differs from original first notice/duplicate measure gate')
    queries = selected.queried_notice_refs
    if (len({ref.key()[:2] for ref in queries}) != len(queries)
            or {ref.key()[:2] for ref in queries} != {ref.key()[:2] for ref in original_input.notice_refs}):
        raise TaskConflict('Existing measure archive requires actual lookup of all original notice identities')
    current = {ref.key()[:2]: read(ref, BankMonitoringNoticeView) for ref in queries}
    for before in original_notices:
        after = current[before.ref.key()[:2]]
        if (before.lender_id != arrangement.lender_id or before.borrower_id != arrangement.borrower_id
                or before.arrangement_ref != arrangement.ref
                or before.available_at.clock_ref != original_context.business_time.clock_ref
                or before.available_at.offset > original_context.business_time.offset
                or any(getattr(before, field) != getattr(after, field)
                    for field in ('lender_id', 'borrower_id', 'choice', 'affected_scope', 'scope'))
                or any(getattr(before, field).key()[:2] != getattr(after, field).key()[:2]
                    for field in ('arrangement_ref', 'covenant_ref', 'terms_ref'))
                or before.remedy_deadline is not None and before.remedy_deadline != after.remedy_deadline
                or before.delivery == 'verified_served' and (
                    after.delivery != before.delivery or after.served_at != before.served_at)
                or after.available_at.clock_ref != context.business_time.clock_ref
                or after.available_at.offset > context.business_time.offset):
            raise TaskConflict('Existing measure archive rewrites original notice content/service or knowledge time')
    needed = {ref.key()[:2] for ref in (*expected_refs, *existing)}
    evidence = {}
    for key in needed:
        notice = current[key]
        if notice.delivery != 'verified_served':
            return 'waiting', None
        if (notice.served_at is None or notice.served_at.clock_ref != context.business_time.clock_ref
                or notice.served_at.offset > min(context.business_time.offset, notice.available_at.offset)
                or notice.remedy_deadline is not None and (notice.remedy_deadline.clock_ref != notice.served_at.clock_ref
                    or notice.remedy_deadline.offset < notice.served_at.offset)
                or not notice.delivery_evidence_refs):
            return 'unavailable', None
        for ref in notice.delivery_evidence_refs:
            row = read(ref, EvidenceRecord)
            if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                raise TaskConflict('Existing measure archive requires actual observed original delivery evidence')
            evidence[ref.key()] = row.model_dump(mode='json')
    resolution = dict(schema_version='bank-existing-monitoring-measure-resolution.v1',
        disposition='observed_existing_measure', original_action_input=raw, action_input=raw,
        original_context=original_context.model_dump(mode='json'), context=context.model_dump(mode='json'),
        notices=[current[ref.key()[:2]].model_dump(mode='json') for ref in original_input.notice_refs],
        existing_measure_refs=[current[ref.key()[:2]].ref.model_dump(mode='json') for ref in existing],
        sources=[row.model_dump(mode='json') for row in rows.values()], delivery_evidence=list(evidence.values()))
    if validate_relation(source_identity=deepcopy(source), condition_code=expected_code, terminal_existing_measure=True,
            original_context=original_context.model_copy(deep=True), original_action_input=raw,
            context=context.model_copy(deep=True), resolution=deepcopy(resolution), reading=reading) is not True:
        raise TaskConflict('Existing measure archive lacks native original measure/service/current authority authentication')
    return 'ready', resolution
