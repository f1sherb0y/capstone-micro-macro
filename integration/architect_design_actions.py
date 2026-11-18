"""Assemble original Architect A05 finite design drafts and saved comparison sources."""
from copy import deepcopy
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import ClassVar

from integration.architect_opportunity_actions import ArchitectOpportunityActionAssembler, PreparedArchitectOpportunity
from src.actions.contracts.architect_appointment_objects import ArchitectAppointmentView
from src.actions.contracts.architect_design_objects import (
    ArchitectDesignAreaPreparation, ArchitectDesignAreaResultView, ArchitectDesignCoverageView, ArchitectDesignLimitView,
    ArchitectDesignProfileView, ArchitectDesignTaskView, ArchitectDesignVariableView, architect_design_schemas,
)
from src.actions.contracts.architect_planning_objects import ArchitectPlanningWorkFactView
from src.actions.contracts.architect_research_objects import (
    ArchitectResearchAssessmentView, ArchitectResearchGapView, ArchitectResearchMethodView,
    ArchitectResearchOptionView, ArchitectResearchScopeView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.contracts.qs_cost_objects import QSCostBriefView
from src.actions.contracts.qs_research_objects import QSResearchCostPlanView
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class PreparedArchitectDesign(PreparedArchitectOpportunity):
    ACTION_ID: ClassVar[str] = 'ARCHITECT-A05'


class ArchitectDesignActionAssembler(ArchitectOpportunityActionAssembler):
    """Freeze original catalog, work and method evidence under the current read guard.

    Empty available options and nullable comparison scope/method stay explicit.
    Original processor checks finite engagement limits, actual author work,
    supported area methods, draft variables and comparative coverage. Assembly
    creates no design version, investment, approval or change to Owner objectives.
    """
    ACTION_ID = 'ARCHITECT-A05'
    SOURCE_SCHEMAS = staticmethod(architect_design_schemas)

    def build_from_change_task(self, context, *, change_submission, change_identity,
            change_execution_versions, change_read_context, registration_ref, native_evidence_ref,
            native_source_sha256, relation_evidence_refs, read_guard, validate_history,
            validate_current, validate_receipt_relation, **source_refs):
        """Bind actual A09 proposal intake to A05 sources without creating a task."""
        from integration.architect_change_task_handoff import prepare_architect_change_task_handoff
        from integration.architect_change_results import ArchitectChangeResultWorker
        from integration.architect_submission import ArchitectResultSubmission
        from integration.macro_views import AuthorizedMacroViewAssembler
        from src.actions.contracts.architect_change_objects import architect_change_schemas

        if (not isinstance(change_submission, ArchitectResultSubmission)
                or change_submission.ACTION_ID != 'ARCHITECT-A09'
                or not isinstance(change_submission.worker, ArchitectChangeResultWorker)
                or change_submission.worker.registry is not self.registry
                or change_submission.worker.store.run_id != self.organizations.run_id or self.source_mode != 'formal'
                or not all(callable(callback) for callback in
                    (read_guard, validate_history, validate_current, validate_receipt_relation))):
            raise TaskConflict('Change task requires original A09 submission/worker and actual guarded source checks')
        context = self._context(context)
        own_context = ActionContext.model_validate(change_read_context).model_copy(deep=True)
        if (own_context.contract_ref.kind != 'ActionContract' or own_context.contract_ref.id != 'ARCHITECT-A09'
                or own_context.execution_mode == 'offline_fixture'
                or any(getattr(own_context, name) != getattr(context, name) for name in
                    ('run_id', 'scope', 'business_time', 'execution_mode'))):
            raise TaskConflict('Change intake requires independently authorized A09 history at the current A05 scope/time')
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(source_refs)
        if action_input.prior_option_ref is None:
            raise TaskConflict('Actual change task requires the original explicit parent option version')
        with read_guard(context.model_copy(deep=True)):
            receipt = change_submission.read_receipt(change_identity)
            if receipt['receipt']['disposition'] != 'accepted':
                raise TaskConflict('Rejected change proposal cannot establish actual revision intake')
            own_views = AuthorizedMacroViewAssembler(self.organizations, self.provider, architect_change_schemas(),
                macro_version=self.macro_version, source_mode='formal')
            own_resolver = own_views.build_resolver(own_context, 'ARCHITECT-A09', 'Architect')
            own_reading = ActionReadView(own_context, own_resolver, self.organizations, 'ARCHITECT-A09', 'Architect')
            reading = None
            try:
                saved = change_submission.worker.read_completed(change_identity, current_context=own_context,
                    reading=own_reading, execution_versions=change_execution_versions, validate_current=validate_history)
                reading = self.build_result_reading(context)
                preflight = SimpleNamespace(context=context, action_input=action_input, reading=reading)

                def validate_link(**sources):
                    if (sources['saved'].identity.as_dict() != receipt['identity']
                            or sources['saved'].record_sha256 != receipt['record_sha256']):
                        raise TaskConflict('Change proposal receipt substitutes its original saved result')
                    return (validate_current(**sources) is True
                        and validate_receipt_relation(receipt=deepcopy(receipt), **sources) is True)

                handoff = prepare_architect_change_task_handoff(saved, invocation=preflight,
                    registration_ref=registration_ref, native_evidence_ref=native_evidence_ref,
                    native_source_sha256=native_source_sha256, relation_evidence_refs=relation_evidence_refs,
                    validate_current=validate_link)
                if change_submission.read_receipt(change_identity) != receipt:
                    raise TaskConflict('Original change receipt changed during actual task linkage')
                if handoff['kind'] != 'prepared':
                    return handoff
                invocation = self.build(context, **source_refs)
                if any(invocation.reading._reads.get(key) != row for key, row in reading._reads.items()):
                    raise TaskConflict('Actual change task differs from the frozen A05 source snapshot')
                invocation.reading.recheck()
                if change_submission.read_receipt(change_identity) != receipt:
                    raise TaskConflict('Original change receipt changed before A05 assembly completed')
                return {**handoff, 'provenance': {**handoff['provenance'], 'submission': deepcopy(receipt)},
                    'invocation': replace(invocation, reading_sha256=task_digest(invocation.reading.evidence()))}
            finally:
                if reading is not None:
                    reading.recheck()
                own_reading.recheck()

    def prepare_area_calculation(self, context, *, preparation, author_authority_ref,
            validate_current, **source_refs):
        """Produce one area report while the caller holds its actual source guard.

        Predeclared report references remain in the original input. This path
        does not create a runnable design invocation or require future reports.
        """
        from integration.architect_area_calculations import prepare_architect_area_calculation

        context, action_input, reading = self._build_area_reading(context, preparation=preparation, **source_refs)
        return prepare_architect_area_calculation(context=context, action_input=action_input,
            reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=validate_current)

    def save_area_calculation(self, context, *, publications, read_guard, preparation,
            author_authority_ref, validate_current, **source_refs):
        """Produce and durably save under the actual source guard; publish separately."""
        from integration.architect_area_calculation_publication import ArchitectAreaCalculationPublicationStore
        from integration.architect_area_calculations import prepare_architect_area_calculation

        if (not isinstance(publications, ArchitectAreaCalculationPublicationStore)
                or publications.registry is not self.registry or publications.methods is not self.methods
                or publications.organizations is not self.organizations or not callable(read_guard)):
            raise TaskConflict('Area save requires original registries and actual source writer guard')
        context = self._context(context)
        with read_guard(context.model_copy(deep=True)):
            context, action_input, reading = self._build_area_reading(context, preparation=preparation, **source_refs)
            calculation = prepare_architect_area_calculation(context=context, action_input=action_input,
                reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
                validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation, context=context, action_input=action_input, reading=reading)
            return {'kind': 'prepared', 'calculation': calculation, 'record': record}

    def _build_area_reading(self, context, *, preparation, **source_refs):
        """Freeze preparation sources without making a runnable design invocation."""
        context = self._context(context)
        preparation = ArchitectDesignAreaPreparation.model_validate(preparation).model_copy(deep=True)
        registration = self.registry.get(self.ACTION_ID)
        if registration.role != 'Architect' or not registration.implemented or registration.skill is None:
            raise TaskConflict('Area assembly requires the original implemented action and Architect Skill')
        action_input = registration.contract.validate_input(source_refs)
        future_keys = {ref.key() for ref in action_input.method_result_refs}
        projection = self._views.assemble(context, self.ACTION_ID, 'Architect')
        if any(row.ref == preparation.calculation_ref for row in projection.objects):
            raise TaskConflict('Area production cannot replace an already supplied report target')
        resolver = ReferenceResolver(context.run_id, source_mode=self.source_mode, schemas=self.SOURCE_SCHEMAS())
        for row in projection.objects:
            resolver.register_projection(row.ref, row.value)
        resolver.freeze_read(context.read_token, [row.ref for row in projection.objects])
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'Architect',
            methods=self.methods, method_refs=registration.skill.manifest.method_refs)
        try:
            for row in projection.objects:
                if row.ref.key() not in future_keys:
                    reading.resolve(row.ref)
            for ref in walk_references(action_input):
                if ref.key() not in future_keys:
                    reading.resolve(ref)
            validate_architect_area_preparation_sources(action_input, preparation=preparation,
                context=context, organization_id=reading.organization_id, sources=reading._reads)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise TaskConflict('Area assembly requires its original authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            return context, action_input, reading
        finally:
            reading.recheck()

    def build(self, context, *, scope, brief_ref, task_ref, design_profile_ref, basis_refs,
            prior_option_ref, method_result_refs, available_option_refs, professional_refs,
            cost_refs, comparison_scope_ref, comparison_method_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'brief_ref': brief_ref, 'task_ref': task_ref, 'design_profile_ref': design_profile_ref,
            'basis_refs': basis_refs, 'prior_option_ref': prior_option_ref, 'method_result_refs': method_result_refs,
            'available_option_refs': available_option_refs, 'professional_refs': professional_refs, 'cost_refs': cost_refs,
            'comparison_scope_ref': comparison_scope_ref, 'comparison_method_ref': comparison_method_ref},
            prepared_type=PreparedArchitectDesign, validate_sources=validate_architect_design_sources)


