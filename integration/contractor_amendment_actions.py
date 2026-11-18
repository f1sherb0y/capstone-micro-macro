"""Freeze original Contractor A03 inputs; procurement effects belong to the host."""
from dataclasses import dataclass
from typing import ClassVar

from integration.action_model_host import resolve_action_model_host
from integration.macro_views import AuthorizedMacroViewAssembler
from src.actions.contracts.common import ActionContext, walk_references
from src.actions.contracts.contractor_amendment_objects import (
    ContractorAmendmentBidView, ContractorAmendmentProfileView,
    ContractorAmendmentQuestionView, ContractorAmendmentReservationView,
    ContractorAmendmentRoundView, ContractorAmendmentRuleView,
    ContractorAmendmentSubmissionView, contractor_amendment_schemas,
)
from src.actions.contracts.contractor_bid_objects import ContractorBidPackageView
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.runner import ActionRunner
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedContractorAmendment:
    ACTION_ID: ClassVar[str] = 'CONTRACTOR-A03'
    context: ActionContext
    action_input: object
    runner: ActionRunner
    reading: ActionReadView
    input_sha256: str
    context_sha256: str
    reading_sha256: str

    def execute(self, *, execution_path=None):
        """Evaluate the original invocation without sending or releasing anything."""
        if (task_digest(self.action_input.model_dump(mode='json')) != self.input_sha256
                or task_digest(self.context.model_dump(mode='json')) != self.context_sha256
                or task_digest(self.reading.evidence()) != self.reading_sha256
                or self.runner.references is not self.reading._resolver
                or self.runner.organizations is not self.reading._organizations):
            raise TaskConflict('Prepared amendment changed its original input, context or authorized sources')
        self.reading.check_method_context(self.context, self.ACTION_ID)
        self.reading.recheck()
        return self.runner.run_action(self.context, self.action_input, execution_path=execution_path)


class ContractorAmendmentActionAssembler:
    """Use explicitly supplied versions, questions and reservations.

    The application holds its current source/authorization guard while building
    and executing. Submission status, time windows, reservation completeness,
    revision pricing and all four choices remain original processor checks.
    An accepted prior bid is never inferred from a local A02 decision.
    """
    ACTION_ID = 'CONTRACTOR-A03'
    SOURCE_SCHEMAS = staticmethod(contractor_amendment_schemas)

    def __init__(self, *, registry, organizations, provider, macro_version,
            source_mode, methods=None, audit_sink=None, policy_version=None,
            model_version=None, decision_strategies=(), model_host=None):
        model_version, bindings = resolve_action_model_host(registry=registry,
            run_id=organizations.run_id, model_version=model_version,
            decision_strategies=decision_strategies, model_host=model_host)
        self.registry, self.organizations, self.provider = registry, organizations, provider
        self.macro_version, self.source_mode = macro_version, source_mode
        self.methods, self.audit_sink = methods, audit_sink
        self.policy_version, self.model_version = policy_version, model_version
        self.decision_strategies = bindings
        self._views = AuthorizedMacroViewAssembler(organizations, provider,
            self.SOURCE_SCHEMAS(), macro_version=macro_version, source_mode=source_mode)

    def build(self, context, *, bid_ref, clarification_refs, package_ref,
            round_ref, amendment_rule_ref, reservation_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'bid_ref': bid_ref, 'clarification_refs': clarification_refs,
            'package_ref': package_ref, 'round_ref': round_ref,
            'amendment_rule_ref': amendment_rule_ref, 'reservation_refs': reservation_refs},
            prepared_type=PreparedContractorAmendment, validate_sources=validate_contractor_amendment_sources)

    def _prepare_supplied_snapshot(self, context, *, input_values, prepared_type, validate_sources):
        """Freeze Contractor sources while leaving action-specific checks explicit."""
        context = self._context(context)
        registration = self.registry.get(self.ACTION_ID)
        if registration.role != 'Contractor' or not registration.implemented or registration.skill is None:
            raise ValueError('Amendment assembly requires its actual processor and bound Contractor Skill')
        action_input = registration.contract.validate_input(input_values)
        projection = self._views.assemble(context, self.ACTION_ID, 'Contractor')
        resolver = ReferenceResolver(context.run_id, source_mode=self.source_mode,
            schemas=self.SOURCE_SCHEMAS())
        for row in projection.objects:
            resolver.register_projection(row.ref, row.value)
        resolver.freeze_read(context.read_token, [row.ref for row in projection.objects])
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'Contractor',
            methods=runner.methods, method_refs=registration.skill.manifest.method_refs)
        try:
            # Include supplied profiles and output dependencies without computing
            # replacement quantities, prices, programme or business eligibility.
            for row in projection.objects:
                reading.resolve(row.ref)
            for ref in walk_references(action_input):
                reading.resolve(ref)
            validate_sources(action_input, context=context,
                organization_id=reading.organization_id, sources=reading._reads)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Amendment assembly requires its original authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            return prepared_type(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')),
                task_digest(context.model_dump(mode='json')), task_digest(reading.evidence()))
        finally:
            reading.recheck()

    def _context(self, context):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if (context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != self.ACTION_ID
                or (self.source_mode == 'fixture') != (context.execution_mode == 'offline_fixture')):
            raise ValueError('Contractor assembly requires its original action contract and explicit source mode')
        return context

    def build_result_reading(self, context):
        """Create a fresh authorized boundary for explicit own-result reads."""
        context = self._context(context)
        resolver = self._views.build_resolver(context, self.ACTION_ID, 'Contractor')
        return ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'Contractor')


