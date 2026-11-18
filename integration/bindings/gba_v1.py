"""Assemble the actual GBA external module and its matching final provider."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib

from integration.agent_client import GbaV1AgentClient, AgentClientError
from integration.bootstrap import enable_gba_imports


@dataclass(frozen=True)
class GbaV1Assembly:
    engine: object
    client: GbaV1AgentClient
    _original_module: object = field(init=False, repr=False, compare=False)
    _original_provider: object = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, '_original_module', self.engine.agent_module)
        object.__setattr__(self, '_original_provider', self.engine.lifecycle_engine.decision_provider)
        self._validate_components()

    def read_enterprise_resources(self, *, organization_id, read_guard):
        """Read original own-enterprise resource facts under the host engine guard."""
        from integration.bindings.gba_v1_views import read_enterprise_resources

        self._validate_components()
        return read_enterprise_resources(self.engine,self.client,
            organization_id=organization_id,read_guard=read_guard)

    def read_own_progress_payments(self, *, organization_id, tick, read_guard):
        from integration.bindings.gba_v1_progress_payments import read_own_progress_payments

        return read_own_progress_payments(self, organization_id=organization_id, tick=tick, read_guard=read_guard)

    def read_own_final_accounts(self, *, organization_id, tick, read_guard):
        from integration.bindings.gba_v1_final_accounts import read_own_final_accounts

        return read_own_final_accounts(self, organization_id=organization_id, tick=tick, read_guard=read_guard)

    def read_invited_tender_project(self, *, organization_id, project_id, read_guard):
        from integration.bindings.gba_v1_tender_package import read_invited_tender_project

        self._validate_components()
        return read_invited_tender_project(self.engine,self.client,
            organization_id=organization_id,project_id=project_id,read_guard=read_guard)

    def prepare_tender_package(self, *, context, reading, project_id, read_guard, terms_ref=None):
        from integration.bindings.gba_v1_tender_package import prepare_gba_tender_package

        source = self.read_invited_tender_project(organization_id=reading.organization_id,
            project_id=project_id,read_guard=read_guard)
        if source.get('kind') == 'needs_information':
            return source
        return prepare_gba_tender_package(source,context=context,reading=reading,terms_ref=terms_ref)

    def publish_tender_package(self, *, context, reading, project_id, read_guard,
            terms_ref, publications, next_context):
        """Produce and publish original source objects at the next authorized token."""
        from integration.bindings.gba_v1_tender_publication import GbaTenderPublicationStore

        if not isinstance(publications,GbaTenderPublicationStore) or publications.store is not self.client.tasks:
            raise AgentClientError('Tender publication must share the actual client run journal')
        prepared = self.prepare_tender_package(context=context,reading=reading,
            project_id=project_id,read_guard=read_guard,terms_ref=terms_ref)
        if prepared['kind'] != 'prepared':
            return prepared
        record = publications.publish(prepared,source_context=context,reading=reading,next_context=next_context)
        return {**prepared,'publication':record}

    def publish_screening_snapshot(self, *, context, reading, project_id, read_guard,
            terms_ref, facts_ref, publications, next_context):
        """Publish package/invitation/resources from one host-guarded snapshot.

        validate_source on publications must check both source records and the
        original independent terms/enterprise facts. Holding the real writer
        guard across reads and publication avoids composing different ticks or
        mid-tick updates. Nested read helpers use no additional lock acquisition.
        """
        from contextlib import nullcontext
        from integration.bindings.gba_v1_tender_publication import GbaTenderPublicationStore

        if (not callable(read_guard) or not isinstance(publications,GbaTenderPublicationStore)
                or publications.store is not self.client.tasks):
            raise AgentClientError('Screening publication requires the actual writer guard and shared journal')
        with read_guard():
            # The actual host guard is already held; no engine writer can
            # advance either source between these original reads and commit.
            locked_read = nullcontext
            package = self.prepare_tender_package(context=context,reading=reading,
                project_id=project_id,read_guard=locked_read,terms_ref=terms_ref)
            if package['kind'] != 'prepared':
                return package
            resources = self.prepare_screening_resources(context=context,reading=reading,
                read_guard=locked_read,facts_ref=facts_ref)
            if resources['kind'] != 'prepared':
                return resources
            record = publications.publish(package,source_context=context,reading=reading,
                next_context=next_context,resource_projections=resources)
            return {'kind':'prepared','package':package,'resources':resources,'publication':record}

    def prepare_enterprise_capacity(self, *, context, reading, read_guard, mapping_ref=None):
        """Prepare input from the actual resource read and explicit host calendar."""
        from integration.bindings.gba_v1_capacity import prepare_gba_capacity_input

        source = self.read_enterprise_resources(organization_id=reading.organization_id,read_guard=read_guard)
        return prepare_gba_capacity_input(source,context=context,reading=reading,mapping_ref=mapping_ref)

    def prepare_supplier_quote_capacity(self, *, context, reading, read_guard, adoption_ref, validate_current):
        """Read actual enterprise resources and project Supplier quote capacity under one guard."""
        from contextlib import nullcontext
        from integration.supplier_quote_capacity_source import prepare_supplier_quote_capacity

        if not callable(read_guard) or not callable(validate_current):
            raise ValueError('Actual shared host guard and current capacity source validator required')
        with read_guard():
            source = self.read_enterprise_resources(organization_id=reading.organization_id, read_guard=nullcontext)
            return prepare_supplier_quote_capacity(source, context=context, reading=reading,
                adoption_ref=adoption_ref, validate_current=validate_current)

    def prepare_screening_resources(self, *, context, reading, read_guard, facts_ref):
        """Produce A01 capability/commitments from actual source and independent competence."""
        from integration.bindings.gba_v1_screening_resources import prepare_gba_screening_resource_projections

        source = self.read_enterprise_resources(organization_id=reading.organization_id,read_guard=read_guard)
        return prepare_gba_screening_resource_projections(source,context=context,reading=reading,facts_ref=facts_ref)

    def prepare_bid_capacity(self, *, context, reading, read_guard, facts_ref):
        """Produce A02 capacity and original pool/commitment source projections."""
        from integration.bindings.gba_v1_bid_capacity import prepare_gba_bid_capacity_projections

        source = self.read_enterprise_resources(organization_id=reading.organization_id,read_guard=read_guard)
        return prepare_gba_bid_capacity_projections(source,context=context,reading=reading,facts_ref=facts_ref)

    def publish_bid_capacity(self, *, context, reading, read_guard, facts_ref,
            publications, next_context):
        """Publish A02 resources under one actual host guard and a fresh read token."""
        from contextlib import nullcontext
        from integration.bindings.gba_v1_tender_publication import GbaTenderPublicationStore

        if (not callable(read_guard) or not isinstance(publications,GbaTenderPublicationStore)
                or publications.store is not self.client.tasks):
            raise AgentClientError('Bid capacity publication requires the actual writer guard and shared journal')
        with read_guard():
            prepared = self.prepare_bid_capacity(context=context,reading=reading,
                read_guard=nullcontext,facts_ref=facts_ref)
            if prepared['kind'] != 'prepared':
                return prepared
            record = publications.publish_bid_capacity(prepared,source_context=context,
                reading=reading,next_context=next_context)
            return {**prepared,'publication':record}

    def publish_bid_costs(self, *, context, reading, read_guard, adoption_refs,
            validate_current, publications, next_context):
        """Produce and publish explicitly adopted lines under the actual host writer guard."""
        from integration.contractor_bid_costs import prepare_contractor_bid_cost
        from integration.bindings.gba_v1_tender_publication import GbaTenderPublicationStore
        from src.actions.contracts.common import Reference
        from src.actions.contracts.owner_study_objects import unique_refs

        refs = [Reference.model_validate(ref) for ref in adoption_refs]
        unique_refs(refs)
        if (not refs or not callable(read_guard) or not callable(validate_current)
                or not isinstance(publications, GbaTenderPublicationStore)
                or publications.store is not self.client.tasks):
            raise AgentClientError('Bid cost publication requires explicit sources, host guard and shared journal')
        with read_guard():
            prepared = []
            for ref in refs:
                result = prepare_contractor_bid_cost(context=context, reading=reading,
                    adoption_ref=ref, validate_current=validate_current)
                if result['kind'] != 'prepared':
                    return result
                prepared.append(result)
            record = publications.publish_bid_costs(prepared, source_context=context,
                reading=reading, next_context=next_context)
            return {'kind': 'prepared', 'costs': prepared, 'publication': record}

    def publish_bid_quantities(self, *, context, reading, source_reading, read_guard, mapping_refs,
            validate_current, publications, next_context):
        """Publish original QS quantity projections under the same actual host guard."""
        from integration.contractor_bid_quantities import prepare_contractor_bid_quantity
        from integration.bindings.gba_v1_tender_publication import GbaTenderPublicationStore
        from src.actions.contracts.common import Reference
        from src.actions.contracts.owner_study_objects import unique_refs

        refs = [Reference.model_validate(ref) for ref in mapping_refs]
        unique_refs(refs)
        if (not refs or not callable(read_guard) or not callable(validate_current)
                or not isinstance(publications, GbaTenderPublicationStore)
                or publications.store is not self.client.tasks):
            raise AgentClientError('Quantity publication requires explicit source relations, host guard and shared journal')
        with read_guard():
            prepared = []
            for ref in refs:
                result = prepare_contractor_bid_quantity(context=context, reading=reading,
                    source_reading=source_reading, mapping_ref=ref, validate_current=validate_current)
                if result['kind'] != 'prepared':
                    return result
                prepared.append(result)
            record = publications.publish_bid_quantities(prepared, source_context=context,
                reading=reading, source_reading=source_reading, next_context=next_context)
            return {'kind': 'prepared', 'quantities': prepared, 'publication': record}

    def publish_bid_programme(self, *, context, reading, read_guard, basis_ref,
            validate_current, publications, next_context):
        """Produce and publish a plan under the actual writer guard, without resource booking."""
        from integration.contractor_bid_programme import prepare_contractor_bid_programme
        from integration.bindings.gba_v1_tender_publication import GbaTenderPublicationStore

        if (not callable(read_guard) or not callable(validate_current)
                or not isinstance(publications, GbaTenderPublicationStore)
                or publications.store is not self.client.tasks):
            raise AgentClientError('Programme publication requires an explicit host guard and original shared journal')
        with read_guard():
            prepared = prepare_contractor_bid_programme(context=context, reading=reading,
                basis_ref=basis_ref, validate_current=validate_current)
            if prepared['kind'] != 'prepared':
                return prepared
            record = publications.publish_bid_programme(prepared, source_context=context,
                reading=reading, next_context=next_context)
            return {**prepared, 'publication': record}

    def build_contractor_bid_pipeline(self, **components):
        """Compose the source/publication/result chain from explicitly configured host components."""
        from integration.contractor_bid_pipeline import GbaContractorBidPipeline

        return GbaContractorBidPipeline(assembly=self, **components)

    def prepare_contractor_screening(self, *, context, reading, registration, read_guard,
            package_ref, capability_ref, commitments_ref, screening_profile_ref,
            qualification_refs=(), invitation_refs=(), mapping_ref=None):
        """Assemble A01 with its exact host projections and actual resource source."""
        from integration.bindings.gba_v1_contractor_screening import prepare_gba_contractor_screening_input

        source = self.read_enterprise_resources(organization_id=reading.organization_id,read_guard=read_guard)
        return prepare_gba_contractor_screening_input(source,context=context,reading=reading,
            registration=registration,package_ref=package_ref,capability_ref=capability_ref,
            commitments_ref=commitments_ref,screening_profile_ref=screening_profile_ref,
            qualification_refs=qualification_refs,invitation_refs=invitation_refs,mapping_ref=mapping_ref)

    def bind_contractor_tender_proposal(self, *, registry, read_output, revalidate, client_version):
        """Explicitly install the audited A02 bridge before the first request."""
        from integration.bindings.gba_v1_tender_proposal import GbaTenderProposalAdapter

        self._validate_components()
        adapter = GbaTenderProposalAdapter(run_id=self.client.run_id,
            simulation_id=self.engine.simulation_id,registry=registry,
            read_output=read_output,revalidate=revalidate)
        role, operation = adapter.HANDLER_KEY
        self.client.bind_proposal_handler(role=role,operation=operation,
            handler=adapter,client_version=client_version)
        return adapter

    def bind_contractor_tender_decision(self, *, validate_current, client_version, host_configuration_sha256):
        """Bind the saved A02 choice to the actual bounded final provider route."""
        self._validate_components()
        return self.client.bind_tender_decision(validate_current=validate_current,client_version=client_version,
            host_configuration_sha256=host_configuration_sha256)

    def restore_contractor_tender_bindings(self, *, registry, read_output, revalidate,
            validate_current, host_configuration_sha256):
        """Restore only after the host has restored the actual original engine."""
        self._validate_components()
        if self.engine.simulation_id != self.client.simulation_id:
            raise AgentClientError('Tender restoration requires the original engine/client simulation identity')
        return self.client.restore_tender_bindings(registry=registry,read_output=read_output,
            revalidate=revalidate,validate_current=validate_current,
            host_configuration_sha256=host_configuration_sha256)

    def _validate_components(self):
        module = self.engine.agent_module
        provider = self.engine.lifecycle_engine.decision_provider
        if (module is not self._original_module or provider is not self._original_provider
                or module.client is not self.client or provider is not module.decision_provider):
            raise AgentClientError("Engine module and final decision provider no longer share the bound client")
        validate_native = getattr(module, '_validate_native_composition', None)
        if validate_native is not None:
            validate_native()

    def evidence(self):
        self._validate_components()
        module = self.engine.agent_module
        provider = self.engine.lifecycle_engine.decision_provider
        return {"schema_version": "gba-v1-assembly.v1", "mode": "gba_v1_module",
                "macro_version": "gba-public-2026-08-21",
                "initialization": {"project_source": "native_project_generation" if self.engine.enable_project_generation
                                   else "supplied_projects", "enterprise_ids": sorted(self.client.organization_roles)},
                "module": f"{type(module).__module__}.{type(module).__qualname__}",
                "provider": f"{type(provider).__module__}.{type(provider).__qualname__}",
                "client": self.client.evidence(),
                **({'native_composition': module.native_composition_evidence()}
                    if hasattr(module, 'native_composition_evidence') else {}),
                "source_readers": {"own_enterprise_resources": {
                    "component": "integration.bindings.gba_v1_views.read_enterprise_resources",
                    "schema_version": "gba-v1-enterprise-resources.v1",
                    "status": "implemented_unverified", "requires_host_engine_guard": True,
                    "role_action_projection": False}},
                "input_producers": {"enterprise_capacity": {
                    "component": "integration.bindings.gba_v1_capacity.prepare_gba_capacity_input",
                    "status": "implemented_unverified", "requires_sourced_calendar_mapping": True,
                    "method_execution": False}, "contractor_screening": {
                    "component": "integration.bindings.gba_v1_contractor_screening.prepare_gba_contractor_screening_input",
                    "action_id": "CONTRACTOR-A01", "status": "implemented_unverified",
                    "requires_sourced_calendar_mapping": True, "business_execution": False}},
                "limitations": ["Old operation contracts only; no implicit mapping to the 106 new actions",
                                "Feedback is restricted to named own-enterprise event projections"]}


def build_module_engine(request, client: GbaV1AgentClient, *, allow_native_project_generation=False,
                        allow_native_initial_projects_with_generation=False,
                        checkpoint=None, checkpointable=False) -> GbaV1Assembly:
    enable_gba_imports()
    from gba_construction_sim.backend.agents.external_adapter import ExternalAgentModuleAdapter
    from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
    from gba_construction_sim.backend.simulation.simulation_engine import SimulationEngine

    request = SimulationCreateRequest.model_validate(request).model_copy(deep=True)
    if (type(allow_native_project_generation) is not bool
            or type(allow_native_initial_projects_with_generation) is not bool):
        raise AgentClientError('Native project generation requires an explicit boolean selection')
    if allow_native_initial_projects_with_generation and (not allow_native_project_generation or not request.initial_projects):
        raise AgentClientError('Mixed native initialization requires explicit generation and supplied initial projects')
    if allow_native_project_generation:
        from gba_construction_sim.backend.simulation.simulation_engine import ensure_mvp_support_agents
        identities = {agent.agent_id: agent.role for agent in request.agents}
        merged = ensure_mvp_support_agents(request.agents)
        if (request.agent_source != 'default' or not request.enable_project_generation or request.use_prior_network_edges
                or not request.agents or (request.initial_projects and not allow_native_initial_projects_with_generation)
                or len(identities) != len(request.agents)
                or {a.agent_id: a.role for a in merged} != identities or len(merged) != len(request.agents)):
            raise AgentClientError('Native generation requires supplied unique agents with all support roles, '
                                   'default source, no undeclared initial projects and no prior network edges')
        if allow_native_initial_projects_with_generation:
            initial_ids = [p.project_id for p in request.initial_projects]
            if len(set(initial_ids)) != len(initial_ids) or any(p.startswith('PGEN') for p in initial_ids):
                raise AgentClientError('Initial projects must be unique and leave the PGEN namespace to the native generator')
            fields = {'owner_id': 'Owner', 'selected_architect_id': 'Architect', 'selected_engineer_id': 'Engineer',
                'selected_qs_id': 'QS', 'selected_contractor_id': 'Contractor', 'selected_bank_id': 'Bank'}
            for project in request.initial_projects:
                if any(getattr(project, field) is not None and identities.get(getattr(project, field)) != role
                       for field, role in fields.items()):
                    raise AgentClientError('Explicit initial project refers to an undeclared or differently typed participant')
                if any(identities.get(e.agent_id) != e.role or e.project_id != project.project_id for e in project.engagements):
                    raise AgentClientError('Explicit initial engagement changes its declared project or participant role')
                if any(c.get('contractor_id') is not None and identities.get(c['contractor_id']) != 'Contractor'
                       for c in project.contracts):
                    raise AgentClientError('Explicit initial contract refers to an undeclared Contractor')
    elif request.agent_source != "explicit" or not request.agents or not request.initial_projects:
        raise AgentClientError("Module integration requires explicit agents and projects")
    if request.procurement_execution.mode != "gba_native":
        raise AgentClientError("External module assembly cannot also own micro procurement")
    if type(checkpointable) is not bool:
        raise AgentClientError('Checkpoint ownership requires an explicit boolean selection')
    if checkpointable or checkpoint is not None:
        from integration.native_checkpoint import NativeEngineLease
        client._native_engine_lease = NativeEngineLease(client.tasks.path)
    client.claim({agent.agent_id: agent.role for agent in request.agents})
    if checkpointable or checkpoint is not None:
        from integration.module_host import module_client_implementation
        client._native_initial_binding = {'versions': dict(client.versions),
            'implementation': module_client_implementation(client)}
    # Original register_profiles enriches the supplied profiles in place.
    # Checkpoint identity must still bind the caller's unmodified request.
    checkpoint_request = request.model_copy(deep=True) if checkpoint is not None else None
    native_routes = getattr(client, 'native_routes', None)
    if native_routes is not None and native_routes.settings.direct_native_proposals:
        from integration.bindings.gba_v1_native_composition import DeclaredNativeComposition
        module = DeclaredNativeComposition(client, request.agents, random_seed=request.random_seed)
    else:
        module = ExternalAgentModuleAdapter(client, request.agents, random_seed=request.random_seed)
    engine = SimulationEngine.from_request(request, agent_module=module,
                                           decision_provider=module.decision_provider)
    if checkpoint is not None:
        from integration.native_checkpoint import restore_native_checkpoint
        restore_native_checkpoint(engine, client, request=checkpoint_request, path=checkpoint)
    client.attach(engine.simulation_id)
    return GbaV1Assembly(engine, client)


def macro_binding_source_hashes() -> dict[str, str]:
    root = enable_gba_imports()
    symbols = ["agents/contracts.py", "agents/external_adapter.py", "agents/operation_specs.py",
               "simulation/simulation_engine.py", "simulation/enterprise_decision_scheduler.py"]
    return {f"gba_construction_sim/backend/{name}":
            hashlib.sha256((root / "gba_construction_sim/backend" / name).read_bytes()).hexdigest()
            for name in symbols}
