"""Assemble original Engineer A05 finite professional design sources."""
from dataclasses import dataclass
from typing import ClassVar

from integration.engineer_opportunity_actions import EngineerOpportunityActionAssembler, PreparedEngineerOpportunity
from src.actions.contracts.architect_design_objects import ArchitectDesignLimitView
from src.actions.contracts.common import EvidenceRecord, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.contracts.engineer_appointment_objects import EngineerAppointmentView
from src.actions.contracts.engineer_design_objects import (
    EngineerDesignTaskView, EngineerDesignProfileView, EngineerDesignMethodProjection,
    EngineerParameterResultView, EngineerParameterCatalogView, EngineerValidatedParameterView,
    EngineerDesignParameterPreparation,
    EngineerDesignCheckPreparation,
    engineer_design_schemas,
)
from src.actions.contracts.engineer_planning_objects import EngineerPlanningWorkFactView
from src.actions.contracts.engineer_research_objects import (
    EngineerResearchGapView, EngineerResearchTargetView, EngineerResearchCheckSpecView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_cost_objects import QSCostBriefView
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedEngineerDesign(PreparedEngineerOpportunity):
    ACTION_ID: ClassVar[str] = 'ENGINEER-A05'


class EngineerDesignActionAssembler(EngineerOpportunityActionAssembler):
    """Freeze original sources under the application's current authorization guard.

    The original processor checks finite engagement limits, saved calculations,
    actual author work and supported parameter domains. Null prior designs and
    unknown/missing evidence retain their original branches. Submission and
    independently accepted effects remain separate from local design results.
    """
    ACTION_ID = 'ENGINEER-A05'
    SOURCE_SCHEMAS = staticmethod(engineer_design_schemas)

    def prepare_parameter_calculation(self, context, *, preparation, author_authority_ref,
            validate_current, **source_refs):
        """Produce one result while the caller holds its actual source guard."""
        from integration.engineer_parameter_calculations import prepare_engineer_parameter_calculation

        context, action_input, reading = self._build_parameter_reading(context,
            preparation=preparation, **source_refs)
        return prepare_engineer_parameter_calculation(context=context, action_input=action_input,
            reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=validate_current)

    def _build_parameter_reading(self, context, *, preparation, **source_refs):
        return self._build_calculation_reading(context, preparation=preparation,
            preparation_model=EngineerDesignParameterPreparation,
            validate_sources=validate_engineer_parameter_preparation_sources, **source_refs)

    def prepare_interface_check_calculation(self, context, *, preparation, author_authority_ref,
            validate_current, **source_refs):
        """Produce one check while the caller holds its actual source guard."""
        from integration.engineer_interface_check_calculations import prepare_engineer_interface_check_calculation

        context, action_input, reading = self._build_interface_check_reading(context,
            preparation=preparation, **source_refs)
        return prepare_engineer_interface_check_calculation(context=context, action_input=action_input,
            reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=validate_current)

    def _build_interface_check_reading(self, context, *, preparation, **source_refs):
        return self._build_calculation_reading(context, preparation=preparation,
            preparation_model=EngineerDesignCheckPreparation,
            validate_sources=validate_engineer_check_preparation_sources, **source_refs)

    def _build_calculation_reading(self, context, *, preparation, preparation_model, validate_sources,
            future_result_refs=None, **source_refs):
        """Freeze exact original sources without consuming reserved result outputs."""
        context = self._context(context)
        preparation = preparation_model.model_validate(preparation).model_copy(deep=True)
        registration = self.registry.get(self.ACTION_ID)
        if registration.role != 'Engineer' or not registration.implemented or registration.skill is None:
            raise TaskConflict('Parameter assembly requires original implemented A05 and Engineer Skill')
        action_input = registration.contract.validate_input(source_refs)
        future_refs = action_input.method_result_refs if future_result_refs is None else future_result_refs
        future_keys = {ref.key() for ref in future_refs} | {preparation.calculation_ref.key()}
        projection = self._views.assemble(context, self.ACTION_ID, 'Engineer')
        if any(row.ref == preparation.calculation_ref for row in projection.objects):
            raise TaskConflict('Parameter production cannot replace an already supplied result target')
        resolver = ReferenceResolver(context.run_id, source_mode=self.source_mode, schemas=self.SOURCE_SCHEMAS())
        for row in projection.objects:
            resolver.register_projection(row.ref, row.value)
        resolver.freeze_read(context.read_token, [row.ref for row in projection.objects])
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'Engineer',
            methods=self.methods, method_refs=registration.skill.manifest.method_refs)
        try:
            for row in projection.objects:
                if row.ref.key() not in future_keys:
                    reading.resolve(row.ref)
            for ref in walk_references(action_input):
                if ref.key() not in future_keys:
                    reading.resolve(ref)
            validate_sources(action_input, preparation=preparation,
                context=context, organization_id=reading.organization_id, sources=reading._reads)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise TaskConflict('Parameter assembly requires its original authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            return context, action_input, reading
        finally:
            reading.recheck()

    def save_parameter_calculation(self, context, *, publications, read_guard, preparation,
            author_authority_ref, validate_current, **source_refs):
        """Produce and retain under the actual source guard; publish separately."""
        from integration.engineer_parameter_publication import EngineerParameterPublicationStore
        from integration.engineer_parameter_calculations import prepare_engineer_parameter_calculation

        if (not isinstance(publications, EngineerParameterPublicationStore)
                or publications.registry is not self.registry or publications.methods is not self.methods
                or publications.organizations is not self.organizations or not callable(read_guard)):
            raise TaskConflict('Parameter save requires original registries and actual source writer guard')
        context = self._context(context)
        with read_guard(context.model_copy(deep=True)):
            context, action_input, reading = self._build_parameter_reading(context,
                preparation=preparation, **source_refs)
            calculation = prepare_engineer_parameter_calculation(context=context, action_input=action_input,
                reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
                validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation, context=context, action_input=action_input, reading=reading)
            return {'kind':'prepared', 'calculation':calculation, 'record':record}

    def save_interface_check_calculation(self, context, *, publications, read_guard, preparation,
            author_authority_ref, validate_current, **source_refs):
        """Produce and durably save one original check; publish separately."""
        from integration.engineer_interface_check_publication import EngineerInterfaceCheckPublicationStore
        from integration.engineer_interface_check_calculations import prepare_engineer_interface_check_calculation

        if (not isinstance(publications, EngineerInterfaceCheckPublicationStore)
                or publications.registry is not self.registry or publications.methods is not self.methods
                or publications.organizations is not self.organizations or not callable(read_guard)):
            raise TaskConflict('Check save requires original registries and actual source writer guard')
        context = self._context(context)
        with read_guard(context.model_copy(deep=True)):
            context, action_input, reading = self._build_interface_check_reading(context,
                preparation=preparation, **source_refs)
            calculation = prepare_engineer_interface_check_calculation(context=context, action_input=action_input,
                reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
                validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation, context=context, action_input=action_input, reading=reading)
            return {'kind':'prepared', 'calculation':calculation, 'record':record}

    def build(self, context, *, scope, brief_ref, task_ref, engineering_profile_ref,
            evidence_refs, method_result_refs, prior_option_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'brief_ref': brief_ref, 'task_ref': task_ref,
            'engineering_profile_ref': engineering_profile_ref, 'evidence_refs': evidence_refs,
            'method_result_refs': method_result_refs, 'prior_option_ref': prior_option_ref},
            prepared_type=PreparedEngineerDesign, validate_sources=validate_engineer_design_sources)


