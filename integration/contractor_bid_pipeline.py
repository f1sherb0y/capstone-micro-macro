"""Explicit host orchestration of existing A02 source publication and result components."""
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Annotated

from pydantic import Field, model_validator

from integration.contractor_bid_actions import ContractorBidActionAssembler, PreparedContractorBid
from integration.contractor_bid_results import ContractorBidResultWorker
from integration.bindings.gba_v1_tender_publication import GbaTenderPublicationStore, GbaTenderPublishedViewProvider
from src.actions.contracts.common import ActionContext, StrictRecord, ref_type
from src.actions.contracts.contractor_bid_objects import ContractorBidProfileView
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict


class ContractorBidSourcePlan(StrictRecord):
    """Host-supplied exact references and authorized snapshots of one business time."""
    capacity_context: ActionContext
    quantity_context: ActionContext
    cost_context: ActionContext
    bid_context: ActionContext
    capacity_facts_ref: ref_type('GbaBidEnterpriseFacts')
    quantity_mapping_refs: Annotated[list[ref_type('ContractorQuantityMapping')], Field(min_length=1)]
    cost_adoption_refs: Annotated[list[ref_type('ContractorCostAdoption')], Field(min_length=1)]
    pricing_profile_ref: ref_type('ContractorPricingProfile')
    capacity_ref: ref_type('ContractorCapacity')
    allowed_method_refs: list[ref_type('WorkMethod')] | None = None
    programme_context: ActionContext | None = None
    programme_basis_ref: ref_type('ContractorProgrammeBasis') | None = None

    @model_validator(mode='after')
    def explicit_programme_stage(self):
        if (self.programme_context is None) != (self.programme_basis_ref is None):
            raise ValueError('Programme production requires both an explicit source context and basis')
        return self


class ContractorBidPipelinePlan(ContractorBidSourcePlan):
    handoff_basis_ref: ref_type('ContractorProcurementHandoffBasis')


@dataclass(frozen=True)
class PreparedContractorBidPipeline:
    invocation: PreparedContractorBid
    publication_sha256s: tuple[str, ...]
    handoff_basis_sha256: str
    screening_result_sha256: str


