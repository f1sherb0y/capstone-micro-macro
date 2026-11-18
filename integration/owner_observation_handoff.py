"""Relate a saved OWN-A01 intention to an independently observed actual case."""
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import Field

from integration.owner_observation_results import SavedOwnerObservation
from src.actions.contracts.common import EvidenceRecord, Reference, TextId, TimePoint, ref_type
from src.actions.contracts.owner_objects import OwnerObservationSourceView, OwnerOpportunityView, owner_observation_schemas
from src.actions.contracts.owner_proposal_objects import ProposalCaseView, owner_proposal_schemas
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.models import Digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class OwnerObservationHandoffBasisView(CostSource):
    ref: ref_type('OwnerObservationHandoffBasis')
    run_id: TextId
    organization_id: TextId
    observation_task_sha256: Digest
    observation_record_sha256: Digest
    observation_input_sha256: Digest
    observation_context_sha256: Digest
    observation_result_sha256: Digest
    observation_audit_sha256: Digest
    observation_source_reading_sha256: Digest
    case_ref: ref_type('OwnerCase')
    case_sha256: Digest
    native_event_id: TextId
    native_source_sha256: Digest
    native_evidence_ref: ref_type('Evidence')
    observed_at: TimePoint
    author_actor_id: TextId
    author_function_ref: ref_type('FunctionAssignment')
    author_authority_ref: ref_type('Authorization')
    author_action_id: Literal['OWN-A16']
    authored_at: TimePoint
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]


def owner_observation_handoff_schemas():
    schemas = owner_proposal_schemas()
    schemas.register_kind('OwnerObservationHandoffBasis', OwnerObservationHandoffBasisView, str)
    schemas.register_kind('Observation', OwnerObservationSourceView, str)
    schemas.register_kind('Opportunity', OwnerOpportunityView, str)
    return schemas


