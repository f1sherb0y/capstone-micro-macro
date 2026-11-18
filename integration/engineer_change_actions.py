"""Assemble original Engineer A09 remedy, revision and reassessment sources."""
from dataclasses import dataclass
from typing import ClassVar

from integration.engineer_opportunity_actions import EngineerOpportunityActionAssembler, PreparedEngineerOpportunity
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.engineer_change_objects import (
    EngineerChangeDeliverableView, EngineerChangeIssueView, EngineerChangeObligationView,
    EngineerChangeProfileView, EngineerChangeInstructionView, EngineerChangeBasisView,
    EngineerChangeQuestionView, EngineerChangeScopeView, EngineerChangeDependencyView,
    EngineerChangeMethodProjection, engineer_change_schemas,
    EngineerChangeCheckPreparation,
    EngineerChangeParameterPreparation,
    EngineerChangeRevisionCheckPreparation,
)
from src.actions.contracts.engineer_design_objects import EngineerDesignTaskView
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedEngineerChange(PreparedEngineerOpportunity):
    ACTION_ID: ClassVar[str] = 'ENGINEER-A09'


class EngineerChangeActionAssembler(EngineerOpportunityActionAssembler):
    """Freeze actual issue/obligation/version evidence under the current read guard.

    Original processor decides instruction requirements, remedy authority,
    permitted parameter changes, affected dependencies, independent rechecks and
    finite actual work. Fee disputes and missing instructions retain their
    original branches. Assembly creates no revision, instruction or obligation
    discharge and preserves the historical design and observed engineering facts.
    """
    ACTION_ID = 'ENGINEER-A09'
    SOURCE_SCHEMAS = staticmethod(engineer_change_schemas)

    def prepare_parameter_input(self, context, *, preparation, **source_refs):
        """Prepare original revision sources under the caller's actual read guard."""
        from src.actions.roles.engineer_change import prepare_engineer_change_parameter_input

        context, action_input, reading = self._build_parameter_reading(context,
            preparation=preparation, **source_refs)
        return prepare_engineer_change_parameter_input(context, action_input, reading, preparation)

    def _build_parameter_reading(self, context, *, preparation, **source_refs):
        """Freeze revision sources while isolating every future method result."""
        from integration.engineer_design_actions import EngineerDesignActionAssembler

        return EngineerDesignActionAssembler._build_calculation_reading(self, context,
            preparation=preparation, preparation_model=EngineerChangeParameterPreparation,
            validate_sources=validate_engineer_change_parameter_preparation_sources, **source_refs)

    def prepare_parameter_calculation(self, context, *, preparation, author_authority_ref,
            validate_current, **source_refs):
        """Produce one original revision parameter under the caller's source guard."""
        from integration.engineer_change_parameter_calculations import prepare_engineer_change_parameter_calculation

        context, action_input, reading = self._build_parameter_reading(context,
            preparation=preparation, **source_refs)
        return prepare_engineer_change_parameter_calculation(context=context, action_input=action_input,
            reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=validate_current)

    def save_parameter_calculation(self, context, *, publications, read_guard, preparation,
            author_authority_ref, validate_current, **source_refs):
        """Produce and retain one original revision parameter; publish separately."""
        from integration.engineer_change_parameter_publication import EngineerChangeParameterPublicationStore
        from integration.engineer_change_parameter_calculations import prepare_engineer_change_parameter_calculation

        if (not isinstance(publications, EngineerChangeParameterPublicationStore)
                or publications.registry is not self.registry or publications.methods is not self.methods
                or publications.organizations is not self.organizations or not callable(read_guard)):
            raise TaskConflict('Revision parameter save requires original registries and actual source writer guard')
        context = self._context(context)
        with read_guard(context.model_copy(deep=True)):
            context, action_input, reading = self._build_parameter_reading(context,
                preparation=preparation, **source_refs)
            calculation = prepare_engineer_change_parameter_calculation(context=context, action_input=action_input,
                reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
                validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation, context=context, action_input=action_input, reading=reading)
            return {'kind': 'prepared', 'calculation': calculation, 'record': record}

    def prepare_revision_check_input(self, context, *, preparation, **source_refs):
        """Prepare original revision check sources under the caller's read guard."""
        from src.actions.roles.engineer_change import prepare_engineer_change_revision_check_input

        context, action_input, reading = self._build_revision_check_reading(context,
            preparation=preparation, **source_refs)
        return prepare_engineer_change_revision_check_input(context, action_input, reading, preparation)

    def _build_revision_check_reading(self, context, *, preparation, **source_refs):
        """Freeze revision sources while isolating every reserved method result."""
        from integration.engineer_design_actions import EngineerDesignActionAssembler

        return EngineerDesignActionAssembler._build_calculation_reading(self, context,
            preparation=preparation, preparation_model=EngineerChangeRevisionCheckPreparation,
            validate_sources=validate_engineer_change_revision_check_preparation_sources, **source_refs)

    def prepare_revision_check_calculation(self, context, *, preparation, author_authority_ref,
            validate_current, **source_refs):
        """Produce one original revision interface check under the caller's guard."""
        from integration.engineer_change_revision_check_calculations import prepare_engineer_change_revision_check_calculation

        context, action_input, reading = self._build_revision_check_reading(context,
            preparation=preparation, **source_refs)
        return prepare_engineer_change_revision_check_calculation(context=context, action_input=action_input,
            reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=validate_current)

    def save_revision_check_calculation(self, context, *, publications, read_guard, preparation,
            author_authority_ref, validate_current, **source_refs):
        """Produce and retain one original revision check; publish separately."""
        from integration.engineer_change_revision_check_publication import EngineerChangeRevisionCheckPublicationStore
        from integration.engineer_change_revision_check_calculations import prepare_engineer_change_revision_check_calculation

        if (not isinstance(publications, EngineerChangeRevisionCheckPublicationStore)
                or publications.registry is not self.registry or publications.methods is not self.methods
                or publications.organizations is not self.organizations or not callable(read_guard)):
            raise TaskConflict('Revision check save requires original registries and actual source writer guard')
        context = self._context(context)
        with read_guard(context.model_copy(deep=True)):
            context, action_input, reading = self._build_revision_check_reading(context,
                preparation=preparation, **source_refs)
            calculation = prepare_engineer_change_revision_check_calculation(context=context, action_input=action_input,
                reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
                validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation, context=context, action_input=action_input, reading=reading)
            return {'kind': 'prepared', 'calculation': calculation, 'record': record}

    def prepare_check_calculation(self, context, *, preparation, author_authority_ref,
            validate_current, **source_refs):
        """Produce one original version recheck under the caller's source guard."""
        from integration.engineer_change_check_calculations import prepare_engineer_change_check_calculation

        context, action_input, reading = self._build_check_reading(context, preparation=preparation, **source_refs)
        return prepare_engineer_change_check_calculation(context=context, action_input=action_input,
            reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=validate_current)

    def _build_check_reading(self, context, *, preparation, **source_refs):
        """Freeze original obligation/reassessment inputs without future results."""
        from integration.engineer_design_actions import EngineerDesignActionAssembler

        return EngineerDesignActionAssembler._build_calculation_reading(self, context, preparation=preparation,
            preparation_model=EngineerChangeCheckPreparation,
            validate_sources=validate_engineer_change_check_preparation_sources, **source_refs)

    def save_check_calculation(self, context, *, publications, read_guard, preparation,
            author_authority_ref, validate_current, **source_refs):
        """Produce and retain one original A09 recheck; publish separately."""
        from integration.engineer_change_check_publication import EngineerChangeCheckPublicationStore
        from integration.engineer_change_check_calculations import prepare_engineer_change_check_calculation

        if (not isinstance(publications, EngineerChangeCheckPublicationStore)
                or publications.registry is not self.registry or publications.methods is not self.methods
                or publications.organizations is not self.organizations or not callable(read_guard)):
            raise TaskConflict('Change check save requires original registries and actual source writer guard')
        context = self._context(context)
        with read_guard(context.model_copy(deep=True)):
            context, action_input, reading = self._build_check_reading(context, preparation=preparation, **source_refs)
            calculation = prepare_engineer_change_check_calculation(context=context, action_input=action_input,
                reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
                validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation, context=context, action_input=action_input, reading=reading)
            return {'kind': 'prepared', 'calculation': calculation, 'record': record}

    def build(self, context, *, scope, issue_ref, obligation_ref, prior_deliverable_ref,
            instruction_ref, evidence_refs, method_result_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'issue_ref': issue_ref, 'obligation_ref': obligation_ref,
            'prior_deliverable_ref': prior_deliverable_ref, 'instruction_ref': instruction_ref,
            'evidence_refs': evidence_refs, 'method_result_refs': method_result_refs},
            prepared_type=PreparedEngineerChange, validate_sources=validate_engineer_change_sources)


