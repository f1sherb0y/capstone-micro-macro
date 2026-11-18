"""Assemble original Engineer A13 finite research and saved professional checks."""
from dataclasses import dataclass
from typing import ClassVar

from integration.engineer_opportunity_actions import EngineerOpportunityActionAssembler, PreparedEngineerOpportunity
from src.actions.contracts.architect_research_objects import ArchitectResearchLimitView, ArchitectResearchRequestView
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.engineer_research_objects import (
    EngineerResearchAuthorityView, EngineerResearchTaskView, EngineerResearchTargetView,
    EngineerResearchCheckSpecView, EngineerResearchAssessmentView, EngineerResearchMethodProjection,
    EngineerResearchScopeView, EngineerResearchGapView, engineer_research_schemas,
    EngineerResearchCheckPreparation,
    EngineerResearchEstimatePreparation,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_cost_objects import QSCostBriefView
from src.actions.contracts.qs_research_objects import QSResearchExpenseView, QSResearchCostFactView
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedEngineerResearch(PreparedEngineerOpportunity):
    ACTION_ID: ClassVar[str] = 'ENGINEER-A13'


class EngineerResearchActionAssembler(EngineerOpportunityActionAssembler):
    """Freeze delegated research under the application's current source read guard.

    The original processor checks independently accepted service/delegation,
    actual spending and work, limited method support and reconstructed assessment
    reuse. Empty options, missing evidence and null comparison stay explicit.
    Assembly creates no ranking, investigation, appointment or investment.
    """
    ACTION_ID = 'ENGINEER-A13'
    SOURCE_SCHEMAS = staticmethod(engineer_research_schemas)

    def prepare_check_calculation(self, context, *, preparation, author_authority_ref,
            validate_current, **source_refs):
        """Produce one delegated check under the caller's actual source guard."""
        from integration.engineer_research_check_calculations import prepare_engineer_research_check_calculation

        context, action_input, reading = self._build_check_reading(context, preparation=preparation, **source_refs)
        return prepare_engineer_research_check_calculation(context=context, action_input=action_input,
            reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=validate_current)

    def _build_check_reading(self, context, *, preparation, **source_refs):
        """Freeze original A13 sources while excluding reserved check results."""
        from integration.engineer_design_actions import EngineerDesignActionAssembler

        return EngineerDesignActionAssembler._build_calculation_reading(self, context, preparation=preparation,
            preparation_model=EngineerResearchCheckPreparation,
            validate_sources=validate_engineer_research_check_preparation_sources, **source_refs)

    def _build_estimate_reading(self, context, *, preparation, **source_refs):
        """Isolate the request's estimate target while retaining existing checks."""
        from integration.engineer_design_actions import EngineerDesignActionAssembler

        preparation = EngineerResearchEstimatePreparation.model_validate(preparation).model_copy(deep=True)
        return EngineerDesignActionAssembler._build_calculation_reading(self, context, preparation=preparation,
            preparation_model=EngineerResearchEstimatePreparation,
            validate_sources=validate_engineer_research_estimate_preparation_sources,
            future_result_refs=[preparation.calculation_ref], **source_refs)

    def prepare_estimate_calculation(self, context, *, preparation, author_authority_ref,
            validate_current, **source_refs):
        """Produce one sourced estimate under the caller's actual source guard."""
        from integration.engineer_research_estimate_calculations import prepare_engineer_research_estimate_calculation

        context, action_input, reading = self._build_estimate_reading(context, preparation=preparation, **source_refs)
        return prepare_engineer_research_estimate_calculation(context=context, action_input=action_input,
            reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=validate_current)

    def build(self, context, *, scope, brief_ref, research_authority_ref, task_ref,
            option_refs, check_spec_refs, evidence_refs, expenditure_limit_ref,
            available_assessment_refs, method_result_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'brief_ref': brief_ref, 'research_authority_ref': research_authority_ref,
            'task_ref': task_ref, 'option_refs': option_refs, 'check_spec_refs': check_spec_refs,
            'evidence_refs': evidence_refs, 'expenditure_limit_ref': expenditure_limit_ref,
            'available_assessment_refs': available_assessment_refs, 'method_result_refs': method_result_refs},
            prepared_type=PreparedEngineerResearch, validate_sources=validate_engineer_research_sources)

    def save_estimate_calculation(self, context, *, publications, read_guard, preparation,
            author_authority_ref, validate_current, **source_refs):
        """Produce and retain one sourced A13 estimate; publish separately."""
        from integration.engineer_research_estimate_publication import EngineerResearchEstimatePublicationStore
        from integration.engineer_research_estimate_calculations import prepare_engineer_research_estimate_calculation

        if (not isinstance(publications, EngineerResearchEstimatePublicationStore)
                or publications.registry is not self.registry or publications.methods is not self.methods
                or publications.organizations is not self.organizations or not callable(read_guard)):
            raise TaskConflict('Research estimate save requires original registries and actual source writer guard')
        context = self._context(context)
        with read_guard(context.model_copy(deep=True)):
            context, action_input, reading = self._build_estimate_reading(context, preparation=preparation, **source_refs)
            calculation = prepare_engineer_research_estimate_calculation(context=context, action_input=action_input,
                reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
                validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation, context=context, action_input=action_input, reading=reading)
            return {'kind': 'prepared', 'calculation': calculation, 'record': record}

    def save_check_calculation(self, context, *, publications, read_guard, preparation,
            author_authority_ref, validate_current, **source_refs):
        """Produce and retain one delegated A13 check; publish separately."""
        from integration.engineer_research_check_publication import EngineerResearchCheckPublicationStore
        from integration.engineer_research_check_calculations import prepare_engineer_research_check_calculation

        if (not isinstance(publications, EngineerResearchCheckPublicationStore)
                or publications.registry is not self.registry or publications.methods is not self.methods
                or publications.organizations is not self.organizations or not callable(read_guard)):
            raise TaskConflict('Research check save requires original registries and actual source writer guard')
        context = self._context(context)
        with read_guard(context.model_copy(deep=True)):
            context, action_input, reading = self._build_check_reading(context, preparation=preparation, **source_refs)
            calculation = prepare_engineer_research_check_calculation(context=context, action_input=action_input,
                reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
                validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation, context=context, action_input=action_input, reading=reading)
            return {'kind': 'prepared', 'calculation': calculation, 'record': record}


