"""Explicit independent intake sources for native regulatory review requests."""
from copy import deepcopy
import argparse
import json
from pathlib import Path

from integration.bootstrap import enable_gba_imports
from integration.contractor_tender_development import _write, _write_launch_files, known, ref
from integration.government_intake_native import GovernmentIntakePlan, GovernmentIntakeSettings
from integration.government_intake_actions import GovernmentIntakeActionAssembler
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest


def build_bundle(directory,*,run_id,with_approval=False,revision_first=False,completion=False,with_feedback=False,
        with_monthly_feedback=False,monthly_feedback_ticks=None,
        allow_monthly_saved_recovery=False,query_saved_monthly_on_error=False,
        allow_intake_saved_recovery=False,query_saved_intake_on_error=False,
        allow_saved_recovery=False,query_saved_approval_on_error=False,
        continue_unstarted_approval_actions_on_error=False,owner_id='regulatory-owner',
        agency_ids=('regulatory-agency-a','regulatory-agency-b'),contractor_id='regulatory-contractor',
        clock_id=None,owner_function_id=None,project_ids=('regulatory-first','regulatory-followup'),
        intake_ticks=(1,2),approval_ticks=None,sources_only=False,organization_locations=None,organization_actor_ids=None):
    enable_gba_imports()
    from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
    if revision_first and not with_approval:raise ValueError('A revision scenario requires explicit original micro approval')
    if completion and not with_approval:raise ValueError('Completion requires explicit original micro approval')
    if with_feedback and not with_approval:raise ValueError('Private original feedback requires explicit micro approval')
    if allow_saved_recovery and not with_approval:raise ValueError('Saved approval recovery requires explicit micro approval')
    if continue_unstarted_approval_actions_on_error and not with_approval:
        raise ValueError('Unstarted approval continuation requires explicit micro approval')
    if query_saved_approval_on_error and not allow_saved_recovery:
        raise ValueError('Approval query on error requires explicit saved-result recovery')
    if query_saved_intake_on_error and not allow_intake_saved_recovery:
        raise ValueError('Intake query on error requires explicit saved-result recovery')
    if allow_monthly_saved_recovery and not with_monthly_feedback:
        raise ValueError('Saved monthly recovery requires explicit micro monthly feedback')
    if query_saved_monthly_on_error and not allow_monthly_saved_recovery:
        raise ValueError('Monthly query on error requires explicit saved-result recovery')
    projects=tuple(project_ids);intake_ticks=tuple(intake_ticks)
    if (not projects or len(set(projects))!=len(projects)
            or any(not isinstance(p,str) or not p for p in projects)
            or not intake_ticks or any(type(t) is not int or t<1 for t in intake_ticks)
            or intake_ticks!=tuple(sorted(set(intake_ticks)))):
        raise ValueError('Regulatory sources need distinct projects and increasing initial intake ticks')
    if approval_ticks is not None:
        approval_ticks=tuple(approval_ticks)
        if (not with_approval or not approval_ticks
                or any(type(t) is not int or t<intake_ticks[0] for t in approval_ticks)
                or approval_ticks!=tuple(sorted(set(approval_ticks)))):
            raise ValueError('Regulatory approval ticks must follow their declared initial assignment')
    # A source-only composition declares no existing Contractor or contract.
    # The actual native project and its actual winner belong to the caller.
    parties=[owner_id,*agency_ids]+([contractor_id] if completion and not sources_only else [])
    if ((len(agency_ids)!=2 if not sources_only else not agency_ids)
            or any(not isinstance(v,str) or not v for v in parties)
            or len(set(parties))!=len(parties)):
        raise ValueError('Regulatory input needs distinct explicit Owner, declared agencies and optional Contractor')
    actors={org:org for org in parties}
    if organization_actor_ids is not None:
        if (not isinstance(organization_actor_ids,dict) or not set(organization_actor_ids)<=set(parties)
                or any(type(actor) is not str or not actor.strip() for actor in organization_actor_ids.values())):
            raise ValueError('Initial regulatory actor mapping requires known organizations and nonempty actor IDs')
        actors.update(organization_actor_ids)
        if len(set(actors.values()))!=len(actors):
            raise ValueError('Regulatory organization actors must remain distinct')
    locations=deepcopy(organization_locations or {})
    if not isinstance(locations,dict) or set(locations)-set(parties):
        raise ValueError('Initial public locations must belong to the declared regulatory parties')
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=False)
    roles={owner_id:'Owner',**{agency:'Government' for agency in agency_ids}}
    if completion and not sources_only:roles[contractor_id]='Contractor'
    phase='completion' if completion else 'design';suffix='-completion' if completion else ''
    document_type=phase+'-summary';matter_code=phase+'_review'
    clock=ref('ClockProfile',clock_id or run_id+'-clock')
    point=lambda tick:{'clock_ref':clock,'offset':tick}
    window={'start':point(0),'end':point(99),'bounds':'closed_open'}
    organizations=[];grants=[];plans=[]
    for org,role in roles.items():
        basis=ref('Evidence',org+suffix+'-independent-assumptions')
        function=ref('FunctionAssignment',(owner_function_id if role=='Owner' and owner_function_id else org+suffix+'-function'))
        organizations.append({'organization_id':org,'actor_id':actors[org],'source_ids':['synthetic:'+org],
            'public_description':'Explicit synthetic regulatory sources; no real authority, case filing or legal validity.',
            'public_location':deepcopy(locations.get(org,known('Hong Kong'))),'members':[],'evidence_refs':[basis],
            'assignments':[{'role':role,'function_ref':function,'configuration_version':'1','basis_refs':[basis]}]})
        if role!='Government':continue
        for project in projects:
            for tick in intake_ticks:
                tag=org+'-'+project+'-t'+str(tick)+suffix;rr=lambda kind,name:ref(kind,tag+'-'+name)
                scope={'kind':'project','ref':ref('Project',project),'coverage_refs':[]}
                native=rr('Evidence','actual-native-request');submission=rr('Submission','received')
                matter=rr('RegulatoryMatter','matter');jurisdiction=rr('Jurisdiction','jurisdiction');procedure=rr('Procedure','procedure')
                authority=rr('Authorization','intake-grant');objects=[]
                def add(reference,**value):objects.append({'ref':reference,'value':{'ref':reference,'evidence_refs':[basis],**value}})
                objects.append({'ref':basis,'value':{'ref':basis,'source_kind':'synthetic','basis_kind':'assumed',
                    'locator':'explicit-regulatory-intake-assumptions','content_hash':task_digest({'agency':org,
                        'region_coverage':['Hong Kong'] if org==agency_ids[0] else ['Guangzhou'],
                        'independently_received_signed_eligible_submission':True,'material_categories':[document_type]}),
                    'effective_window':window}})
                objects.append({'ref':native,'value':{'ref':native,'source_kind':'synthetic','basis_kind':'observed',
                    'locator':'actual-native-regulatory-review-request','content_hash':None,'effective_window':window}})
                project_basis=ref('Evidence',project+'-initial-source')
                objects.append({'ref':project_basis,'value':{'ref':project_basis,'source_kind':'synthetic','basis_kind':'assumed',
                    'locator':'explicit-shared-initial-project-identity','content_hash':task_digest({'project_id':project,
                        'owner_id':owner_id,'region':'Hong Kong'}),'effective_window':window}})
                # The immutable public project identity has one shared source.
                # Per-recipient current observations belong to the distinct
                # received-submission view, not this shared project version.
                add(scope['ref'],evidence_refs=[project_basis])
                # This original source declares direct applicant submission.
                # Changing executing actors does not appoint a submitting agent.
                add(submission,scope=scope,applicant_id=owner_id,submitter_id=owner_id,
                    recipient_organization_id=org,agency_authority_ref=None,matter_ref=matter,jurisdiction_ref=jurisdiction,
                    procedure_ref=procedure,prior_case_ref=None,project_region_id=known('Hong Kong'),
                    applicant_registration_region_id=known('Hong Kong'),applicant_operating_region_ids=known(['Hong Kong']),
                    submitted_at=point(0),receipt_status='received',status='active',signed=known(True),applicant_eligible=known(True),
                    materials=[{'requirement_ref':rr('InformationRequirement','document'),'evidence_ref':basis}],evidence_refs=[basis,native])
                add(matter,scope=scope,matter_code=matter_code,project_region_id=known('Hong Kong'))
                add(jurisdiction,organization_id=org,effective_window=window,covered_matter_codes=known([matter_code]),
                    covered_project_region_ids=known(['Hong Kong'] if org==agency_ids[0] else ['Guangzhou']),
                    covered_scopes=[scope],referral=None,outside_coverage_rule_ref=rr('Rule','outside'))
                add(procedure,matter_ref=matter,jurisdiction_ref=jurisdiction,effective_window=window,intake_mode=known('completeness'),
                    requirement_refs=[rr('InformationRequirement',n) for n in ('signature','eligibility','document')],
                    ineligible_decline_rule_ref=rr('Rule','ineligible'),withdrawal_rule_ref=rr('Rule','withdrawn'))
                for name,purpose in [('correction','correction'),('outside','decline_outside_coverage'),
                        ('ineligible','decline_ineligible'),('withdrawn','withdrawal')]:
                    add(rr('Rule',name),scope=scope,organization_id=org,matter_ref=matter,procedure_ref=procedure,
                        purpose=purpose,recipient_id=None,effective_window=window)
                add(rr('EvidenceTarget','material'),submission_ref=submission,scope=scope)
                add(rr('RegulatoryRecipient','applicant'),actor_id=owner_id,scope=scope)
                add(rr('ResponseRequirement','correction'),rule_ref=rr('Rule','correction'),scope=scope,
                    description='Explicit assumed correction requirement, no real regulatory rule.')
                for name,kind in [('signature','signature'),('eligibility','applicant_eligibility'),('document','document')]:
                    add(rr('InformationRequirement',name),procedure_ref=procedure,scope=scope,check_kind=kind,
                        correction_question={'scope':scope,'target_refs':[rr('EvidenceTarget','material')],
                            'question':'Provide required '+name,'recipient_refs':[rr('RegulatoryRecipient','applicant')],
                            'requirement_ref':rr('Rule','correction'),'response_requirement_ref':rr('ResponseRequirement','correction'),
                            'evidence_refs':[basis]})
                assignment=organizations[-1]['assignments'][0]
                objects.append({'ref':function,'value':deepcopy(assignment)})
                grant={'ref':authority,'organization_id':org,'actor_id':actors[org],'function_ref':function,'action_ids':['GOV-A02'],
                    'scopes':[scope],'readable_refs':[],'tool_ids':[],'basis_refs':[basis],'validity':window}
                objects.append({'ref':authority,'value':grant})
                candidate=rr('CandidateSet','intake')
                objects.append({'ref':candidate,'value':{'operation_id':tag,'scope':scope,'as_of':point(tick),
                    'candidates':[{'ref':submission,'permitted_choices':['accept_for_processing','decline_processing']}],
                    'search_profile_ref':rr('Profile','received-sources')}})
                visible=[r['ref'] for r in objects];grant['readable_refs']=visible;grants.append(deepcopy(grant))
                context={'run_id':run_id,'actor_id':actors[org],'function_ref':function,'authorization_refs':[authority],
                    'operation_id':tag,'contract_ref':ref('ActionContract','GOV-A02'),'task_ref':rr('DecisionTask','intake'),
                    'scope':scope,'business_time':point(tick),'read_token':tag+'-read','visible_refs':visible,
                    'candidate_set_ref':candidate,'execution_mode':'rule'}
                inputs={'scope':scope,'submission_ref':submission,'applicant_id':owner_id,'agency_authority_ref':None,
                    'matter_ref':matter,'jurisdiction_ref':jurisdiction,'procedure_ref':procedure,'prior_case_ref':None}
                plan=GovernmentIntakePlan.model_validate({'organization_id':org,'project_id':project,'tick':tick,'context':context,
                    'review_phase':phase,
                    'action_input':inputs,'objects':objects,'native_evidence_ref':native,
                    'utility':{'value':'0.7','unit':'score','basis_ref':basis},'probability':{'value':'1','unit':'probability','basis_ref':basis}})
                for row in plan.objects:
                    value=deepcopy(row['value'])
                    if row['ref']['kind']=='Evidence' and value['content_hash'] is None:value['content_hash']='0'*64
                    GovernmentIntakeActionAssembler.SOURCE_SCHEMAS().validate_projection(Reference.model_validate(row['ref']),value)
                plans.append(plan.model_dump(mode='json'))
    source=_write(directory,'government-intake-input.json',{'schema_version':'government-intake-input.v1','run_id':run_id,'plans':plans})
    approval={}
    if with_approval:
        from integration.government_approval_native_development import approval_plans
        produced=approval_plans(plans,grants,revision_first=revision_first,
            approval_ticks=approval_ticks if approval_ticks is not None else (3,4) if completion else None,
            initial_assignment_tick=intake_ticks[0],
            with_feedback=with_feedback,approval_organization_ids=[agency_ids[0]])
        approval={'approval':{'version':'1','allow_saved_recovery':allow_saved_recovery,
            'continue_unstarted_actions_on_error':continue_unstarted_approval_actions_on_error,
            **_write(directory,'government-approval-input.json',{
            'schema_version':'government-approval-input.v1','run_id':run_id,'plans':produced})}}
    monthly={}
    if with_monthly_feedback:
        from integration.government_monthly_native_development import monthly_plans
        produced=monthly_plans(plans,grants,ticks=monthly_feedback_ticks or range(1,5 if completion else 3))
        monthly={'monthly':{'version':'1','allow_saved_recovery':allow_monthly_saved_recovery,
            **_write(directory,'government-monthly-input.json',{
            'schema_version':'government-monthly-feedback-input.v1','run_id':run_id,'plans':produced})}}
    settings=GovernmentIntakeSettings.model_validate({'version':'1','policy_version':'explicit-regulatory-intake-v1',**source,**approval,**monthly,
        'allow_saved_recovery':allow_intake_saved_recovery,
        'authority':{'runtime_id':run_id,'version':'1','organization_snapshot':{'schema_version':'organization.v2','run_id':run_id,
            'organizations':organizations,'authorizations':grants}}})
    _write(directory,'assembly-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1',
        'settings':settings.model_dump(mode='json')})
    if sources_only:
        return {'status':'independent-initial-regulatory-sources-unverified',
            'settings':settings.model_dump(mode='json'),
            'native_projects_or_execution_created':False}
    _write(directory,'native-host.json',{'schema_version':'gba-module-host-config.v1','host_id':run_id,'version':'1',
        'settings':{'run_id':run_id,'micro_government_intake_scope':True,'native_government_approval_transport':not with_approval,
            'micro_government_approval_scope':with_approval,
            'micro_government_monthly_feedback_scope':with_monthly_feedback,
            'query_saved_approval_on_error':query_saved_approval_on_error,
            'query_saved_intake_on_error':query_saved_intake_on_error,
            'query_saved_monthly_on_error':query_saved_monthly_on_error,
            'native_proposals':[{'role':r,'operation':'decide_monthly_operation'} for r in sorted(set(roles.values()))
                if not (with_monthly_feedback and r=='Government')]
                +([] if with_approval else [{'role':'Government','operation':'decide_approval'}]),
            'native_decisions':[{'role':r,'decision_type':'monthly_enterprise_operation'} for r in sorted(set(roles.values()))
                if not (with_monthly_feedback and r=='Government')]
                +([] if with_approval else [{'role':'Government','decision_type':'government_design_approval'}])}})
    initial=[{'project_id':project,'name':project,'project_type':'building','region':'Hong Kong',
        'owner_id':owner_id,'initial_budget':1000,'current_stage':'approval' if project==projects[0] else 'design',
        'stage_tick':1 if revision_first and project==projects[0] else 0,
        'performance':{'design_quality':1,'information_quality':1,'inspection_pass_probability':1}}
        for project in projects]
    if completion:
        for project in initial:
            project.update(current_stage='construction',stage_tick=0,selected_contractor_id=contractor_id,
                contract_sum=1000,contracts=[{'contractor_id':contractor_id,'contract_sum':1000,
                    'status':'active','source':'explicit-preexisting-contract-not-current-micro-execution'}],
                engagements=[{'engagement_id':project['project_id']+'-initial-contractor',
                    'project_id':project['project_id'],'agent_id':contractor_id,'role':'Contractor',
                    'status':'active','start_stage':'construction','joined_at_tick':0,'resource_allocation':1}])
            project['performance'].update(actual_progress=1,planned_progress=1,overall_quality=1,detected_defect_rate=0,
                defect_rate=0,safety_risk=0,variation_risk=0,claim_risk=0)
    request=SimulationCreateRequest.model_validate({'agent_source':'explicit','agents':[{'agent_id':org,'name':org,'role':role,
        'region':'Hong Kong','enterprise_type':'explicit_synthetic','total_resource_capacity':10,'management_capability':1,
        'policy_adaptability':1,'occupied_resource':2 if completion and role=='Contractor' else 0} for org,role in roles.items()],
        'initial_projects':initial,'enable_project_generation':False,'use_prior_network_edges':False,
        'ticks':4 if completion else 2,'random_seed':42})
    _write(directory,'macro-request.json',request.model_dump(mode='json'))
    readme='''# 原政府微观受理与原生审查意向

运行 `& './run.ps1'`。原宏观真实请求执行原 GOV-A02，原最终确认复用同一结果。
两家机构的辖区、签章、申请人资格和独立收到的设计摘要均为明确合成假设，不由宏观质量分数或当前请求推导。
机构 A 的辖区覆盖 Hong Kong；机构 B 只覆盖 Guangzhou。原处理器实际判断接受或拒绝处理。
本接线仅把该准备结果映射为原生接受/暂缓审查意向；不创建正式立案回执或 RegulatoryCase，不声称已执行 GOV-A04/A07。
后续审批仍显式采用原 GovernmentAgent.decide_approval，并确认同一提案；这部分不计微观覆盖。
真实监管审查事件只投递本机构，保留微观任务/结果和提案来源；后续请求核对本机构较早事件、原提案、最终确认及 GOV-A02 结果，再把历史摘要绑定到原处理器实际读取的证据。
该历史只表明已确认的接受/暂缓审查意向，不改变独立提供的辖区、资格、签章和材料，也不代表正式立案或许可。反馈驱动的其他业务及其他受理分支继续接线。
两个项目分别从 approval 和 design 开始，由原生命周期推进，运行窗口为两个时点。没有旧采购生命周期或第二套正式账本。
'''
    if with_approval:
        readme=readme.replace('不声称已执行 GOV-A04/A07。','正式立案与详细许可仍不在本窗口内。').replace(
            '后续审批仍显式采用原 GovernmentAgent.decide_approval，并确认同一提案；这部分不计微观覆盖。',
            '本窗口显式接管后续审批：原 GOV-A04 实际重算声明的文档代码规则，实际审查意见交给原 GOV-A07 形成授权草稿，再映射原生 approve；实算不符合时，由明确程序规则形成 defer_by_procedure 草稿，映射原生 request_revision。最终确认复用同一微观结果。独立初始案例、审查委任、规则及签署权限均为明确合成假设，不由 A02 接受意向产生。文档代码相符不代表物理设计或现实法律合规。原生审批结果仅反馈本机构，后续审查和决定均读取核实后的较早实际结果。尚未接通条件批准、正式拒绝、受理补件、送达和许可证分支。')
    if revision_first:readme+='\n本窗口首项目初始审批阶段已过一个时点，收到的合成文件类型不符；宏观质量分数仍为 1。原 A04 实算不符合，原 A07 形成暂缓并要求修改的草稿，由宏观原生逻辑退回 design；下一时点 followup 项目读取本机构较早真实退回反馈后完成自己的审查和决定。\n'
    if completion:
        readme='''# 原生完工审查与审批接线候选

运行 `& './run.ps1'`，四个原生时点；当前仅生成输入，业务结果待集中联调。
两个项目从明确提供的 construction 初始状态开始，承包商、既有主合同、进度和质量均为合成初始事实；不计作本轮招标、签约、施工或付款成果。
原生命周期触发 completion inspection 后，原 GOV-A02 判断受理意向，宏观选择机构并建立实际 engagement。
第 3/4 时点的原 decide_approval 请求复用原 GOV-A04 文档规则计算和 GOV-A07 授权草稿，再通过 government_completion_approval 返回 approve/request_revision。
材料、案例、规则和签署权限是独立合成输入；代码相符不代表现场检查或 GOV-A10 已执行，不形成详细许可或正式签署决定账本。
宏观还会检查自身缺陷条件；微观同意不等于实际完工。后续读取将核对本机构原任务、提案、最终确认和实际 project_completed/quality_issue，分别保留审批意见与宏观执行结果。
每次决定使用独立的案件检查清单，精确关联原受理程序；不覆盖原程序或改写已收到的材料版本。
--revision-first 使首项目材料代码持续不符合，保留宏观要求整改及下一时点读取既有结果的路径；不在同一材料版本下偷偷修正内容。
未启用旧采购生命周期，未修改宏观源码，未创建第二套正式账本。
'''
    if with_feedback:
        readme+='\n已显式启用 --with-feedback：每次原生审批前执行原 GOV-A12 record_feedback，核实本机构严格较早的审批及完工/整改历史。Feedback 是有权私有查询的实际读取结果，不是假称外部送达；空历史只表示无已核实的较早结果。原 A12 结果及来源摘要进入本次原 A04/A07 实际读取的 Evidence；不改变独立材料合规事实、法律条件、宏观政策、项目或资金。原处理器及实际后续消费待集中联调。\n'
    if with_monthly_feedback:
        readme+='\n已显式启用 --with-monthly-feedback：原宏观每次 Government.decide_monthly_operation 执行原 GOV-A12 私有经验整理，经同一原生提案/最终确认返回 review_policy_feedback。实际 agent_operation 和原企业记忆由宏观记录，后续月度及审批读取严格较早的本机构记录。独立组织授权只允许记录反馈，不代表正式政策发布、参数修改、检查、资金或资源执行；原引擎随机能力更新单独保留。其他分支与月度中断恢复不作已完成声明。\n'
    if allow_monthly_saved_recovery:
        readme+='\n已启用 --allow-monthly-saved-recovery：宿主可用 `assembly.client.recover_proposal(original_request)` 查询当前原生月度请求的已保存原 GOV-A12 结果；--query-saved-monthly-on-error 可在同一调用等待期间自动查询。核对原请求、权限、来源、版本及审计；缺结果保持未决，不重跑微观、不重启引擎、不新建或重提正式请求。\n'
    if allow_saved_recovery:
        readme+='\n已显式启用 --allow-saved-recovery：宿主可调用 `assembly.client.recover_proposal(original_request)` 查询并还原原审批提案。仅支持同一原生运行、当前项目/时点/请求及执行版本，且全部前置阶段已有原始完成结果与来源/审计。只补全技术任务和还原原响应，不重新执行处理器或模型，不投递宏观、不推进或恢复引擎、不重提正式业务；缺结果、等待、未知或状态变化继续未决。默认关闭，此能力尚待集中故障联调。\n'
    if query_saved_approval_on_error:
        readme+='\n已显式启用 --query-saved-approval-on-error：原生审批调用仍在进行时，若处理器结果已保存而技术收尾失败，客户端只查询同一原结果，并将经核验的原响应返回仍在等待的原调用。所有原阶段须已完成；不重跑缺失阶段，不新建宏观请求，不重启引擎或重提业务。查询不能核实原结果时继续抛出原错误，未知状态保留。\n'
    if continue_unstarted_approval_actions_on_error:
        readme+='\n--continue-unstarted-approval-actions-on-error 仅在原生审批调用仍等待、原 GOV-A12/A04/A07 任务和快照已登记且原执行声明证明准备尚未开始时，继续同一阶段一次；来源、授权及版本仍由原处理器复核。默认关闭，独立于已保存结果查询。已开始但无结果、等待补件及未知状态不重跑，不重启引擎或新建正式请求。\n'
    if allow_intake_saved_recovery:
        readme+='\n已启用 --allow-intake-saved-recovery：只查询当前原受理请求的已保存 GOV-A02 完成结果，核对原请求/输入/快照/七版本/来源/授权及审计后补全技术状态；--query-saved-intake-on-error 可交回同一仍等待的原宏观调用。缺结果、等待和未知保持未决，不执行缺失动作、不重启失败时点、不创建补件接收、不重提正式业务。\n'
    _write_launch_files(directory,assembly_hook='integration.government_intake_native:configure_assembly',readme_override=readme)
    return {'status':'synthetic_government_intake_bundle_unverified','directory':str(directory),'plans':len(plans)}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--run-id',required=True)
    parser.add_argument('--with-approval',action='store_true')
    parser.add_argument('--organization-actor-ids',type=Path)
    parser.add_argument('--allow-intake-saved-recovery',action='store_true')
    parser.add_argument('--query-saved-intake-on-error',action='store_true')
    parser.add_argument('--revision-first',action='store_true')
    parser.add_argument('--completion',action='store_true')
    parser.add_argument('--with-feedback',action='store_true')
    parser.add_argument('--with-monthly-feedback',action='store_true')
    parser.add_argument('--allow-monthly-saved-recovery',action='store_true')
    parser.add_argument('--query-saved-monthly-on-error',action='store_true')
    parser.add_argument('--allow-saved-recovery',action='store_true')
    parser.add_argument('--query-saved-approval-on-error',action='store_true')
    parser.add_argument('--continue-unstarted-approval-actions-on-error',action='store_true')
    args=parser.parse_args(argv);print(json.dumps(build_bundle(args.output,run_id=args.run_id,
        organization_actor_ids=(json.loads(args.organization_actor_ids.read_text(encoding='utf-8')) if args.organization_actor_ids else None),
        with_approval=args.with_approval,revision_first=args.revision_first,completion=args.completion,with_feedback=args.with_feedback,
        with_monthly_feedback=args.with_monthly_feedback,
        allow_intake_saved_recovery=args.allow_intake_saved_recovery,
        query_saved_intake_on_error=args.query_saved_intake_on_error,
        allow_monthly_saved_recovery=args.allow_monthly_saved_recovery,
        query_saved_monthly_on_error=args.query_saved_monthly_on_error,
        allow_saved_recovery=args.allow_saved_recovery,query_saved_approval_on_error=args.query_saved_approval_on_error,
        continue_unstarted_approval_actions_on_error=args.continue_unstarted_approval_actions_on_error)))


if __name__=='__main__':main()
