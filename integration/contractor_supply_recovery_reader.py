"""Read original A05 supply commitments without substituting a new work mandate."""
from dataclasses import dataclass, replace
from pydantic import BaseModel, model_serializer

from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutRecoveryReader, build_assembled_contractor_closeout_dispatcher,
)
from integration.contractor_formation_command_reader import ContractorFormationRecoveryBindings
from integration.contractor_planning_actions import ContractorPlanningActionAssembler
from integration import contractor_planning_actions as planning_actions
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, Reference, StrictRecord, TextId, walk_references
from src.actions.contracts.references import ActionReadView
from src.actions.implementation import callable_implementation
from src.actions.roles import contractor_planning as planning_role
from src.coordination import contractor_supply_conditions as supply_conditions
from src.coordination import contractor_plan_conditions as plan_conditions
from src.coordination.contractor_supply_conditions import (
    CODE, LIMIT_CODE, RECIPIENT_CODE, CYCLE_CODE, CAPACITY_CODE, ContractorSupplyConditionReading, contractor_original_supply_profile,
)
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class ContractorSupplyCurrentSelection:
    request: RoleContractInvocation
    history_ref: Reference


@dataclass(frozen=True)
class _SupplyHistoryReading:
    context: ActionContext
    action_input: BaseModel
    reading: ActionReadView
    context_sha256: str
    input_sha256: str


class ContractorSupplyRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId
    terminal_supply_enabled: bool = False

    @model_serializer(mode='wrap')
    def preserve_original_configuration(self, handler):
        result = handler(self)
        if not self.terminal_supply_enabled:
            result.pop('terminal_supply_enabled', None)
        return result


@dataclass(frozen=True)
class ContractorSupplyRecoveryBindings(ContractorFormationRecoveryBindings):
    """Actual commitment source, current guard, native validation and successor callbacks."""


class ContractorSupplyRecoveryReader(ContractorCloseoutRecoveryReader):
    ACTION_ID = 'CONTRACTOR-A05'
    ASSEMBLER_TYPE = ContractorPlanningActionAssembler
    SELECTION_TYPE = ContractorSupplyCurrentSelection
    READING_TYPE = ContractorSupplyConditionReading
    PROFILE_FACTORY = staticmethod(contractor_original_supply_profile)
    ROOT_FIELD = None
    SCOPE_FIELD = 'authorized_scope_ref'
    READER_SCHEMA = 'contractor-supply-recovery-reader.v2'
    CONDITION_CODES = (CODE, LIMIT_CODE, RECIPIENT_CODE, CYCLE_CODE, CAPACITY_CODE)
    CONDITION_KINDS = {CODE: 'SupplyCommitment', LIMIT_CODE: ['Contract', 'WorkAuthorization'],
        RECIPIENT_CODE: 'SupplyRequirement', CYCLE_CODE: 'Dependency', CAPACITY_CODE: 'ContractorCapacity'}
    MULTI_REF_CONDITION_CODES = (RECIPIENT_CODE, CYCLE_CODE)

    def _supply_checks(self):
        return dict(condition_profile=self.PROFILE_FACTORY,
            history_checks=supply_conditions.check_contractor_supply_history,
            cycle_checks=plan_conditions.check_contractor_plan_cycle,
            capacity_checks=plan_conditions.check_contractor_plan_capacity,
            plan_history_checks=plan_conditions._check_contractor_plan_wait,
            supply_checks=planning_role.plan_work_and_supply,
            planning_implementation=planning_role._plan_work_and_supply,
            historical_wait_checks=planning_role.recheck_original_contractor_supply_wait,
            historical_cycle_checks=planning_role.recheck_original_contractor_plan_cycle,
            historical_capacity_checks=planning_role.recheck_original_contractor_plan_capacity,
            historical_capacity_comparison=planning_role.compare_capacity,
            registered_processor=self.assembler.registry.get(self.ACTION_ID).processor,
            source_checks=planning_actions.validate_contractor_planning_sources,
            source_schemas=self.assembler.SOURCE_SCHEMAS)

    def _components(self):
        return (*super()._components(), self.assembler.registry.get(self.ACTION_ID).contract,
            *self._supply_checks().values())

    def _configuration(self):
        result = super()._configuration()
        for name, callback in self._supply_checks().items():
            result[name] = module_factory_descriptor(callback, name)
        result['check_implementations'] = {name: callable_implementation(callback)
            for name, callback in self._supply_checks().items()}
        return result

    def __call__(self, check, *, history_terminal=False):
        selected = super().__call__(check, history_terminal=history_terminal)
        return replace(selected, contract=self.assembler.registry.get(self.ACTION_ID).contract)

    def _assemble_current(self, context, action_input, history_terminal):
        if not history_terminal:
            return super()._assemble_current(context, action_input, history_terminal)
        assembler = self.assembler
        registration = assembler.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.skill is None or registration.role != self.ROLE:
            raise TaskConflict('Supply archive requires its original implemented Contractor contract')
        resolver = assembler._views.build_resolver(context, self.ACTION_ID, self.ROLE)
        reading = ActionReadView(context, resolver, assembler.organizations, self.ACTION_ID, self.ROLE,
            methods=assembler.methods, method_refs=registration.skill.manifest.method_refs)
        try:
            for ref in walk_references(action_input):
                reading.resolve(ref)
            return _SupplyHistoryReading(context, action_input, reading,
                task_digest(context.model_dump(mode='json')), task_digest(action_input.model_dump(mode='json')))
        finally:
            reading.recheck()


def build_assembled_contractor_supply_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or ContractorSupplyRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, ContractorSupplyRecoveryReader):
        raise ValueError('Supply recovery requires its original typed same-store reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
