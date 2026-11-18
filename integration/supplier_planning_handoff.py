"""Bind saved A05 plans to actual A06 tasks without creating tasks or releases."""
from copy import deepcopy
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from integration.supplier_planning_results import SavedSupplierPlanning
from src.actions.contracts.architect_review_objects import Digest
from src.actions.contracts.common import EvidenceRecord, Reference, StrictRecord, TextId, ref_type
from src.actions.contracts.government_review_objects import GovReviewAuthored
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_cost_objects import CostSource
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_execution_objects import SupplierExecutionTaskView, SupplierProductionReleaseView, supplier_execution_schemas
from src.actions.contracts.supplier_planning_objects import SupplierPlannedTask
from src.coordination.tasks import task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


class SupplierFormedTaskLine(StrictRecord):
    planned_task: SupplierPlannedTask
    task_ref: ref_type('SupplyTask')
    task_sha256: Digest
    core_event_id: TextId


class SupplierTaskFormationRecordView(CostSource):
    """Host projection of an existing complete task registration and its plan."""
    ref: ref_type('SupplierTaskFormationRecord')
    run_id: TextId
    organization_id: TextId
    work_authority_ref: ref_type('SupplyWorkAuthorization')
    lines: Annotated[list[SupplierFormedTaskLine], Field(min_length=1)]
    native_source_sha256: Digest
    native_evidence_ref: ref_type('Evidence')


class SupplierPlanningHandoffBasisView(GovReviewAuthored):
    ref: ref_type('SupplierPlanningHandoffBasis')
    run_id: TextId
    organization_id: TextId
    planning_task_sha256: Digest
    planning_record_sha256: Digest
    planning_result_sha256: Digest
    planning_audit_sha256: Digest
    planning_source_reading_sha256: Digest
    formation_record_ref: ref_type('SupplierTaskFormationRecord')
    formation_record_sha256: Digest
    relation_evidence_refs: Annotated[list[ref_type('Evidence')], Field(min_length=1)]
    author_action_id: Literal['SUPPLIER-A06']


def supplier_planning_handoff_schemas():
    schemas = supplier_execution_schemas()
    schemas.register_kind('SupplierTaskFormationRecord', SupplierTaskFormationRecordView, str)
    schemas.register_kind('SupplierPlanningHandoffBasis', SupplierPlanningHandoffBasisView, str)
    return schemas


