"""Read original A09 claim and notice-procedure waits under actual current grants."""
from dataclasses import dataclass, replace
from pydantic import BaseModel, model_serializer

from integration import contractor_claim_actions as claim_actions
from integration.contractor_claim_actions import ContractorClaimActionAssembler
from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutRecoveryReader, build_assembled_contractor_closeout_dispatcher,
)
from integration.contractor_formation_command_reader import ContractorFormationRecoveryBindings
from integration.module_host import module_factory_descriptor
from integration.role_contract_host import RoleContractInvocation
from src.actions.contracts.common import ActionContext, Reference, StrictRecord, TextId, walk_references
from src.actions.contracts.references import ActionReadView
from src.actions.implementation import callable_implementation
from src.actions.roles import contractor_claim as claim_role
from src.coordination import contractor_claim_conditions as claim_conditions
from src.coordination.contractor_claim_conditions import (
    CLAIM_CODE, DEADLINE_CODE, ContractorClaimConditionReading, contractor_original_claim_profile,
)
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class ContractorClaimCurrentSelection:
    request: RoleContractInvocation
    history_ref: Reference


@dataclass(frozen=True)
class _ClaimHistoryReading:
    context: ActionContext
    action_input: BaseModel
    reading: ActionReadView
    context_sha256: str
    input_sha256: str


class ContractorClaimRecoverySettings(StrictRecord):
    version: TextId
    macro_version: TextId
    policy_version: TextId
    terminal_claim_enabled: bool = False

    @model_serializer(mode='wrap')
    def preserve_original_configuration(self, handler):
        result = handler(self)
        if not self.terminal_claim_enabled:
            result.pop('terminal_claim_enabled', None)
        return result


@dataclass(frozen=True)
class ContractorClaimRecoveryBindings(ContractorFormationRecoveryBindings):
    """Actual query, guarded source, independent native and successor callbacks."""


class ContractorClaimRecoveryReader(ContractorCloseoutRecoveryReader):
    ACTION_ID = 'CONTRACTOR-A09'
    ASSEMBLER_TYPE = ContractorClaimActionAssembler
    SELECTION_TYPE = ContractorClaimCurrentSelection
    READING_TYPE = ContractorClaimConditionReading
    PROFILE_FACTORY = staticmethod(contractor_original_claim_profile)
    SCOPE_FIELD = None
    READER_SCHEMA = 'contractor-claim-recovery-reader.v3'
    CONDITION_CODES = (CLAIM_CODE, DEADLINE_CODE)
    CONDITION_KINDS = {CLAIM_CODE: 'Claim', DEADLINE_CODE: 'ClaimProcedure'}

    def _claim_checks(self):
        return dict(condition_profile=self.PROFILE_FACTORY,
            history_checks=claim_conditions.check_contractor_claim_history,
            claim_checks=claim_role.handle_interfaces_and_claims,
            claim_implementation=claim_role._handle_interfaces_and_claims,
            historical_wait_checks=claim_role.recheck_original_contractor_claim_wait,
            registered_processor=self.assembler.registry.get(self.ACTION_ID).processor,
            source_checks=claim_actions.validate_contractor_claim_sources,
            source_schemas=self.assembler.SOURCE_SCHEMAS)

    def _components(self):
        return (*super()._components(), self.assembler.registry.get(self.ACTION_ID).contract,
            *self._claim_checks().values())

    def _configuration(self):
        result = super()._configuration()
        for name, callback in self._claim_checks().items():
            result[name] = module_factory_descriptor(callback, name)
        result['check_implementations'] = {name: callable_implementation(callback)
            for name, callback in self._claim_checks().items()}
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
            raise TaskConflict('Claim archive requires its original implemented Contractor contract')
        resolver = assembler._views.build_resolver(context, self.ACTION_ID, self.ROLE)
        reading = ActionReadView(context, resolver, assembler.organizations, self.ACTION_ID, self.ROLE,
            methods=assembler.methods, method_refs=registration.skill.manifest.method_refs)
        try:
            for ref in walk_references(action_input):
                reading.resolve(ref)
            return _ClaimHistoryReading(context, action_input, reading,
                task_digest(context.model_dump(mode='json')), task_digest(action_input.model_dump(mode='json')))
        finally:
            reading.recheck()


def build_assembled_contractor_claim_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or ContractorClaimRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, ContractorClaimRecoveryReader):
        raise ValueError('Claim recovery requires its original typed same-store reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