def validate_engineer_change_sources(action_input, *, context, organization_id, sources):
    return _validate_engineer_change_sources(action_input, context=context,
        organization_id=organization_id, sources=sources, pending_result_keys=frozenset())


def validate_engineer_change_parameter_preparation_sources(action_input, *, preparation, context, organization_id, sources):
    """Bind the original revise branch, own parent and reserved parameter target."""
    from integration.engineer_design_actions import validate_engineer_parameter_preparation_sources

    preparation = EngineerChangeParameterPreparation.model_validate(preparation)
    return _validate_engineer_change_revision_preparation_sources(action_input, preparation=preparation,
        context=context, organization_id=organization_id, sources=sources,
        validate_design=validate_engineer_parameter_preparation_sources)


def validate_engineer_change_revision_check_preparation_sources(action_input, *, preparation, context, organization_id, sources):
    """Bind original revise task/spec/result mapping without consuming outputs."""
    from integration.engineer_design_actions import validate_engineer_check_preparation_sources

    preparation = EngineerChangeRevisionCheckPreparation.model_validate(preparation)
    return _validate_engineer_change_revision_preparation_sources(action_input, preparation=preparation,
        context=context, organization_id=organization_id, sources=sources,
        validate_design=validate_engineer_check_preparation_sources)


def _validate_engineer_change_revision_preparation_sources(action_input, *, preparation, context,
        organization_id, sources, validate_design):
    from types import SimpleNamespace

    issue = sources.get(action_input.issue_ref.key())
    original = sources.get(action_input.prior_deliverable_ref.key())
    profile = sources.get(issue.change_profile_ref.key()) if isinstance(issue, EngineerChangeIssueView) else None
    task = sources.get(profile.revision_task_ref.key()) if (isinstance(profile, EngineerChangeProfileView)
        and profile.revision_task_ref is not None) else None
    if (not isinstance(original, EngineerChangeDeliverableView)
            or not isinstance(profile, EngineerChangeProfileView) or profile.choice != 'revise'
            or not isinstance(task, EngineerDesignTaskView) or task.draft is None
            or task.draft.parent_option_ref != original.option_ref
            or profile.change_basis_ref is None
            or {ref.key() for ref in profile.method_result_refs} != {ref.key() for ref in action_input.method_result_refs}):
        raise TaskConflict('Revision preparation replaces original branch, parent, basis or result set')
    pending = frozenset(ref.key() for ref in action_input.method_result_refs)
    if pending.intersection(sources):
        raise TaskConflict('Revision preparation cannot consume reserved result outputs')
    _validate_engineer_change_sources(action_input, context=context,
        organization_id=organization_id, sources=sources, pending_result_keys=pending)
    design_input = SimpleNamespace(scope=action_input.scope, brief_ref=original.brief_ref,
        task_ref=task.ref, engineering_profile_ref=original.engineering_profile_ref,
        evidence_refs=action_input.evidence_refs, method_result_refs=action_input.method_result_refs,
        prior_option_ref=original.option_ref)
    return validate_design(design_input, preparation=preparation,
        context=context, organization_id=organization_id, sources=sources)


