"""Explicitly compose original GBA behavior for routes not owned by micro actions.

No failure fallback is provided. An application declares each native route at
startup; micro routes must be installed separately before engine execution.
Native results remain labelled as native and never count as micro coverage.
"""
from __future__ import annotations

from copy import deepcopy
import inspect
import hashlib
from pathlib import Path
from typing import get_type_hints

from pydantic import Field, TypeAdapter

from integration.bootstrap import enable_gba_imports
from integration.module_host import GbaModuleHostConfiguration, GbaModuleHostExtension
from src.actions.contracts.common import StrictRecord, TextId
from src.coordination.tasks import task_digest
from integration.agent_client import GbaV1AgentClient


class NativeProposalRoute(StrictRecord):
    role: TextId
    operation: TextId


class NativeDecisionRoute(StrictRecord):
    role: TextId
    decision_type: TextId


class NativeRouteSettings(StrictRecord):
    run_id: TextId | None = None
    native_proposals: list[NativeProposalRoute] = Field(default_factory=list)
    # These explicitly unowned operations keep the original typed module call.
    # They never transport a micro response outside the external validator.
    direct_native_proposals: list[NativeProposalRoute] = Field(default_factory=list)
    native_decisions: list[NativeDecisionRoute] = Field(default_factory=list)
    # This module only delegates to the existing local rule provider. It never
    # instantiates a model, guesses a provider, or handles undeclared requests.
    provider: str = 'gba_rule_based'
    # Identity scoping also applies when QS business is explicitly owned by a
    # micro bridge. It delegates no business behavior to the native provider.
    micro_qs_evaluation_scope: bool = False
    # Invitation dispatch belongs to the bridge; only declared initial
    # projects delegate to these original native routes.
    mixed_owner_invitation_scope: bool = False
    mixed_qs_learning_scope: bool = False
    micro_professional_intake_scope: bool = False
    native_professional_intake_scope: bool = False
    micro_government_intake_scope: bool = False
    micro_government_approval_scope: bool = False
    micro_government_monthly_feedback_scope: bool = False
    micro_bank_monthly_strategy_scope: bool = False
    micro_owner_opportunity_scope: bool = False
    micro_owner_commission_scope: bool = False
    native_government_approval_transport: bool = False
    micro_supplier_order_scope: bool = False
    micro_contractor_supply_scope: bool = False
    micro_contractor_formation_scope: bool = False
    micro_owner_award_scope: bool = False
    query_saved_approval_on_error: bool = False
    query_saved_intake_on_error: bool = False
    query_saved_monthly_on_error: bool = False
    query_saved_bank_monthly_on_error: bool = False
    query_saved_qs_learning_on_error: bool = False
    query_saved_financing_on_error: bool = False
    query_saved_supply_on_error: bool = False
    query_saved_tender_on_error: bool = False
    query_saved_opportunity_on_error: bool = False
    native_project_financing_scope: bool = False
    native_financing_proposal_transport: bool = False
    native_financing_proposal_transport_roles: list[TextId] = Field(default_factory=list)


