"""Rejudge an original GOV-A05 analysis task without inventing received opinions."""
from copy import deepcopy
from dataclasses import dataclass

from pydantic import TypeAdapter

from src.actions.contracts.common import ActionContext, EvidenceRecord, Known, ScopeRef, ref_type, walk_references
from src.actions.contracts.government_consultation_objects import (
    GovConsultationCaseView, GovConsultationRuleView, GovDisclosurePackageView,
    GovConsultationView, GovConsultationTaskView, GovConsultationResponseView, GovConsultationApplicabilityView,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


_CODE = 'government_consultation_analysis_task_wait'
_DISCLOSURE_CODE = 'government_consultation_disclosure_not_authorized'
_CASE_CODE = 'government_consultation_case_not_open'
_ACTIVE_CODE = 'government_consultation_not_active'
_OPINION_CODE = 'government_consultation_wait_for_new_actual_opinion'
_NO_OPINION_CODE = 'government_consultation_no_actual_opinion_yet'
_APPLICABILITY_CODE = 'government_consultation_not_applicable_by_original_basis'
_QUERY_CODE = 'government_consultation_query_existing_before_duplicate'
_CODES = (_CODE, _DISCLOSURE_CODE, _CASE_CODE, _ACTIVE_CODE, _OPINION_CODE, _NO_OPINION_CODE, _APPLICABILITY_CODE, _QUERY_CODE)
_FIELDS = frozenset({'scope', 'case_ref', 'consultation_rule_ref', 'disclosure_package_ref',
    'recipient_refs', 'prior_consultation_ref', 'response_refs'})
_BASES = (('case_ref', 'RegulatoryCase', GovConsultationCaseView),
    ('consultation_rule_ref', 'Rule', GovConsultationRuleView),
    ('disclosure_package_ref', 'DisclosurePackage', GovDisclosurePackageView),
    ('prior_consultation_ref', 'Consultation', GovConsultationView))


@dataclass(frozen=True)
class GovernmentConsultationConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict
    consultation_sources: list[dict] | None = None
    unavailable_targets: list[dict] | None = None
    consultation_query: dict | None = None


def government_original_consultation_task_profile(read_current, validate_relation):
    """Task authorization permits new judgment, with disclosure and opinion gates retained."""
    return _original_consultation_history_profile(read_current, validate_relation, _CODE)


def government_original_consultation_active_profile(read_current, validate_relation):
    """Lawful reactivation retains the original consultation and all received history."""
    return _original_consultation_history_profile(read_current, validate_relation, _ACTIVE_CODE)


def government_original_consultation_opinion_profile(read_current, validate_relation):
    """Only an actually received, unregistered opinion permits registration recovery."""
    return _original_consultation_history_profile(read_current, validate_relation, _OPINION_CODE)


def government_original_consultation_no_opinion_profile(read_current, validate_relation):
    """Actual opinions or an independently lawful inapplicability basis clear this gate."""
    return _original_consultation_history_profile(read_current, validate_relation, _NO_OPINION_CODE)


def _read_consultation_applicability(read, reading, rule, case, scope, source, proof_refs):
    applicability = read(rule.applicability_basis_ref, GovConsultationApplicabilityView)
    if (applicability.case_ref != case.ref or applicability.rule_ref != rule.ref
            or applicability.author_organization_id != source['organization_id']
            or applicability.author_action_id != 'GOV-A05'):
        raise TaskConflict('Government consultation applicability substitutes original case/agency/action')
    grant = reading.resolve(applicability.author_authority_ref)
    function = reading.resolve(applicability.author_function_ref)
    if (not isinstance(grant, Authorization) or grant.ref != applicability.author_authority_ref
            or not isinstance(function, RoleAssignment) or function.function_ref != applicability.author_function_ref
            or function.role != 'Government' or grant.actor_id != applicability.author_actor_id
            or grant.organization_id != source['organization_id'] or grant.function_ref != function.function_ref
            or 'GOV-A05' not in grant.action_ids or not grant.validity.contains(applicability.authored_at)
            or not any(scope_covers(covered, scope) for covered in grant.scopes)
            or applicability.authored_at.clock_ref != applicability.available_at.clock_ref
            or applicability.authored_at.offset > applicability.available_at.offset
            or not applicability.effective_window.contains(applicability.authored_at)):
        raise TaskConflict('Government consultation applicability lacks actual independent author authority')
    proof_refs.extend([*grant.basis_refs, *function.basis_refs])
    return applicability


def _original_consultation_history_profile(read_current, validate_relation, condition_code):
    analysis_wait = condition_code == _CODE
    opinion_wait = condition_code == _OPINION_CODE
    no_opinion_wait = condition_code == _NO_OPINION_CODE
    complete_history = analysis_wait or opinion_wait or no_opinion_wait
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Government consultation recovery requires actual sources and independent native history validation')

    def indexed(refs):
        values = {ref.key()[:2]: ref for ref in refs}
        if len(values) != len(refs):
            raise TaskConflict('Government consultation recovery duplicates a physical source')
        return values

    def evaluate(check):
        source, waited = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'GOV-A05' or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code != condition_code or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in waited) != ('Task' if analysis_wait else 'Consultation',)
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Government consultation recovery replaces original analysis-task wait or agency')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, GovernmentConsultationConditionReading) or not isinstance(selected.context, ActionContext)
                or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.original_action_input, dict)
                or not isinstance(selected.action_input, dict)):
            raise TaskConflict('Government consultation recovery requires typed original/current invocation sources')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        original_input, action_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
        try:
            if (set(original_input) != _FIELDS or set(action_input) != _FIELDS
                    or task_digest(original_input) != source['input_sha256'] or original_input['scope'] != action_input['scope']
                    or context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract'
                    or context.contract_ref.id != 'GOV-A05' or context.execution_mode != 'llm'
                    or reading._resolver.source_mode != 'formal' or reading.organization_id != source['organization_id']
                    or context.business_time != check.signal.business_time or context.operation_id == source['request_id']):
                raise TaskConflict('Government consultation recovery changes original snapshot/scope/current invocation')
            scope = TypeAdapter(ScopeRef).validate_python(action_input['scope'])
            if not scope_covers(context.scope, scope):
                raise TaskConflict('Government consultation recovery leaves original authorized scope')
            reading.check_method_context(context, 'GOV-A05')
            versions, proof_rows, proof_refs = [], [], []

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref or not scope_covers(scope, row.scope):
                    raise TaskConflict('Government consultation recovery lacks exact scoped original/current sources')
                proof_rows.append(row)
                return row

            for raw in (original_input, action_input):
                if raw['prior_consultation_ref'] is None:
                    raise TaskConflict('Government analysis recovery cannot create a replacement consultation')
                rows = {field: read(ref_type(kind).model_validate(raw[field]), schema) for field, kind, schema in _BASES}
                case, rule, package, consultation = (rows[field] for field, _, _ in _BASES)
                if rule.choice not in {'analyze', 'register_response'}:
                    raise TaskConflict('Government consultation recovery replaces original continuation choice')
                if analysis_wait and (rule.analysis_task_ref is None or rule.choice != 'analyze'):
                    raise TaskConflict('Government consultation wait lacks original selected analysis task')
                if opinion_wait and rule.choice != 'register_response':
                    raise TaskConflict('Government consultation opinion recovery replaces original registration choice')
                if no_opinion_wait and rule.choice != 'analyze':
                    raise TaskConflict('Government consultation no-opinion recovery replaces original analyze choice')
                applicability = None
                known_inapplicable = False
                if no_opinion_wait:
                    applicability = _read_consultation_applicability(read, reading, rule, case, scope, source, proof_refs)
                    known_inapplicable = isinstance(applicability.applicable, Known) and applicability.applicable.value is False
                # Inactive consultation is emitted before the later task gate;
                # registration may have no analysis task at all.
                task = read(rule.analysis_task_ref, GovConsultationTaskView) if analysis_wait else None
                recipients = indexed([ref_type('ConsultationRecipient').model_validate(ref) for ref in raw['recipient_refs']])
                responses = {key: read(ref, GovConsultationResponseView) for key, ref in indexed(
                    [ref_type('ConsultationResponse').model_validate(ref) for ref in raw['response_refs']]).items()}
                if (case.organization_id != source['organization_id'] or rule.organization_id != source['organization_id']
                        or consultation.organization_id != source['organization_id']
                        or task is not None and task.organization_id != source['organization_id']
                        or rule.case_ref != case.ref or rule.procedure_ref != case.procedure_ref or package.case_ref != case.ref
                        or package.submission_ref != case.current_submission_ref or consultation.ref not in case.consultation_refs
                        or consultation.case_ref != case.ref or consultation.rule_ref != rule.ref
                        or consultation.procedure_ref != case.procedure_ref or consultation.disclosure_package_ref != package.ref
                        or consultation.content_sha256 != package.content_sha256 or consultation.clock_rule_ref != rule.clock_rule_ref
                        or {ref for ref in recipients.values()} != set(consultation.recipient_refs)
                        or complete_history and set(consultation.response_refs) != {row.ref for row in responses.values()}
                        or task is not None and (task.case_ref != case.ref or task.consultation_ref != consultation.ref)):
                    raise TaskConflict('Government consultation recovery borrows another case/procedure/package/channel/history')
                for response in responses.values():
                    if (response.consultation_ref != consultation.ref or response.package_ref != package.ref
                            or response.content_sha256 != package.content_sha256 or response.recipient_ref not in recipients.values()):
                        raise TaskConflict('Government consultation recovery substitutes original response/channel/content')
                indexed(consultation.delivery_refs)
                indexed(consultation.participation_refs)
                if len(set(consultation.registered_event_ids)) != len(consultation.registered_event_ids):
                    raise TaskConflict('Government consultation recovery duplicates registered opinion events')
                events = {}
                actual_opinions = {}
                for response in responses.values():
                    body = response.model_dump(mode='json', exclude={'ref', 'available_at', 'effective_window', 'evidence_refs'})
                    if complete_history and response.event_id in events and events[response.event_id] != body:
                        raise TaskConflict('Government consultation recovery duplicates an event with changed opinion content')
                    events[response.event_id] = body
                    if response.status == 'received' and response.response_kind == 'opinion':
                        actual_opinions.setdefault(response.event_id, response)
                if complete_history and not set(consultation.registered_event_ids) <= events.keys():
                    raise TaskConflict('Government consultation recovery drops an actually registered event source')
                new_opinions = [response for event, response in actual_opinions.items()
                    if event not in consultation.registered_event_ids]
                versions.append(dict(**rows, task=task, recipients=recipients, responses=responses,
                    new_opinions=new_opinions, actual_opinions=list(actual_opinions.values()),
                    applicability=applicability, known_inapplicable=known_inapplicable))
            old, current = versions
            old_task, task = old['task'], current['task']
            old_consultation, consultation = old['prior_consultation_ref'], current['prior_consultation_ref']
            if analysis_wait and (old_task.ref != waited[0] or old_task.status == 'authorized'
                    or old_consultation.status != 'active' or old_consultation.coverage != 'complete'):
                raise TaskConflict('Government consultation recovery differs from original unauthorized analysis task')
            if condition_code == _ACTIVE_CODE and (old_consultation.ref != waited[0] or old_consultation.status != 'withdrawn'):
                raise TaskConflict('Government consultation recovery differs from original inactive consultation wait')
            if opinion_wait and (old_consultation.ref != waited[0] or old_consultation.status != 'active'
                    or old_consultation.coverage != 'complete' or old['new_opinions']):
                raise TaskConflict('Government consultation recovery differs from original absence of new actual opinions')
            if no_opinion_wait and (old_consultation.ref != waited[0] or old_consultation.status != 'active'
                    or old_consultation.coverage != 'complete' or old['actual_opinions'] or old['known_inapplicable']):
                raise TaskConflict('Government consultation recovery differs from original analysis without actual opinions')
            if (any(old[field].ref.key()[:2] != current[field].ref.key()[:2] for field, _, _ in _BASES)
                    or analysis_wait and (old_task.ref.key()[:2] != task.ref.key()[:2]
                        or old_task.function_ref.key()[:2] != task.function_ref.key()[:2])
                    or old['consultation_rule_ref'].choice != current['consultation_rule_ref'].choice
                    or old['consultation_rule_ref'].authority_ref.key()[:2] != current['consultation_rule_ref'].authority_ref.key()[:2]
                    or any(getattr(old['consultation_rule_ref'], field) is not None and (
                        getattr(current['consultation_rule_ref'], field) is None or
                        getattr(old['consultation_rule_ref'], field).key()[:2] !=
                        getattr(current['consultation_rule_ref'], field).key()[:2])
                        for field in ('analysis_task_ref', 'analysis_result_ref', 'referral_recipient_ref'))
                    or any(getattr(old['consultation_rule_ref'], field).key()[:2]
                        != getattr(current['consultation_rule_ref'], field).key()[:2] for field in (
                            'clock_rule_ref', 'applicability_basis_ref', 'disclosure_authority_ref'))
                    or old['disclosure_package_ref'].content_sha256 != current['disclosure_package_ref'].content_sha256
                    or old['disclosure_package_ref'].submission_sha256 != current['disclosure_package_ref'].submission_sha256
                    or old['case_ref'].current_submission_ref.key()[:2] != current['case_ref'].current_submission_ref.key()[:2]
                    or old['case_ref'].applicant_id != current['case_ref'].applicant_id
                    or old['case_ref'].matter_ref != current['case_ref'].matter_ref
                    or old['case_ref'].procedure_ref.key()[:2] != current['case_ref'].procedure_ref.key()[:2]
                    or old['case_ref'].jurisdiction_ref.key()[:2] != current['case_ref'].jurisdiction_ref.key()[:2]
                    or old['recipients'].keys() != current['recipients'].keys()
                    or old['responses'].keys() - current['responses'].keys()
                    or indexed(old_consultation.response_refs).keys() - indexed(consultation.response_refs).keys()
                    or set(old_consultation.registered_event_ids) - set(consultation.registered_event_ids)
                    or indexed(old_consultation.delivery_refs).keys() - indexed(consultation.delivery_refs).keys()
                    or indexed(old_consultation.participation_refs).keys() - indexed(consultation.participation_refs).keys()
                    or indexed(old['case_ref'].consultation_refs).keys() - indexed(current['case_ref'].consultation_refs).keys()):
                raise TaskConflict('Government consultation recovery rewrites disclosed content or retained opinion/delivery/participation history')
            for key, response in old['responses'].items():
                new = current['responses'][key]
                if response.event_id != new.event_id:
                    raise TaskConflict('Government consultation recovery substitutes original response event identity')
                if response.status == 'received' and (any(getattr(response, field) != getattr(new, field) for field in (
                        'received_at', 'response_kind', 'position', 'status', 'authored_at', 'author_actor_id',
                        'author_organization_id', 'author_action_id'))
                        or response.author_function_ref.key()[:2] != new.author_function_ref.key()[:2]
                        or response.author_authority_ref.key()[:2] != new.author_authority_ref.key()[:2]
                        or response.recipient_ref.key()[:2] != new.recipient_ref.key()[:2]
                        or indexed(response.issue_question_refs).keys() != indexed(new.issue_question_refs).keys()):
                    raise TaskConflict('Government consultation recovery rewrites an actually received opinion or receipt')
            now = context.business_time
            if (current['case_ref'].status in {'closed', 'withdrawn'} or consultation.status != 'active'
                    or analysis_wait and task.status != 'authorized'
                    or complete_history and (consultation.coverage != 'complete' or consultation.as_of != now)
                    or opinion_wait and not current['new_opinions']
                    or no_opinion_wait and not current['actual_opinions'] and not current['known_inapplicable']):
                return 'waiting'
            if opinion_wait or no_opinion_wait:
                received_opinions = current['new_opinions'] if opinion_wait else current['actual_opinions']
                for response in received_opinions:
                    if (any(point.clock_ref != now.clock_ref for point in (
                            response.authored_at, response.received_at, response.available_at))
                            or response.authored_at.offset > response.received_at.offset
                            or response.received_at.offset > response.available_at.offset):
                        raise TaskConflict('Government consultation recovery substitutes actual opinion receipt chronology')
                    if response.available_at.offset > now.offset:
                        return 'unavailable'
            current_rows = [current[field] for field, _, _ in _BASES]
            if task is not None:
                current_rows.append(task)
            if no_opinion_wait:
                current_rows.append(current['applicability'])
            if any(row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                    or not row.effective_window.contains(now) for row in current_rows):
                return 'unavailable'
            authorities = [(current['consultation_rule_ref'].authority_ref, context.function_ref)]
            if task is not None:
                authorities.append((task.authority_ref, task.function_ref))
            for authority_ref, function_ref in authorities:
                grant, function = reading.resolve(authority_ref), reading.resolve(function_ref)
                if (not isinstance(grant, Authorization) or grant.ref != authority_ref
                        or not isinstance(function, RoleAssignment) or function.function_ref != function_ref
                        or function.role != 'Government' or grant.actor_id != context.actor_id
                        or grant.organization_id != source['organization_id'] or grant.function_ref != context.function_ref
                        or function_ref != context.function_ref or 'GOV-A05' not in grant.action_ids
                        or not grant.validity.contains(now) or not any(scope_covers(covered, scope) for covered in grant.scopes)):
                    raise TaskConflict('Government consultation recovery lacks current actual analysis/agency authority')
                proof_refs.extend([*grant.basis_refs, *function.basis_refs])
            for row in proof_rows:
                proof_refs.extend(ref for ref in walk_references(row) if ref.kind == 'Evidence')
            evidence = {}
            for ref in proof_refs:
                row = reading.resolve(ref)
                if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                    raise TaskConflict('Government consultation recovery requires actual observed source history evidence')
                evidence[ref.key()] = row.model_dump(mode='json')
            native = dict(source_identity=deepcopy(source), condition_code=condition_code,
                original_action_input=original_input, action_input=action_input,
                original_consultation=old_consultation.model_dump(mode='json'), consultation=consultation.model_dump(mode='json'),
                consultation_sources=deepcopy(selected.consultation_sources), unavailable_targets=deepcopy(selected.unavailable_targets),
                evidence=deepcopy(list(evidence.values())), context=context.model_copy(deep=True), reading=reading)
            if analysis_wait:
                native.update(original_task=old_task.model_dump(mode='json'), task=task.model_dump(mode='json'))
            if opinion_wait:
                native.update(new_opinion_refs=[response.ref.model_dump(mode='json') for response in current['new_opinions']])
            if no_opinion_wait:
                native.update(original_applicability=old['applicability'].model_dump(mode='json'),
                    applicability=current['applicability'].model_dump(mode='json'),
                    actual_opinion_refs=[response.ref.model_dump(mode='json') for response in current['actual_opinions']])
            if validate_relation(**native) is not True:
                raise TaskConflict('Government consultation recovery lacks native analysis-task transition and full received-source lineage')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('GOV-A05', condition_code, '1', frozenset({'dependency_change'}), evaluate)
