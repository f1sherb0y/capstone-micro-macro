"""Read original Bank cash reconciliation for actual Owner payment reception."""
from integration.bank_execution_actions import BankExecutionActionAssembler
from integration.bank_execution_results import BankExecutionResultWorker, SavedBankExecution
from integration.bank_quote_reader import BankQuoteReader, BankQuoteReaderSettings, _bind_bank_owner_sources


class BankExecutionReaderSettings(BankQuoteReaderSettings):
    """bank_request is current Bank A07 history; recipient is current Owner A06."""


class BankExecutionReader(BankQuoteReader):
    """Read only original reconcile decisions backed by their complete snapshots.

    execute or cancel_unexecuted proposals cannot prove paid cash. The existing
    Owner handoff and actual application independently check execution/receipt
    identity, unknown/failure states, partial/incremental/cumulative events and
    separate instructed, settled, credited, principal, fee and returned totals.
    Reading creates no transfer, debt reduction, cash event or paid obligation.
    """
    SETTINGS_TYPE = BankExecutionReaderSettings
    WORKER_TYPE = BankExecutionResultWorker
    ASSEMBLER_TYPE = BankExecutionActionAssembler
    SAVED_TYPE = SavedBankExecution
    SOURCE_ACTION_ID = 'BANK-A07'
    RECIPIENT_ACTION_ID = 'OWN-A06'
    EXPECTED_CHOICES = frozenset({'reconcile'})

    def required_shared_refs(self, saved):
        return {saved.action_input.arrangement_ref.key(), *(ref.key() for ref in saved.result.payload.execution_refs)}


def bind_bank_execution_sources(*, sources, reader, validate_reception, version):
    """Pair original Bank reconciliation with independent actual Owner cash reception."""
    if not isinstance(reader, BankExecutionReader):
        raise ValueError('Bank execution binding requires the original reconciliation reader')
    return _bind_bank_owner_sources(sources=sources, reader=reader, validate_reception=validate_reception, version=version,
        source_action='BANK-A07', recipient_action='OWN-A06', reader_field='read_bank_execution',
        validator_field='validate_bank_execution_reception', schema_version='v5-bank-execution-source-binding.v2',
        evidence_field='v5_bank_execution_binding')
