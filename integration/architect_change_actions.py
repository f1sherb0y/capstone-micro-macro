"""Freeze original Architect A09 obligations, design instructions and impact evidence."""
from dataclasses import dataclass
from typing import ClassVar

from integration.architect_opportunity_actions import ArchitectOpportunityActionAssembler, PreparedArchitectOpportunity
from src.actions.contracts.architect_change_objects import (
    ArchitectChangeDeliverableView, ArchitectChangeIssueView, ArchitectChangeObligationView,
    ArchitectChangeProfileView, ArchitectChangeInstructionView, ArchitectChangeDependencyView,
    ArchitectChangeImpactMethodView, ArchitectChangeImpactResultView, ArchitectChangeEntitlementView,
    ArchitectChangeQuestionView, architect_change_schemas,
    ArchitectChangeImpactPreparation,
)
from src.actions.contracts.architect_design_objects import ArchitectDesignVariableView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.common import walk_references
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.contracts.domain import CandidateSet
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class PreparedArchitectChange(PreparedArchitectOpportunity):
    ACTION_ID: ClassVar[str] = 'ARCHITECT-A09'


class ArchitectChangeActionAssembler(ArchitectOpportunityActionAssembler):
    """Keep explanation, proposed revision and separately decided fee rights distinct.

    Original processor checks unchanged content, instruction authority, variable
    limits, affected dependencies and executed impact evidence. Nullable inputs
    remain explicit. Assembly changes no design, obligation, works or fee right.
    """
    ACTION_ID = 'ARCHITECT-A09'
    SOURCE_SCHEMAS = staticmethod(architect_change_schemas)

    def prepare_impact_input(self, context, *, preparation, **source_refs):
        """Prepare original impact inputs under the caller's actual source guard."""
        from src.actions.roles.architect_change import prepare_architect_change_impact_input

        context, action_input, reading = self._build_impact_reading(context,
            preparation=preparation, **source_refs)
        return prepare_architect_change_impact_input(context, action_input, reading, preparation)

    def prepare_impact_calculation(self, context, *, preparation, author_authority_ref,
            validate_current, **source_refs):
        """Produce one original declared impact under the caller's source guard."""
        from integration.architect_change_impact_calculations import prepare_architect_change_impact_calculation

        context, action_input, reading = self._build_impact_reading(context,
            preparation=preparation, **source_refs)
        return prepare_architect_change_impact_calculation(context=context, action_input=action_input,
            reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=validate_current)

    def save_impact_calculation(self, context, *, publications, read_guard, preparation,
            author_authority_ref, validate_current, **source_refs):
        """Produce and retain original impact under the actual source writer guard."""
        from integration.architect_change_impact_publication import ArchitectChangeImpactPublicationStore
        from integration.architect_change_impact_calculations import prepare_architect_change_impact_calculation

        if (not isinstance(publications, ArchitectChangeImpactPublicationStore)
                or publications.registry is not self.registry or publications.methods is not self.methods
                or publications.organizations is not self.organizations or not callable(read_guard)):
            raise TaskConflict('Impact save requires original registries and actual source writer guard')
        context = self._context(context)
        with read_guard(context.model_copy(deep=True)):
            context, action_input, reading = self._build_impact_reading(context,
                preparation=preparation, **source_refs)
            calculation = prepare_architect_change_impact_calculation(context=context, action_input=action_input,
                reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
                validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation, context=context, action_input=action_input, reading=reading)
            return {'kind': 'prepared', 'calculation': calculation, 'record': record}

    def _build_impact_reading(self, context, *, preparation, **source_refs):
        """Freeze original A09 sources while isolating its reserved impact result."""
        context = self._context(context)
        preparation = ArchitectChangeImpactPreparation.model_validate(preparation).model_copy(deep=True)
        registration = self.registry.get(self.ACTION_ID)
        if registration.role != 'Architect' or not registration.implemented or registration.skill is None:
            raise TaskConflict('Impact preparation requires original implemented A09 and Architect Skill')
        action_input = registration.contract.validate_input(source_refs)
        future = {ref.key() for ref in action_input.impact_result_refs}
        projection = self._views.assemble(context, self.ACTION_ID, 'Architect')
        if any(row.ref == preparation.calculation_ref for row in projection.objects):
            raise TaskConflict('Impact preparation cannot replace an already supplied result target')
        resolver = ReferenceResolver(context.run_id, source_mode=self.source_mode, schemas=self.SOURCE_SCHEMAS())
        for row in projection.objects:
            resolver.register_projection(row.ref, row.value)
        resolver.freeze_read(context.read_token, [row.ref for row in projection.objects])
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'Architect',
            methods=self.methods, method_refs=registration.skill.manifest.method_refs)
        try:
            for ref in [*(row.ref for row in projection.objects), *walk_references(action_input)]:
                if ref.key() not in future:
                    reading.resolve(ref)
            validate_architect_change_impact_preparation_sources(action_input, preparation=preparation,
                context=context, organization_id=reading.organization_id, sources=reading._reads)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise TaskConflict('Impact preparation requires original authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            return context, action_input, reading
        finally:
            reading.recheck()

    def build(self, context, *, scope, issue_ref, used_deliverable_ref, obligation_ref,
            instruction_ref, impact_method_ref, impact_result_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'issue_ref': issue_ref, 'used_deliverable_ref': used_deliverable_ref,
            'obligation_ref': obligation_ref, 'instruction_ref': instruction_ref,
            'impact_method_ref': impact_method_ref, 'impact_result_refs': impact_result_refs},
            prepared_type=PreparedArchitectChange, validate_sources=validate_architect_change_sources)


