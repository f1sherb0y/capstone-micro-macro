"""Reassemble original A10 billing condition waits through actual guarded fee sources."""
from dataclasses import dataclass, replace
from pydantic import BaseModel, model_serializer

from integration.architect_billing_actions import ArchitectBillingActionAssembler
from integration.architect_submission_receipt_reader import ArchitectSubmissionRecoverySettings, ArchitectSubmissionRecoveryBindings
from integration.contractor_closeout_recovery_reader import (
    ContractorCloseoutRecoveryReader, ContractorCloseoutCurrentSelection, build_assembled_contractor_closeout_dispatcher,
)
from integration.module_host import module_factory_descriptor
from src.actions.roles.architect_billing import handle_service_fees
from src.coordination.architect_billing_conditions import (
    CONDITIONS_CODE, CLAIM_CODE, REMINDER_CODE, INTERNAL_CODE, ArchitectBillingConditionReading, architect_original_billing_profile,
)
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.references import ActionReadView
from src.coordination.invocations import InvocationSnapshotStore
from src.coordination.tasks import TaskConflict, task_digest


class ArchitectBillingRecoverySettings(ArchitectSubmissionRecoverySettings):
    """Actual billing sources; original claim status archive requires an explicit switch."""
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
class ArchitectBillingCurrentSelection(ContractorCloseoutCurrentSelection):
    """Current version of the original deferred billing clause."""


@dataclass(frozen=True)
class ArchitectBillingRecoveryBindings(ArchitectSubmissionRecoveryBindings):
    """Actual guarded fee conditions, native authorization and successor callbacks."""


@dataclass(frozen=True)
class _ArchitectBillingHistoryReading:
    context: ActionContext
    action_input: BaseModel
    reading: ActionReadView
    context_sha256: str
    input_sha256: str


class ArchitectBillingRecoveryReader(ContractorCloseoutRecoveryReader):
    ACTION_ID = 'ARCHITECT-A10'
    ROLE = 'Architect'
    ASSEMBLER_TYPE = ArchitectBillingActionAssembler
    SELECTION_TYPE = ArchitectBillingCurrentSelection
    READING_TYPE = ArchitectBillingConditionReading
    PROFILE_FACTORY = staticmethod(architect_original_billing_profile)
    ROOT_FIELD = 'engagement_ref'
    SCOPE_FIELD = 'scope'
    READER_SCHEMA = 'architect-billing-recovery-reader.v1'
    CONDITION_CODES = (CONDITIONS_CODE, CLAIM_CODE, REMINDER_CODE, INTERNAL_CODE)
    CONDITION_KINDS = {CONDITIONS_CODE: 'BillingClause', CLAIM_CODE: 'FeeClaim', REMINDER_CODE: 'FeeClaim', INTERNAL_CODE: 'Engagement'}

    def _components(self):
        return (*super()._components(), self.assembler.registry.get(self.ACTION_ID).contract, handle_service_fees)

    def _configuration(self):
        result = super()._configuration()
        result['billing_checks'] = module_factory_descriptor(handle_service_fees, 'billing_checks')
        return result

    def __call__(self, check, *, history_terminal=False):
        if history_terminal and check.condition.condition_code not in {CLAIM_CODE, REMINDER_CODE, INTERNAL_CODE}:
            raise ValueError('Only original claim/received reminder/native internal accounting queries support terminal archival')
        selected = super().__call__(check, history_terminal=history_terminal)
        return replace(selected, contract=self.assembler.registry.get(self.ACTION_ID).contract)


    def _assemble_current(self, context, action_input, history_terminal):
        if not history_terminal:
            return super()._assemble_current(context, action_input, history_terminal)
        assembler = self.assembler
        registration = assembler.registry.get(self.ACTION_ID)
        if not registration.implemented or registration.skill is None or registration.role != self.ROLE:
            raise TaskConflict('Fee history reading requires its actual original implemented Architect contract')
        resolver = assembler._views.build_resolver(context, self.ACTION_ID, self.ROLE)
        reading = ActionReadView(context, resolver, assembler.organizations, self.ACTION_ID, self.ROLE,
            methods=assembler.methods, method_refs=registration.skill.manifest.method_refs)
        try:
            for ref in walk_references(action_input):
                reading.resolve(ref)
            return _ArchitectBillingHistoryReading(context, action_input, reading,
                task_digest(context.model_dump(mode='json')), task_digest(action_input.model_dump(mode='json')))
        finally:
            reading.recheck()


def build_assembled_architect_billing_dispatcher(*, inbox, store, assembler, select_current,
        read_guard, validate_relation, project_signal, prepare, revalidate, reader=None):
    reader = reader or ArchitectBillingRecoveryReader(assembler=assembler,
        snapshots=InvocationSnapshotStore(store), select_current=select_current)
    if not isinstance(reader, ArchitectBillingRecoveryReader):
        raise ValueError('Billing recovery requires its original typed same-store reader')
    return build_assembled_contractor_closeout_dispatcher(inbox=inbox, store=store, assembler=assembler,
        select_current=select_current, read_guard=read_guard, validate_relation=validate_relation,
        project_signal=project_signal, prepare=prepare, revalidate=revalidate, reader=reader)