def validate_engineer_change_check_preparation_sources(action_input, *, preparation, context, organization_id, sources):
    """Bind original reassess profile/task/spec and reserved result mapping."""
    issue = sources.get(action_input.issue_ref.key())
    profile = sources.get(issue.change_profile_ref.key()) if isinstance(issue, EngineerChangeIssueView) else None
    task = sources.get(profile.reassessment_task_ref.key()) if (isinstance(profile, EngineerChangeProfileView)
        and profile.reassessment_task_ref is not None) else None
    if (not isinstance(task, EngineerDesignTaskView) or profile.choice != 'reassess'
            or preparation.check_spec_ref not in profile.reassessment_check_refs
            or preparation.check_spec_ref not in task.check_spec_refs
            or preparation.calculation_ref not in task.method_result_refs
            or {ref.key() for ref in task.method_result_refs} != {ref.key() for ref in action_input.method_result_refs}):
        raise TaskConflict('Change preparation must retain original reassess task/spec/result inputs')
    unique_refs([row.check_spec_ref for row in task.check_result_targets])
    unique_refs([row.calculation_ref for row in task.check_result_targets])
    selected = next((row for row in task.check_result_targets if row.check_spec_ref == preparation.check_spec_ref), None)
    if selected is not None and selected.calculation_ref != preparation.calculation_ref:
        raise TaskConflict('Change preparation replaces original spec/result target mapping')
    pending = frozenset(ref.key() for ref in action_input.method_result_refs)
    if pending.intersection(sources):
        raise TaskConflict('Change preparation cannot consume reserved result outputs')
    return _validate_engineer_change_sources(action_input, context=context,
        organization_id=organization_id, sources=sources, pending_result_keys=pending)


