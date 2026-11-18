"""Bank compatibility binding over the shared original-journal V7 bridge."""
from dataclasses import dataclass

from integration.execution_wait_recovery import ExecutionWaitRecoveryBridge


@dataclass(frozen=True)
class BankExecutionWaitRecoveryBridge(ExecutionWaitRecoveryBridge):
    role: str = 'Bank'