class NativeRouteAgentClient(GbaV1AgentClient):
    def _task_request_id(self, purpose, request):
        return self.native_routes.task_request_id(purpose, request)

    def propose(self, raw_request):
        """Optionally reconcile durable work while its native call is open.

        Querying happens after the original client lock is released, retaining
        host -> client lock order. It never invokes the business handler twice.
        Unknown work still raises the original error and remains unresolved.
        """
        from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1
        request = self._input_snapshot(AgentProposalRequestV1, raw_request)
        try:
            return super().propose(request)
        except Exception as original_error:
            settings = self.native_routes.settings
            route = (request.agent.role, request.operation)
            if route == ('Government', 'consider_review_assignment') and settings.query_saved_intake_on_error:
                from integration.government_intake_native import GovernmentIntakeApplication
                owner_type, kind = GovernmentIntakeApplication, 'intake'
            elif route == ('Government', 'decide_approval') and settings.query_saved_approval_on_error:
                from integration.government_approval_native import GovernmentApprovalApplication
                owner_type, kind = GovernmentApprovalApplication, 'approval'
            elif route == ('Government', 'decide_monthly_operation') and settings.query_saved_monthly_on_error:
                from integration.government_monthly_native import GovernmentMonthlyApplication
                owner_type, kind = GovernmentMonthlyApplication, 'monthly'
            elif route == ('Bank', 'decide_monthly_operation') and settings.query_saved_bank_monthly_on_error:
                from integration.bank_monthly_native import BankMonthlyApplication
                owner_type, kind = BankMonthlyApplication, 'bank_monthly'
            elif route == ('QS', 'decide_monthly_operation') and settings.query_saved_qs_learning_on_error:
                from integration.qs_evaluation_learning import QSEvaluationLearning
                owner_type, kind = QSEvaluationLearning, 'qs_learning'
            elif route == ('Bank', 'consider_financing') and settings.query_saved_financing_on_error:
                from integration.bank_financing_native import BankFinancingApplication
                owner_type, kind = BankFinancingApplication, 'financing'
            elif route == ('Supplier', 'consider_supply_order') and settings.query_saved_supply_on_error:
                from integration.supplier_order_native import SupplierOrderNativeApplication
                owner_type, kind = SupplierOrderNativeApplication, 'supply'
            elif route == ('Contractor', 'consider_tender') and settings.query_saved_tender_on_error:
                from integration.bindings.gba_v1_tender_proposal import GbaTenderProposalAdapter
                owner_type, kind = GbaTenderProposalAdapter, 'tender'
            elif route == ('Owner', 'evaluate_project_opportunity') and settings.query_saved_opportunity_on_error:
                from integration.owner_opportunity_native import OwnerOpportunityApplication
                owner_type, kind = OwnerOpportunityApplication, 'opportunity'
            else:
                raise
            with self._lock:
                handler, _ = self._proposal_route(request)
                owner = getattr(handler, '__self__', handler)
                if not isinstance(owner, owner_type):
                    raise original_error
                authorized = owner.saved_recovery_enabled if kind == 'tender' else owner.settings.allow_saved_recovery
                if not authorized:
                    raise original_error
            try:
                response = self.recover_proposal(request)
            except Exception as recovery_error:
                raise original_error from recovery_error
            with self._lock:
                self._calls.append({'purpose': 'propose_saved_' + kind + '_returned', 'run_id': self.run_id,
                    'status': 'returned_saved_result',
                    'request_id': request.request_id, 'agent_id': request.agent.agent_id,
                    'action_type': response.action_type, 'response_sha256': task_digest(response.model_dump(mode='json')),
                    'business_reexecuted': False, 'new_native_request': False,
                    'boundary': 'Returned to the still-open original macro proposal call; no engine restart or resubmission.'})
            return response