def prepare_owner_observation_handoff(saved, *, context, reading, basis_ref, case_ref, validate_current):
    if (not isinstance(saved, SavedOwnerObservation) or not isinstance(reading, ActionReadView)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'OWN-A16'
            or not callable(validate_current)):
        raise ValueError('Owner handoff requires original saved A01 and an explicit currently authorized A16 reading')
    reading.check_method_context(context, 'OWN-A16')
    if (saved.current_context != context or saved.identity.action_id != 'OWN-A01' or saved.identity.role != 'Owner'
            or saved.identity.run_id != context.run_id or saved.identity.organization_id != reading.organization_id
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256
            or context.operation_id == saved.context.operation_id or context.task_ref.key() == saved.context.task_ref.key()
            or context.read_token == saved.context.read_token
            or reading._resolver.source_mode != 'formal' or saved.context.execution_mode == 'offline_fixture'):
        raise TaskConflict('Owner handoff changes original task/content/recipient or lacks independently observed formal sources')
    if saved.result.kind != 'completed' or saved.result.payload.choice not in {'create_case', 'propose', 'revise_case', 'follow'}:
        return {'kind': 'needs_information', 'missing_fields': ['original_owner_case_relation'],
            'requested_refs': [saved.action_input.objective_ref]}
    result_sha256 = task_digest(saved.result.model_dump(mode='json'))
    if (saved.audit.get('input_sha256') != saved.identity.input_sha256
            or saved.audit.get('result_sha256') != result_sha256 or saved.audit.get('result_kind') != 'completed'):
        raise TaskConflict('Owner handoff changes its actually audited original result')

    def read(ref, schema):
        ref = Reference.model_validate(ref)
        source = reading.resolve(ref)
        if not isinstance(source, schema) or source.ref.key() != ref.key():
            raise TaskConflict('Owner handoff substitutes an original source schema or reference version')
        return source

    try:
        basis = read(basis_ref, OwnerObservationHandoffBasisView)
        case = read(case_ref, ProposalCaseView)
        objective = reading.resolve(saved.action_input.objective_ref)
        expected = {'observation_task_sha256': saved.identity.key,
            'observation_record_sha256': saved.record_sha256, 'observation_input_sha256': saved.identity.input_sha256,
            'observation_context_sha256': saved.identity.context_sha256, 'observation_result_sha256': result_sha256,
            'observation_audit_sha256': task_digest(saved.audit),
            'observation_source_reading_sha256': saved.source_reading_sha256,
            'case_sha256': task_digest(case.model_dump(mode='json'))}
        originals = {Reference.model_validate(row['ref']).key(): row['projection'] for row in saved.source_reading}
        if (any(getattr(basis, key) != value for key, value in expected.items())
                or basis.run_id != context.run_id or basis.organization_id != reading.organization_id
                or case.organization_id != reading.organization_id or basis.case_ref.key() != case.ref.key()
                or basis.scope != context.scope or case.objective_ref.key() != saved.action_input.objective_ref.key()
                or originals.get(saved.action_input.objective_ref.key()) != objective.model_dump(mode='json')
                or context.scope.kind == 'assessment_case' and context.scope.ref.key() != case.ref.key()
                or context.scope.kind == 'organization' and context.scope.ref.id != reading.organization_id):
            raise TaskConflict('Owner handoff changes original objective/content, actual private case, recipient or scope')
        payload = saved.result.payload.model_dump(mode='json')
        schemas = owner_observation_schemas()
        if payload['choice'] in {'create_case', 'propose'}:
            actual_demands = {ref.key() for ref in case.observation_refs}
            if not payload['source_refs']:
                raise TaskConflict('Original owner case intention has no selected observation sources')
            for raw_ref in payload['source_refs']:
                ref = Reference.model_validate(raw_ref)
                source = schemas.validate_projection(ref, originals.get(ref.key()))
                if (not isinstance(source, OwnerObservationSourceView) or source.demand_ref.key() not in actual_demands
                        or read(ref, OwnerObservationSourceView).model_dump(mode='json') != source.model_dump(mode='json')):
                    raise TaskConflict('Actual case does not preserve the originally selected observation/demand versions')
                demand = reading.resolve(source.demand_ref)
                if originals.get(source.demand_ref.key()) != demand.model_dump(mode='json'):
                    raise TaskConflict('Actual case changed the original selected demand source snapshot')
        elif payload['choice'] == 'revise_case' or payload['target']['kind'] == 'case':
            selected = payload['case_ref'] if payload['choice'] == 'revise_case' else payload['target']['case_ref']
            if (selected['kind'], selected['id']) != (case.ref.kind, case.ref.id):
                raise TaskConflict('Actual case replaces the originally selected private case identity')
        else:
            selected = Reference.model_validate(payload['target']['opportunity_ref'])
            if selected.key() not in {ref.key() for ref in case.opportunity_refs}:
                raise TaskConflict('Actual case lacks the originally selected opportunity version')
            if originals.get(selected.key()) != read(selected, OwnerOpportunityView).model_dump(mode='json'):
                raise TaskConflict('Actual case changes the original followed opportunity snapshot')
        times = [saved.context.business_time, basis.observed_at, basis.authored_at, basis.available_at, context.business_time]
        if (any(point.clock_ref != context.business_time.clock_ref for point in [*times, case.updated_at])
                or any(left.offset > right.offset for left, right in zip(times, times[1:]))
                or case.updated_at.offset > basis.observed_at.offset
                or not basis.effective_window.contains(context.business_time)
                or not basis.effective_window.contains(basis.authored_at)):
            raise TaskConflict('Owner handoff changes actual source availability or independent relation chronology')
        grant = read(basis.author_authority_ref, Authorization)
        assignment = reading.resolve(basis.author_function_ref)
        if (not isinstance(assignment, RoleAssignment) or assignment.role != 'Owner'
                or assignment.function_ref.key() != basis.author_function_ref.key()
                or grant.function_ref.key() != basis.author_function_ref.key()
                or grant.organization_id != reading.organization_id or grant.actor_id != basis.author_actor_id
                or basis.author_action_id not in grant.action_ids or not grant.validity.contains(basis.authored_at)
                or not any(scope_covers(scope, basis.scope) for scope in grant.scopes)):
            raise TaskConflict('Owner handoff lacks independently authorized original relation authorship')
        relations = {ref.key() for ref in basis.relation_evidence_refs}
        if len(relations) != len(basis.relation_evidence_refs) or basis.native_evidence_ref.key() in relations:
            raise TaskConflict('Owner actual native evidence cannot replace independent relation evidence')
        for ref in [*basis.evidence_refs, *basis.relation_evidence_refs, basis.native_evidence_ref,
                *grant.basis_refs, *assignment.basis_refs]:
            evidence = read(ref, EvidenceRecord)
            if (evidence.effective_window is not None and not evidence.effective_window.contains(context.business_time)
                    or ref.key() in relations | {basis.native_evidence_ref.key()}
                        and (evidence.basis_kind != 'observed' or evidence.source_kind == 'synthetic')):
                raise TaskConflict('Owner handoff requires available actual native and independent observed relation evidence')
        native = read(basis.native_evidence_ref, EvidenceRecord)
        if native.content_hash != basis.native_source_sha256:
            raise TaskConflict('Actual owner case observation changes its original native source digest')
        if validate_current(saved=deepcopy(saved), basis=basis.model_copy(deep=True), case=case.model_copy(deep=True),
                native_evidence=native.model_copy(deep=True), context=context.model_copy(deep=True), reading=reading) is not True:
            raise TaskConflict('Owner handoff requires actual current native-case/original-intention relation validation')
        return {'kind': 'prepared', 'source_mode': 'formal', 'provenance': {**expected,
            'basis_ref': basis.ref.model_dump(mode='json'), 'basis_sha256': task_digest(basis.model_dump(mode='json')),
            'case_ref': case.ref.model_dump(mode='json'), 'native_event_id': basis.native_event_id,
            'native_source_sha256': basis.native_source_sha256}}
    finally:
        reading.recheck()
