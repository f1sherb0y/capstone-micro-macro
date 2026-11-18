"""QS-A06 evaluates original bids without replacing bidder prices or buyer decisions."""
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.qs_bid_objects import (
    QSBidRoundView, QSBidView, QSBidEligibilityView, QSBidClarificationView,
    QSBidNormalizationBasisView, QSBidEvaluationProfileView, QSBidEvaluationRuleView,
    QSBidMethodResultView, QSBidExclusionAuthorityView, QSBidGapView,
)
from src.actions.contracts.qs_procurement_objects import QSProcurementDocumentView, QSProcurementGapView, QSProcurementResponseView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.methods.qs_bid import NORMALIZE_METHOD, RANK_METHOD, NormalizeInput, BidRankInput
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def evaluate_bids(context, action_input, reading):
    return _evaluate_bids(context, action_input, reading)


def prepare_bid_normalization(context, action_input, reading):
    """Prepare sourced comparison adjustments without reading an unproduced result.

    Reuse the original eligibility, clarification, price and adjustment checks;
    return before arithmetic, exclusion or an evaluation decision is performed.
    """
    return _evaluate_bids(context, action_input, reading, prepare_normalization=True)


def prepare_bid_ranking(context, action_input, reading):
    """Prepare ranking from original bids and saved normalization, without arithmetic."""
    return _evaluate_bids(context, action_input, reading, prepare_ranking=True)


