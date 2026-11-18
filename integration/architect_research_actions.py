"""Freeze original Architect A13 bounded research and finite comparison sources."""
from dataclasses import dataclass
from typing import ClassVar

from integration.architect_opportunity_actions import ArchitectOpportunityActionAssembler, PreparedArchitectOpportunity
from src.actions.contracts.architect_research_objects import (
    ArchitectResearchAuthorityView, ArchitectResearchDecisionView, ArchitectResearchTaskView,
    ArchitectResearchProfileView, ArchitectResearchOptionView, ArchitectResearchAssessmentView,
    ArchitectResearchScopeView, ArchitectResearchMethodView, ArchitectResearchGapView,
    ArchitectResearchRequestView, ArchitectResearchReferenceView, ArchitectResearchLimitView,
    ArchitectResearchEstimateView, ArchitectResearchEstimateMethodView, architect_research_schemas,
    ArchitectResearchEstimatePreparation,
)
from src.actions.contracts.qs_cost_objects import QSCostBriefView
from src.actions.contracts.qs_research_objects import QSResearchExpenseView, QSResearchCostFactView, QSResearchCostPlanView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.common import walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedArchitectResearch(PreparedArchitectOpportunity):
    ACTION_ID: ClassVar[str] = 'ARCHITECT-A13'


class ArchitectResearchActionAssembler(ArchitectOpportunityActionAssembler):
    """Preserve independently received research authority and finite spending limits.

    Original processor checks acceptance, actual cost/work, comparison coverage
    and separately supported investigation estimates. Empty candidate lists and
    a null comparison method remain explicit. Assembly creates no ranking,
    investigation, investment, approval, fee or further appointment.
    """
    ACTION_ID = 'ARCHITECT-A13'
    SOURCE_SCHEMAS = staticmethod(architect_research_schemas)

    def prepare_estimate_input(self, context, *, preparation, **source_refs):
        """Prepare original sourced work while the caller holds its source guard."""
        from src.actions.roles.architect_research import prepare_architect_research_estimate_input

        context, action_input, reading = self._build_estimate_reading(context,
            preparation=preparation, **source_refs)
        return prepare_architect_research_estimate_input(context, action_input, reading, preparation)

    def prepare_estimate_calculation(self, context, *, preparation, author_authority_ref,
            validate_current, **source_refs):
        """Produce one original estimate under the caller's actual source guard."""
        from integration.architect_research_estimate_calculations import prepare_architect_research_estimate_calculation

        context, action_input, reading = self._build_estimate_reading(context,
            preparation=preparation, **source_refs)
        return prepare_architect_research_estimate_calculation(context=context, action_input=action_input,
            reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=validate_current)

    def save_estimate_calculation(self, context, *, publications, read_guard, preparation,
            author_authority_ref, validate_current, **source_refs):
        """Produce and retain original estimate under the actual source guard."""
        from integration.architect_research_estimate_publication import ArchitectResearchEstimatePublicationStore
        from integration.architect_research_estimate_calculations import prepare_architect_research_estimate_calculation

        if (not isinstance(publications, ArchitectResearchEstimatePublicationStore)
                or publications.registry is not self.registry or publications.methods is not self.methods
                or publications.organizations is not self.organizations or not callable(read_guard)):
            raise TaskConflict('Research estimate save requires original registries and actual source guard')
        context = self._context(context)
        with read_guard(context.model_copy(deep=True)):
            context, action_input, reading = self._build_estimate_reading(context,
                preparation=preparation, **source_refs)
            calculation = prepare_architect_research_estimate_calculation(context=context, action_input=action_input,
                reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
                validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation, context=context, action_input=action_input, reading=reading)
            return {'kind': 'prepared', 'calculation': calculation, 'record': record}

    def _build_estimate_reading(self, context, *, preparation, **source_refs):
        """Freeze actual A13 sources without consuming the reserved estimate."""
        context = self._context(context)
        preparation = ArchitectResearchEstimatePreparation.model_validate(preparation).model_copy(deep=True)
        registration = self.registry.get(self.ACTION_ID)
        if registration.role != 'Architect' or not registration.implemented or registration.skill is None:
            raise TaskConflict('Research estimate requires original implemented A13 and Architect Skill')
        action_input = registration.contract.validate_input(source_refs)
        future = preparation.calculation_ref.key()
        projection = self._views.assemble(context, self.ACTION_ID, 'Architect')
        if any(row.ref == preparation.calculation_ref for row in projection.objects):
            raise TaskConflict('Research estimate cannot replace an already supplied result target')
        resolver = ReferenceResolver(context.run_id, source_mode=self.source_mode, schemas=self.SOURCE_SCHEMAS())
        for row in projection.objects:
            resolver.register_projection(row.ref, row.value)
        resolver.freeze_read(context.read_token, [row.ref for row in projection.objects])
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'Architect',
            methods=self.methods, method_refs=registration.skill.manifest.method_refs)
        try:
            for ref in [*(row.ref for row in projection.objects), *walk_references(action_input)]:
                if ref.key() != future:
                    reading.resolve(ref)
            validate_architect_research_estimate_preparation_sources(action_input, preparation=preparation,
                context=context, organization_id=reading.organization_id, sources=reading._reads)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise TaskConflict('Research estimate requires original authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            return context, action_input, reading
        finally:
            reading.recheck()

    def build(self, context, *, scope, brief_ref, research_authority_ref, task_ref,
            design_profile_ref, expenditure_limit_ref, comparison_scope_ref,
            available_option_refs, professional_refs, cost_refs, comparison_method_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'brief_ref': brief_ref, 'research_authority_ref': research_authority_ref,
            'task_ref': task_ref, 'design_profile_ref': design_profile_ref,
            'expenditure_limit_ref': expenditure_limit_ref, 'comparison_scope_ref': comparison_scope_ref,
            'available_option_refs': available_option_refs, 'professional_refs': professional_refs,
            'cost_refs': cost_refs, 'comparison_method_ref': comparison_method_ref},
            prepared_type=PreparedArchitectResearch, validate_sources=validate_architect_research_sources)


