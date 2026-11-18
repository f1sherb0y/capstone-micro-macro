"""Assemble original QS A05 procurement sources and publication grants."""
from dataclasses import dataclass
from typing import ClassVar

from integration.qs_market_actions import QSMarketActionAssembler, PreparedQSMarket
from src.actions.contracts.qs_procurement_objects import (
    QSProcurementScopeView, QSProcurementTaskView, QSProcurementRoundView,
    QSProcurementTemplateView, QSProcurementDesignView, QSMeasurementRuleView,
    QSPricingRuleView, QSProcurementQuantityView, QSProcurementGapView,
    QSProcurementResponseView, QSProcurementExclusionView, QSProcurementPackageView,
    QSProcurementRevisionView, QSProcurementDocumentView, QSPublicationBasisView,
    QSProcurementPublicationAuthorityView, qs_procurement_schemas,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class PreparedQSProcurement(PreparedQSMarket):
    ACTION_ID: ClassVar[str] = 'QS-A05'


class QSProcurementActionAssembler(QSMarketActionAssembler):
    """Freeze supplied originals under the application's current read guard.

    Quantity coverage, provisional quantities, pricing compatibility, revision
    completeness and publication permissions remain original processor checks.
    Assembly creates no quantities, published documents or tender approvals.
    """
    ACTION_ID = 'QS-A05'
    SOURCE_SCHEMAS = staticmethod(qs_procurement_schemas)

    def build(self, context, *, scope, procurement_scope_ref, design_refs,
            measurement_rule_ref, quantity_schedule_ref, prior_document_ref,
            publication_authority_ref):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'procurement_scope_ref': procurement_scope_ref,
            'design_refs': design_refs, 'measurement_rule_ref': measurement_rule_ref,
            'quantity_schedule_ref': quantity_schedule_ref,
            'prior_document_ref': prior_document_ref,
            'publication_authority_ref': publication_authority_ref},
            prepared_type=PreparedQSProcurement,
            validate_sources=validate_qs_procurement_sources)


def validate_qs_procurement_sources(action_input, *, context, organization_id, sources):
    """Check original source identities without granting publication authority."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('QS procurement lacks its exact original concrete source')
        if row.scope != action_input.scope:
            raise TaskConflict('QS procurement source changes its original requested scope')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('QS procurement changes its original invocation scope')
    unique_refs(action_input.design_refs)
    procurement = read(action_input.procurement_scope_ref, QSProcurementScopeView)
    task = read(procurement.task_ref, QSProcurementTaskView)
    round_ = read(procurement.round_ref, QSProcurementRoundView)
    template = read(procurement.template_ref, QSProcurementTemplateView)
    if (task.organization_id != organization_id or task.function_ref.key() != context.function_ref.key()
            or task.procurement_scope_ref.key() != procurement.ref.key()
            or task.round_ref.key() != round_.ref.key()
            or round_.procurement_scope_ref.key() != procurement.ref.key()
            or round_.template_ref.key() != template.ref.key()
            or round_.buyer_id != procurement.buyer_id
            or round_.buyer_organization_id != procurement.buyer_organization_id):
        raise TaskConflict('QS procurement task changes its original organization, scope, round or buyer')
    for ref in action_input.design_refs:
        read(ref, QSProcurementDesignView)
    read(action_input.measurement_rule_ref, QSMeasurementRuleView)
    if action_input.quantity_schedule_ref is not None:
        read(action_input.quantity_schedule_ref, QSProcurementQuantityView)
    if action_input.prior_document_ref is not None:
        read(action_input.prior_document_ref, QSProcurementDocumentView)
    # Missing optional dependencies remain processor-owned gap/deferred branches.
    if procurement.pricing_rule_ref.key() in sources:
        read(procurement.pricing_rule_ref, QSPricingRuleView)
    for ref in procurement.exclusions:
        if ref.key() in sources:
            read(ref, QSProcurementExclusionView)
    question_refs = list(procurement.question_refs)
    if action_input.quantity_schedule_ref is not None:
        quantity = read(action_input.quantity_schedule_ref, QSProcurementQuantityView)
        question_refs.extend(line.provisional_question_ref for line in quantity.lines
            if line.provisional_question_ref is not None)
    for ref in set(question_refs):
        if ref.key() not in sources:
            continue
        question = read(ref, QSProcurementGapView)
        if (question.procurement_scope_ref.key() != procurement.ref.key()
                or question.round_ref.key() != round_.ref.key()):
            raise TaskConflict('QS procurement question changes its original scope or round')
        if question.response_requirement_ref.key() in sources:
            response = read(question.response_requirement_ref, QSProcurementResponseView)
            if (response.procurement_scope_ref.key() != procurement.ref.key()
                    or response.round_ref.key() != round_.ref.key()):
                raise TaskConflict('QS procurement response changes its original scope or round')
    if procurement.revision_impact_ref is not None and procurement.revision_impact_ref.key() in sources:
        impact = read(procurement.revision_impact_ref, QSProcurementRevisionView)
        if (impact.procurement_scope_ref.key() != procurement.ref.key()
                or impact.round_ref.key() != round_.ref.key()):
            raise TaskConflict('QS procurement revision changes its original scope or round')
        for change in impact.changes:
            if change.package_ref.key() in sources:
                package = read(change.package_ref, QSProcurementPackageView)
                if package.procurement_scope_ref.id != procurement.ref.id:
                    raise TaskConflict('QS procurement revision borrows another procurement package')
    if procurement.saved_document_ref is not None and procurement.saved_document_ref.key() in sources:
        read(procurement.saved_document_ref, QSProcurementDocumentView)
    if action_input.publication_authority_ref is not None:
        grant = read(action_input.publication_authority_ref, QSProcurementPublicationAuthorityView)
        if (grant.procurement_scope_ref.key() != procurement.ref.key()
                or grant.round_ref.key() != round_.ref.key()
                or grant.delegate_actor_id != context.actor_id
                or grant.delegate_organization_id != organization_id
                or grant.delegate_function_ref.key() != context.function_ref.key()
                or grant.buyer_actor_id != procurement.buyer_id
                or grant.buyer_organization_id != procurement.buyer_organization_id):
            raise TaskConflict('QS publication grant changes its original buyer or delegate')
        if grant.publication_basis_ref.key() in sources:
            basis = read(grant.publication_basis_ref, QSPublicationBasisView)
            if (basis.procurement_scope_ref.key() != procurement.ref.key()
                    or basis.round_ref.key() != round_.ref.key()
                    or basis.document_ref.key() != grant.document_ref.key()):
                raise TaskConflict('QS publication basis changes its original scope, round or document')
    # Design/quantity/pricing mismatch questions, document revision contents,
    # original author authority and permission/digest checks stay in the processor.
