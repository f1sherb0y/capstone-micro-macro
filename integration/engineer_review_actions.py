"""Assemble original Engineer A06 reviews and saved interface-check sources."""
from dataclasses import dataclass
from typing import ClassVar

from integration.engineer_opportunity_actions import EngineerOpportunityActionAssembler, PreparedEngineerOpportunity
from src.actions.contracts.architect_review_objects import ArchitectReviewIssueView
from src.actions.contracts.engineer_appointment_objects import EngineerAppointmentView
from src.actions.contracts.engineer_review_objects import (
    EngineerReviewTargetView, EngineerReviewRequestView, EngineerReviewTaskView,
    EngineerReviewSpecView, EngineerReviewResultView, EngineerReviewInterfaceView,
    EngineerReviewScopeView, EngineerReviewIndependenceView, EngineerReviewQuestionView,
    EngineerReviewCheckPreparation,
    engineer_review_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedEngineerReview(PreparedEngineerOpportunity):
    ACTION_ID: ClassVar[str] = 'ENGINEER-A06'


class EngineerReviewActionAssembler(EngineerOpportunityActionAssembler):
    """Freeze original review identities under the application's current read guard.

    Original processor checks author/reviewer authority and independence, actual
    method results, evidence, coverage and unresolved interfaces. Requests for
    evidence or coordination retain their original choices; no content edits,
    approvals, permitted use or independent findings are created by assembly.
    """
    ACTION_ID = 'ENGINEER-A06'
    SOURCE_SCHEMAS = staticmethod(engineer_review_schemas)

    def prepare_check_calculation(self, context, *, preparation, author_authority_ref,
            validate_current, **source_refs):
        """Produce one independently authorized check under the caller's source guard."""
        from integration.engineer_review_check_calculations import prepare_engineer_review_check_calculation

        context, action_input, reading = self._build_check_reading(context, preparation=preparation, **source_refs)
        return prepare_engineer_review_check_calculation(context=context, action_input=action_input,
            reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=validate_current)

    def _build_check_reading(self, context, *, preparation, **source_refs):
        """Reuse future-result isolation while retaining A06 schemas and grants."""
        from integration.engineer_design_actions import EngineerDesignActionAssembler

        return EngineerDesignActionAssembler._build_calculation_reading(self, context, preparation=preparation,
            preparation_model=EngineerReviewCheckPreparation,
            validate_sources=validate_engineer_review_check_preparation_sources, **source_refs)

    def save_check_calculation(self, context, *, publications, read_guard, preparation,
            author_authority_ref, validate_current, **source_refs):
        """Produce and retain one original A06 check; publish separately."""
        from integration.engineer_review_check_publication import EngineerReviewCheckPublicationStore
        from integration.engineer_review_check_calculations import prepare_engineer_review_check_calculation

        if (not isinstance(publications,EngineerReviewCheckPublicationStore)
                or publications.registry is not self.registry or publications.methods is not self.methods
                or publications.organizations is not self.organizations or not callable(read_guard)):
            raise TaskConflict('Review check save requires original registries and actual source writer guard')
        context=self._context(context)
        with read_guard(context.model_copy(deep=True)):
            context,action_input,reading=self._build_check_reading(context,preparation=preparation,**source_refs)
            calculation=prepare_engineer_review_check_calculation(context=context,action_input=action_input,
                reading=reading,preparation=preparation,author_authority_ref=author_authority_ref,
                validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record=publications.save(calculation,context=context,action_input=action_input,reading=reading)
            return {'kind':'prepared','calculation':calculation,'record':record}

    def build(self, context, *, scope, target_ref, review_request_ref, check_spec_refs,
            method_result_refs, independence_check_ref, interface_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'target_ref': target_ref, 'review_request_ref': review_request_ref,
            'check_spec_refs': check_spec_refs, 'method_result_refs': method_result_refs,
            'independence_check_ref': independence_check_ref, 'interface_refs': interface_refs},
            prepared_type=PreparedEngineerReview, validate_sources=validate_engineer_review_sources)


def validate_engineer_review_sources(action_input, *, context, organization_id, sources):
    """Check original parties and supplied source identities without judging work."""
    return _validate_engineer_review_sources(action_input,context=context,
        organization_id=organization_id,sources=sources,pending_result_keys=frozenset())


def validate_engineer_review_check_preparation_sources(action_input, *, preparation, context, organization_id, sources):
    """Retain original review/spec registration while isolating future checks."""
    request=sources.get(action_input.review_request_ref.key())
    if (not isinstance(request,EngineerReviewRequestView) or request.choice != 'assess'
            or {ref.key() for ref in request.received_method_result_refs} != {ref.key() for ref in action_input.method_result_refs}
            or preparation.check_spec_ref not in action_input.check_spec_refs
            or preparation.calculation_ref not in action_input.method_result_refs):
        raise TaskConflict('Review production must retain original assess request/spec/result inputs')
    task=sources.get(request.task_ref.key())
    if not isinstance(task,EngineerReviewTaskView):
        raise TaskConflict('Review production requires its original concrete task')
    unique_refs([row.check_spec_ref for row in task.check_result_targets])
    unique_refs([row.calculation_ref for row in task.check_result_targets])
    selected=next((row for row in task.check_result_targets if row.check_spec_ref == preparation.check_spec_ref),None)
    if selected is not None and selected.calculation_ref != preparation.calculation_ref:
        raise TaskConflict('Review production substitutes original spec/result target mapping')
    pending=frozenset(ref.key() for ref in action_input.method_result_refs)
    if pending.intersection(sources):
        raise TaskConflict('Review production cannot consume reserved result outputs')
    return _validate_engineer_review_sources(action_input,context=context,
        organization_id=organization_id,sources=sources,pending_result_keys=pending)


def _validate_engineer_review_sources(action_input, *, context, organization_id, sources, pending_result_keys):
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Engineer review lacks its exact original concrete source')
        if hasattr(row, 'scope') and not scope_covers(action_input.scope, row.scope):
            raise TaskConflict('Engineer review source leaves its original authorized scope')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Engineer review changes its original invocation scope')
    for refs in (action_input.check_spec_refs, action_input.method_result_refs, action_input.interface_refs):
        unique_refs(refs)
    target = read(action_input.target_ref, EngineerReviewTargetView)
    request = read(action_input.review_request_ref, EngineerReviewRequestView)
    if (request.organization_id != organization_id or request.target_ref.key() != target.ref.key()
            or request.content_sha256 != target.content_sha256):
        raise TaskConflict('Engineer review changes its original organization, target or content version')

    def bound(row):
        if (row.review_request_ref.key() != request.ref.key() or row.target_ref.key() != target.ref.key()
                or row.content_sha256 != target.content_sha256):
            raise TaskConflict('Engineer review source changes its original request, target or content version')

    if request.task_ref.key() in sources:
        task = read(request.task_ref, EngineerReviewTaskView)
        if (task.organization_id != organization_id or task.review_request_ref.key() != request.ref.key()
                or task.appointment_ref.key() != request.appointment_ref.key()
                or task.target_ref.key() != target.ref.key() or task.requested_use != request.requested_use):
            raise TaskConflict('Engineer review task changes its original parties, appointment, target or use')
    if request.appointment_ref.key() in sources:
        read(request.appointment_ref, EngineerAppointmentView)
    for ref in action_input.check_spec_refs:
        bound(read(ref, EngineerReviewSpecView))
    for ref in action_input.method_result_refs:
        if ref.key() in pending_result_keys:
            continue
        result = read(ref, EngineerReviewResultView)
        bound(result)
        if result.task_ref.key() != request.task_ref.key():
            raise TaskConflict('Engineer saved review execution changes its original task')
    for ref in action_input.interface_refs:
        bound(read(ref, EngineerReviewInterfaceView))
    for ref in request.engineering_scope_refs:
        if ref.key() in sources:
            bound(read(ref, EngineerReviewScopeView))
    if action_input.independence_check_ref is not None:
        read(action_input.independence_check_ref, EngineerReviewIndependenceView)
    # Original processor determines completeness, nullable check/template relation,
    # actual author/reviewer separation and current independent verifier authority.
    for ref in request.question_refs:
        if ref.key() in sources:
            question = read(ref, EngineerReviewQuestionView)
            if question.review_request_ref.key() != request.ref.key() or question.target_ref.key() != target.ref.key():
                raise TaskConflict('Engineer review question changes its original request or target')
    for ref in [*target.unresolved_issue_refs, *request.coordination_issue_refs]:
        if ref.key() in sources and read(ref, ArchitectReviewIssueView).target_ref.key() != target.ref.key():
            raise TaskConflict('Engineer review issue changes its original target')
