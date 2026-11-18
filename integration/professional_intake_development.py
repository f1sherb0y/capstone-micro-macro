"""Explicit synthetic three-role appointment and later own-feedback input bundle."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path

from integration.contractor_tender_development import _write, _write_launch_files, ref, known
from integration.professional_intake_native import COMPONENTS, ProfessionalIntakePlan, ProfessionalIntakeSettings
from src.actions.contracts.common import Reference


def declared_private_judgment_roles(*, enabled, with_feedback, roles=None):
    """Select initial policies only; never change a running firm's history."""
    supported = ('Architect', 'Engineer', 'QS')
    if type(enabled) is not bool or enabled and not with_feedback:
        raise ValueError('Private intake judgment requires the explicit --with-feedback composition')
    if roles is None:
        return supported if enabled else ()
    if (not enabled or not isinstance(roles, (list, tuple)) or not roles
            or any(type(role) is not str for role in roles)
            or len(set(roles)) != len(roles) or not set(roles) <= set(supported)):
        raise ValueError('Private intake judgment roles require an enabled policy and distinct supported professional roles')
    return tuple(roles)


def build_bundle(directory, *, run_id,with_owner=False, with_confirmation=False,project_schedule=None,
        project_object_types=None, with_opportunity=False, opportunity_interest_permitted=True,
        incompatible_confirmation_roles=(),decline_after_unresolved_confirmation=False,prior_appointment_limits=None,
        decline_after_no_interest=False,with_feedback=False,organization_actor_ids=None,
        with_private_intake_judgment=False, private_intake_judgment_roles=None):
    judgment_roles = declared_private_judgment_roles(enabled=with_private_intake_judgment,
        with_feedback=with_feedback, roles=private_intake_judgment_roles)
    if decline_after_no_interest and not with_opportunity:
        raise ValueError('Declining after no interest requires the original --with-opportunity predecessor')
    if not opportunity_interest_permitted and not with_opportunity:
        raise ValueError('Interest permission requires the original --with-opportunity predecessor')
    limits={'Architect':None,'Engineer':1,'QS':None}
    if prior_appointment_limits is not None:
        if (not isinstance(prior_appointment_limits,dict) or not set(prior_appointment_limits)<=set(limits)
                or any(v is not None and (type(v) is not int or v<1) for v in prior_appointment_limits.values())):
            raise ValueError('Professional history limits require known roles and positive counts or null')
        limits.update(prior_appointment_limits)
    if (len(set(incompatible_confirmation_roles))!=len(incompatible_confirmation_roles)
            or not set(incompatible_confirmation_roles)<={'Architect','Engineer','QS'}):
        raise ValueError('Detailed appointment incompatibility requires distinct professional roles')
    if (incompatible_confirmation_roles or decline_after_unresolved_confirmation) and not with_confirmation:
        raise ValueError('Detailed appointment history requires --with-confirmation')
    if with_confirmation and not with_owner:
        raise ValueError('Professional A03 reception requires --with-owner and its actual independent commercial handoff')
    roles = {'professional-owner': 'Owner', 'professional-architect': 'Architect',
             'professional-engineer': 'Engineer', 'professional-qs': 'QS'}
    if with_owner:roles['professional-architect-b']='Architect'
    if organization_actor_ids is not None and (
            not isinstance(organization_actor_ids,dict) or not set(organization_actor_ids)<=set(roles)
            or any(not isinstance(actor,str) or not actor.strip() for actor in organization_actor_ids.values())):
        raise ValueError('Professional actors require known organizations and nonempty actor IDs')
    actors={org:(organization_actor_ids or {}).get(org,org) for org in roles}
    if len(set(actors.values()))!=len(actors):
        raise ValueError('Professional organizations require distinct execution actors')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    clock = ref('ClockProfile', 'professional-clock')

    def point(tick):
        return {'clock_ref': clock, 'offset': tick}

    def window(start=0, end=100):
        return {'start': point(start), 'end': point(end), 'bounds': 'closed_open'}

    projects = [('professional-first', 1, 1), ('professional-followup', 0, 2)]
    object_types={project:'building' for project,_,_ in projects}
    if project_object_types is not None:
        if (not isinstance(project_object_types,dict) or set(project_object_types)!=set(object_types)
                or any(value not in {'building','infrastructure','industrial','public_facility','digital_smart'}
                    for value in project_object_types.values())):
            raise ValueError('Professional initial object types must explicitly name each original project and supported type')
        object_types=dict(project_object_types)
    if project_schedule is not None:
        schedule=dict(project_schedule)
        if (set(schedule)!={p[0] for p in projects} or len(schedule)!=len(project_schedule)
                or any(type(tick) is not int or tick<1 for tick in schedule.values())):
            raise ValueError('Professional input schedule must explicitly time each original project once')
        projects=[(project,stage_tick,schedule[project]) for project,stage_tick,_ in projects]
    scopes = {name: {'kind': 'project', 'ref': ref('Project', name), 'coverage_refs': [ref('WorkScope', name + '-work')]}
              for name, _stage_tick, _at in projects}
    organizations, grants, basis_rows = {}, {}, {}
    for organization, role in roles.items():
        basis = ref('Evidence', organization + '-assumptions')
        function = ref('FunctionAssignment', organization + '-function')
        organizations[organization] = {'organization_id': organization, 'actor_id': actors[organization],
            'source_ids': ['synthetic:' + organization], 'public_description': 'Explicit synthetic professional appointment inputs; no real-world evidence.',
            'public_location': known('Hong Kong'), 'members': [], 'evidence_refs': [basis],
            'assignments': [{'role': role, 'function_ref': function, 'configuration_version': '1', 'basis_refs': [basis]}]}
        grants[organization] = {'ref': ref('Authorization', organization + '-grant'), 'organization_id': organization,
            'actor_id': actors[organization], 'function_ref': function, 'action_ids': ['OWN-A04'] if role == 'Owner' else [role.upper() + '-A02'],
            'scopes': list(scopes.values()), 'readable_refs': [], 'tool_ids': [], 'basis_refs': [basis], 'validity': window()}
        basis_rows[organization] = {'ref': basis, 'value': {'ref': basis, 'source_kind': 'synthetic', 'basis_kind': 'assumed',
            'locator': 'professional-intake-development:independent-assumptions',
            'content_hash': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'effective_window': window()}}
    plans = []
    for project, _stage_tick, tick in projects:
        scope = scopes[project]
        for organization, role in roles.items():
            if role == 'Owner':
                continue
            if with_owner:
                scope={'kind':'project','ref':ref('Project',project),
                    'coverage_refs':[ref('WorkScope',project+'-'+role.lower()+'-service-work')]}
                for member in (organization,'professional-owner'):
                    if scope not in grants[member]['scopes']:grants[member]['scopes'].append(scope)
            tag = project + '-' + organization
            basis = organizations[organization]['evidence_refs'][0]
            native = ref('Evidence', tag + '-native')
            request_ref, terms_ref = ref('ServiceRequest', tag + '-request'), ref('ServiceTerms', tag + '-terms')
            capability_ref, calendar_ref = ref('Capability', tag + '-capability'), ref('ResourceCalendar', tag + '-calendar')
            pricing_ref, profile_ref = ref('FeeBasis', tag + '-fees'), ref('WorkProfile', tag + '-work-profile')
            candidates = ref('CandidateSet', tag + '-candidates')
            client_authority, payer_authority = ref('Authority', tag + '-commission'), ref('Authority', tag + '-payment')
            service = {'Architect': 'architectural_design', 'Engineer': 'engineering', 'QS': 'cost_estimation'}[role]
            responsibility = {'Architect': 'architectural_design', 'Engineer': 'structural_design', 'QS': 'quantity_surveying'}[role]
            objects = [deepcopy(basis_rows[organization]), deepcopy(basis_rows['professional-owner'])]

            def put(reference, **values):
                objects.append({'ref': reference, 'value': {'ref': reference, **values}})

            shared = {'evidence_refs': [basis]}
            put(native, source_kind='synthetic', basis_kind='observed', locator='native-professional-intake:' + tag,
                content_hash=None, effective_window=window())
            public_basis={'evidence_refs':[organizations['professional-owner']['evidence_refs'][0]]} if with_owner else shared
            put(clock, **public_basis, tick_unit='month')
            put(scope['ref'], **public_basis)
            put(scope['coverage_refs'][0], **public_basis, parent_ref=scope['ref'])
            for member in (organization, 'professional-owner'):
                assignment = organizations[member]['assignments'][0]
                objects.append({'ref': assignment['function_ref'], 'value': deepcopy(assignment)})
                objects.append({'ref': grants[member]['ref'], 'value': deepcopy(grants[member])})
            for reference, purpose in [(client_authority, 'commission_service'), (payer_authority, 'authorize_payment')]:
                put(reference, evidence_refs=[organizations['professional-owner']['evidence_refs'][0]],
                    organization_id='professional-owner', actor_id=actors['professional-owner'], purposes=[purpose], scopes=[scope],
                    service_codes=[service], validity=window())
            put(request_ref, **shared, scope=scope, provider_id=actors[organization], provider_organization_id=organization,
                client_id=actors['professional-owner'], client_organization_id='professional-owner', payer_id=actors['professional-owner'],
                payer_organization_id='professional-owner', client_authority_ref=client_authority, payer_authority_ref=payer_authority,
                offered_terms_ref=terms_ref, fee_basis_ref=pricing_ref, permitted_offer_scopes=[scope],
                permitted_service_codes=[service], open_question_refs=[], received_at=point(tick), effective_window=window(), status='active')
            terms = {'scope': scope, 'request_ref': request_ref, 'prior_terms_ref': None, 'provider_id': actors[organization],
                'client_id': actors['professional-owner'], 'payer_id': actors['professional-owner'], 'relation': 'external', 'region_id': known('Hong Kong'),
                'service_code': known(service), 'object_type': known(object_types[project]), 'requested_uses': known(['research']),
                'responsibility_codes': known([responsibility]), 'required_qualification_codes': known(['synthetic-professional-license']),
                'required_method_refs': known([]), 'fee': known({'value': '100', 'currency': 'HKD', 'basis_ref': basis}),
                'payment_risk': known({'value': '0.1', 'unit': 'risk', 'basis_ref': basis}), 'work_profile_ref': profile_ref,
                'effort_estimate': known({'value': '1', 'unit': 'effort', 'basis_ref': basis}),
                'desired_window': known(window(tick + 2, tick + 4)), 'deliverable_requirement_refs': [],
                'issued_at': point(tick), 'effective_window': window(), 'status': 'offered', 'selection_priority': known(1)}
            if with_owner:
                deliverable=ref('DeliverableRequirement',tag+'-research-report')
                terms['deliverable_requirement_refs']=[deliverable]
                put(deliverable,**shared,request_ref=request_ref,scope=scope,requested_use='research',
                    description='Independent declared '+role+' research report for '+project)
            capability = {'organization_id': organization, 'effective_window': window(), 'region_ids': known(['Hong Kong']),
                'service_codes': known([service]), 'object_types': known([object_types[project]]), 'allowed_uses': known(['research']),
                'responsibility_codes': known([responsibility]), 'method_refs': known([]),
                'qualification_refs': [ref('Qualification', tag + '-license')], 'qualification_coverage': 'complete'}
            qualification = {'organization_id': organization, 'code': 'synthetic-professional-license', 'region_ids': ['Hong Kong'],
                'service_codes': [service], 'effective_window': window(), 'standing': known(True)}
            profile = {'region_ids': ['Hong Kong'], 'service_codes': [service], 'object_types': [object_types[project]], 'effective_window': window(),
                'clock_ref': clock, 'resource_kind': role.lower(), 'effort_unit': 'effort', 'capacity_unit': 'capacity',
                'effort_per_capacity_tick': '1', 'method': 'constant_capacity_over_half_open_window_v1'}
            resource = {'resource_ref': ref('Resource', tag + '-resource'), 'resource_kind': role.lower(), 'region_id': known('Hong Kong'),
                'total': known({'value': '2', 'unit': 'capacity', 'basis_ref': basis}), 'effective_window': window()}
            if role == 'Engineer':
                terms.update(discipline_codes=known(['structural']), function_code=known('design'), independence_requirement_ref=None)
                capability.update(discipline_codes=known(['structural']), function_codes=known(['design']))
                qualification.update(discipline_codes=['structural'], function_codes=['design'])
                profile['discipline_codes'] = ['structural']
                resource.update(discipline_codes=known(['structural']), suitable=known(True), personnel_ids=known(['synthetic-engineer-person']))
            put(terms_ref, **shared, **terms)
            put(capability_ref, **shared, **capability)
            put(ref('Qualification', tag + '-license'), **shared, **qualification)
            put(profile_ref, **shared, **profile)
            put(calendar_ref, **shared, organization_id=organization, as_of=point(tick), coverage='complete', resources=[resource], commitments=[])
            put(pricing_ref, evidence_refs=[basis, native], organization_id=organization, scope=scope, effective_window=window(),
                minimum_fee=known({'value': '50', 'currency': 'HKD', 'basis_ref': basis}),
                maximum_payment_risk=known({'value': '0.5', 'unit': 'risk', 'basis_ref': basis}), new_work_policy=known('evaluate'),
                counteroffer_terms_refs=[], counteroffer_calculation_refs=[])
            action_input = {'scope': scope, 'request_ref': request_ref, 'terms_ref': terms_ref,
                'capability_ref': capability_ref, 'capacity_ref': calendar_ref}
            if role == 'Architect':
                action_input['price_basis_ref'] = pricing_ref
            elif role == 'Engineer':
                action_input['independence_requirement_ref'] = None
            else:
                conflict = ref('ConflictCheck', tag + '-conflict')
                put(conflict, **shared, organization_id=organization, request_ref=request_ref, scope=scope,
                    status='clear', conflict_codes=[], checked_at=point(tick), effective_window=window())
                action_input['conflict_check_ref'] = conflict
            objects.append({'ref': candidates, 'value': {'operation_id': tag, 'scope': scope, 'as_of': point(tick),
                'candidates': [{'ref': request_ref, 'permitted_choices': ['decline']},
                               {'ref': terms_ref, 'permitted_choices': ['accept']}],
                'search_profile_ref': ref('Profile', tag + '-exposure')}})
            refs = [row['ref'] for row in objects]
            grants[organization]['readable_refs'].extend(refs)
            context = {'run_id': run_id, 'actor_id': actors[organization], 'function_ref': organizations[organization]['assignments'][0]['function_ref'],
                'authorization_refs': [grants[organization]['ref']], 'operation_id': tag, 'contract_ref': ref('ActionContract', role.upper() + '-A02'),
                'task_ref': ref('DecisionTask', tag), 'scope': scope, 'business_time': point(tick), 'read_token': tag + '-read',
                'visible_refs': refs, 'candidate_set_ref': candidates, 'execution_mode': 'rule'}
            plans.append({'organization_id': organization, 'role': role, 'project_id': project, 'tick': tick, 'context': context,
                'action_input': action_input, 'objects': objects, 'native_evidence_ref': native,
                'max_prior_appointments':limits[role],
                'unresolved_appointment_policy':'decline_new_work' if decline_after_unresolved_confirmation else 'require_resolution',
                'utility': {'value': '0.7', 'unit': 'score', 'basis_ref': basis},
                'probability': {'value': '1', 'unit': 'probability', 'basis_ref': basis}})
    if with_opportunity:
        from integration.professional_opportunity_development import add_opportunity
        for plan in plans:
            add_opportunity(plan,grants[plan['organization_id']],interest_permitted=opportunity_interest_permitted,
                decline_after_no_interest=decline_after_no_interest)
    owner_plans=[]
    if with_owner:
        from integration.owner_commission_native_development import commission_plans
        owner_plans=commission_plans(directory,run_id=run_id,professional_plans=plans,
            organizations=organizations,grants=grants,basis_rows=basis_rows)
    confirmation_plans = []
    if with_confirmation:
        from integration.professional_appointment_native_development import appointment_plans
        confirmation_plans = appointment_plans(professional_plans=plans, grants=grants,
            incompatible_first_roles=incompatible_confirmation_roles)
    feedback_plans = []
    if with_feedback:
        from integration.professional_feedback_development import feedback_plan
        from integration.professional_private_judgment_development import judgment_plan
        for plan in plans:
            private_judgment = plan['role'] in judgment_roles
            if private_judgment:
                plan['private_intake_judgment_policy'] = 'pause_after_actual_selection_recommendation'
            for event_type in ('appointment_decision', 'consultant_team_appointed'):
                feedback_plans.append(judgment_plan(plan, grant=grants[plan['organization_id']])
                    if private_judgment and event_type == 'consultant_team_appointed'
                    else feedback_plan(plan, grant=grants[plan['organization_id']], event_type=event_type))
    # One immutable initial grant value across all supplied projections.
    for grant in grants.values():
        grant['readable_refs'] = list({json.dumps(r, sort_keys=True): r for r in grant['readable_refs']}.values())
    for plan in feedback_plans:
        for row in plan['objects']:
            if row['ref']['kind'] == 'Authorization':
                row['value'] = deepcopy(grants[row['value']['organization_id']])
    for plan in plans:
        for row in [*plan['objects'],*plan.get('opportunity',{}).get('objects',[])]:
            if row['ref']['kind'] == 'Authorization':
                row['value'] = deepcopy(grants[row['value']['organization_id']])
        ProfessionalIntakePlan.model_validate(plan)
        schemas = COMPONENTS[plan['role']][0].SOURCE_SCHEMAS()
        for row in plan['objects']:
            value = deepcopy(row['value'])
            if row['ref'] == plan['native_evidence_ref'] or with_opportunity and row['ref']==plan['opportunity']['handoff_evidence_ref']:
                value['content_hash'] = '0' * 64  # Temporary schema validation only.
            schemas.validate_projection(Reference.model_validate(row['ref']), value)
        if with_opportunity:
            from integration.professional_opportunity_development import validate_opportunity
            validate_opportunity(plan)
    inputs = _write(directory, 'professional-input.json', {'schema_version': 'professional-intake-input.v1', 'run_id': run_id, 'plans': plans})
    owner_settings=None
    if with_owner:
        from integration.owner_commission_native_development import write_commission_sources
        owner_settings=write_commission_sources(directory,run_id=run_id,plans=owner_plans,grants=grants)
    appointment_settings = None
    if with_confirmation:
        from integration.professional_appointment_native_development import write_appointment_sources
        appointment_settings = write_appointment_sources(directory, run_id=run_id, plans=confirmation_plans, grants=grants)
    settings = ProfessionalIntakeSettings.model_validate({'version': '1', 'policy_version': 'professional-explicit-assumptions-v1',
        'owner_final_source': 'original_micro_owner_commission_proposal' if with_owner else 'original_native_appointment_proposal',
        'owner':owner_settings, 'appointment': appointment_settings,
        'feedback':({'version':'1','policy_version':'professional-own-native-feedback.v1',
            **_write(directory,'professional-feedback-input.json',{'schema_version':'native-lifecycle-actions-input.v1',
                'run_id':run_id,'source_declaration':'independent_inputs_not_native_execution_proof',
                'plans':feedback_plans})} if with_feedback else None),
        'authority': {'runtime_id': run_id, 'version': '1', 'organization_snapshot': {'schema_version': 'organization.v2', 'run_id': run_id,
            'organizations': list(organizations.values()), 'authorizations': list(grants.values())}}, **inputs})
    _write(directory, 'assembly-host.json', {'schema_version': 'gba-module-host-config.v1', 'host_id': run_id,
        'version': '1', 'settings': settings.model_dump(mode='json')})
    _write(directory, 'native-host.json', {'schema_version': 'gba-module-host-config.v1', 'host_id': run_id, 'version': '1',
        'settings': {'run_id': run_id, 'micro_professional_intake_scope': True,'micro_owner_commission_scope':with_owner,
            'native_proposals': [{'role': r, 'operation': 'decide_monthly_operation'} for r in sorted(set(roles.values()))]
                + ([] if with_owner else [{'role': 'Owner', 'operation': 'select_appointment'}]),
            'native_decisions': [{'role': r, 'decision_type': 'monthly_enterprise_operation'} for r in sorted(set(roles.values()))]}})
    from gba_construction_sim.backend.models.simulation import SimulationCreateRequest

    macro = SimulationCreateRequest.model_validate({'agent_source': 'explicit', 'agents': [
        {'agent_id': name, 'name': name, 'role': role, 'region': 'Hong Kong', 'enterprise_type': 'explicit_synthetic',
         'total_resource_capacity': 10} for name, role in roles.items()],
        'initial_projects': [{'project_id': name, 'name': 'Synthetic professional service ' + name, 'project_type': object_types[name],
            'region': 'Hong Kong', 'owner_id': 'professional-owner', 'initial_budget': 1000,
            'current_stage': 'initiation', 'stage_tick': stage_tick} for name, stage_tick, _tick in projects],
        'enable_project_generation': False, 'use_prior_network_edges': False, 'ticks': 2, 'random_seed': 42})
    _write(directory, 'macro-request.json', macro.model_dump(mode='json'))
    readme="""# 合成专业委任及后续反馈消费

运行 `& './run.ps1'`。同一业主与 Architect/Engineer/QS，两个错峰项目，两个原生时点。
原 A02 工作者在真实 consider_appointment 请求到来后形成接受/拒绝；propose/decide 复用同一结果。
业主选人提案和月度操作显式使用原宏观行为，不计为微观覆盖；宏观创建正式委任和 engagement。
业主最终选择明确读取同一次原 OwnerAgent.select_appointment 提案并校验候选范围，不另作规则选择。
各专业组织只接收自己的决定、是否实际获委任；后续 A02 读取原生已委任反馈及原微观摘要。
Engineer 的显式组织策略规定：已实际获一次委任后不再接新委托，后续项目应由原 A02 作商业拒绝。

服务范围、委托/付款授权、资格、能力、费用、风险、日历、生产率和协议指标均是 synthetic/assumed。
原生规范化容量不是微观专业人员数量。微观服务费不在此收取，未声称正式费用或完整服务合同成立。
实际请求和较早本组织委任记录的哈希在运行时绑定。无模型调用，澄清/补件不会伪装成拒绝或成功。
三角色 A03 的委任后确认及更细服务履约仍待后续接线；本输入不是八角色/106 动作整体完成证据。
input-manifest.json 固定输入；修改输入应生成新目录，旧任务库保留。
"""
    if with_owner:
        readme='''# 原 OWN-A04 与实际专业委任

运行 `& './run.ps1'`。三类专业原 A02 在真实请求中接受或拒绝，原 OWN-A04 再实算业主管理容量、费用上限和明确偏好，经原生提案/最终确认交宏观委任。
两个建筑师独立接受同一初始研究工作要求。服务、资格、费用、付款/签署授权及完整管理负荷为明确合成输入；Owner 私有接收视图逐字段核对实际 A02 条款、交付要求、来源、作者及授权，不共享专业方费率策略、私人日历或讨论。
只由原宏观创建项目委任和 engagement；没有模拟专业报价发布、详细签约、收费、付款或容量预留，也未声称三角色 A03 确认已执行。
首个项目形成的本业主真实委任结果按角色反馈。下一项目原 OWN-A04 读取已核对的真实结果；明确 repeat_provider_priority_penalty=2 只改变私有选人偏好，可从建筑师 A 改选 B，不改资格、费用或物理管理负荷。
Engineer 的原有一次委任后拒绝策略保留。无独立接受者时原 OWN-A04 返回 reject_all，只表达本次未选人，不伪造重招或终止既有委任。
默认不带 --with-owner 的专业接单开发入口保留原生业主选择。八角色/106 动作、其他委任分支、三方确认、专业履约、综合装配和恢复仍待后续完成。
宏观源码冻结，不启用旧采购生命周期，不建立第二套正式账本，无真实模型调用。
'''
    if with_confirmation:
        readme = readme.replace('也未声称三角色 A03 确认已执行。', '三角色 A03 私有兼容确认由下述显式接收入口处理。')
        readme = readme.replace('三方确认、专业履约', '专业履约')
        readme += '''
\n已显式启用 --with-confirmation：宏观实际 consultant_team_appointed 事件投递给获委任者后，客户端原 continuation_dispatcher 调用原三专业 A03 assembler/worker，核对原独立 A02、原 OWN-A04、原生提案/最终确认与实际选人事件。未中选或拒单者不执行 A03。
A03 只形成私有兼容确认；不创建详细服务关系、合同、收费、资源预留或任务分配。QS 未提供具体任务，原处理器只确认委任，不声称完成任务计划。人员/能力/冲突检查/日历等仍是明确合成输入，QS 细化视图保持原物理容量与负荷不变。
后续原 A02 必须读取本机构严格较早的原 A03 确认；缺失、待补或不兼容保留待复核，不转成成功或原生规则兜底。重复投递只核对既有任务，不重跑。微观确认失败不会撤销宏观已执行的实际委任。
'''
    if with_opportunity:
        readme += '''
\n已启用 --with-opportunity：实际 consider_appointment 请求先执行原三专业 A01，原 express_interest 结果及有权来源以独立 Evidence 交原 A02 消费。表达兴趣不发消息、不接受委任、不收费或预留资源；仍由原 A02 和宏观原有接口分别决定接单及正式选人。其他 A01 选择保留原状态并停止本次接单评估，不冒充宏观拒单。初始机会访问和兴趣权限、专业策略及日历均为明确合成来源。
'''
        if decline_after_no_interest:
            readme += '\n--decline-after-no-interest 显式声明本机构不参与后的新增工作策略：原 A01 的 ignore（Architect/QS）或 decline（Engineer）形成后，以原结果证据交原 A02，按 FeeBasis.new_work_policy=decline 重新评估并返回宏观原拒单接口。A01 本身不充当正式拒单；clarify、track、prepare、缺资料及失败仍保留原未决边界。--without-interest 用于声明初始兴趣权限为 false 的合成来源。\n'
    if with_feedback:
        readme += '\n已启用 --with-feedback：原生 appointment_decision 实际投递后，核对本机构原 A02、原提案和最终决定，由原三专业 A12 记录接受意向或实际拒单。实际 consultant_team_appointed 仅为中选机构触发另一项原 A12，记录 appointed；后轮原 A02 读取本机构已完成记录及真实委任历史，继续使用既有次数策略。反馈不创建详细委任、履约、收费、现金、训练或资质更新。未中选计划保持未触发；all_triggered_private_actions_formed 与全部计划完成分别报告。已声明但缺失的历史反馈结果需诊断，不自动重跑。\n'
    if with_private_intake_judgment:
        readme += '\n--with-private-intake-judgment 显式启用合成场景中的私有接单建议：实际中选后，原评估保存/发布组件通过既有 fixture 模式计算初始声明的有限合作规则，原 A12 形成 update_judgment 建议；后轮原 A02 核对本机构原结果和发布摘要，按初始明确策略暂停新增接单。来源继续标为 synthetic，不绕过正式来源要求、不应用正式策略、不推断能力/资质/资金变化。次数策略独立；可用 --prior-appointment-limits 的 null 关闭它以单独观察建议消费。\n'
    if with_private_intake_judgment:
        readme += '\nInitial private intake judgment roles: ' + ', '.join(judgment_roles) + '. --private-intake-judgment-role may be repeated; omitted means all three professional roles. Other roles retain record-only selection feedback. This selects initial private policies, not runtime identity/history changes.\n'
    if incompatible_confirmation_roles or decline_after_unresolved_confirmation:
        readme+='\n--incompatible-confirmation-role 显式声明首轮独立详细委任不兼容来源；原 A03 自行形成 decline_incompatible 或 request_amendment，问题保留为私有结果，不代表已送达补件、撤销委任或修约。--decline-after-unresolved-confirmation 显式配置后轮接单策略：核对本机构较早实际委任及原 A03 未决结果后，交原 A02 按原 FeeBasis 拒绝新增工作。默认仍要求先解决，不改旧合同、委任、费用、资源或专业能力。\n'
    if prior_appointment_limits is not None:
        readme+='\n--prior-appointment-limits 接收按角色配置的 JSON 对象，例如 {"Engineer":null} 关闭工程师的历史委任次数限制；正整数为拒绝新增工作的次数门槛，未声明角色保留默认策略。次数限制与 A03 未决结果策略独立，不改变专业能力或已有委任。\n'
    if organization_actor_ids is not None:
        _write(directory,'initial-organization-actors.json',{'schema_version':'initial-organization-actors.v1',
            'run_id':run_id,'organization_actor_ids':actors,'boundary':'Initial declarations only; no runtime identity or history migration.'})
    readme+='\n--organization-actor-ids 接收组织到执行 actor 的 JSON 映射，在最初构建授权、服务条款、邀请、商业披露及确认来源时绑定。宏观 agent、任务组织和法律机构保持组织 ID；服务契约中的 provider_id/client_id/payer_id 按原契约使用 actor，各自的 organization_id 保留机构归属。旧输入和运行历史不迁移；八角色共享组合需另行装配验证。\n'
    _write_launch_files(directory,assembly_hook='integration.professional_intake_native:configure_assembly',readme_override=readme)
    return {'status': 'synthetic_professional_intake_bundle_unverified', 'directory': str(directory), 'run_id': run_id}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--with-owner',action='store_true')
    parser.add_argument('--with-confirmation', action='store_true')
    parser.add_argument('--with-opportunity', action='store_true')
    parser.add_argument('--with-feedback', action='store_true')
    parser.add_argument('--with-private-intake-judgment', action='store_true')
    parser.add_argument('--private-intake-judgment-role', action='append', choices=['Architect','Engineer','QS'])
    parser.add_argument('--without-interest', action='store_true')
    parser.add_argument('--decline-after-no-interest', action='store_true')
    parser.add_argument('--incompatible-confirmation-role',action='append',choices=['Architect','Engineer','QS'],default=[])
    parser.add_argument('--decline-after-unresolved-confirmation',action='store_true')
    parser.add_argument('--prior-appointment-limits',type=json.loads)
    parser.add_argument('--organization-actor-ids',type=json.loads)
    args = parser.parse_args(argv)
    print(json.dumps(build_bundle(args.output, run_id=args.run_id,with_owner=args.with_owner,
        with_confirmation=args.with_confirmation,with_opportunity=args.with_opportunity,
        with_feedback=args.with_feedback,
        with_private_intake_judgment=args.with_private_intake_judgment,
        private_intake_judgment_roles=args.private_intake_judgment_role,
        opportunity_interest_permitted=not args.without_interest,
        decline_after_no_interest=args.decline_after_no_interest,
        incompatible_confirmation_roles=args.incompatible_confirmation_role,
        decline_after_unresolved_confirmation=args.decline_after_unresolved_confirmation,
        prior_appointment_limits=args.prior_appointment_limits,
        organization_actor_ids=args.organization_actor_ids), ensure_ascii=False))


if __name__ == '__main__':
    main()
