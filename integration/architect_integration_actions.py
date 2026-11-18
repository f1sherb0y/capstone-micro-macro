"""Freeze original Architect A06 author inputs and scoped interface delegation."""
from copy import deepcopy
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import ClassVar

from integration.architect_opportunity_actions import ArchitectOpportunityActionAssembler, PreparedArchitectOpportunity
from src.actions.contracts.architect_integration_objects import (
    ArchitectIntegrationOptionView, ArchitectIntegrationProfileView, ArchitectIntegrationSourceView,
    ArchitectIntegrationAuthorityView, ArchitectIntegrationIssueView, ArchitectIntegrationInterfaceView,
    ArchitectIntegrationQuestionView, ArchitectIntegrationConsistencyView, ArchitectIntegrationMethodView,
    ArchitectIntegrationConsistencyPreparation,
    architect_integration_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.common import ActionContext
from src.actions.contracts.common import walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class PreparedArchitectIntegration(PreparedArchitectOpportunity):
    ACTION_ID: ClassVar[str] = 'ARCHITECT-A06'


class ArchitectIntegrationActionAssembler(ArchitectOpportunityActionAssembler):
    """Preserve each supplied author's original output under the current read guard.

    Nullable delegation, absent responses and unknown/conflicting conclusions
    stay explicit. The original processor checks independent author authority,
    received history, delegation, consistency digests and retained issues.
    Assembly does not override conclusions, close issues or grant approval.
    """
    ACTION_ID = 'ARCHITECT-A06'
    SOURCE_SCHEMAS = staticmethod(architect_integration_schemas)

    def prepare_consistency_calculation(self, context, *, preparation, author_authority_ref,
            validate_current, **source_refs):
        """Produce one original reference report under the caller's source guard."""
        from integration.architect_interface_consistency_calculations import prepare_architect_interface_consistency_calculation

        context, action_input, reading = self._build_consistency_reading(context, preparation=preparation, **source_refs)
        return prepare_architect_interface_consistency_calculation(context=context, action_input=action_input,
            reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
            validate_current=validate_current)

    def _build_consistency_reading(self, context, *, preparation, **source_refs):
        """Freeze original authors and delegation without requiring future reports."""
        context = self._context(context)
        preparation = ArchitectIntegrationConsistencyPreparation.model_validate(preparation).model_copy(deep=True)
        registration = self.registry.get(self.ACTION_ID)
        if registration.role != 'Architect' or not registration.implemented or registration.skill is None:
            raise TaskConflict('Consistency assembly requires the original implemented action and Architect Skill')
        action_input = registration.contract.validate_input(source_refs)
        projection = self._views.assemble(context, self.ACTION_ID, 'Architect')
        if any(row.ref == preparation.calculation_ref for row in projection.objects):
            raise TaskConflict('Consistency production cannot replace an already supplied report target')
        resolver = ReferenceResolver(context.run_id, source_mode=self.source_mode, schemas=self.SOURCE_SCHEMAS())
        for row in projection.objects:
            resolver.register_projection(row.ref, row.value)
        resolver.freeze_read(context.read_token, [row.ref for row in projection.objects])
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'Architect',
            methods=self.methods, method_refs=registration.skill.manifest.method_refs)
        try:
            option = reading.resolve(action_input.option_ref)
            if not isinstance(option, ArchitectIntegrationOptionView):
                raise TaskConflict('Consistency assembly requires its original concrete option')
            profile = reading.resolve(option.integration_profile_ref)
            if not isinstance(profile, ArchitectIntegrationProfileView):
                raise TaskConflict('Consistency assembly requires its original concrete profile')
            future_keys = {ref.key() for ref in profile.consistency_result_refs}
            for row in projection.objects:
                if row.ref.key() not in future_keys:
                    reading.resolve(row.ref)
            for ref in walk_references(action_input):
                reading.resolve(ref)
            reading.resolve(preparation.method_ref)
            validate_architect_consistency_preparation_sources(action_input, preparation=preparation,
                context=context, organization_id=reading.organization_id, sources=reading._reads)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise TaskConflict('Consistency assembly requires its original authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            return context, action_input, reading
        finally:
            reading.recheck()

    def save_consistency_calculation(self, context, *, publications, read_guard, preparation,
            author_authority_ref, validate_current, **source_refs):
        """Produce and durably save original reference proof; publish separately."""
        from integration.architect_interface_consistency_publication import ArchitectInterfaceConsistencyPublicationStore
        from integration.architect_interface_consistency_calculations import prepare_architect_interface_consistency_calculation

        if (not isinstance(publications, ArchitectInterfaceConsistencyPublicationStore)
                or publications.registry is not self.registry or publications.methods is not self.methods
                or publications.organizations is not self.organizations or not callable(read_guard)):
            raise TaskConflict('Consistency save requires original registries and actual source writer guard')
        context = self._context(context)
        with read_guard(context.model_copy(deep=True)):
            context, action_input, reading = self._build_consistency_reading(context, preparation=preparation, **source_refs)
            calculation = prepare_architect_interface_consistency_calculation(context=context, action_input=action_input,
                reading=reading, preparation=preparation, author_authority_ref=author_authority_ref,
                validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation, context=context, action_input=action_input, reading=reading)
            return {'kind': 'prepared', 'calculation': calculation, 'record': record}

    def build_from_registered_design(self, context, *, design_submission, design_identity,
            design_execution_versions, design_read_context, registration_ref, native_evidence_ref,
            native_source_sha256, relation_evidence_refs, read_guard, validate_history,
            validate_current, validate_receipt_relation, **source_refs):
        """Link an actually registered A05 draft without rerunning design work."""
        from integration.architect_design_registration_handoff import prepare_architect_design_registration_handoff
        from integration.architect_design_results import ArchitectDesignResultWorker
        from integration.architect_submission import ArchitectResultSubmission
        from integration.macro_views import AuthorizedMacroViewAssembler
        from src.actions.contracts.architect_design_objects import architect_design_schemas
        from src.actions.contracts.references import ActionReadView

        if (not isinstance(design_submission, ArchitectResultSubmission) or design_submission.ACTION_ID != 'ARCHITECT-A05'
                or not isinstance(design_submission.worker, ArchitectDesignResultWorker)
                or design_submission.worker.registry is not self.registry
                or design_submission.worker.store.run_id != self.organizations.run_id or self.source_mode != 'formal'
                or not all(callable(callback) for callback in
                    (read_guard, validate_history, validate_current, validate_receipt_relation))):
            raise TaskConflict('Design handoff requires original A05 submission/worker and actual guarded source checks')
        context = self._context(context)
        own_context = ActionContext.model_validate(design_read_context).model_copy(deep=True)
        if (own_context.contract_ref.kind != 'ActionContract' or own_context.contract_ref.id != 'ARCHITECT-A05'
                or own_context.execution_mode == 'offline_fixture'
                or any(getattr(own_context, name) != getattr(context, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'scope', 'business_time', 'execution_mode'))):
            raise TaskConflict('Design history requires separately declared current A05 authority at the same A06 read time')
        action_input = self.registry.get(self.ACTION_ID).contract.validate_input(source_refs)
        with read_guard(context.model_copy(deep=True)):
            receipt = design_submission.read_receipt(design_identity)
            if receipt['receipt']['disposition'] != 'accepted':
                raise TaskConflict('Rejected design submission cannot prove native option registration')
            own_views = AuthorizedMacroViewAssembler(self.organizations, self.provider, architect_design_schemas(),
                macro_version=self.macro_version, source_mode='formal')
            own_resolver = own_views.build_resolver(own_context, 'ARCHITECT-A05', 'Architect')
            own_reading = ActionReadView(own_context, own_resolver, self.organizations, 'ARCHITECT-A05', 'Architect')
            saved = design_submission.worker.read_completed(design_identity, current_context=own_context,
                reading=own_reading, execution_versions=design_execution_versions, validate_current=validate_history)
            reading = self.build_result_reading(context)
            preflight = SimpleNamespace(context=context, action_input=action_input, reading=reading)

            def validate_link(**sources):
                if (sources['saved'].identity.as_dict() != receipt['identity']
                        or sources['saved'].record_sha256 != receipt['record_sha256']):
                    raise TaskConflict('Design receipt substitutes its original saved draft result')
                return (validate_current(**sources) is True
                    and validate_receipt_relation(receipt=deepcopy(receipt), **sources) is True)

            handoff = prepare_architect_design_registration_handoff(saved, invocation=preflight,
                registration_ref=registration_ref, native_evidence_ref=native_evidence_ref,
                native_source_sha256=native_source_sha256, relation_evidence_refs=relation_evidence_refs,
                validate_current=validate_link)
            if design_submission.read_receipt(design_identity) != receipt:
                raise TaskConflict('Original design receipt changed during registered-option linkage')
            own_reading.recheck()
            if handoff['kind'] != 'prepared':
                return handoff
            invocation = self.build(context, **source_refs)
            if any(invocation.reading._reads.get(key) != row for key, row in reading._reads.items()):
                raise TaskConflict('Registered design linkage differs from the actual frozen A06 source snapshot')
            reading.recheck()
            invocation.reading.recheck()
            return {**handoff, 'provenance': {**handoff['provenance'], 'submission': deepcopy(receipt)},
                'invocation': replace(invocation, reading_sha256=task_digest(invocation.reading.evidence()))}

    def build(self, context, *, scope, option_ref, professional_refs, cost_refs,
            supply_refs, integration_authority_ref, open_issue_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'option_ref': option_ref, 'professional_refs': professional_refs,
            'cost_refs': cost_refs, 'supply_refs': supply_refs,
            'integration_authority_ref': integration_authority_ref, 'open_issue_refs': open_issue_refs},
            prepared_type=PreparedArchitectIntegration, validate_sources=validate_architect_integration_sources)


