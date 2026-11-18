"""Read original A06 readiness waits under current source grants."""
from dataclasses import dataclass
from pydantic import model_serializer

from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutRecoveryReader, build_assembled_contractor_closeout_dispatcher,
)
from integration.contractor_formation_command_reader import ContractorFormationRecoveryBindings
from integration.contractor_readiness_actions import ContractorReadinessActionAssembler
from integration import contractor_readiness_actions as readiness_actions
from integration.contractor_supply_recovery_reader import ContractorSupplyRecoveryReader, ContractorSupplyCurrentSelection
from integration.module_host import module_factory_descriptor
from src.actions.contracts.common import StrictRecord, TextId
from src.actions.implementation import callable_implementation
from src.actions.roles import contractor_readiness as readiness_role
from src.coordination import contractor_readiness_conditions as readiness_conditions
from src.coordination.contractor_readiness_conditions import (
    CYCLE_CODE, REPLACEMENT_CODE, STATE_CODE, ContractorReadinessConditionReading, contractor_original_readiness_profile,
)
from src.coordination.invocations import InvocationSnapshotStore


class ContractorReadinessRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId
    terminal_readiness_enabled: bool = False

    @model_serializer(mode='wrap')
    def preserve_original_configuration(self, handler):
        result = handler(self)
        if not self.terminal_readiness_enabled:
            result.pop('terminal_readiness_enabled', None)
        return result


@dataclass(frozen=True)
class ContractorReadinessCurrentSelection(ContractorSupplyCurrentSelection):
    """Actual first waited task query and independently selected readiness input."""


@dataclass(frozen=True)
class ContractorReadinessRecoveryBindings(ContractorFormationRecoveryBindings):
    """Actual guarded task query, native validation and successor callbacks."""


class ContractorReadinessRecoveryReader(ContractorSupplyRecoveryReader):
    ACTION_ID = 'CONTRACTOR-A06'
    ASSEMBLER_TYPE = ContractorReadinessActionAssembler
    SELECTION_TYPE = ContractorReadinessCurrentSelection
    READING_TYPE = ContractorReadinessConditionReading
    PROFILE_FACTORY = staticmethod(contractor_original_readiness_profile)
    ROOT_FIELD = 'task_ref'
    SCOPE_FIELD = None
    READER_SCHEMA = 'contractor-readiness-recovery-reader.v3'
    CONDITION_CODES = (CYCLE_CODE, REPLACEMENT_CODE, STATE_CODE)
    CONDITION_KINDS = {code: 'Task' for code in CONDITION_CODES}
    MULTI_REF_CONDITION_CODES = (CYCLE_CODE,)

    def _readiness_checks(self):
        return dict(condition_profile=self.PROFILE_FACTORY,
            history_checks=readiness_conditions.check_contractor_readiness_history,
            readiness_checks=readiness_role.check_task_readiness,
            registered_processor=self.assembler.registry.get(self.ACTION_ID).processor,
            source_checks=readiness_actions.validate_contractor_readiness_sources,
            source_schemas=self.assembler.SOURCE_SCHEMAS)

    def _components(self):
        return (*ContractorCloseoutRecoveryReader._components(self),
            self.assembler.registry.get(self.ACTION_ID).contract, *self._readiness_checks().values())

    def _configuration(self):
        result = ContractorCloseoutRecoveryReader._configuration(self)
        for name, callback in self._readiness_checks().items():
            result[name] = module_factory_descriptor(callback, name)
        result['check_implementations'] = {name: callable_implementation(callback)
            for name, callback in self._readiness_checks().items()}
        return result


def build_assembled_contractor_readiness_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or ContractorReadinessRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, ContractorReadinessRecoveryReader):
        raise ValueError('Readiness recovery requires its original typed same-store reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
