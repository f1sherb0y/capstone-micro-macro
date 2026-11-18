"""CONTRACTOR-A13 finite consulting; estimates cannot commit construction/supply."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.contractor_advice_objects import (
    ContractorAdviceBriefView, ContractorAdviceOptionView, ContractorAdviceRequestView,
    ContractorAdviceProfileView, ContractorAdviceCapabilityView, ContractorAdviceAuthorityView,
    ContractorAdviceTaskView, ContractorAdviceExecutionView, ContractorAdviceFeeView,
    ContractorAdviceMethodView, ContractorAdviceDurationMethodView, ContractorAdviceCaseView,
    ContractorAdviceIssueView, ContractorAdviceSupplierView, ContractorAdviceReferenceView,
    ContractorAdviceProposalView,
)
from src.actions.contracts.contractor_bid_objects import ContractorBidMethodView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _known, _needs, _unsupported
from src.methods.contractor_advice import CONTRACTOR_DURATION_METHOD, ContractorDurationInput
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def give_preliminary_advice(context, action_input, reading):
    now, sources = context.business_time, {}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('contractor-advice-clock-alignment')

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('contractor-advice-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not row.effective_window.contains(now): _needs('current_original_advice_evidence', [ref])
            sources[ref.key()] = ref

    def read(ref, schema):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'contractor-advice-projection:{ref.kind}')
        if hasattr(row, 'scope') and not scope_covers(row.scope, context.scope):
            raise ValueError('Advisory input leaves original authorized service scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at); clock(row.effective_window.start)
            if row.available_at.offset > now.offset or not row.effective_window.contains(now):
                _needs('received_current_original_advice_input', [ref])
        evidence(getattr(row, 'evidence_refs', [])); sources[ref.key()] = ref; return row

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def authorized(ref, actor, function_ref, organization, action, roles):
        grant = read(ref, Authorization); function = read(function_ref, RoleAssignment)
        if (grant.actor_id != actor or grant.function_ref != function_ref or grant.organization_id != organization
                or action not in grant.action_ids or function.role not in roles
                or not any(scope_covers(scope, context.scope) for scope in grant.scopes)):
            raise ValueError('Advisory request/decision lacks original actor, organization and scope authority')
        clock(grant.validity.start)
        if not grant.validity.contains(now): _needs('current_original_advisory_authority', [ref])
        evidence([*grant.basis_refs, *function.basis_refs])

    def external_authority(row, prefix):
        role = read(getattr(row, prefix + '_function_ref'), RoleAssignment).role
        allowed = {'Owner': {'OWN-A02', 'OWN-A04'}, 'Architect': {'ARCHITECT-A13'},
                   'Engineer': {'ENGINEER-A13'}, 'QS': {'QS-A13'}}
        action = getattr(row, prefix + '_action_id')
        if action not in allowed.get(role, set()): raise ValueError('Advisory issuer/requester has no independent requesting action')
        authorized(getattr(row, prefix + '_authority_ref'), getattr(row, prefix + '_actor_id'),
                   getattr(row, prefix + '_function_ref'), getattr(row, prefix + '_organization_id'), action, {role})

    def reference(ref, basis_ref=None, recipients=None):
        row = read(ref, ContractorAdviceReferenceView)
        if not same(row.request_ref, request.ref) or (basis_ref is not None and basis_ref.key() not in keys(row.basis_refs)):
            raise ValueError('Advice assumption/use/condition changes the original request or basis version')
        if not _known(row.allowed, 'original_advice_reference_permission') or 'preliminary_advice' not in row.allowed_uses:
            _needs('original_preliminary_advice_reference_permission', [ref])
        if recipients is not None and not set(row.recipient_ids) <= set(recipients):
            raise ValueError('Advice discloses to an independently unauthorized recipient')
        return row

    def completed(choice, **fields):
        reading.recheck(); return {'kind': 'completed', 'payload': {'choice': choice, 'note': profile.note, **fields}}

    def technical(code):
        reading.recheck(); return {'kind': 'technical_error', 'error': {'kind': 'unrecorded',
            'correlation_id': context.operation_id, 'code': code}, 'retryability': 'unknown'}

    def dimensions(rows):
        if len({row.code for row in rows}) != len(rows): raise ValueError('Advice repeats a scope/scale dimension')
        for row in rows:
            if row.value.state == 'known': evidence([row.value.value.basis_ref])
        return {row.code: row.value for row in rows}

    def delivery_expectation(basis):
        if basis.desired_delivery_at.state == 'known': clock(basis.desired_delivery_at.value)

    try:
        request = read(action_input.advisory_request_ref, ContractorAdviceRequestView)
        profile = read(request.profile_ref, ContractorAdviceProfileView)
        if (profile.organization_id != reading.organization_id or not same(profile.request_ref, request.ref)
                or reading.organization_id not in request.recipient_organization_ids):
            raise ValueError('Advisory request/choice belongs to another contractor')
        authorized(profile.authority_ref, context.actor_id, context.function_ref, reading.organization_id,
                   'CONTRACTOR-A13', {'Contractor'})
        external_authority(request, 'author')
        if profile.choice == 'decline': return completed('decline')
        brief = read(action_input.brief_ref, ContractorAdviceBriefView)
        if not same(request.brief_ref, brief.ref) or keys(request.option_refs) != keys(action_input.option_refs):
            raise ValueError('Advisory input changes the original requested brief or option versions')
        bases = {brief.ref.key(): brief}; dimensions(brief.dimensions); delivery_expectation(brief)
        for ref in action_input.option_refs:
            row = read(ref, ContractorAdviceOptionView)
            if not same(row.brief_ref, brief.ref): raise ValueError('Advisory option changes its original brief')
            dimensions(row.dimensions); delivery_expectation(row)
            for source_ref in row.source_refs: reading.resolve(source_ref)
            bases[ref.key()] = row
        if profile.choice == 'propose_paid_study':
            if profile.proposal_ref is None: _needs('original_scoped_paid_study_proposal')
            proposal = read(profile.proposal_ref, ContractorAdviceProposalView)
            if (proposal.organization_id != reading.organization_id or not same(proposal.request_ref, request.ref)
                    or proposal.scope != context.scope):
                raise ValueError('Study proposal changes original request or contractor')
            evidence(proposal.estimate_basis_refs)
            for state, positive in ((proposal.effort, True), (proposal.proposed_fee, False)):
                if state.state == 'known':
                    evidence([state.value.basis_ref]); amount = decimal_fraction(state.value.value)
                    if amount < 0 or (positive and amount == 0): raise ValueError('Known proposed study effort/fee is invalid')
            keys(proposal.condition_refs)
            for ref in proposal.condition_refs: reference(ref)
            return completed('propose_paid_study', scope_ref=proposal.scope, effort=proposal.effort,
                             proposed_fee=proposal.proposed_fee, condition_refs=proposal.condition_refs)
        if action_input.advisory_authority_ref is None:
            _needs('bounded_paid_or_explicit_free_advisory_work_authorization', [request.ref])
        grant = read(action_input.advisory_authority_ref, ContractorAdviceAuthorityView)
        if (grant.organization_id != reading.organization_id or grant.scope != context.scope or grant.delegate_actor_id != context.actor_id
                or grant.delegate_function_ref != context.function_ref or not same(grant.request_ref, request.ref)):
            raise ValueError('Advisory work delegation changes original actor/function/organization/request')
        external_authority(grant, 'issuer')
        allowed_inputs = keys(grant.allowed_input_refs)
        required_inputs = keys([action_input.brief_ref, *action_input.option_refs, *action_input.supplier_evidence_refs])
        if not required_inputs <= allowed_inputs: _needs('explicit_original_service_scope_and_input_disclosure_authorization')
        if not grant.allowed_recipient_ids: _needs('original_authorized_advice_recipients')
        task = read(grant.task_ref, ContractorAdviceTaskView)
        if (task.organization_id != reading.organization_id or not same(task.authority_ref, grant.ref)
                or task.scope != grant.scope or not same(task.request_ref, request.ref) or keys(task.input_refs) != required_inputs):
            raise ValueError('Advisory study task changes original authorized input versions')
        if task.status == 'failed': return technical('contractor_advisory_study_failed')
        if task.status != 'completed' or task.execution_coverage != 'complete': _needs('completed_original_bounded_advisory_work')
        effort_cap = _known(grant.max_effort, 'original_finite_advice_effort_limit')
        cost_cap = _known(grant.max_internal_cost, 'original_finite_advice_cost_limit')
        evidence([effort_cap.basis_ref, cost_cap.basis_ref]); effort_total, cost_total = Fraction(), Fraction()
        if decimal_fraction(effort_cap.value) <= 0 or decimal_fraction(cost_cap.value) < 0:
            raise ValueError('Advisory work must have finite positive effort and nonnegative cost limits')
        keys(task.execution_refs)
        for ref in task.execution_refs:
            work = read(ref, ContractorAdviceExecutionView); clock(work.execution_window.start)
            if (work.organization_id != reading.organization_id or not same(work.task_ref, task.ref)
                    or work.scope != task.scope or not same(work.authority_ref, grant.ref)
                    or work.execution_window.start.offset < grant.effective_window.start.offset
                    or work.execution_window.end.offset > min(now.offset, grant.effective_window.end.offset)):
                raise ValueError('Actual advisory work changes authorized scope, task or business window')
            if work.status == 'failed': return technical('contractor_advisory_execution_failed')
            if work.status != 'completed': _needs('actual_completed_advisory_input_records', [ref])
            effort = _known(work.effort, 'actual_original_advice_effort'); cost = _known(work.internal_cost, 'actual_original_advice_cost')
            evidence([effort.basis_ref, cost.basis_ref])
            if effort.unit != effort_cap.unit or cost.currency != cost_cap.currency: _unsupported('contractor-advice-work-unit-currency-domain')
            if decimal_fraction(effort.value) <= 0 or decimal_fraction(cost.value) < 0: raise ValueError('Actual advisory effort/cost is invalid')
            effort_total += decimal_fraction(effort.value); cost_total += decimal_fraction(cost.value)
        if effort_total > decimal_fraction(effort_cap.value) or cost_total > decimal_fraction(cost_cap.value):
            _needs('separate_authorization_for_work_beyond_finite_advice_limits')
        if grant.mode == 'paid':
            if grant.fee_obligation_ref is None: _needs('original_agreed_advisory_fee_obligation')
            fee = read(grant.fee_obligation_ref, ContractorAdviceFeeView)
            if (not same(fee.authority_ref, grant.ref) or fee.creditor_id != reading.organization_id
                    or fee.debtor_id != grant.issuer_organization_id):
                raise ValueError('Advisory fee belongs to another service or legal party')
            amount = _known(fee.agreed_fee, 'original_agreed_paid_advisory_fee'); evidence([amount.basis_ref])
            if fee.status != 'effective' or decimal_fraction(amount.value) <= 0: _needs('effective_original_paid_advisory_arrangement')
        elif grant.fee_obligation_ref is not None: raise ValueError('Explicit free exchange cannot silently create a client fee')
        capability = read(action_input.capability_ref, ContractorAdviceCapabilityView); clock(capability.as_of)
        if capability.organization_id != reading.organization_id: raise ValueError('Advice capability belongs to another contractor')
        if capability.as_of != now or capability.coverage != 'complete': _needs('complete_current_original_advisory_capability')
        if not action_input.method_refs: _unsupported('contractor-preliminary-constructability-method')
        if not keys(action_input.method_refs) <= keys(capability.method_refs): _unsupported('contractor-preliminary-capability-method-domain')
        if not keys(action_input.supplier_evidence_refs) <= keys(request.allowed_supplier_evidence_refs):
            raise ValueError('Advisory input discloses unauthorized supplier evidence')
        supplies = {}
        for ref in action_input.supplier_evidence_refs:
            supply = read(ref, ContractorAdviceSupplierView)
            if supply.basis_ref.key() not in bases: raise ValueError('Supply advice estimates another original scope/version')
            role = 'Supplier' if supply.source_kind == 'supplier_advice' else 'Contractor'
            authorized(supply.author_authority_ref, supply.author_actor_id, supply.author_function_ref,
                       supply.author_organization_id, 'SUPPLIER-A13' if role == 'Supplier' else 'CONTRACTOR-A13', {role})
            for ref_ in supply.assumption_refs: reference(ref_, supply.basis_ref, grant.allowed_recipient_ids)
            supplies[ref.key()] = supply
        if not profile.case_refs: _needs('original_scoped_constructability_advice')
        keys(profile.case_refs); covered, results = set(), []
        for ref in profile.case_refs:
            case = read(ref, ContractorAdviceCaseView)
            if (case.organization_id != reading.organization_id or not same(case.task_ref, task.ref)
                    or case.scope != context.scope or not same(case.request_ref, request.ref) or case.basis_ref.key() not in bases):
                raise ValueError('Constructability case changes original finite task or basis version')
            if case.basis_ref.key() in covered: raise ValueError('Advice repeats the same original brief/option')
            covered.add(case.basis_ref.key()); basis = bases[case.basis_ref.key()]
            if case.status == 'failed': return technical('contractor_constructability_method_failed')
            if case.status != 'ok': _unsupported('contractor-constructability-case-domain')
            if 'preliminary_advice' not in basis.allowed_uses: _needs('original_preliminary_basis_use_permission')
            if (basis.region_id not in capability.region_ids or basis.object_type not in capability.object_types
                    or not set(basis.special_condition_codes) <= set(capability.special_condition_codes)):
                _unsupported('contractor-advisory-region-object-special-condition-domain')
            if case.constructability_method_ref.key() not in keys(action_input.method_refs):
                raise ValueError('Advice adds an undeclared constructability method')
            method = read(case.constructability_method_ref, ContractorAdviceMethodView)
            if (basis.region_id not in method.region_ids or basis.object_type not in method.object_types
                    or not set(basis.special_condition_codes) <= set(method.special_condition_codes)):
                _unsupported('contractor-constructability-method-applicability')
            original_dims, used_dims = dimensions(basis.dimensions), dimensions(case.input_dimensions)
            if original_dims != used_dims: _needs('same_original_scale_structure_and_transport_batch_versions')
            incomplete_dimensions = any(code not in original_dims or original_dims[code].state != 'known'
                                        for code in method.required_dimension_codes)
            if case.duration_method_ref.key() not in keys(method.allowed_duration_method_refs):
                raise ValueError('Advice uses an undeclared duration method')
            duration_method = read(case.duration_method_ref, ContractorAdviceDurationMethodView)
            if duration_method.local_method_ref.key() != CONTRACTOR_DURATION_METHOD.key(): _unsupported('contractor-duration-method-binding')
            assumptions = keys(case.assumption_refs)
            if duration_method.independent_resources_assumption_ref.key() not in assumptions:
                _needs('explicit_independent_inputs_assumption_for_duration_bounds')
            for ref_ in case.assumption_refs: reference(ref_, case.basis_ref, grant.allowed_recipient_ids)
            keys(case.work_method_refs)
            if not keys(case.work_method_refs) <= keys(method.allowed_work_method_refs):
                raise ValueError('Advice substitutes undeclared original work methods')
            for ref_ in case.work_method_refs:
                work_method = read(ref_, ContractorBidMethodView)
                if (basis.region_id not in work_method.region_ids or basis.object_type not in work_method.object_types
                        or not set(basis.special_condition_codes) <= set(work_method.special_condition_codes)):
                    _unsupported('contractor-advice-work-method-domain')
            issues, site_gap, scope_gap = [], False, False; keys(case.issue_refs)
            for ref_ in case.issue_refs:
                issue = read(ref_, ContractorAdviceIssueView)
                if not same(issue.request_ref, request.ref) or not same(issue.basis_ref, case.basis_ref):
                    raise ValueError('Interface issue changes original advice scope/version')
                if not scope_covers(case.scope, issue.issue.scope_ref): raise ValueError('Interface issue changes authorized service scope')
                reference(issue.issue.requirement_ref, case.basis_ref, grant.allowed_recipient_ids); evidence(issue.issue.evidence_refs)
                site_gap |= issue.code == 'site_receiving'; scope_gap |= issue.code == 'unassessed_scope'; issues.append(issue.issue)
            if incomplete_dimensions and not scope_gap: _needs('explicit_unassessed_scale_scope_for_limited_advice')
            if not keys(case.supplier_evidence_refs) <= set(supplies): raise ValueError('Case borrows unread supplier evidence')
            for ref_ in case.supplier_evidence_refs:
                supply = supplies[ref_.key()]
                if not same(supply.basis_ref, case.basis_ref): raise ValueError('Case applies supplier estimate to another version')
                if not keys(supply.assumption_refs) <= assumptions: _needs('supplier_estimates_and_conditions_retained_as_assumptions')
                if supply.site_receiving_ready.state != 'known' or not supply.site_receiving_ready.value:
                    if not site_gap: _needs('explicit_site_receiving_interface_gap_not_manufacturing_delivery')
            use = reference(case.permitted_use_ref, case.basis_ref, grant.allowed_recipient_ids)
            if not use.recipient_ids: _needs('original_finite_advice_disclosure_recipients')
            if not case.validity_condition_refs: _needs('original_advice_validity_conditions')
            keys(case.validity_condition_refs)
            for ref_ in case.validity_condition_refs: reference(ref_, case.basis_ref, grant.allowed_recipient_ids)
            if not case.activities: _unsupported('contractor-declared-duration-operation-method')
            evidence([case.result_basis_ref])
            for activity in case.activities:
                evidence([activity.source_ref])
                for interval in (activity.lower, activity.upper):
                    if interval.state == 'known': evidence([interval.value.basis_ref])
            report = reading.calculate(CONTRACTOR_DURATION_METHOD, ContractorDurationInput(activities=case.activities,
                unit=duration_method.unit, result_basis_ref=case.result_basis_ref, source_refs=list(sources.values())))
            if report.kind != 'ok':
                if report.kind == 'invalid_input': _unsupported('contractor-duration-dependency-and-unit-domain')
                raw = report.model_dump(mode='python')
                if report.kind == 'needs_information': raw['requested_refs'] = []
                raise ObservationGap(raw)
            basis_payload = {'kind': 'brief', 'brief_ref': case.basis_ref} if case.basis_ref.kind == 'OwnerBrief' else {'kind': 'option', 'option_ref': case.basis_ref}
            lower, upper = report.value.lower, report.value.upper
            if incomplete_dimensions:
                lower = upper = {'state': 'unknown', 'reason_code': 'original_required_scale_scope_unassessed',
                                 'missing_refs': case.evidence_refs}
            results.append({'basis': basis_payload, 'scope_ref': case.scope, 'work_method_refs': case.work_method_refs,
                'duration': {'lower': lower, 'upper': upper, 'method_ref': duration_method.ref},
                'interface_issues': issues, 'assumptions': case.assumption_refs, 'permitted_use_ref': case.permitted_use_ref,
                'validity_condition_refs': case.validity_condition_refs})
        expected = keys(action_input.option_refs) if action_input.option_refs else {brief.ref.key()}
        if covered != expected: _needs('complete_original_requested_option_or_brief_advice_scope')
        return completed('provide_advice', results=results)
    except ObservationGap as gap:
        reading.recheck(); return gap.result