def validate_architect_design_sources(action_input, *, context, organization_id, sources):
    """Check original task, brief, catalog and supplied work identities without compiling."""
    return _validate_architect_design_sources(action_input, context=context,
        organization_id=organization_id, sources=sources, pending_area_keys=frozenset())


def validate_architect_area_preparation_sources(action_input, *, preparation, context, organization_id, sources):
    """Keep exact original sources while reserving only declared area outputs."""
    task = sources.get(action_input.task_ref.key())
    if (not isinstance(task, ArchitectDesignTaskView) or task.choice != 'produce'
            or preparation.draft_index >= len(task.drafts)
            or {ref.key() for ref in task.method_result_refs} != {ref.key() for ref in action_input.method_result_refs}
            or task.drafts[preparation.draft_index].method_result_refs != [preparation.calculation_ref]):
        raise TaskConflict('Area preparation must retain its original produce task and declared draft result target')
    pending = frozenset(ref.key() for ref in task.method_result_refs)
    if pending.intersection(sources):
        raise TaskConflict('Area preparation cannot consume reserved report outputs')
    return _validate_architect_design_sources(action_input, context=context,
        organization_id=organization_id, sources=sources, pending_area_keys=pending)


def _validate_architect_design_sources(action_input, *, context, organization_id, sources, pending_area_keys):
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Architect design lacks its exact original concrete source')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Architect design changes its original invocation scope')
    for refs in (action_input.basis_refs, action_input.method_result_refs, action_input.available_option_refs,
            action_input.professional_refs, action_input.cost_refs):
        unique_refs(refs)
    brief = read(action_input.brief_ref, QSCostBriefView)
    task = read(action_input.task_ref, ArchitectDesignTaskView)
    profile = read(action_input.design_profile_ref, ArchitectDesignProfileView)
    if (task.organization_id != organization_id or task.brief_ref.key() != brief.ref.key()
            or task.design_profile_ref.key() != profile.ref.key()):
        raise TaskConflict('Architect design task changes its original organization, brief or catalog')
    if task.appointment_ref.key() in sources:
        read(task.appointment_ref, ArchitectAppointmentView)
    if task.design_limit_ref.key() in sources:
        limit = read(task.design_limit_ref, ArchitectDesignLimitView)
        if limit.appointment_ref.key() != task.appointment_ref.key():
            raise TaskConflict('Architect design limits change their original engagement')
    for ref in [*action_input.available_option_refs, *([action_input.prior_option_ref] if action_input.prior_option_ref is not None else [])]:
        if read(ref, ArchitectResearchOptionView).brief_ref.key() != brief.ref.key():
            raise TaskConflict('Architect design option changes its original brief')
    for ref in action_input.professional_refs:
        if read(ref, ArchitectResearchAssessmentView).brief_ref.key() != brief.ref.key():
            raise TaskConflict('Architect professional assessment changes its original brief')
    for ref in action_input.cost_refs:
        if read(ref, QSResearchCostPlanView).brief_ref.key() != brief.ref.key():
            raise TaskConflict('Architect comparison cost changes its original brief')
    if action_input.comparison_scope_ref is not None:
        comparison = read(action_input.comparison_scope_ref, ArchitectResearchScopeView)
        if comparison.task_ref.key() != task.ref.key() or comparison.brief_ref.key() != brief.ref.key():
            raise TaskConflict('Architect comparison scope changes its original task or brief')
    if action_input.comparison_method_ref is not None:
        method = read(action_input.comparison_method_ref, ArchitectResearchMethodView)
        if (method.task_ref.key() != task.ref.key() or action_input.comparison_scope_ref is not None
                and method.comparison_scope_ref.key() != action_input.comparison_scope_ref.key()):
            raise TaskConflict('Architect comparison method changes its original task or scope')
    for ref in action_input.method_result_refs:
        if ref.key() in pending_area_keys:
            continue
        result = read(ref, ArchitectDesignAreaResultView)
        if result.task_ref.key() != task.ref.key() or result.design_profile_ref.key() != profile.ref.key():
            raise TaskConflict('Architect area result changes its original task or catalog')
    for ref in profile.variable_refs:
        if ref.key() in sources and read(ref, ArchitectDesignVariableView).design_profile_ref.key() != profile.ref.key():
            raise TaskConflict('Architect design variable changes its original catalog')
    for ref in profile.coverage_refs:
        if ref.key() in sources and read(ref, ArchitectDesignCoverageView).design_profile_ref.key() != profile.ref.key():
            raise TaskConflict('Architect component coverage changes its original catalog')
    for ref in task.work_fact_refs:
        if ref.key() in sources:
            fact = read(ref, ArchitectPlanningWorkFactView)
            if fact.organization_id != organization_id or fact.task_ref.key() != task.ref.key():
                raise TaskConflict('Architect actual work changes its original organization or task')
    for ref in task.question_refs:
        if ref.key() in sources:
            gap = read(ref, ArchitectResearchGapView)
            if gap.task_ref.key() != task.ref.key() or gap.brief_ref.key() != brief.ref.key():
                raise TaskConflict('Architect design question changes its original task or brief')
