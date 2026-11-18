"""Compose existing role applications in one native engine.

Only explicit transport ownership is composed here. Business processing remains
in the original action workers; formal state remains in the native lifecycle.
"""
from integration.bank_financing_native import BankFinancingApplication, BankFinancingSettings
from integration.contractor_tender_authority_runtime import build_authority_runtime
from integration.module_host import GbaModuleHostConfiguration, GbaModuleHostExtension, module_client_implementation
from integration.professional_intake_native import ProfessionalIntakeApplication, ProfessionalIntakeSettings
from integration.government_intake_native import GovernmentIntakeApplication, GovernmentIntakeSettings
from integration.supplier_order_native import SupplierOrderNativeApplication, SupplierOrderNativeSettings
from integration.owner_opportunity_native import OwnerOpportunityApplication, OwnerOpportunitySettings
from integration.contractor_formation_native import ContractorFormationNativeApplication, ContractorFormationNativeSettings
from integration.native_lifecycle_actions import NativeLifecycleApplication, NativeLifecycleSettings
from src.actions.contracts.common import StrictRecord
from src.coordination.tasks import TaskConflict, task_digest


class FinancingProfessionalSettings(StrictRecord):
    bank: BankFinancingSettings
    professional: ProfessionalIntakeSettings
    government: GovernmentIntakeSettings | None = None
    supplier: SupplierOrderNativeSettings | None = None
    opportunity: OwnerOpportunitySettings | None = None
    formation: ContractorFormationNativeSettings | None = None
    tender: GbaModuleHostConfiguration | None = None
    lifecycle: NativeLifecycleSettings | None = None


