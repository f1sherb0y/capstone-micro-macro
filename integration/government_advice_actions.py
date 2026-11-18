"""Freeze original Government A01 consultation, jurisdiction and procedural sources."""
from dataclasses import dataclass
from typing import ClassVar

from integration.action_model_host import resolve_action_model_host
from integration.macro_views import AuthorizedMacroViewAssembler
from src.actions.contracts.government_advice_objects import (
    GovConsultationRequestView, GovAdviceAuthorityView, GovAdviceBriefView,
    GovAdviceOptionView, GovAdviceProcedureView, GovAdviceRuleView,
    GovAdviceRequirementView, GovAdviceTargetView, GovAdviceTriggerView,
    GovAdviceRecipientView, government_advice_schemas,
)
from src.actions.contracts.government_objects import GovMatterView, GovJurisdictionView, GovResponseRequirementView
from src.actions.contracts.common import ActionContext, EvidenceRecord, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView, ReferenceResolver
from src.actions.runner import ActionRunner
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.registry import scope_covers


@dataclass(frozen=True)
class PreparedGovernmentAdvice:
    ACTION_ID: ClassVar[str] = 'GOV-A01'
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
            raise TaskConflict('Prepared consultation changed its original input, context or authorized sources')
        self.reading.check_method_context(self.context, self.ACTION_ID)
        self.reading.recheck()
        return self.runner.run_action(self.context, self.action_input, execution_path=execution_path)


class GovernmentAdviceActionAssembler:
    """Freeze original consultation sources under the application's read guard.

    Original jurisdiction, procedure applicability, lawful recipient disclosure
    and independent consultation authority remain processor decisions. Assembly
    creates no approvals, permits, technical conformity or investment decisions.
    """
    ACTION_ID = 'GOV-A01'
    SOURCE_SCHEMAS = staticmethod(government_advice_schemas)

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

    def build(self, context, *, scope, consultation_ref, brief_ref, option_refs,
            matter_ref, jurisdiction_ref, procedure_ref, evidence_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'consultation_ref': consultation_ref, 'brief_ref': brief_ref,
            'option_refs': option_refs, 'matter_ref': matter_ref, 'jurisdiction_ref': jurisdiction_ref,
            'procedure_ref': procedure_ref, 'evidence_refs': evidence_refs},
            prepared_type=PreparedGovernmentAdvice, validate_sources=validate_government_advice_sources)

    def _prepare_supplied_snapshot(self, context, *, input_values, prepared_type, validate_sources):
        """Freeze Government sources while leaving action-specific checks explicit."""
        context = self._context(context)
        registration = self.registry.get(self.ACTION_ID)
        if registration.role != 'Government' or not registration.implemented or registration.skill is None:
            raise ValueError('Consultation assembly requires its actual processor and bound Government Skill')
        action_input = registration.contract.validate_input(input_values)
        projection = self._views.assemble(context, self.ACTION_ID, 'Government')
        resolver = ReferenceResolver(context.run_id, source_mode=self.source_mode,
            schemas=self.SOURCE_SCHEMAS())
        for row in projection.objects:
            resolver.register_projection(row.ref, row.value)
        resolver.freeze_read(context.read_token, [row.ref for row in projection.objects])
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        reading = ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'Government',
            methods=runner.methods, method_refs=registration.skill.manifest.method_refs)
        try:
            # Preserve all supplied sources, including output dependencies,
            # without deciding jurisdiction, guidance applicability or permission.
            for row in projection.objects:
                reading.resolve(row.ref)
            for ref in walk_references(action_input):
                reading.resolve(ref)
            validate_sources(action_input, context=context,
                organization_id=reading.organization_id, sources=reading._reads)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Consultation assembly requires its original authorized candidate set')
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
            raise ValueError('Government assembly requires its original action contract and explicit source mode')
        return context

    def build_result_reading(self, context):
        """Create a fresh authorized boundary for explicit own-result reads."""
        context = self._context(context)
        resolver = self._views.build_resolver(context, self.ACTION_ID, 'Government')
        return ActionReadView(context, resolver, self.organizations, self.ACTION_ID, 'Government')


