"""Assemble original Contractor A11 handover and final-account inputs."""
from dataclasses import dataclass
from typing import ClassVar

from integration.contractor_amendment_actions import ContractorAmendmentActionAssembler, PreparedContractorAmendment
from src.actions.contracts.contractor_closeout_objects import (
    ContractorAsBuiltBatchView, ContractorAsBuiltDesignView, ContractorAsBuiltView,
    ContractorCloseoutContractView, ContractorCloseoutDependencyView,
    ContractorCloseoutIssueView, ContractorCloseoutRemedyPlanView,
    ContractorCloseoutTaskAuthorityView, ContractorCloseoutVerificationView,
    ContractorContinuingResponsibilityView, ContractorFinalAccountView,
    ContractorHandoverProcedureView, ContractorHandoverProfileView, ContractorHandoverRequestView,
    ContractorInspectionEvidenceView, ContractorRequestableComponentView,
    ContractorVisibleDefectView, ContractorWorkRecordView, OwnerPaymentObligationView,
    contractor_closeout_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedContractorCloseout(PreparedContractorAmendment):
    ACTION_ID: ClassVar[str] = 'CONTRACTOR-A11'


class ContractorCloseoutActionAssembler(ContractorAmendmentActionAssembler):
    """Freeze actual configurations, independent checks and residual duties.

    The actual application holds its current source/authorization guard. Original
    processor checks configuration coverage, verification, defects, remedy and
    itemized settlement. Pending handover stays pending. Assembly creates no
    owner acceptance, use permission, defect closure, debt discharge or refund.
    """
    ACTION_ID = 'CONTRACTOR-A11'
    SOURCE_SCHEMAS = staticmethod(contractor_closeout_schemas)

    def build(self, context, *, contract_ref, scope_ref, as_built_refs, verification_refs,
            defect_refs, settlement_components, handover_profile_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'contract_ref': contract_ref, 'scope_ref': scope_ref, 'as_built_refs': as_built_refs,
            'verification_refs': verification_refs, 'defect_refs': defect_refs,
            'settlement_components': settlement_components, 'handover_profile_ref': handover_profile_ref},
            prepared_type=PreparedContractorCloseout, validate_sources=validate_contractor_closeout_sources)


