"""Persist original BANK-A08 monitoring evidence without formal notice/enforcement effects."""
from dataclasses import dataclass

from integration.bank_intake_results import BankIntakeResultWorker, SavedBankIntake
from integration.bank_monitoring_actions import PreparedBankMonitoring, validate_monitoring_selection
from src.actions.contracts.bank_monitoring_objects import bank_monitoring_schemas
from src.actions.contracts.common import walk_references
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class SavedBankMonitoring(SavedBankIntake):
    """Original local monitoring output, not service, restriction or release evidence."""


class BankMonitoringResultWorker(BankIntakeResultWorker):
    SCHEMA = 'bank-monitoring-result.v1'
    ACTION_ID = 'BANK-A08'
    PREPARED_TYPE = PreparedBankMonitoring
    RESULT_TABLE = 'bank_monitoring_results'
    WAIT_KIND = 'manual_bank_monitoring_result_review'
    EXECUTION_ERROR_CODE = 'bank_monitoring_execution_exception'
    SOURCE_SCHEMAS = staticmethod(bank_monitoring_schemas)
    SAVED_TYPE = SavedBankMonitoring
    READ_ACTION_IDS = frozenset({'BANK-A08'})

    def _validate_primary_sources(self, snapshot, identity, originals):
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(snapshot['action_input'])
        for ref in walk_references(action_input):
            if ref.key() not in originals:
                raise TaskConflict('Saved monitoring decision lacks an original selected input source')
        try:
            validate_monitoring_selection(action_input, organization_id=identity.organization_id,
                resolve=lambda ref: originals.get(ref.key()))
        except ValueError as error:
            raise TaskConflict('Saved monitoring decision substitutes original bank, facility, covenant or notice') from error
