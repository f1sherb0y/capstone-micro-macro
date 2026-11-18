"""Prepare BANK-A03 against one complete supplied, authorized credit source snapshot."""
from copy import deepcopy
from dataclasses import dataclass, replace

from integration.bank_intake_actions import BankIntakeActionAssembler, PreparedBankIntake
from integration.bank_intake_handoff import bank_intake_handoff_schemas, prepare_bank_intake_handoff
from src.actions.contracts.bank_credit_objects import CreditRiskMethodView, unique_identities
from src.actions.contracts.bank_objects import FinanceApplicationView, FinanceProductProfileView
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.runner import ActionRunner
from src.coordination.tasks import task_digest


@dataclass(frozen=True)
class PreparedBankCredit(PreparedBankIntake):
    """An original risk-review invocation; indicative ranges never become approved finance."""


class BankCreditActionAssembler(BankIntakeActionAssembler):
    ACTION_ID = 'BANK-A03'
    SOURCE_SCHEMAS = staticmethod(bank_intake_handoff_schemas)

    def build(self, context, *, application_ref, disclosures, forecast_refs, debt_refs,
            permit_risk_refs, risk_method_ref, product_ref):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if (context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.ACTION_ID
                or self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture'):
            raise ValueError('Credit assembly requires its explicit original BANK-A03 context and source mode')
        registration = self.registry.get(self.ACTION_ID)
        if registration.role != 'Bank' or not registration.implemented or registration.skill is None:
            raise ValueError('Credit assembly requires its original Bank processor and Skill')
        # Read once. The source host supplies the exact authorized snapshot;
        # forecasts, portfolios, debts and professional methods are not inferred.
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
        selected = {name: [Reference.model_validate(ref) for ref in values] for name, values in
            (('disclosures', disclosures), ('forecast_refs', forecast_refs),
             ('debt_refs', debt_refs), ('permit_risk_refs', permit_risk_refs))}
        for refs in selected.values():
            unique_identities(refs)
        action_input = registration.contract.validate_input({**selected,
            'application_ref': Reference.model_validate(application_ref),
            'risk_method_ref': Reference.model_validate(risk_method_ref), 'product_ref': Reference.model_validate(product_ref)})
        try:
            # Preserve all explicitly supplied source projections, including
            # output condition/rule dependencies and method inputs. No calculator
            # runs here, and no extra professional source is queried.
            for row in projection.objects:
                reading.resolve(row.ref)
            for ref in walk_references(action_input):
                reading.resolve(ref)
            application = reading.resolve(action_input.application_ref)
            product = reading.resolve(action_input.product_ref)
            risk = reading.resolve(action_input.risk_method_ref)
            if (not isinstance(application, FinanceApplicationView) or application.ref != action_input.application_ref
                    or not isinstance(product, FinanceProductProfileView) or product.ref != action_input.product_ref
                    or not isinstance(risk, CreditRiskMethodView) or risk.ref != action_input.risk_method_ref
                    or any(row.lender_id != reading.organization_id for row in (application, product, risk))
                    or risk.product_ref != product.ref or product.ref not in application.product_candidates):
                raise ValueError('Credit source selection changes its original application, lender, product or risk method')
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Credit assembly requires its original candidate set projection')
            candidates.check_context(context, registration.contract.choices)
            return PreparedBankCredit(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')), task_digest(context.model_dump(mode='json')),
                task_digest(reading.evidence()))
        finally:
            reading.recheck()

    def build_from_intake(self, context, *, intake_worker, intake_identity, intake_execution_versions,
            basis_ref, validate_history, validate_current, **credit_refs):
        """Relate explicitly selected history to actual intake; do not rerun A02."""
        from integration.bank_intake_results import BankIntakeResultWorker

        if (not isinstance(intake_worker, BankIntakeResultWorker) or intake_worker.ACTION_ID != 'BANK-A02'
                or intake_worker.registry is not self.registry
                or intake_worker.store.run_id != self.organizations.run_id
                or not callable(validate_history) or not callable(validate_current)):
            raise ValueError('Credit handoff requires its original A02 worker and explicit current host checks')
        invocation = self.build(context, **credit_refs)
        saved = intake_worker.read_completed(intake_identity, current_context=invocation.context,
            reading=invocation.reading, execution_versions=intake_execution_versions, validate_current=validate_history)
        handoff = prepare_bank_intake_handoff(saved, context=invocation.context, reading=invocation.reading,
            basis_ref=basis_ref, application_ref=invocation.action_input.application_ref,
            product_ref=invocation.action_input.product_ref, validate_current=validate_current)
        if handoff['kind'] != 'prepared':
            return handoff
        invocation.reading.recheck()
        return {**handoff, 'invocation': replace(invocation, reading_sha256=task_digest(invocation.reading.evidence()))}

    def build_from_submitted_intake(self, context, *, intake_submission, intake_identity,
            intake_execution_versions, basis_ref, validate_history, validate_current,
            validate_receipt_relation, **credit_refs):
        """Bind independently observed intake to the original confirmed native receipt.

        No polling, task creation, approval or A02 replay occurs here. The
        application must prove which actual native record/event the raw reply
        identifies; an accepted transport envelope alone is insufficient.
        """
        from integration.bank_intake_submission import BankIntakeSubmission

        if (not isinstance(intake_submission, BankIntakeSubmission)
                or not all(callable(callback) for callback in
                    (validate_history, validate_current, validate_receipt_relation))):
            raise ValueError('Submitted intake handoff requires the original binding and actual receipt-to-record validator')
        receipt = intake_submission.read_receipt(intake_identity)
        if receipt['receipt']['disposition'] != 'accepted':
            raise ValueError('Rejected native intake cannot become an accepted review source')

        def validate_link(**sources):
            if sources['reading']._resolver.source_mode != 'formal':
                raise ValueError('Submitted intake handoff requires actual formal current sources')
            if (sources['saved'].identity.as_dict() != receipt['identity']
                    or sources['saved'].record_sha256 != receipt['record_sha256']):
                raise ValueError('Native intake receipt changes the original saved decision or task')
            if validate_current(**sources) is not True:
                return False
            return validate_receipt_relation(receipt=deepcopy(receipt), **sources) is True

        handoff = self.build_from_intake(context, intake_worker=intake_submission.worker,
            intake_identity=intake_identity, intake_execution_versions=intake_execution_versions,
            basis_ref=basis_ref, validate_history=validate_history, validate_current=validate_link, **credit_refs)
        if handoff['kind'] != 'prepared':
            return handoff
        if intake_submission.read_receipt(intake_identity) != receipt:
            raise ValueError('Original native intake receipt changed during actual source linkage')
        invocation = handoff['invocation']
        invocation.reading.recheck()
        return {**handoff, 'provenance': {**handoff['provenance'], 'submission': deepcopy(receipt)},
            'invocation': replace(invocation, reading_sha256=task_digest(invocation.reading.evidence()))}
