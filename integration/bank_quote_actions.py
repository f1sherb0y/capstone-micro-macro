"""Assemble BANK-A04 from explicitly supplied authorized quotation sources."""
from copy import deepcopy
from dataclasses import dataclass, replace

from integration.bank_credit_handoff import bank_credit_handoff_schemas, prepare_bank_credit_handoff
from integration.bank_intake_actions import BankIntakeActionAssembler, PreparedBankIntake
from src.actions.contracts.bank_credit_objects import CreditLendingCapacityView, unique_identities
from src.actions.contracts.bank_objects import FinanceApplicationView
from src.actions.contracts.bank_quote_objects import (
    QuoteCreditAssessmentView, QuoteProductView,
)
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.runner import ActionRunner
from src.coordination.tasks import task_digest
from src.organization.models import Authorization


def validate_quote_selection(action_input, *, run_id, organization_id, resolve):
    """Check source identities only; quotation eligibility stays in the processor."""
    selected = (
        (action_input.application_ref, FinanceApplicationView),
        (action_input.product_ref, QuoteProductView),
        (action_input.assessment_ref, QuoteCreditAssessmentView),
        (action_input.capacity_snapshot_ref, CreditLendingCapacityView),
        (action_input.authority_ref, Authorization),
    )
    values = []
    for ref, schema in selected:
        value = resolve(ref)
        if not isinstance(value, schema) or value.ref != ref:
            raise ValueError('Quote source selection changes its original typed reference')
        values.append(value)
    application, product, assessment, capacity, authority = values
    if (assessment.source_run_id != run_id
            or any(row.lender_id != organization_id for row in (application, product, assessment, capacity))
            or authority.organization_id != organization_id
            or assessment.application_ref != application.ref or assessment.product_ref != product.ref
            or assessment.borrower_id != application.borrower_id or assessment.scope_ref != application.scope_ref):
        raise ValueError('Quote source selection changes the original run, bank, application, product or borrower')


@dataclass(frozen=True)
class PreparedBankQuote(PreparedBankIntake):
    """An original quotation invocation, without registering an offer or reservation."""


class BankQuoteActionAssembler(BankIntakeActionAssembler):
    ACTION_ID = 'BANK-A04'
    SOURCE_SCHEMAS = staticmethod(bank_credit_handoff_schemas)

    def build(self, context, *, application_ref, assessment_ref, authority_ref, product_ref,
            pricing_candidates, capacity_snapshot_ref, funding_path_refs):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if (context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.ACTION_ID
                or self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture'):
            raise ValueError('Quote assembly requires its original BANK-A04 context and explicit source mode')
        registration = self.registry.get(self.ACTION_ID)
        if registration.role != 'Bank' or not registration.implemented or registration.skill is None:
            raise ValueError('Quote assembly requires its original Bank processor and Skill')
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
            (('pricing_candidates', pricing_candidates), ('funding_path_refs', funding_path_refs))}
        for refs in selected.values():
            unique_identities(refs)
        action_input = registration.contract.validate_input({**selected,
            'application_ref': Reference.model_validate(application_ref),
            'assessment_ref': Reference.model_validate(assessment_ref),
            'authority_ref': Reference.model_validate(authority_ref),
            'product_ref': Reference.model_validate(product_ref),
            'capacity_snapshot_ref': Reference.model_validate(capacity_snapshot_ref)})
        try:
            # Retain the complete supplied snapshot, including assessment source
            # dependencies and terms used only by output branches. Read no new
            # professional source and run no assessment or pricing method here.
            for row in projection.objects:
                reading.resolve(row.ref)
            for ref in walk_references(action_input):
                reading.resolve(ref)
            validate_quote_selection(action_input, run_id=context.run_id, organization_id=reading.organization_id,
                resolve=reading.resolve)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Quote assembly requires its original candidate set projection')
            candidates.check_context(context, registration.contract.choices)
            return PreparedBankQuote(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')), task_digest(context.model_dump(mode='json')),
                task_digest(reading.evidence()))
        finally:
            reading.recheck()

    def build_from_credit(self, context, *, credit_worker, credit_identity, credit_execution_versions,
            basis_ref, validate_history, validate_current, **quote_refs):
        """Connect selected saved review to actual recorded sources without replay."""
        from integration.bank_credit_results import BankCreditResultWorker

        if (not isinstance(credit_worker, BankCreditResultWorker) or credit_worker.ACTION_ID != 'BANK-A03'
                or credit_worker.registry is not self.registry
                or credit_worker.store.run_id != self.organizations.run_id
                or not callable(validate_history) or not callable(validate_current)):
            raise ValueError('Quote handoff requires original A03 worker and explicit current host checks')
        invocation = self.build(context, **quote_refs)
        saved = credit_worker.read_completed(credit_identity, current_context=invocation.context,
            reading=invocation.reading, execution_versions=credit_execution_versions, validate_current=validate_history)
        handoff = prepare_bank_credit_handoff(saved, context=invocation.context, reading=invocation.reading,
            basis_ref=basis_ref, assessment_ref=invocation.action_input.assessment_ref, validate_current=validate_current)
        invocation.reading.recheck()
        return {**handoff, 'invocation': replace(invocation, reading_sha256=task_digest(invocation.reading.evidence()))}

    def build_from_submitted_credit(self, context, *, credit_submission, credit_identity,
            credit_execution_versions, basis_ref, validate_history, validate_current,
            validate_receipt_relation, **quote_refs):
        """Relate confirmed review registration to actual assessment and recorded review.

        Registration acceptance preserves the original recommend/conditional/
        decline payload. The existing handoff and quote processor retain their
        rules; the application proves the raw receipt's actual native relation.
        No receipt polling, review replay or quotation registration occurs here.
        """
        from integration.bank_credit_submission import BankCreditSubmission

        if (not isinstance(credit_submission, BankCreditSubmission)
                or credit_submission.worker.registry is not self.registry
                or credit_submission.worker.store.run_id != self.organizations.run_id
                or not all(callable(callback) for callback in
                    (validate_history, validate_current, validate_receipt_relation))):
            raise ValueError('Submitted review handoff requires original A03 binding and explicit host relation validators')
        receipt = credit_submission.read_receipt(credit_identity)
        if receipt['receipt']['disposition'] != 'accepted':
            raise ValueError('Rejected native review registration cannot prove a recorded assessment')

        def validate_link(**sources):
            if (sources['reading']._resolver.source_mode != 'formal'
                    or sources['saved'].identity.as_dict() != receipt['identity']
                    or sources['saved'].record_sha256 != receipt['record_sha256']):
                raise ValueError('Review receipt changes original formal decision or current source mode')
            if validate_current(**sources) is not True:
                return False
            return validate_receipt_relation(receipt=deepcopy(receipt), **sources) is True

        handoff = self.build_from_credit(context, credit_worker=credit_submission.worker,
            credit_identity=credit_identity, credit_execution_versions=credit_execution_versions,
            basis_ref=basis_ref, validate_history=validate_history, validate_current=validate_link, **quote_refs)
        if handoff['kind'] != 'prepared':
            return handoff
        if credit_submission.read_receipt(credit_identity) != receipt:
            raise ValueError('Original review registration receipt changed during actual assessment linkage')
        invocation = handoff['invocation']
        invocation.reading.recheck()
        return {**handoff, 'provenance': {**handoff['provenance'], 'submission': deepcopy(receipt)},
            'invocation': replace(invocation, reading_sha256=task_digest(invocation.reading.evidence()))}