def prepare_supplier_planning_handoff(saved, *, context, reading, basis_ref, task_ref,
        release_ref, validate_current):
    """Check original complete plan lineage, selected current task and independent release."""
    if (not isinstance(saved, SavedSupplierPlanning) or not isinstance(reading, ActionReadView)
            or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A06'
            or not callable(validate_current)):
        raise ValueError('Planning handoff requires saved A05 evidence and actual authorized A06 reading')
    reading.check_method_context(context, 'SUPPLIER-A06')
    if (saved.current_context != context or saved.identity.action_id != 'SUPPLIER-A05'
            or saved.identity.role != 'Supplier' or saved.identity.run_id != context.run_id
            or saved.identity.organization_id != reading.organization_id or saved.context.scope != context.scope
            or saved.context.business_time.clock_ref != context.business_time.clock_ref
            or saved.context.business_time.offset > context.business_time.offset
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
        raise ValueError('Planning handoff changes original run, Supplier, scope, input/context or sources')
    if (saved.result.kind != 'completed' or saved.result.payload.choice not in
            {'plan_manufacture', 'plan_purchase', 'split_plan', 'revise_plan'}):
        return {'kind': 'needs_information', 'missing_fields': ['completed_original_supply_plan'],
            'requested_refs': [saved.action_input.work_authority_ref]}
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    expected_audit = {'run_id': context.run_id, 'action_id': 'SUPPLIER-A05',
        'input_sha256': saved.identity.input_sha256, 'result_sha256': result_sha,
        'result_kind': 'completed', 'operation_id': saved.context.operation_id}
    if (any(saved.audit.get(k) != v for k, v in expected_audit.items())
            or saved.audit.get('stages') != {'input_validation': 'accepted', 'authorization': 'accepted', 'processor': 'bound'}
            or saved.audit.get('reading', {}).get('status') != 'accepted'
            or saved.audit.get('reading', {}).get('read_token') != saved.context.read_token):
        raise ValueError('Planning handoff lacks original successful authorized audit')
    now = context.business_time

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise ValueError('Planning handoff requires exact concrete original sources')
        if (row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                or not row.effective_window.contains(now)):
            raise ValueError('Planning relation or task formation source is unavailable now')
        return row

    def evidence_at(refs, at):
        if at.clock_ref != now.clock_ref or at.offset > now.offset:
            raise ValueError('Planning evidence changes original use clock or time')
        for ref in {ref.key(): ref for ref in refs}.values():
            row = reading.resolve(ref)
            if (not isinstance(row, EvidenceRecord)
                    or row.effective_window is not None and not row.effective_window.contains(at)):
                raise ValueError('Planning source lacks authorized evidence valid at its use time')

    try:
        basis = read(Reference.model_validate(basis_ref), SupplierPlanningHandoffBasisView)
        expected = {'run_id': context.run_id, 'organization_id': reading.organization_id, 'scope': context.scope,
            'planning_task_sha256': saved.identity.key, 'planning_record_sha256': saved.record_sha256,
            'planning_result_sha256': result_sha, 'planning_audit_sha256': task_digest(saved.audit),
            'planning_source_reading_sha256': saved.source_reading_sha256}
        if any(getattr(basis, k) != v for k, v in expected.items()):
            raise ValueError('Planning source relation substitutes original saved evidence')
        grant, assignment = reading.resolve(basis.author_authority_ref), reading.resolve(basis.author_function_ref)
        if (not isinstance(grant, Authorization) or not isinstance(assignment, RoleAssignment)
                or assignment.role != 'Supplier' or assignment.function_ref != basis.author_function_ref
                or grant.organization_id != reading.organization_id or basis.author_organization_id != reading.organization_id
                or grant.actor_id != basis.author_actor_id or grant.function_ref != basis.author_function_ref
                or basis.author_action_id not in grant.action_ids or not any(scope_covers(s, basis.scope) for s in grant.scopes)
                or basis.authored_at.clock_ref != now.clock_ref or basis.authored_at.offset > basis.available_at.offset
                or not grant.validity.contains(basis.authored_at) or not basis.effective_window.contains(basis.authored_at)):
            raise ValueError('Planning relation lacks original independent Supplier author authority')
        for ref in [*grant.basis_refs, *assignment.basis_refs]:
            if ref.kind == 'Evidence':
                evidence_at([ref], basis.authored_at)
            else:
                reading.resolve(ref)
        source = read(basis.formation_record_ref, SupplierTaskFormationRecordView)
        if (source.run_id != context.run_id or source.organization_id != reading.organization_id
                or source.scope != saved.context.scope or source.work_authority_ref != saved.action_input.work_authority_ref
                or task_digest(source.model_dump(mode='json')) != basis.formation_record_sha256):
            raise ValueError('Actual task formation substitutes original work mandate or native record')
        original = [SupplierPlannedTask.model_validate(t.model_dump(mode='python')) for t in saved.result.payload.tasks]
        by_key = {t.local_key: t for t in original}
        unique_refs([row.task_ref for row in source.lines])
        if (len(by_key) != len(original) or len(source.lines) != len(original)
                or {row.planned_task.local_key for row in source.lines} != set(by_key)
                or any(row.planned_task != by_key[row.planned_task.local_key] for row in source.lines)):
            raise ValueError('Task formation changes or drops original plan lines, dependencies, inputs or resources')
        selected = [row for row in source.lines if row.task_ref.key() == Reference.model_validate(task_ref).key()]
        if len(selected) != 1:
            raise ValueError('Selected A06 task is absent from the exact original formed plan')
        selected = selected[0]
        task = read(selected.task_ref, SupplierExecutionTaskView)
        if (task.organization_id != reading.organization_id or task.as_of != now
                or task.mode != selected.planned_task.mode or task.scope != selected.planned_task.scope_ref
                or task_digest(task.model_dump(mode='json')) != selected.task_sha256
                or task.remaining_target.unit != selected.planned_task.target.quantity.unit
                or not Decimal('0') <= Decimal(task.remaining_target.value) <= Decimal(selected.planned_task.target.quantity.value)):
            raise ValueError('Current task changes original plan identity/mode/scope or remaining quantity')
        release = None
        if release_ref is not None:
            release = read(Reference.model_validate(release_ref), SupplierProductionReleaseView)
            if (task.mode == 'purchase' or release.organization_id != reading.organization_id
                    or release.task_ref != task.ref or release.method_ref != task.production_method_ref):
                raise ValueError('Independent release names another task or production method')
        unique_refs(basis.relation_evidence_refs)
        if set(basis.relation_evidence_refs).intersection([source.native_evidence_ref, *source.evidence_refs]):
            raise ValueError('Native task formation evidence cannot replace independent source relation')
        evidence_at([*basis.evidence_refs, *basis.relation_evidence_refs], basis.authored_at)
        for ref in basis.relation_evidence_refs:
            if reading.resolve(ref).basis_kind != 'observed':
                raise ValueError('Planning relation requires independent original observed evidence')
        evidence_at([source.native_evidence_ref, *source.evidence_refs, *task.evidence_refs,
            task.remaining_target.basis_ref, *([] if release is None else release.evidence_refs)], now)
        native = reading.resolve(source.native_evidence_ref)
        if native.basis_kind != 'observed' or native.content_hash != source.native_source_sha256:
            raise ValueError('Native task requires its exact current observed evidence')
        if validate_current(saved=deepcopy(saved), context=context.model_copy(deep=True), basis=basis.model_copy(deep=True),
                source=source.model_copy(deep=True), task=task.model_copy(deep=True),
                release=None if release is None else release.model_copy(deep=True)) is not True:
            raise ValueError('Actual task registration, method correspondence and independent release require host verification')
        return {'kind': 'prepared', 'task_ref': task.ref, 'planning_record_sha256': saved.record_sha256,
            'planning_result_sha256': result_sha, 'basis_sha256': task_digest(basis.model_dump(mode='json')),
            'formation_record_sha256': basis.formation_record_sha256, 'native_task_source_sha256': source.native_source_sha256,
            'limitations': ['Source relation only; A06 retains actual release/gate/history and resource checks.',
                'No task/release/reservation creation or reset of remaining quantity.']}
    finally:
        reading.recheck()
