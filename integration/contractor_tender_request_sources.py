"""Execute the configured A01/A02 source-production sequence on a native request.

This is the request_work_factory for the existing tender application. It binds
original assemblers, workers, native reads and publications; it owns no formal
business state and has no model or native-rule fallback. Source snapshots and
professional indicator documents remain explicit independently supplied input.
"""
from contextlib import nullcontext
from typing import Annotated, Literal

from pydantic import Field, model_validator

from integration.contractor_bid_pipeline import ContractorBidPipelinePlan, ContractorBidSourcePlan
from integration.contractor_bid_results import ContractorTenderReadSelection
from integration.contractor_tender_request_trigger import ContractorTenderRequestWork
from integration.contractor_tender_indicators import TenderIndicatorDocumentSettings, publish_indicators
from integration.contractor_tender_snapshot_sources import ContractorTenderSnapshotReader
from integration.contractor_tender_clarification_response import TenderClarificationResponsePlan, respond_to_clarification
from integration.contractor_tender_handoff_sources import TenderHandoffProduction, publish_handoff
from integration.macro_views import AuthorizedMacroViewAssembler
from src.actions.contracts.common import ActionContext, StrictRecord, TextId, ref_type
from src.actions.contracts.references import ActionReadView
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.models import Digest


class TenderScreeningInputs(StrictRecord):
    package_ref: ref_type('ProcurementPackage')
    capability_ref: ref_type('ContractorCapability')
    commitments_ref: ref_type('CommitmentSnapshot')
    screening_profile_ref: ref_type('OpportunityScreeningProfile')
    qualification_refs: list[ref_type('Qualification')]
    invitation_refs: list[ref_type('Invitation')]


class TenderScreeningPublication(StrictRecord):
    source_context: ActionContext
    terms_ref: ref_type('GbaTenderPackageTerms')
    facts_ref: ref_type('GbaScreeningEnterpriseFacts')


class TenderClarificationContinuation(StrictRecord):
    screening_context: ActionContext
    screening_inputs: TenderScreeningInputs
    screening_mapping_ref: ref_type('GbaCapacityMapping')
    screening_publication: TenderScreeningPublication
    response_evidence_ref: ref_type('Evidence')


class TenderDeclineInputs(StrictRecord):
    context: ActionContext
    pricing_profile_ref: ref_type('ContractorPricingProfile')
    capacity_ref: ref_type('ContractorCapacity')
    cost_refs: list[ref_type('CostBasis')]
    allowed_method_refs: list[ref_type('WorkMethod')] | None = None
    source_plan: ContractorBidSourcePlan | None = None

    @model_validator(mode='after')
    def sourced_decline_matches_invocation(self):
        plan = self.source_plan
        if plan is not None and (plan.bid_context != self.context
                or any(getattr(plan, name) != getattr(self, name) for name in
                    ('pricing_profile_ref', 'capacity_ref', 'allowed_method_refs'))):
            raise ValueError('Decline source production must preserve its exact invocation and selected references')
        if plan is not None and self.cost_refs:
            raise ValueError('Sourced decline takes cost references from actual production, not preset targets')
        return self


class TenderScreeningFeedbackPolicy(StrictRecord):
    base_profile_ref: ref_type('OpportunityScreeningProfile')
    evidence_ref: ref_type('Evidence')
    decline_after_prior_submissions: int | None = Field(ge=1, strict=True)
    project_only: bool = True
    query_prior_submissions: bool = False
    decline_after_prior_evaluations: int | None = Field(default=None,ge=1,strict=True)
    decline_after_prior_declines: int | None = Field(default=None,ge=1,strict=True)
    decline_after_prior_final_accounts: int | None = Field(default=None, ge=1, strict=True)
    decline_after_prior_payment_delays: int | None = Field(default=None, ge=1, strict=True)

    @model_validator(mode='after')
    def explicit_feedback_limit(self):
        if all(getattr(self, name) is None for name in ('decline_after_prior_submissions',
                'decline_after_prior_evaluations', 'decline_after_prior_declines',
                'decline_after_prior_final_accounts', 'decline_after_prior_payment_delays')):
            raise ValueError('Tender feedback policy needs at least one explicit positive outcome limit')
        return self


