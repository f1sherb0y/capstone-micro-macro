"""Build BANK-A02 from an explicitly selected, currently authorized application."""
from dataclasses import dataclass, replace

from integration.action_model_host import resolve_action_model_host
from integration.macro_views import AuthorizedMacroViewAssembler
from src.actions.contracts.bank_objects import FinanceApplicationView, FinanceProductProfileView, bank_intake_schemas
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.runner import ActionRunner
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class PreparedBankIntake:
    context: ActionContext
    action_input: object
    runner: ActionRunner
    reading: ActionReadView
    input_sha256: str
    context_sha256: str
    reading_sha256: str

    def execute(self, *, execution_path=None):
        if (task_digest(self.action_input.model_dump(mode='json')) != self.input_sha256
                or task_digest(self.context.model_dump(mode='json')) != self.context_sha256
                or task_digest(self.reading.evidence()) != self.reading_sha256):
            raise TaskConflict('Prepared bank intake changed its original input, context or source snapshot')
        self.reading.recheck()
        return self.runner.run_action(self.context, self.action_input, execution_path=execution_path)


class BankIntakeActionAssembler:
    ACTION_ID = 'BANK-A02'
    SOURCE_SCHEMAS = staticmethod(bank_intake_schemas)

    def __init__(self, *, registry, organizations, provider, macro_version, source_mode,
            methods=None, audit_sink=None, policy_version=None, model_version=None,
            decision_strategies=(), model_host=None):
        model_version, bindings = resolve_action_model_host(registry=registry,
            run_id=organizations.run_id, model_version=model_version,
            decision_strategies=decision_strategies, model_host=model_host)
        self.registry, self.organizations, self.provider = registry, organizations, provider
        self.macro_version, self.source_mode = macro_version, source_mode
        self.methods, self.audit_sink, self.policy_version = methods, audit_sink, policy_version
        self.model_version, self.decision_strategies = model_version, bindings
        self._views = AuthorizedMacroViewAssembler(organizations, provider, self.SOURCE_SCHEMAS(),
            macro_version=macro_version, source_mode=source_mode)

    def build(self, context, *, application_ref):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if (context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'BANK-A02'
                or self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture'):
            raise ValueError('Bank intake requires the original A02 context and explicit source mode')
        registration = self.registry.get('BANK-A02')
        if registration.role != 'Bank' or not registration.implemented or registration.skill is None:
            raise ValueError('Bank intake requires its original implemented processor and Skill')
        resolver = self._views.build_resolver(context, registration.action_id, registration.role)
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        reading = ActionReadView(context, resolver, self.organizations, registration.action_id,
            registration.role, methods=runner.methods, method_refs=registration.skill.manifest.method_refs)
        try:
            ref = Reference.model_validate(application_ref)
            application = reading.resolve(ref)
            if (not isinstance(application, FinanceApplicationView) or application.ref.key() != ref.key()
                    or application.lender_id != reading.organization_id):
                raise ValueError('Bank intake substitutes the original application version or lender')
            action_input = registration.contract.validate_input({'application_ref': application.ref,
                'borrower_id': application.borrower_id, 'applicant_authority_ref': application.applicant_authority_ref,
                'requested': application.requested, 'purpose_ref': application.purpose_ref,
                'product_candidates': application.product_candidates, 'disclosure_refs': application.disclosure_refs})
            for source_ref in walk_references(action_input):
                reading.resolve(source_ref)
            original_sources = [application, reading.resolve(application.borrower_ref),
                reading.resolve(application.purpose_ref), reading.resolve(application.applicant_authority_ref),
                reading.resolve(application.applicant_function_ref)]
            # Required conditions can appear only in the output. Save their
            # original supplied versions before execution, without evaluating them.
            for product_ref in application.product_candidates:
                product = reading.resolve(product_ref)
                if not isinstance(product, FinanceProductProfileView) or product.ref != product_ref:
                    raise ValueError('Bank intake product candidate changes its original source schema')
                original_sources.append(product)
                for condition_ref in product.required_condition_refs:
                    original_sources.append(reading.resolve(condition_ref))
            for source in original_sources:
                for evidence_ref in walk_references(source):
                    if evidence_ref.kind == 'Evidence':
                        reading.resolve(evidence_ref)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Bank intake requires the original candidate set projection')
            candidates.check_context(context, registration.contract.choices)
            return PreparedBankIntake(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')), task_digest(context.model_dump(mode='json')),
                task_digest(reading.evidence()))
        finally:
            reading.recheck()

    def build_from_owner_application(self, context, *, owner_decision, receipt_ref,
            validate_reception, application_ref):
        """Link an actual registered application to the original Owner apply result."""
        from integration.owner_financing_bank_intake_handoff import validate_received_owner_application

        if self.ACTION_ID != 'BANK-A02':
            raise ValueError('Owner application reception is only available at Bank intake')
        prepared = self.build(context, application_ref=application_ref)
        validate_received_owner_application(owner_decision, prepared=prepared,
            receipt_ref=receipt_ref, validate_reception=validate_reception)
        return replace(prepared, reading_sha256=task_digest(prepared.reading.evidence()))

    def _prepare_supplied_snapshot(self, context, *, input_values, prepared_type, validate_sources,
            validate_source_history=None):
        """Prepare an explicit bank input against one complete supplied source view."""
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if (context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.ACTION_ID
                or self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture'):
            raise ValueError('Bank assembly requires its original action context and explicit source mode')
        registration = self.registry.get(self.ACTION_ID)
        if registration.role != 'Bank' or not registration.implemented or registration.skill is None:
            raise ValueError('Bank assembly requires its original implemented processor and Skill')
        projection = self._views.assemble(context, self.ACTION_ID, 'Bank')
        resolver = ReferenceResolver(context.run_id, source_mode=self.source_mode, schemas=self.SOURCE_SCHEMAS())
        for row in projection.objects:
            resolver.register_projection(row.ref, row.value)
        resolver.freeze_read(context.read_token, [row.ref for row in projection.objects])
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'Bank',
            methods=runner.methods, method_refs=registration.skill.manifest.method_refs)
        action_input = registration.contract.validate_input(input_values)
        try:
            # Preserve supplied output-only dependencies and source evidence;
            # business branches and all method calculations stay in the processor.
            for row in projection.objects:
                reading.resolve(row.ref)
            for ref in walk_references(action_input):
                reading.resolve(ref)
            validate_sources(action_input, organization_id=reading.organization_id, resolve=reading.resolve)
            if validate_source_history is not None:
                validate_source_history(action_input, organization_id=reading.organization_id, sources=reading._reads)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Bank assembly requires its original candidate set projection')
            candidates.check_context(context, registration.contract.choices)
            return prepared_type(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')), task_digest(context.model_dump(mode='json')),
                task_digest(reading.evidence()))
        finally:
            reading.recheck()

    def build_result_reading(self, context):
        """Create a current same-action read boundary for explicitly selected history."""
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if (context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.ACTION_ID
                or self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture'):
            raise ValueError('Bank historical reading requires its explicit original action and source mode')
        resolver = self._views.build_resolver(context, self.ACTION_ID, 'Bank')
        return ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'Bank')
