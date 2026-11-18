"""Read actual original Contractor measurement applications under the source guard."""
from dataclasses import dataclass
from pydantic import model_serializer

from integration import contractor_payment_actions as payment_actions
from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutRecoveryReader, build_assembled_contractor_closeout_dispatcher,
)
from integration.contractor_formation_command_reader import ContractorFormationRecoveryBindings
from integration.contractor_payment_actions import ContractorPaymentActionAssembler
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import Reference, StrictRecord, TextId
from src.actions.contracts import contractor_payment_objects as payment_objects
from src.actions.implementation import callable_implementation
from src.actions.roles import contractor_payment as payment_role
from src.coordination import contractor_measurement_conditions as measurement_conditions
from src.coordination.contractor_measurement_conditions import (
    CODE, ContractorMeasurementConditionReading, contractor_original_measurement_profile,
)
from src.coordination.invocations import InvocationSnapshotStore


@dataclass(frozen=True)
class ContractorMeasurementCurrentSelection:
    request: RoleContractInvocation
    history_ref: Reference


class ContractorMeasurementRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId
    terminal_measurement_enabled: bool = False

    @model_serializer(mode='wrap')
    def preserve_original_configuration(self, handler):
        result = handler(self)
        if not self.terminal_measurement_enabled:
            result.pop('terminal_measurement_enabled', None)
        return result


@dataclass(frozen=True)
class ContractorMeasurementRecoveryBindings(ContractorFormationRecoveryBindings):
    """Actual selection, native validation and independent successor callbacks."""


class ContractorMeasurementRecoveryReader(ContractorCloseoutRecoveryReader):
    ACTION_ID = 'CONTRACTOR-A10'
    ASSEMBLER_TYPE = ContractorPaymentActionAssembler
    SELECTION_TYPE = ContractorMeasurementCurrentSelection
    READING_TYPE = ContractorMeasurementConditionReading
    PROFILE_FACTORY = staticmethod(contractor_original_measurement_profile)
    SCOPE_FIELD = None
    READER_SCHEMA = 'contractor-measurement-recovery-reader.v4'
    CONDITION_CODES = (CODE,)
    CONDITION_KINDS = {CODE: 'MeasurementApplication'}

    def _measurement_checks(self):
        return dict(condition_profile=self.PROFILE_FACTORY,
            history_checks=measurement_conditions.check_contractor_measurement_history,
            payment_checks=payment_role.request_measurement_and_cash,
            work_event_checks=payment_objects.validate_contractor_measurement_work_events,
            payment_processor=self.assembler.registry.get(self.ACTION_ID).processor,
            source_checks=payment_actions.validate_contractor_payment_sources,
            source_schemas=self.assembler.SOURCE_SCHEMAS)

    def _components(self):
        return (*super()._components(), self.assembler.registry.get(self.ACTION_ID).contract,
            *self._measurement_checks().values())

    def _configuration(self):
        result = super()._configuration()
        for name, callback in self._measurement_checks().items():
            result[name] = module_factory_descriptor(callback, name)
        result['check_implementations'] = {name: callable_implementation(callback)
            for name, callback in self._measurement_checks().items()}
        return result


def build_assembled_contractor_measurement_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or ContractorMeasurementRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, ContractorMeasurementRecoveryReader):
        raise ValueError('Measurement recovery requires its original typed reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
