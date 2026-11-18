"""Isolated local Contractor A12 sources for explicit V7 fault verification."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from threading import RLock

from integration.action_model_host import ActionOptionSource
from integration.lifecycle_v7_model_fault import ModelFaultSources
from integration.macro_views import AuthorizedMacroViewAssembler
from integration.role_contract_host import RoleContractInvocation
from src.actions.commercial_options import CommercialProfileOptionProvider
from src.actions.contracts.commercial_continuation_objects import commercial_continuation_schemas
from src.actions.registry import ActionRegistry
from src.actions.roles.contractor_continuation import continue_contractor_business
from src.actions.runner import ActionRunner
from src.coordination.tasks import TaskConflict, TaskIdentity, TaskStore, task_digest
from src.organization.registry import OrganizationRegistry, OrganizationSnapshot


def build_sources(*, request, output_directory):
    """Build from declared synthetic JSON only; never read tests or old results.

    The local identity uses the original contract source SHA and Skill/prompt
    SHA. These are explicit fixture versions, not commercial-worker identities
    or formal execution evidence. Only protect/suspend proposals are supported;
    no mathematical method, transition, payment or submission is executed.
    """
    original = deepcopy(request)
    digest = task_digest(original)
    invocation = RoleContractInvocation.model_validate(original['request'])
    context = invocation.context
    identity = TaskIdentity(**original['identity'])
    settings = original['sources']['settings']
    if (set(settings) != {'schema_version', 'organization_snapshot', 'source_projection',
            'source_configuration_sha256', 'assumption_text'}
            or settings['schema_version'] != 'v7-commercial-model-fault-fixture-sources.v1'
            or identity.action_id != 'CONTRACTOR-A12' or identity.role != 'Contractor'
            or context.execution_mode != 'offline_fixture' or invocation.execution_path != 'single_agent'
            or original['origin'] != 'synthetic' or not isinstance(settings['assumption_text'], str)):
        raise ValueError('V7 local source supports only an explicitly synthetic Contractor A12 case')
    payload = {k: v for k, v in settings.items() if k != 'source_configuration_sha256'}
    if task_digest(payload) != settings['source_configuration_sha256']:
        raise TaskConflict('Original V7 independent source declaration changed')
    snapshot = OrganizationSnapshot.model_validate(settings['organization_snapshot'])
    if (snapshot.schema_version != 'organization.v2' or snapshot.run_id != context.run_id
            or len(snapshot.organizations) != 1 or len(snapshot.authorizations) != 1
            or snapshot.inactive_authorization_refs
            or snapshot.organizations[0].organization_id != identity.organization_id):
        raise ValueError('V7 source requires one isolated original fixture organization and grant')
    organizations = OrganizationRegistry(context.run_id)
    for organization in snapshot.organizations:
        organizations.register(organization)
    for authorization in snapshot.authorizations:
        organizations.authorize(authorization)
    grants = organizations.grants(context, identity.action_id, identity.role)
    registry = ActionRegistry()
    registry.register_processor('CONTRACTOR-A12', 'contractor.original_business_continuation.v1',
        continue_contractor_business, strategy='single_agent')
    registration = registry.get(identity.action_id)
    skill = registration.skill.manifest
    versions = {'client': 'v7-local-commercial-fixture.v1', 'skill': skill.skill_sha256,
        'prompt': skill.prompt_sha256, 'contract': registration.contract.source_sha256,
        'method': 'commercial-proposals-no-method.v1', 'model': 'synthetic-local-model-fault.v1',
        'strategy': 'single_agent:actions.single_agent.validated_options:1'}
    if identity.versions != versions:
        raise TaskConflict('V7 fixture versions differ from the original contract/Skill/selection path')
    projection = deepcopy(settings['source_projection'])
    if (projection['run_id'] != context.run_id or projection['organization_id'] != identity.organization_id
            or projection['business_time'] != context.business_time.model_dump(mode='json')
            or projection['read_token'] != context.read_token
            or [row['ref'] for row in projection['objects']] != [r.model_dump(mode='json') for r in context.visible_refs]):
        raise ValueError('V7 projection differs from its exact original isolated invocation')
    rows = {task_digest(row['ref']): row for row in projection['objects']}
    if len(rows) != len(projection['objects']):
        raise ValueError('V7 fixture repeats source references')
    evidence_rows = [row['value'] for row in projection['objects'] if row['ref']['kind'] == 'Evidence']
    if (not evidence_rows or any(row['source_kind'] != 'synthetic' or row['basis_kind'] != 'assumed'
            or row['content_hash'] != task_digest(settings['assumption_text']) for row in evidence_rows)):
        raise ValueError('V7 fixture may only use its explicitly declared synthetic assumptions')
    inputs = [registration.contract.validate_input(o['action_input']) for o in original['options']]
    profiles = [rows[task_digest(i.continuation_profile_ref.model_dump(mode='json'))]['value'] for i in inputs]
    base_input = registration.contract.validate_input(invocation.action_input)
    if (len(inputs) != 2 or {p['choice'] for p in profiles} != {'protect', 'suspend'}
            or len({task_digest(p['state_ref']) for p in profiles}) != 1
            or len({task_digest(p['basis_ref']) for p in profiles}) != 1
            or any(p['organization_id'] != identity.organization_id for p in profiles)
            or any(i.model_dump(exclude={'continuation_profile_ref'}) != base_input.model_dump(
                exclude={'continuation_profile_ref'}) for i in inputs)):
        raise ValueError('V7 alternatives must retain the original state/rights and all business input references')
    lock = RLock()
    closed = False

    @contextmanager
    def guard():
        with lock:
            if closed or task_digest(request) != digest or organizations.grants(context, identity.action_id, identity.role) != grants:
                raise TaskConflict('V7 local source invocation or original authority changed')
            try:
                yield
            finally:
                if closed or task_digest(request) != digest or organizations.grants(context, identity.action_id, identity.role) != grants:
                    raise TaskConflict('V7 local source invocation or original authority changed during reading')

    class Provider:
        def project(self, *, context, organization_id, grants):
            with guard():
                if (context.model_dump(mode='json') != invocation.context.model_dump(mode='json')
                        or organization_id != identity.organization_id
                        or grants != organizations.grants(context, identity.action_id, identity.role)):
                    raise TaskConflict('V7 projection request changes original recipient/context/grants')
                return deepcopy(projection)

    resolver = AuthorizedMacroViewAssembler(organizations, Provider(), commercial_continuation_schemas(),
        macro_version=projection['macro_version'], source_mode='fixture').build_resolver(
            context, identity.action_id, identity.role)
    runner = ActionRunner(registry, organizations=organizations, references=resolver,
        run_id=context.run_id, policy_version='v7-local-commercial-proposals.v1')
    producer = CommercialProfileOptionProvider()

    def validate_invocation(data, actual_identity):
        with guard():
            if (data != original or actual_identity != identity or actual_identity.versions != versions
                    or actual_identity.input_sha256 != task_digest(base_input.model_dump(mode='json'))
                    or actual_identity.context_sha256 != task_digest(context.model_dump(mode='json'))
                    or registry.get(identity.action_id) is not registration):
                raise TaskConflict('V7 independent local invocation/version/input verification failed')
            return True

    path = Path(original['sources']['journal_path']).resolve()
    if path.parent != Path(output_directory).resolve() or path.exists():
        raise TaskConflict('V7 local fault needs a new journal in its own selected output directory')
    store = TaskStore(run_id=context.run_id, organization_ids=[identity.organization_id], path=path)

    def close():
        nonlocal closed
        with lock:
            closed = True
            store.close()

    return ModelFaultSources(runner, store, ActionOptionSource(producer.VERSION,
        producer.prepare_options, producer.validate_options), validate_invocation, guard, close)
