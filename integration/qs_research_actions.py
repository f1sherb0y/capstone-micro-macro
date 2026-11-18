"""Assemble original QS A13 cost comparisons and bounded research sources."""
from dataclasses import dataclass
from typing import ClassVar

from integration.qs_market_actions import QSMarketActionAssembler, PreparedQSMarket
from src.actions.contracts.qs_cost_objects import QSCostBriefView
from src.actions.contracts.qs_research_objects import (
    QSResearchAuthorityView, QSResearchTaskView, QSResearchOptionView, QSResearchBasisView,
    QSResearchAssessmentView, QSResearchCostPlanView, QSResearchProfileView, QSResearchLimitView,
    QSResearchExpenseView, QSResearchCostFactView, QSResearchRequestView, QSResearchGapView,
    QSResearchResponseView, QSResearchNormalizationView, QSResearchMethodProjection,
    QSResearchReferenceView,
    qs_research_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.common import ref_type, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class PreparedQSResearch(PreparedQSMarket):
    ACTION_ID: ClassVar[str] = 'QS-A13'


class QSResearchActionAssembler(QSMarketActionAssembler):
    """Freeze supplied originals under the application's current read guard.

    Original A04 costs, professional limits, comparison arithmetic and actual
    research spending remain processor checks. Assembly creates no estimates,
    successful calculations, supplier reservations or investment approvals.
    """
    ACTION_ID = 'QS-A13'
    SOURCE_SCHEMAS = staticmethod(qs_research_schemas)

    def prepare_normalization_input(self, context, *, calculation_ref, **source_refs):
        """Prepare original adjustments while the caller holds the actual source guard."""
        from src.actions.roles.qs_research import prepare_qs_research_normalization_input

        context, action_input, reading = self._build_normalization_reading(context,
            calculation_ref=calculation_ref, **source_refs)
        return prepare_qs_research_normalization_input(context, action_input, reading)

    def prepare_normalization_calculation(self, context, *, calculation_ref,
            author_authority_ref, validate_current, **source_refs):
        """Produce the fixed normalization once under the caller's actual source guard."""
        from integration.qs_research_normalization_calculations import prepare_qs_research_normalization_calculation

        context, action_input, reading = self._build_normalization_reading(context,
            calculation_ref=calculation_ref, **source_refs)
        return prepare_qs_research_normalization_calculation(context=context, action_input=action_input,
            reading=reading, calculation_ref=calculation_ref, author_authority_ref=author_authority_ref,
            validate_current=validate_current)

    def save_normalization_calculation(self, context, *, publications, read_guard,
            calculation_ref, author_authority_ref, validate_current, **source_refs):
        """Produce and retain one normalization under the actual source guard."""
        from integration.qs_research_normalization_calculations import prepare_qs_research_normalization_calculation
        from integration.qs_research_normalization_publication import QSResearchNormalizationPublicationStore

        if (not isinstance(publications, QSResearchNormalizationPublicationStore)
                or publications.registry is not self.registry or publications.methods is not self.methods
                or publications.organizations is not self.organizations or not callable(read_guard)):
            raise TaskConflict('Research normalization save requires original registries and actual source guard')
        context = self._context(context)
        with read_guard(context.model_copy(deep=True)):
            context, action_input, reading = self._build_normalization_reading(context,
                calculation_ref=calculation_ref, **source_refs)
            try:
                calculation = prepare_qs_research_normalization_calculation(context=context, action_input=action_input,
                    reading=reading, calculation_ref=calculation_ref, author_authority_ref=author_authority_ref,
                    validate_current=validate_current)
                if calculation['kind'] != 'prepared':
                    return calculation
                record = publications.save(calculation, context=context, action_input=action_input, reading=reading)
                return {'kind': 'prepared', 'calculation': calculation, 'record': record}
            finally:
                basis = reading._reads[action_input.comparison_basis_ref.key()]
                profile = reading._reads[basis.comparison_profile_ref.key()]
                future = {ref.key() for ref in (profile.normalization_result_ref, profile.ranking_result_ref)
                    if ref is not None}
                if future.intersection(reading._reads):
                    raise TaskConflict('Research normalization save cannot consume future comparison outputs')
                reading.recheck()

    def _build_normalization_reading(self, context, *, calculation_ref, **source_refs):
        """Freeze relevant original sources and isolate both future comparison reports."""
        return self._build_comparison_reading(context, calculation_ref=calculation_ref,
            kind='normalization', **source_refs)

    def prepare_ranking_input(self, context, *, calculation_ref, **source_refs):
        """Read original comparable costs without normalization or ranking execution."""
        from src.actions.roles.qs_research import prepare_qs_research_ranking_input

        context, action_input, reading = self._build_ranking_reading(context,
            calculation_ref=calculation_ref, **source_refs)
        return prepare_qs_research_ranking_input(context, action_input, reading)

    def prepare_ranking_calculation(self, context, *, calculation_ref, author_authority_ref,
            validate_current, validate_normalization_provenance, **source_refs):
        """Produce a fixed ranking under the caller's actual guarded source read."""
        from integration.qs_research_ranking_calculations import prepare_qs_research_ranking_calculation

        context, action_input, reading = self._build_ranking_reading(context,
            calculation_ref=calculation_ref, **source_refs)
        return prepare_qs_research_ranking_calculation(context=context, action_input=action_input,
            reading=reading, calculation_ref=calculation_ref, author_authority_ref=author_authority_ref,
            validate_current=validate_current, validate_normalization_provenance=validate_normalization_provenance)

    def save_ranking_calculation(self, context, *, publications, read_guard, calculation_ref,
            author_authority_ref, validate_current, validate_normalization_provenance, **source_refs):
        """Produce and retain one ranking with original normalization under the source guard."""
        from integration.qs_research_ranking_calculations import prepare_qs_research_ranking_calculation
        from integration.qs_research_ranking_publication import QSResearchRankingPublicationStore

        if (not isinstance(publications, QSResearchRankingPublicationStore)
                or publications.registry is not self.registry or publications.methods is not self.methods
                or publications.organizations is not self.organizations or not callable(read_guard)):
            raise TaskConflict('Research ranking save requires original registries and actual source guard')
        context = self._context(context)
        target = ref_type('MethodResult').model_validate(calculation_ref)
        with read_guard(context.model_copy(deep=True)):
            context, action_input, reading = self._build_ranking_reading(context,
                calculation_ref=target, **source_refs)
            try:
                calculation = prepare_qs_research_ranking_calculation(context=context, action_input=action_input,
                    reading=reading, calculation_ref=target, author_authority_ref=author_authority_ref,
                    validate_current=validate_current, validate_normalization_provenance=validate_normalization_provenance)
                if calculation['kind'] != 'prepared':
                    return calculation
                record = publications.save(calculation, context=context, action_input=action_input, reading=reading)
                return {'kind': 'prepared', 'calculation': calculation, 'record': record}
            finally:
                if target.key() in reading._reads:
                    raise TaskConflict('Research ranking save cannot consume its future ranking output')
                reading.recheck()

    def _build_ranking_reading(self, context, *, calculation_ref, **source_refs):
        return self._build_comparison_reading(context, calculation_ref=calculation_ref,
            kind='ranking', **source_refs)

    def _build_comparison_reading(self, context, *, calculation_ref, kind, **source_refs):
        if kind not in {'normalization','ranking'}:
            raise TaskConflict('Research comparison reading supports only fixed normalization and ranking routes')
        context = self._context(context)
        target = ref_type('MethodResult').model_validate(calculation_ref).model_copy(deep=True)
        registration = self.registry.get(self.ACTION_ID)
        if (registration.role != 'QS' or not registration.implemented or registration.skill is None
                or type(target.version) is not str):
            raise TaskConflict('Research comparison requires implemented QS A13, its Skill and immutable target')
        action_input = registration.contract.validate_input(source_refs)
        projection = self._views.assemble(context, self.ACTION_ID, 'QS')
        originals = {row.ref.key(): row.value for row in projection.objects}
        basis = originals.get(action_input.comparison_basis_ref.key())
        profile = (originals.get(basis.comparison_profile_ref.key())
            if isinstance(basis, QSResearchBasisView) and basis.comparison_profile_ref is not None else None)
        if (not isinstance(profile, QSResearchProfileView) or profile.task_ref != action_input.task_ref
                or profile.comparison_basis_ref != action_input.comparison_basis_ref
                or getattr(profile, kind + '_result_ref') != target):
            raise TaskConflict('Research comparison substitutes the original task, profile, basis or reserved target')
        targets = [ref for ref in (profile.normalization_result_ref, profile.ranking_result_ref) if ref is not None]
        unique_refs(targets)
        future_keys = {ref.key() for ref in targets if kind=='normalization' or ref==target}
        if future_keys.intersection(originals):
            raise TaskConflict('Research comparison cannot replace or consume already supplied comparison targets')
        resolver = ReferenceResolver(context.run_id, source_mode=self.source_mode, schemas=self.SOURCE_SCHEMAS())
        for row in projection.objects:
            resolver.register_projection(row.ref, row.value)
        resolver.freeze_read(context.read_token, [row.ref for row in projection.objects])
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'QS',
            methods=self.methods, method_refs=registration.skill.manifest.method_refs)
        try:
            # The processor reads the required cost history lazily. Unrelated
            # historical comparison reports are not inputs to this preparation.
            for ref in [*walk_references(action_input), basis.ref, profile.ref]:
                if ref.key() in future_keys:
                    raise TaskConflict('Research comparison input aliases a future comparison output')
                reading.resolve(ref)
            validate_qs_research_sources(action_input, context=context,
                organization_id=reading.organization_id, sources=reading._reads)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise TaskConflict('Research comparison requires its original authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                if candidate.ref.key() in future_keys:
                    raise TaskConflict('Research comparison candidate aliases a future comparison output')
                reading.resolve(candidate.ref)
            return context, action_input, reading
        finally:
            if future_keys.intersection(reading._reads):
                raise TaskConflict('Research comparison source reading contains a future comparison output')
            reading.recheck()

    def build(self, context, *, scope, brief_ref, research_authority_ref, task_ref,
            option_refs, assessment_refs, cost_plan_refs, comparison_basis_ref,
            expenditure_limit_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'brief_ref': brief_ref, 'research_authority_ref': research_authority_ref,
            'task_ref': task_ref, 'option_refs': option_refs, 'assessment_refs': assessment_refs,
            'cost_plan_refs': cost_plan_refs, 'comparison_basis_ref': comparison_basis_ref,
            'expenditure_limit_ref': expenditure_limit_ref}, prepared_type=PreparedQSResearch,
            validate_sources=validate_qs_research_sources)