class GbaContractorBidPipeline:
    """Compose one explicitly selected submit-bid chain without automatic retries.

    This source-production path requires actual independent host professional
    inputs. Existing direct A02 assembly remains available for already supplied
    sources and decline decisions. Preparation writes technical publications
    only; execute uses the original worker, audit and invocation snapshot store.
    No model adapter, indicator mapping or native business effect is synthesized.
    """
    VERSION = 'gba-v1-contractor-bid-pipeline.v4'

    def __init__(self, *, assembly, assembler, worker, publications, source_provider,
            read_guard, validate_quantity, validate_cost, validate_handoff, validate_programme=None):
        from integration.bindings.gba_v1 import GbaV1Assembly

        if (not isinstance(assembly, GbaV1Assembly) or not isinstance(assembler, ContractorBidActionAssembler)
                or not isinstance(worker, ContractorBidResultWorker)
                or not isinstance(publications, GbaTenderPublicationStore)
                or worker.store is not assembly.client.tasks or publications.store is not worker.store
                or worker.registry is not assembler.registry or publications.organizations is not assembler.organizations
                or not isinstance(assembler.provider, GbaTenderPublishedViewProvider)
                or assembler.provider.publications is not publications
                or not callable(getattr(source_provider, 'project', None))
                or any(not callable(callback) for callback in
                       (read_guard, validate_quantity, validate_cost, validate_handoff))):
            raise ValueError('Bid pipeline requires shared original components, published provider and explicit host callbacks')
        self.assembly, self.assembler, self.worker = assembly, assembler, worker
        self.publications, self.source_provider = publications, source_provider
        self.read_guard = read_guard
        self.validate_quantity, self.validate_cost, self.validate_handoff = (
            validate_quantity, validate_cost, validate_handoff)
        if validate_programme is not None and not callable(validate_programme):
            raise ValueError('Programme stage requires an explicit host validation callback')
        self.validate_programme = validate_programme

    def prepare(self, plan, *, screening, screening_result, screening_audit):
        """Publish ordered source snapshots and validate the original A01→A02 relation."""
        return self._prepare(plan, screening=screening, screening_result=screening_result,
            screening_audit=screening_audit, decline=False)

    def prepare_decline(self, plan, *, screening, screening_result):
        """Source an explicit commercial refusal without fabricating a participation handoff.

        The original package retains its deliverables and quantities. Those
        inputs use the same authorized source producers as a submitted bid.
        A01 participation is an intent: an independently supplied A02 refusal
        may still follow it. An unresolved A01 or clarification cannot do so.
        A missing source or failed computation never becomes a refusal.
        """
        return self._prepare(plan, screening=screening, screening_result=screening_result,
            screening_audit=None, decline=True)

    def _prepare(self, plan, *, screening, screening_result, screening_audit, decline):
        from integration.contractor_screening_actions import PreparedContractorScreening
        from integration.contractor_screening_results import SavedContractorScreening

        schema = ContractorBidSourcePlan if decline else ContractorBidPipelinePlan
        plan = schema.model_validate(plan).model_copy(deep=True)
        contexts = (plan.capacity_context, plan.quantity_context, plan.cost_context,
                    *(() if plan.programme_context is None else (plan.programme_context,)), plan.bid_context)
        original = contexts[0]
        if (original.run_id != self.worker.store.run_id or len({context.read_token for context in contexts}) != len(contexts)
                or any(context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'CONTRACTOR-A02'
                       or any(getattr(context, name) != getattr(original, name) for name in
                              ('run_id', 'actor_id', 'function_ref', 'contract_ref', 'scope', 'business_time', 'execution_mode'))
                       for context in contexts)):
            raise TaskConflict('Bid pipeline requires distinct original same-time A02 read points')
        if plan.programme_context is not None and self.validate_programme is None:
            raise TaskConflict('Requested programme production lacks its explicit host validator')
        if (not isinstance(screening, (PreparedContractorScreening, SavedContractorScreening))
                or any(getattr(screening.context, name) != getattr(original, name) for name in
                    ('run_id', 'actor_id', 'function_ref', 'scope', 'business_time', 'execution_mode'))):
            raise TaskConflict('Bid pipeline requires the actual original same-run A01 procurement invocation')
        source_registry = screening.registry if isinstance(screening, SavedContractorScreening) else screening.runner.registry
        source_result = source_registry.get('CONTRACTOR-A01').contract.result_adapter.validate_python(screening_result)
        if (source_result.kind != 'completed' or source_result.payload.choice not in (
                {'participate', 'decline'} if decline else {'participate'})):
            missing = 'completed_original_resolved_screening_decision' if decline else 'completed_original_participation_decision'
            return {'kind': 'needs_information', 'missing_fields': [missing],
                    'requested_refs': [screening.action_input.package_ref]}
        for refs in (plan.quantity_mapping_refs, plan.cost_adoption_refs, plan.allowed_method_refs or []):
            unique_refs(refs)
        # No implicit host writer acquisition inside providers/validators: the
        # single actual guard remains held throughout this same-time chain.
        with self.read_guard():
            reading = self.assembler.build_capacity_reading(original)
            profile = reading.resolve(plan.pricing_profile_ref)
            expected_choice = 'decline_bid' if decline else 'submit_bid'
            if not isinstance(profile, ContractorBidProfileView) or profile.choice != expected_choice:
                raise TaskConflict('Selected source-production pipeline requires an explicit ' + expected_choice + ' profile')
            capacity = self.assembly.publish_bid_capacity(context=original, reading=reading,
                read_guard=nullcontext, facts_ref=plan.capacity_facts_ref,
                publications=self.publications, next_context=plan.quantity_context)
            if capacity['kind'] != 'prepared':
                return capacity
            if capacity['capacity_projection'].ref != plan.capacity_ref:
                raise TaskConflict('Pipeline capacity differs from the explicitly selected original target')
            reading = self.assembler.build_capacity_reading(plan.quantity_context)
            source_reading = self.assembler.build_quantity_source_reading(plan.quantity_context,
                source_provider=self.source_provider)
            quantities = self.assembly.publish_bid_quantities(context=plan.quantity_context, reading=reading,
                source_reading=source_reading, read_guard=nullcontext, mapping_refs=plan.quantity_mapping_refs,
                validate_current=self.validate_quantity, publications=self.publications, next_context=plan.cost_context)
            if quantities['kind'] != 'prepared':
                return quantities
            reading = self.assembler.build_capacity_reading(plan.cost_context)
            costs = self.assembly.publish_bid_costs(context=plan.cost_context, reading=reading,
                read_guard=nullcontext, adoption_refs=plan.cost_adoption_refs,
                validate_current=self.validate_cost, publications=self.publications,
                next_context=plan.programme_context or plan.bid_context)
            if costs['kind'] != 'prepared':
                return costs
            stages = [capacity, quantities, costs]
            if plan.programme_context is not None:
                from integration.contractor_bid_programme import ContractorBidProgrammeBasisView

                reading = self.assembler.build_capacity_reading(plan.programme_context)
                basis = reading.resolve(plan.programme_basis_ref)
                if (not isinstance(basis, ContractorBidProgrammeBasisView) or basis.programme_ref != profile.programme_ref
                        or basis.package_ref != profile.package_ref or basis.capacity_ref != plan.capacity_ref
                        or set(basis.exclusion_refs) != set(profile.exclusion_refs)):
                    raise TaskConflict('Pipeline programme changes original profile, capacity or excluded bid scope')
                programme = self.assembly.publish_bid_programme(context=plan.programme_context, reading=reading,
                    read_guard=nullcontext, basis_ref=plan.programme_basis_ref, validate_current=self.validate_programme,
                    publications=self.publications, next_context=plan.bid_context)
                if programme['kind'] != 'prepared':
                    return programme
                stages.append(programme)
            bid_refs = dict(pricing_profile_ref=plan.pricing_profile_ref, capacity_ref=plan.capacity_ref,
                cost_refs=[result['cost_projection'].ref for result in costs['costs']],
                allowed_method_refs=plan.allowed_method_refs)
            if decline:
                invocation = self.assembler.build(plan.bid_context, **bid_refs)
                self._check_quantities(invocation, quantities)
                invocation.reading.recheck()
                return invocation
            handoff = self.assembler.build_from_screening(plan.bid_context, screening=screening,
                screening_result=screening_result, screening_audit=screening_audit,
                handoff_basis_ref=plan.handoff_basis_ref, validate_current=self.validate_handoff,
                **bid_refs)
            if handoff['kind'] != 'prepared':
                return handoff
            invocation = handoff['invocation']
            self._check_quantities(invocation, quantities)
            invocation.reading.recheck()
            return PreparedContractorBidPipeline(invocation=invocation,
                publication_sha256s=tuple(result['publication']['record_sha256']
                    for result in stages),
                handoff_basis_sha256=handoff['basis_sha256'],
                screening_result_sha256=handoff['screening_result_sha256'])

    @staticmethod
    def _check_quantities(invocation, quantities):
        if {ref.key() for ref in invocation.action_input.quantity_refs} != {
                result['quantity_projection'].ref.key() for result in quantities['quantities']}:
            raise TaskConflict('Pipeline quantity set differs from the original complete procurement selection')

    def execute(self, prepared, *, request_id, purpose='action'):
        """Explicit execution uses saved original snapshots; no republishing or auto-retry."""
        if not isinstance(prepared, PreparedContractorBidPipeline):
            raise TaskConflict('Bid pipeline execution requires its actual prepared source chain')
        with self.read_guard():
            identity = self.worker.register(prepared.invocation, request_id=request_id, purpose=purpose)
            outcome = self.worker.execute(identity, prepared.invocation)
        return {**outcome, 'identity': identity,
            'publication_sha256s': prepared.publication_sha256s,
            'handoff_basis_sha256': prepared.handoff_basis_sha256,
            'screening_result_sha256': prepared.screening_result_sha256}