def validate_architect_change_sources(action_input, *, context, organization_id, sources):
    return _validate_architect_change_sources(action_input, context=context,
        organization_id=organization_id, sources=sources, pending_result_keys=frozenset())


def validate_architect_change_impact_preparation_sources(action_input, *, preparation, context, organization_id, sources):
    """Bind the predeclared result and original method without consuming outputs."""
    preparation = ArchitectChangeImpactPreparation.model_validate(preparation)
    pending = frozenset(ref.key() for ref in action_input.impact_result_refs)
    if (action_input.impact_result_refs != [preparation.calculation_ref]
            or type(preparation.calculation_ref.version) is not str
            or action_input.impact_method_ref is None or pending.intersection(sources)):
        raise TaskConflict('Impact preparation changes original method/result or consumes reserved outputs')
    return _validate_architect_change_sources(action_input, context=context,
        organization_id=organization_id, sources=sources, pending_result_keys=pending)


def _validate_architect_change_sources(action_input, *, context, organization_id, sources, pending_result_keys):
    """Check original issue/version/contract identities without deciding a change."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Architect change lacks its exact original concrete source')
        return row

    def same_original(row):
        if row.used_deliverable_ref.key() != original.ref.key():
            raise TaskConflict('Architect change source changes its original used version')
        return row

    def same_issue(row):
        same_original(row)
        if row.issue_ref.key() != issue.ref.key():
            raise TaskConflict('Architect change source changes its original issue')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Architect change changes its original invocation scope')
    original = read(action_input.used_deliverable_ref, ArchitectChangeDeliverableView)
    issue = same_original(read(action_input.issue_ref, ArchitectChangeIssueView))
    obligation = read(action_input.obligation_ref, ArchitectChangeObligationView)
    if (issue.obligation_ref.key() != obligation.ref.key() or obligation.organization_id != organization_id
            or obligation.deliverable_ref.key() != original.ref.key()):
        raise TaskConflict('Architect design support changes original obligation, organization or version')
    unique_refs(original.dependency_refs)
    unique_refs([item.variable_ref for item in original.variables])
    unique_refs(obligation.variable_refs)
    unique_refs(obligation.permitted_impact_method_refs)
    if action_input.instruction_ref is not None:
        instruction = same_issue(read(action_input.instruction_ref, ArchitectChangeInstructionView))
        if (instruction.obligation_ref.key() != obligation.ref.key()
                or instruction.contract_ref.key() != obligation.contract_ref.key()):
            raise TaskConflict('Architect change instruction changes its original obligation or contract')
        unique_refs(instruction.authorized_variable_refs)
    if action_input.impact_method_ref is not None:
        method = read(action_input.impact_method_ref, ArchitectChangeImpactMethodView)
        if method.obligation_ref.key() != obligation.ref.key():
            raise TaskConflict('Architect impact method changes its original obligation')
    unique_refs(action_input.impact_result_refs)
    for ref in action_input.impact_result_refs:
        if ref.key() in pending_result_keys:
            continue
        result = same_issue(read(ref, ArchitectChangeImpactResultView))
        if result.instruction_ref != action_input.instruction_ref:
            raise TaskConflict('Architect impact result changes its original instruction')
        if action_input.impact_method_ref is not None and result.method_ref.key() != action_input.impact_method_ref.key():
            raise TaskConflict('Architect impact result changes its original method')
    for ref in original.dependency_refs:
        if ref.key() in sources:
            dependency = same_original(read(ref, ArchitectChangeDependencyView))
            unique_refs(dependency.depends_on_variable_refs)
    if issue.change_profile_ref.key() not in sources:
        return
    profile = read(issue.change_profile_ref, ArchitectChangeProfileView)
    if profile.issue_ref.key() != issue.ref.key() or profile.obligation_ref.key() != obligation.ref.key():
        raise TaskConflict('Architect change profile changes its original issue or obligation')
    for refs in (profile.response_basis_refs, profile.affected_dependency_refs, profile.question_refs,
            profile.impact_question_refs, [item.variable_ref for item in profile.proposed_variable_changes]):
        unique_refs(refs)
    for item in [*original.variables, *profile.proposed_variable_changes]:
        if item.variable_ref.key() in sources:
            variable = read(item.variable_ref, ArchitectDesignVariableView)
            if variable.design_profile_ref.key() != original.design_profile_ref.key():
                raise TaskConflict('Architect change variable changes its original design catalog')
    for ref in [*profile.question_refs, *profile.impact_question_refs]:
        if ref.key() in sources:
            question = same_issue(read(ref, ArchitectChangeQuestionView))
            if question.question.scope != action_input.scope:
                raise TaskConflict('Architect change question changes its original scope')
    if profile.fee_entitlement_ref is not None and profile.fee_entitlement_ref.key() in sources:
        entitlement = same_issue(read(profile.fee_entitlement_ref, ArchitectChangeEntitlementView))
        if (entitlement.obligation_ref.key() != obligation.ref.key()
                or entitlement.contract_ref.key() != obligation.contract_ref.key() or entitlement.cause != issue.kind):
            raise TaskConflict('Architect fee entitlement changes its original obligation, contract or cause')