def _validate_engineer_change_sources(action_input, *, context, organization_id, sources, pending_result_keys):
    """Check exact source identities without revising or reassessing engineering."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Engineer change lacks its exact original concrete source')
        if hasattr(row, 'scope') and not scope_covers(action_input.scope, row.scope):
            raise TaskConflict('Engineer change source leaves its original authorized scope')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Engineer change changes its original invocation scope')
    for refs in (action_input.evidence_refs, action_input.method_result_refs):
        unique_refs(refs)
    original = read(action_input.prior_deliverable_ref, EngineerChangeDeliverableView)
    issue = read(action_input.issue_ref, EngineerChangeIssueView)
    obligation = read(action_input.obligation_ref, EngineerChangeObligationView)
    if (obligation.organization_id != organization_id or issue.used_deliverable_ref.key() != original.ref.key()
            or issue.obligation_ref.key() != obligation.ref.key() or obligation.deliverable_ref.key() != original.ref.key()):
        raise TaskConflict('Engineer change replaces its original issue, obligation, organization or version')
    for ref in action_input.evidence_refs:
        read(ref, EvidenceRecord)
    for ref in action_input.method_result_refs:
        if ref.key() in pending_result_keys:
            continue
        wrapped = read(ref, EngineerChangeMethodProjection)
        if wrapped.record.ref.key() != ref.key():
            raise TaskConflict('Engineer saved change execution replaces its original record version')
    if action_input.instruction_ref is not None:
        instruction = read(action_input.instruction_ref, EngineerChangeInstructionView)
        if (instruction.issue_ref.key() != issue.ref.key() or instruction.obligation_ref.key() != obligation.ref.key()
                or instruction.used_deliverable_ref.key() != original.ref.key()
                or instruction.original_content_sha256 != original.content_sha256
                or instruction.contract_ref.key() != obligation.contract_ref.key()):
            raise TaskConflict('Engineer instruction changes its original issue, obligation, contract or content')
    if issue.change_profile_ref.key() not in sources:
        return
    profile = read(issue.change_profile_ref, EngineerChangeProfileView)
    if profile.issue_ref.key() != issue.ref.key() or profile.obligation_ref.key() != obligation.ref.key():
        raise TaskConflict('Engineer change profile replaces its original issue or obligation')
    for ref in (profile.revision_task_ref, profile.reassessment_task_ref):
        if ref is not None and ref.key() in sources:
            task = read(ref, EngineerDesignTaskView)
            if (task.organization_id != organization_id or task.appointment_ref.key() != obligation.appointment_ref.key()
                    or task.brief_ref.key() != original.brief_ref.key()
                    or task.engineering_profile_ref.key() != original.engineering_profile_ref.key()):
                raise TaskConflict('Engineer revision/recheck task replaces its original appointment, brief or profile')
    if profile.change_basis_ref is not None and profile.change_basis_ref.key() in sources:
        basis = read(profile.change_basis_ref, EngineerChangeBasisView)
        if (basis.issue_ref.key() != issue.ref.key() or basis.obligation_ref.key() != obligation.ref.key()
                or basis.prior_deliverable_ref.key() != original.ref.key()
                or basis.original_content_sha256 != original.content_sha256):
            raise TaskConflict('Engineer change basis replaces its original issue, obligation or content')
    for ref in profile.question_refs:
        if ref.key() in sources:
            gap = read(ref, EngineerChangeQuestionView)
            if gap.issue_ref.key() != issue.ref.key() or gap.used_deliverable_ref.key() != original.ref.key():
                raise TaskConflict('Engineer remedy question replaces its original issue or version')
    for ref in profile.reassessment_scope_refs:
        if ref.key() in sources and read(ref, EngineerChangeScopeView).used_deliverable_ref.key() != original.ref.key():
            raise TaskConflict('Engineer reassessment scope replaces its original version')
    for ref in original.dependency_refs:
        if ref.key() in sources and read(ref, EngineerChangeDependencyView).used_deliverable_ref.key() != original.ref.key():
            raise TaskConflict('Engineer affected dependency replaces its original version')
    # Current permission, instruction/draft digest, completeness, affected sets,
    # independent verifier evidence and all four choices remain processor-owned.
