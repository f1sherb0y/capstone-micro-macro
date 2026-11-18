"""Assemble original Contractor A08 inspection and remedy inputs."""
from dataclasses import dataclass
from typing import ClassVar

from integration.contractor_amendment_actions import ContractorAmendmentActionAssembler, PreparedContractorAmendment
from src.actions.contracts.contractor_quality_objects import (
    ContractorInspectionEvidenceView, ContractorInspectionMethodView, ContractorInspectionObservationMethodView,
    ContractorInspectionProfileView, ContractorInspectionRequirementView,
    ContractorInspectionResultView, ContractorIsolationAuthorityView,
    ContractorRemedyCapacityView, ContractorRemedyDependencyView, ContractorRemedyPlanView,
    ContractorVisibleDefectView, ContractorWorkRecordView, contractor_quality_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedContractorQuality(PreparedContractorAmendment):
    ACTION_ID: ClassVar[str] = 'CONTRACTOR-A08'


class ContractorQualityActionAssembler(ContractorAmendmentActionAssembler):
    """Freeze visible inspection inputs without reading hidden quality state.

    The actual application holds its current source/authorization guard. Original
    processor checks independent observation, method support, defect coverage,
    isolation authority, remedy capacity and recheck history. Assembly creates no
    inspection approval, defect closure, remedy execution or inventory return.
    """
    ACTION_ID = 'CONTRACTOR-A08'
    SOURCE_SCHEMAS = staticmethod(contractor_quality_schemas)

    def build(self, context, *, scope_ref, work_record_refs, requirement_refs,
            defect_refs, evidence_refs, inspection_profile_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope_ref': scope_ref, 'work_record_refs': work_record_refs,
            'requirement_refs': requirement_refs, 'defect_refs': defect_refs,
            'evidence_refs': evidence_refs, 'inspection_profile_ref': inspection_profile_ref},
            prepared_type=PreparedContractorQuality, validate_sources=validate_contractor_quality_sources)


