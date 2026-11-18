"""Build commercial A12 invocations from exact authorized host projections."""
from dataclasses import dataclass

from integration.macro_views import AuthorizedMacroViewAssembler
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.contractor_continuation_objects import contractor_continuation_schemas
from src.actions.contracts.supplier_continuation_objects import supplier_continuation_schemas, supplier_continuation_types
from src.actions.contracts.commercial_continuation_objects import commercial_continuation_types
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.runner import ActionRunner
from src.coordination.tasks import task_digest


@dataclass(frozen=True)
class PreparedCommercialAction:
    context: ActionContext
    action_input: object
    runner: ActionRunner
    reading: ActionReadView
    input_sha256: str
    context_sha256: str
    reading_sha256: str

    def execute(self, *, execution_path=None):
        """Execute the assembled invocation; formal submission remains separate."""
        if (task_digest(self.action_input.model_dump(mode='json')) != self.input_sha256
                or task_digest(self.context.model_dump(mode='json')) != self.context_sha256
                or task_digest(self.reading.evidence()) != self.reading_sha256
                or self.runner.references is not self.reading._resolver
                or self.runner.organizations is not self.reading._organizations):
            raise ValueError('Prepared commercial invocation changed; assemble a fresh invocation')
        self.reading.check_method_context(self.context, self.context.contract_ref.id)
        self.reading.recheck()
        return self.runner.run_action(self.context, self.action_input, execution_path=execution_path)


class CommercialActionAssembler:
    """A fixed host provider supplies facts; this class only produces inputs.

    No facts, authority, evidence or execution receipts are synthesized. Each
    supported action has its own closed schemas and persistent read-point
    checks. Formal and fixture sources are explicit, with no fallback between
    them. The chosen profile must already exist in the authorized host view.
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
        self._types = {'CONTRACTOR-A12':commercial_continuation_types(),
                       'SUPPLIER-A12':supplier_continuation_types()}
        self._views = {
            action_id:AuthorizedMacroViewAssembler(organizations,provider,schemas(),
                macro_version=macro_version,source_mode=source_mode)
            for action_id,schemas in (
                ('CONTRACTOR-A12',contractor_continuation_schemas),
                ('SUPPLIER-A12',supplier_continuation_schemas))}
        self.source_mode = source_mode

    def read_sources(self, context):
        """Read current authorized projections without creating or running a decision."""
        context = ActionContext.model_validate(context).model_copy(deep=True)
        action_id = context.contract_ref.id
        if context.contract_ref.kind != 'ActionContract' or action_id not in self._views:
            raise ValueError('Commercial input assembly supports only explicit Contractor/Supplier A12 contracts')
        if (self.source_mode == 'fixture') != (context.execution_mode == 'offline_fixture'):
            raise ValueError('Commercial projections require the matching explicit execution/source mode')
        registration = self.registry.get(action_id)
        if not registration.implemented or registration.skill is None:
            raise ValueError('Commercial action requires its registered processor and bound Skill')
        views = self._views[action_id]
        projection = views.assemble(context, action_id, registration.role)
        resolver = ReferenceResolver(context.run_id, source_mode=self.source_mode, schemas=views.schemas)
        for row in projection.objects:
            resolver.register_projection(row.ref, row.value)
        resolver.freeze_read(context.read_token, [row.ref for row in projection.objects])
        runner = ActionRunner(self.registry,organizations=self.organizations,references=resolver,
            methods=self.methods,audit_sink=self.audit_sink,policy_version=self.policy_version,
            model_version=self.model_version,decision_strategies=self.decision_strategies)
        reading = ActionReadView(context,resolver,self.organizations,action_id,registration.role,
            methods=runner.methods,method_refs=registration.skill.manifest.method_refs)
        # Retain supplied output dependencies and original execution/transfer
        # sources even when the selected processor branch does not read them.
        for row in projection.objects:
            reading.resolve(row.ref)
        reading.recheck()
        return runner, reading

    def build(self, context, *, profile_ref):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        profile_ref = Reference.model_validate(profile_ref)
        runner, reading = self.read_sources(context)
        action_id = context.contract_ref.id
        registration = self.registry.get(action_id)
        types = self._types[action_id]
        profile = reading.resolve(profile_ref)
        if not isinstance(profile,types['ContinuationProfile']) or profile.ref != profile_ref:
            raise ValueError('Commercial input requires its concrete current profile projection')
        state, basis = reading.resolve(profile.state_ref), reading.resolve(profile.basis_ref)
        if not isinstance(state,types['ContinuationState']) or not isinstance(basis,types['ContinuationBasis']):
            raise ValueError('Commercial input requires typed original state and authority basis')
        if (profile.scope != context.scope or state.scope != context.scope
                or profile.organization_id != reading.organization_id or state.organization_id != reading.organization_id
                or state.run_id != context.run_id or profile.actor_id != context.actor_id
                or profile.function_ref != context.function_ref or profile.authority_ref not in context.authorization_refs
                or basis.organization_id != reading.organization_id or basis.state_ref != state.ref):
            raise ValueError('Commercial input changes original firm, actor, function, authority, scope or state')
        for ref in state.execution_refs:
            execution = reading._reads.get(ref.key())
            if execution is not None and (not isinstance(execution, types['ContinuationExecution'])
                    or execution.organization_id != reading.organization_id or execution.run_id != context.run_id
                    or execution.state_ref.key()[:2] != state.ref.key()[:2]):
                raise ValueError('Commercial history changes the original firm, run or physical state')
            if execution is not None and execution.business_key == profile.business_key:
                original = reading._reads.get(execution.profile_ref.key())
                if original is not None and (not isinstance(original, types['ContinuationProfile'])
                        or original.state_ref != execution.state_ref or original.organization_id != execution.organization_id
                        or original.scope != execution.scope or original.business_key != execution.business_key):
                    raise ValueError('Commercial execution substitutes its original profile or state version')
        unique_refs(basis.evidence_refs)
        fields = {'scope_ref':context.scope,'authority_basis_refs':basis.evidence_refs,
            'continuation_profile_ref':profile.ref,'obligation_refs':state.obligation_refs,
            'observation_refs':state.observation_refs}
        if action_id == 'CONTRACTOR-A12':
            fields.update(resource_commitment_refs=state.commitment_refs,material_position_refs=state.material_refs)
        else:
            fields.update(commitment_refs=state.commitment_refs,inventory_refs=state.material_refs,
                work_in_progress_refs=state.work_in_progress_refs,shipment_refs=state.shipment_refs)
        action_input = registration.contract.validate_input(fields)
        for ref in walk_references(action_input): reading.resolve(ref)
        candidates = reading.resolve(context.candidate_set_ref)
        if not isinstance(candidates,CandidateSet):
            raise ValueError('Commercial action requires its typed authorized candidate set')
        candidates.check_context(context,registration.contract.choices)
        for candidate in candidates.candidates: reading.resolve(candidate.ref)
        reading.recheck()
        return PreparedCommercialAction(context,action_input,runner,reading,
            task_digest(action_input.model_dump(mode='json')),
            task_digest(context.model_dump(mode='json')),task_digest(reading.evidence()))
