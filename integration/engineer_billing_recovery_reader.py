"""Recover original A10 billing conditions through actual formal fee sources."""
from dataclasses import dataclass, replace
from pydantic import BaseModel, model_serializer

from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutRecoveryReader, ContractorCloseoutCurrentSelection, build_assembled_contractor_closeout_dispatcher,
)
from integration.engineer_billing_actions import EngineerBillingActionAssembler
from integration.engineer_submission_receipt_reader import EngineerSubmissionRecoverySettings, EngineerSubmissionRecoveryBindings
from integration.module_host import module_factory_descriptor
from src.actions.roles.engineer_billing import handle_engineering_fees
from src.coordination.engineer_billing_conditions import (
    CONDITIONS_CODE, CLAIM_CODE, REMINDER_CODE, LEDGER_CODE, INTERNAL_CODE,
    EngineerBillingConditionReading, engineer_original_billing_profile,
    check_engineer_billing_conditions, check_engineer_billing_claim, check_engineer_billing_reminder,
    _check_engineer_billing_history, _verify_engineer_billing_receipt_ledger,
    check_engineer_billing_internal_cost, _engineer_internal_financial_history,
)
from src.coordination.invocations import InvocationSnapshotStore
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import TaskConflict, task_digest


class EngineerBillingRecoverySettings(EngineerSubmissionRecoverySettings):
    """Actual fee sources; existing claim archival requires an explicit switch."""
    terminal_claim_enabled: bool = False
    terminal_receipt_enabled: bool = False
    terminal_internal_cost_enabled: bool = False

    @model_serializer(mode='wrap')
    def preserve_original_configuration(self, handler):
        result = handler(self)
        if not self.terminal_claim_enabled:
            result.pop('terminal_claim_enabled', None)
        if not self.terminal_receipt_enabled:
            result.pop('terminal_receipt_enabled', None)
        if not self.terminal_internal_cost_enabled:
            result.pop('terminal_internal_cost_enabled', None)
        return result


@dataclass(frozen=True)
class EngineerBillingRecoveryBindings(EngineerSubmissionRecoveryBindings):
    """Guarded actual fee sources and independent native condition/debt validation."""


@dataclass(frozen=True)
class EngineerBillingCurrentSelection(ContractorCloseoutCurrentSelection):
    """Current version of the original clause and separately authorized invocation."""


@dataclass(frozen=True)
class _EngineerBillingHistoryReading:
    context: ActionContext
    action_input: BaseModel
    reading: ActionReadView
    context_sha256: str
    input_sha256: str


class EngineerBillingRecoveryReader(ContractorCloseoutRecoveryReader):
    ACTION_ID = 'ENGINEER-A10'
    ROLE = 'Engineer'
    ASSEMBLER_TYPE = EngineerBillingActionAssembler
    SELECTION_TYPE = EngineerBillingCurrentSelection
    READING_TYPE = EngineerBillingConditionReading
    PROFILE_FACTORY = staticmethod(engineer_original_billing_profile)
    ROOT_FIELD = 'engagement_ref'
    SCOPE_FIELD = 'scope'
    READER_SCHEMA = 'engineer-billing-recovery-reader.v1'
    CONDITION_CODES = (CONDITIONS_CODE, CLAIM_CODE, REMINDER_CODE, LEDGER_CODE, INTERNAL_CODE)
    CONDITION_KINDS = {CONDITIONS_CODE: 'BillingClause', CLAIM_CODE: 'FeeClaim',
        REMINDER_CODE: 'FeeClaim', LEDGER_CODE: 'FeeClaim', INTERNAL_CODE: 'Engagement'}

    def _components(self):
        return (*super()._components(), self.assembler.registry.get(self.ACTION_ID).contract,
            handle_engineering_fees, check_engineer_billing_conditions, check_engineer_billing_claim, _check_engineer_billing_history,
            check_engineer_billing_reminder, _verify_engineer_billing_receipt_ledger,
            check_engineer_billing_internal_cost, _engineer_internal_financial_history)

    def _configuration(self):
        result = super()._configuration()
        result['billing_checks'] = module_factory_descriptor(handle_engineering_fees, 'billing_checks')
        result['billing_condition_checks'] = module_factory_descriptor(check_engineer_billing_conditions, 'billing_condition_checks')
        result['billing_claim_checks'] = module_factory_descriptor(check_engineer_billing_claim, 'billing_claim_checks')
        result['billing_history_checks'] = module_factory_descriptor(_check_engineer_billing_history, 'billing_history_checks')
        result['billing_reminder_checks'] = module_factory_descriptor(check_engineer_billing_reminder, 'billing_reminder_checks')
        result['billing_receipt_ledger_checks'] = module_factory_descriptor(_verify_engineer_billing_receipt_ledger, 'billing_receipt_ledger_checks')
        result['billing_internal_cost_checks'] = module_factory_descriptor(check_engineer_billing_internal_cost, 'billing_internal_cost_checks')
        result['billing_internal_financial_checks'] = module_factory_descriptor(_engineer_internal_financial_history, 'billing_internal_financial_checks')
        return result

    def __call__(self, check, *, history_terminal=False):
        if history_terminal and check.condition.condition_code not in {CLAIM_CODE, REMINDER_CODE, LEDGER_CODE, INTERNAL_CODE}:
            raise ValueError('Only actual claim, recognized receipt or native internal accounting queries support terminal billing archival')
        return replace(super().__call__(check, history_terminal=history_terminal),
            contract=self.assembler.registry.get(self.ACTION_ID).contract)

    def _assemble_current(self, context, action_input, history_terminal):
        if not history_terminal:
            return super()._assemble_current(context, action_input, history_terminal)
        assembler = self.assembler
        registration = assembler.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.skill is None or registration.role != self.ROLE:
            raise TaskConflict('Billing history requires the original implemented A10 contract')
        resolver = assembler._views.build_resolver(context, self.ACTION_ID, self.ROLE)
        reading = ActionReadView(context, resolver, assembler.organizations, self.ACTION_ID, self.ROLE,
            methods=assembler.methods, method_refs=registration.skill.manifest.method_refs)
        try:
            for ref in walk_references(action_input):
                reading.resolve(ref)
            return _EngineerBillingHistoryReading(context, action_input, reading,
                task_digest(context.model_dump(mode='json')), task_digest(action_input.model_dump(mode='json')))
        finally:
            reading.recheck()


def build_assembled_engineer_billing_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or EngineerBillingRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, EngineerBillingRecoveryReader):
        raise ValueError('Engineering billing recovery requires its original typed same-store reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
