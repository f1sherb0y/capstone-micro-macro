"""Assemble original QS A04 costing sources and independently saved calculations."""
from dataclasses import dataclass
from typing import ClassVar

from integration.qs_market_actions import QSMarketActionAssembler, PreparedQSMarket
from src.actions.contracts.qs_cost_objects import (
    QSCostBriefView, QSCostOptionView, QSCostTaskView, QSCostScopeView,
    QSCostComparisonBasisView, QSQuantityBasisView, QSQuantityScheduleView,
    QSCostPriceView, QSCostCalculationView, QSCostQuestionView,
    QSCostResponseRequirementView, qs_cost_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class PreparedQSCost(PreparedQSMarket):
    ACTION_ID: ClassVar[str] = 'QS-A04'


class QSCostActionAssembler(QSMarketActionAssembler):
    """Freeze actual quantity/price bases under the application's current read guard.

    The original processor checks author authority, physical coverage, quantity
    methods, price comparability and saved calculation arithmetic. Missing
    quantity/price evidence and failed calculations retain their own branches.
    Assembly creates no quantities, prices, approved budget or incurred cost.
    """
    ACTION_ID = 'QS-A04'
    SOURCE_SCHEMAS = staticmethod(qs_cost_schemas)

    def build(self, context, *, scope, brief_ref, option_ref, task_ref, cost_scope_ref,
            quantity_basis_refs, price_refs, method_result_refs, comparison_basis_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'brief_ref': brief_ref, 'option_ref': option_ref, 'task_ref': task_ref,
            'cost_scope_ref': cost_scope_ref, 'quantity_basis_refs': quantity_basis_refs,
            'price_refs': price_refs, 'method_result_refs': method_result_refs,
            'comparison_basis_ref': comparison_basis_ref}, prepared_type=PreparedQSCost,
            validate_sources=validate_qs_cost_sources)

    def prepare_calculation(self, context, *, calculation_ref, author_authority_ref, validate_current, **source_refs):
        """Prepare original arithmetic through this assembler's bound registry/Skill."""
        from integration.qs_cost_calculations import prepare_qs_cost_calculation

        prepared = self.build(context, **source_refs)
        return prepare_qs_cost_calculation(context=prepared.context, action_input=prepared.action_input,
            reading=prepared.reading, calculation_ref=calculation_ref,
            author_authority_ref=author_authority_ref, validate_current=validate_current)

    def publish_calculation(self, context, *, publications, next_context, read_guard,
            calculation_ref, author_authority_ref, validate_current, **source_refs):
        """Calculate once, save original execution, then publish under one source guard."""
        from integration.qs_cost_calculation_publication import QSCostCalculationPublicationStore
        from integration.qs_cost_calculations import prepare_qs_cost_calculation

        if (not isinstance(publications, QSCostCalculationPublicationStore)
                or publications.registry is not self.registry or publications.organizations is not self.organizations
                or publications.methods is not self.methods or not callable(read_guard)):
            raise TaskConflict('Cost publication requires the assembler original registries and actual source writer guard')
        with read_guard(context):
            prepared = self.build(context, **source_refs)
            calculation = prepare_qs_cost_calculation(context=prepared.context, action_input=prepared.action_input,
                reading=prepared.reading, calculation_ref=calculation_ref,
                author_authority_ref=author_authority_ref, validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation, context=prepared.context,
                action_input=prepared.action_input, reading=prepared.reading)
            publication = publications.publish(record['record_sha256'],
                source_context=prepared.context, next_context=next_context)
            return {'kind': 'prepared', 'calculation': calculation, 'record': record, 'publication': publication}


def validate_qs_cost_sources(action_input, *, context, organization_id, sources):
    """Check concrete original costing associations without producing amounts."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('QS cost lacks its exact original concrete source')
        if row.scope != action_input.scope:
            raise TaskConflict('QS cost source changes its original requested scope')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('QS cost changes its original invocation scope')
    for refs in (action_input.quantity_basis_refs, action_input.price_refs, action_input.method_result_refs):
        unique_refs(refs)
    brief = read(action_input.brief_ref, QSCostBriefView)
    option = read(action_input.option_ref, QSCostOptionView)
    task = read(action_input.task_ref, QSCostTaskView)
    cost_scope = read(action_input.cost_scope_ref, QSCostScopeView)
    comparison = read(action_input.comparison_basis_ref, QSCostComparisonBasisView)
    if (task.organization_id != organization_id or task.function_ref.key() != context.function_ref.key()
            or option.brief_ref.key() != brief.ref.key() or cost_scope.option_ref.key() != option.ref.key()
            or task.brief_ref.key() != brief.ref.key() or task.option_ref.key() != option.ref.key()
            or task.cost_scope_ref.key() != cost_scope.ref.key()
            or task.comparison_basis_ref.key() != comparison.ref.key()):
        raise TaskConflict('QS cost task changes its original organization, brief, option, scope or comparison')
    for ref in action_input.quantity_basis_refs:
        quantity = read(ref, QSQuantityBasisView)
        if quantity.option_ref.key() != option.ref.key():
            raise TaskConflict('QS quantity basis changes its original design option')
        if quantity.quantity_schedule_ref is not None and quantity.quantity_schedule_ref.key() in sources:
            schedule = read(quantity.quantity_schedule_ref, QSQuantityScheduleView)
            if schedule.option_ref.key() != option.ref.key():
                raise TaskConflict('QS quantity schedule changes its original design option')
    for ref in action_input.price_refs:
        read(ref, QSCostPriceView)
    for ref in action_input.method_result_refs:
        saved = read(ref, QSCostCalculationView)
        if (saved.task_ref.key() != task.ref.key() or saved.brief_ref.key() != brief.ref.key()
                or saved.option_ref.key() != option.ref.key() or saved.cost_scope_ref.key() != cost_scope.ref.key()
                or saved.comparison_basis_ref.key() != comparison.ref.key()):
            raise TaskConflict('QS saved calculation changes its original task or input versions')
    for item in cost_scope.items:
        for ref, issue in ((item.quantity_question_ref, 'quantity'), (item.price_question_ref, 'price'),
                (item.coverage_question_ref, 'coverage')):
            if ref.key() in sources:
                question = read(ref, QSCostQuestionView)
                if question.task_ref.key() != task.ref.key() or question.line_key != item.line_key or question.issue != issue:
                    raise TaskConflict('QS cost question changes its original task, line or missing input')
                if question.response_requirement_ref.key() in sources:
                    response = read(question.response_requirement_ref, QSCostResponseRequirementView)
                    if response.task_ref.key() != task.ref.key():
                        raise TaskConflict('QS cost response requirement changes its original task')
    # Exact input coverage, price/quantity compatibility, exclusions, arithmetic,
    # missing-data questions and technical failures remain processor decisions.