class NativeRoutes:
    VERSION = 'explicit-gba-native-routes.v31'

    def __init__(self, *, request, settings):
        enable_gba_imports()
        from gba_construction_sim.backend.agents.agent_registry import AgentBehaviorRegistry
        from gba_construction_sim.backend.agents.operation_specs import get_operation_contract
        from gba_construction_sim.backend.decision.rule_based_provider import RuleBasedDecisionProvider

        self.settings = NativeRouteSettings.model_validate(settings).model_copy(deep=True)
        if self.settings.query_saved_monthly_on_error and not self.settings.micro_government_monthly_feedback_scope:
            raise ValueError('Saved monthly query on error requires exclusively owned original micro monthly feedback')
        if self.settings.query_saved_bank_monthly_on_error and not self.settings.micro_bank_monthly_strategy_scope:
            raise ValueError('Saved Bank monthly query requires exclusively owned original micro Bank monthly strategy')
        if self.settings.query_saved_approval_on_error and (
                not self.settings.micro_government_intake_scope or not self.settings.micro_government_approval_scope
                or self.settings.native_government_approval_transport):
            raise ValueError('Saved approval query on error requires exclusively owned original micro approval')
        if self.settings.provider != 'gba_rule_based':
            raise ValueError('Native routes require the explicitly selected bundled rule provider')
        self.roles = {agent.agent_id: agent.role for agent in request.agents}
        self._proposals = frozenset((route.role, route.operation) for route in self.settings.native_proposals)
        self._decisions = frozenset((route.role, route.decision_type) for route in self.settings.native_decisions)
        if self.settings.query_saved_intake_on_error and (
                not self.settings.micro_government_intake_scope or 'Government' not in self.roles.values()
                or ('Government','consider_review_assignment') in self._proposals
                or ('Government','government_review_assignment') in self._decisions):
            raise ValueError('Saved intake query requires exclusively owned original micro Government intake routes')
        if self.settings.query_saved_financing_on_error and (
                not self.settings.native_project_financing_scope or 'Bank' not in self.roles.values()
                or self.settings.native_financing_proposal_transport
                or 'Bank' in self.settings.native_financing_proposal_transport_roles
                or ('Bank', 'consider_financing') in self._proposals
                or ('Bank', 'bank_project_financing') in self._decisions):
            raise ValueError('Saved financing query requires exclusively owned original micro Bank financing routes')
        direct = [(route.role, route.operation) for route in self.settings.direct_native_proposals]
        if self.settings.mixed_qs_learning_scope and (
                not self.settings.micro_qs_evaluation_scope
                or ('QS', 'decide_monthly_operation') not in self._proposals
                or ('QS', 'monthly_enterprise_operation') not in self._decisions
                or ('QS', 'decide_monthly_operation') in direct):
            raise ValueError('QS private learning requires original declared monthly routes behind its micro step')
        if self.settings.query_saved_qs_learning_on_error and not self.settings.mixed_qs_learning_scope:
            raise ValueError('Saved QS learning query requires its explicitly installed private learning route')
        if len(set(direct)) != len(direct) or not set(direct) <= self._proposals:
            raise ValueError('Direct native module calls require distinct explicitly native proposal routes')
        if self.settings.mixed_owner_invitation_scope and (
                ('Owner', 'select_tender_invitees') not in self._proposals
                or ('Owner', 'owner_tender_shortlist') not in self._decisions
                or ('Owner', 'select_tender_invitees') in direct):
            raise ValueError('Mixed invitations require explicit original routes behind the invitation bridge')
        if self.settings.micro_bank_monthly_strategy_scope and (
                'Bank' not in self.roles.values() or ('Bank','decide_monthly_operation') in self._proposals
                or ('Bank','monthly_enterprise_operation') in self._decisions):
            raise ValueError('Micro monthly Bank strategy requires exclusive Bank monthly routes')
        if self.settings.query_saved_opportunity_on_error and (
                not self.settings.micro_owner_opportunity_scope or 'Owner' not in self.roles.values()
                or ('Owner','evaluate_project_opportunity') in self._proposals
                or ('Owner','owner_project_opportunity') in self._decisions):
            raise ValueError('Saved opportunity query requires exclusively owned original micro Owner routes')
        if self.settings.query_saved_tender_on_error and (
                'Contractor' not in self.roles.values() or ('Contractor', 'consider_tender') in self._proposals
                or ('Contractor', 'tender_decision') in self._decisions):
            raise ValueError('Saved tender query on error requires exclusively owned original micro tender routes')
        if self.settings.micro_government_monthly_feedback_scope and (
                not self.settings.micro_government_intake_scope or 'Government' not in self.roles.values()
                or ('Government','decide_monthly_operation') in self._proposals
                or ('Government','monthly_enterprise_operation') in self._decisions):
            raise ValueError('Micro monthly feedback needs exclusive original Government monthly routes and its parent application')
        if (len(self._proposals) != len(self.settings.native_proposals)
                or len(self._decisions) != len(self.settings.native_decisions)):
            raise ValueError('Native route declarations cannot contain duplicates')
        for role, operation in self._proposals:
            if role not in self.roles.values():
                raise ValueError('Declared native proposal role is outside the original participants')
            get_operation_contract(operation, role)
        if any(role not in self.roles.values() for role, _ in self._decisions):
            raise ValueError('Declared native decision role is outside the original participants')
        if (len(set(self.settings.native_financing_proposal_transport_roles)) != len(self.settings.native_financing_proposal_transport_roles)
                or not set(self.settings.native_financing_proposal_transport_roles) <= {'Owner', 'Bank'}):
            raise ValueError('Native financing transport roles must be distinct Owner/Bank declarations')
        if self.settings.native_financing_proposal_transport or self.settings.native_financing_proposal_transport_roles:
            from integration.project_financing_native import PROPOSALS, DECISIONS
            selected_roles = set(self.roles.values()) if self.settings.native_financing_proposal_transport else set(self.settings.native_financing_proposal_transport_roles)
            required_proposals = {key for key in PROPOSALS if key[0] in selected_roles}
            required_decisions = {key for key in DECISIONS if key[0] in selected_roles}
            if (not self.settings.native_project_financing_scope or 'Owner' not in self.roles.values()
                    or not required_proposals <= self._proposals or not required_decisions <= self._decisions):
                raise ValueError('Native financing proposal transport requires explicit scoped native proposal/final routes')
        if self.settings.micro_qs_evaluation_scope and (
                'QS' not in self.roles.values() or ('QS', 'evaluate_bid') in self._proposals
                or ('QS', 'qs_bid_evaluation') in self._decisions):
            raise ValueError('Micro QS task scoping requires exclusive micro evaluation routes')
        if self.settings.micro_contractor_formation_scope and (
                'Contractor' not in self.roles.values() or ('Contractor','decide_contract_terms') in self._proposals
                or ('Contractor','contract_negotiation') in self._decisions):
            raise ValueError('Micro Contractor formation requires exclusive original terms and negotiation routes')
        if self.settings.micro_owner_award_scope and (
                'Owner' not in self.roles.values() or not self.settings.micro_contractor_formation_scope
                or ('Owner','decide_contract_award') in self._proposals
                or ('Owner','owner_contract_award') in self._decisions):
            raise ValueError('Micro Owner award requires original Contractor formation and exclusive award routes')
        if self.settings.micro_professional_intake_scope and (
                any((role, 'consider_appointment') in self._proposals for role in ('Architect', 'Engineer', 'QS'))
                or any((role, role.lower() + '_appointment_acceptance') in self._decisions
                       for role in ('Architect', 'Engineer', 'QS'))):
            raise ValueError('Micro professional scoping requires exclusive micro service-intake routes')
        if self.settings.micro_owner_commission_scope and (
                not self.settings.micro_professional_intake_scope or ('Owner','select_appointment') in self._proposals
                or any(('Owner','owner_select_'+r) in self._decisions for r in ('architect','engineer','qs'))):
            raise ValueError('Micro Owner commission requires micro professional intake and exclusive Owner selection routes')
        if self.settings.native_professional_intake_scope:
            professional = {'Architect','Engineer','QS'}
            if (self.settings.micro_professional_intake_scope
                    or not ({(r,'consider_appointment') for r in professional}
                            | {('Owner','select_appointment')}) <= self._proposals
                    or not ({(r,r.lower()+'_appointment_acceptance') for r in professional}
                            | {('Owner','owner_select_'+r.lower()) for r in professional}) <= self._decisions):
                raise ValueError('Native appointment scoping requires its exclusive declared proposal and final routes')
        self.behaviors = AgentBehaviorRegistry(random_seed=request.random_seed)
        if self.settings.micro_owner_opportunity_scope and (
                ('Owner','evaluate_project_opportunity') in self._proposals
                or ('Owner','owner_project_opportunity') in self._decisions
                or ('Owner','owner_project_initiation') in self._decisions):
            raise ValueError('Micro owner opportunity requires exclusive proposal/final ownership')
        if self.settings.micro_government_intake_scope and (
                ('Government','consider_review_assignment') in self._proposals
                or ('Government','government_review_assignment') in self._decisions):
            raise ValueError('Micro regulatory intake requires exclusive proposal and final routes')
        if self.settings.native_government_approval_transport and (
                not self.settings.micro_government_intake_scope or ('Government','decide_approval') not in self._proposals
                or ('Government','government_design_approval') not in self._decisions):
            raise ValueError('Native approval transport requires scoped micro intake and declared original approval routes')
        if self.settings.micro_government_approval_scope and (
                not self.settings.micro_government_intake_scope or self.settings.native_government_approval_transport
                or ('Government','decide_approval') in self._proposals
                or any(('Government',decision) in self._decisions for decision in
                    ('government_design_approval','government_completion_approval'))):
            raise ValueError('Micro approval requires exclusive proposal/final routes and scoped micro intake')
        if self.settings.micro_contractor_supply_scope and (
                not self.settings.micro_supplier_order_scope or ('Contractor','select_supplier') in self._proposals
                or ('Contractor','contractor_supplier_selection') in self._decisions):
            raise ValueError('Micro Contractor procurement requires exclusive Contractor routes and scoped Supplier micro inputs')
        if self.settings.query_saved_supply_on_error and not self.settings.micro_supplier_order_scope:
            raise ValueError('Supply saved-result query requires exclusive micro Supplier routes')
        if self.settings.micro_supplier_order_scope and (
                ('Supplier','consider_supply_order') in self._proposals
                or ('Supplier','supplier_order_acceptance') in self._decisions
                or not self.settings.micro_contractor_supply_scope and (
                    ('Contractor','select_supplier') not in self._proposals
                    or ('Contractor','contractor_supplier_selection') not in self._decisions)):
            raise ValueError('Micro supply orders require exclusive Supplier routes and explicit original Contractor selection')
        self.provider = RuleBasedDecisionProvider()
        self._source_paths = {Path(inspect.getfile(type(self.provider))), Path(inspect.getfile(type(self.behaviors)))}
        if self.settings.native_project_financing_scope:
            from gba_construction_sim.backend.simulation.simulation_engine import SimulationEngine
            self._source_paths.add(Path(inspect.getfile(SimulationEngine)))
        from gba_construction_sim.backend.agents.agent_registry import ROLE_AGENT_TYPES
        self._source_paths.update(Path(inspect.getfile(ROLE_AGENT_TYPES[role])) for role in set(self.roles.values()))
        self._source_sha256 = self._sources()
        self.assembly = None
        self._calls = []

    def _sources(self):
        root = enable_gba_imports()
        return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(self._source_paths)}

    def attach(self, assembly):
        if self.assembly is not None:
            raise ValueError('Native routes cannot be shared by engines')
        if assembly.client.organization_roles != self.roles:
            raise ValueError('Native routing changes original enterprise identities')
        assembly._validate_components()
        self.assembly = assembly

    def _profile(self, request):
        from integration.agent_client import AgentClientError

        if self.assembly is None:
            raise AgentClientError('Explicit native routes must be attached before execution')
        self.assembly._validate_components()
        profile = self.assembly.engine.agents.get(request.agent.agent_id)
        if profile is None or profile.role != request.agent.role or self.roles.get(profile.agent_id) != profile.role:
            raise AgentClientError('Native request substitutes an original enterprise identity')
        # Original behavior may append background data. Only the core owns
        # writes to its live profile; the delegated behavior uses a read copy.
        return profile.model_copy(deep=True)

    def propose(self, request):
        from gba_construction_sim.backend.agents.contracts import AgentProposalResponseV1
        from integration.agent_client import AgentClientError

        key = (request.agent.role, request.operation)
        if key not in self._proposals:
            raise AgentClientError('No explicit native proposal route: ' + repr(key))
        profile = self._profile(request)
        behavior = self.behaviors.for_profile(profile)
        method = getattr(behavior, request.operation)
        hints, signature = get_type_hints(method), inspect.signature(method)
        values = {}
        # The native external protocol transports typed objects as JSON. Restore
        # precisely the original method's declared argument types, preserving
        # supplied candidates and values rather than reading a larger pool.
        for name, value in request.inputs.items():
            parameter = signature.parameters.get(name)
            if parameter is None:
                raise AgentClientError('Native transport supplies an undeclared method argument: ' + name)
            values[name] = TypeAdapter(hints[name]).validate_python(value) if name in hints else deepcopy(value)
        if key in {('Owner', 'select_appointment'), ('Owner', 'select_financing_offer'),('Contractor','select_supplier')}:
            # The native annotation leaves the second tuple item as object.
            # JSON therefore survives TypeAdapter as a dict, while the role
            # reads AgentDecision attributes. Restore the actual dataclass;
            # keep every supplied value and let the original role choose.
            from gba_construction_sim.backend.agents.base_agent import AgentDecision
            field = 'candidates' if request.operation == 'select_appointment' else 'offers'
            values[field] = [(candidate, TypeAdapter(AgentDecision).validate_python(decision))
                             for candidate, decision in values[field]]
        decision = self.behaviors.propose(profile, request.operation, **values)
        factors = {**deepcopy(decision.factors), 'decision_source': 'native_macro'}
        if key == ('QS', 'evaluate_bid'):
            factors['native_evaluation_scope'] = self._evaluation_scope(request, purpose='propose')
        if self.settings.native_project_financing_scope:
            from integration.project_financing_native import PROPOSALS, financing_scope
            if key in PROPOSALS:
                factors['native_financing_scope'] = financing_scope(self.assembly, request, purpose='propose')
        if self.settings.native_government_approval_transport and key==('Government','decide_approval'):
            from integration.government_intake_scope import government_scope
            factors['native_government_scope']=government_scope(self.assembly,request,purpose='propose')
        if self.settings.micro_supplier_order_scope and key==('Contractor','select_supplier'):
            from integration.supplier_order_native_scope import supply_scope
            factors['native_supply_scope']=supply_scope(self.assembly,request,purpose='propose')
        if (self.settings.micro_professional_intake_scope and key == ('Owner', 'select_appointment')
                or self.settings.native_professional_intake_scope and key in
                {('Owner','select_appointment'), *((r,'consider_appointment') for r in ('Architect','Engineer','QS'))}):
            from integration.professional_intake_scope import professional_scope
            factors['native_professional_scope'] = professional_scope(self.assembly, request, purpose='propose')
        self._calls.append({'purpose': 'propose', 'role': key[0], 'operation': key[1],
                            'request_id': request.request_id, 'decision_source': 'native_macro'})
        return AgentProposalResponseV1(request_id=request.request_id,
            action_type=decision.action_type, accepted=decision.accepted, utility=decision.utility,
            probability=decision.probability, reason=decision.reason, data=deepcopy(decision.data),
            factors=factors)

    def _evaluation_scope(self, request, *, purpose):
        """Identify the actual bid, without changing the frozen native request ID.

        The native loop reuses one ID for every candidate. A technical scope
        travels in proposal factors into the original final-decision support.
        It changes no score, candidate set, formal state or response identity.
        """
        from integration.agent_client import AgentClientError

        if self.assembly is None:
            raise AgentClientError('Native evaluation identity requires the attached original engine')
        tick = self.assembly.engine.current_tick
        if purpose == 'propose':
            inputs = request.inputs
            contractor_id = inputs.get('bid', {}).get('contractor_id')
            project_id = inputs.get('project', {}).get('project_id')
            if contractor_id != inputs.get('contractor', {}).get('agent_id'):
                raise AgentClientError('Native bid evaluation substitutes its original contractor')
            scope = {'tick': tick, 'project_id': project_id, 'contractor_id': contractor_id}
        else:
            scope = request.decision_support.get('decision_factors', {}).get('native_evaluation_scope')
            if (not isinstance(scope, dict) or set(scope) != {'tick', 'project_id', 'contractor_id'}
                    or scope['tick'] != request.tick or scope['project_id'] != request.project_id):
                raise AgentClientError('Native final evaluation lacks its exact original proposal scope')
        projects = self.assembly.engine.projects
        project = projects.get(scope['project_id']) if isinstance(projects, dict) else next(
            (project for project in projects if project.project_id == scope['project_id']), None)
        if (type(scope['tick']) is not int or scope['tick'] != tick or project is None
                or not scope['contractor_id'] or project.selected_qs_id != request.agent.agent_id
                or len([bid for bid in project.bids if bid['contractor_id'] == scope['contractor_id']]) != 1):
            raise AgentClientError('Native evaluation scope must name one actual current bid and appointed QS')
        return deepcopy(scope)

    def task_request_id(self, purpose, request):
        operation = request.operation if purpose == 'propose' else request.decision_type
        key = (request.agent.role, operation)
        if self.settings.micro_bank_monthly_strategy_scope and (purpose,*key) in {
                ('propose','Bank','decide_monthly_operation'),('decide','Bank','monthly_enterprise_operation')}:
            from integration.bank_monthly_native_sources import monthly_bank_scope
            return request.request_id+':bank-monthly:'+task_digest(monthly_bank_scope(self.assembly,request,purpose=purpose))
        if self.settings.micro_government_monthly_feedback_scope and (purpose,*key) in {
                ('propose','Government','decide_monthly_operation'),('decide','Government','monthly_enterprise_operation')}:
            from integration.government_monthly_native_sources import monthly_scope
            return request.request_id+':monthly-feedback:'+task_digest(monthly_scope(self.assembly,request,purpose=purpose))
        if self.settings.micro_owner_award_scope and (purpose,*key) in {
                ('propose','Owner','decide_contract_award'),('decide','Owner','owner_contract_award')}:
            from integration.owner_award_native_sources import award_scope
            return request.request_id+':owner-award:'+task_digest(award_scope(self.assembly,request,purpose=purpose))
        if self.settings.micro_contractor_formation_scope and (purpose,*key) in {
                ('propose','Contractor','decide_contract_terms'),('decide','Contractor','contract_negotiation')}:
            from integration.contractor_formation_native_sources import formation_scope
            return request.request_id+':contract-terms:'+task_digest(formation_scope(self.assembly,request,purpose=purpose))
        if self.settings.micro_owner_opportunity_scope and key in {
                ('Owner','evaluate_project_opportunity'),('Owner','owner_project_opportunity')}:
            from integration.owner_opportunity_scope import owner_opportunity_scope
            return request.request_id+':owner-opportunity:'+task_digest(owner_opportunity_scope(self.assembly,request,purpose=purpose))
        if self.settings.micro_supplier_order_scope and (purpose,*key) in {
                ('propose','Supplier','consider_supply_order'),('propose','Contractor','select_supplier'),
                ('decide','Supplier','supplier_order_acceptance'),('decide','Contractor','contractor_supplier_selection')}:
            from integration.supplier_order_native_scope import supply_scope
            return request.request_id+':supply-scope:'+task_digest(supply_scope(self.assembly,request,purpose=purpose))
        if self.settings.micro_government_intake_scope and request.agent.role=='Government' and operation in {
                'consider_review_assignment','decide_approval','government_review_assignment','government_design_approval',
                'government_completion_approval'}:
            from integration.government_intake_scope import government_scope
            return request.request_id+':regulatory-scope:'+task_digest(government_scope(self.assembly,request,purpose=purpose))
        if self.settings.native_project_financing_scope:
            from integration.project_financing_native import PROPOSALS, DECISIONS, financing_scope, opportunity_scope
            if purpose == 'propose' and key == ('Owner', 'evaluate_project_opportunity'):
                return request.request_id + ':native-opportunity:' + task_digest(opportunity_scope(self.assembly, request))
            if key in (PROPOSALS if purpose == 'propose' else DECISIONS):
                return request.request_id + ':native-financing:' + task_digest(financing_scope(self.assembly, request, purpose=purpose))
        if (self.settings.micro_professional_intake_scope or self.settings.native_professional_intake_scope) and (
                purpose == 'propose' and (key in {(role, 'consider_appointment') for role in ('Architect', 'Engineer', 'QS')}
                                         or key == ('Owner', 'select_appointment'))
                or purpose == 'decide' and (key in {(role, role.lower() + '_appointment_acceptance')
                    for role in ('Architect', 'Engineer', 'QS')}
                    or key in {('Owner', 'owner_select_' + role) for role in ('architect', 'engineer', 'qs')})):
            from integration.professional_intake_scope import professional_scope
            scope = professional_scope(self.assembly, request, purpose=purpose)
            return request.request_id + ':professional-scope:' + task_digest(scope)
        declared = self._proposals if purpose == 'propose' else self._decisions
        if (key in declared or self.settings.micro_qs_evaluation_scope) and (purpose, *key) in {
                ('propose', 'QS', 'evaluate_bid'), ('decide', 'QS', 'qs_bid_evaluation')}:
            scope = self._evaluation_scope(request, purpose=purpose)
            return request.request_id + ':native-evaluation:' + task_digest(scope)
        return request.request_id

    def decide(self, request):
        from gba_construction_sim.backend.agents.contracts import AgentDecisionResponseV1
        from gba_construction_sim.backend.agents.external_adapter import ExternalAgentDecisionProvider
        from gba_construction_sim.backend.models.environment import MacroEnvironment
        from gba_construction_sim.backend.models.policy import PolicyRegime
        from gba_construction_sim.backend.models.project import ConstructionProject
        from gba_construction_sim.backend.models.stage_rule import StageRule
        from integration.agent_client import AgentClientError

        key = (request.agent.role, request.decision_type)
        if key not in self._decisions:
            raise AgentClientError('No explicit native final decision route: ' + repr(key))
        if self.settings.micro_supplier_order_scope and key==('Contractor','contractor_supplier_selection'):
            from integration.supplier_order_native_scope import transport_native_supplier_selection
            self._profile(request)
            return transport_native_supplier_selection(self,request)
        if self.settings.native_government_approval_transport and key in {
                ('Government','government_design_approval'),('Government','government_completion_approval')}:
            from integration.government_intake_scope import transport_native_approval
            self._profile(request)
            return transport_native_approval(self,request)
        if self.settings.native_professional_intake_scope and key in {
                *((r,r.lower()+'_appointment_acceptance') for r in ('Architect','Engineer','QS')),
                *(('Owner','owner_select_'+r) for r in ('architect','engineer','qs'))}:
            from integration.professional_intake_scope import transport_native_appointment_decision
            self._profile(request)
            return transport_native_appointment_decision(self,request)
        if self.settings.native_financing_proposal_transport or request.agent.role in self.settings.native_financing_proposal_transport_roles:
            from integration.project_financing_native import DECISIONS, transport_native_financing_decision
            if key in DECISIONS:
                self._profile(request)
                return transport_native_financing_decision(self, request)
        profile = self._profile(request)
        stage_rule = deepcopy(request.stage_rule)
        # The original collector transports a role-scoped snapshot, whose
        # allowed_actions is a list. Restore only this role's entry; do not
        # recover other roles' permissions from the engine's full registry.
        if isinstance(stage_rule.get('allowed_actions'), list):
            stage_rule['allowed_actions'] = {profile.role: stage_rule['allowed_actions']}
        context = {
            **deepcopy(request.decision_support), **deepcopy(request.decision_task),
            'request_id': request.request_id, 'tick': request.tick,
            'decision_type': request.decision_type, 'allowed_actions': list(request.constraints.allowed_actions),
            'decision_task': deepcopy(request.decision_task), 'decision_support': deepcopy(request.decision_support),
            'candidate_options': deepcopy(request.candidate_options),
            'project': ConstructionProject.model_validate(request.project) if request.project else None,
            'macro_environment': MacroEnvironment.model_validate(request.environment) if request.environment else None,
            'policy': PolicyRegime.model_validate(request.policy) if request.policy else None,
            'stage_rule': StageRule.model_validate(stage_rule) if stage_rule else None,
            'agent_memory': deepcopy(request.memory), 'agent_belief': deepcopy(request.beliefs),
            'agent_strategy': deepcopy(request.strategy), 'recent_messages': deepcopy(request.recent_messages),
        }
        # Named risk inputs are available in the original protocol; keep them
        # distinct from actual own resource state and canonical request fields.
        for name, value in request.current_state.get('risk_inputs', {}).items():
            if name not in context:
                context[name] = deepcopy(value)
        action = self.provider.decide(profile, context)
        response = AgentDecisionResponseV1(request_id=request.request_id, agent_id=profile.agent_id,
            action_type=action.action_type, decision=action.decision, reason=action.reason,
            data={**deepcopy(action.data), 'decision_source': 'native_macro'})
        ExternalAgentDecisionProvider._validated_action(request, response)
        self._calls.append({'purpose': 'decide', 'role': key[0], 'decision_type': key[1],
                            'request_id': request.request_id, 'decision_source': 'native_macro'})
        return response

    def evidence(self):
        if self._sources() != self._source_sha256:
            raise ValueError('Original native behavior sources changed after route configuration')
        return {'version': self.VERSION, 'native_proposals': sorted(self._proposals),
                'native_decisions': sorted(self._decisions), 'calls': deepcopy(self._calls),
                'source_sha256': deepcopy(self._source_sha256),
                'native_project_financing_scope': self.settings.native_project_financing_scope,
                'native_financing_proposal_transport': self.settings.native_financing_proposal_transport,
                'native_financing_proposal_transport_roles': list(self.settings.native_financing_proposal_transport_roles),
                'native_professional_intake_scope': self.settings.native_professional_intake_scope,
                'mixed_owner_invitation_scope': self.settings.mixed_owner_invitation_scope,
                'mixed_qs_learning_scope': self.settings.mixed_qs_learning_scope,
                'micro_government_intake_scope': self.settings.micro_government_intake_scope,
                'micro_government_approval_scope': self.settings.micro_government_approval_scope,
                'micro_government_monthly_feedback_scope':self.settings.micro_government_monthly_feedback_scope,
                'micro_bank_monthly_strategy_scope':self.settings.micro_bank_monthly_strategy_scope,
                'micro_owner_opportunity_scope': self.settings.micro_owner_opportunity_scope,
                'micro_owner_commission_scope': self.settings.micro_owner_commission_scope,
                'native_government_approval_transport': self.settings.native_government_approval_transport,
                'micro_supplier_order_scope': self.settings.micro_supplier_order_scope,
                'query_saved_supply_on_error': self.settings.query_saved_supply_on_error,
                'micro_contractor_supply_scope': self.settings.micro_contractor_supply_scope,
                'micro_contractor_formation_scope': self.settings.micro_contractor_formation_scope,
                'micro_owner_award_scope': self.settings.micro_owner_award_scope,
                'query_saved_approval_on_error': self.settings.query_saved_approval_on_error,
                'query_saved_intake_on_error': self.settings.query_saved_intake_on_error,
                'query_saved_monthly_on_error': self.settings.query_saved_monthly_on_error,
                'query_saved_bank_monthly_on_error': self.settings.query_saved_bank_monthly_on_error,
                'query_saved_qs_learning_on_error': self.settings.query_saved_qs_learning_on_error,
                'query_saved_financing_on_error': self.settings.query_saved_financing_on_error,
                'query_saved_tender_on_error': self.settings.query_saved_tender_on_error,
                'query_saved_opportunity_on_error': self.settings.query_saved_opportunity_on_error,
                'direct_native_proposals': [r.model_dump(mode='json') for r in self.settings.direct_native_proposals],
                'micro_coverage': False, 'fallback_on_micro_failure': False}


