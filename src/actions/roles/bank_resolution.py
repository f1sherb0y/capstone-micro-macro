"""BANK-A10 resolution requests never erase debt or manufacture recovery cash."""
from src.actions.contracts.common import EvidenceRecord, Known, TimeWindow
from src.actions.contracts.bank_resolution_objects import (
    BankResolutionArrangementView, BankResolutionObligationView, BankResolutionProfileView,
    BankResolutionRuleView, BankDifficultyView, BankDefaultNoticeView, BankSecurityRightView,
    BankEnforcementRightView, BankEnforcementMechanismView, BankRemedyProposalView,
    BankResolutionRequirementView, BankRestructureProposalView, BankRestructureAcceptanceView,
    BankWriteoffPolicyView, BankResolutionExecutionView, BankResolutionTermSourceView,
    BankDebtExecutionView, BankDebtReceiptView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def resolve_debt(context, action_input, reading):
    now,bank,scope=context.business_time,reading.organization_id,context.scope

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def clock(point):
        if point.clock_ref!=now.clock_ref: _unsupported('bank-resolution-clock-alignment')

    def evidence(refs,at=None):
        for ref in refs:
            row=reading.resolve(ref)
            if not isinstance(row,EvidenceRecord): _unsupported('bank-resolution-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if at is not None and not row.effective_window.contains(at):
                    _needs('original_bank_resolution_evidence_at_execution',[ref])

    def read(ref,schema,historic=False,linked=False):
        row=reading.resolve(ref)
        if not isinstance(row,schema): _unsupported('bank-resolution-projection:'+ref.kind)
        if hasattr(row,'scope') and not linked and not scope_covers(scope,row.scope):
            raise ValueError('Resolution source expands original authorized scope')
        evidence(getattr(row,'evidence_refs',[]))
        if hasattr(row,'available_at'):
            clock(row.available_at)
            if row.available_at.offset>now.offset: _needs('received_original_bank_resolution_source',[ref])
        if hasattr(row,'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now): _needs('current_original_bank_resolution_source',[ref])
        return row

    def true(value): return isinstance(value,Known) and value.value is True

    def authorize(ref,actor,function,organization,action,at,target):
        grant=read(ref,Authorization,historic=True,linked=True);assignment=read(function,RoleAssignment,historic=True,linked=True)
        roles={'BANK':'Bank','OWN':'Owner','CONTRACTOR':'Contractor','SUPPLIER':'Supplier',
               'QS':'QS','ENGINEER':'Engineer','ARCHITECT':'Architect','GOV':'Government'}
        if (grant.actor_id!=actor or grant.function_ref!=function or grant.organization_id!=organization
                or assignment.role!=roles.get(action.split('-')[0]) or action not in grant.action_ids
                or not any(scope_covers(s,target) for s in grant.scopes)):
            raise ValueError('Resolution substitutes original author/function/party/action/scope authority')
        clock(at);clock(grant.validity.start)
        if not grant.validity.contains(at): _needs('original_bank_resolution_authority_at_execution',[ref])
        evidence(grant.basis_refs+assignment.basis_refs,at=at)
        return grant

    def author(row):
        clock(row.authored_at)
        if row.authored_at.offset>row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Resolution source precedes original actual author execution')
        evidence(row.evidence_refs,at=row.authored_at)
        return authorize(row.author_authority_ref,row.author_actor_id,row.author_function_ref,
            row.author_organization_id,row.author_action_id,row.authored_at,row.scope)

    def amount(value):
        evidence([value.basis_ref]);number=decimal_fraction(value.value)
        if value.currency!=arrangement.currency or number<0:
            raise ValueError('Debt resolution changes original currency or uses negative amount')
        return number

    def remaining(row):
        values=[row.actual_due,row.actual_paid,row.actual_offset]
        if not all(isinstance(v,Known) for v in values): _needs('actual_original_remaining_resolution_debt',[row.ref])
        balance=amount(values[0].value)-amount(values[1].value)-amount(values[2].value)
        if balance<0: raise ValueError('Original paid/offset debt exceeds actual original due')
        return balance

    def difficulty(ref):
        row=read(ref,BankDifficultyView,linked=True);grant=author(row)
        if (row.arrangement_ref!=arrangement.ref or not row.source_refs or not keys(row.source_refs)<=keys(grant.readable_refs)
                or not keys(row.obligation_refs)<=set(obligations)):
            raise ValueError('Resolution difficulty lacks original arrangement/source read rights')
        if row.status=='failed': raise ObservationGap({'kind':'technical_error','error':{'kind':'unrecorded','correlation_id':context.operation_id,'code':'original-resolution-assessment-failed'},'retryability':'unknown'})
        if row.status=='unsupported': _unsupported('original-resolution-assessment-domain')
        if row.status!='ok' or not true(row.supported): _needs('supported_original_debt_difficulty_or_breach',[row.ref])
        for source_ref in row.source_refs:
            source=reading.resolve(source_ref)
            if hasattr(source,'available_at'):
                clock(source.available_at)
                if source.available_at.offset>row.authored_at.offset: raise ValueError('Difficulty assessment precedes original source availability')
        return row

    def wait(ref):
        reading.recheck()
        return {'kind':'deferred','reason_code':'query_original_resolution_or_cash_execution','resume_condition':{
            'trigger':'dependency_change','object_refs':[ref],'earliest_time':None,'condition_code':'query_original_resolution_or_cash_execution'}}

    def complete(**fields):
        reading.recheck()
        return {'kind':'completed','payload':{'choice':profile.choice,'basis_refs':profile.basis_refs,**fields,
            'note':profile.note+' Resolution request only. Existing debt maturity survives a proposed remedy/restructure; accepted changes require atomic original debt carry and valid party consents. Enforcement, recovery and actual cash are separate. Accounting writeoff is not debt forgiveness and needs no collateral execution right; project termination does not clear the borrower debt.'}}

    try:
        arrangement=read(action_input.arrangement_ref,BankResolutionArrangementView,linked=True)
        profile=read(action_input.resolution_profile_ref,BankResolutionProfileView)
        if (arrangement.lender_id!=bank or profile.organization_id!=bank or profile.arrangement_ref!=arrangement.ref
                or profile.actor_id!=context.actor_id or profile.function_ref!=context.function_ref or profile.scope!=scope
                or profile.authority_ref!=action_input.authority_ref or profile.authority_ref not in context.authorization_refs
                or not scope_covers(arrangement.scope,scope)):
            raise ValueError('Resolution replaces original bank/arrangement/actor/authority/scope')
        authorize(action_input.authority_ref,context.actor_id,context.function_ref,bank,'BANK-A10',now,scope)
        clock(arrangement.as_of)
        if arrangement.as_of!=now or arrangement.coverage!='complete': _needs('complete_current_original_debt_resolution_history')
        for supplied,original in [('notice_refs','notice_refs'),('unpaid_refs','obligation_refs'),('security_refs','security_refs'),('remedy_refs','remedy_refs')]:
            if keys(getattr(action_input,supplied))!=keys(getattr(arrangement,original)): _needs('complete_original_resolution_'+supplied)
        if not profile.basis_refs: _needs('specific_original_resolution_basis')
        evidence(profile.basis_refs);keys(profile.basis_refs)
        if not scope_covers(scope,profile.affected_scope): raise ValueError('Resolution decision expands original affected scope')
        rule=read(arrangement.rule_ref,BankResolutionRuleView,linked=True);author(rule)
        if rule.arrangement_ref!=arrangement.ref or rule.author_organization_id!=bank or profile.choice not in rule.permitted_choices or not true(rule.permitted):
            _needs('original_contractual_resolution_choice_permission')
        obligations={}
        for ref in arrangement.obligation_refs:
            row=read(ref,BankResolutionObligationView,linked=True);clock(row.as_of);clock(row.due_at)
            if row.arrangement_ref!=arrangement.ref or row.debtor_id!=arrangement.borrower_id or row.payee_id!=bank or row.as_of!=now:
                _needs('actual_current_original_borrower_resolution_obligations',[ref])
            obligations[ref.key()]=row
        keys(arrangement.payment_execution_refs)
        payment_commands=set();payment_business=set();receipt_events=set()
        for ref in arrangement.payment_execution_refs:
            execution=read(ref,BankDebtExecutionView,historic=True,linked=True)
            if execution.arrangement_ref!=arrangement.ref or execution.lender_id!=bank or execution.borrower_id!=arrangement.borrower_id:
                raise ValueError('Resolution substitutes original funds execution parties/arrangement')
            if execution.command_id in payment_commands or execution.business_key in payment_business:
                raise ValueError('Resolution repeats an original funds execution command/business key')
            payment_commands.add(execution.command_id);payment_business.add(execution.business_key)
            if execution.status in {'unknown','pending','partial'}: return wait(execution.ref)
            if execution.status=='succeeded' and not execution.receipt_refs:
                _needs('original_verified_successful_funds_execution_receipt',[execution.ref])
            keys(execution.receipt_refs)
            for receipt_ref in execution.receipt_refs:
                receipt=read(receipt_ref,BankDebtReceiptView,historic=True,linked=True)
                if (receipt.execution_ref!=execution.ref or receipt.arrangement_ref!=arrangement.ref or receipt.command_id!=execution.command_id
                        or receipt.business_key!=execution.business_key or receipt.lender_id!=bank or receipt.borrower_id!=arrangement.borrower_id
                        or receipt.event_id in receipt_events):
                    raise ValueError('Resolution substitutes original verified execution receipt')
                clock(receipt.effective_at);clock(receipt.verified_at)
                if not receipt.effective_at.offset<=receipt.verified_at.offset<=min(now.offset,receipt.available_at.offset):
                    _needs('verified_original_bank_resolution_receipt_effective_time',[receipt_ref])
                received=amount(receipt.amount)
                if received<=0: raise ValueError('Resolution requires positive original actual receipt amount')
                keys([effect.debt_component_ref for effect in receipt.principal_effects])
                if sum((amount(effect.amount) for effect in receipt.principal_effects),0)>received:
                    raise ValueError('Resolution receipt principal effects exceed original actual amount')
                receipt_events.add(receipt.event_id)
        business=set();keys(arrangement.resolution_execution_refs)
        for ref in arrangement.resolution_execution_refs:
            execution=read(ref,BankResolutionExecutionView,historic=True,linked=True)
            if execution.organization_id!=bank or execution.run_id!=context.run_id or execution.arrangement_ref.id!=arrangement.ref.id or execution.business_key in business:
                raise ValueError('Resolution history repeats original run/arrangement/business identity')
            business.add(execution.business_key)
            if execution.business_key==profile.business_key:
                original=read(execution.profile_ref,BankResolutionProfileView,historic=True,linked=True)
                excluded={'ref','arrangement_ref','available_at','effective_window'}
                if (original.arrangement_ref!=execution.arrangement_ref or original.organization_id!=execution.organization_id
                        or original.scope!=execution.scope or original.business_key!=execution.business_key
                        or execution.profile_sha256!=content_digest(original)
                        or original.model_dump(exclude=excluded)!=profile.model_dump(exclude=excluded)):
                    raise ValueError('Resolution changes original payload under existing business identity')
                return wait(execution.ref)
            if execution.status in {'unknown','pending'} and profile.choice in {'accept_restructure','enforce','accounting_writeoff'}: return wait(execution.ref)

        if profile.choice=='accounting_writeoff':
            if profile.writeoff_policy_ref is None: _needs('original_bank_accounting_writeoff_policy')
            policy=read(profile.writeoff_policy_ref,BankWriteoffPolicyView,linked=True);author(policy)
            if (policy.organization_id!=bank or policy.author_organization_id!=bank or arrangement.ref.key() not in keys(policy.arrangement_refs)
                    or not keys(policy.obligation_refs)<=set(obligations) or not policy.obligation_refs
                    or not true(policy.permitted) or not scope_covers(policy.scope,profile.affected_scope)):
                _needs('current_original_bank_accounting_writeoff_permission')
            return complete(scope_ref=profile.affected_scope,authority_ref=action_input.authority_ref,accounting_policy_ref=policy.ref)
        if profile.choice=='decline_remedy':
            if profile.declined_remedy_ref is None or profile.declined_remedy_ref.key() not in keys(arrangement.remedy_refs): _needs('received_original_remedy_proposal_to_decline')
            remedy=read(profile.declined_remedy_ref,BankRemedyProposalView,linked=True);author(remedy)
            if remedy.arrangement_ref!=arrangement.ref or remedy.author_organization_id!=arrangement.borrower_id or remedy.status not in {'received','pending'}:
                raise ValueError('Decline substitutes original received borrower remedy')
            return complete(proposal_ref=remedy.ref)
        if profile.choice in {'request_remedy','propose_restructure','accept_restructure'}:
            if profile.difficulty_ref is None: _needs('original_supported_difficulty_or_remedy_basis')
            difficulty(profile.difficulty_ref)
        if profile.choice=='request_remedy':
            if not profile.required_items or profile.response_window_ref is None: _needs('specific_original_remedy_items_and_response_window')
            if len({i.local_key for i in profile.required_items})!=len(profile.required_items): raise ValueError('Remedy repeats original local requirement identity')
            for item in profile.required_items:
                requirement=read(item.requirement_ref,BankResolutionRequirementView,linked=True);author(requirement)
                if (requirement.arrangement_ref!=arrangement.ref or requirement.responsible_id!=item.responsible_id
                        or not item.basis_refs or not scope_covers(profile.affected_scope,item.scope_ref)
                        or not scope_covers(requirement.scope,item.scope_ref) or not true(requirement.permitted)):
                    raise ValueError('Remedy request creates an unauthorized party requirement or scope')
                evidence(item.basis_refs)
            window=read(profile.response_window_ref,TimeWindow);clock(window.start);clock(window.end)
            if window.start.offset<now.offset: raise ValueError('New remedy response window begins in the past')
            return complete(required_items=[i.model_dump(mode='python') for i in profile.required_items],response_window_ref=profile.response_window_ref)
        if profile.choice in {'propose_restructure','accept_restructure'}:
            if profile.proposal_ref is None: _needs('original_itemized_restructure_proposal')
            proposal=read(profile.proposal_ref,BankRestructureProposalView,linked=True);author(proposal);clock(proposal.effective_at)
            if (proposal.arrangement_ref!=arrangement.ref or proposal.author_organization_id not in {bank,arrangement.borrower_id}
                    or proposal.status=='withdrawn' or not scope_covers(proposal.scope,profile.affected_scope)):
                raise ValueError('Restructure substitutes original loan/party/proposal')
            terms=proposal.revised_terms
            if (terms.borrower_id!=arrangement.borrower_id or terms.product_ref.key() not in keys(rule.allowed_product_refs)
                    or terms.pricing_ref.key() not in keys(rule.allowed_pricing_refs) or not keys(terms.fee_rule_refs)<=keys(rule.allowed_fee_refs)
                    or terms.repayment_rule_ref.key() not in keys(rule.allowed_repayment_refs) or amount(terms.principal_limit)>amount(rule.maximum_principal_limit)):
                raise ValueError('Revised loan terms leave original product/pricing/fee/repayment authority')
            for ref in [terms.product_ref,terms.purpose_ref,terms.pricing_ref,*terms.fee_rule_refs,terms.repayment_rule_ref]:
                source=read(ref,BankResolutionTermSourceView,linked=True)
                if source.arrangement_ref!=arrangement.ref or not true(source.permitted): _needs('original_permitted_restructure_terms_source',[ref])
            for ref in terms.condition_refs:
                condition=read(ref,BankResolutionRequirementView,linked=True);author(condition)
                if condition.arrangement_ref!=arrangement.ref or not true(condition.permitted): _needs('original_restructure_condition_permission',[ref])
                if profile.choice=='accept_restructure' and not true(condition.satisfied): _needs('actual_original_restructure_effectiveness_condition',[ref])
            tenor=read(terms.tenor_ref,TimeWindow);validity=read(terms.validity_ref,TimeWindow)
            for window in (tenor,validity): clock(window.start);clock(window.end)
            if not validity.contains(now) or not tenor.contains(proposal.effective_at): _needs('current_original_restructure_terms_validity')
            if keys([line.obligation_ref for line in proposal.carry_lines])!=set(obligations): raise ValueError('Restructure must carry every original loan obligation exactly once')
            for line in proposal.carry_lines:
                original=obligations[line.obligation_ref.key()]
                if line.obligation_sha256!=content_digest(original) or amount(line.old_remaining)!=remaining(original):
                    raise ValueError('Restructure carries stale or duplicated original debt balance')
                change=amount(line.adjustment_amount);old=amount(line.old_remaining);new=amount(line.carry_amount);evidence(line.basis_refs)
                expected=old+(change if line.adjustment_kind=='increase' else -change if line.adjustment_kind=='decrease' else 0)
                if new!=expected or line.adjustment_kind=='none' and change!=0 or change and not line.basis_refs:
                    raise ValueError('Debt carry creates unsupported balance change or fictional recovery')
            if profile.choice=='propose_restructure': return complete(revised_terms=terms.model_dump(mode='python'))
            parties=set();authors=set();keys(profile.acceptance_refs)
            for ref in profile.acceptance_refs:
                acceptance=read(ref,BankRestructureAcceptanceView,linked=True);acceptance_grant=author(acceptance)
                if (acceptance.proposal_ref!=proposal.ref or acceptance.proposal_sha256!=content_digest(proposal)
                        or acceptance.party_id!=acceptance.author_organization_id or acceptance.party_id in parties
                        or acceptance.author_actor_id in authors
                        or acceptance.party_id!=bank and acceptance.author_actor_id==context.actor_id
                        or not scope_covers(acceptance.scope,proposal.scope)
                        or proposal.ref.key() not in {r.key() for r in acceptance_grant.readable_refs}
                        or acceptance.authored_at.offset<proposal.authored_at.offset
                        or not true(acceptance.accepted) or acceptance.status!='active'):
                    raise ValueError('Restructure acceptance substitutes exact proposal or independent party consent')
                if not validity.contains(acceptance.authored_at):
                    _needs('original_restructure_terms_valid_at_party_acceptance',[ref])
                parties.add(acceptance.party_id);authors.add(acceptance.author_actor_id)
            if not {bank,arrangement.borrower_id,*rule.required_party_ids}<=parties: _needs('all_original_required_restructure_party_acceptances')
            return complete(proposal_ref=proposal.ref,acceptance_refs=profile.acceptance_refs)

        if profile.choice!='enforce' or not profile.enforcement_right_refs: _needs('specific_original_enforcement_rights')
        keys(profile.enforcement_right_refs)
        for ref in profile.enforcement_right_refs:
            right=read(ref,BankEnforcementRightView,linked=True);author(right)
            if right.security_ref.key() not in keys(arrangement.security_refs): raise ValueError('Enforcement invents original collateral')
            security=read(right.security_ref,BankSecurityRightView,linked=True);author(security)
            if (right.arrangement_ref!=arrangement.ref or right.author_organization_id not in {bank,security.author_organization_id}
                    or security.arrangement_ref!=arrangement.ref or security.holder_id!=bank
                    or not true(security.permitted) or not true(right.permitted) or not true(right.procedure_satisfied)
                    or not scope_covers(right.scope,profile.affected_scope)):
                _needs('original_valid_security_and_enforcement_scope_authority',[ref])
            procedure_assessment=difficulty(right.procedure_assessment_ref)
            if (procedure_assessment.kind!='contract_breach' or not scope_covers(procedure_assessment.scope,profile.affected_scope)
                    or right.ref.key() not in keys(procedure_assessment.source_refs)):
                _needs('original_verified_enforcement_procedure_and_breach',[ref])
            mechanism=read(right.mechanism_ref,BankEnforcementMechanismView,linked=True)
            if mechanism.mode=='uncovered' or not true(mechanism.supported): _unsupported('bank-legal-enforcement-mechanism-uncovered')
            if not mechanism.procedure_basis_refs: _needs('original_enforcement_procedure_basis')
            evidence(mechanism.procedure_basis_refs)
            if rule.require_notice_for_enforcement and not right.notice_refs: _needs('original_valid_enforcement_notices')
            if not keys(right.notice_refs)<=keys(arrangement.notice_refs): raise ValueError('Enforcement substitutes original notice history')
            if not right.notice_refs:
                if profile.difficulty_ref is None: _needs('original_verified_enforceable_contract_breach')
                if difficulty(profile.difficulty_ref).kind!='contract_breach': _needs('confirmed_original_contract_breach_for_enforcement')
            for notice_ref in right.notice_refs:
                notice=read(notice_ref,BankDefaultNoticeView,linked=True);author(notice)
                if (notice.arrangement_ref!=arrangement.ref or notice.author_organization_id!=bank or notice.status!='active'
                        or notice.delivery!='verified_served' or notice.served_at is None or not true(notice.confirmed_default)
                        or notice.basis_kind=='risk_estimate' or not keys(notice.obligation_refs)<=set(obligations)):
                    _needs('actual_original_default_and_verified_notice_service',[notice_ref])
                clock(notice.served_at);clock(notice.grace_deadline);clock(notice.remedy_deadline)
                if notice.served_at.offset>notice.available_at.offset or min(notice.grace_deadline.offset,notice.remedy_deadline.offset)<notice.served_at.offset:
                    raise ValueError('Default notice substitutes original service/deadline chronology')
                if notice.served_at.offset>now.offset or now.offset<=notice.grace_deadline.offset:
                    _needs('original_default_notice_grace_expiry',[notice_ref])
                if rule.require_expired_remedy_for_enforcement and now.offset<=notice.remedy_deadline.offset:
                    _needs('original_contract_remedy_window_expiry',[notice_ref])
                if notice.basis_kind=='actual_due_unpaid':
                    if not notice.obligation_refs or not any(obligations[r.key()].due_at.offset<=now.offset and remaining(obligations[r.key()])>0 for r in notice.obligation_refs):
                        _needs('actual_original_due_unpaid_default')
                elif notice.breach_assessment_ref is None: _needs('original_verified_contractual_breach')
                else:
                    breach=difficulty(notice.breach_assessment_ref)
                    if breach.kind!='contract_breach' or not keys(notice.obligation_refs)<=keys(breach.obligation_refs):
                        _needs('original_confirmed_contract_breach_for_notice')
        return complete(scope_ref=profile.affected_scope,right_refs=profile.enforcement_right_refs)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