def validate_engineer_research_sources(action_input, *, context, organization_id, sources):
    return _validate_engineer_research_sources(action_input, context=context,
        organization_id=organization_id, sources=sources, pending_result_keys=frozenset())


def validate_engineer_research_check_preparation_sources(action_input, *, preparation, context, organization_id, sources):
    """Check original reserved targets without consuming or assessing outputs."""
    task = sources.get(action_input.task_ref.key())
    if (not isinstance(task, EngineerResearchTaskView)
            or {ref.key() for ref in task.method_result_refs} != {ref.key() for ref in action_input.method_result_refs}
            or preparation.check_spec_ref not in task.check_spec_refs
            or preparation.check_spec_ref not in action_input.check_spec_refs
            or preparation.calculation_ref not in task.method_result_refs):
        raise TaskConflict('Research preparation must retain original task/spec/result inputs')
    unique_refs([row.check_spec_ref for row in task.check_result_targets])
    unique_refs([row.calculation_ref for row in task.check_result_targets])
    selected = next((row for row in task.check_result_targets if row.check_spec_ref == preparation.check_spec_ref), None)
    if selected is not None and selected.calculation_ref != preparation.calculation_ref:
        raise TaskConflict('Research preparation replaces its original spec/result mapping')
    pending = frozenset(ref.key() for ref in action_input.method_result_refs)
    if pending.intersection(sources):
        raise TaskConflict('Research preparation cannot consume reserved result outputs')
    return _validate_engineer_research_sources(action_input, context=context,
        organization_id=organization_id, sources=sources, pending_result_keys=pending)


def validate_engineer_research_estimate_preparation_sources(action_input, *, preparation, context, organization_id, sources):
    """Bind original request/estimate target without consuming future results."""
    task = sources.get(action_input.task_ref.key())
    request = sources.get(preparation.request_profile_ref.key())
    if (not isinstance(task, EngineerResearchTaskView) or not isinstance(request, ArchitectResearchRequestView)
            or task.missing_policy != 'request' or task.request_profile_ref != request.ref
            or request.task_ref != task.ref or request.estimate_ref != preparation.calculation_ref
            or preparation.calculation_ref in task.method_result_refs):
        raise TaskConflict('Research estimate preparation must retain original request and separate result target')
    pending = frozenset([preparation.calculation_ref.key()])
    if pending.intersection(sources):
        raise TaskConflict('Research estimate preparation cannot consume reserved result outputs')
    return _validate_engineer_research_sources(action_input, context=context,
        organization_id=organization_id, sources=sources, pending_result_keys=pending)


