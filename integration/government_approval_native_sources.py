"""Bind native assignment and actual A04 output to a private A07 source view."""
from integration.bank_financing_private import checked_result, evidence_binding
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from integration.government_history_authority import authorize_government_history
from src.actions.contracts.government_decision_objects import GovDecisionDraft
from src.actions.roles.qs_change import content_digest


def ref_digest(ref):
    return task_digest(ref.model_dump(mode='json') if hasattr(ref,'model_dump') else ref)


def current_review_assignment(parent, plan, scope):
    """A02 willingness is evidence of assignment, never evidence of case filing."""
    assembly=parent.assembly
    project=assembly.engine.projects[plan.project_id]
    assignment_tick=plan.tick if plan.assignment_tick is None else plan.assignment_tick
    assignment_scope={**scope,'tick':assignment_tick,'purpose':
        'completion_review_assignment' if plan.review_phase=='completion' else 'review_assignment'}
    events=[e for e in project.event_log if e['event_type']=='regulatory_review_decision'
        and e['tick']==assignment_tick and e['agent_id']==plan.organization_id
        and e['data'].get('decision_factors',{}).get('native_government_scope')==assignment_scope]
    if len(events)!=1:
        raise TaskConflict('Approval needs its actual current own review-assignment event')
    event=events[0];data=event['data'];factors=data.get('decision_factors',{})
    if plan.review_phase=='completion' and data.get('purpose')!='completion inspection':
        raise TaskConflict('Completion approval cannot borrow a design review assignment')
    records=[r for r in parent._records() if r['state']=='formed' and r['scope']==assignment_scope
        and r['native_request']['agent']['agent_id']==plan.organization_id]
    if len(records)!=1 or factors.get('micro_action_id')!='GOV-A02' or data.get('accepted') is not True:
        raise TaskConflict('Approval cannot substitute declined or unconfirmed regulatory intake')
    record=records[0];identity=TaskIdentity(**record['identity']);saved=checked_result(parent.worker,identity)
    authorize_government_history(assembly,identity,organizations=parent.organizations,
        tick=assembly.engine.current_tick,saved=saved)
    intake,=[p for p in parent.plans if (p.organization_id,p.project_id,p.tick)==
        (plan.organization_id,plan.project_id,assignment_tick) and p.review_phase==plan.review_phase]
    if plan.review_phase=='completion' and not any(e.agent_id==plan.organization_id and e.role=='Government'
            and e.status.value=='active' and e.joined_at_tick==assignment_tick for e in project.engagements):
        raise TaskConflict('Completion approval requires its actual still-active selected Government engagement')
    if intake.action_input['submission_ref']!=plan.review_input['submission_ref']:
        raise TaskConflict('Approval substitutes its actual independently received intake submission')
    tasks=assembly.client.tasks.for_organization(run_id=assembly.client.run_id,organization_id=plan.organization_id)
    proposals=[t['output'] for t in tasks if t['identity']['purpose']=='propose'
        and t['identity']['action_id']=='consider_review_assignment' and t['state']=='output_formed'
        and t['output'].get('factors',{}).get('native_government_scope')==assignment_scope]
    finals=[t['output'] for t in tasks if t['identity']['purpose']=='decide'
        and t['identity']['action_id']=='government_review_assignment' and t['state']=='output_formed'
        and t['output'].get('data',{}).get('native_government_scope')==assignment_scope]
    if len(proposals)!=1 or len(finals)!=1:
        raise TaskConflict('Approval lost its original intake proposal or final confirmation')
    proposal,final=proposals[0],finals[0]
    if (saved['result']['payload']['choice']!='accept_for_processing'
            or saved['result_sha256']!=record['result_sha256']
            or factors.get('micro_task_key')!=identity.key
            or factors.get('micro_result_sha256')!=saved['result_sha256']
            or record['proposal_response_sha256']!=task_digest(proposal)
            or data.get('proposal_response_sha256')!=task_digest(proposal)
            or final['data'].get('proposal_response_sha256')!=task_digest(proposal)
            or proposal['accepted'] is not True or final['decision'] is not True
            or final['action_type']!=proposal['action_type'] or data.get('action_type')!=proposal['action_type']):
        raise TaskConflict('Approval substitutes its actual completed intake or assigned reviewer')
    return {'event_id':event['event_id'],'micro_task_key':identity.key,
        'micro_result_sha256':saved['result_sha256'],'proposal_response_sha256':task_digest(proposal),
        'final_response_sha256':task_digest(final),'scope':assignment_scope,
        'intake_evidence':{'ref':intake.native_evidence_ref.model_dump(mode='json'),'observed':record['observed']}}


