"""BANK-A11 closes only supported original scopes; every remaining source survives."""
from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.bank_closeout_objects import (
    BankCloseoutArrangementView, BankCloseoutProfileView, BankCloseoutRuleView,
    BankCloseoutDebtView, BankCloseoutCommitmentView, BankCommitmentCloseRuleView,
    BankCloseoutSecurityView, BankCloseoutIssueView, BankRemainingObligationView,
    BankCloseoutVerificationView, BankCloseoutExecutionView, BankDebtExecutionView, BankDebtReceiptView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def close_arrangement(context, action_input, reading):
    now,bank,scope=context.business_time,reading.organization_id,context.scope

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def clock(point):
        if point.clock_ref!=now.clock_ref: _unsupported('bank-closeout-clock-alignment')

    def evidence(refs):
        for ref in refs:
            row=reading.resolve(ref)
            if not isinstance(row,EvidenceRecord): _unsupported('bank-closeout-evidence-schema')
            if row.effective_window is not None: clock(row.effective_window.start)

    def read(ref,schema,historic=False,linked=False):
        row=reading.resolve(ref)
        if not isinstance(row,schema): _unsupported('bank-closeout-projection:'+ref.kind)
        if hasattr(row,'scope') and not linked and not scope_covers(scope,row.scope):
            raise ValueError('Finance closeout expands original invocation scope')
        evidence(getattr(row,'evidence_refs',[]))
        if hasattr(row,'available_at'):
            clock(row.available_at)
            if row.available_at.offset>now.offset: _needs('received_original_finance_closeout_source',[ref])
        if hasattr(row,'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now): _needs('current_original_finance_closeout_source',[ref])
        return row

    def true(value): return isinstance(value,Known) and value.value is True

    def authorize(ref,actor,function,organization,action,at,target):
        grant=read(ref,Authorization,historic=True,linked=True);assignment=read(function,RoleAssignment,historic=True,linked=True)
        roles={'BANK':'Bank','OWN':'Owner','CONTRACTOR':'Contractor','SUPPLIER':'Supplier','GOV':'Government',
               'ENGINEER':'Engineer','ARCHITECT':'Architect','QS':'QS'}
        if (grant.actor_id!=actor or grant.function_ref!=function or grant.organization_id!=organization
                or assignment.role!=roles.get(action.split('-')[0]) or action not in grant.action_ids
                or not any(scope_covers(s,target) for s in grant.scopes)):
            raise ValueError('Finance closeout substitutes original author/function/party/action authority')
        clock(at);clock(grant.validity.start)
        if not grant.validity.contains(at): _needs('original_finance_closeout_authority_at_execution',[ref])
        evidence(grant.basis_refs+assignment.basis_refs)
        return grant

    def author(row):
        clock(row.authored_at)
        if row.authored_at.offset>row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Finance closeout source precedes its original author execution')
        return authorize(row.author_authority_ref,row.author_actor_id,row.author_function_ref,
            row.author_organization_id,row.author_action_id,row.authored_at,row.scope)

    def amount(value):
        evidence([value.basis_ref]);number=decimal_fraction(value.value)
        if value.currency!=arrangement.currency or number<0:
            raise ValueError('Finance closeout changes original currency or negative balance')
        return number

    def overlap(left,right):
        return (left.kind==right.kind and left.ref==right.ref and
            (left==right or bool(keys(left.coverage_refs)&keys(right.coverage_refs))))

    def wait(ref):
        reading.recheck()
        return {'kind':'deferred','reason_code':'query_original_finance_closeout_or_payment','resume_condition':{
            'trigger':'dependency_change','object_refs':[ref],'earliest_time':None,'condition_code':'query_original_finance_closeout_or_payment'}}

    def verify(ref,target_ref,required_sources):
        row=read(ref,BankCloseoutVerificationView,linked=True);grant=author(row);clock(row.as_of)
        refs=[s.source_ref for s in row.source_digests]
        if (row.arrangement_ref!=arrangement.ref or row.choice!=profile.choice or row.target_ref.key()!=target_ref.key()
                or row.as_of!=now or not scope_covers(row.checked_scope,target) or not row.source_digests
                or not keys(required_sources)<=keys(refs) or not keys(refs)<=keys(grant.readable_refs)):
            raise ValueError('Finance closure verification substitutes original target/scope/ledger/read rights')
        if row.author_organization_id!=bank: _needs('original_lender_verified_finance_closure',[ref])
        if row.status=='failed': raise ObservationGap({'kind':'technical_error','error':{'kind':'unrecorded','correlation_id':context.operation_id,'code':'original-finance-closeout-check-failed'},'retryability':'unknown'})
        if row.status=='unsupported': _unsupported('original-finance-closeout-check-domain')
        if row.status!='ok' or not true(row.supported): _needs('supported_original_finance_closeout_conditions',[ref])
        for source in row.source_digests:
            original=reading.resolve(source.source_ref)
            if content_digest(original)!=source.content_sha256: raise ValueError('Finance closeout reuses stale balance or source verification')
            if hasattr(original,'available_at'):
                clock(original.available_at)
                if original.available_at.offset>row.authored_at.offset: raise ValueError('Closure verification precedes original source availability')

    try:
        arrangement=read(action_input.arrangement_ref,BankCloseoutArrangementView,linked=True)
        profile=read(arrangement.closeout_profile_ref,BankCloseoutProfileView)
        if (arrangement.lender_id!=bank or profile.arrangement_ref!=arrangement.ref or profile.organization_id!=bank
                or profile.actor_id!=context.actor_id or profile.function_ref!=context.function_ref or profile.scope!=scope
                or profile.authority_ref not in context.authorization_refs or not scope_covers(arrangement.scope,scope)):
            raise ValueError('Finance closeout substitutes original arrangement/bank/actor/scope/authority')
        authorize(profile.authority_ref,context.actor_id,context.function_ref,bank,'BANK-A11',now,scope)
        clock(arrangement.as_of)
        if arrangement.as_of!=now or arrangement.coverage!='complete': _needs('complete_current_formal_finance_closeout_ledger')
        for supplied,original in [('debt_refs','debt_refs'),('security_refs','security_refs')]:
            if keys(getattr(action_input,supplied))!=keys(getattr(arrangement,original)): _needs('complete_original_finance_closeout_'+supplied)
        target=profile.scope_ref
        if not scope_covers(scope,target) or not profile.basis_refs: _needs('explicit_original_finance_closure_scope_and_basis')
        evidence(profile.basis_refs);keys(profile.basis_refs)
        rule=read(arrangement.rule_ref,BankCloseoutRuleView,linked=True);author(rule)
        if rule.arrangement_ref!=arrangement.ref or rule.author_organization_id!=bank or profile.choice not in rule.permitted_choices or not true(rule.permitted):
            _needs('original_lender_closeout_procedure_permission')
        sources={};remaining_sources=set();debts={};executions={};commitments={};securities={};issues={}
        physical_debts=set()
        for ref in arrangement.debt_refs:
            debt=read(ref,BankCloseoutDebtView,linked=True);clock(debt.as_of);clock(debt.accrual_complete_through)
            if (debt.arrangement_ref!=arrangement.ref or debt.lender_id!=bank or debt.borrower_id!=arrangement.borrower_id
                    or debt.as_of!=now): _needs('current_original_finance_debt_components',[ref])
            if debt.physical_component_key in physical_debts: raise ValueError('Finance closure aliases original physical debt component')
            physical_debts.add(debt.physical_component_key)
            paid=amount(debt.cash_paid)+amount(debt.actual_offset);due=amount(debt.actual_due)
            if paid>due: raise ValueError('Finance closeout paid/offset exceeds original due component')
            debts[ref.key()]=debt;sources[ref.key()]=debt
            if (not isinstance(debt.outstanding_balance,Known) or amount(debt.outstanding_balance.value)>0
                    or debt.accrual_complete_through!=now or paid<due):
                remaining_sources.add(ref.key())
        receipt_events=set();payment_commands=set();payment_business=set()
        keys(arrangement.payment_execution_refs)
        for ref in arrangement.payment_execution_refs:
            execution=read(ref,BankDebtExecutionView,historic=True,linked=True)
            if execution.arrangement_ref!=arrangement.ref or execution.lender_id!=bank or execution.borrower_id!=arrangement.borrower_id:
                raise ValueError('Finance closure replaces original pending payment parties/arrangement')
            if execution.command_id in payment_commands or execution.business_key in payment_business:
                raise ValueError('Finance closure repeats an original payment command/business key')
            payment_commands.add(execution.command_id);payment_business.add(execution.business_key)
            executions[ref.key()]=execution;sources[ref.key()]=execution
            if execution.status in {'unknown','pending','partial'}: remaining_sources.add(ref.key())
            if execution.status=='succeeded' and not execution.receipt_refs: _needs('original_verified_completed_finance_payment',[ref])
            keys(execution.receipt_refs)
            for receipt_ref in execution.receipt_refs:
                receipt=read(receipt_ref,BankDebtReceiptView,historic=True,linked=True)
                if (receipt.execution_ref!=execution.ref or receipt.arrangement_ref!=arrangement.ref or receipt.lender_id!=bank
                        or receipt.borrower_id!=arrangement.borrower_id or receipt.command_id!=execution.command_id
                        or receipt.business_key!=execution.business_key or receipt.event_id in receipt_events):
                    raise ValueError('Closure aliases or substitutes original actual cash receipt event')
                clock(receipt.effective_at);clock(receipt.verified_at)
                if not receipt.effective_at.offset<=receipt.verified_at.offset<=min(now.offset,receipt.available_at.offset):
                    _needs('verified_original_finance_closeout_receipt_effective_time',[receipt_ref])
                received=amount(receipt.amount)
                if received<=0: raise ValueError('Finance closure requires positive original actual receipt amount')
                keys([effect.debt_component_ref for effect in receipt.principal_effects])
                principal_total=0
                for effect in receipt.principal_effects:
                    component=debts.get(effect.debt_component_ref.key())
                    if component is None or component.kind!='principal':
                        raise ValueError('Finance closure receipt changes original principal component')
                    principal_total+=amount(effect.amount)
                if principal_total>received:
                    raise ValueError('Finance closure receipt principal effects exceed original actual amount')
                receipt_events.add(receipt.event_id)
        if keys(action_input.pending_execution_refs)!={key for key,e in executions.items() if e.status in {'unknown','pending','partial'}}:
            _needs('all_original_pending_or_unknown_finance_executions')
        physical=set()
        for ref in arrangement.commitment_refs:
            commitment=read(ref,BankCloseoutCommitmentView,linked=True);clock(commitment.as_of);clock(commitment.expiry_at)
            if (commitment.arrangement_ref!=arrangement.ref or commitment.lender_id!=bank or commitment.as_of!=now
                    or commitment.physical_commitment_key in physical or not keys(commitment.execution_refs)<=set(executions)):
                raise ValueError('Closure substitutes current original commitment or pending execution history')
            physical.add(commitment.physical_commitment_key);commitments[ref.key()]=commitment;sources[ref.key()]=commitment
            if commitment.status!='closed': remaining_sources.add(ref.key())
        expected_unused={key for key,c in commitments.items() if c.status=='unknown' or
            c.status=='active' and (not isinstance(c.unused_amount,Known) or amount(c.unused_amount.value)>0)}
        if keys(action_input.unused_commitment_refs)!=expected_unused: _needs('all_original_current_unused_commitments')
        for ref in arrangement.security_refs:
            security=read(ref,BankCloseoutSecurityView,linked=True);author(security)
            if security.arrangement_ref!=arrangement.ref or security.holder_id!=bank or not keys(security.debt_refs)<=set(debts):
                raise ValueError('Closure substitutes original security holder or covered debts')
            securities[ref.key()]=security;sources[ref.key()]=security
            if security.status!='released': remaining_sources.add(ref.key())
        for ref in arrangement.issue_refs:
            issue=read(ref,BankCloseoutIssueView,linked=True)
            if issue.arrangement_ref!=arrangement.ref: raise ValueError('Closure issue belongs to another arrangement')
            issues[ref.key()]=issue;sources[ref.key()]=issue
            if issue.status!='resolved': remaining_sources.add(ref.key())
        if keys(action_input.unresolved_refs)!={key for key,i in issues.items() if i.status!='resolved'}:
            _needs('all_original_unresolved_finance_issues')
        retained=[];seen=set();keys(arrangement.remaining_obligation_refs)
        for ref in arrangement.remaining_obligation_refs:
            original=read(ref,BankRemainingObligationView,linked=True);clock(original.as_of)
            key=original.source_ref.key()
            if (original.arrangement_ref!=arrangement.ref or original.as_of!=now or key not in sources or key in seen
                    or original.source_sha256!=content_digest(sources[key])):
                raise ValueError('Remaining obligation aliases, omits or changes original source ledger')
            seen.add(key)
            if key in remaining_sources: retained.append(original.ref)
        if not remaining_sources<=seen: _needs('all_formal_original_remaining_obligation_sources')
        business=set();keys(arrangement.closeout_execution_refs)
        for ref in arrangement.closeout_execution_refs:
            execution=read(ref,BankCloseoutExecutionView,historic=True,linked=True)
            if execution.organization_id!=bank or execution.run_id!=context.run_id or execution.arrangement_ref.id!=arrangement.ref.id or execution.business_key in business:
                raise ValueError('Closure repeats original arrangement/run/business identity')
            business.add(execution.business_key)
            if execution.business_key==profile.business_key:
                original=read(execution.profile_ref,BankCloseoutProfileView,historic=True,linked=True)
                metadata={'ref','arrangement_ref','available_at','effective_window'}
                if (original.arrangement_ref!=execution.arrangement_ref or original.organization_id!=execution.organization_id
                        or original.scope!=execution.scope or original.business_key!=execution.business_key
                        or original.scope_ref!=execution.affected_scope or execution.profile_sha256!=content_digest(original)
                        or original.model_dump(exclude=metadata)!=profile.model_dump(exclude=metadata)):
                    raise ValueError('Closeout changes original business payload')
                return wait(execution.ref)
            if profile.choice!='retain' and execution.status in {'pending','unknown'} and overlap(target,execution.affected_scope): return wait(execution.ref)

        candidates=keys(profile.release_candidate_refs)
        if not candidates<=keys(action_input.unused_commitment_refs): raise ValueError('Closeout invents original unused commitment release candidates')
        if profile.choice=='retain' and (candidates or profile.security_close_refs): raise ValueError('Retain cannot release original commitments/security')
        if profile.choice!='retain':
            if not rule.verification_refs: _needs('original_scope_closeout_verification')
            for ref in rule.verification_refs: verify(ref,arrangement.ref,[arrangement.ref])
            if profile.choice=='close_unused' and not candidates: _needs('specific_actual_unused_commitments_to_close')
            for key in candidates:
                commitment=commitments[key]
                if not scope_covers(target,commitment.scope): raise ValueError('Partial closure cannot release a shared whole-scope commitment')
                if commitment.status!='active' or not isinstance(commitment.unused_amount,Known) or amount(commitment.unused_amount.value)<=0:
                    _needs('known_actual_original_unused_commitment',[commitment.ref])
                for execution_ref in commitment.execution_refs:
                    if executions[execution_ref.key()].status in {'unknown','pending','partial'}: return wait(execution_ref)
                release=read(commitment.release_rule_ref,BankCommitmentCloseRuleView,linked=True);author(release)
                if release.commitment_ref!=commitment.ref or release.author_organization_id!=bank or not true(release.permitted):
                    _needs('original_commitment_close_permission',[commitment.ref])
                if release.trigger=='expired' and now.offset<commitment.expiry_at.offset: _needs('actual_unused_commitment_expiry',[commitment.ref])
                if release.trigger=='cleared_scope' and profile.choice!='close_cleared_scope': _needs('cleared_original_scope_before_commitment_close')
                if not release.verification_refs: _needs('original_commitment_release_conditions')
                for ref in release.verification_refs: verify(ref,commitment.ref,[commitment.ref,*commitment.execution_refs])
            if profile.choice=='close_cleared_scope':
                for key,source in sources.items():
                    if not overlap(target,source.scope): continue
                    if not scope_covers(target,source.scope): _needs('separate_original_partial_finance_component_scope',[source.ref])
                    if key in debts and key in remaining_sources: _needs('actual_all_principal_interest_fee_components_cleared',[source.ref])
                    if key in executions and key in remaining_sources: return wait(source.ref)
                    if key in issues and key in remaining_sources: _needs('original_unresolved_finance_issue_completion',[source.ref])
                    if key in commitments and key in remaining_sources and key not in candidates: _needs('original_remaining_commitment_retained_outside_closed_scope',[source.ref])
                expected={key for key,row in securities.items() if overlap(target,row.scope) and row.status!='released'}
                if keys(profile.security_close_refs)!=expected: _needs('all_original_security_closure_conditions_for_selected_scope')
                for key in expected:
                    security=securities[key]
                    if security.status!='active' or any(k in remaining_sources for k in keys(security.debt_refs)):
                        _needs('all_original_secured_debts_cleared_before_security_release',[security.ref])
                    if not security.release_verification_refs: _needs('original_valid_security_release_conditions',[security.ref])
                    for ref in security.release_verification_refs: verify(ref,security.ref,[security.ref,*security.debt_refs])
            elif profile.security_close_refs: raise ValueError('Unused commitment closure cannot close security/debt automatically')
        reading.recheck()
        return {'kind':'completed','payload':{'choice':profile.choice,'scope_ref':target,'retained_refs':retained,
            'release_candidate_refs':profile.release_candidate_refs,'basis_refs':profile.basis_refs,'note':profile.note+
            ' Closure proposal only. Original remaining debt, unknown payment, security and unresolved issues stay linked and scheduled until actual core effects. Unused commitment expiry is separate from debt/security clearance; project completion or accounting writeoff does not clear the loan. Release candidates are not actual released capacity; history remains.'}}
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
