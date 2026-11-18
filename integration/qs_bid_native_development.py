"""Author explicit QS evaluation inputs over the existing Owner/Contractor bundle."""
from copy import deepcopy
import argparse
import json
from pathlib import Path

from integration.contractor_tender_development import _write, _write_launch_files, ref, known
from integration.owner_invitation_development import build_bundle as build_owner
from src.coordination.tasks import task_digest


def build_bundle(directory, *, run_id, with_native_owner_selection=False,with_evaluation_feedback=False,
        with_qs_learning=False,allow_qs_learning_saved_recovery=False,query_saved_qs_learning_on_error=False,
        owner_options=None,with_original_bid_history=False,exclude_contractor_id=None,exclude_all_bids=False,clarify_contractor_id=None):
    if type(with_original_bid_history) is not bool or with_original_bid_history and not with_native_owner_selection:
        raise ValueError('Original bid history requires explicitly declared native Owner selection')
    if type(with_native_owner_selection) is not bool:
        raise ValueError('Native Owner selection requires an explicit boolean configuration')
    if type(with_evaluation_feedback) is not bool or with_evaluation_feedback and not with_native_owner_selection:
        raise ValueError('Evaluation feedback requires explicit native Owner module selection')
    if type(with_qs_learning) is not bool or with_qs_learning and not with_evaluation_feedback:
        raise ValueError('QS learning requires the explicit earlier actual evaluation feedback window')
    if allow_qs_learning_saved_recovery and not with_qs_learning:
        raise ValueError('QS learning recovery requires --with-qs-learning')
    if query_saved_qs_learning_on_error and not allow_qs_learning_saved_recovery:
        raise ValueError('QS learning query requires --allow-qs-learning-saved-recovery')
    owner_options = deepcopy(owner_options) if owner_options is not None else {}
    if not isinstance(owner_options, dict) or {'run_id','evaluation_feedback'} & set(owner_options):
        raise ValueError('QS input composition requires independent initial Owner options without run/time overrides')
    if owner_options.pop('feedback_followup',with_evaluation_feedback) != with_evaluation_feedback:
        raise ValueError('QS feedback timing must match the explicitly selected evaluation feedback window')
    owner_id = owner_options.get('owner_id','dev-owner')
    qs_id = owner_options.get('qs_id','dev-qs')
    contractor_ids = owner_options.get('contractor_ids',('dev-contractor-a','dev-contractor-b'))
    if exclude_contractor_id is not None and (not with_native_owner_selection
            or not isinstance(exclude_contractor_id,str) or exclude_contractor_id not in contractor_ids):
        raise ValueError('Authorized exclusion requires native Owner selection and one declared original Contractor ID')
    if type(exclude_all_bids) is not bool or exclude_all_bids and (
            exclude_contractor_id is not None or not with_native_owner_selection or not with_evaluation_feedback):
        raise ValueError('All-bid exclusion requires native selection, evaluation feedback and no single-bid exclusion override')
    if clarify_contractor_id is not None and (not with_native_owner_selection
            or clarify_contractor_id not in contractor_ids or exclude_contractor_id is not None or exclude_all_bids):
        raise ValueError('Bid clarification requires native Owner selection, one original bidder and no exclusion override')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    child = directory / 'owner-contractor'
    build_owner(child, run_id=run_id,feedback_followup=with_evaluation_feedback,
        evaluation_feedback=with_evaluation_feedback,**owner_options)
    bid_tick=1 if with_evaluation_feedback else 2
    evaluation_tick=3 if with_evaluation_feedback else 4

    def read(name):
        return json.loads((child / name).read_text(encoding='utf-8'))

    configuration_input = read('tender-configuration-input.json')
    authority = configuration_input['authority']['organization_snapshot']
    organizations = {o['organization_id']: o for o in authority['organizations']}
    grants = {g['organization_id']: g for g in authority['authorizations']}
    qs = organizations[qs_id]
    grant = grants[qs_id]
    grant['action_ids'].append('QS-A06')
    owner_context = read('owner-invitation-input.json')['plans'][0]['context']
    scope, clock = owner_context['scope'], owner_context['business_time']['clock_ref']
    now = {'clock_ref': clock, 'offset': evaluation_tick}
    # Evaluation follows actual submission by two original lifecycle ticks.
    values = {}
    shared_evidence = {task_digest(e) for organization in organizations.values() for e in organization['evidence_refs']}
    for name in ('sources.json', 'quantity-sources.json'):
        for snapshot in read(name)['snapshots']:
            for row in snapshot['projection']['objects']:
                if (row['ref']['kind'] in {'ClockProfile', 'Project', 'WorkScope', 'FunctionAssignment', 'Authorization'}
                        or task_digest(row['ref']) in shared_evidence):
                    values[task_digest(row['ref'])] = deepcopy(row)
    objects = list(values.values())
    basis = qs['evidence_refs'][0]
    profile = ref('EvaluationProfile', 'dev-qs-native-profile')
    round_ref = ref('ProcurementRound', 'dev-qs-native-round')
    document = ref('ProcurementDocument', 'dev-qs-native-document')
    procurement = ref('ProcurementScope', 'dev-qs-native-scope')
    rule = ref('EvaluationRule', 'dev-qs-native-qualification-rule')
    candidates = ref('CandidateSet', 'dev-qs-native-candidates')
    common = {'scope': scope, 'available_at': now, 'effective_window': grant['validity'], 'evidence_refs': [basis]}
    author = {'author_actor_id': qs['actor_id'], 'author_function_ref': qs['assignments'][0]['function_ref'],
        'author_authority_ref': grant['ref']}

    def put(reference, **value):
        objects.append({'ref': reference, 'value': {'ref': reference, **value}})

    bids = []
    for contractor in contractor_ids:
        organization = organizations[contractor]
        bid_ref = ref('Bid', 'dev-qs-native-' + contractor)
        evidence = ref('Evidence', 'dev-qs-native-submission-' + contractor)
        eligibility = ref('EligibilityAssessment', 'dev-qs-native-eligibility-' + contractor)
        put(evidence, source_kind='synthetic', basis_kind='observed', locator='native-submitted-bid:' + contractor,
            content_hash=None, effective_window=grant['validity'])
        put(bid_ref, **{**common, 'evidence_refs': [basis, evidence]}, round_ref=round_ref, document_ref=document,
            bidder_id=organization['actor_id'], bidder_organization_id=contractor,
            function_ref=organization['assignments'][0]['function_ref'], authority_ref=grants[contractor]['ref'],
            submission_action_id='CONTRACTOR-A02', status='submitted', submitted_at=None, price=None,
            region_id='Hong Kong', price_time={'clock_ref': clock, 'offset': bid_tick}, included_scope_keys=['normalized-work'],
            eligibility_ref=eligibility, normalization_basis_ref=None)
        put(eligibility, **common, **author, author_action_id='QS-A06', round_ref=round_ref, document_ref=document,
            bid_ref=bid_ref, rule_refs=[rule], status='ok', qualified=known(True), compliant=known(True),
            risk=known({'value': '0.2', 'unit': 'risk', 'basis_ref': basis}), checked_at=now)
        bids.append({'contractor_id': contractor, 'bid_ref': bid_ref, 'evidence_ref': evidence,
            'evaluation_score': {'value': '0.7', 'unit': 'score', 'basis_ref': basis}})
    put(round_ref, **common, procurement_scope_ref=procurement, buyer_id=owner_id, buyer_organization_id=owner_id,
        template_ref=ref('ProcurementTemplate', 'dev-qs-native-template'), status='closed', document_ref=document,
        bid_refs=[b['bid_ref'] for b in bids], clarification_refs=[])
    put(document, **common, **author, author_action_id='QS-A05', round_ref=round_ref, status='published', draft={
        'procurement_scope_ref': procurement, 'design_refs': [], 'quantity_schedule_ref': ref('QuantitySchedule', 'dev-qs-native-quantity'),
        'measurement_rule_ref': ref('MeasurementRule', 'dev-qs-native-measurement'),
        'pricing_rule_ref': ref('PricingRule', 'dev-qs-native-pricing'), 'exclusions': [], 'open_questions': [], 'prior_document_ref': None})
    put(rule, **common, round_ref=round_ref, document_ref=document, predicate='qualification', consequence='recommend_exclusion')
    put(profile, **common, round_ref=round_ref, document_ref=document, organization_id=qs_id,
        function_ref=qs['assignments'][0]['function_ref'], authority_ref=grant['ref'], currency='HKD', region_id='Hong Kong',
        price_time={'clock_ref': clock, 'offset': bid_tick}, required_scope_keys=['normalized-work'], rule_refs=[rule],
        question_refs=[], on_unknown='report', normalization_result_ref=None, ranking_result_ref=None, criteria=[],
        exclusion_bid_ref=None, exclusion_rule_ref=None, exclusion_authority_ref=None)
    operation_id = 'dev-qs-native-evaluation'
    # CandidateSet has no intrinsic ref field in its schema.
    objects.append({'ref': candidates, 'value': {'operation_id': operation_id, 'scope': scope, 'as_of': now,
        'candidates': [{'ref': round_ref, 'permitted_choices': ['evaluate']}],
        'search_profile_ref': ref('Profile', 'dev-qs-native-exposure')}})
    refs = [row['ref'] for row in objects]
    grant['readable_refs'] = deepcopy(refs)
    for row in objects:
        if row['ref']['kind'] == 'Authorization':
            row['value'] = deepcopy(grants[row['value']['organization_id']])
    context = {**deepcopy(owner_context), 'actor_id': qs['actor_id'], 'function_ref': qs['assignments'][0]['function_ref'],
        'authorization_refs': [grant['ref']], 'operation_id': operation_id, 'contract_ref': ref('ActionContract', 'QS-A06'),
        'task_ref': ref('DecisionTask', operation_id), 'business_time': now, 'read_token': operation_id + '-read',
        'visible_refs': refs, 'candidate_set_ref': candidates}
    plan = {'organization_id': qs_id, 'project_id': scope['ref']['id'], 'tick': evaluation_tick, 'currency': 'HKD', 'context': context,
        'objects': objects, 'bids': bids, 'action_input': {'scope': scope, 'round_ref': round_ref,
            'procurement_document_ref': document, 'bid_refs': [b['bid_ref'] for b in bids], 'clarification_refs': [],
            'evaluation_profile_ref': profile, 'method_result_refs': []}}
    from integration.qs_bid_native import QSBidNativePlan
    from src.actions.contracts.qs_bid_objects import qs_bid_schemas
    from src.actions.contracts.common import Reference

    admissibility_settings = None
    if exclude_contractor_id is not None:
        from integration.qs_bid_admissibility_development import prepare_admissibility_sources
        from integration.qs_bid_admissibility import QSBidAdmissibilityPlan
        exclusion = prepare_admissibility_sources(plan,contractor_id=exclude_contractor_id,
            authorizations=authority['authorizations'])
        exclusion = QSBidAdmissibilityPlan.model_validate(exclusion).model_dump(mode='json')
        admissibility_settings = {'version':'1',**_write(directory,'qs-admissibility-input.json',
            {'schema_version':'qs-bid-admissibility-input.v1','run_id':run_id,'plans':[exclusion]})}
    if clarify_contractor_id is not None:
        from integration.qs_bid_clarification_development import prepare_bid_question
        prepare_bid_question(plan,contractor_id=clarify_contractor_id,authorizations=authority['authorizations'])
    plans = [plan]
    if exclude_all_bids:
        from integration.qs_bid_all_excluded_development import prepare_all_excluded_rounds
        from integration.qs_bid_admissibility import QSBidAdmissibilityPlan
        plans, exclusions = prepare_all_excluded_rounds(plan,authorizations=authority['authorizations'])
        exclusions = [QSBidAdmissibilityPlan.model_validate(p).model_dump(mode='json') for p in exclusions]
        admissibility_settings = {'version':'1',**_write(directory,'qs-admissibility-input.json',
            {'schema_version':'qs-bid-admissibility-input.v1','run_id':run_id,'plans':exclusions})}
    plans = [QSBidNativePlan.model_validate(p).model_dump(mode='json') for p in plans]
    plan = plans[0]
    for row in objects:
        value = deepcopy(row['value'])
        if row['ref'] in [b['evidence_ref'] for b in bids]:
            value['content_hash'] = '0' * 64  # Schema check only; not written to inputs.
        if row['ref']['kind'] == 'Bid':
            value['price'] = known({'value': '0', 'currency': 'HKD', 'basis_ref': basis})
            value['submitted_at'] = {'clock_ref': clock, 'offset': bid_tick}
        qs_bid_schemas().validate_projection(Reference.model_validate(row['ref']), value)
    qs_file = _write(directory, 'qs-bid-input.json', {'schema_version': 'qs-bid-native-input.v1', 'run_id': run_id, 'plans': plans})
    learning_settings = None
    if with_qs_learning:
        from integration.qs_evaluation_learning_development import learning_plan
        learning = learning_plan(plan, tick=4, authorizations=authority['authorizations'])
        learning_settings = {'version': '1', 'allow_saved_recovery':allow_qs_learning_saved_recovery,
            **_write(directory, 'qs-learning-input.json', {
            'schema_version': 'qs-evaluation-learning-input.v1', 'run_id': run_id, 'plans': [learning]})}
    for name, field in [('sources.json', 'snapshots'), ('quantity-sources.json', 'quantity_snapshots')]:
        sources = read(name)
        for snapshot in sources['snapshots']:
            for row in snapshot['projection']['objects']:
                if row['ref']['kind'] == 'Authorization':
                    row['value'] = deepcopy(grants[row['value']['organization_id']])
        file = _write(directory, name, sources)
        configuration_input[field].update(snapshot_path=file['file_path'], snapshot_sha256=file['file_sha256'])
    owner_source = read('owner-invitation-input.json')
    for p in owner_source['plans']:
        for row in p['objects']:
            if row['ref']['kind'] == 'Authorization':
                row['value'] = deepcopy(grants[row['value']['organization_id']])
    owner_file = _write(directory, 'owner-invitation-input.json', owner_source)
    from integration.contractor_tender_configuration import build_configuration
    from integration.module_host import GbaModuleHostConfiguration

    if with_original_bid_history:
        from integration.contractor_selected_tender_sources import declare_selected_tender_history
        contexts = declare_selected_tender_history(configuration_input, query_tick=evaluation_tick)
        _write(directory,'selected-tender-history-input.json',{'schema_version':'selected-tender-history-input.v1',
            'run_id':run_id,'contexts':contexts})
    configuration = build_configuration(configuration_input).model_dump(mode='json')
    sources = configuration['settings']['source_settings']
    sources['application_settings'] = {'owner_contractor': {'contractor': sources['application_settings'],
        'owner_invitation': {'version': '1', **owner_file}, 'policy_version': configuration_input['policy_version']},
        'qs_bid': {'version': '1', **qs_file}, 'policy_version': configuration_input['policy_version']}
    if learning_settings is not None:
        sources['application_settings']['qs_bid']['learning'] = learning_settings
    if admissibility_settings is not None:
        sources['application_settings']['qs_bid']['admissibility'] = admissibility_settings
    if clarify_contractor_id is not None:
        sources['application_settings']['qs_bid']['publish_native_bid_questions'] = True
    sources['application_factory'] = 'integration.qs_bid_native:build_application'
    _write(directory, 'tender-configuration-input.json', configuration_input)
    _write(directory, 'tender-host.json', GbaModuleHostConfiguration.model_validate(configuration).model_dump(mode='json'))
    native = read('native-host.json')
    native['settings']['micro_qs_evaluation_scope'] = True
    native['settings']['mixed_qs_learning_scope'] = with_qs_learning
    native['settings']['query_saved_qs_learning_on_error'] = query_saved_qs_learning_on_error
    # Keep the next original operation explicit even though its frozen external
    # contract is known to reject the required field. An undeclared route must
    # not hide that independently verified compatibility boundary.
    native['settings']['native_proposals'].append({'role': 'Owner', 'operation': 'select_preferred_bid'})
    native['settings']['native_decisions'].append({'role': 'Owner', 'decision_type': 'owner_preferred_bidder_selection'})
    if with_native_owner_selection:
        native['settings']['direct_native_proposals']=[{'role':'Owner','operation':'select_preferred_bid'}]
    if with_evaluation_feedback:
        native['settings']['native_proposals'].extend([{'role':'Owner','operation':'decide_contract_award'},
            {'role':'Contractor','operation':'decide_contract_terms'}])
        native['settings']['native_decisions'].extend([{'role':'Owner','decision_type':'owner_contract_award'},
            {'role':'Contractor','decision_type':'contract_negotiation'}])
    _write(directory, 'native-host.json', native)
    request = read('macro-request.json')
    request['ticks'] = 4
    _write(directory, 'macro-request.json', request)
    _write(directory, 'assembly-host.json', {'schema_version': 'gba-module-host-config.v1', 'host_id': run_id, 'version': '1',
        'settings': {'tender_configuration_path': str(directory / 'tender-host.json')}})
    source_note = {'source_mode': 'synthetic_assumption',
        'note': 'Original prices/time bind actual committed Contractor submission events; published micro document, '
                'scope coverage, eligibility, compliance and scores are independent synthetic assumptions. No bid ranking is asserted.',
        'limit': ('Explicit native Owner module selection is enabled; Owner selection is original native behavior, '
                 'not a micro OWN-A08 result. Only actual runtime events establish evaluation or award.'
                 if with_native_owner_selection else
                 'The frozen native Owner select_preferred_bid contract conflict follows QS evaluation; '
                 'this bundle must not claim committed evaluation/award or successful completion past that boundary.')}
    if with_evaluation_feedback:
        initial_invitations = json.loads((child / 'contractor' / 'initial-invitation-source.json').read_text(encoding='utf-8'))
        _write(directory, 'initial-invitation-source.json', initial_invitations)
        source_note['initial_invitations'] = initial_invitations
        source_note['evaluation_feedback'] = {
            'source': 'authorized own query of actual earlier native bid_evaluation_completed events',
            'first_bid_tick': bid_tick, 'evaluation_tick': evaluation_tick, 'later_screening_tick': 4,
            'decline_after_prior_submissions': 999, 'decline_after_prior_evaluations': 1,
            'limit': 'An explicit private intake preference; no award, profit or released-resource inference.'}
    if with_qs_learning:
        source_note['qs_learning'] = {'action': 'QS-A12', 'choice': 'record_feedback', 'tick': 4,
            'trigger': 'Original native monthly request', 'source': 'Authorized own query, not external delivery',
            'boundary': 'Original monthly business stays native; no forecast error, applied judgment or training.'}
    if exclude_all_bids:
        source_note['all_bids_excluded'] = {'synthetic_initial_failure_and_delegation':True,
            'review_ticks':[p['tick'] for p in plans],'contractors':list(contractor_ids),
            'native_effect':'Original selection deferral, not a terminal buyer rejection or a signed contract'}
    if clarify_contractor_id is not None:
        source_note['bid_clarification'] = {'contractor_id':clarify_contractor_id,
            'independent_qualification_state':'unknown','original_bid_price_unchanged':True,
            'native_effect':'Actual question message only; evaluation waits for real bidder answers and new authorized sources'}
    _write(directory, 'source-note.json', source_note)
    readme="""# 合成业主邀请、投标及 QS 评标输入

运行 `& './run.ps1'`。时点 1 原 OWN-A09 邀请、时点 2 原 A01/A02 投标、时点 4 原 QS-A06 评标。
同一轮次只执行一次 QS-A06，各原生单份投标请求读取同一轮次结果；未知、澄清和建议排除不会冒充准入。
价格和提交时间在运行时读取实际原生提交事件，并核对原请求/反馈任务；输入不预填报价。
初始已发布微观文件、覆盖范围、资格/合规、风险及 0.7 分数是显式合成假设；不声称专业方法实证有效。

已知限制：原生 Owner.select_preferred_bid 同时要求且禁止 selected_contractor_id；宏观保持冻结。
默认运行预计在评标后的该入口失败。原生时点可能回滚，保存的 QS 工作结果不是正式评标完成回执。
此包用于检视评标接线和定位兼容边界，不能宣称授标或全链成功。原 journal 和失败输出保留。
输入由 input-manifest.json 固定；修改输入应生成新包。完整回归集中进行。
"""
    if with_native_owner_selection:
        readme=readme.replace('已知限制：原生 Owner.select_preferred_bid 同时要求且禁止 selected_contractor_id；宏观保持冻结。\n默认运行预计在评标后的该入口失败。原生时点可能回滚，保存的 QS 工作结果不是正式评标完成回执。\n此包用于检视评标接线和定位兼容边界，不能宣称授标或全链成功。原 journal 和失败输出保留。',
            '已显式启用 --with-native-owner-selection：启动时按原 agent_module 接口组合原生 Owner.select_preferred_bid；该步骤不经过外部响应传输，也不读取微观选标结果。其他微观提案及所有外部最终决定仍使用原宏观校验器，无失败兜底。\nQS-A06 仍由原微观处理器执行；原生选标不计 OWN-A08 微观完成。只有实际运行产生的 bid_evaluation_completed 才证明评标正式完成，四时点窗口不代表签约或完整生命周期。')
    if with_evaluation_feedback:
        readme+='\n--with-evaluation-feedback：首项目期初已邀请两家承包商，各有 0.15 原生占用，明确属于合成初始假设，不生成期初邀请事件或计 OWN-A09。实际首轮投标在时点 1、评标在时点 3；第二项目从招标准备正常推进，在时点 3 由原 OWN-A09 邀请、时点 4 的原 A01 消费严格较早的本企业真实评标结果。独立偏好在一次评标后暂停新增投标；原提交次数阈值 999 不触发，不把评标等同于已签约、实际利润或资源释放。首项目后续条款谈判是显式原生路由，不计微观 A04/OWN-A10；原问题与资源由宏观原有规则保留。\n'
        readme=readme.replace('时点 1 原 OWN-A09 邀请、时点 2 原 A01/A02 投标、时点 4 原 QS-A06 评标。',
            '当前启用评标反馈窗口，业务时序和期初邀请假设见下方说明。')
    if with_qs_learning:
        readme+='\n--with-qs-learning：时点 4 的原生月度请求先执行原 QS-A12，记录本机构真实评标查询；月度经营决定仍为原生，不将中选或评分当作实际成本，不应用判断变更或培训。\n'
        readme+='--allow-qs-learning-saved-recovery / --query-saved-qs-learning-on-error 显式允许原月度调用查询已保存的 QS-A12，重核原请求、读取、版本及当前授权后补技术收尾；原微观动作不重跑。已保存的原生提案直接返回，原生调用已发起但没有保存响应时保持未知，不自动重试。\n'
    if exclude_contractor_id is not None:
        readme += ('\n--exclude-contractor-id '+exclude_contractor_id+
            ': initial synthetic known qualification failure and explicit buyer delegation are declared independently '
            'before sealing. Original QS-A06 comparison retains all original bid prices; a separate original QS-A06 '
            'checks the received delegation and returns exclude_authorized. The positive native score proposal and '
            'negative exclude_bid final decision remain distinct. The original macro filters the bid; absence from '
            'a bounded published ranking does not deliver a private exclusion receipt or release that bidder resources.\n')
    if exclude_all_bids:
        readme+='\n--exclude-all-bids explicitly declares both failed qualifications and buyer delegations before sealing. Each original native review gets its own context and original exclusions; actual native selection remains deferred. Later QS-A12 records the earlier real deferral. No bidder receipt, resource release, terminal refusal or cash is inferred.\n'
    _write_launch_files(directory, readme_override=readme)
    return {'status': 'synthetic_qs_bid_native_bundle_unverified', 'directory': str(directory), 'run_id': run_id}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--with-native-owner-selection', action='store_true')
    parser.add_argument('--exclude-contractor-id')
    parser.add_argument('--clarify-contractor-id',help='Declare missing bid qualification and publish the original QS question; evaluation remains unresolved')
    parser.add_argument('--exclude-all-bids',action='store_true',
        help='Independent known failed qualifications and buyer delegations for both original bids; selection stays deferred')
    parser.add_argument('--with-original-bid-history', action='store_true')
    parser.add_argument('--with-evaluation-feedback', action='store_true')
    parser.add_argument('--with-qs-learning', action='store_true')
    parser.add_argument('--allow-qs-learning-saved-recovery', action='store_true')
    parser.add_argument('--query-saved-qs-learning-on-error', action='store_true')
    args = parser.parse_args(argv)
    print(json.dumps(build_bundle(args.output, run_id=args.run_id,
        with_native_owner_selection=args.with_native_owner_selection,
        with_original_bid_history=args.with_original_bid_history,
        with_evaluation_feedback=args.with_evaluation_feedback, with_qs_learning=args.with_qs_learning,
        allow_qs_learning_saved_recovery=args.allow_qs_learning_saved_recovery,
        query_saved_qs_learning_on_error=args.query_saved_qs_learning_on_error,
        exclude_contractor_id=args.exclude_contractor_id,exclude_all_bids=args.exclude_all_bids,clarify_contractor_id=args.clarify_contractor_id), ensure_ascii=False))


if __name__ == '__main__':
    main()
