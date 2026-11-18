"""Assemble actual authorized OWN-A16 proposal inputs without drafting source facts."""
from dataclasses import dataclass, replace
from typing import ClassVar

from integration.owner_observation_actions import OwnerObservationActionAssembler, PreparedOwnerObservation
from integration.owner_observation_handoff import owner_observation_handoff_schemas, prepare_owner_observation_handoff
from src.actions.contracts.owner_objects import OwnerManagementCapacityView, OwnerObjectiveView
from src.actions.contracts.owner_proposal_objects import (
    ProposalCandidateView, ProposalCaseView, ProposalFundingView, ProposalInternalNeedView,
    ProposalSpaceView,
)
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class PreparedOwnerProposal(PreparedOwnerObservation):
    ACTION_ID: ClassVar[str] = 'OWN-A16'


class OwnerProposalActionAssembler(OwnerObservationActionAssembler):
    """Keep the complete six-field input and independently supplied private case.

    A01 saved intentions never create the case, candidate space, money or
    proposal candidates here. Methods and business choices remain in A16.
    """
    ACTION_ID = 'OWN-A16'
    SOURCE_SCHEMAS = staticmethod(owner_observation_handoff_schemas)

    def build(self, context, *, case_ref, objective_ref, demand_refs, internal_need_refs,
            candidate_space_ref, funding_ref):
        return self._prepare_supplied_snapshot(context,
            input_values={'case_ref': case_ref, 'objective_ref': objective_ref, 'demand_refs': demand_refs,
                'internal_need_refs': internal_need_refs, 'candidate_space_ref': candidate_space_ref,
                'funding_ref': funding_ref}, prepared_type=PreparedOwnerProposal,
            validate_sources=self._validate_proposal_sources)

    @staticmethod
    def _validate_proposal_sources(action_input, *, context, reading):
        validate_owner_proposal_sources(action_input, context=context,
            organization_id=reading.organization_id, sources=reading._reads)

    def build_from_observation(self, context, *, observation_worker, observation_identity,
            observation_execution_versions, basis_ref, validate_history, validate_current, **proposal_refs):
        """Use original A01 history and actual case sources without replaying A01."""
        from integration.owner_observation_results import OwnerObservationResultWorker

        if (not isinstance(observation_worker, OwnerObservationResultWorker)
                or observation_worker.ACTION_ID != 'OWN-A01' or observation_worker.registry is not self.registry
                or observation_worker.store.run_id != self.organizations.run_id or self.source_mode != 'formal'
                or not callable(validate_history) or not callable(validate_current)):
            raise ValueError('Owner proposal handoff requires original A01 worker, formal sources and explicit host checks')
        invocation = self.build(context, **proposal_refs)
        saved = observation_worker.read_completed(observation_identity, current_context=invocation.context,
            reading=invocation.reading, execution_versions=observation_execution_versions, validate_current=validate_history)
        handoff = prepare_owner_observation_handoff(saved, context=invocation.context, reading=invocation.reading,
            basis_ref=basis_ref, case_ref=invocation.action_input.case_ref, validate_current=validate_current)
        if handoff['kind'] != 'prepared':
            return handoff
        return {**handoff, 'invocation': replace(invocation, reading_sha256=task_digest(invocation.reading.evidence()))}


def validate_owner_proposal_sources(action_input, *, context, organization_id, sources):
    """Validate the same immutable typed source identities before/after saving."""
    case = sources.get(action_input.case_ref.key())
    objective = sources.get(action_input.objective_ref.key())
    space = sources.get(action_input.candidate_space_ref.key())
    funding = sources.get(action_input.funding_ref.key())
    for source, schema in ((case, ProposalCaseView), (objective, OwnerObjectiveView),
            (space, ProposalSpaceView), (funding, ProposalFundingView)):
        if not isinstance(source, schema) or source.organization_id != organization_id:
            raise TaskConflict('Owner proposal changes its original private case, objective, space or funding owner')
    if (case.objective_ref.key() != objective.ref.key() or space.case_ref.key() != case.ref.key()
            or space.objective_ref.key() != objective.ref.key()
            or context.scope.kind == 'assessment_case' and context.scope.ref.key() != case.ref.key()
            or context.scope.kind == 'organization' and context.scope.ref.id != organization_id):
        raise TaskConflict('Owner proposal changes the original case/objective relation or own scope')
    for refs in (action_input.demand_refs, action_input.internal_need_refs, space.candidate_refs):
        if len({(ref.kind, ref.id) for ref in refs}) != len(refs):
            raise TaskConflict('Owner proposal repeats a physical source or candidate across versions')
    for ref in action_input.internal_need_refs:
        need = sources.get(ref.key())
        if (not isinstance(need, ProposalInternalNeedView) or need.organization_id != organization_id
                or need.case_ref.key() != case.ref.key()):
            raise TaskConflict('Owner proposal internal need belongs to another owner or private case')
    # Only check output dependencies that were actually supplied. The original
    # processor decides whether a branch needs them; never create replacements.
    if space.capacity_ref.key() in sources:
        capacity = sources[space.capacity_ref.key()]
        if not isinstance(capacity, OwnerManagementCapacityView) or capacity.organization_id != organization_id:
            raise TaskConflict('Owner proposal changes its original private management capacity')
    for ref in space.candidate_refs:
        if ref.key() not in sources:
            continue
        candidate = sources[ref.key()]
        if (not isinstance(candidate, ProposalCandidateView) or candidate.organization_id != organization_id
                or candidate.case_ref.key() != case.ref.key() or candidate.objective_ref.key() != objective.ref.key()):
            raise TaskConflict('Owner proposal candidate belongs to another owner, case or objective')