def validate_government_advice_sources(action_input, *, context, organization_id, sources):
    """Check original consultation versions without determining jurisdiction."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('Government advice lacks its exact original concrete source')
        if hasattr(row, 'scope') and not scope_covers(row.scope, action_input.scope):
            raise TaskConflict('Government advice source does not cover its original requested scope')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('Government advice changes its original invocation scope')
    unique_refs(action_input.option_refs)
    unique_refs(action_input.evidence_refs)
    request = read(action_input.consultation_ref, GovConsultationRequestView)
    if (request.recipient_organization_id != organization_id
            or any(getattr(request, field) != getattr(action_input, field)
                for field in ('scope', 'brief_ref', 'matter_ref', 'jurisdiction_ref', 'procedure_ref'))
            or set(request.option_refs) != set(action_input.option_refs)
            or set(request.supplied_evidence_refs) != set(action_input.evidence_refs)):
        raise TaskConflict('Government consultation substitutes its original recipient, scope or input versions')
    read(action_input.matter_ref, GovMatterView)
    jurisdiction = read(action_input.jurisdiction_ref, GovJurisdictionView)
    if jurisdiction.organization_id != organization_id:
        raise TaskConflict('Government consultation substitutes another organization jurisdiction')
    if request.consultation_authority_ref.key() in sources:
        grant = read(request.consultation_authority_ref, GovAdviceAuthorityView)
        if (grant.consultation_ref != request.ref or grant.applicant_id != request.applicant_id
                or grant.recipient_organization_id != organization_id or grant.delegate_actor_id != context.actor_id
                or grant.delegate_function_ref != context.function_ref):
            raise TaskConflict('Government consultation authority substitutes its original applicant or delegate')
    if action_input.brief_ref is not None:
        brief = read(action_input.brief_ref, GovAdviceBriefView)
        if (brief.applicant_id != request.applicant_id or set(brief.option_refs) != set(request.option_refs)
                or organization_id not in brief.recipient_organization_ids):
            raise TaskConflict('Government consultation brief substitutes its original applicant, options or recipient')
    for ref in action_input.option_refs:
        option = read(ref, GovAdviceOptionView)
        if (option.brief_ref != request.brief_ref or option.applicant_id != request.applicant_id
                or organization_id not in option.recipient_organization_ids):
            raise TaskConflict('Government consultation option substitutes its original brief, applicant or recipient')
    for ref in action_input.evidence_refs:
        read(ref, EvidenceRecord)
    if action_input.procedure_ref is not None:
        procedure = read(action_input.procedure_ref, GovAdviceProcedureView)
        if procedure.matter_ref != request.matter_ref or procedure.jurisdiction_ref != request.jurisdiction_ref:
            raise TaskConflict('Government consultation procedure substitutes its original matter or jurisdiction')

    def same_versions(row):
        if (row.consultation_ref != request.ref or row.brief_ref != request.brief_ref
                or set(row.option_refs) != set(request.option_refs)):
            raise TaskConflict('Government guidance source substitutes original consultation, brief or options')

    rules = list(request.guidance_rule_refs) + [question.requirement_ref for question in request.questions]
    if jurisdiction.referral is not None:
        rules.append(jurisdiction.referral.basis_ref)
    for ref in set(rules):
        if ref.key() not in sources:
            continue
        rule = read(ref, GovAdviceRuleView)
        same_versions(rule)
        if (rule.organization_id != organization_id or rule.matter_ref != request.matter_ref
                or rule.jurisdiction_ref != request.jurisdiction_ref or rule.procedure_ref != request.procedure_ref):
            raise TaskConflict('Government guidance rule substitutes its original organization or procedure')
        if rule.recipient_ref is not None and rule.recipient_ref.key() in sources:
            read(rule.recipient_ref, GovAdviceRecipientView)
    for ref in request.information_requirement_refs:
        if ref.key() in sources:
            requirement = read(ref, GovAdviceRequirementView)
            if requirement.consultation_ref != request.ref or requirement.procedure_ref != request.procedure_ref:
                raise TaskConflict('Government information requirement substitutes its original consultation or procedure')
    for question in request.questions:
        for ref in question.target_refs:
            if ref.key() in sources:
                same_versions(read(ref, GovAdviceTargetView))
        for ref in question.recipient_refs:
            if ref.key() in sources:
                read(ref, GovAdviceRecipientView)
        if question.response_requirement_ref.key() in sources:
            response = read(question.response_requirement_ref, GovResponseRequirementView)
            if response.rule_ref != question.requirement_ref:
                raise TaskConflict('Government response requirement substitutes its original question rule')
    for ref in request.update_trigger_refs:
        if ref.key() in sources:
            same_versions(read(ref, GovAdviceTriggerView))
    # Current authority, unknown jurisdiction/applicability, lawful recipients,
    # procedure/rule coverage and advice/clarification/referral remain processor checks.
