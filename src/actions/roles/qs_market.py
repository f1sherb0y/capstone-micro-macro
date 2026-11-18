"""QS-A01 market decisions; never sends interest or executes research."""
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.qs_market_objects import (
    QSMarketStrategyView, QSMarketOpportunityView, QSMarketTriggerView,
    QSMarketPriceSourceView, QSMarketRequestView, QSMarketResearchAuthorityView,
)
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers
from src.actions.roles.professional_outreach import outreach_constraint


def identify_market(context, action_input, reading):
    now = context.business_time

    def available(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('qs-market-clock-alignment')
        if point.offset > now.offset:
            _needs('available_original_market_facts')

    def current(window):
        available(window.start)
        if not window.contains(now):
            _needs('current_market_permission_or_source')

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('qs-market-evidence-schema')
            if row.effective_window is not None:
                current(row.effective_window)

    def read(ref, schema, collect=True):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported(f'qs-market-projection:{ref.kind}')
        if hasattr(row, 'scope') and not scope_covers(row.scope, action_input.scope):
            raise ValueError('Market source does not cover the requested scope')
        if hasattr(row, 'available_at'):
            available(row.available_at); current(row.effective_window)
        if collect:
            evidence(getattr(row, 'evidence_refs', []))
        return row

    def authorized(ref, actor, function):
        grant = read(ref, Authorization)
        assignment = read(function, RoleAssignment)
        if (grant.actor_id != actor or grant.function_ref != function
                or grant.organization_id != reading.organization_id or assignment.role != 'QS'
                or 'QS-A01' not in grant.action_ids
                or not any(scope_covers(scope, action_input.scope) for scope in grant.scopes)):
            raise ValueError('Market decision lacks independent original QS authorization')
        current(grant.validity); evidence(grant.basis_refs); evidence(assignment.basis_refs)

    def permitted(state):
        return state.state == 'known' and state.value is True

    def completed(choice, note, **fields):
        if choice=='register_source' and (strategy.monthly_cost_policy_ref is not None or strategy.monthly_cost_observation_ref is not None):
            if strategy.monthly_cost_policy_ref is None or strategy.monthly_cost_observation_ref is None:
                raise ValueError('Monthly cost policy and observation must be declared together')
            from src.actions.roles.qs_monthly_cost_market import analyze_monthly_cost_market
            judgment=analyze_monthly_cost_market(context,reading,strategy=strategy,source_refs=fields['source_refs'])
            note=judgment.model_dump_json()
            if judgment.operation=='review_cost_market':choice='ignore';fields={'reason':judgment.interpretation}
        reading.recheck()
        return {'kind': 'completed', 'payload': {
            'choice': choice, 'scope': action_input.scope,
            'note': note, **fields}}

    def bounded(estimate, remaining, dimension):
        if estimate.state != 'known' or remaining.state != 'known':
            _needs(f'original_market_research_{dimension}_estimate_and_remaining_limit')
        a, b = estimate.value, remaining.value
        evidence([a.basis_ref, b.basis_ref])
        field = 'currency' if dimension == 'budget' else 'unit'
        if getattr(a, field) != getattr(b, field):
            _unsupported(f'qs-market-research-{dimension}-conversion')
        cost, limit = decimal_fraction(a.value), decimal_fraction(b.value)
        if cost < 0 or limit < 0:
            raise ValueError('Market research estimate or remaining limit is negative')
        return cost <= limit

    try:
        if action_input.scope != context.scope:
            raise ValueError('Market decision changes invocation scope')
        unique_refs(action_input.opportunity_refs); unique_refs(action_input.price_source_refs)
        strategy = read(action_input.strategy_ref, QSMarketStrategyView)
        if strategy.organization_id != reading.organization_id:
            raise ValueError('Market strategy belongs to another organization')
        authorized(strategy.author_authority_ref, strategy.author_actor_id, strategy.author_function_ref)
        if (set(strategy.opportunity_order) != set(action_input.opportunity_refs)
                or set(strategy.source_order) != set(action_input.price_source_refs)):
            _needs('complete_original_market_candidate_set', [*strategy.opportunity_order, *strategy.source_order])
        constraint=outreach_constraint(context,reading,strategy.outreach_limits)
        restrictions = [constraint[1]] if constraint else []
        for choice in strategy.choice_order:
            if constraint and not constraint[0] and choice!='ignore':continue
            if choice in {'track', 'express_interest'}:
                for ref in strategy.opportunity_order:
                    row = read(ref, QSMarketOpportunityView, collect=False)
                    if (context.actor_id not in row.recipient_ids or not permitted(row.permission)):
                        restrictions.append('Opportunity access is not independently authorized')
                        continue
                    evidence(row.evidence_refs)
                    if row.status != 'open' or strategy.ref not in row.strategy_refs:
                        continue
                    if choice == 'track' and row.trigger_ref is not None:
                        trigger = read(row.trigger_ref, QSMarketTriggerView)
                        if trigger.opportunity_ref != row.ref or trigger.scope != row.scope:
                            raise ValueError('Market trigger changes original opportunity or scope')
                        if trigger.status == 'active' and context.actor_id in trigger.recipient_ids:
                            return completed('track', 'Track the original visible opportunity and trigger',
                                             opportunity_ref=row.ref, trigger_ref=trigger.ref)
                    if (choice == 'express_interest' and row.inviting_actor_id is not None
                            and permitted(row.interest_permission)):
                        return completed('express_interest', 'Interest decision only; no disclosure or service commitment',
                                         recipient_id=row.inviting_actor_id)
            elif choice == 'register_source':
                for ref in strategy.source_order:
                    row = read(ref, QSMarketPriceSourceView, collect=False)
                    if (context.actor_id not in row.recipient_ids or not permitted(row.permission)
                            or row.confidentiality in {'competitor_secret', 'unauthorized'}):
                        restrictions.append('Confidential or unauthorized price source withheld')
                        continue
                    evidence(row.evidence_refs)
                    if (row.source_kind == 'market_commentary' or row.observation_ref is None
                            or row.applicability.state != 'known'):
                        restrictions.append('Commentary or incomplete applicability retained as a source gap')
                        continue
                    app = row.applicability.value
                    if app.price_source_ref != row.ref or app.scope != row.scope:
                        raise ValueError('Price applicability changes original source or scope')
                    available(app.available_at); current(app.effective_window); available(app.price_time)
                    if app.price_time.offset > app.available_at.offset:
                        raise ValueError('Price applicability precedes its original price observation')
                    observed = reading.resolve(row.observation_ref)
                    if not isinstance(observed, EvidenceRecord) or observed.basis_kind != 'observed':
                        restrictions.append('Original source lacks an observed quote or index')
                        continue
                    evidence([row.observation_ref, *app.evidence_refs])
                    for metadata in [app.region_ref, app.delivery_scope_ref, app.measurement_rule_ref,
                                     *app.included_scope_refs, *app.excluded_scope_refs]:
                        reading.resolve(metadata)
                    return completed('register_source',
                        'Register one original source at its original region/time/scope; no conversion or confidence uplift'
                        + ('; ' + '; '.join(row.limitations) if row.limitations else ''),
                        source_refs=[row.ref], applicability=app.model_dump(exclude={
                            'ref', 'scope', 'available_at', 'effective_window'}))
            elif choice == 'prepare':
                if strategy.preparation_ref is None or action_input.research_authority_ref is None:
                    restrictions.append('Research request lacks independent preparation authority')
                    continue
                request = read(strategy.preparation_ref, QSMarketRequestView)
                grant = read(action_input.research_authority_ref, QSMarketResearchAuthorityView)
                if (request.strategy_ref != strategy.ref or grant.strategy_ref != strategy.ref
                        or grant.request_profile_ref != request.ref or grant.organization_id != reading.organization_id
                        or grant.delegate_actor_id != context.actor_id or grant.delegate_function_ref != context.function_ref
                        or request.authority_basis_refs != [grant.ref]):
                    raise ValueError('Research request changes original strategy, delegation or provider')
                authorized(grant.issuer_authority_ref, grant.issuer_actor_id, grant.issuer_function_ref)
                if not permitted(grant.permission) or request.purpose not in grant.allowed_purposes:
                    restrictions.append('Research permission or purpose not granted')
                    continue
                if grant.as_of != now:
                    _needs('current_original_market_research_remaining_limits')
                if not set(request.input_refs) <= set(grant.allowed_input_refs):
                    _needs('independently_authorized_market_research_inputs')
                if not bounded(request.estimated_cost, grant.remaining_budget, 'budget'):
                    restrictions.append('Research request exceeds remaining budget')
                    continue
                if request.work_profile_ref is not None and request.effort_estimate.state != 'known':
                    _needs('supported_original_market_research_effort_estimate')
                if request.effort_estimate.state == 'known':
                    if not bounded(request.effort_estimate, grant.remaining_effort, 'effort'):
                        restrictions.append('Research request exceeds remaining work allowance')
                        continue
                if request.desired_window.state == 'known':
                    window = request.desired_window.value
                    if window.start.clock_ref != now.clock_ref:
                        _unsupported('qs-market-research-window-clock')
                    if window.start.offset < now.offset:
                        _needs('future_market_research_request_window')
                for refs in (request.input_refs, request.output_requirement_refs, request.dependency_refs):
                    unique_refs(refs)
                    for ref in refs:
                        original = reading.resolve(ref)
                        if isinstance(original, QSMarketPriceSourceView) and (
                                context.actor_id not in original.recipient_ids or not permitted(original.permission)
                                or original.confidentiality in {'competitor_secret', 'unauthorized'}):
                            _needs('authorized_nonconfidential_market_research_inputs')
                if request.work_profile_ref is not None:
                    reading.resolve(request.work_profile_ref)
                for question in request.questions:
                    if question.scope != action_input.scope:
                        raise ValueError('Research question changes original request scope')
                    if not set(question.recipient_ids) <= set(grant.question_recipient_ids):
                        raise ValueError('Research question names an independently unauthorized recipient')
                    for ref in [*question.target_refs, question.response_requirement_ref]:
                        reading.resolve(ref)
                    evidence(question.evidence_refs)
                return completed('prepare', 'Bounded preparation request only; no work, resource reservation or charge',
                    request=request.model_dump(exclude={'ref', 'strategy_ref', 'available_at', 'effective_window',
                                                      'evidence_refs', 'estimated_cost'}))
            elif choice == 'ignore':
                return completed('ignore', '; '.join(restrictions) or 'Original strategy selects no participation',
                                 reason=strategy.ignore_reason)
        _needs('eligible_original_market_choice')
    except ObservationGap as exc:
        reading.recheck()
        return exc.result
