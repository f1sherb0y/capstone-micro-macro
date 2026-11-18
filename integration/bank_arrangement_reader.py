"""Read original Bank arrangement confirmations for actual Owner payment inputs."""
from integration.bank_arrangement_actions import BankArrangementActionAssembler
from integration.bank_arrangement_results import BankArrangementResultWorker, SavedBankArrangement
from integration.bank_quote_reader import BankQuoteReader, BankQuoteReaderSettings, _bind_bank_owner_sources


class BankArrangementReaderSettings(BankQuoteReaderSettings):
    """bank_request is current Bank A05 history; recipient is current Owner A06."""


class BankArrangementReader(BankQuoteReader):
    """Reuse original snapshots, seven versions, current authority and sharing checks.

    Only an original completed confirm is read. Actual signatures, registered
    terms, undrawn capacity, formation/per-draw conditions, unknown executions
    and draw permissions remain checked by the Owner handoff and application.
    No arrangement, commitment, draw instruction or paid cash is generated.
    """
    SETTINGS_TYPE = BankArrangementReaderSettings
    WORKER_TYPE = BankArrangementResultWorker
    ASSEMBLER_TYPE = BankArrangementActionAssembler
    SAVED_TYPE = SavedBankArrangement
    SOURCE_ACTION_ID = 'BANK-A05'
    RECIPIENT_ACTION_ID = 'OWN-A06'
    EXPECTED_CHOICES = frozenset({'confirm'})

    def required_shared_refs(self, saved):
        return {saved.action_input.offer_ref.key(), saved.action_input.borrower_acceptance_ref.key()}


def bind_payment_arrangement_sources(*, sources, reader, validate_reception, version):
    """Pair original Bank confirmation reading with independent actual reception."""
    if not isinstance(reader, BankArrangementReader):
        raise ValueError('Arrangement binding requires the original Bank arrangement reader')
    return _bind_bank_owner_sources(sources=sources, reader=reader, validate_reception=validate_reception, version=version,
        source_action='BANK-A05', recipient_action='OWN-A06', reader_field='read_bank_arrangement',
        validator_field='validate_payment_arrangement_reception', schema_version='v5-payment-arrangement-source-binding.v2',
        evidence_field='v5_payment_arrangement_binding')
