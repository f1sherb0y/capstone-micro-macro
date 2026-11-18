"""Assemble original OWN-A12 inputs without recording acceptance or settlement."""
from dataclasses import dataclass
from typing import ClassVar

from integration.owner_observation_actions import OwnerObservationActionAssembler, PreparedOwnerObservation
from src.actions.contracts.owner_closeout_objects import (
    ContractorCloseoutVerificationView, ContractorInspectionEvidenceView,
    ContractorVisibleDefectView, ContractorWorkRecordView,
    OwnerCloseoutCaseView, OwnerCloseoutContractView, OwnerCloseoutOrganizationView,
    OwnerCloseoutPermitView, OwnerCloseoutProfileView, OwnerCloseoutProjectView,
    OwnerCloseoutStateView, OwnerCloseoutDecisionView, OwnerHandoverSubmissionView, OwnerSettlementProposalView,
    owner_closeout_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedOwnerCloseout(PreparedOwnerObservation):
    ACTION_ID: ClassVar[str] = 'OWN-A12'


class OwnerCloseoutActionAssembler(OwnerObservationActionAssembler):
    """Keep scoped handovers, independent checks, permits, defects and proposals.

    Applications hold their current source/authorization guard. The original
    processor evaluates completeness, independent use, remaining duties and
    settlement choices. Assembly grants no use rights, acceptance or payment.
    """
    ACTION_ID = 'OWN-A12'
    SOURCE_SCHEMAS = staticmethod(owner_closeout_schemas)

    def build(self, context, *, scope_ref, handover_refs, verification_refs,
            permit_refs, defect_refs, settlement_refs):
        return self._prepare_supplied_snapshot(context,
            input_values={'scope_ref': scope_ref, 'handover_refs': handover_refs,
                'verification_refs': verification_refs, 'permit_refs': permit_refs,
                'defect_refs': defect_refs, 'settlement_refs': settlement_refs},
            prepared_type=PreparedOwnerCloseout, validate_sources=self._validate_closeout_sources)

    @staticmethod
    def _validate_closeout_sources(action_input, *, context, reading):
        validate_owner_closeout_sources(action_input, context=context,
            organization_id=reading.organization_id, sources=reading._reads)


def validate_owner_closeout_sources(action_input, *, context, organization_id, sources):
    """Check original identities without evaluating acceptance or clearance."""
    if action_input.scope_ref != context.scope:
        raise TaskConflict('Owner closeout input changes its original invocation scope')
    anchor = sources.get(context.scope.ref.key())
    if not isinstance(anchor, (OwnerCloseoutOrganizationView, OwnerCloseoutCaseView, OwnerCloseoutProjectView)):
        raise TaskConflict('Owner closeout changes its original scope anchor projection')
    state = sources.get(anchor.closeout_state_ref.key())
    if state is not None and (not isinstance(state, OwnerCloseoutStateView)
            or state.organization_id != organization_id or state.scope != context.scope):
        raise TaskConflict('Owner closeout changes the original state owner or scope')
    contracts = None
    if isinstance(state, OwnerCloseoutStateView):
        contracts = {ref.key() for ref in state.contract_refs}
        for ref in state.contract_refs:
            contract = sources.get(ref.key())
            if contract is not None and (not isinstance(contract, OwnerCloseoutContractView)
                    or contract.owner_id != organization_id):
                raise TaskConflict('Owner closeout state substitutes another owner contract')
        profile = sources.get(state.decision_profile_ref.key())
        if profile is not None and (not isinstance(profile, OwnerCloseoutProfileView)
                or profile.state_ref.key() != state.ref.key() or profile.scope != context.scope
                or profile.organization_id != organization_id or profile.actor_id != context.actor_id
                or profile.function_ref.key() != context.function_ref.key()
                or profile.authority_ref.key() not in {ref.key() for ref in context.authorization_refs}
                or profile.contract_ref.key() not in contracts):
            raise TaskConflict('Owner closeout profile changes the original state, owner, actor, contract or authority')
        for ref in state.decision_history_refs:
            previous = sources.get(ref.key())
            if previous is not None and (not isinstance(previous, OwnerCloseoutDecisionView)
                    or previous.state_ref.key()[:2] != state.ref.key()[:2]
                    or previous.contract_ref.key() not in contracts or previous.author_organization_id != organization_id):
                raise TaskConflict('Owner closeout history changes its original state, contract or owner')
            if (previous is not None and isinstance(profile, OwnerCloseoutProfileView)
                    and (previous.contract_ref, previous.business_key) == (profile.contract_ref, profile.business_key)):
                original = sources.get(previous.profile_ref.key())
                if original is not None and (not isinstance(original, OwnerCloseoutProfileView)
                        or original.state_ref != previous.state_ref or original.contract_ref != previous.contract_ref
                        or original.organization_id != previous.author_organization_id or original.scope != previous.scope
                        or original.business_key != previous.business_key or original.choice != previous.choice):
                    raise TaskConflict('Owner closeout decision changes its original profile state, scope or choice')
    for refs, schema in ((action_input.handover_refs, OwnerHandoverSubmissionView),
            (action_input.verification_refs, ContractorCloseoutVerificationView),
            (action_input.permit_refs, OwnerCloseoutPermitView),
            (action_input.settlement_refs, OwnerSettlementProposalView)):
        unique_refs(refs)
        for ref in refs:
            row = sources.get(ref.key())
            if not isinstance(row, schema) or contracts is not None and row.contract_ref.key() not in contracts:
                raise TaskConflict('Owner closeout source changes its original projection or state contract relation')
    unique_refs(action_input.defect_refs)
    for ref in action_input.defect_refs:
        defect = sources.get(ref.key())
        if not isinstance(defect, ContractorVisibleDefectView):
            raise TaskConflict('Owner closeout changes an original visible defect projection')
        work = sources.get(defect.work_record_ref.key())
        if work is not None and (not isinstance(work, ContractorWorkRecordView)
                or work.physical_work_key != defect.physical_work_key):
            raise TaskConflict('Owner closeout defect changes its original physical work identity')
        observed = sources.get(defect.observation_ref.key())
        if observed is not None and (not isinstance(observed, ContractorInspectionEvidenceView)
                or observed.work_record_ref.key() != defect.work_record_ref.key()
                or observed.physical_work_key != defect.physical_work_key
                or not scope_covers(observed.scope, defect.scope)
                or work is not None and not scope_covers(work.scope, observed.scope)):
            raise TaskConflict('Owner closeout defect substitutes another original observation or work record')
    # Complete/current histories, original author authority, actual observations,
    # independent verification, residual duties and monetary consequences remain
    # original processor and host checks, including missing-information outcomes.
