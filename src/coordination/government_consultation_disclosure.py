"""Recover original A05 case and disclosure gates with retained source identities."""
from copy import deepcopy

from pydantic import TypeAdapter

from src.actions.contracts.common import ActionContext, EvidenceRecord, Known, ScopeRef, ref_type, walk_references
from src.actions.contracts.government_consultation_objects import GovDisclosureAuthorityView
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.government_consultation_conditions import (
    GovernmentConsultationConditionReading, _BASES, _FIELDS, _DISCLOSURE_CODE, _CASE_CODE,
    _APPLICABILITY_CODE, _read_consultation_applicability,
)
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def government_original_consultation_disclosure_profile(read_current, validate_relation):
    """An independently lawful permission change permits a fresh A05 judgment."""
    return _original_consultation_source_profile(read_current, validate_relation, _DISCLOSURE_CODE)


def government_original_consultation_case_profile(read_current, validate_relation):
    """Reopening the original case permits fresh judgment at its downstream gates."""
    return _original_consultation_source_profile(read_current, validate_relation, _CASE_CODE)


def government_original_consultation_applicability_profile(read_current, validate_relation):
    """Only an independently applicable original basis permits initiation recovery."""
    return _original_consultation_source_profile(read_current, validate_relation, _APPLICABILITY_CODE)