def validate_engineer_design_sources(action_input, *, context, organization_id, sources):
    """Check concrete original identities without computing engineering values."""
    return _validate_engineer_design_sources(action_input, context=context,
        organization_id=organization_id, sources=sources, pending_result_keys=frozenset())


def validate_engineer_parameter_preparation_sources(action_input, *, preparation, context, organization_id, sources):
    """Retain exact produce sources while reserving the original execution outputs."""
    task = sources.get(action_input.task_ref.key())
    if (not isinstance(task, EngineerDesignTaskView) or task.choice != 'produce' or task.draft is None
            or {ref.key() for ref in task.method_result_refs} != {ref.key() for ref in action_input.method_result_refs}
            or preparation.calculation_ref not in task.method_result_refs
            or preparation.input.parameter_ref not in task.draft.selected_parameter_refs):
        raise TaskConflict('Parameter preparation must retain its original produce task and selected result target')
    pending = frozenset(ref.key() for ref in action_input.method_result_refs)
    if pending.intersection(sources):
        raise TaskConflict('Parameter preparation cannot consume reserved result outputs')
    return _validate_engineer_design_sources(action_input, context=context,
        organization_id=organization_id, sources=sources, pending_result_keys=pending)


def validate_engineer_check_preparation_sources(action_input, *, preparation, context, organization_id, sources):
    """Retain original check/target registration while isolating future results."""
    task = sources.get(action_input.task_ref.key())
    if (not isinstance(task, EngineerDesignTaskView) or task.choice not in {'produce','report_limit'}
            or {ref.key() for ref in task.method_result_refs} != {ref.key() for ref in action_input.method_result_refs}
            or preparation.check_spec_ref not in task.check_spec_refs
            or preparation.calculation_ref not in task.method_result_refs):
        raise TaskConflict('Check preparation must retain original task/spec and reserved result inputs')
    unique_refs([row.check_spec_ref for row in task.check_result_targets])
    unique_refs([row.calculation_ref for row in task.check_result_targets])
    selected = next((row for row in task.check_result_targets if row.check_spec_ref == preparation.check_spec_ref), None)
    if selected is not None and selected.calculation_ref != preparation.calculation_ref:
        raise TaskConflict('Check preparation replaces its original spec/result target mapping')
    pending = frozenset(ref.key() for ref in action_input.method_result_refs)
    if pending.intersection(sources):
        raise TaskConflict('Check preparation cannot consume reserved result outputs')
    return _validate_engineer_design_sources(action_input, context=context,
        organization_id=organization_id, sources=sources, pending_result_keys=pending)