class FinancingProfessionalApplication:
    VERSION = 'gba-v1-financing-professional.v16'

    def _settings_digest(self):
        """Check every authority, serialize the shared large snapshot just once.

        Equality checks retain detection of mutations in any role's authority.
        No cached fingerprint or skipped runtime integrity check is used.
        """
        common = self.settings.bank.authority
        serialized = common.model_dump(mode='json')
        exclude = {}
        for name in ('bank', 'professional', 'government', 'supplier', 'opportunity', 'formation'):
            role = getattr(self.settings, name)
            if role is not None:
                if role.authority != common:
                    raise TaskConflict('Combined role authority changed')
                exclude[name] = {'authority': True}
        if self.settings.tender is not None:
            contractor = self.settings.tender.settings['source_settings']['application_settings']['owner_contractor']['contractor']
            if contractor['authority'] != serialized:
                raise TaskConflict('Combined tender authority changed')
            exclude['tender'] = {'settings': {'source_settings': {'application_settings': {
                'owner_contractor': {'contractor': {'authority': True}}}}}}
        return task_digest({'digest_version': 'shared-authority-once.v1', 'authority': serialized,
            'settings': self.settings.model_dump(mode='json', exclude=exclude)})

    def __init__(self, *, assembly, settings, request=None, output_directory=None, offline=True):
        self.assembly = assembly
        self.settings = FinancingProfessionalSettings.model_validate(settings).model_copy(deep=True)
        self._settings_sha = self._settings_digest()
        if any(s.authority != self.settings.bank.authority for s in
                (self.settings.professional, self.settings.government, self.settings.supplier,self.settings.opportunity,self.settings.formation) if s is not None):
            raise TaskConflict('Combined roles require one identical initial organization and authorization snapshot')
        client = assembly.client
        self._native_decision = client.decision_handler
        self._initial_implementation = module_client_implementation(client)
        if (client._calls or client._request_hashes or client._tender_feedback is not None
                or client.continuation_dispatcher is not None
                or client.binding_installation_blocked()):
            raise TaskConflict('Combined applications must be installed before any native request or recovered task')
        self.authority = build_authority_runtime(assembly=assembly, settings=self.settings.bank.authority)
        self.read_guard = self.authority.read_guard
        self.tender = None
        self._tender_components = None
        self.lifecycle = None
        try:
            # Both applications are built before installing any handler. They
            # remain fail-closed until the complete client topology is sealed.
            self.bank = BankFinancingApplication(assembly=assembly, settings=self.settings.bank,
                authority=self.authority, install=False)
            self.professional = ProfessionalIntakeApplication(assembly=assembly, settings=self.settings.professional,
                authority=self.authority, install=False)
            self.government = (GovernmentIntakeApplication(assembly=assembly, settings=self.settings.government,
                authority=self.authority, install=False) if self.settings.government is not None else None)
            self.supplier = (SupplierOrderNativeApplication(assembly=assembly, settings=self.settings.supplier,
                authority=self.authority, install=False) if self.settings.supplier is not None else None)
            self.opportunity = (OwnerOpportunityApplication(assembly=assembly, settings=self.settings.opportunity,
                authority=self.authority, install=False) if self.settings.opportunity is not None else None)
            self.formation = (ContractorFormationNativeApplication(assembly=assembly, settings=self.settings.formation,
                authority=self.authority, install=False) if self.settings.formation is not None else None)
            self.applications = tuple(a for a in (self.bank, self.professional, self.government, self.supplier,self.opportunity,self.formation) if a is not None)
            if self.settings.lifecycle is not None:
                self.lifecycle = NativeLifecycleApplication(assembly=assembly, authority=self.authority,
                    settings=self.settings.lifecycle)
                if self.professional.feedback is not None:
                    own = self.professional.feedback.plans
                    if ({p.plan_id for p in self.lifecycle.plans} & {p.plan_id for p in own}
                            or {task_digest(p.context.model_dump(mode='json')) for p in self.lifecycle.plans}
                                & {task_digest(p.context.model_dump(mode='json')) for p in own}):
                        raise TaskConflict('Shared event applications cannot claim the same original plan or invocation')
            self._components = (self.assembly, client, client.tasks, self.authority, self.applications, self.lifecycle)
            with client._lock:
                if module_client_implementation(client) != self._initial_implementation:
                    raise TaskConflict('Combined application construction changed the initial declared native transport')
                bindings = self._proposals()
                if set(bindings) & set(client.proposal_handlers):
                    raise TaskConflict('Combined application ownership conflicts with an existing declared proposal route')
                for (role, operation), handler in bindings.items():
                    client.bind_proposal_handler(role=role, operation=operation, handler=handler,
                        client_version=self.VERSION + ':' + role + ':' + operation)
                client.decision_handler = self.decide
                client.continuation_dispatcher = self.dispatch
                if self.settings.tender is not None:
                    if request is None or output_directory is None:
                        raise ValueError('Shared tender requires its original initialization request and output directory')
                    from integration.contractor_tender_module_host import configure_assembly as configure_tender
                    from integration.owner_invitation_native import OwnerInvitationBridge
                    from integration.qs_bid_native import QSBidNativeBridge
                    from integration.bindings.gba_v1_tender_decision import GbaTenderDecisionAdapter
                    self.tender = configure_tender(assembly=assembly, request=request,
                        output_directory=output_directory, offline=offline,
                        configuration=self.settings.tender, authority=self.authority)
                    proposal = client.proposal_handlers[('Contractor', 'consider_tender')]
                    host = proposal._recovery_host()
                    final = client.decision_handler
                    invitation = getattr(getattr(final, 'other_handler', None), '__self__', None)
                    qs = invitation if isinstance(invitation,QSBidNativeBridge) else None
                    if qs is not None:
                        invitation = getattr(qs._other_decision,'__self__',None)
                    qs_expected = self.settings.tender.settings['source_settings']['application_factory']=='integration.qs_bid_native:build_application'
                    if (not isinstance(final, GbaTenderDecisionAdapter)
                            or not isinstance(invitation, OwnerInvitationBridge)
                            or qs_expected != (qs is not None)
                            or invitation._other_decision != self.decide):
                        raise TaskConflict('Shared tender requires its declared original QS/Owner invitation and tender decision chain')
                    self._tender_components = (proposal, host, final, invitation, qs)
                self._decision_handler = client.decision_handler
                self._tender_extension = self.tender
                for application in self.applications:
                    application.seal_client_binding()
                self._implementation = module_client_implementation(client)
            self.check()
        except Exception:
            if self.tender is not None:self.tender.close()
            if self.lifecycle is not None:self.lifecycle.close()
            if getattr(self, 'professional', None) is not None:self.professional.close()
            self.authority.close()
            raise

    def _proposals(self):
        result = {}
        for application in self.applications:
            bindings = application.proposal_bindings()
            if set(bindings) & set(result):
                raise TaskConflict('Combined micro applications declare overlapping original proposal ownership')
            result.update(bindings)
        return result

    def check(self):
        client = self.assembly.client
        if (self._components != (self.assembly, client, client.tasks, self.authority, self.applications, self.lifecycle)
                or self.applications != tuple(a for a in (self.bank, self.professional, self.government, self.supplier,self.opportunity,self.formation) if a is not None)
                or self._settings_digest() != self._settings_sha
                or self.tender is not self._tender_extension
                or (self.settings.tender is None) != (self.tender is None)
                or self.read_guard != self.authority.read_guard
                or any(a.authority is not self.authority or a.registry is not self.authority.registry
                    or a.organizations is not self.authority.organizations or a.read_guard != self.read_guard
                    or a._other_decision != self._native_decision for a in self.applications)
                or module_client_implementation(client) != self._implementation
                or client.decision_handler != self._decision_handler or client.continuation_dispatcher != self.dispatch
                or any(client.proposal_handlers.get(key) != handler for key, handler in self._proposals().items())):
            raise TaskConflict('Combined roles changed their sealed routes, original native fallback or shared runtime')
        for application in self.applications:
            application._check()
        if self.lifecycle is not None:
            self.lifecycle.check()
        if self.tender is not None:
            proposal, host, final, invitation, qs = self._tender_components
            if (client.proposal_handlers.get(('Contractor', 'consider_tender')) is not proposal
                    or proposal._recovery_host() is not host or client.decision_handler is not final
                    or final.other_handler != (qs.decide if qs is not None else invitation.decide)
                    or invitation._other_decision != self.decide
                    or client.proposal_handlers.get(('Owner', 'select_tender_invitees')) != invitation.propose
                    or host.pipeline.worker.store is not client.tasks
                    or host.pipeline.worker.registry is not self.authority.registry
                    or host.pipeline.assembler.organizations is not self.authority.organizations
                    or host.pipeline.read_guard != self.read_guard
                    or invitation.bindings.registry is not self.authority.registry
                    or invitation.bindings.organizations is not self.authority.organizations
                    or invitation.bindings.read_guard != self.read_guard):
                raise TaskConflict('Shared tender changed its original handlers, authority, task store or writer guard')
            host._check(bound=True)
            invitation._check()
            if qs is not None:
                if (qs._other_decision != invitation.decide or qs.assembly is not self.assembly
                        or client.proposal_handlers.get(('QS','evaluate_bid')) != qs.propose
                        or qs.bindings.registry is not self.authority.registry
                        or qs.bindings.organizations is not self.authority.organizations
                        or qs.bindings.read_guard != self.read_guard
                        or qs.worker.store is not client.tasks):
                    raise TaskConflict('Shared QS evaluation changed its original chain, authority or task journal')
                if qs.learning is not None and client.proposal_handlers.get(('QS','decide_monthly_operation')) != qs.learning.propose:
                    raise TaskConflict('Shared QS learning lost its declared original monthly trigger')
                qs._check()

    def decide(self, request):
        with self.read_guard():
            self.check()
            key = (request.agent.role, request.decision_type)
            if self.opportunity is not None and key==('Owner','owner_project_opportunity'):
                return self.opportunity.decide(request)
            if self.formation is not None and (key==('Contractor','contract_negotiation') or (
                    self.formation.owner is not None and key==('Owner','owner_contract_award'))):
                return self.formation.decide(request)
            if key == ('Bank', 'bank_project_financing') or (
                    self.bank.monthly is not None and key==('Bank','monthly_enterprise_operation')) or (
                    self.bank.owner is not None and key == ('Owner', 'owner_financing_selection')):
                return self.bank.decide(request)
            if key in {(role, role.lower() + '_appointment_acceptance') for role in ('Architect', 'Engineer', 'QS')} or (
                    self.professional.owner is not None
                    and key in {('Owner', 'owner_select_' + role) for role in ('architect', 'engineer', 'qs')}):
                return self.professional.decide(request)
            if self.government is not None and (key == ('Government', 'government_review_assignment') or (
                    self.government.monthly is not None and key==('Government','monthly_enterprise_operation')) or (
                    self.government.approval is not None and key in {
                        ('Government', 'government_design_approval'), ('Government', 'government_completion_approval')})):
                return self.government.decide(request)
            if self.supplier is not None and (key == ('Supplier', 'supplier_order_acceptance') or (
                    self.supplier.contractor is not None and key == ('Contractor', 'contractor_supplier_selection'))):
                return self.supplier.decide(request)
            # This is the original explicitly declared native provider. An
            # exception from any owned micro branch never reaches this path.
            return self._native_decision(request)

    def dispatch(self, *, run_id, organization_id):
        with self.read_guard():
            self.check()
            if run_id != self.assembly.client.run_id or organization_id not in self.assembly.client.organization_roles:
                raise TaskConflict('Combined observation changes its original run or receiving organization')
            if self.bank.arrangement is not None:
                self.bank.arrangement.dispatch(run_id=run_id, organization_id=organization_id)
            if self.professional.appointment is not None:
                self.professional.appointment.dispatch(run_id=run_id, organization_id=organization_id)

    def evidence(self):
        with self.read_guard():
            self.check()
            return {'version': self.VERSION, 'settings_sha256': self._settings_sha,
                'shared_runtime': {'run_id': self.assembly.client.run_id,
                    'simulation_id': self.assembly.client.simulation_id,
                    'organization_snapshot_sha256': task_digest(
                        self.authority.settings.organization_snapshot.model_dump(mode='json')),
                    'task_store': 'one original native client journal', 'authority_and_registry': 'shared'},
                'bank': self.bank.evidence(), 'professional': self.professional.evidence(),
                **({'government': self.government.evidence()} if self.government is not None else {}),
                **({'supplier': self.supplier.evidence()} if self.supplier is not None else {}),
                **({'opportunity':self.opportunity.evidence()} if self.opportunity is not None else {}),
                **({'formation':self.formation.evidence()} if self.formation is not None else {}),
                **({'tender':self.tender.evidence()} if self.tender is not None else {}),
                **({'lifecycle':self.lifecycle.evidence()} if self.lifecycle is not None else {}),
                'limits': 'Composes declared financing, appointments and optional regulatory/supply/contract-terms applications. '
                    'Only the native lifecycle writes formal state. Initial cases are explicit assumptions; '
                    'assembly does not prove end-to-end execution. Detailed loan execution, service performance '
                    'and remaining C3/C4 actions remain pending.'}

    def close(self):
        try:
            if self.tender is not None:self.tender.close()
        finally:
            try:
                if self.lifecycle is not None:self.lifecycle.close()
            finally:
                try:
                    self.professional.close()
                finally:
                    self.authority.close()


def configure_assembly(*, assembly, request, output_directory, offline, configuration):
    if offline is not True:
        raise ValueError('Explicit synthetic combined-role composition requires offline mode')
    config = GbaModuleHostConfiguration.model_validate(configuration)
    assembly.client.native_routes.attach(assembly)
    app = FinancingProfessionalApplication(assembly=assembly, settings=config.settings,
        request=request, output_directory=output_directory, offline=offline)
    return GbaModuleHostExtension(version=app.VERSION, evidence=app.evidence,
        close=app.close, writer_guard=app.read_guard, checkpoint_validator=app.check)
