"""Explicit initial review inputs; runtime A04 supplies the A07 findings."""
from copy import deepcopy

from integration.contractor_tender_development import ref, known
from integration.government_approval_native import GovernmentApprovalPlan
from integration.government_review_actions import GovernmentReviewActionAssembler
from integration.government_decision_actions import GovernmentDecisionActionAssembler
from src.actions.contracts.common import Reference
from src.actions.contracts.government_decision_objects import GovDecisionDraft
from src.actions.roles.qs_change import content_digest
from src.methods.government_rules import GOV_RULE_METHOD, GovRuleInput, check_declared_rule
from src.coordination.tasks import task_digest


def approval_plans(intake_plans,grants,*,revision_first=False,approval_ticks=None,with_feedback=False,
        approval_organization_ids=None,initial_assignment_tick=1):
    plans=[]
    scheduled=[(intake,intake['tick']) for intake in intake_plans] if approval_ticks is None else [
        (intake,tick) for intake in intake_plans if intake['tick']==initial_assignment_tick for tick in approval_ticks]
    for intake,tick in scheduled:
        if (intake['organization_id'] not in approval_organization_ids if approval_organization_ids is not None
                else not intake['organization_id'].endswith('-a')):continue
        org=intake['organization_id'];project=intake['project_id'];assignment_tick=intake['tick']
        actor=intake['context']['actor_id']
        phase=intake.get('review_phase','design');document_type=phase+'-summary'
        scope=intake['action_input']['scope'];point={**intake['context']['business_time'],'offset':tick};clock=point['clock_ref']
        at=lambda n:{'clock_ref':clock,'offset':n}
        window={'start':at(0),'end':at(99),'bounds':'closed_open'}
        tag=org+'-'+project+'-t'+str(tick)+('-completion' if phase=='completion' else '')+'-approval'
        rr=lambda kind,name:ref(kind,tag+'-'+name)
        function=intake['context']['function_ref']
        function_source,=[r['value'] for r in intake['objects'] if r['ref']==function]
        applicant_id=next(r['value']['applicant_id'] for r in intake['objects']
            if r['ref']==intake['action_input']['submission_ref'])
        basis=function_source['basis_refs'][0]
        case=rr('RegulatoryCase','independent-initial-case');task=rr('Task','review')
        submission=intake['action_input']['submission_ref'];matter=intake['action_input']['matter_ref']
        jurisdiction=intake['action_input']['jurisdiction_ref'];procedure=intake['action_input']['procedure_ref']
        decision_procedure=rr('Procedure','case-decision-checklist')
        review_grant=rr('Authorization','review');decision_grant=rr('Authorization','decision')
        review_native=rr('Evidence','actual-review-request');decision_native=rr('Evidence','actual-decision-request')
        handoff=rr('Evidence','actual-a04-handoff');source=rr('Evidence','received-'+phase+'-document')
        document={'schema_version':'synthetic-'+phase+'-document.v1','project_id':project,
            'applicant_id':applicant_id,
            'document_type':'unrecognized-drawing' if revision_first and project=='regulatory-first' else document_type,
            'limits':'Synthetic declared document-code check only; no physical inspection, safety certification or real legal validity.'}
        document_sha=task_digest(document)
        rule=rr('Rule','document-type');applicability=rr('ApplicabilityBasis','document-type')
        fact=rr('VerifiedFact','document-type');method_result=rr('MethodResult','original-independent-check')
        descriptor=rr('MethodDescriptor','rule-executor');assignment=rr('ReviewAssignment','initial-reviewer')
        assessment=rr('Assessment','actual-a04-private-review');finding=rr('MethodResult','actual-a04-finding')
        decision_check=rr('DecisionCheck','document-type');decision_basis=rr('DecisionBasis','authorized-draft')
        outcome_rule=rr('Rule','approve');effect=rr('EffectRule','native-approval');command=rr('DecisionCommand','draft-only')
        revision_rule=rr('Rule','require-design-revision');revision_effect=rr('EffectRule','revision-without-permission')
        authority=rr('Authority','decision-outcome')
        intake_objects={task_digest(r['ref']):r for r in intake['objects']}
        common=[deepcopy(intake_objects[task_digest(r)]) for r in
            [basis,function,scope['ref'],matter,jurisdiction,intake['native_evidence_ref']]]
        received=deepcopy(intake_objects[task_digest(submission)])
        received['value'].update(available_at=at(0),effective_window=window,content_sha256=document_sha)
        common.append(received)
        common.append({'ref':source,'value':{'ref':source,'source_kind':'synthetic','basis_kind':'observed',
            'locator':'embedded-synthetic-'+phase+'-document:'+task_digest(document),'content_hash':document_sha,'effective_window':window}})
        initial=rr('Evidence','independent-review-assumptions')
        common.append({'ref':initial,'value':{'ref':initial,'source_kind':'synthetic','basis_kind':'assumed',
            'locator':'explicit-initial-case-review-assignment-rule-and-signing-authority',
            'content_hash':task_digest({'case':case,'assignment':assignment,'jurisdiction':jurisdiction,
                'rule':rule,'authority':authority,'initial_case_not_created_by_intake':True,'document':document}),
            'effective_window':window}})
        def observed(reference,locator):
            return {'ref':reference,'value':{'ref':reference,'source_kind':'synthetic','basis_kind':'observed',
                'locator':locator,'content_hash':None,'effective_window':window}}
        def row(reference,**value):
            return {'ref':reference,'value':{'ref':reference,'scope':scope,'available_at':at(0),
                'effective_window':window,'evidence_refs':[initial],**value}}
        def authored(action,grant,when):
            return {'author_actor_id':actor,'author_organization_id':org,'author_function_ref':function,
                'author_authority_ref':grant,'author_action_id':action,'authored_at':when}
        bound={'case_ref':case,'submission_ref':submission,'content_sha256':document_sha}
        initial_case=row(case,organization_id=org,applicant_id=applicant_id,matter_ref=matter,
            procedure_ref=procedure,current_submission_ref=submission,linked_submission_refs=[],jurisdiction_ref=jurisdiction,
            region_id=known('Hong Kong'),queue_ref=rr('CaseQueue','initial'),task_refs=[task],status='accepted')
        review_objects=[*deepcopy(common),deepcopy(initial_case),observed(review_native,'actual-native-'+phase+'-approval-request')]
        review_objects.extend([
            row(task,**bound,organization_id=org,function_ref=function,authority_ref=review_grant,
                assignment_ref=assignment,rule_refs=[rule],professional_refs=[],reuse_basis_refs=[],
                verified_evidence_refs=[source],method_result_refs=[method_result],dependency_refs=[],question_refs=[],
                condition_refs=[],verification_method_ref=None,choice='assess',
                explanation='Check actual received synthetic document code against explicit assumed rule; no physical safety inference.',
                status='authorized',evidence_refs=[initial,review_native]),
            row(assignment,organization_id=org,case_ref=case,task_ref=task,work_profile_ref=rr('WorkProfile','initial'),
                resource_refs=[],commitment_refs=[],window=window,status='effective'),
            row(rule,**bound,organization_id=org,jurisdiction_ref=jurisdiction,criterion='code_equals',
                method_ref=GOV_RULE_METHOD.model_dump(mode='json'),method_descriptor_ref=descriptor,result_ref=method_result,
                applicability_ref=applicability,fact_ref=fact,unit=None,minimum=None,maximum=None,
                expected_code=document_type,required_professions=[],discipline_code='synthetic-document-type',question_refs=[]),
            row(applicability,**bound,rule_ref=rule,applicable=known(True),**authored('GOV-A04',review_grant,at(0))),
            row(fact,**bound,rule_ref=rule,measured_value=None,code_value=known(document['document_type']),
                verification_evidence_refs=[source],**authored('GOV-A04',review_grant,at(0))),
            row(descriptor,organization_id=org,purpose='rule_check',rule_refs=[rule],executor_function_ref=function,
                executor_authority_ref=review_grant,executor_actor_id=actor,execution_action_id='GOV-A04',
                supported=known(True),calculation_method_ref=GOV_RULE_METHOD.model_dump(mode='json'))])
        method_input=GovRuleInput(criterion='code_equals',applicable=known(True),measured_value=None,
            code_value=known(document['document_type']),unit=None,minimum=None,maximum=None,expected_code=document_type,
            professional_findings=[],professional_complete=True,
            source_refs=[Reference.model_validate(r) for r in [rule,applicability,submission,task,fact,source]])
        review_objects.append(row(method_result,**bound,task_ref=task,rule_ref=rule,
            method_ref=GOV_RULE_METHOD.model_dump(mode='json'),input_sha256=content_digest(method_input),status='ok',
            report=check_declared_rule(method_input).model_dump(mode='json'),**authored('GOV-A04',review_grant,at(0))))
        decision_objects=[*deepcopy(common),observed(decision_native,'actual-native-'+phase+'-approval-request'),
            observed(handoff,'actual-original-a04-saved-result'),
            deepcopy(next(r for r in review_objects if r['ref']==descriptor))]
        case_view=deepcopy(initial_case);case_view['value'].update(assessment_refs=[assessment],unresolved_issue_refs=[],
            decision_refs=[],history_coverage='complete',as_of=point)
        decision_objects.append(case_view)
        draft={'outcome':'approve','case_ref':case,'submission_ref':submission,'covered_scope':scope,
            'decision_basis_ref':decision_basis,'assessment_refs':[assessment],'conditions':[],
            'reason':'Approve native '+phase+'-review gate after actual original A04 document checks; detailed initial authority remains an explicit synthetic assumption.',
            'effect_rule_ref':effect,'expiry_rule_ref':None,'notification_recipient_ids':[applicant_id],
            'prior_decision_ref':None,'next_procedure_refs':[]}
        actual_author=authored('GOV-A04',review_grant,point)
        decision_objects.extend([
            row(assessment,**bound,check_result_refs=[finding],reuse_basis_ref=None,status='valid',
                evidence_refs=[handoff],available_at=point,**actual_author),
            row(finding,assessment_ref=assessment,check_ref=decision_check,submission_ref=submission,content_sha256=document_sha,
                finding='unknown',status='unknown',verification_evidence_refs=[handoff],applicability_basis_ref=None,
                method_ref=GOV_RULE_METHOD.model_dump(mode='json'),method_descriptor_ref=descriptor,
                evidence_refs=[handoff],available_at=point,**actual_author),
            row(decision_check,rule_ref=rule,required_before_approval=True),
            row(decision_procedure,source_procedure_ref=procedure,case_ref=case,
                required_check_refs=[decision_check],required_procedure_refs=[],modeled=True),
            row(outcome_rule,case_ref=case,procedure_ref=decision_procedure,outcome='approve',permitted=known(True),
                permits_incomplete_review=False,required_nonconforming_check_refs=[],issue_refs=[],effect_rule_ref=effect,
                expiry_rule_ref=None,next_procedure_refs=[]),
            row(effect,decision_rule_ref=outcome_rule,outcome='approve',mode='on_signed_record',
                notification_recipient_ids=[applicant_id],modeled=True),
            row(revision_rule,case_ref=case,procedure_ref=decision_procedure,outcome='defer_by_procedure',permitted=known(True),
                permits_incomplete_review=True,required_nonconforming_check_refs=[],issue_refs=[],effect_rule_ref=revision_effect,
                expiry_rule_ref=None,next_procedure_refs=[]),
            row(revision_effect,decision_rule_ref=revision_rule,outcome='defer_by_procedure',mode='no_permission',
                notification_recipient_ids=[applicant_id],modeled=True),
            row(authority,organization_id=org,actor_id=actor,function_ref=function,case_ref=case,submission_ref=submission,
                decision_basis_ref=decision_basis,outcomes=['approve','defer_by_procedure'],permitted=known(True)),
            row(decision_basis,**bound,signer_actor_id=actor,signer_function_ref=function,signer_authorization_ref=decision_grant,
                decision_authority_ref=authority,procedure_ref=decision_procedure,decision_rule_ref=outcome_rule,draft=draft,
                condition_basis_refs=[],command_ref=command,evidence_refs=[initial,decision_native],
                available_at=point,**authored('GOV-A07',decision_grant,point)),
            row(command,case_ref=case,submission_ref=submission,decision_basis_ref=decision_basis,
                operation_id=tag+'-GOV-A07',business_key=tag+'-original-native-approval',
                draft_sha256=content_digest(GovDecisionDraft.model_validate(draft)),
                official_decision_ref=None,status='not_submitted',lookup_status='not_queried')])
        contexts={}
        # A07 must independently read the A04 authorship grant, with precisely
        # the original read scope; no A07 signing authority is borrowed from it.
        action_grants=[]
        for action,grant_ref,objects,native,target,choices in [
                ('GOV-A04',review_grant,review_objects,review_native,task,['assess']),
                ('GOV-A07',decision_grant,decision_objects,decision_native,case,['approve','defer_by_procedure'])]:
            candidate=rr('CandidateSet',action)
            objects.append({'ref':candidate,'value':{'operation_id':tag+'-'+action,'scope':scope,'as_of':point,
                'candidates':[{'ref':target,'permitted_choices':choices}],'search_profile_ref':rr('Profile',action)}})
            grant={'ref':grant_ref,'organization_id':org,'actor_id':actor,'function_ref':function,'action_ids':[action],
                'scopes':[scope],'readable_refs':[],'tool_ids':[],'basis_refs':[initial],'validity':window}
            action_grants.append(grant);objects.append({'ref':grant_ref,'value':grant})
        # The handoff Evidence is readable by the original A04 author; its
        # content is bound after execution, without changing this grant version.
        action_grants[0]['readable_refs']=[r['ref'] for r in review_objects]+[handoff]
        decision_objects.append({'ref':review_grant,'value':deepcopy(action_grants[0])})
        action_grants[1]['readable_refs']=[r['ref'] for r in decision_objects]
        for action,grant,objects in [('GOV-A04',action_grants[0],review_objects),('GOV-A07',action_grants[1],decision_objects)]:
            grants.append(deepcopy(grant));visible=[r['ref'] for r in objects]
            contexts[action]={'run_id':intake['context']['run_id'],'actor_id':actor,'function_ref':function,
                'authorization_refs':[grant['ref']],'operation_id':tag+'-'+action,'contract_ref':ref('ActionContract',action),
                'task_ref':rr('DecisionTask',action),'scope':scope,'business_time':point,'read_token':tag+'-'+action+'-read',
                'visible_refs':visible,'candidate_set_ref':rr('CandidateSet',action),'execution_mode':'rule'}
        feedback=None
        if with_feedback:
            from integration.government_approval_native_learning_development import feedback_plan
            feedback=feedback_plan(intake,tick=tick,tag=tag,grants=grants)
        plan=GovernmentApprovalPlan.model_validate({'organization_id':org,'project_id':project,'tick':tick,'feedback':feedback,
            'review_phase':phase,'assignment_tick':assignment_tick,
            'review_context':contexts['GOV-A04'],'decision_context':contexts['GOV-A07'],
            'review_input':{'scope':scope,'case_ref':case,'submission_ref':submission,'task_ref':task,'rule_refs':[rule],
                'professional_refs':[],'verified_evidence_refs':[source],'method_result_refs':[method_result]},
            'decision_input':{'scope':scope,'case_ref':case,'current_submission_ref':submission,'assessment_refs':[assessment],
                'unresolved_issue_refs':[],'procedure_completion_ref':None,'decision_basis_ref':decision_basis},
            'review_objects':review_objects,'decision_objects':decision_objects,'review_native_evidence_ref':review_native,
            'decision_native_evidence_ref':decision_native,'handoff_evidence_ref':handoff,'assessment_ref':assessment,
            'submission_content':document,'submission_evidence_ref':source,
            'check_links':[{'review_rule_ref':rule,'decision_check_ref':decision_check,'decision_finding_ref':finding}],
            'outcome_policy':{'approve_rule_ref':outcome_rule,'approve_effect_ref':effect,
                'revision_rule_ref':revision_rule,'revision_effect_ref':revision_effect,'approve_reason':draft['reason'],
                'revision_reason':'Require a corrected '+phase+' submission under the explicit procedure because the actual A04 document-code check is nonconforming; no formal refusal or permission is issued.'},
            'utility':intake['utility'],'probability':intake['probability']})
        for assembler,objects in [(GovernmentReviewActionAssembler,plan.review_objects),
                (GovernmentDecisionActionAssembler,plan.decision_objects)]:
            for item in objects:
                value=deepcopy(item['value'])
                if item['ref']['kind']=='Evidence' and value['content_hash'] is None:value['content_hash']='0'*64
                assembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(item['ref']),value)
        plans.append(plan.model_dump(mode='json'))
    return plans
