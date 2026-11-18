"""Rejudge the original cancelled procurement round without inventing a bid."""
from copy import deepcopy
from dataclasses import dataclass

from pydantic import TypeAdapter

from src.actions.contracts.common import ActionContext, EvidenceRecord, ScopeRef, ref_type
from src.actions.contracts.qs_bid_objects import (
    QSBidRoundView, QSBidView, QSBidClarificationView, QSBidEvaluationProfileView,
    QSBidEvaluationRuleView, QSBidMethodResultView,
)
from src.actions.contracts.qs_procurement_objects import QSProcurementDocumentView
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


_CODE = 'qs.bid.active_evaluation_round'
_FIELDS = frozenset({'scope', 'round_ref', 'procurement_document_ref', 'bid_refs',
    'clarification_refs', 'evaluation_profile_ref', 'method_result_refs'})
_BASES = (('round_ref', 'ProcurementRound', QSBidRoundView),
    ('procurement_document_ref', 'ProcurementDocument', QSProcurementDocumentView),
    ('evaluation_profile_ref', 'EvaluationProfile', QSBidEvaluationProfileView))


@dataclass(frozen=True)
class QSBidConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict


def qs_original_bid_round_profile(read_current, validate_relation):
    """Ready permits fresh same-round advice, with no exclusion or award effect."""
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('QS bid recovery requires actual sources and native round/history validation')

    def indexed(refs):
        rows = {ref.key()[:2]: ref for ref in refs}
        if len(rows) != len(refs):
            raise TaskConflict('QS bid recovery repeats a physical source')
        return rows

    def evaluate(check):
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'QS-A06' or source['role'] != 'QS' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 1 or old_refs[0].kind != 'ProcurementRound'):
            raise TaskConflict('QS bid recovery substitutes original round wait or recipient')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, QSBidConditionReading) or not isinstance(selected.context, ActionContext)
                or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.original_action_input, dict)
                or not isinstance(selected.action_input, dict)):
            raise TaskConflict('QS bid recovery requires typed current reading and original snapshot input')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        try:
            old_input, action_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
            if (set(old_input) != _FIELDS or set(action_input) != _FIELDS or task_digest(old_input) != source['input_sha256']
                    or context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'QS-A06'
                    or context.execution_mode == 'offline_fixture' or reading._resolver.source_mode != 'formal'
                    or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                    or old_input['scope'] != action_input['scope']):
                raise TaskConflict('QS bid recovery changes original snapshot, scope or current invocation')
            scope, now = TypeAdapter(ScopeRef).validate_python(action_input['scope']), context.business_time
            if context.scope != scope:
                raise TaskConflict('QS bid recovery changes original evaluation coverage')
            reading.check_method_context(context, 'QS-A06')
            proof_rows, proof_refs = [], []

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref or row.scope != scope:
                    raise TaskConflict('QS bid recovery lacks an exact scoped original/current source')
                proof_rows.append(row)
                return row

            versions = []
            for raw in (old_input, action_input):
                rows = {field: read(ref_type(kind).model_validate(raw[field]), schema) for field, kind, schema in _BASES}
                round_, document, profile = (rows[field] for field, _, _ in _BASES)
                if (round_.document_ref != document.ref or document.round_ref != round_.ref or document.status != 'published'
                        or profile.round_ref != round_.ref or profile.document_ref != document.ref
                        or document.draft.procurement_scope_ref != round_.procurement_scope_ref
                        or profile.organization_id != source['organization_id']):
                    raise TaskConflict('QS bid recovery substitutes original round, published document or QS profile')
                versions.append(rows)
            old, current = versions
            original, round_ = old['round_ref'], current['round_ref']
            old_profile, profile = old['evaluation_profile_ref'], current['evaluation_profile_ref']
            if (original.ref != old_refs[0] or original.status != 'cancelled'
                    or any(old[field].ref.key()[:2] != current[field].ref.key()[:2] for field, _, _ in _BASES)
                    or any(getattr(original, field) != getattr(round_, field) for field in (
                        'buyer_id', 'buyer_organization_id', 'procurement_scope_ref', 'template_ref'))
                    or profile.function_ref != context.function_ref or profile.authority_ref not in context.authorization_refs
                    or any(getattr(old_profile, field) != getattr(profile, field) for field in (
                        'organization_id', 'function_ref', 'currency', 'region_id', 'price_time', 'required_scope_keys', 'on_unknown', 'criteria'))
                    or old['procurement_document_ref'].draft != current['procurement_document_ref'].draft):
                raise TaskConflict('QS bid recovery changes original buyer, procurement terms or evaluation basis')
            if round_.status == 'cancelled':
                return 'waiting'
            if any(row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                    or not row.effective_window.contains(now) for row in current.values()):
                return 'unavailable'

            def authorize(ref, actor, function_ref, action, at, roles, organization=None):
                grant, function = reading.resolve(ref), reading.resolve(function_ref)
                if (not isinstance(grant, Authorization) or not isinstance(function, RoleAssignment)
                        or function.function_ref != function_ref or function.role not in roles
                        or grant.actor_id != actor or grant.function_ref != function_ref or action not in grant.action_ids
                        or at.clock_ref != now.clock_ref or at.offset > now.offset or not grant.validity.contains(at)
                        or organization is not None and grant.organization_id != organization
                        or not any(scope_covers(s, scope) for s in grant.scopes)):
                    raise TaskConflict('QS bid recovery lacks original bidder/author or current QS evaluation authority')
                actions = {'QS': {'QS-A05', 'QS-A06'}, 'Contractor': {'CONTRACTOR-A02', 'CONTRACTOR-A03'}, 'Supplier': {'SUPPLIER-A03'}}
                if action not in actions.get(function.role, set()):
                    raise TaskConflict('QS bid recovery changes original source function/action')
                proof_refs.extend([*grant.basis_refs, *function.basis_refs])

            authorize(profile.authority_ref, context.actor_id, profile.function_ref, 'QS-A06', now, {'QS'}, source['organization_id'])
            histories = {}
            bid_pairs = []
            for raw, bases in ((old_input, old), (action_input, current)):
                rows = {}
                for field, kind, schema, declared in (
                        ('bid_refs', 'Bid', QSBidView, bases['round_ref'].bid_refs),
                        ('clarification_refs', 'Clarification', QSBidClarificationView, bases['round_ref'].clarification_refs),
                        ('method_result_refs', 'MethodResult', QSBidMethodResultView, [])):
                    refs = indexed([ref_type(kind).model_validate(value) for value in raw[field]])
                    if raw is action_input and field != 'method_result_refs' and {ref.key() for ref in refs.values()} != {ref.key() for ref in declared}:
                        raise TaskConflict('QS bid successor lacks complete current round bids/clarifications')
                    for key, ref in indexed(declared).items():
                        if key in refs and refs[key] != ref:
                            raise TaskConflict('QS bid history selects two versions of one declared physical source')
                        refs[key] = ref
                    rows[field] = {key: read(ref, schema) for key, ref in refs.items()}
                    for row in rows[field].values():
                        if row.round_ref != bases['round_ref'].ref or row.document_ref != bases['procurement_document_ref'].ref:
                            raise TaskConflict('QS bid history borrows another original round/document version')
                        if field == 'method_result_refs' and (row.profile_ref != bases['evaluation_profile_ref'].ref
                                or row.calculated_at.clock_ref != row.available_at.clock_ref
                                or row.calculated_at.offset > row.available_at.offset):
                            raise TaskConflict('QS bid saved calculation substitutes its evaluation profile or creation time')
                bid_pairs.append(rows)
            before, after = bid_pairs
            for field in ('bid_refs', 'clarification_refs'):
                if not before[field].keys() <= after[field].keys():
                    raise TaskConflict('QS bid recovery drops original declared bid/clarification history')
            for key, bid in before['bid_refs'].items():
                latest = after['bid_refs'][key]
                if (bid.bidder_id != latest.bidder_id or bid.bidder_organization_id != latest.bidder_organization_id
                        or bid.submission_action_id != latest.submission_action_id
                        or (bid.submitted_at == latest.submitted_at and any(getattr(bid, field) != getattr(latest, field)
                            for field in ('price', 'region_id', 'price_time', 'included_scope_keys')))):
                    raise TaskConflict('QS bid recovery rewrites the original bidder or unchanged submission price')
            # New independently authenticated bidder submissions may carry a
            # new price. Keep both versions; native validation proves their
            # actual supersession instead of letting QS reprice an old offer.
            expected = {ref.key() for ref in (profile.normalization_result_ref, profile.ranking_result_ref) if ref is not None}
            if {row.ref.key() for row in after['method_result_refs'].values()} != expected:
                raise TaskConflict('QS bid successor replaces its exact current saved-method selection')
            for field in before:
                histories[field] = {'original': [row.model_dump(mode='json') for row in before[field].values()],
                    'current': [row.model_dump(mode='json') for row in after[field].values()]}
            old_rules = {key: read(ref, QSBidEvaluationRuleView) for key, ref in indexed(old_profile.rule_refs).items()}
            rules = {key: read(ref, QSBidEvaluationRuleView) for key, ref in indexed(profile.rule_refs).items()}
            if old_rules.keys() != rules.keys() or any(
                    row.predicate != rules[key].predicate or row.consequence != rules[key].consequence for key, row in old_rules.items()):
                raise TaskConflict('QS bid recovery rewrites original evaluation rules')
            for collection, bases in ((old_rules, old), (rules, current)):
                if any(row.round_ref != bases['round_ref'].ref or row.document_ref != bases['procurement_document_ref'].ref for row in collection.values()):
                    raise TaskConflict('QS bid recovery borrows rules from another round/document')
            histories['rule_refs'] = {'original': [row.model_dump(mode='json') for row in old_rules.values()],
                'current': [row.model_dump(mode='json') for row in rules.values()]}
            for rows in bid_pairs:
                for row in rows['bid_refs'].values():
                    if row.submitted_at.clock_ref != row.available_at.clock_ref or row.submitted_at.offset > row.available_at.offset:
                        raise TaskConflict('QS bid recovery makes an offer available before actual submission')
                    authorize(row.authority_ref, row.bidder_id, row.function_ref, row.submission_action_id,
                        row.submitted_at, {'Contractor', 'Supplier'}, row.bidder_organization_id)
                    if row.price.state == 'known':
                        proof_refs.append(row.price.value.basis_ref)
                for row in rows['clarification_refs'].values():
                    bid = rows['bid_refs'].get(row.bid_ref.key()[:2])
                    if bid is None or row.bid_ref != bid.ref or row.response_author_id != bid.bidder_id:
                        raise TaskConflict('QS bid clarification substitutes its original bidder or bid version')
                    authorize(row.response_authority_ref, row.response_author_id, row.response_function_ref, row.response_action_id,
                        row.available_at, {'Contractor', 'Supplier'}, bid.bidder_organization_id)
            for row in proof_rows:
                proof_refs.extend(row.evidence_refs)
                if isinstance(row, (QSProcurementDocumentView, QSBidMethodResultView)):
                    authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref, row.author_action_id,
                        getattr(row, 'calculated_at', row.available_at), {'QS'},
                        source['organization_id'] if isinstance(row, QSBidMethodResultView) else None)
                if isinstance(row, QSBidMethodResultView):
                    proof_refs.extend(value.normalized_price.basis_ref for value in row.prices)
            proof_refs.extend(criterion.basis_ref for base in (old_profile, profile) for criterion in base.criteria)
            observed = {}
            for ref in proof_refs:
                evidence = reading.resolve(ref)
                if not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic' or evidence.basis_kind != 'observed':
                    raise TaskConflict('QS bid recovery requires actual observed native round and submission evidence')
                observed[ref.key()] = evidence.model_dump(mode='json')
            if validate_relation(source_identity=deepcopy(source), original_action_input=old_input, action_input=action_input,
                    original_sources={field: row.model_copy(deep=True) for field, row in old.items()},
                    current_sources={field: row.model_copy(deep=True) for field, row in current.items()},
                    bid_history=deepcopy(histories), evidence=deepcopy(list(observed.values())),
                    context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('QS bid recovery lacks native round reactivation, actual bidder supersession and complete history validation')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('QS-A06', _CODE, '1', frozenset({'dependency_change'}), evaluate)