def validate_architect_research_estimate_preparation_sources(action_input, *, preparation, context, organization_id, sources):
    """Keep original request/result identities and exclude the future estimate."""
    task = sources.get(action_input.task_ref.key())
    request = sources.get(preparation.request_profile_ref.key())
    if (not isinstance(task, ArchitectResearchTaskView) or not isinstance(request, ArchitectResearchRequestView)
            or task.request_profile_ref != request.ref or request.task_ref != task.ref
            or request.estimate_ref != preparation.calculation_ref
            or preparation.calculation_ref.key() in sources):
        raise TaskConflict('Estimate preparation must retain original request and its independent future result')
    return validate_architect_research_sources(action_input, context=context,
        organization_id=organization_id, sources=sources)


def validate_architect_research_sources(action_input, *, context, organization_id, sources):
    """Check original task/brief/delegation identities without evaluating research."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Architect research lacks its exact original concrete source')
        if not scope_covers(row.scope, context.scope):
            raise TaskConflict('Architect research source does not cover its original invocation scope')
        return row

    def same_task(row):
        if row.task_ref.key() != task.ref.key():
            raise TaskConflict('Architect research source changes its original task')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Architect research changes its original invocation scope')
    brief = read(action_input.brief_ref, QSCostBriefView)
    task = read(action_input.task_ref, ArchitectResearchTaskView)
    profile = read(action_input.design_profile_ref, ArchitectResearchProfileView)
    grant = same_task(read(action_input.research_authority_ref, ArchitectResearchAuthorityView))
    limit = same_task(read(action_input.expenditure_limit_ref, ArchitectResearchLimitView))
    comparison = same_task(read(action_input.comparison_scope_ref, ArchitectResearchScopeView))
    if (task.organization_id != organization_id or task.function_ref.key() != context.function_ref.key()
            or task.brief_ref.key() != brief.ref.key() or task.design_profile_ref.key() != profile.ref.key()
            or task.expenditure_limit_ref.key() != limit.ref.key() or task.comparison_scope_ref.key() != comparison.ref.key()
            or task.comparison_method_ref != action_input.comparison_method_ref or comparison.brief_ref.key() != brief.ref.key()
            or grant.brief_ref.key() != brief.ref.key() or grant.delegate_organization_id != organization_id
            or grant.delegate_actor_id != context.actor_id or grant.delegate_function_ref.key() != context.function_ref.key()
            or limit.organization_id != organization_id):
        raise TaskConflict('Architect research changes original delegation, task, brief, profile or limits')
    unique_refs(grant.allowed_input_refs)
    for field in ('available_option_refs', 'professional_refs', 'cost_refs'):
        unique_refs(getattr(action_input, field))
        unique_refs(getattr(task, field))
    candidates = {ref.key() for ref in task.available_option_refs}
    for ref in action_input.available_option_refs:
        option = same_task(read(ref, ArchitectResearchOptionView))
        if option.brief_ref.key() != brief.ref.key() or option.design_profile_ref.key() != profile.ref.key():
            raise TaskConflict('Architect research option changes its original brief or design profile')
    for ref in action_input.professional_refs:
        assessment = read(ref, ArchitectResearchAssessmentView)
        if assessment.brief_ref.key() != brief.ref.key() or assessment.option_ref.key() not in candidates:
            raise TaskConflict('Architect research professional source changes its original brief or candidate')
    for ref in action_input.cost_refs:
        cost = read(ref, QSResearchCostPlanView)
        if (cost.brief_ref.key() != brief.ref.key() or cost.draft.option_ref is None
                or cost.draft.option_ref.key() not in candidates):
            raise TaskConflict('Architect research cost source changes its original brief or candidate')
    if action_input.comparison_method_ref is not None:
        method = same_task(read(action_input.comparison_method_ref, ArchitectResearchMethodView))
        if method.comparison_scope_ref.key() != comparison.ref.key():
            raise TaskConflict('Architect comparison method changes its original comparison scope')
    for ref in (grant.acceptance_ref, grant.confirmation_ref):
        if ref.key() in sources:
            decision = read(ref, ArchitectResearchDecisionView)
            if (decision.organization_id != organization_id or decision.actor_id != context.actor_id
                    or decision.function_ref.key() != context.function_ref.key()
                    or decision.service_request_ref.key() != grant.service_request_ref.key()
                    or decision.accepted_terms_ref.key() != grant.accepted_terms_ref.key()
                    or decision.terms_digest != grant.terms_digest
                    or ref == grant.confirmation_ref and decision.appointment_ref != grant.appointment_ref):
                raise TaskConflict('Architect research acceptance changes its original party, request or terms')
    unique_refs(limit.expense_refs)
    for ref in limit.expense_refs:
        if ref.key() in sources:
            expense = same_task(read(ref, QSResearchExpenseView))
            if expense.cost_fact_ref.key() in sources:
                fact = same_task(read(expense.cost_fact_ref, QSResearchCostFactView))
                if (fact.organization_id != organization_id or expense.amount != fact.amount
                        or expense.effort != fact.effort or expense.status != fact.status):
                    raise TaskConflict('Architect research expense changes its original cost/work fact')
    unique_refs(task.question_refs)
    for ref in task.question_refs:
        if ref.key() in sources:
            gap = same_task(read(ref, ArchitectResearchGapView))
            if gap.brief_ref.key() != brief.ref.key() or gap.question.scope != action_input.scope:
                raise TaskConflict('Architect research question changes its original brief or scope')
    if task.request_profile_ref is None or task.request_profile_ref.key() not in sources:
        return
    request = same_task(read(task.request_profile_ref, ArchitectResearchRequestView))
    if request.scope != action_input.scope:
        raise TaskConflict('Architect investigation request changes its original scope')
    for refs in (request.input_refs, request.output_requirement_refs, request.authority_basis_refs, request.dependency_refs):
        unique_refs(refs)
    for ref in [*request.output_requirement_refs, *request.dependency_refs,
            *([request.work_profile_ref] if request.work_profile_ref is not None else [])]:
        if ref.key() in sources:
            same_task(read(ref, ArchitectResearchReferenceView))
    if request.estimate_ref is not None and request.estimate_ref.key() in sources:
        estimate = same_task(read(request.estimate_ref, ArchitectResearchEstimateView))
        unique_refs(estimate.input_refs)
        if (estimate.request_profile_ref.key() != request.ref.key() or set(estimate.input_refs) != set(request.input_refs)
                or estimate.work_profile_ref != request.work_profile_ref or estimate.incremental_cost != request.incremental_cost
                or estimate.effort_estimate != request.effort_estimate):
            raise TaskConflict('Architect research estimate changes its original request, inputs or estimates')
        if estimate.method_ref.key() in sources:
            estimate_method = read(estimate.method_ref, ArchitectResearchEstimateMethodView)
            if estimate_method.design_profile_ref.key() != profile.ref.key():
                raise TaskConflict('Architect investigation estimate method changes its original design profile')