def _validate_engineer_research_sources(action_input, *, context, organization_id, sources, pending_result_keys):
    """Check original delegation and task identities without evaluating findings."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Engineer research lacks its exact original concrete source')
        if hasattr(row, 'scope') and not scope_covers(row.scope, context.scope):
            raise TaskConflict('Engineer research source does not cover its original authorized scope')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Engineer research changes its original invocation scope')
    brief = read(action_input.brief_ref, QSCostBriefView)
    task = read(action_input.task_ref, EngineerResearchTaskView)
    grant = read(action_input.research_authority_ref, EngineerResearchAuthorityView)
    limit = read(action_input.expenditure_limit_ref, ArchitectResearchLimitView)
    if (task.organization_id != organization_id or task.function_ref.key() != context.function_ref.key()
            or task.brief_ref.key() != brief.ref.key() or grant.brief_ref.key() != brief.ref.key()
            or grant.task_ref.key() != task.ref.key() or grant.delegate_organization_id != organization_id
            or grant.delegate_actor_id != context.actor_id or grant.delegate_function_ref.key() != context.function_ref.key()
            or task.expenditure_limit_ref.key() != limit.ref.key()
            or limit.task_ref.key() != task.ref.key() or limit.organization_id != organization_id):
        raise TaskConflict('Engineer research changes its original delegation, task, brief or expenditure limit')
    for field in ('option_refs', 'check_spec_refs', 'evidence_refs', 'available_assessment_refs', 'method_result_refs'):
        unique_refs(getattr(action_input, field))
    for ref in action_input.evidence_refs:
        read(ref, EvidenceRecord)
    for ref in action_input.option_refs:
        if read(ref, EngineerResearchTargetView).brief_ref.key() != brief.ref.key():
            raise TaskConflict('Engineer research option changes its original brief')
    for ref in action_input.check_spec_refs:
        if read(ref, EngineerResearchCheckSpecView).brief_ref.key() != brief.ref.key():
            raise TaskConflict('Engineer research check specification changes its original brief')
    for ref in action_input.available_assessment_refs:
        assessment = read(ref, EngineerResearchAssessmentView).assessment
        if assessment.task_ref.key() != task.ref.key():
            raise TaskConflict('Engineer reusable assessment changes its original task')
    for ref in action_input.method_result_refs:
        if ref.key() in pending_result_keys:
            continue
        wrapped = read(ref, EngineerResearchMethodProjection)
        record = wrapped.check if wrapped.check is not None else wrapped.estimate
        if record.task_ref.key() != task.ref.key():
            raise TaskConflict('Engineer saved research execution changes its original task')
        if wrapped.check is not None and wrapped.check.brief_ref.key() != brief.ref.key():
            raise TaskConflict('Engineer saved research check changes its original brief')
    if task.comparison_scope_ref is not None and task.comparison_scope_ref.key() in sources:
        comparison = read(task.comparison_scope_ref, EngineerResearchScopeView)
        if comparison.task_ref.key() != task.ref.key() or comparison.brief_ref.key() != brief.ref.key():
            raise TaskConflict('Engineer comparison scope changes its original task or brief')
    for ref in task.question_refs:
        if ref.key() in sources:
            gap = read(ref, EngineerResearchGapView)
            if gap.task_ref.key() != task.ref.key() or gap.brief_ref.key() != brief.ref.key():
                raise TaskConflict('Engineer research question changes its original task or brief')
    for ref in limit.expense_refs:
        if ref.key() in sources:
            expense = read(ref, QSResearchExpenseView)
            if expense.task_ref.key() != task.ref.key():
                raise TaskConflict('Engineer research expense changes its original task')
            if expense.cost_fact_ref.key() in sources:
                fact = read(expense.cost_fact_ref, QSResearchCostFactView)
                if fact.task_ref.key() != task.ref.key() or fact.organization_id != organization_id:
                    raise TaskConflict('Engineer research cost/work fact changes its original task or organization')
    if task.request_profile_ref is not None and task.request_profile_ref.key() in sources:
        request = read(task.request_profile_ref, ArchitectResearchRequestView)
        if request.task_ref.key() != task.ref.key() or request.scope != action_input.scope:
            raise TaskConflict('Engineer investigation request changes its original task or scope')
    # Original processor determines independent acceptance, exact input coverage,
    # author authority, independence, actual method replay and bounded estimates.