def validate_architect_consistency_preparation_sources(action_input, *, preparation, context, organization_id, sources):
    """Reserve only original profile outputs while retaining normal source checks."""
    option = sources.get(action_input.option_ref.key())
    profile = sources.get(option.integration_profile_ref.key()) if isinstance(option, ArchitectIntegrationOptionView) else None
    method = sources.get(preparation.method_ref.key())
    if (not isinstance(profile, ArchitectIntegrationProfileView) or profile.choice != 'integrate'
            or preparation.calculation_ref not in profile.consistency_result_refs
            or any(ref.key() in sources for ref in profile.consistency_result_refs)
            or not isinstance(method, ArchitectIntegrationMethodView) or method.option_ref != option.ref):
        raise TaskConflict('Consistency preparation must retain its original integrate profile, target and specific method declaration')
    return validate_architect_integration_sources(action_input, context=context,
        organization_id=organization_id, sources=sources)


def validate_architect_integration_sources(action_input, *, context, organization_id, sources):
    """Check original option/author identities while leaving business branches intact."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Architect integration lacks its exact original concrete source')
        return row

    def same_option(row):
        if row.option_ref.key() != option.ref.key():
            raise TaskConflict('Architect integration source changes its original option version')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Architect integration changes its original invocation scope')
    option = read(action_input.option_ref, ArchitectIntegrationOptionView)
    for field, prefix in (('professional_refs', 'ENGINEER'), ('cost_refs', 'QS'), ('supply_refs', 'SUPPLIER')):
        refs = getattr(action_input, field)
        unique_refs(refs)
        for ref in refs:
            source = same_option(read(ref, ArchitectIntegrationSourceView))
            if source.author_action_id.split('-')[0] != prefix:
                raise TaskConflict('Architect integration source changes its original professional author role')
            unique_refs(source.unresolved_issue_refs)
    unique_refs(action_input.open_issue_refs)
    for ref in action_input.open_issue_refs:
        issue = same_option(read(ref, ArchitectIntegrationIssueView))
        unique_refs(issue.author_reference_refs)
        unique_refs(issue.interface_refs)
    if action_input.integration_authority_ref is not None:
        delegation = same_option(read(action_input.integration_authority_ref, ArchitectIntegrationAuthorityView))
        if (delegation.grantee_organization_id != organization_id
                or delegation.grantee_actor_id != context.actor_id
                or delegation.grantee_function_ref.key() != context.function_ref.key()):
            raise TaskConflict('Architect integration delegation changes its original grantee or function')
        unique_refs(delegation.permitted_input_refs)
        unique_refs(delegation.permitted_interface_refs)
    if option.integration_profile_ref.key() not in sources:
        return
    profile = same_option(read(option.integration_profile_ref, ArchitectIntegrationProfileView))
    if profile.organization_id != organization_id:
        raise TaskConflict('Architect integration profile changes its original organization')
    for field in ('professional_refs', 'cost_refs', 'supply_refs', 'interface_refs', 'open_issue_refs',
            'consistency_result_refs', 'question_refs'):
        unique_refs(getattr(profile, field))
    for ref in profile.interface_refs:
        if ref.key() in sources:
            interface = same_option(read(ref, ArchitectIntegrationInterfaceView))
            unique_refs(interface.input_refs)
            unique_refs(interface.unresolved_issue_refs)
    for ref in profile.question_refs:
        if ref.key() in sources:
            question = same_option(read(ref, ArchitectIntegrationQuestionView))
            if question.question.scope != action_input.scope:
                raise TaskConflict('Architect integration question changes its original scope')
    for ref in profile.consistency_result_refs:
        if ref.key() in sources:
            result = same_option(read(ref, ArchitectIntegrationConsistencyView))
            unique_refs([item.input_ref for item in result.input_digests])
            unique_refs(result.interface_refs)
            unique_refs(result.retained_issue_refs)
            if result.method_ref.key() in sources:
                same_option(read(result.method_ref, ArchitectIntegrationMethodView))
