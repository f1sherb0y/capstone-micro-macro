"""Rejudge original A06 case/submission readiness without resolving supplement issues."""
from copy import deepcopy
from dataclasses import dataclass

from pydantic import TypeAdapter

from src.actions.contracts.common import ActionContext, EvidenceRecord, Known, ScopeRef, ref_type, walk_references
from src.actions.contracts.government_supplement_objects import (
    GovSupplementCaseView, GovSupplementSubmissionView, GovSupplementClockView, GovSupplementProfileView,
    GovSupplementRuleView, GovSupplementDelayAuthorityView, GovSupplementTriggerView,
    GovSupplementResponseView,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers
from src.coordination.government_supplement_transfer import NEW_CASE_CODE


_CODE = 'government_supplement_case_not_ready'
_WINDOW_CODE = 'government_supplement_response_window_still_open'
_DELAY_BASIS_CODE = 'government_supplement_no_evidenced_delay_rule'
_DELAY_PERMISSION_CODE = 'government_supplement_delay_effect_not_authorized'
_RESPONSE_CODE = 'government_supplement_verify_actual_responses_before_delay'
_REASSESSMENT_CODE = 'government_supplement_requires_formal_reassessment'
_CODES = (_CODE, _WINDOW_CODE, _DELAY_BASIS_CODE, _DELAY_PERMISSION_CODE, _RESPONSE_CODE, _REASSESSMENT_CODE, NEW_CASE_CODE)
_FIELDS = frozenset({'scope', 'case_ref', 'issue_refs', 'original_submission_ref', 'response_refs',
    'current_submission_ref', 'reusable_assessment_refs', 'clock_rule_ref'})
_BASES = (('case_ref', 'RegulatoryCase', GovSupplementCaseView),
    ('original_submission_ref', 'Submission', GovSupplementSubmissionView),
    ('current_submission_ref', 'Submission', GovSupplementSubmissionView),
    ('clock_rule_ref', 'ClockRule', GovSupplementClockView))
_LISTS = {'issue_refs': 'Issue', 'response_refs': 'Response', 'reusable_assessment_refs': 'Assessment'}


@dataclass(frozen=True)
class GovernmentSupplementConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict
    supplement_sources: list[dict] | None = None
    unavailable_targets: list[dict] | None = None
    original_context: ActionContext | None = None
    reassessment: dict | None = None
    transfer: dict | None = None


def government_original_supplement_case_profile(read_current, validate_relation):
    """Actual receipt and case readiness permit fresh scoped supplement judgment."""
    return _original_supplement_source_profile(read_current, validate_relation, _CODE)


def government_original_supplement_window_profile(read_current, validate_relation):
    """The original response window must strictly end before fresh delay judgment."""
    return _original_supplement_source_profile(read_current, validate_relation, _WINDOW_CODE)


def government_original_supplement_delay_basis_profile(read_current, validate_relation):
    """Actual scoped deadline, rule and trigger sources clear only the missing-basis gate."""
    return _original_supplement_source_profile(read_current, validate_relation, _DELAY_BASIS_CODE)


def government_original_supplement_delay_permission_profile(read_current, validate_relation):
    """Both actual rule and independent delay authority must permit fresh judgment."""
    return _original_supplement_source_profile(read_current, validate_relation, _DELAY_PERMISSION_CODE)


def government_original_supplement_response_profile(read_current, validate_relation):
    """Retained actual responses require a separately authorized verification invocation."""
    return _original_supplement_source_profile(read_current, validate_relation, _RESPONSE_CODE)


def government_original_supplement_reassessment_profile(read_current, validate_relation):
    """Actual formal reassessment and a lawful continuing route clear this gate."""
    return _original_supplement_source_profile(read_current, validate_relation, _REASSESSMENT_CODE)


def _read_supplement_delay_authority(read, profile, case, clock, issue_refs, context, organization_id):
    rule = read(profile.delay_rule_ref, GovSupplementRuleView)
    if (rule.organization_id != organization_id or rule.case_ref != case.ref or rule.purpose != 'delay'
            or {ref.key() for ref in rule.issue_refs} != {ref.key() for ref in issue_refs}):
        raise TaskConflict('Government supplement delay rule substitutes original case/issues/legal scope')
    if rule.delay_authority_ref is None or rule.delay_effect is None:
        return rule, None
    authority = read(rule.delay_authority_ref, GovSupplementDelayAuthorityView)
    if (authority.organization_id != organization_id or authority.actor_id != context.actor_id
            or authority.function_ref != context.function_ref or authority.case_ref != case.ref
            or authority.rule_ref != rule.ref or authority.clock_rule_ref != clock.ref
            or authority.next_trigger_ref != profile.next_trigger_ref
            or {ref.key() for ref in authority.issue_refs} != {ref.key() for ref in issue_refs}):
        raise TaskConflict('Government supplement delay authority substitutes original actor/clock/trigger/issues')
    return rule, authority


def _original_supplement_source_profile(read_current, validate_relation, condition_code):
    window_wait = condition_code == _WINDOW_CODE
    delay_basis_wait = condition_code == _DELAY_BASIS_CODE
    permission_wait = condition_code == _DELAY_PERMISSION_CODE
    response_wait = condition_code == _RESPONSE_CODE
    reassessment_wait = condition_code == _REASSESSMENT_CODE
    clock_wait = window_wait or delay_basis_wait
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Government supplement recovery requires actual sources and native history validation')

    def identities(refs):
        keys = {ref.key()[:2] for ref in refs}
        if len(keys) != len(refs):
            raise TaskConflict('Government supplement recovery duplicates a physical source')
        return keys

    def evaluate(check):
        source, waited = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'GOV-A06' or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code != condition_code or check.condition.trigger != 'dependency_change'
                or (not response_wait and not reassessment_wait and tuple(ref.kind for ref in waited) != ('RegulatoryCase',
                    'Rule' if permission_wait else 'ClockRule' if clock_wait else 'Submission'))
                or (reassessment_wait and tuple(ref.kind for ref in waited) != ('RegulatoryCase', 'RevisionBasis', 'Submission'))
                or (response_wait and (len(waited) < 2 or waited[0].kind != 'RegulatoryCase'
                    or any(ref.kind != 'Response' for ref in waited[1:])))
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Government supplement recovery replaces original case/current-submission wait')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, GovernmentSupplementConditionReading)
                or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                or not isinstance(selected.original_action_input, dict) or not isinstance(selected.action_input, dict)):
            raise TaskConflict('Government supplement recovery requires typed original/current sources')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        original_input, action_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
        try:
            if (set(original_input) != _FIELDS or set(action_input) != _FIELDS
                    or task_digest(original_input) != source['input_sha256'] or original_input['scope'] != action_input['scope']
                    or context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract'
                    or context.contract_ref.id != 'GOV-A06' or context.execution_mode != 'llm'
                    or reading._resolver.source_mode != 'formal' or reading.organization_id != source['organization_id']
                    or context.business_time != check.signal.business_time or context.operation_id == source['request_id']):
                raise TaskConflict('Government supplement recovery changes original snapshot/scope/current invocation')
            scope = TypeAdapter(ScopeRef).validate_python(action_input['scope'])
            if not scope_covers(context.scope, scope):
                raise TaskConflict('Government supplement recovery leaves original coverage')
            reading.check_method_context(context, 'GOV-A06')
            versions, proof_rows = [], []

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref or not scope_covers(scope, row.scope):
                    raise TaskConflict('Government supplement recovery lacks exact scoped original/current sources')
                proof_rows.append(row)
                return row

            for raw in (original_input, action_input):
                rows = {field: read(ref_type(kind).model_validate(raw[field]), schema) for field, kind, schema in _BASES}
                case, original, current, clock = (rows[field] for field, _, _ in _BASES)
                profile = read(case.supplement_profile_ref, GovSupplementProfileView)
                if (case.organization_id != source['organization_id'] or profile.organization_id != source['organization_id']
                        or profile.case_ref != case.ref or profile.original_submission_ref != original.ref
                        or profile.current_submission_ref != current.ref or case.current_submission_ref != current.ref
                        or original.ref not in case.linked_submission_refs or current.ref not in case.linked_submission_refs
                        or profile.clock_rule_ref != clock.ref or clock.case_ref != case.ref or clock.procedure_ref != case.procedure_ref):
                    raise TaskConflict('Government supplement recovery substitutes case/submission lineage/profile/clock')
                for submission in (original, current):
                    if (submission.matter_ref != case.matter_ref or submission.procedure_ref != case.procedure_ref
                            or submission.jurisdiction_ref != case.jurisdiction_ref or submission.applicant_id != case.applicant_id
                            or submission.recipient_organization_id != source['organization_id']):
                        raise TaskConflict('Government supplement recovery substitutes original applicant/procedure/agency')
                    identities(submission.component_refs)
                rows['profile'] = profile
                rows['input_lists'] = {field: [ref_type(kind).model_validate(ref) for ref in raw[field]]
                    for field, kind in _LISTS.items()}
                for refs in rows['input_lists'].values():
                    identities(refs)
                    for ref in refs:
                        reading.resolve(ref)
                versions.append(rows)
            old, current = versions
            old_case, case = old['case_ref'], current['case_ref']
            old_submission, submission = old['current_submission_ref'], current['current_submission_ref']
            old_profile, profile = old['profile'], current['profile']
            if condition_code == _CODE and (tuple(waited) != (old_case.ref, old_submission.ref)
                    or old_case.status not in {'closed', 'withdrawn'}
                        and old_submission.status == 'active' and old_submission.receipt_status == 'received'):
                raise TaskConflict('Government supplement recovery differs from original case/receipt readiness gap')
            old_clock, clock = old['clock_rule_ref'], current['clock_rule_ref']
            reassessment_proof = None
            if reassessment_wait:
                from src.coordination.government_supplement_reassessment import read_supplement_reassessment
                reassessment_proof = read_supplement_reassessment(selected=selected, source=source, waited=waited,
                    old=old, current=current, context=context, scope=scope, read=read)
                if reassessment_proof is None:
                    return 'waiting'
            if response_wait:
                original_context = selected.original_context
                if (not isinstance(original_context, ActionContext)
                        or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
                        or tuple(waited) != (old_case.ref, *old['input_lists']['response_refs'])
                        or old_profile.choice != 'process_delay' or profile.choice != 'verify_response'
                        or old_profile.delay_rule_ref is None or old_profile.next_trigger_ref is None
                        or old_clock.deadline is None or old_case.status in {'closed', 'withdrawn'}
                        or old_submission.status != 'active' or old_submission.receipt_status != 'received'
                        or old_clock.deadline.clock_ref != original_context.business_time.clock_ref
                        or original_context.business_time.offset <= old_clock.deadline.offset):
                    raise TaskConflict('Government supplement response recovery replaces original elapsed delay wait or verification route')
                old_rule, old_authority = _read_supplement_delay_authority(read, old_profile, old_case, old_clock,
                    old['input_lists']['issue_refs'], original_context, source['organization_id'])
                if (old_authority is None or not isinstance(old_rule.permitted, Known) or old_rule.permitted.value is not True
                        or not isinstance(old_authority.permitted, Known) or old_authority.permitted.value is not True):
                    raise TaskConflict('Government supplement response wait lacks original independent lawful delay permission')
                if (clock.deadline != old_clock.deadline or context.business_time.clock_ref != old_clock.deadline.clock_ref
                        or context.business_time.offset < original_context.business_time.offset
                        or identities(old['input_lists']['issue_refs']) != identities(current['input_lists']['issue_refs'])):
                    raise TaskConflict('Government supplement response recovery changes original deadline/issues/time')
                response_versions = []
                for version in (old, current):
                    responses = {}
                    events = {}
                    for ref in version['input_lists']['response_refs']:
                        row = read(ref, GovSupplementResponseView)
                        if (row.case_ref != version['case_ref'].ref or row.issue_ref not in version['input_lists']['issue_refs']
                                or row.original_submission_ref != version['original_submission_ref'].ref
                                or row.current_submission_ref != version['current_submission_ref'].ref
                                or row.current_content_sha256 != version['current_submission_ref'].content_sha256):
                            raise TaskConflict('Government supplement response recovery substitutes original issue/submission/content')
                        body = row.model_dump(mode='json', exclude={'ref', 'available_at', 'effective_window', 'evidence_refs'})
                        if row.event_id in events and events[row.event_id] != body:
                            raise TaskConflict('Government supplement response recovery changes duplicate event content')
                        events[row.event_id] = body
                        responses[ref.key()[:2]] = row
                    response_versions.append(responses)
                old_responses, responses = response_versions
                if not any(row.status == 'received' for row in old_responses.values()):
                    raise TaskConflict('Government supplement response wait has no actually received original response')
                for key, previous in old_responses.items():
                    row = responses.get(key)
                    if row is None or previous.event_id != row.event_id:
                        raise TaskConflict('Government supplement response recovery drops original event history')
                    if previous.status == 'received' and (
                            any(getattr(previous, field) != getattr(row, field) for field in (
                                'status', 'current_content_sha256', 'received_at', 'authored_at',
                                'author_actor_id', 'author_organization_id', 'author_action_id'))
                            or any(getattr(previous, field).key()[:2] != getattr(row, field).key()[:2] for field in (
                                'issue_ref', 'author_function_ref', 'author_authority_ref'))
                            or identities(previous.fact_refs) - identities(row.fact_refs)):
                        raise TaskConflict('Government supplement response recovery rewrites a received response')
            if permission_wait:
                original_context = selected.original_context
                if (not isinstance(original_context, ActionContext)
                        or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
                        or old_profile.choice != 'process_delay' or old_profile.delay_rule_ref is None
                        or old_profile.next_trigger_ref is None or old_clock.deadline is None
                        or old_case.status in {'closed', 'withdrawn'} or old_submission.status != 'active'
                        or old_submission.receipt_status != 'received'
                        or old_clock.deadline.clock_ref != original_context.business_time.clock_ref
                        or original_context.business_time.offset <= old_clock.deadline.offset):
                    raise TaskConflict('Government supplement permission recovery differs from original elapsed delay gate')
                old_rule, old_authority = _read_supplement_delay_authority(read, old_profile, old_case, old_clock,
                    old['input_lists']['issue_refs'], original_context, source['organization_id'])
                if (old_authority is None or tuple(waited) != (old_case.ref, old_rule.ref)
                        or not isinstance(old_rule.permitted, Known)
                        or old_rule.permitted.value is True and (
                            not isinstance(old_authority.permitted, Known) or old_authority.permitted.value is not False)):
                    raise TaskConflict('Government supplement permission recovery lacks original explicit refusal')
                if (clock.deadline != old_clock.deadline or context.business_time.clock_ref != old_clock.deadline.clock_ref
                        or identities(old_clock.issue_refs) != identities(clock.issue_refs)
                        or identities(old['input_lists']['issue_refs']) != identities(current['input_lists']['issue_refs'])):
                    raise TaskConflict('Government supplement permission recovery rewrites original deadline/issues')
            if delay_basis_wait:
                if (tuple(waited) != (old_case.ref, old_clock.ref) or old_profile.choice != 'process_delay'
                        or old_case.status in {'closed', 'withdrawn'} or old_submission.status != 'active'
                        or old_submission.receipt_status != 'received'
                        or old_clock.deadline is not None and old_profile.delay_rule_ref is not None
                            and old_profile.next_trigger_ref is not None):
                    raise TaskConflict('Government supplement recovery differs from original missing delay sources')
                if (old_clock.deadline is not None and clock.deadline != old_clock.deadline
                        or identities(old_clock.issue_refs) != identities(clock.issue_refs)
                        or identities(old['input_lists']['issue_refs']) != identities(current['input_lists']['issue_refs'])):
                    raise TaskConflict('Government supplement delay basis changes retained deadline/clock/issues')
            if window_wait:
                original_context = selected.original_context
                old_clock, clock = old['clock_rule_ref'], current['clock_rule_ref']
                if (not isinstance(original_context, ActionContext)
                        or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
                        or tuple(waited) != (old_case.ref, old_clock.ref) or old_profile.choice != 'process_delay'
                        or old_profile.delay_rule_ref is None or old_profile.next_trigger_ref is None
                        or old_case.status in {'closed', 'withdrawn'} or old_submission.status != 'active'
                        or old_submission.receipt_status != 'received' or old_clock.deadline is None
                        or old_clock.deadline.clock_ref != original_context.business_time.clock_ref
                        or original_context.business_time.offset > old_clock.deadline.offset):
                    raise TaskConflict('Government supplement recovery differs from original open response window')
                if (clock.deadline != old_clock.deadline or context.business_time.clock_ref != old_clock.deadline.clock_ref
                        or identities(old_clock.issue_refs) != identities(clock.issue_refs)
                        or identities(old['input_lists']['issue_refs']) != identities(current['input_lists']['issue_refs'])):
                    raise TaskConflict('Government supplement recovery replaces original clock/deadline/issues')
            if (any(old[field].ref.key()[:2] != current[field].ref.key()[:2] for field, _, _ in _BASES)
                    or any(old[field].content_sha256 != current[field].content_sha256
                        or identities(old[field].component_refs) != identities(current[field].component_refs)
                        for field in ('original_submission_ref', 'current_submission_ref'))
                    or old_case.applicant_id != case.applicant_id or old_case.matter_ref != case.matter_ref
                    or old_case.procedure_ref.key()[:2] != case.procedure_ref.key()[:2]
                    or old_case.jurisdiction_ref.key()[:2] != case.jurisdiction_ref.key()[:2]
                    or identities(old_case.linked_submission_refs) - identities(case.linked_submission_refs)
                    or identities(old_case.task_refs) - identities(case.task_refs)
                    or old_profile.ref.key()[:2] != profile.ref.key()[:2]
                    or not response_wait and old_profile.choice != profile.choice
                    or old_profile.authority_ref.key()[:2] != profile.authority_ref.key()[:2]
                    or any(getattr(old_profile, field) is not None and (getattr(profile, field) is None
                        or getattr(old_profile, field).key()[:2] != getattr(profile, field).key()[:2])
                        for field in ('revision_basis_ref', 'delay_rule_ref', 'next_trigger_ref'))
                    or any(identities(getattr(old_profile, field)) - identities(getattr(profile, field))
                        for field in ('issue_refs', 'response_refs', 'assessment_refs'))
                    or any(identities(old['input_lists'][field]) - identities(current['input_lists'][field]) for field in _LISTS)):
                raise TaskConflict('Government supplement recovery rewrites original content/choice/retained history')
            if case.status in {'closed', 'withdrawn'} or submission.status != 'active' or submission.receipt_status != 'received':
                return 'waiting'
            now = context.business_time
            if response_wait:
                if (profile.coverage != 'complete' or profile.as_of != now
                        or {ref.key() for ref in profile.issue_refs} != {ref.key() for ref in current['input_lists']['issue_refs']}
                        or {ref.key() for ref in profile.response_refs} != {ref.key() for ref in current['input_lists']['response_refs']}):
                    return 'waiting'
                for row in responses.values():
                    if (any(point.clock_ref != now.clock_ref for point in (row.authored_at, row.received_at, row.available_at))
                            or row.authored_at.offset > row.received_at.offset or row.received_at.offset > row.available_at.offset):
                        raise TaskConflict('Government supplement response recovery substitutes actual receipt chronology')
                    if row.available_at.offset > now.offset:
                        return 'unavailable'
            if window_wait and now.offset <= old_clock.deadline.offset:
                return 'waiting'
            delay_rows = []
            if permission_wait:
                if now.offset <= old_clock.deadline.offset or profile.delay_rule_ref is None or profile.next_trigger_ref is None:
                    return 'waiting'
                rule, authority = _read_supplement_delay_authority(read, profile, case, clock,
                    current['input_lists']['issue_refs'], context, source['organization_id'])
                if authority is None:
                    return 'waiting'
                if (rule.ref.key()[:2] != old_rule.ref.key()[:2]
                        or authority.ref.key()[:2] != old_authority.ref.key()[:2]
                        or rule.delay_effect != old_rule.delay_effect or authority.actor_id != old_authority.actor_id
                        or authority.function_ref.key()[:2] != old_authority.function_ref.key()[:2]):
                    raise TaskConflict('Government supplement permission recovery replaces original effect/authority')
                if (not isinstance(rule.permitted, Known) or rule.permitted.value is not True
                        or not isinstance(authority.permitted, Known) or authority.permitted.value is not True):
                    return 'waiting'
                delay_rows = [rule, authority]
            if delay_basis_wait:
                if clock.deadline is None or profile.delay_rule_ref is None or profile.next_trigger_ref is None:
                    return 'waiting'
                if clock.deadline.clock_ref != now.clock_ref:
                    raise TaskConflict('Government supplement delay basis replaces original business clock')
                rule, authority = _read_supplement_delay_authority(read, profile, case, clock,
                    current['input_lists']['issue_refs'], context, source['organization_id'])
                if authority is None:
                    return 'waiting'
                trigger = read(profile.next_trigger_ref, GovSupplementTriggerView)
                if (trigger.case_ref != case.ref or trigger.rule_ref != rule.ref
                        or {ref.key() for ref in trigger.issue_refs} != {ref.key() for ref in current['input_lists']['issue_refs']}):
                    raise TaskConflict('Government supplement delay trigger substitutes original case/rule/issues')
                # Permission, expiry and actual received responses are later
                # processor gates; source recovery does not grant a delay effect.
                delay_rows = [rule, trigger, authority]
            current_rows = (case, submission, profile, clock, *delay_rows) if clock_wait or permission_wait else (case, submission, profile)
            if any(row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                    or not row.effective_window.contains(now) for row in current_rows):
                return 'unavailable'
            grant, function = reading.resolve(profile.authority_ref), reading.resolve(context.function_ref)
            if (not isinstance(grant, Authorization) or grant.ref != profile.authority_ref
                    or not isinstance(function, RoleAssignment) or function.function_ref != context.function_ref
                    or function.role != 'Government' or grant.actor_id != context.actor_id
                    or grant.organization_id != source['organization_id'] or grant.function_ref != context.function_ref
                    or 'GOV-A06' not in grant.action_ids or not grant.validity.contains(now)
                    or not any(scope_covers(covered, scope) for covered in grant.scopes)):
                raise TaskConflict('Government supplement recovery lacks actual current agency authority')
            proof_refs = [*grant.basis_refs, *function.basis_refs]
            if reassessment_proof is not None:
                proof_refs.extend(reassessment_proof['proof_refs'])
            proof_refs.extend(ref for row in proof_rows for ref in walk_references(row) if ref.kind == 'Evidence')
            evidence = {}
            for ref in proof_refs:
                row = reading.resolve(ref)
                if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                    raise TaskConflict('Government supplement recovery requires observed receipt/case/history evidence')
                evidence[ref.key()] = row.model_dump(mode='json')
            native = dict(source_identity=deepcopy(source), condition_code=condition_code,
                original_action_input=original_input, action_input=action_input,
                original_case=old_case.model_dump(mode='json'), case=case.model_dump(mode='json'),
                original_submission=old_submission.model_dump(mode='json'), submission=submission.model_dump(mode='json'),
                supplement_sources=deepcopy(selected.supplement_sources), unavailable_targets=deepcopy(selected.unavailable_targets),
                evidence=deepcopy(list(evidence.values())), context=context.model_copy(deep=True), reading=reading)
            if reassessment_proof is not None:
                native.update({key: value for key, value in reassessment_proof.items() if key != 'proof_refs'})
                native.update(original_context=selected.original_context.model_dump(mode='json'))
            if window_wait:
                native.update(original_context=original_context.model_dump(mode='json'),
                    original_clock_rule=old_clock.model_dump(mode='json'), clock_rule=clock.model_dump(mode='json'))
            if delay_basis_wait:
                native.update(original_clock_rule=old_clock.model_dump(mode='json'), clock_rule=clock.model_dump(mode='json'),
                    delay_rule=rule.model_dump(mode='json'), delay_authority=authority.model_dump(mode='json'),
                    next_trigger=trigger.model_dump(mode='json'))
            if permission_wait:
                native.update(original_context=original_context.model_dump(mode='json'),
                    original_clock_rule=old_clock.model_dump(mode='json'), clock_rule=clock.model_dump(mode='json'),
                    original_delay_rule=old_rule.model_dump(mode='json'), delay_rule=rule.model_dump(mode='json'),
                    original_delay_authority=old_authority.model_dump(mode='json'), delay_authority=authority.model_dump(mode='json'))
            if response_wait:
                native.update(original_context=original_context.model_dump(mode='json'),
                    original_profile=old_profile.model_dump(mode='json'), profile=profile.model_dump(mode='json'),
                    original_responses=[row.model_dump(mode='json') for row in old_responses.values()],
                    responses=[row.model_dump(mode='json') for row in responses.values()],
                    original_delay_rule=old_rule.model_dump(mode='json'),
                    original_delay_authority=old_authority.model_dump(mode='json'))
            if validate_relation(**native) is not True:
                raise TaskConflict('Government supplement recovery lacks native receipt/case transition and retained history authentication')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('GOV-A06', condition_code, '1', frozenset({'dependency_change'}), evaluate)
