"""BANK-A08: risk observations never replace contractual measure gates."""
from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.bank_monitoring_objects import (
    BankMonitoringArrangementView, BankMonitoringProfileView, BankMonitoringCovenantView,
    BankMonitoringReportView, BankMonitoringNoticeView, BankMonitoringRequirementView,
    BankMonitoringDimensionView, BankMonitoringMethodView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def monitor_arrangement(context, action_input, reading):
    now, lender = context.business_time, reading.organization_id

    def same(left, right): return left.key() == right.key()

    def keys(refs):
        unique_refs(refs); return {ref.key() for ref in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('bank-monitoring-clock-alignment')

    def evidence(refs, historical=False, observed=False):
        keys(refs)
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('bank-monitoring-evidence-schema')
            if observed and row.basis_kind != 'observed':
                _needs('independently_observed_contractual_monitoring_fact', [ref])
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if not historical and not row.effective_window.contains(now): _needs('current_monitoring_evidence', [ref])

    def read(ref, schema, historical=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported(f'bank-monitoring-projection:{ref.kind}')
        if hasattr(row, 'scope') and not (scope_covers(row.scope, context.scope) or scope_covers(context.scope, row.scope)):
            raise ValueError('Monitoring input leaves original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_original_monitoring_input', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historical and not row.effective_window.contains(now): _needs('currently_effective_monitoring_input', [ref])
        evidence(getattr(row, 'evidence_refs', []), historical)
        return row

    def authorize(ref, actor, function_ref, organization, action, scope, at, bank=False):
        grant = read(ref, Authorization); function = read(function_ref, RoleAssignment)
        if (grant.organization_id != organization or grant.actor_id != actor or grant.function_ref != function_ref
                or action not in grant.action_ids or (bank and function.role != 'Bank')
                or not any(scope_covers(value, scope) for value in grant.scopes)):
            raise ValueError('Monitoring actor lacks original organization/action/scope authority')
        clock(grant.validity.start)
        if not grant.validity.contains(at): _needs('valid_original_monitoring_authority', [ref])
        evidence([*grant.basis_refs, *function.basis_refs], historical=at != now)

    def completed(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'findings': findings, 'note': profile.note, **fields}}

    def pending(refs, code):
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': 'original_monitoring_notice_requires_query',
                'resume_condition': {'trigger': 'event', 'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    try:
        arrangement = read(action_input.arrangement_ref, BankMonitoringArrangementView)
        profile = read(action_input.monitoring_profile_ref, BankMonitoringProfileView)
        if (arrangement.lender_id != lender or profile.organization_id != lender
                or not same(profile.arrangement_ref, arrangement.ref)
                or not scope_covers(context.scope, profile.affected_scope)):
            raise ValueError('Monitoring profile changes original bank/facility or widens affected scope')
        authorize(profile.authority_ref, context.actor_id, context.function_ref, lender, 'BANK-A08', context.scope, now, True)
        if arrangement.coverage != 'complete': _needs('complete_received_original_monitoring_history')
        for field in ('covenant_refs', 'notice_refs', 'disclosure_refs'):
            if keys(getattr(action_input, field)) != keys(getattr(arrangement, field)):
                _needs(f'all_original_received_monitoring_{field}', getattr(arrangement, field))
        covenants = {}
        for ref in action_input.covenant_refs:
            covenant = read(ref, BankMonitoringCovenantView, True)
            if not same(covenant.arrangement_ref, arrangement.ref): raise ValueError('Covenant belongs to another arrangement')
            if len({gate.choice for gate in covenant.gates}) != len(covenant.gates): raise ValueError('Covenant repeats a measure gate')
            covenants[ref.key()] = covenant
        reports, findings, dimensions = [], [], {}
        for ref in action_input.disclosure_refs:
            report = read(ref, BankMonitoringReportView, True)
            covenant = covenants.get(report.covenant_ref.key())
            if (covenant is None or not same(report.arrangement_ref, arrangement.ref)
                    or not same(report.terms_ref, covenant.terms_ref) or not scope_covers(covenant.scope, report.scope)):
                raise ValueError('Monitoring report changes original arrangement, covenant, terms or scope')
            clock(report.observed_at)
            if report.observed_at.offset > min(now.offset, report.available_at.offset): _needs('monitoring_observed_before_received')
            if (report.author_organization_id not in covenant.permitted_verifier_ids
                    or report.author_action_id not in covenant.permitted_verifier_action_ids):
                raise ValueError('Monitoring report lacks covenant-permitted independent verifier')
            authorize(report.author_authority_ref, report.author_actor_id, report.author_function_ref,
                      report.author_organization_id, report.author_action_id, report.scope, report.observed_at)
            if len({fact.code for fact in report.facts}) != len(report.facts): raise ValueError('Report repeats an original contractual fact')
            reports.append(report)
            for finding in report.findings:
                dimension = read(finding.dimension_ref, BankMonitoringDimensionView, True)
                method = read(finding.method_ref, BankMonitoringMethodView, True)
                if (not same(dimension.method_ref, method.ref) or not same(method.arrangement_ref, arrangement.ref)
                        or dimension.ref.key() not in keys(method.dimension_refs)
                        or report.author_organization_id not in method.permitted_author_ids):
                    raise ValueError('Monitoring finding changes original authorized dimension/method')
                for row in (dimension, method):
                    if not row.effective_window.contains(report.observed_at): _needs('monitoring_method_valid_when_observed')
                evidence(finding.evidence_refs, True)
                if isinstance(finding.conclusion, Known):
                    if not finding.evidence_refs: _needs('sourced_monitoring_risk_finding')
                    conclusion = finding.conclusion.value
                elif finding.conclusion.state == 'unknown': conclusion = 'unknown'
                else: _needs('supported_monitoring_risk_finding')
                if not report.effective_window.contains(now): conclusion = 'unknown'
                result = {'dimension_ref': dimension.ref, 'conclusion': conclusion,
                          'evidence_refs': finding.evidence_refs, 'method_ref': method.ref}
                previous = dimensions.get(dimension.ref.key())
                if previous is not None and previous[0] == report.observed_at.offset and previous[1] != result:
                    _needs('explicit_reconciled_same_time_monitoring_finding')
                if previous is None or previous[0] < report.observed_at.offset:
                    dimensions[dimension.ref.key()] = (report.observed_at.offset, result)
        findings = [value[1] for value in dimensions.values()]
        notices = []
        for ref in action_input.notice_refs:
            notice = read(ref, BankMonitoringNoticeView, True)
            covenant = covenants.get(notice.covenant_ref.key())
            if (covenant is None or not same(notice.arrangement_ref, arrangement.ref)
                    or not same(notice.terms_ref, covenant.terms_ref) or notice.lender_id != lender
                    or notice.borrower_id != arrangement.borrower_id
                    or not scope_covers(covenant.scope, notice.affected_scope)):
                raise ValueError('Monitoring notice changes original parties, covenant, terms or scope')
            if notice.delivery == 'verified_served':
                if notice.served_at is None or not notice.delivery_evidence_refs: _needs('original_verified_notice_delivery')
                clock(notice.served_at)
                if notice.served_at.offset > min(now.offset, notice.available_at.offset): _needs('notice_served_before_received')
                if notice.remedy_deadline is not None:
                    clock(notice.remedy_deadline)
                    if notice.remedy_deadline.offset < notice.served_at.offset:
                        raise ValueError('Notice remedy deadline precedes original verified service')
                evidence(notice.delivery_evidence_refs, True, True)
            notices.append(notice)
        if profile.choice == 'continue': return completed('continue')
        if profile.choice == 'request_evidence':
            if not profile.requirement_refs: _needs('explicit_original_monitoring_requirements')
            keys(profile.requirement_refs)
            for ref in profile.requirement_refs:
                requirement = read(ref, BankMonitoringRequirementView)
                covenant = covenants.get(requirement.covenant_ref.key())
                if (covenant is None or not same(requirement.arrangement_ref, arrangement.ref)
                        or ref.key() not in keys(covenant.requirement_refs)
                        or requirement.responsible_id not in {arrangement.borrower_id, *covenant.permitted_verifier_ids}):
                    raise ValueError('Monitoring request invents a requirement or an unauthorized responsible party')
                if not covenant.effective_window.contains(now) or not same(covenant.terms_ref, arrangement.terms_ref):
                    _needs('currently_applicable_monitoring_information_requirement')
            return completed('request_evidence', requirement_refs=profile.requirement_refs)
        if profile.target_covenant_ref is None: _needs('explicit_original_covenant_for_measure')
        covenant = covenants.get(profile.target_covenant_ref.key())
        if covenant is None: raise ValueError('Measure uses a covenant outside the original input')
        if not same(covenant.terms_ref, arrangement.terms_ref) or not covenant.effective_window.contains(now):
            _needs('currently_effective_original_covenant_for_measure')
        if not scope_covers(covenant.scope, profile.affected_scope): raise ValueError('Measure widens original covenant scope')
        gates = [gate for gate in covenant.gates if gate.choice == profile.choice]
        if not gates: _needs('original_contractual_permission_for_monitoring_measure')
        gate = gates[0]
        if len(set(gate.fact_codes)) != len(gate.fact_codes): raise ValueError('Measure gate repeats a contractual condition')
        relevant = [notice for notice in notices if same(notice.covenant_ref, covenant.ref)
                    and notice.status == 'active' and notice.affected_scope == profile.affected_scope]
        unsettled = [notice.ref for notice in relevant if notice.delivery != 'verified_served']
        if unsettled: return pending(unsettled, 'query_original_notice_delivery_before_new_measure')
        if profile.choice in {'issue_notice', 'restrict_scope'}:
            existing = [notice.ref for notice in relevant if notice.choice == profile.choice]
            if existing: return pending(existing, 'query_existing_original_monitoring_measure_without_duplicate')
        if profile.choice == 'release_restriction' and not any(notice.choice == 'restrict_scope' for notice in relevant):
            _needs('original_active_scoped_restriction_to_release')
        if gate.prior_notice_required or gate.remedy_window_must_expire:
            prior = [notice for notice in relevant if notice.choice == 'issue_notice']
            if not prior: _needs('original_served_contractual_notice_before_measure')
            if gate.remedy_window_must_expire:
                for notice in prior:
                    if notice.remedy_deadline is None: _needs('original_contractual_remedy_deadline')
                    clock(notice.remedy_deadline)
                    if notice.remedy_deadline.offset >= now.offset: _needs('expired_original_contractual_remedy_window')
        basis = {}
        for code in gate.fact_codes:
            candidates = [report for report in reports if same(report.covenant_ref, covenant.ref)
                          and report.effective_window.contains(now) and scope_covers(report.scope, profile.affected_scope)
                          and any(fact.code == code for fact in report.facts)]
            if not candidates: _needs(f'current_verified_monitoring_fact:{code}')
            latest = max(report.observed_at.offset for report in candidates)
            candidates = [report for report in candidates if report.observed_at.offset == latest]
            for report in candidates:
                fact = next(fact for fact in report.facts if fact.code == code)
                if (fact.nature != 'verified' or not isinstance(fact.satisfied, Known)
                        or not fact.satisfied.value or not fact.evidence_refs):
                    _needs(f'contractual_monitoring_gate_not_verified:{code}', fact.evidence_refs)
                evidence(fact.evidence_refs, observed=True)
                for ref in fact.evidence_refs: basis[ref.key()] = ref
        return completed(profile.choice, covenant_ref=covenant.ref, affected_scope=profile.affected_scope,
                         basis_refs=list(basis.values()))
    except ObservationGap as gap:
        reading.recheck(); return gap.result
