"""SUPPLIER-A10 claims original contract amounts and instructs own cash only."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known,walk_references
from src.actions.contracts.supplier_payment_objects import (
    SupplierSettlementRuleView,SupplierPaymentLedgerView,SupplierPaymentOrderView,SupplierPaymentOrderLineView,
    SupplierOrderPaymentNodeView,SupplierClaimValuationView,SupplierPaymentDeliveryView,SupplierPaymentClaimView,
    SupplierPaymentNodeAuthorityView,
    SupplierPaymentIssueView,OwnerPaymentAccountView,OwnerPaymentSourceView,OwnerPaymentReservationView,
    OwnerPaymentObligationView,OwnerPaymentComponentView,OwnerPaymentExecutionView,OwnerPaymentReceiptView,
    FundingPurposeView,FinanceProductProfileView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap,_needs,_known,_unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.supplier_payment import CLAIM_METHOD,calculate_claim_amount
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization,RoleAssignment
from src.organization.registry import scope_covers


def manage_supplier_cash(context,action_input,reading):
    return _manage_supplier_cash(context,action_input,reading)


def recheck_original_supplier_claim_wait(context,action_input,reading):
    """Recheck immutable original claim sources under actual current read rights.

    The original business time authenticates author grants and saved valuations.
    Fixed pure arithmetic compares their reports without impersonating an old
    method invocation or adding method evidence to the current action. The
    recovery caller separately authenticates the original snapshot/native gate.
    This helper returns an existing wait only and cannot form a new claim.
    """
    reading.check_method_context(reading._context,'SUPPLIER-A10')
    binding=reading._methods._bindings.get(CLAIM_METHOD.key()) if reading._methods is not None else None
    if (CLAIM_METHOD.key() not in reading._method_refs or binding is None
            or binding.executor is not calculate_claim_amount or 'SUPPLIER-A10' not in binding.definition.action_ids
            or binding.definition.effect_kind!='pure_calculation'):
        raise ValueError('Historical claim check requires the original declared pure amount method')
    rule=reading.resolve(action_input.settlement_rule_ref)
    if not isinstance(rule,SupplierSettlementRuleView) or rule.choice!='request_payment':
        raise ValueError('Historical claim check requires the original request-payment branch')
    result=_manage_supplier_cash(context,action_input,reading,historical_claim=True)
    if result.get('kind')!='deferred' or result.get('reason_code') not in {
            'continue_original_supplier_payment_claim','continue_original_existing_contract_node_claim'}:
        raise ValueError('Historical claim sources do not reproduce the original claim wait')
    return result


def _manage_supplier_cash(context,action_input,reading,*,historical_claim=False):
    now,org,scope=context.business_time,reading.organization_id,context.scope

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref:_unsupported('supplier-payment-clock-alignment')

    def evidence(refs,*,at=None,historic=False):
        point=now if at is None else at
        clock(point)
        if point.offset>now.offset:_needs('received_original_supplier_payment_evidence_time')
        for ref in refs:
            row=reading.resolve(ref)
            if not isinstance(row,EvidenceRecord):_unsupported('supplier-payment-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if row.effective_window.start.offset>now.offset:_needs('received_original_supplier_payment_evidence',[ref])
                if (at is not None or not historic) and not row.effective_window.contains(point):
                    _needs('original_supplier_payment_evidence_valid_at_use',[ref])

    def read(ref,schema,historic=False,linked=False,*,evidence_at_field=None):
        row=reading.resolve(ref)
        if not isinstance(row,schema):_unsupported('supplier-payment-projection:'+ref.kind)
        if hasattr(row,'scope') and not linked and not scope_covers(scope,row.scope):
            raise ValueError('Payment source expands original authorized scope')
        if hasattr(row,'available_at'):
            clock(row.available_at)
            if row.available_at.offset>now.offset:_needs('received_original_supplier_payment_source',[ref])
        if hasattr(row,'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now):_needs('current_original_supplier_payment_source',[ref])
        point=None if evidence_at_field is None else getattr(row,evidence_at_field)
        if point is not None:
            clock(point)
            if point.offset>now.offset:_needs('received_original_supplier_payment_evidence_time',[ref])
            if point.offset>row.available_at.offset:raise ValueError('Supplier payment source precedes its actual event or authorship')
        evidence(getattr(row,'evidence_refs',[]),at=point,historic=historic)
        return row

    def true(value):return isinstance(value,Known) and value.value is True

    def authorize(ref,actor,function,organization,action,at,target):
        grant=read(ref,Authorization,historic=True,linked=True);assignment=read(function,RoleAssignment,historic=True,linked=True)
        roles={'SUPPLIER':'Supplier','CONTRACTOR':'Contractor','OWN':'Owner','QS':'QS','BANK':'Bank'}
        if (grant.actor_id!=actor or grant.organization_id!=organization or grant.function_ref!=function
                or assignment.function_ref!=function or assignment.role!=roles.get(action.split('-')[0]) or action not in grant.action_ids
                or not any(scope_covers(s,target) for s in grant.scopes)):
            raise ValueError('Supplier payment lacks original independent actor/function/scope authority')
        clock(at);clock(grant.validity.start)
        if at.offset>now.offset:_needs('received_original_supplier_payment_author_time',[ref])
        if not grant.validity.contains(at):_needs('original_supplier_payment_authority_at_execution',[ref])
        for basis_ref in [*grant.basis_refs,*assignment.basis_refs]:
            if basis_ref.kind=='Evidence':evidence([basis_ref],at=at)
            else:reading.resolve(basis_ref)
        return grant

    def author(row):
        clock(row.authored_at)
        if row.authored_at.offset>row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Payment source precedes original actual author execution')
        return authorize(row.author_authority_ref,row.author_actor_id,row.author_function_ref,row.author_organization_id,
            row.author_action_id,row.authored_at,row.scope)

    def cash(value,*,at=None,historic=False):
        evidence([value.basis_ref],at=at,historic=historic);amount=decimal_fraction(value.value)
        if value.currency!=rule.currency or amount<0:raise ValueError('Supplier payment changes original currency or is negative')
        return amount

    def amount(state,field):return cash(_known(state,field))

    def complete(choice,**fields):
        reading.recheck()
        return {'kind':'completed','payload':{'choice':choice,**fields,'note':rule.note+
            ' Request/draft only. Claim, due debt, actual cash, noncash offset and clearance remain separate. Customer/Owner late payment does not waive independent upstream debt; no project or Owner account is used.'}}

    def wait(code,refs):
        reading.recheck()
        return {'kind':'deferred','reason_code':code,'resume_condition':{'trigger':'dependency_change',
            'object_refs':refs,'earliest_time':None,'condition_code':code}}

    def debt(ref,debtor=None):
        row=read(ref,OwnerPaymentObligationView,linked=True);clock(row.as_of);clock(row.due_at)
        if (org not in {row.debtor_id,row.payee_id} or not scope_covers(scope,row.origin_scope)
                or debtor is not None and row.debtor_id!=debtor):
            raise ValueError('Supplier payment replaces actual legal debt or authorized origin scope')
        if row.as_of!=now:_needs('current_original_supplier_obligation',[ref])
        evidence(row.verification_evidence_refs)
        return row

    def components(row):
        keys(row.component_refs)
        due=paid=offset=Fraction(0);result={}
        for ref in row.component_refs:
            item=read(ref,OwnerPaymentComponentView,linked=True)
            if (item.obligation_ref!=row.ref or item.debtor_id!=row.debtor_id or item.payee_id!=row.payee_id
                    or item.source_ref!=row.source_ref or item.debt_ref!=row.debt_ref or item.as_of!=now):
                raise ValueError('Settlement component changes original obligation/loan/parties/source/snapshot')
            d=amount(item.actual_due,'component_due');p=amount(item.actual_cash_paid,'actual_component_cash_paid');o=amount(item.actual_offset,'actual_component_noncash_offset')
            if p+o>d:raise ValueError('Cash and noncash offset exceed original component value')
            due+=d;paid+=p;offset+=o;result[ref.key()]=(item,d-p-o)
        if (due!=amount(row.actual_due,'actual_debt_due') or paid!=amount(row.actual_paid,'actual_cash_paid')
                or offset!=amount(row.actual_offset,'actual_noncash_offset')):
            raise ValueError('Actual debt totals differ from complete original settlement components')
        return result

    try:
        rule=read(action_input.settlement_rule_ref,SupplierSettlementRuleView)
        if (rule.organization_id!=org or rule.actor_id!=context.actor_id or rule.function_ref!=context.function_ref
                or rule.scope!=scope or rule.authority_ref not in context.authorization_refs):
            raise ValueError('Supplier settlement changes original acting organization/authority')
        authorize(rule.authority_ref,context.actor_id,context.function_ref,org,'SUPPLIER-A10',now,scope)
        for field in ('order_refs','obligation_refs','delivery_evidence_refs','account_refs','execution_refs'):keys(getattr(action_input,field))

        if rule.choice=='seek_finance':
            draft=rule.financing
            if draft is None:_needs('original_supplier_financing_application_draft')
            if (draft.borrower_id!=org or draft.scope_ref!=scope or draft.applicant_authority_ref!=rule.authority_ref
                    or draft.lender_id==org or cash(draft.requested)<=0):
                raise ValueError('Supplier financing draft replaces actual borrower/scope/authority')
            purpose=read(draft.purpose_ref,FundingPurposeView,linked=True)
            if purpose.borrower_ref.id!=org or purpose.scope_ref!=scope:raise ValueError('Finance purpose belongs to another borrower')
            evidence(draft.disclosure_refs);keys(draft.disclosure_refs);keys(draft.product_candidates)
            for ref in draft.product_candidates:
                product=read(ref,FinanceProductProfileView,linked=True)
                if product.lender_id!=draft.lender_id:raise ValueError('Finance candidate belongs to another lender')
            return complete('seek_finance',application=draft.model_dump(mode='python'))

        ledger=read(rule.ledger_ref,SupplierPaymentLedgerView,linked=True);clock(ledger.as_of)
        if ledger.organization_id!=org or ledger.as_of!=now or ledger.coverage!='complete':
            _needs('complete_current_supplier_payment_and_claim_ledger')
        if keys(action_input.obligation_refs)!=keys(ledger.obligation_refs) or keys(action_input.execution_refs)!=keys(ledger.execution_refs):
            _needs('complete_original_supplier_payment_ledger_inputs')
        executions=[];commands=set();business=set()
        for ref in action_input.execution_refs:
            row=read(ref,OwnerPaymentExecutionView,historic=True,linked=True)
            identity=(row.organization_id,row.command_id);business_id=(row.organization_id,row.business_key)
            # Execution/receipt sources have no actual occurrence timestamp;
            # retain their original cash/unknown history without inventing one.
            if (row.organization_id!=org and row.beneficiary_id!=org or identity in commands or business_id in business or cash(row.amount,historic=True)<=0):
                raise ValueError('Payment history repeats original command/business or substitutes legal payer/beneficiary')
            commands.add(identity);business.add(business_id)
            if row.status in {'succeeded','failed','rejected'}:
                if row.receipt_ref is None:_needs('original_supplier_payment_execution_receipt',[ref])
                receipt=read(row.receipt_ref,OwnerPaymentReceiptView,historic=True,linked=True)
                if (receipt.execution_ref!=row.ref or receipt.command_id!=row.command_id or receipt.business_key!=row.business_key
                        or receipt.amount!=row.amount or receipt.beneficiary_id!=row.beneficiary_id or receipt.status!=row.status):
                    raise ValueError('Receipt changes original actual payment command/result')
            executions.append(row)
        by_execution={row.ref.key():row for row in executions}
        account_pending={}
        for ref in action_input.account_refs:
            own_account=read(ref,OwnerPaymentAccountView,historic=True,linked=True)
            if own_account.organization_id!=org:raise ValueError('Supplier history uses another organization account')
            keys(own_account.pending_execution_refs)
            for pending_ref in own_account.pending_execution_refs:
                key=pending_ref.key()
                if key in account_pending and account_pending[key]!=own_account.ref:
                    raise ValueError('Original Supplier pending payment is attributed to multiple accounts')
                account_pending[key]=own_account.ref
                prior=by_execution.get(key)
                if prior is not None and (prior.organization_id!=org or prior.account_ref!=own_account.ref):
                    raise ValueError('Supplier account pending payment changes original legal payer or exact account')
        if rule.choice=='reconcile':
            if not rule.execution_refs or not keys(rule.execution_refs)<=keys(action_input.execution_refs):
                raise ValueError('Payment reconciliation must query original existing execution IDs')
            return complete('reconcile',execution_refs=rule.execution_refs)
        if rule.choice=='dispute':
            if not rule.obligation_refs or not rule.issue_refs or not keys(rule.obligation_refs)<=keys(action_input.obligation_refs):
                _needs('original_existing_supplier_obligations_and_specific_dispute')
            for ref in rule.obligation_refs:debt(ref)
            covered=set()
            for ref in rule.issue_refs:
                issue=read(ref,SupplierPaymentIssueView)
                if issue.organization_id!=org or issue.status=='resolved':raise ValueError('Debt dispute changes original organization or closed issue')
                covered.update(keys(issue.obligation_refs))
            if not keys(rule.obligation_refs)<=covered:raise ValueError('Debt dispute omits original obligation-specific issues')
            return complete('dispute',obligation_refs=rule.obligation_refs)

        if rule.choice=='request_payment':
            draft=rule.claim
            if draft is None or not draft.lines or draft.settlement_rule_ref!=rule.ref:
                _needs('original_order_node_supplier_payment_claim_draft')
            if keys(draft.prior_claim_refs)!=keys(ledger.claim_refs):_needs('complete_original_supplier_claim_history')
            if len(rule.node_refs)!=len(draft.lines) or len(rule.valuation_refs)!=len(draft.lines):
                _needs('exact_original_contract_nodes_and_amount_results_for_claim_lines')
            keys(rule.node_refs);keys(rule.valuation_refs)
            orders={ref.key():read(ref,SupplierPaymentOrderView) for ref in action_input.order_refs}
            coverage=set();node_keys=set();expected_evidence=set()
            for line,node_ref,result_ref in zip(draft.lines,rule.node_refs,rule.valuation_refs):
                order_line=read(line.order_line_ref,SupplierPaymentOrderLineView)
                if order_line.order_ref.key() not in orders:raise ValueError('Claim line replaces original received order')
                order=orders[order_line.order_ref.key()]
                node=read(node_ref,SupplierOrderPaymentNodeView,evidence_at_field='authored_at');author(node);clock(node.as_of)
                node_authority=read(node.node_authority_ref,SupplierPaymentNodeAuthorityView,evidence_at_field='authored_at');author(node_authority)
                if (node_authority.order_ref!=order.ref or node_authority.payer_id!=order.payer_id
                        or node_authority.author_organization_id!=order.payer_id or node_authority.node_ref!=node.ref
                        or not true(node_authority.permitted) or node.author_organization_id!=node_authority.executor_organization_id
                        or node.author_actor_id!=node_authority.executor_actor_id or node.author_function_ref!=node_authority.executor_function_ref
                        or node.author_authority_ref!=node_authority.executor_authority_ref or node.author_action_id!=node_authority.executor_action_id
                        or node_authority.authored_at.offset>node.authored_at.offset
                        or not node_authority.effective_window.contains(node.authored_at)
                        or not scope_covers(node_authority.scope,node.scope)
                        or node.author_organization_id==org):
                    raise ValueError('Claim node substitutes original payer or independently delegated contract valuation authority')
                if (order.supplier_id!=org or order.payer_id!=draft.payer_id or order.currency!=rule.currency or not true(order.effective)
                        or line.order_line_ref.key() not in keys(order.line_refs) or node.ref.key() not in keys(order.node_refs)
                        or node.ref.key() not in keys(order_line.node_refs) or node.order_ref!=order.ref
                        or node.order_line_ref!=line.order_line_ref or node.payee_id!=org or node.payer_id!=draft.payer_id
                        or line.scope_ref!=node.scope or not scope_covers(scope,line.scope_ref) or not true(node.permitted)
                        or node.as_of!=now or node.coverage_key in coverage):
                    raise ValueError('Claim substitutes original contract payer, node coverage, scope or current entitlement basis')
                coverage.add(node.coverage_key);node_keys.add(node.ref.key())
                if not line.evidence_refs or not keys(node.evidence_refs)<=keys(line.evidence_refs):
                    _needs('original_contract_node_claim_evidence')
                # A claim carries original node/delivery evidence as well as
                # any new basis. Check each original use at its real time;
                # additional current claim evidence remains current below.
                evidence(line.evidence_refs,historic=True)
                original_line_evidence=keys(node.evidence_refs)
                if line.prior_component_ref!=node.prior_component_ref:raise ValueError('First claim invents or omits existing settlement component')
                if node.prior_component_ref is not None:
                    item=read(node.prior_component_ref,OwnerPaymentComponentView,linked=True)
                    if item.payee_id!=org or item.debtor_id!=draft.payer_id or item.obligation_ref.key() not in keys(action_input.obligation_refs):
                        raise ValueError('Existing claim component replaces original debtor/payee/debt')
                    outstanding=components(debt(item.obligation_ref))[item.ref.key()][1]
                    if cash(line.claimed)>outstanding:raise ValueError('Claim exceeds existing unpaid cash/offset remainder')
                expected_evidence.update(keys(node.delivery_evidence_refs))
                if node.purpose in {'delivery','inspection'} and not node.delivery_evidence_refs:
                    _needs('original_actual_delivery_or_inspection_basis_of_payment_node')
                delivery_kinds=set()
                for ref in node.delivery_evidence_refs:
                    if ref.key() not in keys(action_input.delivery_evidence_refs):_needs('original_contract_node_delivery_evidence',[ref])
                    delivery=read(ref,SupplierPaymentDeliveryView,historic=True,evidence_at_field='occurred_at');clock(delivery.occurred_at)
                    if (delivery.order_ref!=order.ref or delivery.order_line_ref!=order_line.ref or delivery.node_ref!=node.ref
                            or delivery.occurred_at.offset>now.offset or not keys(delivery.evidence_refs)<=keys(line.evidence_refs)):
                        raise ValueError('Claim delivery basis replaces actual original order/node/time')
                    delivery_kinds.add(delivery.kind)
                    original_line_evidence.update(keys(delivery.evidence_refs))
                evidence([ref for ref in line.evidence_refs if ref.key() not in original_line_evidence])
                if node.purpose=='inspection' and 'actual_inspection' not in delivery_kinds:
                    _needs('original_contract_required_actual_inspection_payment_basis')
                saved=read(result_ref,SupplierClaimValuationView,evidence_at_field='authored_at');grant=author(saved)
                if (saved.node_ref!=node.ref or saved.method_ref!=CLAIM_METHOD or saved.data!=node.data
                        or saved.input_sha256!=content_digest(node.data) or saved.authored_at.offset<node.available_at.offset
                        or not keys(node.data.source_refs)<=keys(grant.readable_refs) or node.ref.key() not in keys(node.data.source_refs)
                        or node.data.currency!=rule.currency):
                    raise ValueError('Claim amount result substitutes original authored contract quantities/prices/source rights')
                if saved.status=='failed':
                    raise ObservationGap({'kind':'technical_error','error':{'kind':'unrecorded','correlation_id':context.operation_id,
                        'code':'original-supplier-claim-valuation-failed'},'retryability':'unknown'})
                if saved.status=='unsupported':_unsupported('original-supplier-claim-valuation-support')
                if saved.status!='ok' or saved.report is None:_needs('original_calculable_supplier_contract_node_amount')
                evidence([node.data.quantity.basis_ref,node.data.unit_price.basis_ref,node.data.fixed_amount.basis_ref,
                    *[v.basis_ref for v in node.data.deduction_amounts]],at=saved.authored_at)
                for source_ref in node.data.source_refs:
                    source=reading.resolve(source_ref)
                    if isinstance(source,EvidenceRecord):evidence([source_ref],at=saved.authored_at)
                    if hasattr(source,'available_at'):
                        clock(source.available_at)
                        if source.available_at.offset>saved.authored_at.offset:
                            raise ValueError('Claim valuation precedes original contract-node amount sources')
                if historical_claim:
                    for basis_ref in walk_references(node.data):
                        if basis_ref.kind=='Evidence':
                            record=read(basis_ref,EvidenceRecord,historic=True,linked=True)
                            if record.effective_window is not None and not record.effective_window.contains(now):
                                _needs('original_current_claim_method_evidence',[basis_ref])
                    report=calculate_claim_amount(node.data)
                else:
                    result=reading.calculate(CLAIM_METHOD,node.data)
                    if result.kind!='ok':
                        if result.kind=='invalid_input':_unsupported('supplier-claim-amount-method-domain')
                        raw=result.model_dump(mode='python')
                        if result.kind=='needs_information':raw['requested_refs']=[]
                        raise ObservationGap(raw)
                    report=result.value
                if report!=saved.report or cash(line.claimed)!=decimal_fraction(report.payable) or not 0<cash(line.claimed)<=amount(node.remaining_claimable,'remaining_original_contract_node_claim_amount'):
                    raise ValueError('Claim amount differs from exact original contract node result or remaining coverage')
            if expected_evidence!=keys(action_input.delivery_evidence_refs):
                raise ValueError('Claim drops or mixes original supplied contract delivery basis')
            identities=set()
            for ref in draft.prior_claim_refs:
                previous=read(ref,SupplierPaymentClaimView,historic=True,linked=True);author(previous)
                if previous.organization_id!=org or previous.business_key in identities:raise ValueError('Claim history substitutes organization or repeats original business identity')
                identities.add(previous.business_key)
                if previous.business_key==rule.business_key:
                    if previous.claim.model_dump(exclude={'prior_claim_refs'})!=draft.model_dump(exclude={'prior_claim_refs'}):
                        raise ValueError('Existing claim business identity changes original content')
                    return wait('continue_original_supplier_payment_claim',[previous.ref])
                if previous.status not in {'withdrawn','rejected'} and (set(previous.coverage_keys)&coverage or keys(previous.node_refs)&node_keys):
                    return wait('continue_original_existing_contract_node_claim',[previous.ref])
            return complete('request_payment',claim=draft.model_dump(mode='python'))

        if rule.choice!='authorize_payment':_unsupported('supplier-settlement-choice')
        existing=[r.ref for r in executions if r.organization_id==org and r.business_key==rule.business_key]
        pending=[r.ref for r in executions if r.status in {'unknown','pending'}]
        if existing or pending:return complete('reconcile',execution_refs=existing or pending)
        if rule.account_ref is None or not rule.lines or rule.account_ref.key() not in keys(action_input.account_refs):
            _needs('own_actual_supplier_account_and_explicit_payment_allocations')
        account=read(rule.account_ref,OwnerPaymentAccountView,linked=True)
        if account.organization_id!=org or account.currency!=rule.currency:raise ValueError('Supplier cannot use project, Owner or another organization cash')
        if account.as_of!=now or account.coverage!='complete' or account.execution_coverage!='complete':_needs('complete_current_actual_supplier_cash_account')
        if account.pending_execution_refs:
            if not keys(account.pending_execution_refs)<=keys(action_input.execution_refs):_needs('original_pending_supplier_cash_commands',account.pending_execution_refs)
            for ref in account.pending_execution_refs:
                prior=by_execution[ref.key()]
                if prior.organization_id!=org or prior.account_ref!=account.ref:
                    raise ValueError('Pending Supplier account payment changes original payer or exact account')
            return complete('reconcile',execution_refs=account.pending_execution_refs)
        source=read(account.source_ref,OwnerPaymentSourceView,linked=True)
        if (source.organization_id!=org or source.account_ref!=account.ref or source.as_of!=now or source.coverage!='complete'
                or source.actual_cash!=account.actual_cash or source.restricted_cash!=account.restricted_cash):
            _needs('matching_current_actual_supplier_funding_source')
        held=Fraction(0);keys(account.reservation_refs)
        for ref in account.reservation_refs:
            reservation=read(ref,OwnerPaymentReservationView,linked=True)
            if reservation.account_ref!=account.ref or reservation.organization_id!=org or reservation.as_of!=now:
                raise ValueError('Cash reservation changes original account/organization/snapshot')
            evidence([reservation.disposition_basis_ref])
            if reservation.status=='held':held+=amount(reservation.amount,'held_supplier_cash_reservation')
        if held!=amount(account.reserved_cash,'actual_reserved_supplier_cash'):raise ValueError('Cash reservation total differs from original complete ledger')
        available=amount(account.actual_cash,'actual_supplier_cash')-amount(account.restricted_cash,'restricted_supplier_cash')-held
        if available<0:raise ValueError('Restricted/reserved funds exceed actual own cash')
        keys([l.obligation_ref for l in rule.lines])
        if len({l.priority for l in rule.lines})!=len(rule.lines):raise ValueError('Cash allocation requires explicit independent priorities')
        total=Fraction(0);used=set();output=[]
        for line in rule.lines:
            if line.obligation_ref.key() not in keys(action_input.obligation_refs) or line.obligation_ref.key() not in keys(account.obligation_refs):
                raise ValueError('Payment line leaves actual own account/debt coverage')
            obligation=debt(line.obligation_ref,org)
            if obligation.status!='effective' or not true(obligation.payable) or obligation.due_at.offset>now.offset:_needs('actual_due_payable_supplier_upstream_debt',[obligation.ref])
            if obligation.source_ref!=account.source_ref or line.payee_id!=obligation.payee_id:raise ValueError('Payment changes original debt funding source or payee')
            outstanding=components(obligation);allocated=Fraction(0);selected=[];keys([v.component_ref for v in line.component_amounts])
            for entry in line.component_amounts:
                key=entry.component_ref.key()
                if key in used or key not in outstanding:raise ValueError('Supplier payment repeats or replaces original debt component')
                item,remaining=outstanding[key];proposed=cash(entry.amount)
                if item.settlement_mode!='cash' or not 0<proposed<=remaining:raise ValueError('Cash payment repeats noncash offset or exceeds known unpaid amount')
                if proposed<remaining and not rule.allow_partial:_needs('explicit_partial_supplier_payment_authority')
                used.add(key);allocated+=proposed;selected.append(entry.component_ref)
            if allocated!=cash(line.amount) or allocated<=0:raise ValueError('Payment line differs from explicit original component amounts')
            if not rule.allow_partial and keys(selected)!={k for k,(v,r) in outstanding.items() if v.settlement_mode=='cash' and r>0}:
                _needs('explicit_partial_supplier_obligation_payment_authority')
            total+=allocated;output.append({'obligation_ref':obligation.ref,'payee_id':obligation.payee_id,'amount':line.amount,'component_refs':selected})
        if total>available:_needs('explicit_revised_supplier_priority_or_partial_allocation_within_actual_cash',[rule.ref,account.ref])
        return complete('authorize_payment',account_ref=account.ref,lines=output)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
