"""OWN-A12 decides acceptance, defects and settlement without recording payment."""
from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.owner_closeout_objects import (
    OwnerCloseoutOrganizationView, OwnerCloseoutCaseView, OwnerCloseoutProjectView,
    OwnerCloseoutStateView, OwnerCloseoutProfileView, OwnerCloseoutContractView,
    OwnerCloseoutProcedureView, OwnerHandoverSubmissionView, OwnerCloseoutPermitView,
    OwnerSettlementProposalView, OwnerCloseoutComponentView, OwnerSettlementAssessmentView,
    OwnerActualSettlementComponentView, OwnerRetentionRuleView, OwnerRetentionConditionView,
    OwnerCloseoutDecisionView, ContractorHandoverRequestView, ContractorAsBuiltView,
    ContractorAsBuiltDesignView, ContractorAsBuiltBatchView, ContractorCloseoutVerificationView,
    ContractorCloseoutMethodView, ContractorCloseoutRequirementView, ContractorCloseoutIssueView,
    ContractorContinuingResponsibilityView, ContractorVisibleDefectView,
    ContractorInspectionEvidenceView, ContractorWorkRecordView, OwnerPaymentObligationView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.contracts.service_objects import ServiceWorkScopeView
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def decide_closeout(context, action_input, reading):
    now, owner, scope = context.business_time, reading.organization_id, context.scope

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('owner-closeout-clock-alignment')

    def evidence(refs):
        keys(refs)
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('owner-closeout-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)

    def read(ref, schema, historic=False, linked=False):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported('owner-closeout-projection:' + ref.kind)
        if hasattr(row, 'scope') and not linked and not scope_covers(scope, row.scope):
            raise ValueError('Owner closeout expands authorized original scope')
        evidence(getattr(row, 'evidence_refs', []))
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_original_owner_closeout_source', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now): _needs('current_original_owner_closeout_source', [ref])
        return row

    def true(value): return isinstance(value, Known) and value.value is True

    def overlaps(left, right):
        if left.kind != right.kind or (left.ref.kind, left.ref.id) != (right.ref.kind, right.ref.id):
            return False
        left_refs = {key[:2] for key in keys(left.coverage_refs)}
        right_refs = {key[:2] for key in keys(right.coverage_refs)}
        # Revisions do not erase an unresolved issue on the same physical work.
        # Preserve the existing anchor-only containment behavior for empty sets.
        return not left_refs or not right_refs or bool(left_refs & right_refs)

    def authorize(ref, actor, function, organization, action, at, target):
        grant = read(ref, Authorization, historic=True, linked=True)
        assignment = read(function, RoleAssignment, historic=True, linked=True)
        roles = {'OWN':'Owner', 'CONTRACTOR':'Contractor', 'QS':'QS', 'ENGINEER':'Engineer',
                 'ARCHITECT':'Architect', 'GOV':'Government', 'BANK':'Bank', 'SUPPLIER':'Supplier'}
        if (grant.actor_id != actor or grant.function_ref != function or grant.organization_id != organization
                or assignment.role != roles.get(action.split('-')[0]) or action not in grant.action_ids
                or not any(scope_covers(s, target) for s in grant.scopes)):
            raise ValueError('Closeout substitutes original author/party/function/action/scope authority')
        clock(at); clock(grant.validity.start)
        if not grant.validity.contains(at): _needs('original_owner_closeout_authority_at_execution', [ref])
        evidence(grant.basis_refs + assignment.basis_refs)
        return grant

    def author(row):
        clock(row.authored_at)
        if row.authored_at.offset > row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Closeout source precedes its original authorized author execution')
        return authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
                         row.author_organization_id, row.author_action_id, row.authored_at, row.scope)

    def status(row, code):
        if row.status == 'failed':
            raise ObservationGap({'kind':'technical_error', 'error':{'kind':'unrecorded',
                'correlation_id':context.operation_id, 'code':code}, 'retryability':'unknown'})
        if row.status == 'unsupported': _unsupported(code)
        if row.status != 'ok': _needs(code, [row.ref])

    def original_sources(refs, grant, at):
        if not refs or not keys(refs) <= keys(grant.readable_refs):
            raise ValueError('Closeout assessment omits original source read rights')
        for ref in refs:
            row = reading.resolve(ref)
            if hasattr(row, 'available_at'):
                clock(row.available_at)
                if row.available_at.offset > at.offset:
                    raise ValueError('Closeout assessment precedes its original sources')

    def observed_defect(defect):
        work = read(defect.work_record_ref, ContractorWorkRecordView, historic=True, linked=True)
        observed = read(defect.observation_ref, ContractorInspectionEvidenceView, historic=True, linked=True)
        author(observed); clock(observed.observed_at)
        if (defect.physical_work_key != work.physical_work_key
                or observed.physical_work_key != work.physical_work_key or observed.work_record_ref != work.ref
                or observed.kind != 'actual_observation' or defect.ref.key() not in keys(observed.defect_refs)
                or observed.observed_at.offset > observed.authored_at.offset
                or not scope_covers(work.scope, observed.scope) or not scope_covers(observed.scope, defect.scope)):
            raise ValueError('Closeout defect changes original actual observation, time or physical scope')
        if any(reading.resolve(ref).basis_kind != 'observed' for ref in observed.evidence_refs):
            _needs('actual_observed_owner_closeout_defect_basis', [observed.ref])

    def complete(**fields):
        reading.recheck()
        return {'kind':'completed', 'payload':{'choice':profile.choice, **fields, 'note':profile.note +
            ' Decision request only. Engineering acceptance, use permit, asset transfer, defect duties, final payable and actual clearance are separate. Remaining issues, downstream obligations and bank debt survive; retention release changes due/restriction only, payment remains OWN-A06. Partial acceptance does not imply whole-route availability or revenue.'}}

    try:
        if action_input.scope_ref != scope: raise ValueError('Owner closeout changes invocation scope')
        anchor = read(scope.ref, (OwnerCloseoutOrganizationView, OwnerCloseoutCaseView, OwnerCloseoutProjectView), linked=True)
        state = read(anchor.closeout_state_ref, OwnerCloseoutStateView)
        if state.organization_id != owner or state.scope != scope:
            raise ValueError('Closeout snapshot belongs to another original owner or scope')
        clock(state.as_of)
        if state.as_of != now or state.coverage != 'complete': _needs('complete_current_owner_closeout_snapshot')
        for field in ('handover_refs','verification_refs','permit_refs','defect_refs','settlement_refs'):
            if keys(getattr(action_input, field)) != keys(getattr(state, field)):
                _needs('complete_original_owner_closeout_' + field)
        profile = read(state.decision_profile_ref, OwnerCloseoutProfileView)
        if (profile.state_ref != state.ref or profile.scope != scope or profile.organization_id != owner
                or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
                or profile.authority_ref not in context.authorization_refs or profile.contract_ref.key() not in keys(state.contract_refs)):
            raise ValueError('Closeout choice replaces original owner, actor, state, contract or authority')
        authorize(profile.authority_ref, context.actor_id, context.function_ref, owner, 'OWN-A12', now, scope)
        contract = read(profile.contract_ref, OwnerCloseoutContractView, linked=True); clock(contract.as_of)
        if contract.owner_id != owner or not scope_covers(scope, contract.scope):
            raise ValueError('Closeout contract leaves original owner scope')
        if contract.coverage != 'complete' or contract.as_of != now: _needs('complete_current_owner_contract_closeout')
        for field in ('handover_refs','settlement_refs','defect_refs'):
            if not keys(getattr(contract, field)) <= keys(getattr(state, field)):
                raise ValueError('Owner snapshot omits original contract closeout history')
        procedure = read(contract.procedure_ref, OwnerCloseoutProcedureView, linked=True); author(procedure)
        if (procedure.contract_ref != contract.ref or procedure.author_organization_id != owner
                or profile.choice not in procedure.permitted_choices or not true(procedure.permitted) or not procedure.recipient_ids):
            _needs('original_owner_contract_closeout_permission')
        evidence(profile.basis_refs)

        obligations = {}
        parties = {owner, contract.contractor_id}
        for ref in state.contract_refs:
            if ref.key() == contract.ref.key(): continue
            related = read(ref, OwnerCloseoutContractView, linked=True)
            if related.owner_id != owner or not scope_covers(scope, related.scope):
                raise ValueError('Closeout state substitutes another owner contract')
            parties.add(related.contractor_id)
        for ref in state.obligation_refs:
            row = read(ref, OwnerPaymentObligationView, linked=True); clock(row.as_of)
            if row.debtor_id not in parties or not (scope_covers(scope, row.origin_scope) or scope_covers(row.origin_scope, scope)):
                raise ValueError('Closeout substitutes original owner debt or liability scope')
            if row.as_of != now: _needs('current_original_remaining_owner_obligations', [ref])
            obligations[ref.key()] = row
        keys(state.obligation_refs)
        responsibilities = {}
        for ref in state.responsibility_refs:
            row = read(ref, ContractorContinuingResponsibilityView, linked=True)
            if (row.contract_ref.key() not in keys(state.contract_refs) or row.organization_id not in parties
                    or not keys(row.obligation_refs) <= set(obligations) or not keys(row.defect_refs) <= keys(state.defect_refs)):
                raise ValueError('Closeout substitutes or omits established remaining responsibilities')
            responsibilities[ref.key()] = row
        if not keys(contract.responsibility_refs) <= set(responsibilities):
            raise ValueError('Contract responsibility history is incomplete')
        histories = set(); keys(state.decision_history_refs)
        for ref in state.decision_history_refs:
            previous = read(ref, OwnerCloseoutDecisionView, historic=True, linked=True); author(previous)
            if (previous.state_ref.kind != state.ref.kind or previous.state_ref.id != state.ref.id
                    or previous.contract_ref.key() not in keys(state.contract_refs) or previous.author_organization_id != owner):
                raise ValueError('Closeout history substitutes original state/contract/owner')
            business = (previous.contract_ref.key(), previous.business_key)
            if business in histories: raise ValueError('Closeout repeats original contract business identity')
            histories.add(business)
            if business == (contract.ref.key(), profile.business_key):
                original = read(previous.profile_ref, OwnerCloseoutProfileView, historic=True, linked=True)
                metadata = {'ref','state_ref','available_at','effective_window'}
                if (original.state_ref != previous.state_ref or original.contract_ref != previous.contract_ref
                        or original.organization_id != previous.author_organization_id or original.scope != previous.scope
                        or original.business_key != previous.business_key or original.choice != previous.choice
                        or previous.choice != profile.choice or previous.profile_sha256 != content_digest(original)
                        or original.model_dump(exclude=metadata) != profile.model_dump(exclude=metadata)):
                    raise ValueError('Closeout reuses original business identity for changed decision content')
                reading.recheck()
                return {'kind':'deferred', 'reason_code':'continue_original_owner_closeout_decision', 'resume_condition':{
                    'trigger':'dependency_change','object_refs':[previous.ref],'earliest_time':None,
                    'condition_code':'continue_original_owner_closeout_decision'}}

        issues = {}
        for ref in contract.issue_refs:
            row = read(ref, ContractorCloseoutIssueView, linked=True)
            if row.contract_ref != contract.ref or not keys(row.defect_refs) <= keys(contract.defect_refs) or not keys(row.component_refs) <= keys(contract.component_refs):
                raise ValueError('Closeout issue substitutes original contract/defect/settlement')
            if row.status != 'resolved': issues[ref.key()] = row
        keys(contract.issue_refs)

        if profile.choice == 'request_rectification':
            if not profile.defect_refs or not keys(profile.defect_refs) <= keys(contract.defect_refs):
                _needs('specific_original_visible_contract_defects')
            for ref in profile.defect_refs:
                defect = read(ref, ContractorVisibleDefectView)
                if defect.status == 'closed':
                    raise ValueError('Rectification omits original actually observed open physical defect')
                observed_defect(defect)
            return complete(defect_refs=profile.defect_refs)

        if profile.choice == 'accept_scope':
            if profile.handover_ref is None or profile.handover_ref.key() not in keys(contract.handover_refs) or profile.accepted_scope is None:
                _needs('original_handover_submission_and_specific_acceptance_scope')
            selected = profile.accepted_scope; target = selected.scope_ref
            if (not selected.basis_refs or not target.coverage_refs or not scope_covers(scope, target)
                    or not scope_covers(contract.scope, target) or not any(scope_covers(s, target) for s in procedure.allowed_acceptance_scopes)):
                raise ValueError('Acceptance lacks original concrete independently permitted contract scope')
            evidence(selected.basis_refs)
            submission = read(profile.handover_ref, OwnerHandoverSubmissionView, linked=True); author(submission)
            request = read(submission.request_ref, ContractorHandoverRequestView, historic=True, linked=True); author(request)
            if (submission.contract_ref != contract.ref or submission.author_organization_id != contract.contractor_id
                    or submission.author_action_id != 'CONTRACTOR-A11' or submission.status not in {'submitted','pending'}
                    or request.contract_ref != contract.ref or request.author_organization_id != contract.contractor_id
                    or request.status not in {'submitted','pending'} or keys(request.as_built_refs) != keys(submission.as_built_refs)
                    or not scope_covers(submission.scope, target) or not true(submission.independent_use)):
                _needs('original_received_handover_for_independently_supported_scope')
            if keys(profile.remaining_issue_refs) != set(issues) or not keys(submission.issue_refs) <= keys(contract.issue_refs):
                raise ValueError('Acceptance must retain all original unresolved contract issues')
            open_defects = set()
            for ref in contract.defect_refs:
                defect = read(ref, ContractorVisibleDefectView, linked=True)
                if defect.status != 'closed' and overlaps(defect.scope, target):
                    observed_defect(defect)
                    open_defects.add(ref.key())
            if (open_defects or any(overlaps(target, issue.scope) for issue in issues.values())) and not procedure.allow_conditional_acceptance:
                _needs('original_permission_for_acceptance_with_remaining_issues')
            retained_defects = {ref.key() for issue in issues.values() for ref in issue.defect_refs}
            if not open_defects <= retained_defects:
                _needs('explicit_remaining_issue_for_original_open_defect')
            configs = {}; covered = set(); physical = set(); configuration_keys = set()
            for ref in submission.as_built_refs:
                row = read(ref, ContractorAsBuiltView, linked=True); author(row)
                if not scope_covers(target, row.scope): continue
                if (row.contract_ref != contract.ref or row.author_organization_id != contract.contractor_id or not true(row.actual)
                        or row.configuration_key in configuration_keys or not row.work_record_refs or not row.scope.coverage_refs):
                    raise ValueError('Acceptance lacks unique original actual configuration')
                configuration_keys.add(row.configuration_key);keys(row.work_record_refs);keys(row.product_batch_refs)
                design = read(row.design_ref, ContractorAsBuiltDesignView, historic=True, linked=True)
                if design.contract_ref != contract.ref or not scope_covers(design.scope, row.scope):
                    raise ValueError('Accepted configuration substitutes original applicable design')
                for batch_ref in row.product_batch_refs:
                    batch = read(batch_ref, ContractorAsBuiltBatchView, historic=True, linked=True)
                    if batch.contract_ref != contract.ref or row.ref.key() not in keys(batch.configuration_refs):
                        raise ValueError('Accepted configuration substitutes actual installed product version')
                for work_ref in row.work_record_refs:
                    work = read(work_ref, ContractorWorkRecordView, historic=True, linked=True)
                    if work.physical_work_key in physical or not scope_covers(row.scope, work.scope):
                        raise ValueError('Acceptance aliases original physical work or scope')
                    evidence([work.net_quantity.basis_ref]);physical.add(work.physical_work_key)
                    if decimal_fraction(work.net_quantity.value) <= 0: _needs('actual_net_work_for_accepted_configuration', [work_ref])
                configs[ref.key()] = row; covered.update(keys(row.scope.coverage_refs))
            keys(submission.as_built_refs)
            if not configs or covered != keys(target.coverage_refs): _needs('actual_configuration_for_exact_accepted_scope')
            for ref in target.coverage_refs:
                work_scope = read(ref, ServiceWorkScopeView)
                if work_scope.parent_ref.key() != target.ref.key(): raise ValueError('Accepted work scope belongs to another parent')
            requirements = keys(submission.requirement_refs)
            if not keys(selected.condition_refs) <= requirements: raise ValueError('Acceptance invents required checks')
            checked = set()
            for ref in state.verification_refs:
                verification = read(ref, ContractorCloseoutVerificationView, linked=True)
                if verification.as_built_ref.key() not in configs or verification.requirement_ref.key() not in requirements: continue
                grant = author(verification);status(verification,'original_owner_handover_verification')
                config = configs[verification.as_built_ref.key()]
                method = read(verification.method_ref, ContractorCloseoutMethodView, linked=True)
                original_sources([verification.as_built_ref, verification.requirement_ref, verification.method_ref],
                    grant, verification.authored_at)
                if (verification.contract_ref != contract.ref or verification.as_built_sha256 != config.content_sha256
                        or verification.author_organization_id == contract.contractor_id
                        or verification.author_action_id not in method.allowed_author_action_ids
                        or verification.author_action_id.split('-')[0] not in {'ENGINEER','ARCHITECT','GOV'}
                        or verification.requirement_ref.key() not in keys(method.requirement_refs) or not true(method.supported) or not true(verification.passed)):
                    _needs('independent_original_version_bound_handover_checks', [ref])
                checked.add((config.ref.key(),verification.requirement_ref.key()))
            required = set()
            for ref in submission.requirement_refs:
                requirement = read(ref, ContractorCloseoutRequirementView, linked=True)
                if requirement.contract_ref != contract.ref: raise ValueError('Handover requirement changes original contract')
                required.update((r.key(),ref.key()) for r in requirement.as_built_refs if r.key() in configs)
            if not required or not required <= checked or set(configs) != {r for r,_ in required}:
                _needs('all_required_original_checks_for_selected_handover_scope')
            if not keys(submission.required_permit_refs) <= keys(state.permit_refs): _needs('original_required_handover_permits')
            for ref in submission.required_permit_refs:
                permit = read(ref, OwnerCloseoutPermitView, linked=True);author(permit)
                if (permit.contract_ref != contract.ref or permit.author_action_id.split('-')[0] != 'GOV'
                        or permit.status != 'issued' or not scope_covers(permit.authorized_scope, target)):
                    _needs('actual_current_scope_bound_handover_permit', [ref])
            return complete(handover_ref=submission.ref,accepted_scope=selected.model_dump(mode='python'),remaining_issue_refs=profile.remaining_issue_refs)

        if not profile.component_refs or not profile.basis_refs or not keys(profile.component_refs) <= keys(contract.component_refs):
            _needs('specific_original_settlement_components_and_basis')
        proposals = {}; keys(contract.settlement_refs)
        for ref in contract.settlement_refs:
            proposal = read(ref, OwnerSettlementProposalView, linked=True);author(proposal)
            if (proposal.contract_ref != contract.ref or proposal.author_organization_id not in {owner,contract.contractor_id}
                    or not keys(proposal.component_refs) <= keys(contract.component_refs)):
                raise ValueError('Settlement proposal substitutes original parties/contract/components')
            if proposal.status != 'withdrawn': proposals[ref.key()] = proposal
        if profile.choice == 'agree_settlement' and not procedure.allow_partial_settlement and keys(profile.component_refs) != keys(contract.component_refs):
            _needs('original_permission_for_partial_final_settlement')
        physical_components = set(); actual_components = set()
        for ref in profile.component_refs:
            component = read(ref, OwnerCloseoutComponentView, linked=True);author(component)
            if (component.contract_ref != contract.ref or component.proposal_ref.key() not in proposals
                    or component.ref.key() not in keys(proposals[component.proposal_ref.key()].component_refs)
                    or component.debtor_id != owner or component.payee_id != contract.contractor_id
                    or component.physical_component_key in physical_components):
                raise ValueError('Settlement repeats original physical component or changes liable parties')
            physical_components.add(component.physical_component_key)
            if component.existing_component_ref is not None:
                actual = read(component.existing_component_ref, OwnerActualSettlementComponentView, linked=True);clock(actual.as_of)
                if (actual.original_component_ref != component.ref or actual.obligation_ref.key() not in obligations
                        or actual.debtor_id != owner or actual.payee_id != component.payee_id or actual.as_of != now
                        or (actual.original_component_ref.kind,actual.original_component_ref.id) in actual_components):
                    raise ValueError('Settlement aliases or substitutes existing original payment component')
                obligation = obligations[actual.obligation_ref.key()]
                if actual.original_component_ref.key() not in keys(obligation.component_refs):
                    raise ValueError('Settlement component is not in original obligation ledger')
                if (actual.debtor_id != obligation.debtor_id or actual.payee_id != obligation.payee_id
                        or actual.source_ref != obligation.source_ref or actual.debt_ref != obligation.debt_ref):
                    raise ValueError('Actual settlement component changes original obligation parties, funding source or debt')
                actual_components.add((actual.original_component_ref.kind,actual.original_component_ref.id))
            if profile.choice == 'dispute_settlement':
                if not any(component.ref.key() in keys(issues[k].component_refs) for k in keys(component.issue_refs) & set(issues)):
                    _needs('specific_original_unresolved_settlement_issue', [ref])
                continue
            if not isinstance(component.proposed_amount, Known): _needs('known_original_settlement_amount', [ref])
            amount = component.proposed_amount.value;evidence([amount.basis_ref])
            if amount.currency != contract.currency or decimal_fraction(amount.value) < 0:
                raise ValueError('Settlement amount changes original currency or becomes negative')
            supported = False;keys(component.assessment_refs)
            for assessment_ref in component.assessment_refs:
                assessment = read(assessment_ref, OwnerSettlementAssessmentView, linked=True);grant = author(assessment)
                status(assessment,'original_independent_settlement_assessment')
                if (assessment.component_ref != component.ref or assessment.component_sha256 != content_digest(component)
                        or assessment.author_organization_id == contract.contractor_id or assessment.author_action_id.split('-')[0] != 'QS'
                        or not keys(assessment.source_refs) <= keys(grant.readable_refs)
                        or component.ref.key() not in keys(assessment.source_refs)):
                    raise ValueError('Settlement assessment replaces original component/version/independent read rights')
                original_sources(assessment.source_refs,grant,assessment.authored_at)
                if not true(assessment.supported) or assessment.amount != component.proposed_amount:
                    _needs('independent_supported_original_component_amount', [assessment_ref])
                supported = True
            if not supported: _needs('original_independent_final_component_verification', [ref])
            if profile.choice == 'release_retention':
                if component.kind != 'retention' or component.retention_rule_ref is None or component.existing_component_ref is None:
                    _needs('existing_original_retention_and_release_terms', [ref])
                balances = [actual.actual_due,actual.actual_cash_paid,actual.actual_offset]
                if not all(isinstance(value,Known) for value in balances):
                    _needs('current_actual_remaining_original_retention_amount',[actual.ref])
                for value in balances:
                    evidence([value.value.basis_ref])
                    if value.value.currency != contract.currency or decimal_fraction(value.value.value) < 0:
                        raise ValueError('Retention release changes original currency or actual balances')
                remaining = decimal_fraction(actual.actual_due.value.value) - decimal_fraction(actual.actual_cash_paid.value.value) - decimal_fraction(actual.actual_offset.value.value)
                if remaining < 0 or decimal_fraction(amount.value) > remaining:
                    raise ValueError('Retention release exceeds original remaining established component')
                if remaining == 0: _needs('original_unreleased_retention_balance',[actual.ref])
                rule = read(component.retention_rule_ref, OwnerRetentionRuleView, linked=True);author(rule);clock(rule.due_at)
                if rule.contract_ref != contract.ref or rule.component_ref != component.ref or rule.author_organization_id != owner:
                    raise ValueError('Retention release terms replace original contract/component/owner authority')
                if now.offset < rule.due_at.offset or not true(rule.permitted): _needs('original_retention_due_and_release_permission', [rule.ref])
                if not keys(rule.retained_responsibility_refs) <= set(responsibilities):
                    raise ValueError('Retention release drops original continuing duties')
                keys(rule.condition_refs)
                for condition_ref in rule.condition_refs:
                    condition = read(condition_ref, OwnerRetentionConditionView, linked=True);grant = author(condition)
                    status(condition,'original_retention_release_conditions')
                    if (condition.rule_ref != rule.ref or not condition.source_refs or not keys(condition.source_refs) <= keys(grant.readable_refs)
                            or condition.author_organization_id == contract.contractor_id):
                        raise ValueError('Retention condition lacks independent original sources/authority')
                    original_sources(condition.source_refs,grant,condition.authored_at)
                    if not true(condition.satisfied): _needs('actual_original_retention_release_condition', [condition.ref])
        return complete(component_refs=profile.component_refs,basis_refs=profile.basis_refs)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