def validate_contractor_quality_sources(action_input, *, context, organization_id, sources):
    """Check supplied physical work relationships without deciding technical acceptance."""
    def read(ref, schema):
        source = sources.get(ref.key())
        if not isinstance(source, schema) or source.ref.key() != ref.key():
            raise TaskConflict('Inspection lacks its exact original concrete source')
        return source

    def authored(row):
        points = (row.authored_at, row.available_at, row.effective_window.start, row.effective_window.end)
        if (any(point.clock_ref != context.business_time.clock_ref for point in points)
                or row.authored_at.offset > row.available_at.offset
                or row.available_at.offset > context.business_time.offset
                or not row.effective_window.contains(row.authored_at)):
            raise TaskConflict('Inspection source changes its original signing time or availability')

    def available_at(row, point):
        if (row.available_at.clock_ref != point.clock_ref
                or row.available_at.offset > point.offset):
            raise TaskConflict('Inspection source was not available at the original signing time')

    if action_input.scope_ref != context.scope:
        raise TaskConflict('Inspection changes its original authorized physical scope')
    for refs in (action_input.work_record_refs, action_input.requirement_refs,
            action_input.defect_refs, action_input.evidence_refs):
        unique_refs(refs)
    profile = read(action_input.inspection_profile_ref, ContractorInspectionProfileView)
    if profile.organization_id != organization_id or profile.scope != action_input.scope_ref:
        raise TaskConflict('Inspection profile changes original contractor or scope')
    records = {ref.key(): read(ref, ContractorWorkRecordView) for ref in action_input.work_record_refs}
    requirements = {ref.key(): read(ref, ContractorInspectionRequirementView) for ref in action_input.requirement_refs}
    for requirement in requirements.values():
        unique_refs(requirement.work_record_refs)
        if not {r.key() for r in requirement.work_record_refs} <= set(records):
            raise TaskConflict('Inspection requirement changes original supplied physical work coverage')
    for ref in action_input.evidence_refs:
        evidence = read(ref, ContractorInspectionEvidenceView)
        authored(evidence)
        record = records.get(evidence.work_record_ref.key())
        if (record is None or evidence.physical_work_key != record.physical_work_key
                or not scope_covers(action_input.scope_ref, evidence.scope)
                or not scope_covers(record.scope, evidence.scope)
                or evidence.observed_at.clock_ref != evidence.authored_at.clock_ref
                or evidence.observed_at.offset > evidence.authored_at.offset):
            raise TaskConflict('Inspection evidence changes the original observed work record or physical identity')
        available_at(record, evidence.authored_at)
        # Observations/assumptions and unknown verification remain original
        # processor inputs; assembly never promotes them to technical success.
    for ref in action_input.defect_refs:
        defect = read(ref, ContractorVisibleDefectView)
        record = records.get(defect.work_record_ref.key())
        if record is None or defect.physical_work_key != record.physical_work_key:
            raise TaskConflict('Visible defect changes original physical work or supplied record')
        unique_refs(defect.requirement_refs)
        for requirement_ref in defect.requirement_refs:
            requirement = requirements.get(requirement_ref.key())
            if (requirement is None or defect.work_record_ref not in requirement.work_record_refs
                    or not scope_covers(requirement.scope, defect.scope)):
                raise TaskConflict('Visible defect substitutes an inspection requirement for different work or scope')
        observation = sources.get(defect.observation_ref.key())
        if observation is not None and (not isinstance(observation, ContractorInspectionEvidenceView)
                or observation.ref != defect.observation_ref
                or observation.work_record_ref.key() != defect.work_record_ref.key()
                or observation.physical_work_key != defect.physical_work_key
                or not scope_covers(observation.scope, defect.scope)):
            raise TaskConflict('Visible defect changes its original observed work evidence')
    if profile.method_ref is not None:
        method = sources.get(profile.method_ref.key())
        if method is not None and (not isinstance(method, ContractorInspectionMethodView)
                or method.ref != profile.method_ref):
            raise TaskConflict('Inspection substitutes its original concrete method source')
        if method is not None:
            observation = sources.get(method.observation_method_ref.key())
            if observation is not None and (not isinstance(observation, ContractorInspectionObservationMethodView)
                    or observation.ref != method.observation_method_ref):
                raise TaskConflict('Inspection substitutes its original concrete observation method source')
    if profile.prior_inspection_ref is not None:
        prior = sources.get(profile.prior_inspection_ref.key())
        if prior is not None and (not isinstance(prior, ContractorInspectionResultView)
                or prior.ref != profile.prior_inspection_ref):
            raise TaskConflict('Inspection substitutes its original historical result source')
        if prior is not None and profile.choice == 'request_recheck':
            authored(prior)
            unique_refs(prior.work_record_refs)
            unique_refs(prior.defect_refs)
            if (not {ref.key() for ref in action_input.defect_refs} <= {ref.key() for ref in prior.defect_refs}
                    or not {ref.key() for ref in prior.work_record_refs} <= set(records)):
                raise TaskConflict('Inspection substitutes original result work or defect coverage')
            for ref in (*prior.work_record_refs, *prior.defect_refs):
                source = sources.get(ref.key())
                if source is not None:
                    available_at(source, prior.authored_at)
            for ref in action_input.defect_refs:
                if not scope_covers(prior.scope, sources[ref.key()].scope):
                    raise TaskConflict('Inspection original result does not cover the actual defect scope')
            prior_method = sources.get(prior.method_ref.key())
            if prior_method is not None:
                if (not isinstance(prior_method, ContractorInspectionMethodView)
                        or prior_method.ref != prior.method_ref):
                    raise TaskConflict('Inspection substitutes its original historical method')
                available_at(prior_method, prior.authored_at)
                if (prior_method.effective_window.start.clock_ref != prior.authored_at.clock_ref
                        or prior_method.effective_window.end.clock_ref != prior.authored_at.clock_ref
                        or not prior_method.effective_window.contains(prior.authored_at)
                        or not scope_covers(prior_method.scope, prior.scope)
                        or prior_method.executor_organization_id != prior.author_organization_id
                        or prior_method.executor_actor_id != prior.author_actor_id
                        or prior_method.executor_function_ref != prior.author_function_ref
                        or prior_method.executor_authority_ref != prior.author_authority_ref
                        or prior_method.executor_action_id != prior.author_action_id):
                    raise TaskConflict('Inspection changes its original historical method, scope or executor')
                prior_observation = sources.get(prior_method.observation_method_ref.key())
                if prior_observation is not None:
                    if (not isinstance(prior_observation, ContractorInspectionObservationMethodView)
                            or prior_observation.ref != prior_method.observation_method_ref):
                        raise TaskConflict('Inspection substitutes its original historical observation method')
                    available_at(prior_observation, prior.authored_at)
                    if (prior_observation.effective_window.start.clock_ref != prior.authored_at.clock_ref
                            or prior_observation.effective_window.end.clock_ref != prior.authored_at.clock_ref
                            or not prior_observation.effective_window.contains(prior.authored_at)
                            or not scope_covers(prior_observation.scope, prior.scope)):
                        raise TaskConflict('Inspection changes its original observation method time or scope')
    if profile.isolation_authority_ref is not None:
        authority = sources.get(profile.isolation_authority_ref.key())
        if authority is not None and (not isinstance(authority, ContractorIsolationAuthorityView)
                or authority.ref != profile.isolation_authority_ref
                or authority.organization_id != organization_id
                or not scope_covers(authority.scope, action_input.scope_ref)):
            raise TaskConflict('Inspection isolation authority changes original organization')
    if profile.remedy_plan_ref is not None:
        plan = sources.get(profile.remedy_plan_ref.key())
        if plan is not None:
            if not isinstance(plan, ContractorRemedyPlanView) or plan.author_organization_id != organization_id:
                raise TaskConflict('Inspection remedy plan changes its original planner organization')
            authored(plan)
            capacity = sources.get(plan.capacity_result_ref.key())
            if capacity is not None and (not isinstance(capacity, ContractorRemedyCapacityView)
                    or capacity.plan_ref.key() != plan.ref.key() or capacity.author_organization_id != organization_id):
                raise TaskConflict('Inspection remedy capacity changes its original plan or planner')
            if capacity is not None:
                authored(capacity)
                available_at(plan, capacity.authored_at)
            for task in plan.tasks:
                if (not scope_covers(action_input.scope_ref, task.scope_ref)
                        or not scope_covers(plan.scope, task.scope_ref)):
                    raise TaskConflict('Inspection remedy task changes its original plan or invocation scope')
                for ref in task.dependency_refs:
                    dependency = sources.get(ref.key())
                    if dependency is not None and (not isinstance(dependency, ContractorRemedyDependencyView)
                            or dependency.plan_ref.key() != plan.ref.key()):
                        raise TaskConflict('Inspection remedy dependency changes its original plan')