def decision_sources(app, plan, record, objects):
    """Project actual scoped checks; do not create any formal assessment ledger."""
    saved=checked_result(app.review_worker,TaskIdentity(**record['review_identity']))
    authorize_government_history(app.assembly,TaskIdentity(**record['review_identity']),
        organizations=app.parent.organizations,tick=app.assembly.engine.current_tick,saved=saved)
    result=saved['result'];payload=result.get('payload',{})
    if (result.get('kind')!='completed' or payload.get('choice')!='assess'
            or saved['result_sha256']!=record['review_result_sha256']):
        raise TaskConflict('Approval requires the original completed GOV-A04 assessment')
    assessment=payload['assessment']
    if assessment['target_ref']!=plan.review_input['submission_ref'] or assessment['task_ref']!=plan.review_input['task_ref']:
        raise TaskConflict('Approval review handoff changes the original submission or task')
    checks=assessment['checks'];links=plan.check_links
    if (len(checks)!=len(links)
            or {ref_digest(c['rule_ref']) for c in checks}!={ref_digest(l.review_rule_ref) for l in links}):
        raise TaskConflict('Approval needs exact original review-check coverage')
    # checked_result/get_record validates the durable snapshot and original
    # invocation; never accept a caller supplied report as the source review.
    originals={task_digest(r['ref']):r['projection'] for r in saved['source_reading']}
    evidence_ref=plan.handoff_evidence_ref.model_dump(mode='json')
    origin={'action_id':'GOV-A04','task_key':TaskIdentity(**record['review_identity']).key,
        'result_sha256':saved['result_sha256'],'assessment_sha256':task_digest(assessment)}
    evidence_binding(objects,evidence_ref,origin)
    by_ref={task_digest(r['ref']):r['value'] for r in objects}
    original_case=originals[task_digest(plan.review_input['case_ref'])]
    decision_case=by_ref[task_digest(plan.decision_input['case_ref'])]
    if any(decision_case.get(k)!=v for k,v in original_case.items()):
        raise TaskConflict('Approval handoff substitutes its original independently supplied case')
    required=[plan.review_input['submission_ref'],plan.review_context.function_ref,
        plan.review_context.authorization_refs[0],plan.submission_evidence_ref]
    required.extend(r['ref'] for r in saved['source_reading']
        if r['ref']['kind'] in {'Jurisdiction','RegulatoryMatter','MethodDescriptor'})
    for ref in required:
        if by_ref.get(ref_digest(ref))!=originals.get(ref_digest(ref)):
            raise TaskConflict('Approval handoff substitutes original received sources or review authority')
    view=by_ref[ref_digest(plan.assessment_ref)]
    if view['check_result_refs']!=[l.decision_finding_ref.model_dump(mode='json') for l in links]:
        raise TaskConflict('Approval assessment substitutes its preauthorized check-result references')
    expected_author={'author_actor_id':plan.review_context.actor_id,'author_organization_id':plan.organization_id,
        'author_function_ref':plan.review_context.function_ref.model_dump(mode='json'),
        'author_authority_ref':plan.review_context.authorization_refs[0].model_dump(mode='json'),
        'author_action_id':'GOV-A04','authored_at':plan.review_context.business_time.model_dump(mode='json')}
    submission=originals[task_digest(plan.review_input['submission_ref'])]
    for row in [view,*[by_ref[ref_digest(l.decision_finding_ref)] for l in links]]:
        if (any(row.get(k)!=v for k,v in expected_author.items())
                or row['submission_ref']!=submission['ref'] or row['content_sha256']!=submission['content_sha256']
                or row['evidence_refs']!=[evidence_ref]):
            raise TaskConflict('Approval handoff substitutes actual review author, version or private evidence')
    for link in links:
        check,=[c for c in checks if c['rule_ref']==link.review_rule_ref.model_dump(mode='json')]
        row=by_ref[ref_digest(link.decision_finding_ref)]
        source=originals.get(task_digest(check['method_result_ref']))
        if (check['covered_scope']!=plan.review_input['scope'] or source is None or source['status']!='ok'
                or source['report']['finding']!=check['finding'] or row['check_ref']!=link.decision_check_ref.model_dump(mode='json')
                or row['assessment_ref']!=plan.assessment_ref.model_dump(mode='json')
                or row['method_ref']!=source['method_ref'] or row['verification_evidence_refs']!=[evidence_ref]):
            raise TaskConflict('Approval finding substitutes actual recomputed review evidence or scope')
        rule=originals[ref_digest(link.review_rule_ref)]
        if row.get('method_descriptor_ref')!=rule.get('method_descriptor_ref'):
            raise TaskConflict('Approval finding substitutes its original review method descriptor')
        row['finding']=check['finding'];row['status']='ok'
    states={c['finding'] for c in checks}
    if not states or not states<={'conforms','nonconforms','not_applicable'}:
        raise TaskConflict('Unresolved review findings need diagnosis before a native approval or revision decision')
    outcome='defer_by_procedure' if 'nonconforms' in states else 'approve'
    policy=plan.outcome_policy
    selected_rule=(policy.revision_rule_ref if outcome=='defer_by_procedure' else policy.approve_rule_ref).model_dump(mode='json')
    selected_effect=(policy.revision_effect_ref if outcome=='defer_by_procedure' else policy.approve_effect_ref).model_dump(mode='json')
    rule=by_ref[ref_digest(selected_rule)];effect=by_ref[ref_digest(selected_effect)]
    if (rule['outcome']!=outcome or rule['effect_rule_ref']!=selected_effect or effect['outcome']!=outcome
            or effect['decision_rule_ref']!=selected_rule
            or (outcome=='defer_by_procedure' and effect['mode']!='no_permission')):
        raise TaskConflict('Approval policy substitutes independent outcome or revision-without-permission rules')
    basis=by_ref[task_digest(plan.decision_input['decision_basis_ref'])]
    draft=basis['draft'];command=by_ref[task_digest(basis['command_ref'])]
    if (command['status']!='not_submitted' or command['official_decision_ref'] is not None
            or command['lookup_status']!='not_queried'
            or command['draft_sha256']!=content_digest(GovDecisionDraft.model_validate(draft))):
        raise TaskConflict('Approval cannot replace a submitted, unknown or changed decision draft')
    basis['decision_rule_ref']=selected_rule;draft['outcome']=outcome;draft['effect_rule_ref']=selected_effect
    draft['reason']=policy.revision_reason if outcome=='defer_by_procedure' else policy.approve_reason
    command['draft_sha256']=content_digest(GovDecisionDraft.model_validate(draft))
    origin['selected_outcome']=outcome;origin['outcome_policy_sha256']=task_digest(policy.model_dump(mode='json'))
    # Include the policy in the private evidence read by the actual A07.
    evidence,=[r['value'] for r in objects if r['ref']==evidence_ref]
    evidence['content_hash']=task_digest(origin)
    return objects,origin
