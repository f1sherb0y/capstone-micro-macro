"""Assemble original QS A06 same-round bids and independently sourced checks."""
from dataclasses import dataclass
from typing import ClassVar

from integration.qs_market_actions import QSMarketActionAssembler, PreparedQSMarket
from src.actions.contracts.qs_bid_objects import (
    QSBidRoundView, QSBidView, QSBidEligibilityView, QSBidClarificationView,
    QSBidNormalizationBasisView, QSBidEvaluationProfileView, QSBidEvaluationRuleView,
    QSBidMethodResultView, QSBidExclusionAuthorityView, QSBidGapView, qs_bid_schemas,
)
from src.actions.contracts.qs_procurement_objects import (
    QSProcurementDocumentView, QSProcurementResponseView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict


@dataclass(frozen=True)
class PreparedQSBid(PreparedQSMarket):
    ACTION_ID: ClassVar[str] = 'QS-A06'


class QSBidActionAssembler(QSMarketActionAssembler):
    """Freeze actual bid inputs under the application's current read guard.

    The original processor checks complete bid/clarification sets, qualifications,
    original prices, normalization arithmetic, ranking and exclusion permission.
    Assembly creates no prices, successful checks, exclusion or contract award.
    """
    ACTION_ID = 'QS-A06'
    SOURCE_SCHEMAS = staticmethod(qs_bid_schemas)

    def build(self, context, *, scope, round_ref, procurement_document_ref,
            bid_refs, clarification_refs, evaluation_profile_ref, method_result_refs):
        return self._prepare_supplied_snapshot(context, input_values={
            'scope': scope, 'round_ref': round_ref,
            'procurement_document_ref': procurement_document_ref,
            'bid_refs': bid_refs, 'clarification_refs': clarification_refs,
            'evaluation_profile_ref': evaluation_profile_ref,
            'method_result_refs': method_result_refs}, prepared_type=PreparedQSBid,
            validate_sources=validate_qs_bid_sources)

    def prepare_normalization(self, context, *, calculation_ref, author_authority_ref,
            validate_current, **source_refs):
        """Prepare original inputs and produce comparison prices without evaluation."""
        from integration.qs_bid_calculations import prepare_qs_bid_normalization

        prepared = self.build(context, **source_refs)
        return prepare_qs_bid_normalization(context=prepared.context, action_input=prepared.action_input,
            reading=prepared.reading, calculation_ref=calculation_ref, author_authority_ref=author_authority_ref,
            validate_current=validate_current)

    def prepare_ranking(self, context, *, calculation_ref, author_authority_ref,
            validate_current, **source_refs):
        """Produce one ranking from current original sources and saved normalization."""
        from integration.qs_bid_calculations import prepare_qs_bid_ranking

        prepared = self.build(context, **source_refs)
        return prepare_qs_bid_ranking(context=prepared.context, action_input=prepared.action_input,
            reading=prepared.reading, calculation_ref=calculation_ref, author_authority_ref=author_authority_ref,
            validate_current=validate_current)

    def save_normalization(self, context, *, publications, read_guard,
            calculation_ref, author_authority_ref, validate_current, **source_refs):
        """Calculate once and return the durable record before explicit publication."""
        from integration.qs_bid_calculation_publication import QSBidNormalizationPublicationStore
        from integration.qs_bid_calculations import prepare_qs_bid_normalization

        if (not isinstance(publications, QSBidNormalizationPublicationStore)
                or publications.registry is not self.registry or publications.organizations is not self.organizations
                or publications.methods is not self.methods or not callable(read_guard)):
            raise TaskConflict('Bid normalization save requires original registries and actual source writer guard')
        with read_guard(context):
            prepared = self.build(context, **source_refs)
            calculation = prepare_qs_bid_normalization(context=prepared.context, action_input=prepared.action_input,
                reading=prepared.reading, calculation_ref=calculation_ref,
                author_authority_ref=author_authority_ref, validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation, context=prepared.context,
                action_input=prepared.action_input, reading=prepared.reading)
            return {'kind':'prepared', 'calculation':calculation, 'record':record}


    def save_ranking(self, context, *, publications, read_guard,
            calculation_ref, author_authority_ref, validate_current, **source_refs):
        """Return the durable original ranking record before explicit publication."""
        from integration.qs_bid_ranking_publication import QSBidRankingPublicationStore
        from integration.qs_bid_calculations import prepare_qs_bid_ranking

        if (not isinstance(publications, QSBidRankingPublicationStore)
                or publications.registry is not self.registry or publications.organizations is not self.organizations
                or publications.methods is not self.methods or not callable(read_guard)):
            raise TaskConflict('Ranking save requires original registries and actual source writer guard')
        with read_guard(context):
            prepared = self.build(context, **source_refs)
            calculation = prepare_qs_bid_ranking(context=prepared.context, action_input=prepared.action_input,
                reading=prepared.reading, calculation_ref=calculation_ref,
                author_authority_ref=author_authority_ref, validate_current=validate_current)
            if calculation['kind'] != 'prepared':
                return calculation
            record = publications.save(calculation, context=prepared.context,
                action_input=prepared.action_input, reading=prepared.reading)
            return {'kind':'prepared', 'calculation':calculation, 'record':record}


def validate_qs_bid_sources(action_input, *, context, organization_id, sources):
    """Check concrete original associations without deciding bid acceptability."""
    def read(ref, schema):
        row = sources.get(ref.key())
        if not isinstance(row, schema) or row.ref.key() != ref.key():
            raise TaskConflict('QS bid lacks its exact original concrete source')
        if row.scope != action_input.scope:
            raise TaskConflict('QS bid source changes its original requested scope')
        return row

    if action_input.scope != context.scope:
        raise TaskConflict('QS bid changes its original invocation scope')
    for refs in (action_input.bid_refs, action_input.clarification_refs, action_input.method_result_refs):
        unique_refs(refs)
    round_ = read(action_input.round_ref, QSBidRoundView)
    document = read(action_input.procurement_document_ref, QSProcurementDocumentView)
    profile = read(action_input.evaluation_profile_ref, QSBidEvaluationProfileView)
    if (round_.document_ref.key() != document.ref.key() or document.round_ref.key() != round_.ref.key()
            or document.draft.procurement_scope_ref.key() != round_.procurement_scope_ref.key()
            or profile.round_ref.key() != round_.ref.key() or profile.document_ref.key() != document.ref.key()
            or profile.organization_id != organization_id or profile.function_ref.key() != context.function_ref.key()):
        raise TaskConflict('QS bid profile changes its original organization, function, round or document')

    def same_round(ref, schema):
        row = read(ref, schema)
        if row.round_ref.key() != round_.ref.key() or row.document_ref.key() != document.ref.key():
            raise TaskConflict('QS bid source borrows another round or document version')
        return row

    def supplied_bid_check(ref, schema, bid_ref):
        if ref is not None and ref.key() in sources:
            row = same_round(ref, schema)
            if row.bid_ref.key() != bid_ref.key():
                raise TaskConflict('QS bid check substitutes another original bid')

    bids = {}
    for ref in action_input.bid_refs:
        bid = same_round(ref, QSBidView)
        bids[ref.key()] = bid
        supplied_bid_check(bid.eligibility_ref, QSBidEligibilityView, ref)
        supplied_bid_check(bid.normalization_basis_ref, QSBidNormalizationBasisView, ref)
    question_refs = list(profile.question_refs)
    for ref in action_input.clarification_refs:
        clarification = same_round(ref, QSBidClarificationView)
        bid = bids.get(clarification.bid_ref.key())
        if bid is None or clarification.response_author_id != bid.bidder_id:
            raise TaskConflict('QS clarification substitutes another original bid or bidder')
        supplied_bid_check(clarification.assessment_ref, QSBidEligibilityView, bid.ref)
        supplied_bid_check(clarification.normalization_basis_ref, QSBidNormalizationBasisView, bid.ref)
        question_refs.append(clarification.question_ref)
    for ref in profile.rule_refs:
        if ref.key() in sources:
            same_round(ref, QSBidEvaluationRuleView)
    for ref in action_input.method_result_refs:
        saved = same_round(ref, QSBidMethodResultView)
        if saved.profile_ref.key() != profile.ref.key():
            raise TaskConflict('QS saved bid calculation changes its original evaluation profile')
    for ref in set(question_refs):
        if ref.key() not in sources:
            continue
        question = same_round(ref, QSBidGapView)
        if question.procurement_scope_ref.key() != round_.procurement_scope_ref.key():
            raise TaskConflict('QS bid question changes its original procurement scope')
        if question.response_requirement_ref.key() in sources:
            response = read(question.response_requirement_ref, QSProcurementResponseView)
            if (response.round_ref.key() != round_.ref.key()
                    or response.procurement_scope_ref.key() != round_.procurement_scope_ref.key()):
                raise TaskConflict('QS bid response changes its original scope or round')
    if profile.exclusion_authority_ref is not None and profile.exclusion_authority_ref.key() in sources:
        grant = same_round(profile.exclusion_authority_ref, QSBidExclusionAuthorityView)
        if (profile.exclusion_bid_ref is None or grant.bid_ref.key() != profile.exclusion_bid_ref.key()
                or profile.exclusion_rule_ref is None or grant.rule_ref.key() != profile.exclusion_rule_ref.key()
                or grant.delegate_actor_id != context.actor_id
                or grant.delegate_organization_id != organization_id
                or grant.delegate_function_ref.key() != context.function_ref.key()):
            raise TaskConflict('QS exclusion grant changes its original delegate, bid or rule')
    # Completeness, published status, source author authority, qualification and
    # permission, method domains and saved arithmetic remain processor decisions.