class TenderRequestSourcePlan(StrictRecord):
    request_sha256: Digest | None = None
    request_binding: Literal['exact_digest', 'current_native_request'] = 'exact_digest'
    organization_id: TextId
    project_id: TextId
    tick: Annotated[int, Field(ge=0)]
    screening_context: ActionContext
    screening_inputs: TenderScreeningInputs
    screening_mapping_ref: ref_type('GbaCapacityMapping')
    screening_publication: TenderScreeningPublication | None = None
    bid_plan: ContractorBidPipelinePlan | None = None
    decline: TenderDeclineInputs | None = None
    mapping_source_context: ActionContext
    exposure_context: ActionContext
    mapping_ref: ref_type('GbaTenderProposalMapping')
    indicator_document: TenderIndicatorDocumentSettings | None = None
    feedback_policy: TenderScreeningFeedbackPolicy | None = None
    handoff_production: TenderHandoffProduction | None = None
    clarification_response: TenderClarificationResponsePlan | None = None
    clarification_continuation: TenderClarificationContinuation | None = None

    @model_validator(mode='after')
    def consistent_contexts(self):
        if (self.request_sha256 is None) != (self.request_binding == 'current_native_request'):
            raise ValueError('Tender plan must select either an exact request digest or explicit current-request binding')
        if self.bid_plan is None and self.decline is None:
            raise ValueError('Tender request needs an explicit sourced bid or decline path')
        first = self.screening_context
        if self.clarification_continuation is not None and self.clarification_response is None:
            raise ValueError('Clarification continuation needs its independent original QS response plan')
        if self.clarification_continuation is not None:
            next_inputs=self.clarification_continuation.screening_inputs
            original=self.screening_inputs
            if (next_inputs.package_ref.id!=original.package_ref.id
                    or next_inputs.package_ref.version==original.package_ref.version
                    or any(getattr(next_inputs,k)!=getattr(original,k) for k in
                        ('capability_ref','commitments_ref','screening_profile_ref','qualification_refs'))):
                raise ValueError('Quantity clarification successor must preserve the enterprise inputs and version the same package')
        if self.clarification_response is not None:
            response = self.clarification_response.context
            if (response.contract_ref.id != 'QS-A05' or response.scope != first.scope
                    or response.run_id != first.run_id or response.business_time != first.business_time
                    or response.execution_mode != 'rule'
                    or response.read_token in {c.read_token for c, _ in self.source_contexts()}):
                raise ValueError('QS clarification response needs its own same-project/time original rule context')
        contexts = self.source_contexts()
        if len({context.read_token for context, _ in contexts}) != len(contexts):
            raise ValueError('Every tender source stage requires its own immutable read token')
        for context, action_id in contexts:
            if (context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != action_id
                    or context.execution_mode == 'offline_fixture'
                    or context.scope.kind != 'project' or context.scope.ref.id != self.project_id
                    or any(getattr(context, name) != getattr(first, name) for name in
                        ('run_id', 'actor_id', 'function_ref', 'scope', 'business_time', 'execution_mode'))):
                raise ValueError('Tender source stages must share original enterprise, project, business time and mode')
        return self

    def source_contexts(self):
        first = self.screening_context
        contexts = [(first, 'CONTRACTOR-A01'),
            (self.mapping_source_context, 'CONTRACTOR-A02'), (self.exposure_context, 'CONTRACTOR-A02')]
        if self.clarification_continuation is not None:
            contexts.extend((c, 'CONTRACTOR-A01') for c in (
                self.clarification_continuation.screening_context,
                self.clarification_continuation.screening_publication.source_context))
        if self.screening_publication is not None:
            contexts.append((self.screening_publication.source_context, 'CONTRACTOR-A01'))
        if self.bid_plan is not None:
            contexts.extend((getattr(self.bid_plan, name), 'CONTRACTOR-A02') for name in
                ('capacity_context', 'quantity_context', 'cost_context', 'bid_context', 'programme_context')
                if getattr(self.bid_plan, name) is not None)
        if self.decline is not None:
            if self.decline.source_plan is None:
                contexts.append((self.decline.context, 'CONTRACTOR-A02'))
            else:
                contexts.extend((getattr(self.decline.source_plan, name), 'CONTRACTOR-A02') for name in
                    ('capacity_context', 'quantity_context', 'cost_context', 'bid_context', 'programme_context')
                    if getattr(self.decline.source_plan, name) is not None)
        if self.handoff_production is not None:
            if self.bid_plan is None:
                raise ValueError('Runtime participation handoff requires an explicit submit-bid pipeline')
            contexts.append((self.handoff_production.source_context, 'CONTRACTOR-A02'))
        return contexts