def _validate_engineer_design_sources(action_input, *, context, organization_id, sources, pending_result_keys):
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Engineer design lacks its exact original concrete source')
        if hasattr(row, 'scope') and not scope_covers(action_input.scope, row.scope):
            raise TaskConflict('Engineer design source leaves its original task scope')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Engineer design changes its original invocation scope')
    for refs in (action_input.evidence_refs, action_input.method_result_refs):
        unique_refs(refs)
    brief = read(action_input.brief_ref, QSCostBriefView)
    task = read(action_input.task_ref, EngineerDesignTaskView)
    profile = read(action_input.engineering_profile_ref, EngineerDesignProfileView)
    if (task.organization_id != organization_id or task.brief_ref.key() != brief.ref.key()
            or task.engineering_profile_ref.key() != profile.ref.key()):
        raise TaskConflict('Engineer design changes its original organization, task, brief or profile')
    if task.appointment_ref.key() in sources:
        read(task.appointment_ref, EngineerAppointmentView)
    if task.design_limit_ref.key() in sources:
        limit = read(task.design_limit_ref, ArchitectDesignLimitView)
        if limit.appointment_ref.key() != task.appointment_ref.key():
            raise TaskConflict('Engineer design limit changes its original appointment')
    for ref in action_input.evidence_refs:
        read(ref, EvidenceRecord)
    if action_input.prior_option_ref is not None:
        parent = read(action_input.prior_option_ref, EngineerResearchTargetView)
        if parent.brief_ref.key() != brief.ref.key():
            raise TaskConflict('Engineer prior option changes its original brief')
    # Completeness, author permission and failed/unknown execution outcomes remain
    # processor decisions, including the original investigation branch.
    for ref in action_input.method_result_refs:
        if ref.key() in pending_result_keys:
            continue
        wrapped = read(ref, EngineerDesignMethodProjection)
        record = wrapped.record
        if record.ref.key() != ref.key() or record.task_ref.key() != task.ref.key():
            raise TaskConflict('Engineer saved method result changes its original reference or task')
        if isinstance(record, EngineerParameterResultView):
            if record.engineering_profile_ref.key() != profile.ref.key():
                raise TaskConflict('Engineer parameter execution changes its original profile')
        elif record.brief_ref.key() != brief.ref.key():
            raise TaskConflict('Engineer saved check changes its original brief')
    for ref in profile.parameter_catalog_refs:
        if ref.key() in sources:
            catalog = read(ref, EngineerParameterCatalogView)
            if catalog.engineering_profile_ref.key() != profile.ref.key():
                raise TaskConflict('Engineer parameter catalog changes its original profile')
    for ref in task.check_spec_refs:
        if ref.key() in sources and read(ref, EngineerResearchCheckSpecView).brief_ref.key() != brief.ref.key():
            raise TaskConflict('Engineer check specification changes its original brief')
    if task.draft is not None:
        for ref in task.draft.selected_parameter_refs:
            if ref.key() in sources:
                parameter = read(ref, EngineerValidatedParameterView)
                if parameter.task_ref.key() != task.ref.key() or parameter.engineering_profile_ref.key() != profile.ref.key():
                    raise TaskConflict('Engineer selected parameter changes its original task or profile')
    for ref in task.work_fact_refs:
        if ref.key() in sources:
            fact = read(ref, EngineerPlanningWorkFactView)
            if fact.organization_id != organization_id or fact.task_ref.key() != task.ref.key():
                raise TaskConflict('Engineer actual work changes its original organization or task')
    for ref in task.question_refs:
        if ref.key() in sources:
            gap = read(ref, EngineerResearchGapView)
            if gap.task_ref.key() != task.ref.key() or gap.brief_ref.key() != brief.ref.key():
                raise TaskConflict('Engineer design question changes its original task or brief')
