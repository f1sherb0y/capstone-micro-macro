"""Read actual original QS fee waits using its final authorized application views."""
from dataclasses import dataclass, replace

from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutRecoveryReader, ContractorCloseoutCurrentSelection,
    build_assembled_contractor_closeout_dispatcher,
)
from integration.engineer_billing_recovery_reader import EngineerBillingRecoveryReader, EngineerBillingRecoverySettings
from integration.module_host import module_factory_descriptor
from integration.qs_billing_actions import QSBillingActionAssembler
from integration.qs_payment_reader import QSPaymentRecoveryBindings
from src.actions.roles.qs_billing import handle_qs_fees
from src.coordination.engineer_billing_conditions import (
    _check_engineer_billing_history, check_engineer_billing_internal_cost,
    _engineer_internal_financial_history, _verify_engineer_billing_receipt_ledger,
)
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.qs_billing_conditions import (
    CONDITIONS_CODE, CLAIM_CODE, REMINDER_CODE, LEDGER_CODE, INTERNAL_CODE, CONDITION_KINDS,
    QSBillingConditionReading, QS_POLICY, qs_original_billing_profile, check_qs_billing_history,
)


class QSBillingRecoverySettings(EngineerBillingRecoverySettings):
    """QS source versions and explicit claim/receipt/internal-cost archival switches."""


@dataclass(frozen=True)
class QSBillingRecoveryBindings(QSPaymentRecoveryBindings):
    """Actual QS source guard and independent native fee, cash, credit and debt validators."""


@dataclass(frozen=True)
class QSBillingCurrentSelection(ContractorCloseoutCurrentSelection):
    """Exact current version of the original clause, fee or internal engagement."""


class QSBillingRecoveryReader(EngineerBillingRecoveryReader):
    ACTION_ID = 'QS-A10'
    ROLE = 'QS'
    ASSEMBLER_TYPE = QSBillingActionAssembler
    SELECTION_TYPE = QSBillingCurrentSelection
    READING_TYPE = QSBillingConditionReading
    PROFILE_FACTORY = staticmethod(qs_original_billing_profile)
    READER_SCHEMA = 'qs-billing-recovery-reader.v1'
    CONDITION_CODES = (CONDITIONS_CODE, CLAIM_CODE, REMINDER_CODE, LEDGER_CODE, INTERNAL_CODE)
    CONDITION_KINDS = CONDITION_KINDS

    def _components(self):
        return (*ContractorCloseoutRecoveryReader._components(self),
            self.assembler.registry.get(self.ACTION_ID).contract, QS_POLICY, *QS_POLICY.source_types.values(),
            handle_qs_fees, check_qs_billing_history, _check_engineer_billing_history,
            check_engineer_billing_internal_cost, _engineer_internal_financial_history,
            _verify_engineer_billing_receipt_ledger)

    def _configuration(self):
        result = ContractorCloseoutRecoveryReader._configuration(self)
        checks = {'billing_checks': handle_qs_fees, 'billing_history_checks': check_qs_billing_history,
            'shared_history_checks': _check_engineer_billing_history,
            'shared_internal_cost_checks': check_engineer_billing_internal_cost,
            'shared_internal_financial_checks': _engineer_internal_financial_history,
            'shared_receipt_ledger_checks': _verify_engineer_billing_receipt_ledger,
            'history_view_assembly': EngineerBillingRecoveryReader._assemble_current}
        result.update({name: module_factory_descriptor(value, name) for name, value in checks.items()})
        result['source_types'] = {name: module_factory_descriptor(schema, name)
            for name, schema in QS_POLICY.source_types.items()}
        return result

    def __call__(self, check, *, history_terminal=False):
        if history_terminal and check.condition.condition_code not in {CLAIM_CODE, REMINDER_CODE, LEDGER_CODE, INTERNAL_CODE}:
            raise ValueError('QS billing terminal archival requires an actual claim, receipt or internal-cost wait')
        selected = ContractorCloseoutRecoveryReader.__call__(self, check, history_terminal=history_terminal)
        return replace(selected, contract=self.assembler.registry.get(self.ACTION_ID).contract)


def build_assembled_qs_billing_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or QSBillingRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, QSBillingRecoveryReader):
        raise ValueError('QS fee recovery requires its original typed same-store reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