class TenderRequestSourcesSettings(StrictRecord):
    version: TextId
    requests: Annotated[list[TenderRequestSourcePlan], Field(min_length=1)]

    @model_validator(mode='after')
    def exact_requests(self):
        keys = [plan.request_sha256 for plan in self.requests if plan.request_sha256 is not None]
        if len(keys) != len(set(keys)):
            raise ValueError('Tender source configuration repeats a native request')
        selectors = [(plan.organization_id, plan.project_id, plan.tick) for plan in self.requests
            if plan.request_binding == 'current_native_request']
        if len(selectors) != len(set(selectors)) or any(
                (plan.organization_id, plan.project_id, plan.tick) in selectors
                for plan in self.requests if plan.request_binding == 'exact_digest'):
            raise ValueError('Current-request tender plans must have distinct nonoverlapping enterprise/project/tick selectors')
        return self


def _prepare_screening(application, request, plan):
    """Publish current native invitation/resources when explicitly requested."""
    assembler, pipeline = application.screening_assembler, application.host.pipeline
    if plan.screening_publication is not None:
        from integration.bindings.gba_v1_contractor_screening import gba_contractor_screening_source_schemas
        from integration.bindings.gba_v1_tender_package import GbaTenderPackageTermsView

        production = plan.screening_publication
        schemas = gba_contractor_screening_source_schemas()
        schemas.register_kind('GbaTenderPackageTerms', GbaTenderPackageTermsView, str)
        views = AuthorizedMacroViewAssembler(application.organizations, pipeline.assembler.provider,
            schemas, macro_version=pipeline.assembler.macro_version, source_mode=pipeline.assembler.source_mode)
        context = production.source_context
        reading = ActionReadView(context, views.build_resolver(context, 'CONTRACTOR-A01', 'Contractor'),
            application.organizations, 'CONTRACTOR-A01', 'Contractor')
        produced = application.assembly.publish_screening_snapshot(context=context, reading=reading,
            project_id=plan.project_id, read_guard=nullcontext, terms_ref=production.terms_ref,
            facts_ref=production.facts_ref, publications=pipeline.publications,
            next_context=plan.screening_context)
        if produced['kind'] != 'prepared':
            raise TaskConflict('Original tender package/resource production is pending: ' + str(produced))
    prepared = assembler.build_gba(plan.screening_context, assembly=application.assembly,
        read_guard=nullcontext, mapping_ref=plan.screening_mapping_ref,
        **plan.screening_inputs.model_dump(mode='python'))
    if prepared['kind'] != 'prepared':
        raise TaskConflict('Original source-backed screening is pending: ' + prepared['kind'])
    return prepared['invocation']


