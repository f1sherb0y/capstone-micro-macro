"""Connect Supplier A13 to original advisory authority and disclosure sources."""
from dataclasses import dataclass

from integration.supplier_quote_actions import PreparedSupplierQuote, SupplierQuoteActionAssembler
from src.actions.contracts.common import ActionContext, Reference, walk_references
from src.actions.contracts.domain import CandidateSet
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.references import ActionReadView
from src.actions.contracts.supplier_advice_objects import (
    ContractorAdviceAuthorityView, ContractorAdviceBriefView, ContractorAdviceOptionView,
    SupplierAdviceCapabilityView, SupplierAdviceDisclosureView, SupplierAdviceMethodView,
    SupplierAdviceProfessionalView, SupplierAdviceRequestView, supplier_advice_schemas,
)
from src.actions.runner import ActionRunner
from src.coordination.tasks import task_digest


@dataclass(frozen=True)
class PreparedSupplierAdvice(PreparedSupplierQuote):
    """Original consultation invocation; no formal quotation or professional approval."""


class SupplierAdviceActionAssembler(SupplierQuoteActionAssembler):
    """Reuse explicit host setup with the original A13 advisory projections.

    The host selects received brief/options, professional advice, bounded work
    authority, capability, disclosure policy and feasibility methods. The
    processor checks authorship, finite effort/fee authority, disclosure rights,
    assumptions and actual supply estimates. Decline and study proposals retain
    their original paths without requiring an advisory work grant. This entry
    creates no authorization, actual productivity, formal offer or design/use
    approval; private evidence is not added to the returned decision by assembly.
    """
    SOURCE_SCHEMAS = staticmethod(supplier_advice_schemas)

    def build(self, context, *, brief_ref, option_refs, professional_advice_refs,
            advisory_request_ref, advisory_scope_ref, capability_ref,
            disclosure_profile_ref, feasibility_method_refs):
        context = ActionContext.model_validate(context).model_copy(deep=True)
        if context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'SUPPLIER-A13':
            raise ValueError('Supplier advice assembly requires its original A13 context')
        if self.source_mode == 'fixture' and context.execution_mode != 'offline_fixture':
            raise ValueError('Fixture advice sources require explicit offline_fixture execution')
        registration = self.registry.get('SUPPLIER-A13')
        if not registration.implemented or registration.skill is None or registration.role != 'Supplier':
            raise ValueError('Supplier advice assembly requires its original Skill and processor')
        resolver = self._views.build_resolver(context, registration.action_id, registration.role)
        runner = ActionRunner(self.registry, organizations=self.organizations, references=resolver,
            methods=self.methods, audit_sink=self.audit_sink, policy_version=self.policy_version,
            model_version=self.model_version, decision_strategies=self.decision_strategies)
        reading = ActionReadView(context, resolver, self.organizations, registration.action_id, registration.role,
            methods=runner.methods, method_refs=registration.skill.manifest.method_refs)
        selected = {name: [Reference.model_validate(ref) for ref in refs] for name, refs in (
            ('option_refs', option_refs), ('professional_advice_refs', professional_advice_refs),
            ('feasibility_method_refs', feasibility_method_refs))}
        for refs in selected.values():
            unique_refs(refs)
        action_input = registration.contract.validate_input({**selected,
            'brief_ref': Reference.model_validate(brief_ref),
            'advisory_request_ref': Reference.model_validate(advisory_request_ref),
            'advisory_scope_ref': None if advisory_scope_ref is None else Reference.model_validate(advisory_scope_ref),
            'capability_ref': Reference.model_validate(capability_ref),
            'disclosure_profile_ref': Reference.model_validate(disclosure_profile_ref)})

        def read(ref, schema):
            row = reading.resolve(ref)
            if not isinstance(row, schema) or row.ref != ref:
                raise ValueError('Supplier advice requires its exact original concrete source version')
            return row

        try:
            request = read(action_input.advisory_request_ref, SupplierAdviceRequestView)
            profile = read(action_input.disclosure_profile_ref, SupplierAdviceDisclosureView)
            if (request.recipient_organization_id != reading.organization_id
                    or profile.organization_id != reading.organization_id or profile.request_ref != request.ref
                    or profile.authority_ref not in context.authorization_refs):
                raise ValueError('Supplier advice changes original recipient, request or disclosure authority')
            brief = read(action_input.brief_ref, ContractorAdviceBriefView)
            for ref in action_input.option_refs:
                read(ref, ContractorAdviceOptionView)
            for ref in action_input.professional_advice_refs:
                read(ref, SupplierAdviceProfessionalView)
            for ref in action_input.feasibility_method_refs:
                read(ref, SupplierAdviceMethodView)
            read(action_input.capability_ref, SupplierAdviceCapabilityView)
            if action_input.advisory_scope_ref is not None:
                read(action_input.advisory_scope_ref, ContractorAdviceAuthorityView)
            # The original processor handles decline before brief/option linkage
            # and requires bounded work only for advice, not study proposals.
            if profile.choice != 'decline' and request.brief_ref != brief.ref:
                raise ValueError('Supplier advice request names another original brief')
            for ref in walk_references(action_input):
                reading.resolve(ref)
            candidates = reading.resolve(context.candidate_set_ref)
            if not isinstance(candidates, CandidateSet):
                raise ValueError('Supplier advice requires its actual current authorized candidate set')
            candidates.check_context(context, registration.contract.choices)
            for candidate in candidates.candidates:
                reading.resolve(candidate.ref)
            reading.recheck()
            return PreparedSupplierAdvice(context, action_input, runner, reading,
                task_digest(action_input.model_dump(mode='json')), task_digest(context.model_dump(mode='json')),
                task_digest(reading.evidence()))
        finally:
            reading.recheck()