def validate_contractor_closeout_sources(action_input, *, context, organization_id, sources):
    """Check original handover relationships without treating submission as acceptance."""
    def read(ref, schema):
        source = sources.get(ref.key())
        if not isinstance(source, schema) or source.ref.key() != ref.key():
            raise TaskConflict('Contractor closeout lacks its exact original concrete source')
        return source

    if action_input.scope_ref != context.scope:
        raise TaskConflict('Contractor closeout changes original authorized scope')
    for refs in (action_input.as_built_refs, action_input.verification_refs,
            action_input.defect_refs, action_input.settlement_components):
        unique_refs(refs)
    contract = read(action_input.contract_ref, ContractorCloseoutContractView)
    profile = read(action_input.handover_profile_ref, ContractorHandoverProfileView)
    if (contract.contractor_id != organization_id or not scope_covers(contract.scope, context.scope)
            or profile.organization_id != organization_id or profile.contract_ref.key() != contract.ref.key()
            or profile.scope != context.scope):
        raise TaskConflict('Contractor closeout changes original contract, contractor or profile scope')
    for ref in action_input.as_built_refs:
        configuration = read(ref, ContractorAsBuiltView)
        if configuration.contract_ref.key() != contract.ref.key() or configuration.author_organization_id != organization_id:
            raise TaskConflict('As-built configuration changes original contract or author organization')
        design = sources.get(configuration.design_ref.key())
        if design is not None and (not isinstance(design, ContractorAsBuiltDesignView)
                or design.contract_ref.key() != contract.ref.key()):
            raise TaskConflict('As-built configuration changes the original design contract')
        for batch_ref in configuration.product_batch_refs:
            batch = sources.get(batch_ref.key())
            if batch is not None and (not isinstance(batch, ContractorAsBuiltBatchView)
                    or batch.contract_ref.key() != contract.ref.key()):
                raise TaskConflict('As-built configuration changes the original product batch contract')
    for ref in action_input.verification_refs:
        if read(ref, ContractorCloseoutVerificationView).contract_ref.key() != contract.ref.key():
            raise TaskConflict('Closeout verification changes its original contract')
        # Independent author, content hash, applicability and unknown/failed
        # verification remain processor checks; a projection is no approval.
    for ref in action_input.defect_refs:
        defect = read(ref, ContractorVisibleDefectView)
        work = sources.get(defect.work_record_ref.key())
        if work is not None and (not isinstance(work, ContractorWorkRecordView)
                or work.physical_work_key != defect.physical_work_key):
            raise TaskConflict('Closeout defect changes the original physical work record')
        observation = sources.get(defect.observation_ref.key())
        if observation is not None and (not isinstance(observation, ContractorInspectionEvidenceView)
                or observation.work_record_ref.key() != defect.work_record_ref.key()
                or observation.physical_work_key != defect.physical_work_key
                or not scope_covers(observation.scope, defect.scope)
                or work is not None and not scope_covers(work.scope, observation.scope)):
            raise TaskConflict('Closeout defect changes its original observed work')
    for ref in action_input.settlement_components:
        component = read(ref, ContractorRequestableComponentView)
        if component.contract_ref.key() != contract.ref.key() or organization_id not in {component.debtor_id, component.payee_id}:
            raise TaskConflict('Closeout settlement changes original contract or legal parties')
        obligation = sources.get(component.obligation_ref.key())
        if obligation is not None and (not isinstance(obligation, OwnerPaymentObligationView)
                or obligation.ref != component.obligation_ref
                or component.obligation_ref not in contract.obligation_refs
                or component.ref not in obligation.component_refs
                or component.debtor_id != obligation.debtor_id or component.payee_id != obligation.payee_id
                or component.source_ref != obligation.source_ref or component.debt_ref != obligation.debt_ref):
            raise TaskConflict('Closeout settlement changes supplied original obligation lineage or coverage')
    for refs, schema in ((contract.issue_refs, ContractorCloseoutIssueView),
            (contract.continuing_responsibility_refs, ContractorContinuingResponsibilityView),
            (contract.handover_request_refs, ContractorHandoverRequestView),
            (contract.final_account_refs, ContractorFinalAccountView)):
        for ref in refs:
            source = sources.get(ref.key())
            if source is not None and (not isinstance(source, schema) or source.contract_ref.key() != contract.ref.key()):
                raise TaskConflict('Closeout substitutes another contract history or continuing responsibility')
            if isinstance(source, ContractorContinuingResponsibilityView) and source.organization_id != organization_id:
                raise TaskConflict('Closeout continuing responsibility changes original organization')
    for ref in contract.obligation_refs:
        obligation = sources.get(ref.key())
        if obligation is not None and (not isinstance(obligation, OwnerPaymentObligationView)
                or organization_id not in {obligation.debtor_id, obligation.payee_id}):
            raise TaskConflict('Closeout substitutes another legal organization obligation')
    procedure = sources.get(profile.procedure_ref.key())
    if procedure is not None and (not isinstance(procedure, ContractorHandoverProcedureView)
            or procedure.contract_ref.key() != contract.ref.key()):
        raise TaskConflict('Closeout procedure changes the original contract')
    if profile.final_account_ref is not None:
        account = sources.get(profile.final_account_ref.key())
        if account is not None and (not isinstance(account, ContractorFinalAccountView)
                or account.contract_ref.key() != contract.ref.key()):
            raise TaskConflict('Closeout final account changes the original contract')
    if profile.remedy_plan_ref is not None:
        plan = sources.get(profile.remedy_plan_ref.key())
        if plan is not None:
            if (not isinstance(plan, ContractorCloseoutRemedyPlanView) or plan.contract_ref.key() != contract.ref.key()
                    or plan.author_organization_id != organization_id):
                raise TaskConflict('Closeout remedy plan changes its original contract or planner')
            authority = sources.get(plan.task_authority_ref.key())
            if authority is not None and (not isinstance(authority, ContractorCloseoutTaskAuthorityView)
                    or authority.contract_ref.key() != contract.ref.key() or authority.organization_id != organization_id):
                raise TaskConflict('Closeout remedy task authority changes original contract or organization')
            for task in plan.tasks:
                for ref in task.dependency_refs:
                    dependency = sources.get(ref.key())
                    if dependency is not None and (not isinstance(dependency, ContractorCloseoutDependencyView)
                            or dependency.plan_ref.key() != plan.ref.key()):
                        raise TaskConflict('Closeout remedy dependency changes its original plan')