def select_saved_bid(*, application, request, plan, identity, invocation):
    """Publish a mapping of a saved result, without calling action processors."""
    sourced_contexts = [source.bid_context for source in
        (plan.bid_plan, plan.decline.source_plan if plan.decline is not None else None) if source is not None]
    if invocation.context in sourced_contexts:
        pipeline = application.host.pipeline
        reading = pipeline.assembler.build_capacity_reading(invocation.context)
        pipeline.publications.retain_bid_sources(source_context=invocation.context,
            reading=reading, next_context=plan.mapping_source_context)
    if plan.indicator_document is not None:
        publish_indicators(application=application, request=request, identity=identity,
            contexts=[plan.mapping_source_context, plan.exposure_context],
            mapping_ref=plan.mapping_ref, settings=plan.indicator_document)
    application.host.publish_tender_mapping(request=request, identity=identity,
        source_context=plan.mapping_source_context, next_context=plan.exposure_context, mapping_ref=plan.mapping_ref)
    return ContractorTenderReadSelection(identity=identity, current_context=plan.exposure_context.model_copy(deep=True),
        mapping_ref=plan.mapping_ref.model_copy(deep=True))


def build_request_work(*, application, request, settings):
    """Concrete request producer; run the existing business workers, not stubs.

    The original trigger has already durably claimed this request. Failed or
    pending preparation is retained there and never becomes a native decline.
    All publication and execution happens under the same engine writer guard.
    """
    config = TenderRequestSourcesSettings.model_validate(settings).model_copy(deep=True)
    with application.read_guard():
        application._check()
        if application.host is None or application.selector is None:
            raise TaskConflict('Tender request source production requires the original installed host and selector')
        request = application.selector._request(request)
        matching = [plan for plan in config.requests
            if plan.request_sha256 == task_digest(request.model_dump(mode='json'))
            or plan.request_binding == 'current_native_request'
                and (plan.organization_id, plan.project_id, plan.tick) == (
                    request.agent.agent_id, request.inputs['project']['project_id'], request.metadata.get('tick'))]
        if len(matching) != 1:
            raise TaskConflict('No explicit same-source production plan for the current native request')
        plan = matching[0]
        if (plan.organization_id != request.agent.agent_id
                or plan.project_id != request.inputs['project']['project_id']
                or type(request.metadata.get('tick')) is not int or plan.tick != request.metadata['tick']
                or plan.tick != application.assembly.engine.current_tick):
            raise TaskConflict('Tender source plan changes the actual requesting enterprise, project or tick')
        for context in (plan.screening_context, plan.mapping_source_context, plan.exposure_context):
            grants = application.organizations.grants(context, context.contract_ref.id, 'Contractor')
            if not grants or grants[0].organization_id != plan.organization_id:
                raise TaskConflict('Tender source plan does not belong to the actual authorized recipient')
        application._execution_components('CONTRACTOR-A01')
        reader = application.host.pipeline.assembler.provider.provider
        if isinstance(reader, ContractorTenderSnapshotReader) and reader.settings.bind_native_on_request:
            reader.bind_request_sources(request=request, contexts=[context for context, _ in plan.source_contexts()])
        quantities = application.host.pipeline.source_provider
        quantity_contexts = [source.quantity_context for source in
            (plan.bid_plan, plan.decline.source_plan if plan.decline is not None else None) if source is not None]
        if (quantity_contexts and isinstance(quantities, ContractorTenderSnapshotReader)
                and quantities.settings.bind_native_on_request):
            quantities.bind_request_sources(request=request, contexts=quantity_contexts)
        feedback_source = None
        if plan.feedback_policy is not None:
            if plan.feedback_policy.query_prior_submissions:
                from integration.bindings.gba_v1_tender_query import query_prior_tender_submissions
                query_prior_tender_submissions(application, request, project_only=plan.feedback_policy.project_only)
            reader = application.host.pipeline.assembler.provider.provider
            if (not isinstance(reader, ContractorTenderSnapshotReader) or reader.assembly is not application.assembly
                    or reader.organizations is not application.organizations or reader.read_guard is not application.read_guard):
                raise TaskConflict('Feedback-derived screening requires the original configured source reader')
            feedback_source = reader.publish_screening_feedback(context=plan.screening_context, request=request,
                profile_ref=plan.screening_inputs.screening_profile_ref,
                base_profile_ref=plan.feedback_policy.base_profile_ref,
                evidence_ref=plan.feedback_policy.evidence_ref,
                decline_after_prior_submissions=plan.feedback_policy.decline_after_prior_submissions,
                decline_after_prior_evaluations=plan.feedback_policy.decline_after_prior_evaluations,
                decline_after_prior_declines=plan.feedback_policy.decline_after_prior_declines,
                decline_after_prior_final_accounts=plan.feedback_policy.decline_after_prior_final_accounts,
                decline_after_prior_payment_delays=plan.feedback_policy.decline_after_prior_payment_delays,
                project_only=plan.feedback_policy.project_only)
        screening = _prepare_screening(application, request, plan)

        def build_bid(*, request, screening, outcome, identity):
            # Branch only on the original saved A01 result. There is no model
            # call here, inferred commercial refusal, or native rule fallback.
            if outcome['result']['payload']['choice'] == 'participate' and plan.bid_plan is not None:
                if plan.handoff_production is not None:
                    publish_handoff(application=application, request=request, screening=screening,
                        identity=identity, plan=plan.bid_plan, settings=plan.handoff_production)
                return plan.bid_plan.model_copy(deep=True)
            if plan.decline is None:
                raise TaskConflict('Screening lacks an independently sourced A02 commercial decision path')
            refs = plan.decline
            if refs.source_plan is not None:
                prepared = application.host.pipeline.prepare_decline(refs.source_plan,
                    screening=screening, screening_result=outcome['result'])
                if isinstance(prepared, dict):
                    raise TaskConflict('Original decline source production is pending: ' + prepared['kind'])
                return prepared
            prepared = application.host.pipeline.assembler.build(refs.context,
                pricing_profile_ref=refs.pricing_profile_ref, capacity_ref=refs.capacity_ref,
                cost_refs=refs.cost_refs, allowed_method_refs=refs.allowed_method_refs)
            profile = prepared.reading.resolve(refs.pricing_profile_ref)
            if profile.choice != 'decline_bid':
                raise TaskConflict('Nonparticipation must not submit a bid through the decline path')
            return prepared

        def select_result(*, request, identity, outcome, invocation):
            return select_saved_bid(application=application, request=request, plan=plan, identity=identity, invocation=invocation)

        def respond(*, request, register_response):
            return respond_to_clarification(application, request, register_response=register_response)

        def continue_clarification(*, request, screening, identity, response):
            from integration.contractor_tender_clarification_continuation import publish_response_consumption
            production = publish_response_consumption(application=application, request=request,
                plan=plan, screening=screening, identity=identity, response=response)
            next_plan = plan.model_copy(update={name:getattr(plan.clarification_continuation,name) for name in
                ('screening_context','screening_inputs','screening_mapping_ref','screening_publication')})
            if plan.feedback_policy is not None:
                policy=plan.feedback_policy
                reader.publish_screening_feedback(context=next_plan.screening_context,request=request,
                    profile_ref=next_plan.screening_inputs.screening_profile_ref,base_profile_ref=policy.base_profile_ref,
                    evidence_ref=policy.evidence_ref,decline_after_prior_submissions=policy.decline_after_prior_submissions,
                    decline_after_prior_evaluations=policy.decline_after_prior_evaluations,
                    decline_after_prior_declines=policy.decline_after_prior_declines,
                    decline_after_prior_final_accounts=policy.decline_after_prior_final_accounts,
                    decline_after_prior_payment_delays=policy.decline_after_prior_payment_delays,
                    project_only=policy.project_only)
            return _prepare_screening(application, request, next_plan), production

        return ContractorTenderRequestWork(screening=screening,
            screening_worker=application.screening_worker, build_bid=build_bid, select_result=select_result,
            feedback_source=feedback_source,
            respond_clarification=respond if plan.clarification_response is not None else None,
            continue_clarification=continue_clarification if plan.clarification_continuation is not None else None)