def validate_qs_research_sources(action_input, *, context, organization_id, sources):
    """Check original research identities without calculating or spending."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('QS research lacks its exact original concrete source')
        if hasattr(row, 'scope') and row.scope != action_input.scope:
            raise TaskConflict('QS research source changes its original requested scope')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('QS research changes its original invocation scope')
    for refs in (action_input.option_refs, action_input.assessment_refs, action_input.cost_plan_refs):
        unique_refs(refs)
    brief = read(action_input.brief_ref, QSCostBriefView)
    task = read(action_input.task_ref, QSResearchTaskView)
    grant = read(action_input.research_authority_ref, QSResearchAuthorityView)
    basis = read(action_input.comparison_basis_ref, QSResearchBasisView)
    limit = read(action_input.expenditure_limit_ref, QSResearchLimitView)
    if (task.brief_ref != brief.ref or task.organization_id != organization_id
            or task.function_ref != context.function_ref or task.comparison_basis_ref != basis.ref
            or task.expenditure_limit_ref != limit.ref or grant.brief_ref != brief.ref
            or grant.task_ref != task.ref or grant.delegate_actor_id != context.actor_id
            or grant.delegate_organization_id != organization_id or grant.delegate_function_ref != context.function_ref
            or limit.task_ref != task.ref or limit.organization_id != organization_id):
        raise TaskConflict('QS research substitutes its original brief, task, delegation, comparison or limit')
    options = {ref.key() for ref in action_input.option_refs}
    for ref in action_input.option_refs:
        read(ref, QSResearchOptionView)
    for ref in action_input.assessment_refs:
        assessment = read(ref, QSResearchAssessmentView)
        if assessment.brief_ref != brief.ref or assessment.option_ref.key() not in options:
            raise TaskConflict('QS research assessment substitutes its original brief or option')
    for ref in action_input.cost_plan_refs:
        plan = read(ref, QSResearchCostPlanView)
        if plan.brief_ref != brief.ref or plan.draft.option_ref.key() not in options:
            raise TaskConflict('QS research cost plan substitutes its original brief or option')
        if plan.draft.calculation_ref is not None and plan.draft.calculation_ref.key() in sources:
            projection = read(plan.draft.calculation_ref, QSResearchMethodProjection)
            original = projection.cost
            if (original is None or original.scope != action_input.scope or original.brief_ref != brief.ref
                    or original.option_ref != plan.draft.option_ref or original.cost_scope_ref != plan.draft.cost_scope_ref
                    or original.comparison_basis_ref != plan.draft.comparison_basis_ref
                    or original.quantity_schedule_ref != plan.draft.quantity_schedule_ref):
                raise TaskConflict('QS research plan substitutes its original A04 calculation input versions')
    for ref in limit.expense_refs:
        if ref.key() not in sources:
            continue
        expense = read(ref, QSResearchExpenseView)
        if expense.task_ref != task.ref:
            raise TaskConflict('QS research expense substitutes another original task')
        if expense.cost_fact_ref.key() in sources:
            fact = read(expense.cost_fact_ref, QSResearchCostFactView)
            if fact.task_ref != task.ref or fact.organization_id != organization_id:
                raise TaskConflict('QS research expense substitutes its original cost fact or organization')
    for ref in task.question_refs:
        if ref.key() not in sources:
            continue
        question = read(ref, QSResearchGapView)
        if question.task_ref != task.ref or question.brief_ref != brief.ref:
            raise TaskConflict('QS research question substitutes its original task or brief')
        if question.response_requirement_ref.key() in sources:
            response = read(question.response_requirement_ref, QSResearchResponseView)
            if response.task_ref != task.ref:
                raise TaskConflict('QS research response substitutes its original task')
    if task.request_profile_ref is not None and task.request_profile_ref.key() in sources:
        request = read(task.request_profile_ref, QSResearchRequestView)
        if request.task_ref != task.ref:
            raise TaskConflict('QS research request substitutes its original task')
        for refs in (request.input_refs, request.output_requirement_refs, request.dependency_refs, request.authority_basis_refs):
            unique_refs(refs)
        for ref in request.input_refs:
            if ref.key() in sources:
                read(ref, QSResearchReferenceView)
        for ref in [*request.output_requirement_refs, *request.dependency_refs,
                *([request.work_profile_ref] if request.work_profile_ref is not None else [])]:
            if ref.key() in sources and read(ref, QSResearchReferenceView).task_ref != task.ref:
                raise TaskConflict('QS research request changes original work, requirement or dependency task')
    if basis.comparison_profile_ref is not None and basis.comparison_profile_ref.key() in sources:
        profile = read(basis.comparison_profile_ref, QSResearchProfileView)
        if profile.task_ref != task.ref or profile.comparison_basis_ref != basis.ref:
            raise TaskConflict('QS comparison profile substitutes its original task or basis')
        for ref in profile.normalization_basis_refs:
            if ref.key() in sources:
                normalization = read(ref, QSResearchNormalizationView)
                if normalization.comparison_basis_ref != basis.ref:
                    raise TaskConflict('QS normalization substitutes its original comparison basis')
        for ref in (profile.normalization_result_ref, profile.ranking_result_ref):
            if ref is None or ref.key() not in sources:
                continue
            projection = read(ref, QSResearchMethodProjection)
            original = projection.comparison
            if (original is None or original.scope != action_input.scope or original.task_ref != task.ref
                    or original.profile_ref != profile.ref or original.comparison_basis_ref != basis.ref):
                raise TaskConflict('QS comparison calculation substitutes its original task, profile or basis')
    # Exact sets, original authority, A04 quantity/price arithmetic, comparison
    # domains/ties and committed/incurred spending versus limits stay in the processor.
