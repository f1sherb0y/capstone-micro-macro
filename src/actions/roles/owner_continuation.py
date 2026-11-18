"""OWN-A13 proposes scoped changes; original unknown executions and duties survive."""
from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.owner_continuation_objects import (
    OwnerContinuationProfileView, OwnerContinuationStateView, OwnerContinuationContractView,
    OwnerContinuationRuleView, OwnerContinuationRiskView, OwnerContinuationDutyView,
    OwnerContinuationVerificationView, OwnerContinuationTaskView, OwnerContinuationCommitmentView,
    OwnerResourceReleaseRuleView, OwnerContinuationExecutionView, OwnerContinuationRightView,
    OwnerContinuationDocumentView, OwnerContinuationTransferPlanView, OwnerContinuationPermitView,
    OwnerPaymentObligationView, OwnerPaymentSourceView,
    OwnerContinuationConditionView, OwnerContinuationConsentView,
)
from src.actions.contracts.service_objects import ServiceScopeOrganizationView
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def decide_continuation(context, action_input, reading):
    now, owner, scope = context.business_time, reading.organization_id, context.scope

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('owner-continuation-clock-alignment')

    def evidence(refs):
        keys(refs)
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row,EvidenceRecord): _unsupported('owner-continuation-evidence-schema')
            if row.effective_window is not None: clock(row.effective_window.start)

    def read(ref, schema, historic=False, linked=False):
        row = reading.resolve(ref)
        if not isinstance(row,schema): _unsupported('owner-continuation-projection:'+ref.kind)
        if hasattr(row,'scope') and not linked and not scope_covers(scope,row.scope):
            raise ValueError('Continuation expands original invocation scope')
        evidence(getattr(row,'evidence_refs',[]))
        if hasattr(row,'available_at'):
            clock(row.available_at)
            if row.available_at.offset>now.offset: _needs('received_original_continuation_source',[ref])
        if hasattr(row,'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now): _needs('current_original_continuation_source',[ref])
        return row

    def true(value): return isinstance(value,Known) and value.value is True

    def authorize(ref,actor,function,organization,action,at,target):
        grant=read(ref,Authorization,historic=True,linked=True)
        assignment=read(function,RoleAssignment,historic=True,linked=True)
        roles={'OWN':'Owner','CONTRACTOR':'Contractor','SUPPLIER':'Supplier','BANK':'Bank',
               'QS':'QS','ARCHITECT':'Architect','ENGINEER':'Engineer','GOV':'Government'}
        if (grant.actor_id!=actor or grant.function_ref!=function or grant.organization_id!=organization
                or assignment.role!=roles.get(action.split('-')[0]) or action not in grant.action_ids
                or not any(scope_covers(s,target) for s in grant.scopes)):
            raise ValueError('Continuation replaces original author/function/party/action/scope authority')
        clock(at);clock(grant.validity.start)
        if not grant.validity.contains(at): _needs('original_continuation_authority_at_execution',[ref])
        evidence(grant.basis_refs+assignment.basis_refs)
        return grant

    def author(row):
        clock(row.authored_at)
        if row.authored_at.offset>row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Continuation source precedes its original author execution')
        return authorize(row.author_authority_ref,row.author_actor_id,row.author_function_ref,
            row.author_organization_id,row.author_action_id,row.authored_at,row.scope)

    def wait(refs):
        reading.recheck()
        return {'kind':'deferred','reason_code':'query_original_continuation_execution','resume_condition':{
            'trigger':'dependency_change','object_refs':refs,'earliest_time':None,
            'condition_code':'query_original_continuation_execution'}}

    def verify(ref,contract_ref=None):
        row=read(ref,OwnerContinuationVerificationView,linked=True);grant=author(row);clock(row.as_of)
        if (row.state_ref!=state.ref or row.state_sha256!=content_digest(state) or row.as_of!=now
                or row.contract_ref is not None and row.contract_ref.key() not in contracts
                or contract_ref is not None and row.contract_ref!=contract_ref
                or profile.choice not in row.permitted_choices or not scope_covers(row.checked_scope,target)
                or not row.source_digests):
            _needs('new_current_scope_and_version_bound_continuation_basis',[ref])
        if row.status=='failed':
            raise ObservationGap({'kind':'technical_error','error':{'kind':'unrecorded',
                'correlation_id':context.operation_id,'code':'original-continuation-verification-failed'},'retryability':'unknown'})
        if row.status=='unsupported': _unsupported('original-continuation-verification-domain')
        if row.status!='ok' or not true(row.supported): _needs('supported_original_continuation_condition',[ref])
        refs=[s.source_ref for s in row.source_digests]
        if not keys(refs)<=keys(grant.readable_refs): raise ValueError('Continuation verification lacks original source read rights')
        if row.family=='permits' and row.author_action_id.split('-')[0]!='GOV':
            raise ValueError('Continuation permit check lacks original regulatory authority')
        if row.family=='safety' and row.author_action_id.split('-')[0] not in {'ENGINEER','ARCHITECT','GOV'}:
            raise ValueError('Continuation safety check substitutes owner preference for professional authority')
        originals={'funding':state.funding_refs,'resources':state.resource_refs,'permits':state.permit_refs,
                   'rights':state.right_refs,'versions':state.contract_refs}
        if row.family in originals and not keys(originals[row.family])<=keys(refs):
            raise ValueError('Continuation check omits current original family sources')
        for item in row.source_digests:
            source=reading.resolve(item.source_ref)
            if content_digest(source)!=item.content_sha256: raise ValueError('Continuation reuses a check after original source content changed')
            if hasattr(source,'available_at'):
                clock(source.available_at)
                if source.available_at.offset>row.authored_at.offset: raise ValueError('Continuation check precedes original source availability')
        return row

    try:
        if action_input.scope_ref!=scope: raise ValueError('Continuation changes original invocation scope')
        profile=read(action_input.continuation_profile_ref,OwnerContinuationProfileView)
        state=read(profile.state_ref,OwnerContinuationStateView)
        if (profile.organization_id!=owner or profile.actor_id!=context.actor_id or profile.function_ref!=context.function_ref
                or profile.authority_ref not in context.authorization_refs or profile.scope!=scope
                or state.organization_id!=owner or state.scope!=scope):
            raise ValueError('Continuation substitutes original owner/actor/authority or full state scope')
        authorize(profile.authority_ref,context.actor_id,context.function_ref,owner,'OWN-A13',now,scope)
        clock(state.as_of)
        if state.as_of!=now or state.coverage!='complete': _needs('complete_current_formal_continuation_ledger')
        for field in ('risk_refs','contract_refs','resource_refs','obligation_refs'):
            if keys(getattr(action_input,field))!=keys(getattr(state,field)): _needs('complete_original_continuation_'+field)
        if keys(profile.retained_obligation_refs)!=keys(state.obligation_refs):
            raise ValueError('Retained-obligation declaration cannot omit or remove a formal original debt')
        target=profile.scope_choice.scope_ref
        if not profile.scope_choice.basis_refs or not scope_covers(scope,target):
            raise ValueError('Continuation requires explicit original affected scope and concrete basis')
        evidence(profile.scope_choice.basis_refs+profile.transfer_basis_refs)
        scope_rule=read(state.scope_rule_ref,OwnerContinuationRuleView,linked=True);author(scope_rule)
        if (scope_rule.contract_ref is not None or scope_rule.author_organization_id!=owner
                or not scope_covers(scope_rule.scope,target) or profile.choice not in scope_rule.permitted_choices
                or not true(scope_rule.permitted) or not scope_rule.recipient_ids):
            _needs('original_owner_scope_continuation_right')
        contracts={};rules={None:scope_rule}
        for ref in state.contract_refs:
            row=read(ref,OwnerContinuationContractView,linked=True);clock(row.as_of)
            if row.owner_id!=owner or row.as_of!=now: _needs('current_original_owner_contract_transition_state',[ref])
            contracts[ref.key()]=row
            if not scope_covers(row.scope,target): continue
            rule=read(row.rule_ref,OwnerContinuationRuleView,linked=True);author(rule)
            if (rule.contract_ref!=row.ref or rule.author_organization_id not in {owner,row.counterparty_id}
                    or profile.choice not in rule.permitted_choices or not true(rule.permitted) or not rule.recipient_ids):
                _needs('original_valid_contract_right_for_continuation_choice',[row.ref])
            rules[ref.key()]=rule
        if contracts and len(rules)==1: _needs('original_contract_permission_for_affected_scope')
        parties={owner,*[r.counterparty_id for r in contracts.values()]}
        obligations={}
        for ref in state.obligation_refs:
            obligation=read(ref,OwnerPaymentObligationView,linked=True);clock(obligation.as_of)
            if obligation.debtor_id not in parties or obligation.as_of!=now:
                _needs('current_original_remaining_formal_continuation_obligation',[ref])
            obligations[ref.key()]=obligation
        for contract in contracts.values():
            if not keys(contract.retained_obligation_refs)<=keys(state.obligation_refs) or not keys(contract.continuing_duty_refs)<=keys(state.retained_duty_refs):
                raise ValueError('Continuation omits original contract debt or continuing duties')
        duties={};keys(state.retained_duty_refs)
        for ref in state.retained_duty_refs:
            duty=read(ref,OwnerContinuationDutyView,linked=True)
            if duty.organization_id not in parties or not keys(duty.obligation_refs)<=keys(state.obligation_refs):
                raise ValueError('Continuation substitutes original safety/storage/debt duties')
            duties[ref.key()]=duty
        for ref in state.risk_refs:
            risk=read(ref,OwnerContinuationRiskView,historic=True,linked=True);author(risk);clock(risk.observed_at)
            if risk.organization_id!=owner or risk.observed_at.offset>risk.authored_at.offset or not keys(risk.affected_contract_refs)<=set(contracts):
                raise ValueError('Continuation risk replaces actual visible original time/owner/contracts')
        if isinstance(state.sunk_cost,Known): evidence([state.sunk_cost.value.basis_ref])

        executions={};business=set();events=set();keys(state.execution_refs)
        for ref in state.execution_refs:
            execution=read(ref,OwnerContinuationExecutionView,historic=True,linked=True)
            if (execution.organization_id!=owner or execution.run_id!=context.run_id or execution.state_ref.id!=state.ref.id
                    or execution.business_key in business or not keys(execution.resource_refs)<=keys(state.resource_refs)):
                raise ValueError('Continuation execution substitutes original run/business/state/resource identity')
            business.add(execution.business_key);executions[ref.key()]=execution
            if execution.status=='succeeded':
                if execution.core_event_id is None or execution.core_event_id in events:
                    raise ValueError('Continuation repeats or omits original actual core event')
                events.add(execution.core_event_id)
            elif execution.core_event_id is not None: raise ValueError('Unconfirmed continuation invents actual released resources')
            if execution.business_key==profile.business_key:
                original=read(execution.profile_ref,OwnerContinuationProfileView,historic=True,linked=True)
                metadata={'ref','state_ref','available_at','effective_window'}
                if (original.state_ref!=execution.state_ref or original.organization_id!=execution.organization_id
                        or original.scope!=execution.scope or original.business_key!=execution.business_key
                        or execution.profile_sha256!=content_digest(original)
                        or original.model_dump(exclude=metadata)!=profile.model_dump(exclude=metadata)):
                    raise ValueError('Continuation changes payload under original execution business identity')
                return wait([execution.ref])
        resources={};physical=set()
        for ref in state.resource_refs:
            resource=read(ref,OwnerContinuationCommitmentView,linked=True);clock(resource.as_of);clock(resource.window.start)
            if resource.owner_id!=owner or resource.as_of!=now or resource.physical_commitment_key in physical:
                raise ValueError('Continuation substitutes or aliases original current physical resource commitment')
            evidence([resource.quantity.basis_ref])
            if decimal_fraction(resource.quantity.value)<0 or not keys(resource.execution_refs)<=set(executions):
                raise ValueError('Continuation commitment changes original quantity or omits execution history')
            physical.add(resource.physical_commitment_key);resources[ref.key()]=resource

        checks={}
        for contract_key,rule in rules.items():
            for ref in rule.condition_refs:
                checked=verify(ref,contracts[contract_key].ref if contract_key is not None else None)
                if contract_key is None and checked.contract_ref is not None:
                    raise ValueError('Scope continuation condition substitutes contract-only permission')
                checks[ref.key()]=checked
        for ref in profile.scope_choice.condition_refs:
            condition=read(ref,OwnerContinuationConditionView,linked=True)
            if condition.verification_ref.key() not in checks: raise ValueError('Continuation choice substitutes an unreviewed original condition')
        if profile.choice in {'suspend','terminate'}:
            if profile.choice=='suspend' and profile.suspension_kind is None: _needs('explicit_reversible_or_irreversible_suspension')
            if profile.suspension_kind=='irreversible' and not all(r.allow_irreversible_suspension for r in rules.values()):
                _needs('original_permission_for_irreversible_suspension')
            required={r.key():r for rule in rules.values() for r in rule.protection_task_refs}
            required.update({r.key():r for duty in duties.values() if duty.kind in {'site_safety','storage'} and not (isinstance(duty.remains,Known) and duty.remains.value is False) for r in duty.task_refs})
            if keys(profile.protection_task_refs)!=set(required): _needs('all_original_required_continuing_site_protection_tasks')
            for ref in profile.protection_task_refs:
                task=read(ref,OwnerContinuationTaskView,linked=True);author(task)
                if (task.owner_id!=owner or task.contract_ref is not None and task.contract_ref.key() not in contracts
                        or task.kind not in {'site_protection','storage','safety'} or not true(task.permitted) or task.status in {'completed','cancelled'}):
                    _needs('original_authorized_continuing_protection_task',[ref])
            if not keys(profile.release_candidate_refs)<=set(resources): raise ValueError('Continuation releases unknown original resources')
            for ref in profile.release_candidate_refs:
                resource=resources[ref.key()]
                if not scope_covers(target,resource.scope):
                    raise ValueError('Continuation cannot release unaffected or shared whole-scope commitments')
                pending=[executions[r.key()].ref for r in resource.execution_refs if executions[r.key()].status in {'unknown','pending'}]
                if pending: return wait(pending)
                if resource.status not in {'held','committed'}: _needs('known_original_held_resource_before_release',[ref])
                rule=read(resource.release_rule_ref,OwnerResourceReleaseRuleView,linked=True);author(rule)
                if (rule.commitment_ref!=resource.ref or rule.author_organization_id!=resource.organization_id
                        or profile.choice not in rule.permitted_choices or not true(rule.permitted)):
                    _needs('original_resource_owner_release_right',[ref])
                for condition_ref in rule.condition_refs: verify(condition_ref)
        elif profile.choice=='resume':
            for key,rule in rules.items():
                if key is None:
                    if not true(rule.resume_permitted): _needs('new_original_owner_scope_resume_permission')
                    if not contracts and (state.status!='suspended' or state.suspension_kind!='reversible'):
                        _needs('original_reversible_own_scope_suspension')
                    continue
                contract=contracts[key]
                if contract.status!='suspended' or contract.suspension_kind!='reversible' or not true(rule.resume_permitted):
                    _needs('original_reversible_suspension_and_new_resume_permission',[contract.ref])
            pending=[e.ref for e in executions.values() if e.status in {'unknown','pending'}]
            if pending: return wait(pending)
            if any(r.status=='unknown' for r in resources.values()): _needs('current_known_original_resume_commitments')
            if not profile.readiness_refs: _needs('new_current_funding_resources_permits_rights_versions_and_safety_checks')
            readiness=[verify(ref) for ref in profile.readiness_refs];keys(profile.readiness_refs)
            required_families={'funding','resources','permits','rights','versions','safety'}
            for key in rules:
                if not required_families<={r.family for r in readiness if (r.contract_ref.key() if r.contract_ref is not None else None)==key}:
                    _needs('complete_new_readiness_for_each_affected_contract')
            for ref in state.funding_refs:
                source=read(ref,OwnerPaymentSourceView,linked=True);clock(source.as_of)
                if source.organization_id!=owner or source.as_of!=now or source.coverage!='complete': _needs('current_original_resume_funding_position',[ref])
                if not isinstance(source.actual_cash,Known) or not isinstance(source.restricted_cash,Known): _needs('actual_resume_cash_and_restrictions',[ref])
                cash,restricted=source.actual_cash.value,source.restricted_cash.value
                evidence([cash.basis_ref,restricted.basis_ref])
                if cash.currency!=restricted.currency or decimal_fraction(restricted.value)<0 or decimal_fraction(cash.value)<decimal_fraction(restricted.value):
                    raise ValueError('Resume funding invents cash or ignores original restrictions')
            for ref in state.permit_refs:
                permit=read(ref,OwnerContinuationPermitView,linked=True);author(permit)
                if permit.author_action_id.split('-')[0]!='GOV' or permit.status!='issued' or not scope_covers(permit.authorized_scope,target):
                    _needs('new_valid_original_resume_permit',[ref])
            for ref in state.right_refs:
                right=read(ref,OwnerContinuationRightView,linked=True);author(right)
                if right.holder_id!=owner or not true(right.permitted): _needs('current_original_owner_resume_right',[ref])
        elif profile.choice in {'replace','transfer'}:
            if (profile.successor_id is None or profile.successor_id==owner or profile.successor_ref is None
                    or profile.successor_ref.id!=profile.successor_id or not profile.transfer_basis_refs or profile.transfer_plan_ref is None):
                _needs('original_successor_and_separate_transfer_basis')
            read(profile.successor_ref,ServiceScopeOrganizationView,linked=True)
            plan=read(profile.transfer_plan_ref,OwnerContinuationTransferPlanView,linked=True);author(plan)
            if (plan.state_ref!=state.ref or plan.successor_id!=profile.successor_id or plan.choice!=profile.choice
                    or plan.author_organization_id!=owner or plan.status=='rejected' or not scope_covers(plan.scope,target)):
                raise ValueError('Continuation transfer plan substitutes original owner/successor/scope')
            original_refs=[*state.right_refs,*state.document_refs,*state.resource_refs,*state.contract_refs,*state.obligation_refs]
            if keys([i.source_ref for i in plan.items])!=keys(original_refs):
                raise ValueError('Transfer must separately cover rights, documents, resources, contracts and all original debts')
            if not plan.verification_refs: _needs('new_scope_bound_transfer_verifications')
            verified=[verify(ref) for ref in plan.verification_refs];keys(plan.verification_refs)
            if 'transfer' not in {r.family for r in verified}: _needs('new_original_successor_transfer_verification')
            if not any(r.family=='transfer' and {plan.ref.key(),profile.successor_ref.key()}<={d.source_ref.key() for d in r.source_digests} for r in verified):
                _needs('new_transfer_verification_bound_to_exact_plan_and_successor')
            for item in plan.items:
                if not item.basis_refs: _needs('specific_original_basis_for_each_transfer_item')
                evidence(item.basis_refs);reading.resolve(item.source_ref)
                required_parties=set()
                if item.source_ref.kind=='Obligation' and item.disposition!='retain':
                    obligation=obligations[item.source_ref.key()]
                    required_parties={obligation.debtor_id,obligation.payee_id,profile.successor_id}
                if item.source_ref.kind=='Contract' and item.disposition=='propose_transfer':
                    required_parties={owner,contracts[item.source_ref.key()].counterparty_id,profile.successor_id}
                if item.source_ref.kind=='ContinuationRight':
                    right=read(item.source_ref,OwnerContinuationRightView,linked=True);author(right)
                    if right.holder_id!=owner or item.disposition=='propose_transfer' and not true(right.transferable):
                        _needs('original_holder_and_transferable_right',[item.source_ref])
                    if item.disposition=='propose_transfer': required_parties={right.holder_id,profile.successor_id}
                if item.source_ref.kind=='ContinuationDocument':
                    document=read(item.source_ref,OwnerContinuationDocumentView,linked=True);author(document)
                    if document.organization_id!=owner or not true(document.permitted): _needs('original_document_handover_right',[item.source_ref])
                if item.source_ref.kind=='ResourceCommitment' and item.disposition!='retain':
                    pending=[executions[r.key()].ref for r in resources[item.source_ref.key()].execution_refs if executions[r.key()].status in {'unknown','pending'}]
                    if pending: return wait(pending)
                    if item.disposition=='propose_transfer': required_parties={resources[item.source_ref.key()].organization_id,profile.successor_id}
                accepted=set();keys(item.consent_refs)
                for consent_ref in item.consent_refs:
                    consent=read(consent_ref,OwnerContinuationConsentView,linked=True);author(consent)
                    if (consent.plan_ref!=plan.ref or consent.source_ref.key()!=item.source_ref.key()
                            or consent.successor_ref!=profile.successor_ref or consent.party_id!=consent.author_organization_id
                            or consent.party_id in accepted or consent.status!='active' or not true(consent.accepted)):
                        raise ValueError('Transfer consent substitutes original object/party/successor or repeats a party')
                    accepted.add(consent.party_id)
                if not required_parties<=accepted: _needs('original_required_party_and_creditor_consents_for_each_transfer_item')
        elif profile.choice=='reduce' and target==scope:
            _needs('explicit_strict_reduced_scope_preserving_unaffected_work')

        fields={'scope':profile.scope_choice.model_dump(mode='python'),'retained_obligation_refs':profile.retained_obligation_refs}
        if profile.choice in {'suspend','terminate'}: fields.update(protection_task_refs=profile.protection_task_refs,release_candidate_refs=profile.release_candidate_refs)
        if profile.choice=='resume': fields['readiness_refs']=profile.readiness_refs
        if profile.choice in {'replace','transfer'}: fields.update(successor_id=profile.successor_id,transfer_basis_refs=profile.transfer_basis_refs)
        reading.recheck()
        return {'kind':'completed','payload':{'choice':profile.choice,**fields,'note':profile.note+
            ' Proposal only; suspension kind: '+str(profile.suspension_kind)+'. Unaffected work remains subject to shared safety, permit and resource constraints. Protection, storage, sunk cost, original rights and outstanding debts survive. Release candidates are not actual releases; transfer items require separate authorized core execution and party acceptance, not automatic novation. Unknown original execution is queried under its original identity.'}}
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
