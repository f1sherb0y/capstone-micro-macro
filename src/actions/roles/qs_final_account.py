"""QS-A09 proposes traced final accounts without treating them as clearance."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known, Money
from src.actions.contracts.qs_final_account_objects import (
    QSFinalContractView, QSFinalProfileView, QSFinalEntitlementView, QSFinalEntitlementAuthorityView,
    QSFinalCashExecutionView, QSFinalAdjustmentView, QSFinalAdjustmentBasisView, QSFinalResultView,
    QSFinalDeterminationView, QSFinalMechanismView, QSFinalConsentView, QSFinalPowerBasisView,
    QSFinalQuestionView, QSFinalResponseView, QSFinalExecutionView, QSFinalAccount,
    QSPaymentCertificateView, QSPaymentStatementView, QSChangeClaimView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.actions.roles.qs_receipts import reconcile_original_receipts
from src.methods.pricing import decimal_fraction, exact_decimal
from src.methods.qs_cost import unknown
from src.methods.qs_final_account import FINAL_ACCOUNT_METHOD, FinalAccountComponent, FinalAccountInput
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def prepare_final_account(context, action_input, reading):
    return _prepare_final_account(context, action_input, reading)


def prepare_final_account_arithmetic(context, action_input, reading):
    """Reuse original settlement-history checks without a saved reconciliation."""
    reading.check_method_context(context, 'QS-A09')
    if action_input.reconciliation_result_ref is not None:
        raise ValueError('Final-account production requires source input without a saved reconciliation')
    return _prepare_final_account(context, action_input, reading, arithmetic_only=True)


def _prepare_final_account(context, action_input, reading, *, arithmetic_only=False):
    now,org,scope=context.business_time,reading.organization_id,context.scope

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def clock(point):
        if point.clock_ref!=now.clock_ref: _unsupported('qs-final-account-clock-alignment')

    def evidence(refs):
        for ref in refs:
            row=reading.resolve(ref)
            if not isinstance(row,EvidenceRecord): _unsupported('qs-final-account-evidence-schema')
            if row.effective_window is not None: clock(row.effective_window.start);clock(row.effective_window.end)

    def read(ref,schema,historic=True,linked=False):
        row=reading.resolve(ref)
        if not isinstance(row,schema): _unsupported('qs-final-account-projection:'+ref.kind)
        if hasattr(row,'scope') and not linked and not scope_covers(scope,row.scope):
            raise ValueError('Final account source expands original authorized scope')
        evidence(getattr(row,'evidence_refs',[]))
        if hasattr(row,'available_at'):
            clock(row.available_at)
            if row.available_at.offset>now.offset: _needs('received_original_final_account_source',[ref])
        if hasattr(row,'effective_window'):
            clock(row.effective_window.start);clock(row.effective_window.end)
            if not historic and not row.effective_window.contains(now): _needs('current_original_final_account_source',[ref])
        return row

    def true(value): return isinstance(value,Known) and value.value is True

    def authorize(ref,actor,function,organization,action,at,target):
        grant=read(ref,Authorization,linked=True);assignment=read(function,RoleAssignment,linked=True)
        roles={'QS':'QS','OWN':'Owner','GOV':'Government','ARCHITECT':'Architect','ENGINEER':'Engineer',
               'CONTRACTOR':'Contractor','SUPPLIER':'Supplier','BANK':'Bank'}
        if (grant.actor_id!=actor or grant.function_ref!=function or grant.organization_id!=organization
                or assignment.function_ref!=function or assignment.role!=roles.get(action.split('-')[0])
                or action not in grant.action_ids or not any(scope_covers(s,target) for s in grant.scopes)):
            raise ValueError('Final account substitutes original author/action/party/function/scope authority')
        clock(at);clock(grant.validity.start);clock(grant.validity.end)
        if not grant.validity.contains(at): _needs('original_final_account_authority_at_execution',[ref])
        evidence(grant.basis_refs+assignment.basis_refs)
        return grant

    def author(row):
        grant=read(row.author_authority_ref,Authorization,linked=True);clock(row.authored_at)
        if row.authored_at.offset>row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Final account source precedes original author execution')
        if hasattr(row,'author_organization_id') and row.author_organization_id!=grant.organization_id:
            raise ValueError('Final account source changes original author organization')
        return authorize(row.author_authority_ref,row.author_actor_id,row.author_function_ref,grant.organization_id,
            row.author_action_id,row.authored_at,row.scope)

    def amount(money):
        evidence([money.basis_ref])
        if money.currency!=contract.currency: _unsupported('qs-final-account-currency-conversion')
        return decimal_fraction(money.value)

    def state_amount(value):
        if isinstance(value,Known): amount(value.value)

    def wait(ref,code='query_original_final_account_execution'):
        reading.recheck()
        return {'kind':'deferred','reason_code':code,'resume_condition':{'trigger':'dependency_change',
            'object_refs':[ref],'earliest_time':None,'condition_code':code}}

    def complete(**fields):
        reading.recheck()
        return {'kind':'completed','payload':{'choice':profile.choice,'scope':scope,**fields,'note':
            'Original final-account opinion only. Determined price, certified value, actual cash and unsettled/disputed duties remain separate. Balance includes retained or not-yet-due liabilities and may show overpayment; it does not prove cash clearance, loan payoff, completed work or resolution of uncovered claims.'}}

    def mechanism(ref,purpose,actor=None,function=None):
        row=read(ref,QSFinalMechanismView,historic=False);author(row)
        if row.contract_ref!=contract.ref or row.purpose!=purpose or not true(row.permitted): _needs('original_applicable_final_settlement_mechanism',[ref])
        if actor is not None and (row.decision_actor_id!=actor or row.decision_function_ref!=function):
            raise ValueError('Final settlement mechanism changes original authorized decision maker')
        grant=read(row.authorization_ref,Authorization,linked=True)
        clock(row.decision_at)
        if row.decision_at.offset>now.offset: _needs('original_received_settlement_decision_execution',[row.ref])
        if purpose=='final_price' and (row.decision_action_id!='QS-A09' or not scope_covers(scope,row.scope)):
            raise ValueError('Final price mechanism must authorize the original QS-A09 scope')
        authorize(row.authorization_ref,row.decision_actor_id,row.decision_function_ref,grant.organization_id,
            row.decision_action_id,now if purpose=='final_price' else row.decision_at,scope)
        if row.mode=='all_parties':
            if set(row.required_party_ids)!=set(contract.party_ids) or len(set(row.required_party_ids))!=len(row.required_party_ids):
                _needs('all_original_contract_parties_for_final_settlement')
        else:
            if row.power_basis_ref is None: _needs('original_independent_delegation_or_external_determination')
            power=read(row.power_basis_ref,QSFinalPowerBasisView,historic=False);author(power)
            if (power.contract_ref!=contract.ref or power.mechanism_ref!=row.ref or power.mode!=row.mode
                    or power.decision_actor_id!=row.decision_actor_id or power.decision_function_ref!=row.decision_function_ref
                    or power.issuer_actor_id!=power.author_actor_id or not true(power.permitted) or not true(power.verified)):
                _needs('original_verified_final_settlement_power',[power.ref])
            if row.mode=='contract_delegated' and power.issuer_actor_id not in contract.party_ids:
                raise ValueError('Final settlement delegation must come from original contract party')
            if row.mode=='external_determination' and not power.author_action_id.startswith('GOV-'):
                _needs('modeled_original_external_legal_determination',[power.ref])
        accepted=set();keys(row.party_consent_refs)
        for ref in row.party_consent_refs:
            consent=read(ref,QSFinalConsentView,historic=False);author(consent)
            if (consent.contract_ref!=contract.ref or consent.mechanism_ref!=row.ref
                    or consent.party_id!=consent.author_actor_id or consent.party_id not in contract.party_ids
                    or consent.party_id in accepted): raise ValueError('Settlement consent substitutes original party/mechanism')
            if not true(consent.accepted): _needs('independent_original_settlement_party_acceptance',[ref])
            accepted.add(consent.party_id)
        if not set(row.required_party_ids)<=accepted: _needs('required_original_settlement_party_acceptance')
        return row

    try:
        if action_input.scope!=scope: raise ValueError('Final account changes invocation scope')
        contract=read(action_input.contract_ref,QSFinalContractView);clock(contract.as_of)
        profile=read(contract.final_profile_ref,QSFinalProfileView,historic=False);author(profile)
        if (contract.valuation_organization_id!=org or contract.valuation_actor_id!=context.actor_id
                or contract.valuation_function_ref!=context.function_ref or profile.contract_ref!=contract.ref
                or profile.author_organization_id!=org
                or profile.actor_id!=context.actor_id or profile.function_ref!=context.function_ref
                or profile.authority_ref not in context.authorization_refs or profile.scope!=scope):
            raise ValueError('Final account changes original contract/valuation firm/actor/current authority')
        authorize(profile.authority_ref,context.actor_id,context.function_ref,org,'QS-A09',now,scope)
        if contract.as_of!=now or contract.coverage!='complete': _needs('complete_current_original_contract_final_history')
        for supplied,original in [('determined_change_refs','determined_change_refs'),('certificate_refs','all_certificate_refs'),
                ('payment_receipt_refs','receipt_refs'),('unresolved_claim_refs','unresolved_claim_refs')]:
            if keys(getattr(action_input,supplied))!=keys(getattr(contract,original)): _needs('complete_original_final_account_'+supplied)
        keys(contract.execution_refs);business=set()
        for ref in contract.execution_refs:
            execution=read(ref,QSFinalExecutionView)
            if execution.contract_ref.id!=contract.ref.id or execution.run_id!=context.run_id or execution.business_key in business:
                raise ValueError('Final account history repeats original run/contract/business identity')
            business.add(execution.business_key)
            if execution.business_key==profile.business_key:
                original=read(execution.profile_ref,QSFinalProfileView)
                metadata={'ref','contract_ref','available_at','effective_window'}
                if (original.contract_ref!=execution.contract_ref or original.scope!=execution.scope
                        or original.business_key!=execution.business_key
                        or execution.profile_sha256!=content_digest(original)
                        or original.model_dump(exclude=metadata)!=profile.model_dump(exclude=metadata)):
                    raise ValueError('Final account changes original content under old business identity')
                return wait(ref)
            if execution.status in {'pending','unknown'}: return wait(ref)
        if profile.choice=='request_evidence':
            if not profile.question_refs: _needs('specific_original_final_account_evidence_questions')
            questions=[];keys(profile.question_refs)
            for ref in profile.question_refs:
                row=read(ref,QSFinalQuestionView,historic=False);response=read(row.response_requirement_ref,QSFinalResponseView,historic=False)
                if (row.contract_ref!=contract.ref or response.contract_ref!=contract.ref or not row.recipient_ids
                        or not set(row.recipient_ids)<=set(contract.party_ids) or not set(row.recipient_ids)<=set(response.recipient_ids)):
                    raise ValueError('Final account evidence request changes original contract/response recipients')
                questions.append({'scope':scope,'target_refs':[row.ref],'question':row.question,'recipient_ids':row.recipient_ids,
                    'evidence_refs':row.evidence_refs,'blocking_uses':['cost_estimation'],'response_requirement_ref':response.ref})
            return complete(questions=questions)
        if not arithmetic_only and action_input.reconciliation_result_ref is None:
            _needs('saved_applicable_original_final_account_reconciliation')
        state_amount(contract.base_amount);changes=[];components={contract.base_component_key}
        for ref in contract.determined_change_refs:
            row=read(ref,QSFinalEntitlementView);author(row)
            power=read(row.decision_authority_ref,QSFinalEntitlementAuthorityView);author(power)
            if (row.contract_ref!=contract.ref or row.status!='decided' or power.contract_ref!=contract.ref
                    or power.claim_ref!=row.claim_ref or power.actor_id!=row.author_actor_id
                    or power.function_ref!=row.author_function_ref or not true(power.permitted)
                    or row.component_key in components): raise ValueError('Final price repeats or substitutes original independently determined entitlement')
            if not isinstance(row.payer_id,Known) or row.payer_id.value!=contract.payer_id: _needs('original_determined_change_payer',[ref])
            state_amount(row.recognized_amount);state_amount(row.disputed_amount)
            if row.direction!='signed' and isinstance(row.recognized_amount,Known) and amount(row.recognized_amount.value)<0:
                raise ValueError('Directional final adjustment requires positive magnitude or explicit original signed amount')
            if (not isinstance(row.disputed_amount,Known) or amount(row.disputed_amount.value)>0) and row.claim_ref.key() not in keys(contract.unresolved_claim_refs):
                _needs('original_unresolved_claim_for_disputed_entitlement',[row.claim_ref])
            components.add(row.component_key)
            changes.append(FinalAccountComponent(component_key=row.component_key,amount=row.recognized_amount,
                direction=-1 if row.direction=='decrease' else 1))
        claims=set()
        for ref in contract.unresolved_claim_refs:
            claim=read(ref,QSChangeClaimView);author(claim)
            if claim.contract_ref!=contract.ref or claim.status!='submitted' or claim.claimant_id not in contract.party_ids:
                raise ValueError('Final account substitutes original unresolved contract claim')
            claims.add(ref.key())
        certificates={};statements={};active=[];current_keys=set();successors=set()
        for ref in contract.all_certificate_refs:
            row=read(ref,QSPaymentCertificateView);author(row)
            if row.contract_ref!=contract.ref: raise ValueError('Final certificate belongs to another contract')
            statement=read(row.statement_ref,QSPaymentStatementView);author(statement)
            if statement.contract_ref!=contract.ref or statement.certificate_ref!=row.ref or statement.calculation_ref!=row.calculation_ref:
                raise ValueError('Final certificate substitutes its original statement/calculation')
            statements[statement.ref.key()]=statement.ref;certificates[ref.key()]=row
            if row.status=='active':
                if row.certificate_key in current_keys: raise ValueError('Final account repeats active certificate under aliases')
                current_keys.add(row.certificate_key);amount(row.assessed_contribution);active.append(row)
        if keys([r.ref for r in active])!=keys(contract.active_certificate_refs): _needs('complete_original_active_certificate_history')
        # sequence identifies the original certificate obligation, as in A08;
        # a corrected version keeps that sequence rather than incrementing it.
        if sorted(r.sequence for r in active)!=list(range(1,len(active)+1)):
            _needs('complete_original_final_certificate_obligation_sequence')
        for row in certificates.values():
            if row.predecessor_ref is not None:
                predecessor=certificates.get(row.predecessor_ref.key())
                if (predecessor is None or predecessor.status!='superseded' or predecessor.certificate_key!=row.certificate_key
                        or predecessor.sequence!=row.sequence or predecessor.ref.key() in successors
                        or predecessor.authored_at.offset>row.authored_at.offset):
                    raise ValueError('Final certificate chain branches, omits or repeats corrected original history')
                successors.add(predecessor.ref.key())
        if any(r.status=='superseded' and r.ref.key() not in successors for r in certificates.values()):
            _needs('original_replacement_for_superseded_final_certificate')
        lineage=set()
        for row in active:
            seen=set()
            while True:
                key=row.ref.key()
                if key in seen: raise ValueError('Final certificate replacement history contains a cycle')
                seen.add(key);lineage.add(key)
                if row.predecessor_ref is None: break
                row=certificates[row.predecessor_ref.key()]
        if lineage!=set(certificates):
            raise ValueError('Final certificate history contains a chain without an active original successor')
        keys(contract.payment_execution_refs);cash_unknown=contract.certified_cash_visibility!='complete';execution_receipts=set()
        for ref in contract.payment_execution_refs:
            execution=read(ref,QSFinalCashExecutionView);clock(execution.as_of)
            if execution.run_id!=context.run_id or execution.contract_ref!=contract.ref or execution.as_of!=now:
                raise ValueError('Final cash history changes original run/contract/current receipt snapshot')
            execution_receipts.update(keys(execution.receipt_refs));cash_unknown|=execution.status in {'pending','unknown'}
        if execution_receipts!=keys(contract.receipt_refs): _needs('complete_original_final_payment_execution_history')
        totals=reconcile_original_receipts(contract,contract.receipt_refs,read,amount)
        cash=Fraction()
        for (purpose,ref),(value,uncertain) in totals.items():
            if purpose=='certified_payment' and ref.key() not in certificates: raise ValueError('Final cash refers to omitted original certificate')
            if purpose=='advance' and ref.key() not in keys(contract.advance_credit_refs): raise ValueError('Final cash refers to omitted original advance')
            cash+=value;cash_unknown|=uncertain
        received=unknown('actual_contract_cash_not_visible_or_verified') if cash_unknown else Known[Money](state='known',value=Money(
            value=exact_decimal(cash),currency=contract.currency,basis_ref=contract.evidence_refs[0]))
        adjustments={'price_deduction':[],'payment_setoff':[],'verified_refund':[]};events=set();keys(contract.adjustment_refs)
        for ref in contract.adjustment_refs:
            row=read(ref,QSFinalAdjustmentView);author(row);clock(row.as_of)
            basis=read(row.authority_ref,QSFinalAdjustmentBasisView);author(basis)
            if (row.contract_ref!=contract.ref or row.as_of!=now or row.component_key in components or row.event_key in events
                    or basis.contract_ref!=contract.ref or basis.adjustment_ref!=row.ref or basis.kind!=row.kind
                    or basis.adjustment_sha256!=content_digest(row) or not true(basis.permitted)):
                raise ValueError('Final account repeats or substitutes original applied refund/setoff/deduction')
            mechanism(basis.mechanism_ref,row.kind);state_amount(row.amount)
            components.add(row.component_key);events.add(row.event_key)
            value=row.amount if row.status=='applied' else unknown('original_adjustment_application_unknown')
            adjustments[row.kind].append(FinalAccountComponent(component_key=row.component_key,amount=value,direction=1))
        data=FinalAccountInput(currency=contract.currency,money_basis_ref=contract.evidence_refs[0],base_component_key=contract.base_component_key,
            base_amount=contract.base_amount,changes=changes,price_deductions=adjustments['price_deduction'],
            certificate_contributions=[r.assessed_contribution for r in active],received_cash=received,
            cash_refunds=adjustments['verified_refund'],noncash_satisfied=adjustments['payment_setoff'],
            source_refs=[contract.ref,*contract.determined_change_refs,*contract.all_certificate_refs,*contract.receipt_refs,
                *contract.payment_execution_refs,*contract.adjustment_refs,*statements.values()])
        if arithmetic_only:
            reading.recheck()
            return {'kind':'prepared','input':data,'contract_ref':contract.ref,
                'unresolved_claim_refs':list(contract.unresolved_claim_refs),'source_statement_refs':list(statements.values())}
        saved=read(action_input.reconciliation_result_ref,QSFinalResultView);author(saved);clock(saved.executed_at)
        if (saved.contract_ref!=contract.ref or saved.method_ref!=FINAL_ACCOUNT_METHOD or saved.data!=data
                or saved.input_sha256!=content_digest(data) or saved.executed_at.offset>saved.authored_at.offset):
            raise ValueError('Final reconciliation changes original contract, cash history or source inputs')
        if saved.status=='unsupported': _unsupported('original-final-account-reconciliation-domain')
        if saved.status!='ok' or saved.report is None: _needs('successful_original_final_account_reconciliation',[saved.ref])
        result=reading.calculate(FINAL_ACCOUNT_METHOD,data)
        if result.kind!='ok':
            if result.kind=='invalid_input': _unsupported('original-final-account-method-domain')
            raw=result.model_dump(mode='python')
            if result.kind=='needs_information': raw['requested_refs']=[]
            raise ObservationGap(raw)
        if result.value!=saved.report: raise ValueError('Final account report differs from exact original reconciliation')
        account=QSFinalAccount(contract_ref=contract.ref,reconciliation_result_ref=saved.ref,
            **result.value.model_dump(mode='python'),unresolved_claim_refs=contract.unresolved_claim_refs,source_statement_refs=list(statements.values()))
        if profile.choice=='propose_account': return complete(account=account.model_dump(mode='python'))
        if profile.determination_basis_ref is None: _needs('independent_original_final_account_determination_basis')
        basis=read(profile.determination_basis_ref,QSFinalDeterminationView,historic=False);author(basis)
        if (basis.contract_ref!=contract.ref or basis.reconciliation_result_ref!=saved.ref or basis.account_sha256!=content_digest(account)
                or basis.actor_id!=context.actor_id or basis.function_ref!=context.function_ref or not true(basis.permitted)
                or len(set(basis.covered_component_keys))!=len(basis.covered_component_keys)
                or not basis.covered_component_keys or not set(basis.covered_component_keys)<=components
                or keys(basis.excluded_claim_refs)!=claims):
            _needs('original_authorized_covered_final_price_and_retained_disputes',[basis.ref])
        if not isinstance(account.determined_total,Known): _needs('original_determined_final_price')
        mechanism(basis.mechanism_ref,'final_price',context.actor_id,context.function_ref)
        return complete(account=account.model_dump(mode='python'),determination_basis_ref=basis.ref)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