def _evaluate_bids(context, action_input, reading, *, prepare_normalization=False, prepare_ranking=False):
    scope, now, sources = action_input.scope, context.business_time, {}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('qs-bid-clock-alignment')

    def current(window, at=now):
        clock(window.start); clock(at)
        return window.contains(at)

    def evidence(refs):
        for ref in refs:
            row=reading.resolve(ref)
            if not isinstance(row,EvidenceRecord):_unsupported('qs-bid-evidence-schema')
            if row.effective_window is not None and not current(row.effective_window):_needs('current_bid_evidence',[ref])

    def read(ref,schema,active=True):
        row=reading.resolve(ref)
        if not isinstance(row,schema):_unsupported('qs-bid-projection:'+ref.kind)
        evidence(getattr(row,'evidence_refs',[]))
        if hasattr(row,'scope') and row.scope!=scope:raise ValueError('Bid input changes original evaluation scope')
        if hasattr(row,'available_at'):
            clock(row.available_at)
            if row.available_at.offset>now.offset:_needs('received_bid_input',[ref])
            if active and not current(row.effective_window):_needs('current_bid_input',[ref])
        sources[ref.key()]=ref
        return row

    def authority(ref,actor,function,action,roles,at=now,organization=None):
        grant=read(ref,Authorization);assignment=read(function,RoleAssignment)
        evidence(grant.basis_refs+assignment.basis_refs)
        if (grant.actor_id!=actor or grant.function_ref!=function or assignment.role not in roles
                or (organization is not None and grant.organization_id!=organization)):
            raise ValueError('Bid source author or legal organization changes original grant')
        if not current(grant.validity,at) or action not in grant.action_ids or not any(scope_covers(s,scope) for s in grant.scopes):
            _needs('original_bid_evaluation_authority',[ref])

    def author(row,roles={'QS'},organization=None):
        assignment=read(row.author_function_ref,RoleAssignment)
        supported={'QS':{'QS-A05','QS-A06'},'Engineer':{'ENGINEER-A05','ENGINEER-A06','ENGINEER-A13'},
            'Government':{'GOV-A03','GOV-A04','GOV-A05'}}
        if row.author_action_id not in supported.get(assignment.role,set()):_unsupported('qs-bid-original-author-function')
        if isinstance(row,QSBidEligibilityView) and assignment.role=='QS':organization=reading.organization_id
        authority(row.author_authority_ref,row.author_actor_id,row.author_function_ref,row.author_action_id,roles,
            getattr(row,'calculated_at',getattr(row,'checked_at',row.available_at)),organization)

    def completed(choice,**fields):
        reading.recheck()
        return {'kind':'completed','payload':{'choice':choice,'scope':scope,
            'note':'Same-round cost advice only; original bid prices retained, unknown checks remain unresolved, no award, contract, obligation or cash effect',**fields}}

    def calculate(method,data):
        result=reading.calculate(method,data)
        if result.kind=='ok':return result.value
        if result.kind=='invalid_input':raise ValueError('Invalid original bid arithmetic or comparison domain')
        raw=result.model_dump(mode='python')
        if result.kind=='needs_information':raw['requested_refs']=[]
        raise ObservationGap(raw)

    def method_record(ref,kind,method,bids,bases):
        row=read(ref,QSBidMethodResultView);author(row,organization=reading.organization_id)
        if (row.kind!=kind or row.method_ref!=method or row.round_ref!=round_.ref or row.document_ref!=document.ref
                or row.profile_ref!=profile.ref or set(row.bid_refs)!=set(bids) or set(row.basis_refs)!=set(bases)):
            raise ValueError('Bid method result changes original round, document, profile, bids or normalization bases')
        clock(row.calculated_at)
        if row.calculated_at.offset>row.available_at.offset:_needs('received_original_bid_calculation',[ref])
        if (profile.available_at.offset>row.calculated_at.offset or document.available_at.offset>row.calculated_at.offset
                or any(read(bid,QSBidView).available_at.offset>row.calculated_at.offset for bid in bids)):
            _needs('bid_calculation_after_original_input_versions',[ref])
        if row.status=='unsupported':_unsupported('qs-bid-original-method-domain')
        if row.status=='failed':raise ObservationGap({'kind':'technical_error','error':{'kind':'unrecorded',
            'correlation_id':context.operation_id,'code':'original_bid_method_failed'},'retryability':'unknown'})
        return row

    try:
        round_=read(action_input.round_ref,QSBidRoundView)
        document=read(action_input.procurement_document_ref,QSProcurementDocumentView)
        author(document)
        profile=read(action_input.evaluation_profile_ref,QSBidEvaluationProfileView)
        if (round_.document_ref!=document.ref or document.round_ref!=round_.ref or document.status!='published'
                or profile.round_ref!=round_.ref or profile.document_ref!=document.ref
                or document.draft.procurement_scope_ref!=round_.procurement_scope_ref
                or profile.organization_id!=reading.organization_id or profile.function_ref!=context.function_ref):
            raise ValueError('Evaluation changes published original document, round or authorized QS function')
        authority(profile.authority_ref,context.actor_id,profile.function_ref,'QS-A06',{'QS'},organization=reading.organization_id)
        if round_.status=='cancelled':
            reading.recheck()
            return {'kind':'deferred','reason_code':'qs_bid_round_cancelled','resume_condition':{'trigger':'dependency_change',
                'object_refs':[round_.ref],'earliest_time':None,'condition_code':'qs.bid.active_evaluation_round'}}
        clock(profile.price_time)
        if profile.price_time.offset>now.offset:_needs('received_bid_comparison_time')
        for values in (action_input.bid_refs,action_input.clarification_refs,action_input.method_result_refs):unique_refs(values)
        if set(action_input.bid_refs)!=set(round_.bid_refs) or set(action_input.clarification_refs)!=set(round_.clarification_refs):
            _needs('complete_original_same_round_bids_and_clarifications')
        expected_methods={r for r in (profile.normalization_result_ref,profile.ranking_result_ref) if r is not None}
        if prepare_normalization:
            if action_input.method_result_refs:
                raise ValueError('Bid normalization production cannot consume saved method results')
            if profile.normalization_result_ref is None:
                _needs('declared_bid_normalization_target')
        elif prepare_ranking:
            if profile.ranking_result_ref is None:
                _needs('declared_bid_ranking_target')
            if profile.ranking_result_ref == profile.normalization_result_ref:
                raise ValueError('Ranking cannot replace or consume its own normalization target')
            dependencies={profile.normalization_result_ref} if profile.normalization_result_ref is not None else set()
            if set(action_input.method_result_refs)!=dependencies:
                _needs('exact_saved_bid_normalization_dependency')
        elif set(action_input.method_result_refs)!=expected_methods:_needs('exact_declared_bid_method_results')
        rules=[read(ref,QSBidEvaluationRuleView) for ref in profile.rule_refs]
        if any(r.round_ref!=round_.ref or r.document_ref!=document.ref for r in rules):raise ValueError('Evaluation rule belongs to another round or document')
        bids=[read(ref,QSBidView) for ref in action_input.bid_refs]
        by_bid={r.ref:r for r in bids};recipients={round_.buyer_id,*[r.bidder_id for r in bids]}
        questions,seen=[],set()

        def question(issue,bid=None,direct_ref=None):
            matches=[]
            for ref in ([direct_ref] if direct_ref is not None else profile.question_refs):
                row=read(ref,QSBidGapView)
                if row.issue!=issue or (bid is not None and row.bid_ref not in {None,bid}):continue
                response=read(row.response_requirement_ref,QSProcurementResponseView)
                if (row.procurement_scope_ref!=round_.procurement_scope_ref or row.round_ref!=round_.ref or row.document_ref!=document.ref
                        or response.procurement_scope_ref!=round_.procurement_scope_ref or response.round_ref!=round_.ref
                        or not set(row.recipient_ids)<=set(response.recipient_ids) or not set(row.recipient_ids)<=recipients
                        or 'procurement' not in row.blocking_uses):raise ValueError('Bid question changes original round or permitted recipients')
                matches.append(row)
                if row.ref.key() not in seen:
                    seen.add(row.ref.key());questions.append({'scope':scope,'target_refs':[row.ref],'question':row.question,
                        'recipient_ids':row.recipient_ids,'evidence_refs':row.evidence_refs,'blocking_uses':row.blocking_uses,
                        'response_requirement_ref':response.ref})
            if not matches:_needs('registered_bid_'+issue+'_question')

        clarifications={}
        for ref in action_input.clarification_refs:
            row=read(ref,QSBidClarificationView);bid=by_bid.get(row.bid_ref)
            if bid is None or row.round_ref!=round_.ref or row.document_ref!=document.ref:raise ValueError('Clarification reuses another bid, document version or procurement round')
            authority(row.response_authority_ref,row.response_author_id,row.response_function_ref,row.response_action_id,
                {'Contractor','Supplier'},row.available_at,bid.bidder_organization_id)
            if row.response_author_id!=bid.bidder_id:raise ValueError('Clarification substitutes another bidder')
            original_question=read(row.question_ref,QSBidGapView)
            if (original_question.round_ref!=round_.ref or original_question.procurement_scope_ref!=round_.procurement_scope_ref
                    or original_question.document_ref!=document.ref or original_question.bid_ref not in {None,bid.ref}):
                raise ValueError('Clarification answers an old round question')
            if row.bid_ref in clarifications:raise ValueError('Multiple unresolved clarification versions require an explicit current selection')
            if not row.confirms_original_price:question('pricing',bid.ref,row.question_ref)
            clarifications[row.bid_ref]=row
        evaluations,eligible,prices,normalization_inputs,basis_refs,failed={},[],{},[],[],{}
        failure_evidence={}
        risks,assessment_times={},{}
        for bid in bids:
            if bid.round_ref!=round_.ref or bid.document_ref!=document.ref:raise ValueError('Bid belongs to another original round or document')
            clock(bid.submitted_at);clock(bid.price_time)
            if bid.submitted_at.offset>bid.available_at.offset or bid.price_time.offset>now.offset:_needs('received_original_bid_time',[bid.ref])
            authority(bid.authority_ref,bid.bidder_id,bid.function_ref,bid.submission_action_id,{'Contractor','Supplier'},
                bid.submitted_at,bid.bidder_organization_id)
            evaluation={'bid_ref':bid.ref,'round_ref':round_.ref,'status':'not_comparable','normalization_result_refs':[],
                'rule_refs':profile.rule_refs,'unresolved_questions':[],'explanation':'Original comparison basis remains incomplete'}
            evaluations[bid.ref]=evaluation
            row_rules=[r for r in rules if r.predicate=='withdrawal' and r.consequence=='recommend_exclusion']
            if bid.status=='withdrawn':
                if not row_rules:question('clarification',bid.ref);continue
                failed[bid.ref]=row_rules;failure_evidence[bid.ref]=bid.evidence_refs
                evaluation.update(status='exclusion_recommended',explanation='Original bidder withdrew this bid; no automatic exclusion or award');continue
            clarification=clarifications.get(bid.ref)
            assessment_ref=clarification.assessment_ref if clarification is not None and clarification.assessment_ref is not None else bid.eligibility_ref
            if assessment_ref is None:
                question('eligibility',bid.ref);evaluation['status']='clarification_required';continue
            assessment=read(assessment_ref,QSBidEligibilityView);author(assessment,{'QS','Engineer','Government'})
            if (assessment.bid_ref!=bid.ref or assessment.round_ref!=round_.ref or assessment.document_ref!=document.ref
                    or set(assessment.rule_refs)!=set(profile.rule_refs)):
                raise ValueError('Eligibility assessment changes original bid, round, document or rules')
            clock(assessment.checked_at)
            if assessment.checked_at.offset>assessment.available_at.offset or assessment.checked_at.offset<bid.submitted_at.offset:
                _needs('original_bid_eligibility_check_time',[assessment.ref])
            if assessment.status=='failed':raise ObservationGap({'kind':'technical_error','error':{'kind':'unrecorded',
                'correlation_id':context.operation_id,'code':'original_bid_eligibility_check_failed'},'retryability':'unknown'})
            if assessment.status=='unsupported':_unsupported('qs-bid-eligibility-method-domain')
            row_rules=[r for r in rules if r.consequence=='recommend_exclusion' and
                ((r.predicate=='qualification' and assessment.qualified.state=='known' and not assessment.qualified.value)
                 or (r.predicate=='compliance' and assessment.compliant.state=='known' and not assessment.compliant.value))]
            if row_rules:
                failed[bid.ref]=row_rules;failure_evidence[bid.ref]=assessment.evidence_refs
                evaluation.update(status='exclusion_recommended',explanation='Original evidenced rule failure; recommendation only without independent exclusion authority');continue
            if (assessment.qualified.state!='known' or assessment.compliant.state!='known'
                    or not assessment.qualified.value or not assessment.compliant.value):
                question('eligibility',bid.ref);evaluation['status']='clarification_required';continue
            risks[bid.ref]=assessment.risk.value if assessment.risk.state=='known' else None
            assessment_times[bid.ref]=assessment.available_at
            if assessment.risk.state=='known':evidence([assessment.risk.value.basis_ref])
            if bid.price.state!='known':question('pricing',bid.ref);continue
            evidence([bid.price.value.basis_ref])
            if decimal_fraction(bid.price.value.value)<0:raise ValueError('Original bid price cannot be negative')
            if clarification is not None and not clarification.confirms_original_price:continue
            basis_ref=clarification.normalization_basis_ref if clarification is not None and clarification.normalization_basis_ref is not None else bid.normalization_basis_ref
            same=(bid.price.value.currency==profile.currency and bid.region_id==profile.region_id
                and bid.price_time==profile.price_time and set(bid.included_scope_keys)==set(profile.required_scope_keys))
            if same and basis_ref is None:
                eligible.append(bid.ref);prices[bid.ref]=bid.price.value;evaluation.update(status='comparable',explanation='Known eligible original price uses the declared exact comparison basis');continue
            if basis_ref is None or profile.normalization_result_ref is None:question('pricing',bid.ref);continue
            basis=read(basis_ref,QSBidNormalizationBasisView);author(basis,organization=reading.organization_id)
            if (basis.bid_ref!=bid.ref or basis.round_ref!=round_.ref or basis.document_ref!=document.ref
                    or basis.original_price!=bid.price.value or basis.target_currency!=profile.currency
                    or basis.target_region_id!=profile.region_id or basis.target_price_time!=profile.price_time
                    or set(basis.target_scope_keys)!=set(profile.required_scope_keys)):
                raise ValueError('Normalization basis changes original bid price or target comparison domain')
            differences={'scope:'+k for k in set(bid.included_scope_keys)^set(profile.required_scope_keys)}
            if bid.region_id!=profile.region_id:differences.add('region:'+bid.region_id+'->'+profile.region_id)
            if bid.price_time!=profile.price_time:differences.add('price_time:'+str(bid.price_time.offset)+'->'+str(profile.price_time.offset))
            if set(r.difference_key for r in basis.adjustments)!=differences or basis.fx_rate.state!='known':question('pricing',bid.ref);continue
            evidence([basis.fx_basis_ref,*[r.amount.basis_ref for r in basis.adjustments]])
            basis_refs.append(basis.ref)
            normalization_inputs.append({'bid_ref':bid.ref,'original_price':bid.price.value,'fx_rate':basis.fx_rate.value,
                'fx_basis_ref':basis.fx_basis_ref,'adjustments':basis.adjustments})
        if prepare_normalization:
            reading.recheck()
            return {'kind':'prepared', 'input':NormalizeInput(currency=profile.currency,
                bids=normalization_inputs,source_refs=list(sources.values())),
                'calculation_ref':profile.normalization_result_ref, 'round_ref':round_.ref,
                'document_ref':document.ref, 'profile_ref':profile.ref, 'basis_refs':basis_refs}
        if profile.normalization_result_ref is not None:
            normalized=[r['bid_ref'] for r in normalization_inputs]
            saved=method_record(profile.normalization_result_ref,'normalization',NORMALIZE_METHOD,normalized,basis_refs)
            if any(read(ref,QSBidNormalizationBasisView).available_at.offset>saved.calculated_at.offset for ref in basis_refs):
                _needs('normalization_after_original_bid_bases',[saved.ref])
            if prepare_ranking:
                normalized_prices=saved.prices
                if set(row.bid_ref for row in normalized_prices)!=set(normalized):
                    raise ValueError('Ranking normalization omits or adds an original comparable bid')
                if any(row.normalized_price.currency!=profile.currency for row in normalized_prices):
                    raise ValueError('Ranking normalization changes its original comparison currency')
            else:
                report=calculate(NORMALIZE_METHOD,NormalizeInput(currency=profile.currency,bids=normalization_inputs,source_refs=list(sources.values())))
                if saved.prices!=report.prices:raise ValueError('Saved normalized bid prices disagree with sourced exact arithmetic')
                normalized_prices=report.prices
            for row in normalized_prices:
                eligible.append(row.bid_ref);prices[row.bid_ref]=row.normalized_price
                evaluations[row.bid_ref].update(status='comparable',normalization_result_refs=[saved.ref],
                    explanation='Original price unchanged; saved sourced comparison adjustments rechecked')
        if profile.exclusion_bid_ref is not None and profile.exclusion_authority_ref is not None:
            bid=by_bid.get(profile.exclusion_bid_ref);row_rules=failed.get(profile.exclusion_bid_ref,[])
            if bid is None or profile.exclusion_rule_ref not in {r.ref for r in row_rules}:
                raise ValueError('Exclusion operation lacks an original evidenced rule failure for the selected bid')
            grant=read(profile.exclusion_authority_ref,QSBidExclusionAuthorityView,False)
            if (grant.round_ref!=round_.ref or grant.document_ref!=document.ref or grant.bid_ref!=bid.ref
                    or grant.rule_ref!=profile.exclusion_rule_ref or grant.delegate_actor_id!=context.actor_id
                    or grant.delegate_organization_id!=reading.organization_id or grant.delegate_function_ref!=context.function_ref):
                raise ValueError('Exclusion authority changes original delegate, bid, rule or round')
            clock(grant.granted_at)
            if grant.granted_at.offset>grant.available_at.offset:_needs('received_original_bid_exclusion_grant')
            authority(grant.buyer_authority_ref,round_.buyer_id,grant.buyer_function_ref,'OWN-A09',{'Owner'},
                grant.granted_at,round_.buyer_organization_id)
            if current(grant.effective_window) and grant.permission.state=='known' and grant.permission.value:
                return completed('exclude_authorized',bid_ref=bid.ref,rule_ref=profile.exclusion_rule_ref,
                    evidence_refs=list(dict.fromkeys([*bid.evidence_refs,*failure_evidence[bid.ref],*grant.evidence_refs,*[e for r in row_rules for e in r.evidence_refs]])))
        if questions and profile.on_unknown=='clarify':return completed('clarify',questions=questions)

        def attach_questions():
            for bid,entry in evaluations.items():
                entry['unresolved_questions']=[q for q in questions if read(q['target_refs'][0],QSBidGapView).bid_ref in {None,bid}]
                if entry['status']=='comparable' and entry['unresolved_questions']:
                    entry['status']='clarification_required'
                    entry['explanation']='Price calculation retained; unresolved original checks prevent complete comparison'
                    if bid in eligible:eligible.remove(bid)

        attach_questions()
        if not bids or len(failed)==len(bids):
            return completed('no_valid_bid',evaluations=list(evaluations.values()),reason='No submitted bid passes the original known rule checks; no contract or award is created')
        ranking_ref=None
        if profile.ranking_result_ref is not None and eligible:
            candidates=[r for r in eligible if risks.get(r) is not None or not any(c.metric=='risk' for c in profile.criteria)]
            if set(candidates)!=set(eligible):
                for ref in set(eligible)-set(candidates):question('pricing',ref)
                if profile.on_unknown=='clarify':return completed('clarify',questions=questions)
                attach_questions()
            else:
                if prepare_ranking:
                    for criterion in profile.criteria:evidence([criterion.basis_ref])
                    reading.recheck()
                    return {'kind':'prepared', 'input':BidRankInput(criteria=profile.criteria,
                        bids=[{'bid_ref':r,'price':prices[r],'risk':risks.get(r)} for r in candidates],
                        source_refs=list(sources.values())), 'calculation_ref':profile.ranking_result_ref,
                        'round_ref':round_.ref, 'document_ref':document.ref,
                        'profile_ref':profile.ref, 'basis_refs':basis_refs}
                saved=method_record(profile.ranking_result_ref,'ranking',RANK_METHOD,candidates,basis_refs)
                if profile.normalization_result_ref is not None and read(profile.normalization_result_ref,QSBidMethodResultView).calculated_at.offset>saved.calculated_at.offset:
                    _needs('ranking_after_original_normalization',[saved.ref])
                for ref in candidates:
                    bid=by_bid[ref]
                    if bid.available_at.offset>saved.calculated_at.offset or assessment_times[ref].offset>saved.calculated_at.offset:
                        _needs('ranking_after_original_bid_versions_and_checks',[saved.ref])
                for criterion in profile.criteria:evidence([criterion.basis_ref])
                report=calculate(RANK_METHOD,BidRankInput(criteria=profile.criteria,bids=[{'bid_ref':r,'price':prices[r],'risk':risks.get(r)} for r in candidates],source_refs=list(sources.values())))
                if saved.ranked_groups!=report.ranked_groups:raise ValueError('Saved ranking disagrees with explicit original criteria or exact tie groups')
                ranking_ref=saved.ref
        return completed('evaluate',evaluations=list(evaluations.values()),ranking_ref=ranking_ref)
    except ObservationGap as exc:
        reading.recheck()
        return exc.result