def validate_contractor_amendment_sources(action_input, *, context, organization_id, sources):
    """Check original relationships, retaining statuses for the business processor."""
    unique_refs(action_input.clarification_refs)
    unique_refs(action_input.reservation_refs)
    def read(ref, schema):
        value = sources.get(ref.key())
        if not isinstance(value, schema) or value.ref.key() != ref.key():
            raise TaskConflict('Amendment input lacks its exact original concrete source')
        return value

    bid = read(action_input.bid_ref, ContractorAmendmentBidView)
    package = read(action_input.package_ref, ContractorBidPackageView)
    tender_round = read(action_input.round_ref, ContractorAmendmentRoundView)
    rule = read(action_input.amendment_rule_ref, ContractorAmendmentRuleView)
    if (bid.organization_id != organization_id or rule.organization_id != organization_id
            or not scope_covers(bid.draft.scope_ref, context.scope)
            or organization_id not in package.recipient_organization_ids
            or tender_round.organization_id not in {None, organization_id}
            or package.round_ref.key() != tender_round.ref.key()
            or tender_round.package_ref.key() != package.ref.key()
            or tender_round.current_package_ref.key() != package.ref.key()
            or tender_round.amendment_rule_ref.key() != rule.ref.key()
            or rule.prior_package_ref.key() != bid.draft.package_ref.key()
            or rule.prior_round_ref.key() != bid.round_ref.key()
            or rule.current_package_ref.key() != package.ref.key()
            or rule.current_round_ref.key() != tender_round.ref.key()):
        raise TaskConflict('Amendment substitutes another contractor, original bid or package/round replacement')
    for ref in action_input.clarification_refs:
        question = read(ref, ContractorAmendmentQuestionView)
        if (question.organization_id != organization_id or question.bid_ref.key() != bid.ref.key()
                or question.package_ref.key() != package.ref.key()
                or question.round_ref.key() != tender_round.ref.key()):
            raise TaskConflict('Amendment question changes its original bid, package, round or recipient')
    for ref in action_input.reservation_refs:
        reservation = read(ref, ContractorAmendmentReservationView)
        if (reservation.organization_id != organization_id or reservation.bid_ref.key() != bid.ref.key()
                or reservation.round_ref.key() != bid.round_ref.key()):
            raise TaskConflict('Amendment reservation changes its original contractor, bid or round')
    # Missing dependencies and complete reservation coverage remain processor
    # exits. Supplied dependencies must retain their original identities.
    execution = sources.get(bid.submission_ref.key())
    if execution is not None and (not isinstance(execution, ContractorAmendmentSubmissionView)
            or execution.organization_id != organization_id or execution.bid_ref.key() != bid.ref.key()
            or execution.package_ref.key() != bid.draft.package_ref.key()
            or execution.round_ref.key() != bid.round_ref.key()):
        raise TaskConflict('Amendment changes the original submission command identity')
    profile = sources.get(rule.profile_ref.key())
    if profile is not None:
        if (not isinstance(profile, ContractorAmendmentProfileView)
                or profile.organization_id != organization_id or profile.bid_ref.key() != bid.ref.key()):
            raise TaskConflict('Amendment changes the original contractor revision profile')
        if profile.revision_input is not None and profile.revision_input.package_ref.key() != package.ref.key():
            raise TaskConflict('Amendment replacement pricing uses another package version')
