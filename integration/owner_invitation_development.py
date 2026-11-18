"""Author an explicit synthetic Owner OWN-A09 -> native invitation -> Contractor bundle."""
from copy import deepcopy
import argparse
import json
from pathlib import Path

from integration.contractor_tender_development import build_bundle as build_contractor, build_feedback_bundle as build_feedback_contractor, _write, _write_launch_files, ref, known
from src.coordination.tasks import task_digest


def build_bundle(directory, *, run_id, owner_id='dev-owner', qs_id='dev-qs',
        contractor_ids=('dev-contractor-a','dev-contractor-b'),clock_id='dev-clock',
        organization_capacity_totals=None,
        project_id='dev-tender-project',source_namespace='',authority_namespace='',organization_locations=None,
        allow_saved_recovery=False,query_saved_tender_on_error=False,additional_candidate_organizations=None,feedback_followup=False,
        followup_project_id='dev-followup-project',clock_tick_unit='explicit_synthetic_macro_month',query_prior_submissions=False,
        continue_unstarted_actions_on_error=False,with_clarification_request=False,with_clarification_response=False,
        continue_clarification=False,evaluation_feedback=False,
        initial_screening_policies=None, decline_after_prior_declines=None, decline_after_prior_final_accounts=None,
        decline_after_prior_payment_delays=None,
        allow_followup_bids=False):
    if evaluation_feedback and not feedback_followup:
        raise ValueError('Evaluated-bid feedback requires the explicit two-project feedback window')
    if type(allow_followup_bids) is not bool or allow_followup_bids and not feedback_followup:
        raise ValueError('Followup bids require explicit permission and the later feedback window')
    from integration.contractor_tender_development import _screening_policies
    _screening_policies(initial_screening_policies, contractor_ids)
    if decline_after_prior_declines is not None and (not feedback_followup
            or type(decline_after_prior_declines) is not int or decline_after_prior_declines < 1 or evaluation_feedback):
        raise ValueError('Decline feedback requires its explicit later window and positive limit, separate from evaluation feedback')
    if decline_after_prior_final_accounts is not None and (not feedback_followup
            or type(decline_after_prior_final_accounts) is not int or decline_after_prior_final_accounts < 1):
        raise ValueError('Final-account feedback requires its explicit later window and positive limit')
    if decline_after_prior_payment_delays is not None and (not feedback_followup
            or type(decline_after_prior_payment_delays) is not int or decline_after_prior_payment_delays < 1):
        raise ValueError('Payment-delay feedback requires its explicit later window and positive limit')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    child = directory / 'contractor'
    contractor_builder=build_feedback_contractor if feedback_followup else build_contractor
    contractor_builder(child, run_id=run_id,owner_id=owner_id,qs_id=qs_id,contractor_ids=contractor_ids,
        organization_capacity_totals=organization_capacity_totals,
        clock_id=clock_id,project_id=project_id,source_namespace=source_namespace,
        authority_namespace=authority_namespace,organization_locations=organization_locations,
        clock_tick_unit=clock_tick_unit,
        query_prior_submissions=query_prior_submissions,
        continue_unstarted_actions_on_error=continue_unstarted_actions_on_error,
        with_clarification_request=with_clarification_request,
        with_clarification_response=with_clarification_response,
        continue_clarification=continue_clarification,
        initial_screening_policies=initial_screening_policies,
        allow_saved_recovery=allow_saved_recovery,query_saved_tender_on_error=query_saved_tender_on_error,
        **({'followup_project_id':followup_project_id,'evaluation_feedback':evaluation_feedback,
            'decline_after_prior_declines':decline_after_prior_declines,
            'decline_after_prior_final_accounts':decline_after_prior_final_accounts,
            'decline_after_prior_payment_delays':decline_after_prior_payment_delays,
            'allow_followup_bids':allow_followup_bids} if feedback_followup else {}))

    def read(name):
        return json.loads((child / name).read_text(encoding='utf-8'))

    configuration_input = read('tender-configuration-input.json')
    authority = configuration_input['authority']['organization_snapshot']
    for organization in additional_candidate_organizations or ():
        if organization['organization_id'] in {row['organization_id'] for row in authority['organizations']}:
            raise ValueError('Additional invitation candidate repeats an original organization')
        authority['organizations'].append(deepcopy(organization))
    organizations = {row['organization_id']: row for row in authority['organizations']}
    owner = organizations[owner_id]
    grants = {row['organization_id']: row for row in authority['authorizations']}
    grant = grants[owner_id]
    def invitation_plan(contractor_plan, *, prefix, operation_id):
        tick=contractor_plan['screening_context']['business_time']['offset']-1
        scope = contractor_plan['screening_context']['scope']
        clock = contractor_plan['screening_context']['business_time']['clock_ref']
        now = {'clock_ref': clock, 'offset': tick}
        source_document = read('sources.json')
        existing = next(row for row in source_document['snapshots']
            if row['project_id']==scope['ref']['id'])['projection']['objects']
        shared_kinds = {'ClockProfile', 'Project', 'WorkScope'}
        shared_refs = [*owner['evidence_refs'], owner['assignments'][0]['function_ref'], grant['ref'], ref('Organization', owner_id)]
        objects = [deepcopy(row) for row in existing if row['ref']['kind'] in shared_kinds or row['ref'] in shared_refs]
        basis = owner['evidence_refs'][0]
        native = ref('Evidence', prefix + '-native-request')
        package = ref('ProcurementPackage', prefix + '-package')
        procedure = ref('ProcurementProcedure', prefix + '-procedure')
        profile = ref('TenderEvaluationProfile', prefix + '-profile')
        round_ref = ref('TenderRound', prefix + '-round')
        funding = ref('FundingPosition', prefix + '-funding')
        submission = ref('TimeWindow', prefix + '-window')
        candidate_set = ref('CandidateSet', prefix + '-candidates')
        bidders = [(organization, ref('EligibleBidder', prefix + '-' + organization))
            for organization in (*contractor_ids,*[row['organization_id'] for row in additional_candidate_organizations or ()])]
        window = grant['validity']
        common = {'scope': scope, 'available_at': now, 'effective_window': window, 'evidence_refs': [basis]}

        def put(reference, value):
            objects.append({'ref': reference, 'value': value})

        put(native, {'ref': native, 'source_kind': 'synthetic', 'basis_kind': 'observed',
            'locator': 'native-owner-invitation:current-request', 'content_hash': None, 'effective_window': window})
        put(package, {**common, 'ref': package, 'owner_organization_id': owner_id, 'owner_actor_id': owner['actor_id'],
            'authority_ref': grant['ref'], 'procedure_ref': procedure, 'evaluation_profile_ref': profile,
            'requirement_refs': [], 'round_refs': [round_ref], 'bidder_refs': [r for _, r in bidders], 'status': 'published'})
        put(procedure, {**common, 'ref': procedure, 'owner_organization_id': owner_id, 'authority_ref': grant['ref'],
            'required_technical_submission_refs': [], 'requirement_refs': [], 'quantity_required': False, 'quantity_basis_ref': None,
            'evaluation_profile_ref': profile, 'submission_window_ref': submission, 'publication_permission': known(True),
            'publication_mode': 'invitation', 'minimum_authorized_budget': known({'value': '0', 'currency': 'HKD', 'basis_ref': basis})})
        put(profile, {**common, 'ref': profile, 'owner_organization_id': owner_id, 'author_actor_id': owner['actor_id'],
            'author_function_ref': owner['assignments'][0]['function_ref'], 'author_authority_ref': grant['ref'],
            'package_ref': package, 'procedure_ref': procedure, 'choice_order': ['invite'], 'criteria': [],
            'invitation_bidder_refs': [r for organization, r in bidders if organization in contractor_ids], 'selected_round_ref': None, 'clarification_ref': None,
            'negotiation_bid_ref': None, 'negotiation_questions': [], 'transition_ref': None,
            'tie_policy': 'retain_equal_groups_require_explicit_award_choice'})
        put(round_ref, {**common, 'ref': round_ref, 'package_ref': package, 'owner_organization_id': owner_id,
            'evaluation_profile_ref': profile, 'bid_refs': [], 'status': 'open', 'accepts_new_bids': True,
            'accepts_awards': False, 'pending_selection_refs': [], 'reservation_refs': [], 'established_contract_refs': []})
        put(funding, {**common, 'ref': funding, 'owner_organization_id': owner_id, 'authority_ref': grant['ref'],
            'as_of': now, 'authorized_limit': known({'value': '1000', 'currency': 'HKD', 'basis_ref': basis}),
            'kind': 'authorized_procurement_budget', 'coverage': 'complete', 'prior_commitments': []})
        put(submission, {'start': {'clock_ref': clock, 'offset': 0}, 'end': {'clock_ref': clock, 'offset': 5}, 'bounds': 'closed_open'})
        for organization_id, reference in bidders:
            organization = organizations[organization_id]
            # This identifies the registered actor only. An unselected candidate
            # gets no invitation permission or inferred professional eligibility.
            assignment = next(row for row in organization['assignments'] if row['role']=='Contractor')
            put(reference, {**common, 'ref': reference, 'organization_id': organization_id, 'actor_id': organization['actor_id'],
                'function_ref': assignment['function_ref'], 'invitation_permission': known(organization_id in contractor_ids),
                'eligibility': known(True) if organization_id in contractor_ids else {
                    'state':'unknown','reason_code':'independent_qualification_not_supplied','missing_refs':[]},
                'eligibility_rule_refs': [], 'status': 'active'})
        put(candidate_set, {'operation_id': operation_id, 'scope': scope, 'as_of': now,
            'candidates': [{'ref': package, 'permitted_choices': ['invite']}],
            'search_profile_ref': ref('Profile', prefix + '-explicit-exposure')})
        refs = [row['ref'] for row in objects]
        context = {'run_id': run_id, 'actor_id': owner['actor_id'], 'function_ref': owner['assignments'][0]['function_ref'],
            'authorization_refs': [grant['ref']], 'operation_id': operation_id,
            'contract_ref': ref('ActionContract', 'OWN-A09'), 'task_ref': ref('DecisionTask', operation_id), 'scope': scope,
            'business_time': now, 'read_token': operation_id + '-read', 'visible_refs': refs,
            'candidate_set_ref': candidate_set, 'execution_mode': 'rule'}
        plan = {'organization_id': owner_id, 'project_id': scope['ref']['id'], 'tick': tick, 'context': context,
            'action_input': {'package_context': {'kind': 'published', 'package_ref': package}, 'round_refs': [round_ref],
                'bidder_refs': [r for _, r in bidders], 'bid_refs': [], 'evaluation_profile_ref': profile, 'funding_ref': funding},
            'objects': objects, 'native_evidence_ref': native,
            'utility': {'value': '0.5', 'unit': 'score', 'basis_ref': basis},
            'probability': {'value': '1', 'unit': 'probability', 'basis_ref': basis}}
        return plan

    by_project={}
    for request_plan in configuration_input['request_work_settings']['requests']:
        by_project.setdefault(request_plan['screening_context']['scope']['ref']['id'],request_plan)
    plans=[invitation_plan(plan,prefix='dev-owner-invitation' if name==project_id else name+'-owner-invitation',
        operation_id='dev-owner-native-invitation' if name==project_id else name+'-owner-native-invitation')
        for name,plan in by_project.items()]
    grant['readable_refs']=list({task_digest(reference):reference for reference in [
        *grant['readable_refs'],*[row['ref'] for plan in plans for row in plan['objects']]]}.values())
    for plan in plans:
        for row in plan['objects']:
            if row['ref']==grant['ref']:row['value']=deepcopy(grant)
    # Validate every professional projection now; the native evidence hash stays
    # unbound until the actual proposal arrives.
    from integration.owner_invitation_native import OwnerInvitationPlan
    from src.actions.contracts.owner_tender_objects import owner_tender_schemas
    from src.actions.contracts.common import Reference

    plans=[OwnerInvitationPlan.model_validate(plan).model_dump(mode='json') for plan in plans]
    for plan in plans:
        for row in plan['objects']:
            value=deepcopy(row['value'])
            if row['ref']==plan['native_evidence_ref']:value['content_hash']='0'*64
            owner_tender_schemas().validate_projection(Reference.model_validate(row['ref']),value)
    owner_file = _write(directory, 'owner-invitation-input.json', {
        'schema_version': 'owner-invitation-input.v1', 'run_id': run_id, 'plans': plans})
    for name, field in [('sources.json', 'snapshots'), ('quantity-sources.json', 'quantity_snapshots')]:
        document = read(name)
        for snapshot in document['snapshots']:
            for row in snapshot['projection']['objects']:
                if row['ref'] == grant['ref']:
                    row['value'] = deepcopy(grant)
        file = _write(directory, name, document)
        configuration_input[field].update(snapshot_path=file['file_path'], snapshot_sha256=file['file_sha256'])
    from integration.contractor_tender_configuration import build_configuration
    from integration.module_host import GbaModuleHostConfiguration

    for plan in configuration_input['request_work_settings']['requests']:
        if plan.get('clarification_response') is not None:
            for row in plan['clarification_response']['objects']:
                if row['ref'] == grant['ref']:
                    row['value'] = deepcopy(grant)
    configuration = build_configuration(configuration_input).model_dump(mode='json')
    sources = configuration['settings']['source_settings']
    sources['application_settings'] = {'contractor': sources['application_settings'],
        'owner_invitation': {'version': '1', **owner_file}, 'policy_version': configuration_input['policy_version']}
    sources['application_factory'] = 'integration.owner_invitation_native:build_application'
    _write(directory, 'tender-configuration-input.json', configuration_input)
    _write(directory, 'tender-host.json', GbaModuleHostConfiguration.model_validate(configuration).model_dump(mode='json'))
    native = read('native-host.json')
    native['settings']['native_proposals'] = [route for route in native['settings']['native_proposals']
        if (route['role'], route['operation']) != ('Owner', 'select_tender_invitees')]
    native['settings']['native_decisions'] = [route for route in native['settings']['native_decisions']
        if (route['role'], route['decision_type']) != ('Owner', 'owner_tender_shortlist')]
    _write(directory, 'native-host.json', native)
    _write(directory, 'macro-request.json', read('macro-request.json'))
    _write(directory, 'assembly-host.json', {'schema_version': 'gba-module-host-config.v1', 'host_id': run_id,
        'version': '1', 'settings': {'tender_configuration_path': str(directory / 'tender-host.json')}})
    _write(directory, 'owner-source-note.json', {'source_mode': 'synthetic_assumption',
        'note': 'Initial micro package, open round, candidate qualifications and budget are explicitly assumed inputs; '
                'they do not assert an earlier native publication receipt. Actual invitations come only from the native lifecycle.',
        'micro_routes': ['Owner.select_tender_invitees', 'Owner.owner_tender_shortlist',
            'Contractor.consider_tender', 'Contractor.tender_decision'],
        'native_routes': 'Explicit monthly enterprise operations remain native and do not count as micro coverage.'})
    readme="""# 合成业主邀请与承包商投标开发输入

运行 `& './run.ps1'`；已有输出时使用 `-OutputDirectory '<新的绝对目录>'`，原任务库保留。
需要项目 `.venv-integration`（Python 3.12+、已声明依赖），从同步命令行启动。

同一项目、业主/QS/两个承包商。原生时点 1 请求业主选择邀请对象：原 OWN-A09 处理器和结果工作器
读取独立授权资料，形成邀请名单；原 propose/decide 消费同一结果，由宏观创建实际邀请与占用。
时点 2 承包商沿用原 A01/A02、容量和量价流程投标。微观失败不会切换规则答案。
月度操作显式由原宏观处理，不计入微观覆盖；未接后续评标、授标和履约。

初始微观包件、开放轮次、资质、预算、日历、量价和指标均是 synthetic/assumed 场景输入；
不是较早宏观正式发布回执。原生请求到来时仅填实际请求证据哈希，不填成功结果或资格。
业主邀请名单只取原生实际候选，受原生数量限制；不编造候选分数。正式邀请由宏观执行。
配置复用同一初始组织授权、原动作登记器、任务库和宿主写锁，无额外正式账本。

`owner-source-note.json` 说明接管范围；`contractor` 子目录保留输入编制来源。
实际启动使用根目录合并配置。`input-manifest.json` 固定全部输入字节，修改输入应生成新包。
此生成器只检查 schema/配置，不证明业务成功；须核对 `runtime/result.json` 原生事件与保存的微观结果。
"""
    if evaluation_feedback:
        readme+='\n评标反馈窗口共四个原生时点：首项目的邀请和 0.15 占用是显式期初假设，不计本次 OWN-A09；首轮投标在时点 1，评标在时点 3。后续项目在时点 3 经原 OWN-A09 邀请，时点 4 消费较早的本企业实际评标结果。期初来源见 contractor/initial-invitation-source.json。\n'
    elif feedback_followup:
        readme+='\n本包启用两个错峰项目，共三个原生时点；后续项目在时点 2 经原 OWN-A09 邀请，时点 3 由原 A01/A02 消费较早本企业投标反馈。两项目来源、读取令牌和业务范围分别声明，不预写投标结果。\n'
    if query_prior_submissions:
        readme+='\n后轮 A01 前显式查询本企业较早原请求的实际执行，补上通知未送达时的私有反馈来源。查不到结果就保留未决；不重投、不伪造收件箱通知。\n'
    readme+='\n--initial-screening-policies <JSON> 在首次封装前声明首项目各承包商原 A01 策略（participate_if_eligible/decline_new_work）。主动拒投另有独立 A02 商业拒绝来源。--decline-after-prior-declines N 需 --feedback-followup，后轮恢复默认参与基准，仅按实际较早本企业拒投次数生成新的私有筛选策略，不把提交、澄清或失败算作拒投。A01 参与意向也不强制 A02 报价；独立商业拒绝仍由原 A02 形成。\n'
    _write_launch_files(directory,readme_override=readme)
    return {'status': 'synthetic_owner_invitation_bundle_unverified', 'directory': str(directory), 'run_id': run_id}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--feedback-followup',action='store_true')
    parser.add_argument('--allow-saved-recovery',action='store_true')
    parser.add_argument('--query-saved-tender-on-error',action='store_true')
    parser.add_argument('--query-prior-submissions',action='store_true')
    parser.add_argument('--continue-unstarted-actions-on-error',action='store_true')
    parser.add_argument('--with-clarification-request',action='store_true')
    parser.add_argument('--with-clarification-response',action='store_true')
    parser.add_argument('--continue-clarification',action='store_true')
    parser.add_argument('--initial-screening-policies',type=Path)
    parser.add_argument('--decline-after-prior-declines',type=int)
    parser.add_argument('--decline-after-prior-final-accounts',type=int)
    parser.add_argument('--decline-after-prior-payment-delays',type=int)
    parser.add_argument('--allow-followup-bids',action='store_true')
    args = parser.parse_args(argv)
    if args.query_prior_submissions and not args.feedback_followup:
        parser.error('--query-prior-submissions requires --feedback-followup')
    print(json.dumps(build_bundle(args.output, run_id=args.run_id,feedback_followup=args.feedback_followup,
        allow_saved_recovery=args.allow_saved_recovery,query_saved_tender_on_error=args.query_saved_tender_on_error,
        query_prior_submissions=args.query_prior_submissions,
        continue_unstarted_actions_on_error=args.continue_unstarted_actions_on_error,
        with_clarification_request=args.with_clarification_request,
        with_clarification_response=args.with_clarification_response,
        continue_clarification=args.continue_clarification,
        initial_screening_policies=json.loads(args.initial_screening_policies.read_text(encoding='utf-8-sig'))
            if args.initial_screening_policies is not None else None,
        decline_after_prior_declines=args.decline_after_prior_declines,
        decline_after_prior_final_accounts=args.decline_after_prior_final_accounts,
        decline_after_prior_payment_delays=args.decline_after_prior_payment_delays,
        allow_followup_bids=args.allow_followup_bids), ensure_ascii=False))


if __name__ == '__main__':
    main()