def _original_consultation_source_profile(read_current, validate_relation, condition_code):
    case_wait = condition_code == _CASE_CODE
    applicability_wait = condition_code == _APPLICABILITY_CODE
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Consultation disclosure recovery requires actual sources and native validation')

    def identities(refs):
        keys = {ref.key()[:2] for ref in refs}
        if len(keys) != len(refs):
            raise TaskConflict('Consultation disclosure recovery duplicates a physical source')
        return keys

    def same_ref(old, current):
        return (old is None and current is None) or (
            old is not None and current is not None and old.key()[:2] == current.key()[:2])

    def retained_channels(old, current):
        # An inapplicable initiation may legitimately have no channels. Its
        # newly applicable version needs independently authorized channels;
        # native validation authenticates additions while retaining old ones.
        return identities(old) <= identities(current) if applicability_wait else identities(old) == identities(current)

    def evaluate(check):
        source, waited = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'GOV-A05' or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code != condition_code or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in waited) != (('RegulatoryCase', 'ApplicabilityBasis') if applicability_wait
                    else ('RegulatoryCase' if case_wait else 'DisclosurePackage',))
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Consultation disclosure recovery replaces the original package wait or agency')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, GovernmentConsultationConditionReading)
                or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                or not isinstance(selected.original_action_input, dict) or not isinstance(selected.action_input, dict)):
            raise TaskConflict('Consultation disclosure recovery requires typed original/current sources')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        original_input, action_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
        try:
            if (set(original_input) != _FIELDS or set(action_input) != _FIELDS
                    or task_digest(original_input) != source['input_sha256'] or original_input['scope'] != action_input['scope']
                    or context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract'
                    or context.contract_ref.id != 'GOV-A05' or context.execution_mode != 'llm'
                    or reading._resolver.source_mode != 'formal' or reading.organization_id != source['organization_id']
                    or context.business_time != check.signal.business_time or context.operation_id == source['request_id']):
                raise TaskConflict('Consultation disclosure recovery changes the original input/scope/current invocation')
            scope = TypeAdapter(ScopeRef).validate_python(action_input['scope'])
            if not scope_covers(context.scope, scope):
                raise TaskConflict('Consultation disclosure recovery leaves authorized scope')
            reading.check_method_context(context, 'GOV-A05')
            versions, proof_rows, proof_refs = [], [], []

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref or not scope_covers(scope, row.scope):
                    raise TaskConflict('Consultation disclosure recovery lacks exact scoped source versions')
                proof_rows.append(row)
                return row

            for raw in (original_input, action_input):
                rows = {field: read(ref_type(kind).model_validate(raw[field]), schema)
                    for field, kind, schema in _BASES if raw[field] is not None}
                case, rule, package = (rows[field] for field, _, _ in _BASES[:3])
                # The case wait is emitted before submission and disclosure
                # validation. Do not require later permission to reopen it.
                disclosure = None if case_wait else read(rule.disclosure_authority_ref, GovDisclosureAuthorityView)
                if (case.organization_id != source['organization_id'] or rule.organization_id != source['organization_id']
                        or rule.case_ref != case.ref or rule.procedure_ref != case.procedure_ref or package.case_ref != case.ref):
                    raise TaskConflict('Consultation recovery substitutes original agency/case/procedure')
                if not case_wait and (disclosure.organization_id != source['organization_id']
                        or package.submission_ref != case.current_submission_ref or disclosure.case_ref != case.ref
                        or disclosure.rule_ref != rule.ref or disclosure.package_ref != package.ref
                        or disclosure.content_sha256 != package.content_sha256 or package.status != 'authorized'):
                    raise TaskConflict('Consultation disclosure recovery substitutes agency/case/procedure/content')
                rows['disclosure'] = disclosure
                if applicability_wait:
                    if rule.choice != 'initiate' or raw['prior_consultation_ref'] is not None or raw['response_refs']:
                        raise TaskConflict('Consultation applicability recovery replaces original initiation input')
                    rows['applicability'] = _read_consultation_applicability(
                        read, reading, rule, case, scope, source, proof_refs)
                rows['recipients'] = [ref_type('ConsultationRecipient').model_validate(ref) for ref in raw['recipient_refs']]
                rows['responses'] = [ref_type('ConsultationResponse').model_validate(ref) for ref in raw['response_refs']]
                identities(rows['recipients']); identities(rows['responses'])
                versions.append(rows)
            old, current = versions
            old_case, old_rule, old_package = (old[field] for field, _, _ in _BASES[:3])
            case, rule, package = (current[field] for field, _, _ in _BASES[:3])
            old_disclosure, disclosure = old['disclosure'], current['disclosure']
            if case_wait and (old_case.ref != waited[0] or old_case.status not in {'closed', 'withdrawn'}
                    or not old_rule.modeled):
                raise TaskConflict('Consultation case recovery differs from the original closed/withdrawn case wait')
            if condition_code == _DISCLOSURE_CODE and (old_package.ref != waited[0] or old_case.status in {'closed', 'withdrawn'}
                    or not isinstance(old_disclosure.permitted, Known) or old_disclosure.permitted.value is not False):
                raise TaskConflict('Consultation disclosure recovery differs from the original explicit refusal')
            if applicability_wait and (tuple(waited) != (old_case.ref, old['applicability'].ref)
                    or old_case.status in {'closed', 'withdrawn'}
                    or not isinstance(old_disclosure.permitted, Known) or old_disclosure.permitted.value is not True
                    or not isinstance(old['applicability'].applicable, Known)
                    or old['applicability'].applicable.value is not False):
                raise TaskConflict('Consultation applicability recovery differs from original independently inapplicable basis')
            if (any(not same_ref(old[field].ref, current[field].ref) for field, _, _ in _BASES[:3])
                    or not same_ref(old.get('prior_consultation_ref').ref if 'prior_consultation_ref' in old else None,
                        current.get('prior_consultation_ref').ref if 'prior_consultation_ref' in current else None)
                    or old_package.content_sha256 != package.content_sha256
                    or old_package.submission_sha256 != package.submission_sha256
                    or not same_ref(old_package.submission_ref, package.submission_ref)
                    or identities(old_package.disclosed_evidence_refs) != identities(package.disclosed_evidence_refs)
                    or not retained_channels(old_package.allowed_recipient_refs, package.allowed_recipient_refs)
                    or old_case.applicant_id != case.applicant_id or old_case.matter_ref != case.matter_ref
                    or not same_ref(old_case.procedure_ref, case.procedure_ref)
                    or not same_ref(old_case.jurisdiction_ref, case.jurisdiction_ref)
                    or not same_ref(old_case.current_submission_ref, case.current_submission_ref)
                    or identities(old_case.task_refs) - identities(case.task_refs)
                    or identities(old_case.consultation_refs) - identities(case.consultation_refs)
                    or old_rule.choice != rule.choice or old_rule.modeled != rule.modeled
                    or any(not same_ref(getattr(old_rule, field), getattr(rule, field)) for field in (
                        'authority_ref', 'applicability_basis_ref', 'disclosure_authority_ref', 'clock_rule_ref',
                        'analysis_task_ref', 'analysis_result_ref', 'referral_recipient_ref'))
                    or identities(old_rule.question_refs) - identities(rule.question_refs)
                    or not retained_channels(old_rule.recipient_refs, rule.recipient_refs)
                    or not retained_channels(old['recipients'], current['recipients'])
                    or identities(old['responses']) - identities(current['responses'])):
                raise TaskConflict('Consultation recovery replaces original content/choice/channels/history')
            if not case_wait and (not same_ref(old_disclosure.ref, disclosure.ref)
                    or old_disclosure.actor_id != disclosure.actor_id
                    or not same_ref(old_disclosure.function_ref, disclosure.function_ref)):
                raise TaskConflict('Consultation disclosure recovery replaces original content/choice/channels/history')
            if (case.status in {'closed', 'withdrawn'} or not case_wait and (
                    not isinstance(disclosure.permitted, Known) or disclosure.permitted.value is not True)):
                return 'waiting'
            if applicability_wait and (not isinstance(current['applicability'].applicable, Known)
                    or current['applicability'].applicable.value is not True):
                return 'waiting'
            now = context.business_time
            current_rows = (case, rule) if case_wait else (case, rule, package, disclosure)
            if applicability_wait:
                current_rows = (*current_rows, current['applicability'])
            if any(row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                    or not row.effective_window.contains(now) for row in current_rows):
                return 'unavailable'
            if not case_wait and (disclosure.actor_id != context.actor_id or disclosure.function_ref != context.function_ref
                    or identities(current['recipients']) != identities(rule.recipient_refs)
                    or not identities(rule.recipient_refs) <= identities(package.allowed_recipient_refs)
                    or not identities(rule.recipient_refs) <= identities(disclosure.recipient_refs)
                    or not identities(package.disclosed_evidence_refs) <= identities(disclosure.evidence_refs_allowed)):
                raise TaskConflict('Consultation disclosure permission does not cover original actor/content/channels')
            grant, function = reading.resolve(rule.authority_ref), reading.resolve(context.function_ref)
            if (not isinstance(grant, Authorization) or grant.ref != rule.authority_ref
                    or not isinstance(function, RoleAssignment) or function.function_ref != context.function_ref
                    or function.role != 'Government' or grant.actor_id != context.actor_id
                    or grant.organization_id != source['organization_id'] or grant.function_ref != context.function_ref
                    or 'GOV-A05' not in grant.action_ids or not grant.validity.contains(now)
                    or not any(scope_covers(covered, scope) for covered in grant.scopes)):
                raise TaskConflict('Consultation disclosure recovery lacks actual current agency authority')
            proof_refs.extend([*grant.basis_refs, *function.basis_refs])
            proof_refs.extend(ref for row in proof_rows for ref in walk_references(row) if ref.kind == 'Evidence')
            evidence = {}
            for ref in proof_refs:
                row = reading.resolve(ref)
                if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                    raise TaskConflict('Consultation disclosure recovery requires observed permission/history evidence')
                evidence[ref.key()] = row.model_dump(mode='json')
            native = dict(source_identity=deepcopy(source), condition_code=condition_code,
                original_action_input=original_input, action_input=action_input,
                original_package=old_package.model_dump(mode='json'), package=package.model_dump(mode='json'),
                consultation_sources=deepcopy(selected.consultation_sources),
                unavailable_targets=deepcopy(selected.unavailable_targets), evidence=deepcopy(list(evidence.values())),
                context=context.model_copy(deep=True), reading=reading)
            if case_wait:
                native.update(original_case=old_case.model_dump(mode='json'), case=case.model_dump(mode='json'))
            else:
                native.update(original_disclosure=old_disclosure.model_dump(mode='json'),
                    disclosure=disclosure.model_dump(mode='json'))
            if applicability_wait:
                native.update(original_applicability=old['applicability'].model_dump(mode='json'),
                    applicability=current['applicability'].model_dump(mode='json'))
            if validate_relation(**native) is not True:
                raise TaskConflict('Consultation disclosure recovery lacks native permission and retained history authentication')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('GOV-A05', condition_code, '1', frozenset({'dependency_change'}), evaluate)
