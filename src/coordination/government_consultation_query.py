"""Use an observed original-consultation lookup before continuing an initiation wait."""
from copy import deepcopy
from typing import Literal

from pydantic import Field, TypeAdapter

from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import (
    ActionContext, EvidenceRecord, ScopeRef, StrictRecord, TextId, TimePoint, ref_type, walk_references,
)
from src.actions.contracts.government_consultation_objects import GovConsultationView, GovDisclosurePackageView
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.government_consultation_conditions import (
    GovernmentConsultationConditionReading, _BASES, _FIELDS, _QUERY_CODE,
)
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class GovernmentConsultationQueryRecord(StrictRecord):
    query_id: TextId
    source_identity_sha256: Digest
    run_id: TextId
    organization_id: TextId
    case_ref: ref_type('RegulatoryCase')
    consultation_ref: ref_type('Consultation')
    queried_at: TimePoint
    result: Literal['found', 'not_found', 'unknown']
    evidence_refs: list[ref_type('Evidence')] = Field(min_length=1)


def government_original_consultation_query_profile(read_current, validate_relation):
    """Found history permits registration/analysis, with no repeated initiation."""
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Consultation query recovery requires actual lookup sources and native validation')

    def identities(refs):
        keys = {ref.key()[:2] for ref in refs}
        if len(keys) != len(refs):
            raise TaskConflict('Consultation query recovery duplicates a physical source')
        return keys

    def evaluate(check):
        source, waited = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'GOV-A05' or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code != _QUERY_CODE or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in waited) != ('Consultation',)
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Consultation query recovery changes original lookup wait or agency')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, GovernmentConsultationConditionReading)
                or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                or not isinstance(selected.original_action_input, dict) or not isinstance(selected.action_input, dict)):
            raise TaskConflict('Consultation query recovery requires typed original/current sources')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        original_input, action_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
        try:
            if (set(original_input) != _FIELDS or set(action_input) != _FIELDS
                    or task_digest(original_input) != source['input_sha256'] or original_input['scope'] != action_input['scope']
                    or context.run_id != source['run_id'] or context.contract_ref.kind != 'ActionContract'
                    or context.contract_ref.id != 'GOV-A05' or context.execution_mode != 'llm'
                    or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                    or reading._resolver.source_mode != 'formal' or reading.organization_id != source['organization_id']):
                raise TaskConflict('Consultation query recovery replaces original snapshot or authorized invocation')
            scope = TypeAdapter(ScopeRef).validate_python(action_input['scope'])
            if not scope_covers(context.scope, scope):
                raise TaskConflict('Consultation query recovery leaves original scope')
            reading.check_method_context(context, 'GOV-A05')
            proof_rows = []

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref or not scope_covers(scope, row.scope):
                    raise TaskConflict('Consultation query recovery lacks exact scoped original/current sources')
                proof_rows.append(row)
                return row

            versions = [{field: read(ref_type(kind).model_validate(raw[field]), schema)
                for field, kind, schema in _BASES if raw[field] is not None}
                for raw in (original_input, action_input)]
            old, current = versions
            old_case, old_rule, old_package = (old[field] for field, _, _ in _BASES[:3])
            case, rule, package = (current[field] for field, _, _ in _BASES[:3])
            original_consultation = read(waited[0], GovConsultationView)
            if (old_rule.choice != 'initiate' or old_case.organization_id != source['organization_id']
                    or original_consultation.organization_id != source['organization_id']
                    or original_consultation.case_ref != old_case.ref):
                raise TaskConflict('Consultation query recovery differs from original initiation/case/agency')
            if original_input['prior_consultation_ref'] is not None:
                if old['prior_consultation_ref'].ref != waited[0]:
                    raise TaskConflict('Consultation query recovery replaces original explicitly requested consultation')
            elif (waited[0] not in old_case.consultation_refs or original_consultation.status != 'active'
                    or original_consultation.rule_ref != old_rule.ref or original_consultation.disclosure_package_ref != old_package.ref):
                raise TaskConflict('Consultation query recovery replaces original case-history duplicate match')
            query = None if selected.consultation_query is None else GovernmentConsultationQueryRecord.model_validate(
                deepcopy(selected.consultation_query))
            if query is None:
                return 'waiting'
            if (query.source_identity_sha256 != task_digest(source) or query.run_id != source['run_id']
                    or query.organization_id != source['organization_id'] or query.queried_at != context.business_time
                    or query.case_ref != case.ref or query.consultation_ref.key()[:2] != waited[0].key()[:2]
                    or len({ref.key() for ref in query.evidence_refs}) != len(query.evidence_refs)):
                raise TaskConflict('Consultation lookup evidence replaces original task/run/case/recipient/time')
            if query.result != 'found':
                return 'waiting'
            if 'prior_consultation_ref' not in current or rule.choice not in {'register_response', 'analyze'}:
                raise TaskConflict('Consultation lookup recovery must continue found history without initiating again')
            consultation = current['prior_consultation_ref']
            historical_package = read(original_consultation.disclosure_package_ref, GovDisclosurePackageView)
            if (consultation.ref != query.consultation_ref or consultation.ref.key()[:2] != waited[0].key()[:2]
                    or case.ref.key()[:2] != old_case.ref.key()[:2]
                    or case.organization_id != source['organization_id'] or rule.organization_id != source['organization_id']
                    or consultation.organization_id != source['organization_id'] or consultation.ref not in case.consultation_refs
                    or consultation.case_ref != case.ref or rule.case_ref != case.ref or package.case_ref != case.ref
                    or rule.ref != consultation.rule_ref or package.ref != consultation.disclosure_package_ref
                    or rule.ref.key()[:2] != original_consultation.rule_ref.key()[:2]
                    or package.ref.key()[:2] != original_consultation.disclosure_package_ref.key()[:2]
                    or package.content_sha256 != original_consultation.content_sha256
                    or historical_package.content_sha256 != original_consultation.content_sha256
                    or package.submission_sha256 != historical_package.submission_sha256
                    or package.submission_ref.key()[:2] != historical_package.submission_ref.key()[:2]
                    or identities(package.disclosed_evidence_refs) != identities(historical_package.disclosed_evidence_refs)
                    or consultation.content_sha256 != original_consultation.content_sha256
                    or consultation.procedure_ref.key()[:2] != original_consultation.procedure_ref.key()[:2]
                    or consultation.clock_rule_ref.key()[:2] != original_consultation.clock_rule_ref.key()[:2]
                    or case.applicant_id != old_case.applicant_id or case.matter_ref != old_case.matter_ref
                    or case.procedure_ref.key()[:2] != old_case.procedure_ref.key()[:2]
                    or case.jurisdiction_ref.key()[:2] != old_case.jurisdiction_ref.key()[:2]
                    or identities(old_case.consultation_refs) - identities(case.consultation_refs)
                    or identities(original_consultation.recipient_refs) != identities(consultation.recipient_refs)
                    or identities(original_consultation.response_refs) - identities(consultation.response_refs)
                    or identities(original_consultation.delivery_refs) - identities(consultation.delivery_refs)
                    or identities(original_consultation.participation_refs) - identities(consultation.participation_refs)
                    or set(original_consultation.registered_event_ids) - set(consultation.registered_event_ids)):
                raise TaskConflict('Consultation lookup recovery substitutes found content or retained original history')
            if case.status in {'closed', 'withdrawn'}:
                return 'waiting'
            now = context.business_time
            if any(row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                    or not row.effective_window.contains(now) for row in (case, rule, package, consultation)):
                return 'unavailable'
            grant, function = reading.resolve(rule.authority_ref), reading.resolve(context.function_ref)
            if (not isinstance(grant, Authorization) or grant.ref != rule.authority_ref
                    or not isinstance(function, RoleAssignment) or function.function_ref != context.function_ref
                    or function.role != 'Government' or grant.actor_id != context.actor_id
                    or grant.organization_id != source['organization_id'] or grant.function_ref != context.function_ref
                    or 'GOV-A05' not in grant.action_ids or not grant.validity.contains(now)
                    or not any(scope_covers(covered, scope) for covered in grant.scopes)):
                raise TaskConflict('Consultation lookup recovery lacks actual current continuation authority')
            proof_refs = [*query.evidence_refs, *grant.basis_refs, *function.basis_refs]
            proof_refs.extend(ref for row in proof_rows for ref in walk_references(row) if ref.kind == 'Evidence')
            evidence = {}
            for ref in proof_refs:
                row = reading.resolve(ref)
                if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                    raise TaskConflict('Consultation lookup requires observed actual endpoint/history evidence')
                evidence[ref.key()] = row.model_dump(mode='json')
            if validate_relation(source_identity=deepcopy(source), condition_code=_QUERY_CODE,
                    original_action_input=original_input, action_input=action_input,
                    consultation_query=query.model_dump(mode='json'),
                    original_consultation=original_consultation.model_dump(mode='json'), consultation=consultation.model_dump(mode='json'),
                    consultation_sources=deepcopy(selected.consultation_sources), unavailable_targets=deepcopy(selected.unavailable_targets),
                    evidence=deepcopy(list(evidence.values())), context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('Consultation lookup lacks native actual query receipt and lawful continuation authentication')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('GOV-A05', _QUERY_CODE, '1', frozenset({'dependency_change'}), evaluate)
