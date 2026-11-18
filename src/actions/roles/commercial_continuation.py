"""Commercial transitions preserve original facts and require independent succession."""
from src.actions.contracts.common import EvidenceRecord, Known, StrictRecord
from src.actions.contracts.commercial_continuation_objects import commercial_continuation_types
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.capacity import CAPACITY_METHOD, CapacityInput
from src.methods.commercial_learning import LESSON_METHOD, CommercialLessonInput, CommercialLessonSample
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def transition_commercial_business(context,action_input,reading,*,action_id='CONTRACTOR-A12',
        continuation_types=None,commitment_input='resource_commitment_refs',material_input='material_position_refs',
        check_extra=None,result_fields=None,readiness_families=None,extra_source_fields=(),extra_transfer_fields=(),extra_material_fields=()):
    types=continuation_types or commercial_continuation_types()
    now,org,scope=context.business_time,reading.organization_id,context.scope

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def clock(point):
        if point.clock_ref!=now.clock_ref: _unsupported('commercial-continuation-clock-alignment')

    def evidence(refs,*,at=None,historic=False):
        point=now if at is None else at
        clock(point)
        if point.offset>now.offset: _needs('received_original_commercial_transition_evidence_time')
        for ref in refs:
            row=reading.resolve(ref)
            if not isinstance(row,EvidenceRecord): _unsupported('commercial-continuation-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start);clock(row.effective_window.end)
                if row.effective_window.start.offset>now.offset: _needs('received_original_commercial_transition_evidence',[ref])
                if (at is not None or not historic) and not row.effective_window.contains(point):
                    _needs('original_commercial_transition_evidence_valid_at_use',[ref])

    def read(ref,schema,historic=False,linked=False,*,evidence_at_field=None):
        row=reading.resolve(ref)
        if not isinstance(row,schema): _unsupported('commercial-continuation-projection:'+ref.kind)
        if hasattr(row,'scope') and not linked and not scope_covers(scope,row.scope):
            raise ValueError('Commercial transition expands original invocation scope')
        if hasattr(row,'available_at'):
            clock(row.available_at)
            if row.available_at.offset>now.offset: _needs('received_original_commercial_transition_source',[ref])
        if hasattr(row,'effective_window'):
            clock(row.effective_window.start);clock(row.effective_window.end)
            if not historic and not row.effective_window.contains(now): _needs('current_original_commercial_transition_source',[ref])
        point=None if evidence_at_field is None else getattr(row,evidence_at_field)
        if point is not None:
            clock(point)
            if point.offset>now.offset: _needs('received_original_commercial_transition_evidence_time',[ref])
            if point.offset>row.available_at.offset:
                raise ValueError('Commercial transition source precedes its actual event or authorship')
        evidence(getattr(row,'evidence_refs',[]),at=point,historic=historic)
        return row

    def true(value): return isinstance(value,Known) and value.value is True

    def authorize(ref,actor,function,organization,action,at,target):
        grant=read(ref,Authorization,historic=True,linked=True);assignment=read(function,RoleAssignment,historic=True,linked=True)
        roles={'CONTRACTOR':'Contractor','SUPPLIER':'Supplier','OWN':'Owner','BANK':'Bank','GOV':'Government',
               'ARCHITECT':'Architect','ENGINEER':'Engineer','QS':'QS'}
        if (grant.actor_id!=actor or grant.function_ref!=function or grant.organization_id!=organization
                or assignment.function_ref!=function or assignment.role!=roles.get(action.split('-')[0])
                or action not in grant.action_ids or not any(scope_covers(s,target) for s in grant.scopes)):
            raise ValueError('Commercial transition substitutes original actor/function/party/action/scope authority')
        clock(at);clock(grant.validity.start);clock(grant.validity.end)
        if at.offset>now.offset: _needs('received_original_commercial_transition_author_time',[ref])
        if not grant.validity.contains(at): _needs('original_commercial_transition_authority_at_execution',[ref])
        for basis_ref in [*grant.basis_refs,*assignment.basis_refs]:
            if basis_ref.kind=='Evidence': evidence([basis_ref],at=at)
            else: reading.resolve(basis_ref)

    def author(row,own=False):
        clock(row.authored_at)
        if row.authored_at.offset>row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Commercial transition source precedes original author execution')
        if own and row.author_organization_id!=org: raise ValueError('Commercial transition replaces original firm author')
        authorize(row.author_authority_ref,row.author_actor_id,row.author_function_ref,row.author_organization_id,
            row.author_action_id,row.authored_at,row.scope)

    def wait(ref,code='query_original_commercial_transition_execution'):
        reading.recheck()
        return {'kind':'deferred','reason_code':code,'resume_condition':{'trigger':'dependency_change','object_refs':[ref],
            'earliest_time':None,'condition_code':code}}

    def calculate(method,data):
        result=reading.calculate(method,data)
        if result.kind!='ok':
            if result.kind=='invalid_input': _unsupported('commercial-continuation-method-domain')
            raw=result.model_dump(mode='python')
            if result.kind=='needs_information': raw['requested_refs']=[]
            raise ObservationGap(raw)
        return result.value

    def complete(**fields):
        if result_fields is not None: fields=result_fields(profile,state,fields)
        reading.recheck()
        return {'kind':'completed','payload':{'choice':profile.choice,**fields,'note':profile.note+
            ' Proposal only. Resource releases/material transfers need actual authorized core transition; debts, disputes, protection, past work/authorship and late original execution remain. Successor may execute only new remaining work and never count inherited completed work as its own. No bankruptcy, automatic completion, cash clearance or capacity improvement is inferred.'}}

    def observation(ref):
        row=read(ref,types['Observation'],historic=True,linked=True,evidence_at_field='authored_at');author(row)
        clock(row.observed_at);clock(row.received_at)
        if row.recipient_organization_id!=org: raise ValueError('Lesson consumes another firm private observations')
        if row.received_at.offset>now.offset: _needs('actually_received_commercial_observation',[ref])
        if row.observed_at.offset>row.authored_at.offset or row.available_at.offset>row.received_at.offset:
            raise ValueError('Lesson changes original observation knowledge chronology')
        source=read(row.original_source_ref,StrictRecord,historic=True,linked=True)
        if content_digest(source)!=row.source_sha256: raise ValueError('Lesson changes original outcome source content')
        if hasattr(source,'available_at') and source.available_at.offset>row.received_at.offset:
            raise ValueError('Lesson injects source received after original observation')
        return row

    try:
        if action_input.scope_ref!=scope: raise ValueError('Commercial continuation changes invocation scope')
        profile=read(action_input.continuation_profile_ref,types['ContinuationProfile'],evidence_at_field='authored_at');author(profile,own=True)
        state=read(profile.state_ref,types['ContinuationState'])
        if (profile.organization_id!=org or state.organization_id!=org or state.run_id!=context.run_id
                or profile.scope!=scope or state.scope!=scope or profile.actor_id!=context.actor_id
                or profile.function_ref!=context.function_ref or profile.authority_ref not in context.authorization_refs):
            raise ValueError('Commercial transition changes original firm/run/scope/actor/authority')
        authorize(profile.authority_ref,context.actor_id,context.function_ref,org,action_id,now,scope)
        if profile.monthly_bid_policy_ref is not None or profile.monthly_bid_observation_ref is not None:
            if profile.monthly_bid_policy_ref is None or profile.monthly_bid_observation_ref is None:
                raise ValueError('Monthly private bid policy requires both current authorized sources')
            if profile.learning_method_ref is None:
                raise ValueError('Monthly private bid policy requires its declared original rule descriptor')
            rule=read(profile.learning_method_ref,types['LearningMethod'],evidence_at_field='authored_at');author(rule,own=True)
            if (rule.organization_id!=org or not true(rule.supported)
                    or rule.calculation_method_ref.id!='micro.contractor.monthly_material_risk_rule'
                    or rule.effect!='future_private_lesson_only'):
                raise ValueError('Monthly strategy rule is not the selected private material-risk mechanism')
            for ref in action_input.observation_refs:
                original_observation=observation(ref)
                if (not true(original_observation.verified) or original_observation.observed_at!=now
                        or original_observation.outcome_code!='actual_native_material_index_observation'):
                    raise ValueError('Monthly strategy requires its actual current received native input observation')
            from src.actions.roles.contractor_monthly_strategy import analyze_monthly_bid_strategy
            judgment=analyze_monthly_bid_strategy(context,action_input,reading,profile=profile,state=state,action_id=action_id)
            reading.recheck()
            return {'kind':'completed','payload':{'choice':'record_lesson','source_refs':profile.source_refs,
                'learning_method_ref':profile.learning_method_ref,'note':judgment.model_dump_json()}}
        clock(state.as_of)
        if state.as_of!=now or state.coverage!='complete': _needs('complete_current_original_commercial_state')
        evidence(action_input.authority_basis_refs)
        if not action_input.authority_basis_refs: _needs('original_authority_evidence_for_commercial_transition')
        for supplied,original in [(commitment_input,'commitment_refs'),(material_input,'material_refs'),('obligation_refs','obligation_refs'),('observation_refs','observation_refs')]:
            if keys(getattr(action_input,supplied))!=keys(getattr(state,original)): _needs('all_original_commercial_'+original)
        business=set();keys(state.execution_refs)
        for ref in state.execution_refs:
            execution=read(ref,types['ContinuationExecution'],historic=True,linked=True)
            if execution.organization_id!=org or execution.run_id!=context.run_id or execution.state_ref.id!=state.ref.id or execution.business_key in business:
                raise ValueError('Commercial transition history changes original run/firm/state/business identity')
            business.add(execution.business_key)
            if execution.business_key==profile.business_key:
                original=read(execution.profile_ref,types['ContinuationProfile'],historic=True,linked=True,evidence_at_field='authored_at')
                author(original,own=True)
                metadata={'ref','state_ref','available_at','effective_window'}
                if (original.state_ref!=execution.state_ref or original.organization_id!=execution.organization_id
                        or original.scope!=execution.scope or original.business_key!=execution.business_key
                        or execution.profile_sha256!=content_digest(original)
                        or original.model_dump(exclude=metadata)!=profile.model_dump(exclude=metadata)):
                    raise ValueError('Commercial transition changes original content under old business identity')
                return wait(ref)
            if execution.status in {'pending','unknown'}: return wait(ref)
        basis=read(profile.basis_ref,types['ContinuationBasis'],evidence_at_field='authored_at');author(basis)
        contracts={};keys(state.contract_refs)
        for ref in state.contract_refs:
            contract=read(ref,types['Contract'],historic=True,linked=True);author(contract)
            if org not in contract.party_organization_ids or basis.ref.key() not in keys(contract.transition_basis_refs):
                raise ValueError('Commercial transition has no original contract-party transition right')
            contracts[ref.key()]=contract
        if (basis.organization_id!=org or basis.state_ref!=state.ref or not true(basis.permitted)
                or profile.choice not in basis.allowed_choices or keys(basis.contract_refs)!=set(contracts)
                or not keys(basis.evidence_refs)<=keys(action_input.authority_basis_refs)):
            _needs('original_valid_commercial_transition_right')
        commitments={};physical=set()
        for ref in state.commitment_refs:
            row=read(ref,types['ResourceCommitment'],linked=True);clock(row.as_of)
            if row.organization_id!=org or row.as_of!=now or row.physical_commitment_key in physical:
                raise ValueError('Commercial transition repeats or substitutes actual original commitment')
            physical.add(row.physical_commitment_key);commitments[ref.key()]=row
        for ref in state.obligation_refs:
            row=read(ref,types['Obligation'],linked=True);clock(row.as_of)
            if row.as_of!=now or org not in {row.debtor_id,row.payee_id}: _needs('original_current_remaining_commercial_obligation',[ref])
        material_plan=read(basis.material_plan_ref,types['MaterialDispositionPlan'],evidence_at_field='authored_at');author(material_plan,own=True)
        if material_plan.organization_id!=org or material_plan.state_ref!=state.ref or keys([i.position_ref for i in material_plan.items])!=keys([
                *state.material_refs,*[ref for field in extra_material_fields for ref in getattr(state,field)]]):
            raise ValueError('Commercial transition omits original material dispositions')
        materials={};physical=set();dispositions={i.position_ref.key():i for i in material_plan.items}
        for ref in state.material_refs:
            row=read(ref,types['InventoryPosition'],linked=True);clock(row.as_of)
            if row.organization_id!=org or row.custodian_organization_id!=org or row.as_of!=now or row.physical_position_key in physical or row.coverage!='complete':
                _needs('complete_current_original_material_custody',[ref])
            physical.add(row.physical_position_key);materials[ref.key()]=row
            item=dispositions[ref.key()];right=read(item.right_ref,types['AssetRight'],linked=True,evidence_at_field='authored_at');author(right)
            if (row.right_ref!=right.ref or right.position_ref!=row.ref or right.owner_organization_id!=row.owner_organization_id
                    or right.custodian_organization_id!=org or right.author_organization_id!=row.owner_organization_id
                    or not true(right.permitted) or item.choice not in right.permitted_choices
                    or item.recipient_organization_id not in right.allowed_recipient_organization_ids):
                _needs('original_owner_authorized_material_preservation_or_disposition',[ref])
            if row.status=='unknown' and item.choice!='query_original': return wait(ref,'query_original_material_position')
            if profile.choice in {'protect','suspend'} and item.choice not in {'preserve','retain_custody','query_original'}:
                raise ValueError('Protection/suspension cannot silently transfer original materials')
        work_records={};physical=set();keys(state.work_record_refs)
        for ref in state.work_record_refs:
            row=read(ref,types['OriginalWorkRecord'],historic=True,linked=True);author(row,own=True)
            execution=read(row.execution_ref,types['OriginalWorkExecution'],linked=True);clock(execution.as_of)
            if (row.organization_id!=org or row.contract_ref.key() not in contracts or row.physical_work_key in physical
                    or execution.organization_id!=org or execution.run_id!=context.run_id or execution.work_record_ref!=row.ref or execution.as_of!=now):
                raise ValueError('Commercial handover substitutes original physical work or execution')
            if execution.status in {'pending','unknown'} and profile.choice not in {'protect','suspend','record_lesson'}:
                return wait(execution.ref,'query_original_late_work_execution')
            if row.status=='completed' and execution.status!='succeeded': raise ValueError('Commercial transition cannot invent completed work from failed execution')
            physical.add(row.physical_work_key);work_records[ref.key()]=row
        documents={};keys(state.document_refs)
        for ref in state.document_refs:
            row=read(ref,types['ContinuationDocument'],historic=True,linked=True,evidence_at_field='authored_at');author(row,own=True)
            if row.organization_id!=org or row.original_author_id!=row.author_actor_id: raise ValueError('Commercial handover changes original document author')
            documents[ref.key()]=row
        duties={};keys(state.responsibility_refs)
        for ref in state.responsibility_refs:
            row=read(ref,types['ContinuingResponsibility'],linked=True);author(row,own=True)
            if row.organization_id!=org or row.contract_ref.key() not in contracts or not keys(row.required_commitment_refs)<=set(commitments):
                raise ValueError('Commercial transition omits original continuing responsibility or resource duty')
            duties[ref.key()]=row
        if check_extra is not None:
            extra_result=check_extra(profile,state,basis,materials,read,author,evidence,clock,wait)
            if extra_result is not None: return extra_result
        if profile.choice=='record_lesson':
            if profile.learning_method_ref is None or not profile.source_refs or not keys(profile.source_refs)<=keys(state.observation_refs):
                _needs('selected_original_learning_method_and_private_observations')
            method=read(profile.learning_method_ref,types['LearningMethod'],evidence_at_field='authored_at');author(method,own=True)
            if method.organization_id!=org or not true(method.supported) or method.calculation_method_ref!=LESSON_METHOD:
                _unsupported('selected_commercial_learning_mechanism')
            applied={};keys(state.applied_observation_refs)
            if not keys(state.applied_observation_refs)<=keys(state.observation_refs): raise ValueError('Commercial lesson history applies unreceived event')
            for ref in state.applied_observation_refs:
                row=observation(ref);identity=(row.source_sha256,row.outcome_code)
                if row.event_key in applied and applied[row.event_key]!=identity:
                    raise ValueError('Applied commercial history changes original event outcome')
                applied[row.event_key]=identity
            selected={};applied_outcomes=set(applied.values());selected_outcomes=set()
            for ref in profile.source_refs:
                row=observation(ref)
                if not true(row.verified): _needs('verified_original_commercial_lesson_outcome',[ref])
                if row.event_key in applied:
                    if applied[row.event_key]!=(row.source_sha256,row.outcome_code): raise ValueError('Applied commercial event changes original source/outcome')
                    continue
                if row.event_key in selected and (selected[row.event_key].source_sha256,selected[row.event_key].outcome_code)!=(row.source_sha256,row.outcome_code):
                    raise ValueError('Commercial lesson repeats event with different original outcome')
                identity=(row.source_sha256,row.outcome_code)
                if identity in applied_outcomes or identity in selected_outcomes: continue
                selected.setdefault(row.event_key,row)
                selected_outcomes.add(identity)
            if not selected: return wait(state.ref,'commercial_lesson_already_applied')
            data=CommercialLessonInput(samples=[CommercialLessonSample(observation_ref=r.ref,event_key=r.event_key,outcome_code=r.outcome_code) for r in selected.values()],
                outcome_catalog=method.outcome_catalog,source_refs=[state.ref,method.ref,*[r.ref for r in selected.values()]])
            if profile.lesson_assessment_ref is None: _needs('saved_original_commercial_lesson_assessment')
            saved=read(profile.lesson_assessment_ref,types['CommercialLessonAssessment'],evidence_at_field='authored_at');author(saved,own=True)
            if saved.organization_id!=org or saved.learning_method_ref!=method.ref or saved.data!=data or saved.input_sha256!=content_digest(data):
                raise ValueError('Commercial lesson assessment changes original received events or mechanism')
            if saved.status=='unsupported': _unsupported('commercial-lesson-assessment-domain')
            if saved.status!='ok' or saved.report is None: _needs('successful_original_commercial_lesson_assessment',[saved.ref])
            if calculate(LESSON_METHOD,data)!=saved.report: raise ValueError('Commercial lesson report differs from original finite mechanism')
            return complete(source_refs=[r.ref for r in selected.values()],learning_method_ref=method.ref)
        retained=keys(profile.retain_resource_refs);released=keys(profile.release_candidate_refs)
        if retained&released or retained|released!=set(commitments): raise ValueError('Commercial transition must partition original commitments')
        for key in released:
            row=commitments[key]
            if row.status=='unknown': return wait(row.ref,'query_original_commercial_resource_commitment')
            if row.status!='held': raise ValueError('Commercial transition cannot release an already released or consumed commitment')
            rule=read(row.release_rule_ref,types['ResourceReleaseRule'],evidence_at_field='authored_at');author(rule,own=True)
            if rule.organization_id!=org or rule.commitment_ref!=row.ref or profile.choice not in rule.allowed_choices or not true(rule.permitted) or not true(rule.verified):
                _needs('original_authorized_actual_transition_resource_release',[row.ref])
        required=set();keys(basis.protection_task_refs)
        for ref in basis.protection_task_refs:
            task=read(ref,types['ProtectionTask']);author(task,own=True)
            if task.organization_id!=org or task.state_ref!=state.ref or not true(task.permitted): _needs('original_continuing_site_protection_task',[ref])
            if task.status=='required': required.update(keys(task.required_commitment_refs))
        for duty in duties.values():
            if duty.status!='complete': required.update(keys(duty.required_commitment_refs))
        if not required<=retained: raise ValueError('Commercial transition releases resources still needed for protection/support duty')
        fields={'scope_ref':scope,'retain_resource_refs':profile.retain_resource_refs,'release_candidate_refs':profile.release_candidate_refs,
            'remaining_obligation_refs':state.obligation_refs}
        if profile.choice=='resume':
            verifications={};keys(profile.readiness_refs)
            source_keys=keys([*state.contract_refs,*state.commitment_refs,*state.material_refs,*state.obligation_refs,*state.work_record_refs,*state.responsibility_refs,
                *[ref for field in extra_source_fields for ref in getattr(state,field)]])
            verified_sources=set()
            for ref in profile.readiness_refs:
                row=read(ref,types['Verification'],evidence_at_field='authored_at');author(row);clock(row.as_of)
                if row.organization_id!=org or row.state_ref!=state.ref or row.state_sha256!=content_digest(state) or row.as_of!=now or row.family in verifications:
                    raise ValueError('Resume substitutes original current readiness snapshot or duplicate family')
                if not true(row.supported): _unsupported('commercial-resume-readiness-mechanism')
                if not true(row.ready): return wait(ref,'commercial_resume_readiness_pending')
                keys([r.source_ref for r in row.source_digests])
                for source in row.source_digests:
                    original=read(source.source_ref,StrictRecord,linked=True)
                    if content_digest(original)!=source.source_sha256: raise ValueError('Resume changes current original source version/content')
                    verified_sources.add(source.source_ref.key())
                verifications[row.family]=row
            if set(verifications)!=(readiness_families or {'resources','materials','design','permits','funding','safety'}) or not source_keys<=verified_sources:
                _needs('all_original_current_resume_resource_material_design_permit_funding_safety_sources')
            verification=verifications['resources']
            if state.resource_calendar_ref is None: _needs('current_original_resume_capacity_calendar')
            calendar=read(state.resource_calendar_ref,types['ResourceCalendar'],evidence_at_field='authored_at');author(calendar,own=True);clock(calendar.as_of)
            if calendar.organization_id!=org or calendar.as_of!=now or calendar.coverage!='complete': _needs('current_complete_cross_contract_resource_calendar')
            ids={r.resource_ref.id for r in calendar.resources}
            if (len(ids)!=len(calendar.resources) or ids!=set(calendar.actual_resource_keys)
                    or len(set(calendar.actual_resource_keys.values()))!=len(calendar.actual_resource_keys)):
                raise ValueError('Resume duplicates actual shared resource under new ids')
            for resource in calendar.resources:
                evidence([resource.total.basis_ref]);clock(resource.effective_window.start);clock(resource.effective_window.end)
            for demand in calendar.authorized_new_demands:
                clock(demand.window.start);clock(demand.window.end);evidence(demand.basis_refs)
                if demand.window.start.offset<now.offset or demand.window.end.offset<=demand.window.start.offset:
                    raise ValueError('Resume cannot reuse an old or empty new-resource demand window')
            existing=keys(calendar.existing_work_commitment_refs)
            if not existing<=retained or any(commitments[key].status!='held' for key in existing):
                raise ValueError('Resume must preserve original held resources covering continuing work')
            for commitment in commitments.values():
                if commitment.status=='held' and not any(c.commitment_ref==commitment.ref and c.resource_ref==commitment.resource_ref
                        and c.quantity==commitment.quantity and c.window==commitment.window for c in calendar.commitments):
                    raise ValueError('Resume calendar omits original actual occupied commitment')
            if not calendar.authorized_new_demands:
                if not existing: _needs('explicit_original_work_covered_by_existing_hold_or_new_demand')
                fields['readiness_refs']=profile.readiness_refs
                return complete(**fields)
            if verification.capacity_assessment_ref is None: _needs('current_original_resume_new_demand_capacity_assessment')
            data=CapacityInput(clock_ref=now.clock_ref,resources=calendar.resources,commitments=calendar.commitments,
                demands=calendar.authorized_new_demands,source_refs=[state.ref,calendar.ref,*state.commitment_refs])
            saved=read(verification.capacity_assessment_ref,types['ContinuationCapacityAssessment'],evidence_at_field='authored_at');author(saved,own=True);clock(saved.executed_at)
            if saved.organization_id!=org or saved.state_ref!=state.ref or saved.data!=data or saved.input_sha256!=content_digest(data) or saved.executed_at.offset>saved.authored_at.offset:
                raise ValueError('Resume capacity assessment changes current original calendar/occupancy/demand')
            if saved.status=='unsupported': _unsupported('commercial-resume-capacity-domain')
            if saved.status!='ok' or saved.report is None: _needs('successful_original_resume_capacity_assessment')
            report=calculate(CAPACITY_METHOD,data)
            if report!=saved.report: raise ValueError('Resume capacity report differs from exact original current demand')
            if not report.feasible: return wait(calendar.ref,'commercial_resume_capacity_unavailable')
            fields['readiness_refs']=profile.readiness_refs
        if profile.choice=='handover':
            if profile.transfer_plan_ref is None: _needs('original_independent_commercial_successor_plan')
            plan=read(profile.transfer_plan_ref,types['ContinuationTransferPlan'],evidence_at_field='authored_at');author(plan,own=True)
            if plan.organization_id!=org or plan.scope!=scope or plan.successor_organization_id==org or not plan.transfer_evidence_refs:
                raise ValueError('Handover substitutes original firm/state/successor or evidence')
            signed_state=state if plan.state_ref==state.ref else read(plan.state_ref,types['ContinuationState'],historic=True)
            clock(signed_state.as_of)
            if (signed_state.organization_id!=org or signed_state.run_id!=context.run_id
                    or (signed_state.ref.kind,signed_state.ref.id)!=(state.ref.kind,state.ref.id)
                    or signed_state.scope!=state.scope or signed_state.coverage!='complete'
                    or signed_state.as_of.offset>plan.authored_at.offset
                    or signed_state.available_at.offset>plan.authored_at.offset
                    or signed_state.as_of.offset>state.as_of.offset):
                raise ValueError('Handover changes the original signed state or its knowledge chronology')
            evidence(signed_state.evidence_refs,at=signed_state.as_of)
            # A clock/receipt refresh does not change the signed business. New
            # resource/material/work/debt/document versions require a new plan
            # and independent consent; they cannot inherit old signatures.
            metadata={'ref','as_of','available_at','effective_window','evidence_refs',
                'observation_refs','applied_observation_refs','execution_refs'}
            for field in type(state).model_fields.keys()-metadata:
                old,current=getattr(signed_state,field),getattr(state,field)
                if isinstance(old,list) and isinstance(current,list):
                    same=keys(old)==keys(current)
                else: same=old==current
                if not same:
                    _needs('new_same_version_commercial_transfer_plan_and_party_consent',[plan.ref,state.ref])
            for field in ['work_record_refs','material_refs','document_refs','obligation_refs','responsibility_refs',*extra_transfer_fields]:
                if keys(getattr(plan,field))!=keys(getattr(state,field)): raise ValueError('Handover omits original completed/unverified/defective work, materials, records or remaining duties')
            for row in documents.values():
                if plan.successor_organization_id not in row.licensed_recipient_organization_ids: _needs('original_licensed_document_access_for_successor',[row.ref])
            for item in material_plan.items:
                if item.choice=='handover' and item.recipient_organization_id!=plan.successor_organization_id:
                    raise ValueError('Handover changes original lawful material recipient')
            acceptance_ref=profile.successor_acceptance_ref or plan.acceptance_ref
            if (acceptance_ref.kind,acceptance_ref.id)!=(plan.acceptance_ref.kind,plan.acceptance_ref.id):
                raise ValueError('Handover substitutes original successor acceptance identity')
            acceptance=read(acceptance_ref,types['ContinuationAcceptance'],evidence_at_field='authored_at');author(acceptance);clock(acceptance.as_of)
            if (acceptance.plan_ref!=plan.ref or acceptance.plan_sha256!=content_digest(plan) or acceptance.successor_organization_id!=plan.successor_organization_id
                    or acceptance.author_organization_id!=plan.successor_organization_id or acceptance.scope!=plan.scope
                    or acceptance.as_of.offset>acceptance.authored_at.offset
                    or acceptance.as_of.offset<signed_state.as_of.offset
                    or acceptance.authored_at.offset<plan.available_at.offset):
                raise ValueError('Successor acceptance changes original same-version plan or independent organization authority')
            if not true(acceptance.accepted): return wait(acceptance.ref,'commercial_handover_waiting_successor_acceptance')
            consent_refs=plan.consent_refs if profile.party_consent_refs is None else profile.party_consent_refs
            accepted=set();keys(plan.consent_refs);keys(consent_refs)
            if {(r.kind,r.id) for r in consent_refs}!={(r.kind,r.id) for r in plan.consent_refs}:
                raise ValueError('Handover replaces or omits original contract-party consent identities')
            for ref in consent_refs:
                consent=read(ref,types['ContinuationConsent'],evidence_at_field='authored_at');author(consent)
                contract=contracts.get(consent.contract_ref.key());identity=(consent.contract_ref.key(),consent.party_organization_id)
                if (contract is None or consent.plan_ref!=plan.ref or consent.plan_sha256!=content_digest(plan)
                        or consent.author_organization_id!=consent.party_organization_id or consent.party_organization_id not in contract.party_organization_ids
                        or consent.scope!=plan.scope or consent.authored_at.offset<plan.available_at.offset
                        or identity in accepted): raise ValueError('Handover substitutes independent original contract-party consent')
                if not true(consent.accepted): return wait(ref,'commercial_handover_waiting_original_party_consent')
                accepted.add(identity)
            if accepted!={(k,party) for k,c in contracts.items() for party in c.party_organization_ids}: _needs('all_original_contract_parties_for_commercial_succession')
            evidence(plan.transfer_evidence_refs,at=plan.authored_at)
            fields.update(successor_id=plan.successor_organization_id,transfer_evidence_refs=plan.transfer_evidence_refs)
        return complete(**fields)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