def build_agent_client(*, request, output_directory, offline, configuration):
    """CLI factory: native background routes, with micro routes installed by a hook."""
    from integration.agent_client import GbaV1AgentClient
    from gba_construction_sim.backend.agents.contracts import AGENT_MODULE_CONTRACT_VERSION

    config = GbaModuleHostConfiguration.model_validate(configuration)
    settings = NativeRouteSettings.model_validate(config.settings)
    if offline is not True:
        raise ValueError('This local native composition requires --offline; a model host must be explicitly configured separately')
    routes = NativeRoutes(request=request, settings=settings)
    directory = Path(output_directory)
    versions = {'client': NativeRoutes.VERSION, 'skill': 'native-role-behaviors.v1',
        'prompt': 'unused-native.v1', 'contract': AGENT_MODULE_CONTRACT_VERSION,
        'method': 'native-rule-based.v1', 'model': 'offline-no-model.v1', 'strategy': 'explicit-native-composition.v1'}
    client = NativeRouteAgentClient(run_id=settings.run_id or directory.resolve().name,
        organization_roles=routes.roles, proposal_handlers={key: routes.propose for key in routes._proposals
            if not (settings.mixed_owner_invitation_scope and key == ('Owner', 'select_tender_invitees'))
            and not (settings.mixed_qs_learning_scope and key == ('QS', 'decide_monthly_operation'))},
        decision_handler=routes.decide, versions=versions,
        inbox_path=directory / 'observations.json', task_path=directory / 'tasks.sqlite')
    client.native_routes = routes
    return client


def configure_assembly(*, assembly, request, output_directory, offline, configuration):
    """Attach the actual engine without changing its module, provider or lifecycle."""
    routes = getattr(assembly.client, 'native_routes', None)
    if not isinstance(routes, NativeRoutes):
        raise ValueError('Native assembly hook requires its original declared routes')
    config = GbaModuleHostConfiguration.model_validate(configuration)
    if config.settings:
        raise ValueError('Native attachment hook accepts no hidden route overrides')
    routes.attach(assembly)
    return GbaModuleHostExtension(version=NativeRoutes.VERSION, evidence=routes.evidence, close=lambda: None)
