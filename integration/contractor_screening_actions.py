"""Assemble original authorized Contractor A01 inputs, including published tenders."""
from contextlib import nullcontext
from dataclasses import dataclass, replace

from integration.macro_views import AuthorizedMacroViewAssembler
from integration.bindings.gba_v1_contractor_screening import gba_contractor_screening_source_schemas
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.contractor_objects import (
    CommitmentSnapshotView, ContractorCapabilityView, InvitationView,
    OpportunityScreeningProfileView, ProcurementPackageView, QualificationView,
)
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.runner import ActionRunner
from src.coordination.tasks import task_digest


@dataclass(frozen=True)
class PreparedContractorScreening:
    context: ActionContext
    action_input: object
    runner: ActionRunner
    reading: ActionReadView
    input_sha256: str
    context_sha256: str
    reading_sha256: str

    def execute(self, *, execution_path=None):
        """Form an audited local intention; macro registration is separate."""
        if (task_digest(self.action_input.model_dump(mode='json')) != self.input_sha256
                or task_digest(self.context.model_dump(mode='json')) != self.context_sha256):
            raise ValueError('Prepared screening changed; assemble the original authorized versions again')
        self.reading.recheck()
        return self.runner.run_action(self.context, self.action_input, execution_path=execution_path)


class ContractorScreeningActionAssembler:
    """Consume exact package/invitation and private enterprise projections.

    A GbaTenderPublishedViewProvider may supply the published package/invitation.
    Qualifications and invitations are explicit host-selected sets; no visible
    object is automatically treated as eligible, no missing list is populated.
    Current business eligibility, gaps, capacity and policy remain A01 checks.
    """

    def __init__(self, *, registry, organizations, provider, macro_version,
            source_mode, methods=None, audit_sink=None, policy_version=None,
            model_version=None, decision_strategies=(), model_host=None):
        from integration.action_model_host import resolve_action_model_host

        model_version, decision_strategies = resolve_action_model_host(registry=registry,
            run_id=organizations.run_id, model_version=model_version,
            decision_strategies=decision_strategies, model_host=model_host)
        self.registry, self.organizations = registry, organizations
        self.methods, self.audit_sink = methods, audit_sink
        self.policy_version, self.model_version = policy_version, model_version
        self.decision_strategies = tuple(decision_strategies)
        self.source_mode = source_mode
        self._views = AuthorizedMacroViewAssembler(organizations, provider,
            gba_contractor_screening_source_schemas(), macro_version=macro_version, source_mode=source_mode)

    def build(self, context, *, package_ref, capability_ref, commitments_ref,
            screening_profile_ref, qualification_refs, invitation_refs):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'CONTRACTOR-A01':
            raise ValueError('Screening assembly requires the explicit Contractor A01 contract')
        if self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture':
            raise ValueError('Fixture screening projections require explicit offline_fixture execution')
        registration = self.registry.get('CONTRACTOR-A01')
        if not registration.implemented or registration.skill is None or registration.role != 'Contractor':
            raise ValueError('Screening assembly requires its actual processor and bound Contractor Skill')
        resolver = self._views.build_resolver(context, registration.action_id, registration.role)
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        reading = ActionReadView(context, resolver, self.organizations, registration.action_id,
            registration.role, methods=runner.methods, method_refs=registration.skill.manifest.method_refs)
        action_input = registration.contract.validate_input({
            'package_ref':Reference.model_validate(package_ref),
            'capability_ref':Reference.model_validate(capability_ref),
            'commitments_ref':Reference.model_validate(commitments_ref),
            'screening_profile_ref':Reference.model_validate(screening_profile_ref),
            'qualification_refs':[Reference.model_validate(ref) for ref in qualification_refs],
            'invitation_refs':[Reference.model_validate(ref) for ref in invitation_refs]})
        unique_refs(action_input.qualification_refs)
        unique_refs(action_input.invitation_refs)

        def read(ref, schema):
            value = reading.resolve(ref)
            if not isinstance(value, schema) or value.ref != ref:
                raise ValueError('Screening assembly lacks an exact original concrete projection')
            return value

        try:
            for ref in walk_references(action_input):
                reading.resolve(ref)
            package = read(action_input.package_ref, ProcurementPackageView)
            for evidence_ref in package.evidence_refs:
                reading.resolve(evidence_ref)
            # The Runner reads these through its own view. Keep the exact
            # question sources in the prepared cache as well, so a completed
            # clarify decision can communicate its original requirements later.
            for requirement_ref in package.clarification_requirement_refs:
                requirement = reading.resolve(requirement_ref)
                if getattr(requirement, 'package_ref', None) != package.ref:
                    raise ValueError('Screening clarification changes its original package version')
                for evidence_ref in requirement.evidence_refs:
                    reading.resolve(evidence_ref)
            capability = read(action_input.capability_ref, ContractorCapabilityView)
            commitments = read(action_input.commitments_ref, CommitmentSnapshotView)
            profile = read(action_input.screening_profile_ref, OpportunityScreeningProfileView)
            if any(getattr(profile,name) is not None for name in ('monthly_region_policy_ref','monthly_region_observation_ref','monthly_jv_policy_ref','monthly_jv_observation_ref')):
                for ref in context.visible_refs:reading.resolve(ref)
            if profile.outreach_limits is not None:
                observation=reading.resolve(profile.outreach_limits.observation_ref)
                reading.resolve(profile.outreach_limits.minimum_market_demand.basis_ref)
                reading.resolve(observation.market_demand.basis_ref)
                for evidence_ref in observation.evidence_refs:reading.resolve(evidence_ref)
            # Persist the exact policy evidence as part of the assembled source
            # cache. The runner has a separate reading; its reads must not be
            # mistaken for evidence retained by this prepared invocation.
            for evidence_ref in profile.evidence_refs:
                reading.resolve(evidence_ref)
            if (capability.organization_ref != commitments.organization_ref
                    or capability.organization_ref != profile.organization_ref
                    or capability.organization_ref.id != reading.organization_id
                    or context.scope.kind == 'organization' and context.scope.ref != capability.organization_ref
                    or context.scope.kind != 'organization' and context.scope != package.scope):
                raise ValueError('Screening input changes original enterprise or procurement scope')
            for ref in action_input.qualification_refs:
                if read(ref, QualificationView).organization_ref != capability.organization_ref:
                    raise ValueError('Selected qualification belongs to another enterprise')
            for ref in action_input.invitation_refs:
                invitation = read(ref, InvitationView)
                if (invitation.package_ref != package.ref or invitation.issuer_ref != package.employer_ref
                        or invitation.recipient_actor_id != context.actor_id):
                    raise ValueError('Selected invitation changes original package, issuer or recipient')
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Screening input requires its actual typed authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            reading.recheck()
            return PreparedContractorScreening(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')),
                task_digest(context.model_dump(mode='json')), task_digest(reading.evidence()))
        finally:
            reading.recheck()

    def build_gba(self, context, *, assembly, read_guard, mapping_ref, **input_refs):
        """Also reconcile the same frozen A01 inputs against the actual GBA source.

        Only the explicit GBA path requires the capacity mapping. A direct
        authorized business invocation can still report missing information or
        a nonresource branch through the original processor without this gate.
        No method, strategy or model is called during either assembly path.
        """
        from integration.bindings.gba_v1 import GbaV1Assembly

        if not isinstance(assembly, GbaV1Assembly) or not callable(read_guard):
            raise ValueError('Source-backed screening requires the actual GBA assembly and shared writer guard')
        # Use the actual engine writer guard for both authorized projections
        # and resource reconciliation; nested native reads need no second lock.
        with read_guard():
            prepared = self.build(context, **input_refs)
            registration = self.registry.get('CONTRACTOR-A01')
            raw = prepared.action_input.model_dump(mode='python')
            reconciled = assembly.prepare_contractor_screening(context=prepared.context,
                reading=prepared.reading, registration=registration, read_guard=nullcontext,
                mapping_ref=mapping_ref, **raw)
            if reconciled['kind'] != 'prepared':
                return reconciled
            if (reconciled['input_sha256'] != prepared.input_sha256
                    or reconciled['context_sha256'] != prepared.context_sha256):
                raise ValueError('GBA reconciliation substituted the original assembled screening input or context')
            prepared.reading.recheck()
            # Reconciliation resolves additional mapping and source evidence.
            # The original result worker must retain that complete read cache.
            prepared = replace(prepared, reading_sha256=task_digest(prepared.reading.evidence()))
            if reconciled['read_sha256'] != prepared.reading_sha256:
                raise ValueError('GBA reconciliation changed its original source reading')
            return {'kind':'prepared', 'invocation':prepared, 'source_record_sha256':reconciled['source_record_sha256'],
                    'capacity_input_sha256':reconciled['capacity_input_sha256'],
                    'reading_sha256':prepared.reading_sha256}
