"""ARCHITECT-A01 bounded business discovery, preserving prior commitments."""
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.architect_opportunity_objects import (
    ArchitectOpportunityView, ArchitectOpportunityStrategyView, ArchitectOpportunityTriggerView,
    ArchitectPreparationRequestView, ArchitectPreparationAuthorityView, ArchitectPreparationEstimateView,
    ArchitectPreparationMethodView, ArchitectOpportunityReferenceView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.service_objects import ServiceResourceCalendarView, ServiceWorkProfileView
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.capacity import CAPACITY_METHOD, CapacityInput, ExactAmount
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers
from src.actions.roles.professional_outreach import outreach_constraint


def discover_opportunity(context, action_input, reading):
    scope, now, sources = action_input.scope, context.business_time, {}

    def available(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('architect-opportunity-clock-alignment')
        if point.offset > now.offset:
            _needs('received_original_opportunity_facts')

    def current(window):
        available(window.start)
        if not window.contains(now):
            _needs('current_opportunity_source_or_permission')

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('architect-opportunity-evidence-schema')
            if row.effective_window is not None:
                current(row.effective_window)
            sources[ref.key()] = ref

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported(f'architect-opportunity-projection:{ref.kind}')
        if hasattr(row, 'scope') and not scope_covers(row.scope, scope):
            raise ValueError('Opportunity projection does not cover the invocation scope')
        if hasattr(row, 'available_at'):
            available(row.available_at); current(row.effective_window)
        evidence(getattr(row, 'evidence_refs', []))
        sources[ref.key()] = ref
        return row

    def authorized(ref, actor, function):
        grant = read(ref, Authorization); assignment = read(function, RoleAssignment)
        if (assignment.role != 'Architect' or grant.organization_id != reading.organization_id
                or grant.actor_id != actor or grant.function_ref != function
                or 'ARCHITECT-A01' not in grant.action_ids
                or not any(scope_covers(s, scope) for s in grant.scopes)):
            raise ValueError('Opportunity preparation lacks independent original Architect authority')
        current(grant.validity); evidence([*grant.basis_refs, *assignment.basis_refs])

    def completed(choice, note, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'scope': scope, 'note': note, **fields}}

    def questions(rows, recipients):
        for row in rows:
            if row.scope != scope or not row.target_refs or not row.recipient_ids:
                raise ValueError('Opportunity clarification lacks original scope, target or recipient')
            if not set(row.recipient_ids) <= set(recipients):
                raise ValueError('Opportunity clarification discloses data to an unauthorized recipient')
            unique_refs(row.target_refs)
            for ref in [*row.target_refs, row.response_requirement_ref]:
                target = read(ref, ArchitectOpportunityReferenceView)
                if target.opportunity_ref != opportunity.ref:
                    raise ValueError('Opportunity clarification target belongs to another opportunity')
            if not set(row.blocking_uses) <= {'research'}:
                raise ValueError('Discovery question borrows an undeclared delivery purpose')
            evidence(row.evidence_refs)
        return rows

    def bounded(estimate, remaining, field):
        a = _known(estimate, f'original_preparation_{field}_estimate')
        b = _known(remaining, f'current_preparation_remaining_{field}')
        evidence([a.basis_ref, b.basis_ref])
        unit = 'currency' if field == 'budget' else 'unit'
        if getattr(a, unit) != getattr(b, unit):
            _unsupported(f'architect-preparation-{field}-conversion')
        if decimal_fraction(a.value) < 0 or decimal_fraction(b.value) < 0:
            raise ValueError('Preparation estimate or remaining allowance is negative')
        return decimal_fraction(a.value) <= decimal_fraction(b.value)

    try:
        if scope != context.scope:
            raise ValueError('Opportunity discovery changes invocation scope')
        opportunity = read(action_input.opportunity_ref, ArchitectOpportunityView)
        strategy = read(action_input.strategy_ref, ArchitectOpportunityStrategyView)
        calendar = read(action_input.capacity_ref, ServiceResourceCalendarView)
        if (strategy.organization_id != reading.organization_id or calendar.organization_id != reading.organization_id
                or strategy.opportunity_ref != opportunity.ref or strategy.capacity_ref != calendar.ref):
            raise ValueError('Opportunity strategy changes original organization, opportunity or calendar')
        if (reading.organization_id not in opportunity.recipient_organization_ids
                or context.actor_id not in opportunity.recipient_actor_ids
                or not _known(opportunity.permission, 'original_opportunity_access_permission')):
            _needs('independently_authorized_opportunity_access', [opportunity.ref])
        authorized(strategy.author_authority_ref, strategy.author_actor_id, strategy.author_function_ref)
        constraint=outreach_constraint(context,reading,strategy.outreach_limits)
        restrictions = [constraint[1]] if constraint else []
        for choice in strategy.choice_order:
            if constraint and not constraint[0] and choice not in {'ignore','clarify'}:continue
            if choice == 'ignore':
                return completed('ignore', '; '.join(restrictions) or 'Original strategy selects no participation',
                                 reason=strategy.ignore_reason)
            if choice == 'clarify':
                if opportunity.questions:
                    return completed('clarify', 'Original scoped discovery questions; no service commitment',
                                     questions=questions(opportunity.questions, opportunity.clarification_recipient_ids))
                continue
            if opportunity.source_verified.state != 'known' or not opportunity.source_verified.value:
                restrictions.append('Opportunity source is unconfirmed; clarification required')
                continue
            if opportunity.status != 'open' or strategy.ref not in opportunity.strategy_refs:
                restrictions.append('Opportunity is closed or outside the original strategy')
                continue
            if choice == 'track' and opportunity.watch_condition_ref is not None:
                trigger = read(opportunity.watch_condition_ref, ArchitectOpportunityTriggerView)
                if trigger.opportunity_ref != opportunity.ref or trigger.organization_id != reading.organization_id:
                    raise ValueError('Opportunity watch trigger changes original opportunity or organization')
                if trigger.status == 'active':
                    return completed('track', 'Track the original opportunity without preparation spending', watch_condition_ref=trigger.ref)
            if choice == 'express_interest' and opportunity.inviting_actor_id is not None:
                if opportunity.interest_permission.state == 'known' and opportunity.interest_permission.value:
                    return completed('express_interest', 'Interest decision only; no message, appointment or income',
                                     recipient_id=opportunity.inviting_actor_id)
            if choice != 'prepare':
                continue
            if action_input.preparation_authority_ref is None or strategy.preparation_ref is None:
                restrictions.append('No independent preparation delegation')
                continue
            request = read(strategy.preparation_ref, ArchitectPreparationRequestView)
            grant = read(action_input.preparation_authority_ref, ArchitectPreparationAuthorityView)
            if (grant.organization_id != reading.organization_id or grant.actor_id != context.actor_id
                    or grant.function_ref != context.function_ref or grant.opportunity_ref != opportunity.ref
                    or grant.request_profile_ref != request.ref or request.opportunity_ref != opportunity.ref
                    or request.scope != scope or request.strategy_ref != strategy.ref or request.authority_basis_refs != [grant.ref]):
                raise ValueError('Preparation request changes original delegation, actor, strategy or opportunity')
            authorized(grant.issuer_authority_ref, grant.issuer_actor_id, grant.issuer_function_ref)
            if not _known(grant.permitted, 'independent_preparation_permission') or request.purpose not in grant.allowed_purposes:
                restrictions.append('Preparation permission or purpose not granted')
                continue
            available(calendar.as_of); available(grant.as_of)
            if calendar.as_of != now or calendar.coverage != 'complete' or grant.as_of != now:
                _needs('complete_current_original_calendar_and_preparation_allowances')
            for refs in (request.input_refs, request.output_requirement_refs, request.dependency_refs):
                unique_refs(refs)
                for ref in refs:
                    reading.resolve(ref)
            if not set(request.input_refs) <= set(grant.allowed_input_refs):
                raise ValueError('Preparation request includes independently unauthorized inputs')
            questions(request.questions, grant.allowed_recipient_ids)
            if request.estimate_result_ref is None:
                _needs('saved_supported_preparation_cost_estimate')
            estimate = read(request.estimate_result_ref, ArchitectPreparationEstimateView)
            if (estimate.opportunity_ref != opportunity.ref or estimate.request_profile_ref != request.ref
                    or estimate.work_profile_ref != request.work_profile_ref or set(estimate.input_refs) != set(request.input_refs)
                    or estimate.estimated_cost != request.estimated_cost or estimate.effort_estimate != request.effort_estimate):
                raise ValueError('Preparation estimate changes original request, inputs, method profile or estimates')
            unique_refs(estimate.input_refs); available(estimate.executed_at)
            authorized(estimate.author_authority_ref, estimate.author_actor_id, estimate.author_function_ref)
            if estimate.executed_at.offset > estimate.available_at.offset:
                raise ValueError('Preparation estimate receipt precedes execution')
            if estimate.execution_status == 'failed':
                reading.recheck()
                return {'kind': 'technical_error', 'error': {'kind': 'unrecorded', 'correlation_id': context.operation_id,
                        'code': 'preparation_estimate_failed'}, 'retryability': 'unknown'}
            if estimate.execution_status != 'succeeded':
                _unsupported('architect-preparation-estimate-method')
            method = read(estimate.method_ref, ArchitectPreparationMethodView)
            region = _known(opportunity.region_id, 'preparation_region')
            service = _known(opportunity.service_code, 'preparation_service')
            object_type = _known(opportunity.object_type, 'preparation_object_type')
            if (region not in method.supported_region_ids or service not in method.supported_service_codes
                    or object_type not in method.supported_object_types):
                _unsupported('architect-preparation-estimate-support-domain')
            if not bounded(request.estimated_cost, grant.remaining_budget, 'budget'):
                restrictions.append('Preparation exceeds remaining spending authority')
                continue
            if request.effort_estimate.state == 'known' and not bounded(request.effort_estimate, grant.remaining_effort, 'effort'):
                restrictions.append('Preparation exceeds remaining effort authority')
                continue
            if request.work_profile_ref is not None:
                profile = read(request.work_profile_ref, ServiceWorkProfileView)
                current(profile.effective_window)
                if (profile.clock_ref != now.clock_ref or profile.method != CAPACITY_METHOD.id
                        or region not in profile.region_ids or service not in profile.service_codes
                        or object_type not in profile.object_types):
                    _unsupported('architect-preparation-work-profile-domain')
                effort = _known(request.effort_estimate, 'supported_preparation_effort')
                window = _known(request.desired_window, 'original_preparation_work_window')
                evidence([effort.basis_ref])
                if (window.start.clock_ref != now.clock_ref or window.start.offset < now.offset
                        or window.bounds != 'closed_open'):
                    _unsupported('architect-preparation-future-half-open-window')
                if effort.unit != profile.effort_unit or decimal_fraction(effort.value) <= 0:
                    _unsupported('architect-preparation-effort-domain')
                ticks = window.end.offset - window.start.offset
                if ticks <= 0:
                    raise ValueError('Preparation window is empty')
                amount = decimal_fraction(effort.value) / (decimal_fraction(profile.effort_per_capacity_tick) * ticks)
                resources = []
                for row in calendar.resources:
                    total = _known(row.total, 'current_original_resource_capacity')
                    evidence([total.basis_ref])
                    resources.append({'resource_ref': row.resource_ref, 'resource_kind': row.resource_kind,
                        'region_id': _known(row.region_id, 'original_resource_region'), 'total': total,
                        'effective_window': row.effective_window})
                for row in calendar.commitments:
                    evidence([row.quantity.basis_ref])
                result = reading.calculate(CAPACITY_METHOD, CapacityInput(clock_ref=now.clock_ref,
                    demands=[{'resource_kind': profile.resource_kind, 'region_id': region, 'unit': profile.capacity_unit,
                              'amount': ExactAmount.from_fraction(amount), 'window': window, 'basis_refs': [effort.basis_ref]}],
                    resources=resources, commitments=[row.model_dump(mode='python') for row in calendar.commitments],
                    source_refs=list(sources.values())))
                if result.kind != 'ok':
                    if result.kind == 'invalid_input':
                        _unsupported('architect-preparation-capacity-domain')
                    raw = result.model_dump(mode='python')
                    if result.kind == 'needs_information': raw['requested_refs'] = []
                    raise ObservationGap(raw)
                if not result.value.feasible:
                    restrictions.append('Original prior commitments leave insufficient preparation capacity')
                    continue
            elif request.desired_window.state == 'known':
                window = request.desired_window.value
                if window.start.clock_ref != now.clock_ref or window.start.offset < now.offset:
                    _needs('future_original_preparation_request_window')
            return completed('prepare', 'Bounded request only; original commitments preserved; no task execution or resource reservation',
                request=request.model_dump(exclude={'ref', 'opportunity_ref', 'strategy_ref', 'available_at',
                    'effective_window', 'evidence_refs', 'estimated_cost', 'estimate_result_ref'}))
        if opportunity.questions:
            return completed('clarify', '; '.join(restrictions) or 'Discovery needs original information',
                             questions=questions(opportunity.questions, opportunity.clarification_recipient_ids))
        _needs('eligible_original_opportunity_choice')
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
