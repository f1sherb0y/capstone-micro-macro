"""Recheck actual GBA source records at the original publication boundary."""
from contextlib import nullcontext
import re

from integration.bindings.gba_v1 import GbaV1Assembly
from src.actions.contracts.common import ActionContext
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.registry import OrganizationRegistry


def validate_native_publication(*, assembly, organizations, prepared, context, project_id=None):
    """Supplement independent professional validation; caller holds writer guard.

    Native package/resource producers carry source_record_sha256. Independent
    quantity/cost/programme/mapping additions carry no native source record and
    retain their application's existing professional/retained-source validators.
    Nothing is inferred from a successful read: this gate checks current original
    source identity, not qualifications, calendar correctness or core effects.
    """
    context = ActionContext.model_validate(context).model_copy(deep=True)
    if (not isinstance(assembly, GbaV1Assembly) or not isinstance(organizations, OrganizationRegistry)
            or organizations.run_id != assembly.client.run_id or context.run_id != assembly.client.run_id
            or context.contract_ref.kind != 'ActionContract'
            or context.contract_ref.id not in {'CONTRACTOR-A01', 'CONTRACTOR-A02'}
            or not isinstance(prepared, dict) or prepared.get('kind') != 'prepared'):
        raise TaskConflict('Native publication requires original same-run Contractor sources and prepared records')
    assembly._validate_components()
    grants = organizations.grants(context, context.contract_ref.id, 'Contractor')
    organization_id = grants[0].organization_id
    original_grants_sha256 = task_digest([grant.model_dump(mode='json') for grant in grants])
    expected_mode = 'fixture' if context.execution_mode == 'offline_fixture' else 'formal'
    has_native_source = 'source_record_sha256' in prepared
    if has_native_source and (not isinstance(prepared['source_record_sha256'], str)
            or re.fullmatch(r'[0-9a-f]{64}', prepared['source_record_sha256']) is None):
        raise TaskConflict('Native publication requires the original complete source record SHA')
    if context.contract_ref.id == 'CONTRACTOR-A01':
        if (not has_native_source or prepared.get('source_mode') != expected_mode
                or not isinstance(project_id, str) or not project_id.strip()):
            raise TaskConflict('A01 native package publication requires its explicit actual project and source mode')
        if context.scope.kind == 'project' and context.scope.ref.id != project_id:
            raise TaskConflict('A01 native package publication substitutes its original project scope')
        tender = assembly.read_invited_tender_project(organization_id=organization_id,
            project_id=project_id, read_guard=nullcontext)
        if tender.get('record_sha256') != prepared['source_record_sha256']:
            raise TaskConflict('Published package no longer matches its actual current own invitation')
        resource_bundle = prepared.get('resource_projections')
        if resource_bundle is not None:
            if (not isinstance(resource_bundle, dict) or resource_bundle.get('kind') != 'prepared'
                    or resource_bundle.get('context_sha256') != task_digest(context.model_dump(mode='json'))
                    or resource_bundle.get('source_mode') != expected_mode):
                raise TaskConflict('Published A01 resource bundle changes its original context or source mode')
            resource = assembly.read_enterprise_resources(organization_id=organization_id, read_guard=nullcontext)
            if (resource_bundle.get('source_record_sha256') != resource['record_sha256']
                    or resource['observed_tick'] != tender.get('observed_tick')):
                raise TaskConflict('Published A01 resources differ from the original same-tick native package read')
    elif has_native_source:
        if (prepared.get('context_sha256') != task_digest(context.model_dump(mode='json'))
                or prepared.get('source_mode') != expected_mode):
            raise TaskConflict('Published A02 capacity changes its original context or source mode')
        resource = assembly.read_enterprise_resources(organization_id=organization_id, read_guard=nullcontext)
        if prepared['source_record_sha256'] != resource['record_sha256']:
            raise TaskConflict('Published A02 capacity no longer matches its actual current own resources')
    assembly._validate_components()
    current = organizations.grants(context, context.contract_ref.id, 'Contractor')
    if task_digest([grant.model_dump(mode='json') for grant in current]) != original_grants_sha256:
        raise TaskConflict('Native publication authority changed during its original source validation')
