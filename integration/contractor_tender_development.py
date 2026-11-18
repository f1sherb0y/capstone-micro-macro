"""Author a single-project synthetic tender input bundle for the original host.

All competence, future calendars, work quantities, prices and productivity below
are explicit development assumptions. Native invitation/resource provenance is
bound only when the real request arrives. No bid, result or receipt is supplied.
"""
from copy import deepcopy
import argparse
import hashlib
import json
import math
from pathlib import Path

from integration.bootstrap import enable_gba_imports
from src.actions.contracts.common import Reference
from src.coordination.tasks import task_digest


NOTE = ('Synthetic development input only: one normalized work item; normalized enterprise capacity is '
    'not physical labour or equipment. Competence, QS documents, prices, productivity, future occupancy '
    'and proposal indicators are assumed. Only native source digests and actual action results are observed at runtime.')


def ref(kind, name, version='1'):
    return {'kind': kind, 'id': name, 'version': version}


def known(value):
    return {'state': 'known', 'value': value}


def _screening_policies(values, contractor_ids):
    if values is None:
        return {}
    if (not isinstance(values, dict) or set(values) - set(contractor_ids)
            or any(value not in ('participate_if_eligible', 'decline_new_work') for value in values.values())):
        raise ValueError('Initial screening policies require known Contractor organizations and original A01 policies')
    return deepcopy(values)


def _write(directory, name, value):
    path = directory / name
    data = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    with path.open('xb') as stream:
        stream.write(data)
    return {'file_path': str(path.resolve()), 'file_sha256': hashlib.sha256(data).hexdigest()}


def _write_launch_files(directory, *, feedback_followup=False, readme_override=None,
        assembly_hook='integration.contractor_tender_development:configure_assembly', allow_native_project_generation=False,
        source_note=None, allow_native_initial_projects_with_generation=False,
        agent_client_factory='integration.native_routes:build_agent_client', offline=True):
    if allow_native_initial_projects_with_generation and not allow_native_project_generation:
        raise ValueError('Mixed native launch requires its explicit native generation flag')
    workspace = str(Path(__file__).resolve().parents[1]).replace("'", "''")
    script = """param([string]$OutputDirectory = (Join-Path $PSScriptRoot 'runtime'))
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $OutputDirectory) {
    throw 'Choose a new output directory; existing journals must be preserved.'
}
Push-Location -LiteralPath '__WORKSPACE__'
try {
    & '.venv-integration/Scripts/python.exe' -m integration.contractor_tender_development --verify $PSScriptRoot
    if ($LASTEXITCODE -ne 0) { throw 'Input bundle changed; generate a new independent bundle.' }
    & '.venv-integration/Scripts/python.exe' -m integration.run `
        --input (Join-Path $PSScriptRoot 'macro-request.json') --output $OutputDirectory `
        --offline --input-format gba_request --macro-mode gba_v1_module `
        --agent-client-factory integration.native_routes:build_agent_client `
        --agent-client-config (Join-Path $PSScriptRoot 'native-host.json') `
        --module-assembly-hook integration.contractor_tender_development:configure_assembly `
        --module-assembly-config (Join-Path $PSScriptRoot 'assembly-host.json')
    if ($LASTEXITCODE -ne 0) { throw 'Integration run failed; inspect the original error and journal.' }
} finally { Pop-Location }
""".replace('__WORKSPACE__', workspace).replace(
        'integration.contractor_tender_development:configure_assembly', assembly_hook).replace(
        'integration.native_routes:build_agent_client', agent_client_factory).replace(
        '--offline --input-format', ('--offline' if offline else '--llm') + ' --input-format')
    if allow_native_project_generation:
        script = script.replace('--macro-mode gba_v1_module', '--macro-mode gba_v1_module --allow-native-project-generation')
    if allow_native_initial_projects_with_generation:
        script = script.replace('--allow-native-project-generation',
            '--allow-native-project-generation --allow-native-initial-projects-with-generation')
    if not offline:
        # PowerShell 5 wraps native stderr as ErrorRecord. Preserve its complete
        # diagnostics, then use the actual exit code to reject a failed run.
        script = script.replace("    & '.venv-integration/Scripts/python.exe'",
            "    $ErrorActionPreference = 'Continue'\n    & '.venv-integration/Scripts/python.exe'")
        script = script.replace('    if ($LASTEXITCODE -ne 0)',
            "    $tenderNativeExitCode = $LASTEXITCODE\n    $ErrorActionPreference = 'Stop'\n    if ($tenderNativeExitCode -ne 0)")
    readme = """# 合成投标开发输入

运行 `& './run.ps1'`；已有输出时，使用 `& './run.ps1' -OutputDirectory '<新的绝对目录>'`。
需要项目的 `.venv-integration`（Python 3.12+、已声明依赖），从同步命令行启动。

同一项目、1 个业主、1 个 QS、2 个承包商；原生时点 1 邀请、时点 2 收标。
微观接管 Contractor.consider_tender 和 tender_decision，执行原 A01/A02、容量及报价方法、同请求交接与指标校验。
Owner 的邀请及三个角色的月度操作显式委派宏观原行为/规则决定，不计入微观覆盖。
不调用模型；微观失败保留失败状态，不切换为规则答案。此包只运行投标窗口，后续评标、授标和履约尚须接入。

所有资质、工程量、价格、生产率、未来占用及指标都是显式 synthetic/assumed 输入。
企业规范化容量不是实际人力或设备；未来占用区间属于场景假设。
文件中原生运行标识、邀请和资源哈希留空，真实请求到达后仅绑定实际原生来源。
报价须由 A02 实算；输入未包含投标结果、宏观回执或成功承诺。
正式投标和反馈由原宏观执行、发布；同组织私有来源按明确授权读取。

生成包只做 schema/配置检查。运行成功须检查 `result.json` 中实际投标、最终决定及反馈日志，不能只看进程退出码。
原始输入由 `input-manifest.json` 固定；修改输入请重新生成独立包，不改写旧运行记录。

生成时可加 `--allow-saved-recovery --query-saved-tender-on-error`：原生请求仍在等待，且原 A01/A02 都已有持久化完成结果时，
只查询原结果、核对来源/权限/执行版本和审计，补全技术任务并还原原提案。两项默认关闭；缺结果保持未决，不重跑处理器或模型。
实际宿主的 `query_submission(original_request)` 核对原传输任务和本企业实际收标/拒绝事件；尚无事件时返回未知，不重新提交或推进引擎。
`--feedback-followup --query-prior-submissions` 可在后轮读取反馈前查询本企业较早原请求的实际执行结果，默认关闭。
即使收标通知未送达，也只将原引擎已经发生并与原提案/最终决定一致的事件作为私有反馈来源；不补造通知，不重新投标。
较早请求仍查不到实际结果时保持未决，停止本次反馈处理，不据此假定此前没有投标或产生商业拒绝。
`--continue-unstarted-actions-on-error` 独立启用同次原生调用内的未开始动作续办，默认关闭。
只有原任务/快照及持久化标记共同证明尚未进入决策准备时，才保留原输入并重查权限/来源后执行一次；
前序动作、来源生产和正式请求不会重跑。准备已开始、结果未知、等待或失败状态仍保持未决；不恢复引擎或跨进程续办。
`--initial-screening-policies <JSON>` 声明首项目各承包商原 A01 策略，只允许 participate_if_eligible / decline_new_work。
主动不参与也需要独立原 A02 商业拒绝来源，不把缺资料、澄清或失败当成拒投。
`--feedback-followup --decline-after-prior-declines N` 让后轮恢复参与基准，并按严格较早的本企业实际拒投次数派生新私有策略；
此模式不以提交次数代替拒投。原 A01 参与意向仍允许原 A02 根据独立商业策略拒绝报价。
`--with-clarification-request` 显式提供一个尚未解决的包件要求，并授权原 A01 通过现有原生澄清会话向当前 QS 发送具体问题。
发送前保存原任务/结果及会话关联；未知发送只允许查询实际消息，不重发。该场景会保留原澄清未决，不能按成功投标验收。
`application.query_clarification_request(original_request)` 只查询本企业原问题；开启会话的通知和发出问题都不代表收到答复或修改包件。
`--with-clarification-response` 同时启用原问题和独立 QS 来源计划，在实际问题发送后执行原 QS-A05 发布权限判断，
仅将已获授权的原采购数量及计量规则通过原生会话答复给提问企业。初始数量、文件及发布授权均为明确合成来源。
`application.query_clarification_response(original_request)` 核对原 QS 结果与实际答复消息，不重跑 QS 或重发消息。
专业答复仍不等于已修订包件或后续 A01 接受；本场景保留原澄清未决，无发布权限时不发送答复。
`--continue-clarification` 同时开启上述问答，在实际授权答复后为同一包件发布独立微观新版本并执行新的原 A01。
仅处理已声明的数量/计量问题，不改变原范围、资源、价格或截止时间，不改写原 `clarify` 结果。
后继 A01 的真实决定才进入原 A02 流水线，再由宏观决定正式投标/拒标；原答复未确认或无权限时停止。
该选项支持同次原生调用内的正常续办。另加 `--allow-saved-recovery --query-saved-tender-on-error`，
在原 A01、实际 QS 答复、后继 A01 均已完成且原 A02 结果已持久化时，可核验原链并恢复技术收尾。
缺少任一必要结果或实际答复时保持未决，不执行缺失阶段；跨进程重启仍需另行实现。
"""
    if feedback_followup:
        readme += """

## 同企业后续反馈消费场景

此包运行两个错峰项目，共 3 个原生时点：首项目在时点 2 收标；后续项目初始已完成一个招标准备时点，
由原宏观流程在时点 2 邀请、时点 3 请求投标。后续组织策略显式规定：已有一次本企业实际提交时不再承接新投标。
策略读取原宏观实际反馈，原 A01 作出判断，原 A02 使用独立声明的拒绝策略返回合法拒绝。
拒绝指标中的 100 HKD 是明确假设的协议参考金额，不是新报价。工程量和成本仍经原生产器生成。
两个项目共享企业授权及私有反馈，专业输入和读取令牌按项目分开。初始准备质量和资源日历均为假设。
窗口止于后续投标请求，不到达首项目时点 4 的评标和业主选择。C2 接入仍需单独完成。
first 和 followup 子目录保留输入编制来源；实际启动使用根目录合并配置。
"""
    if readme_override is not None:
        readme = readme_override
    for name, content in [('run.ps1', script), ('README.md', readme)]:
        with (directory / name).open('xb') as stream:
            stream.write(content.encode('utf-8'))
    if source_note is not None and (not isinstance(source_note,str) or not source_note.strip()):
        raise ValueError('Development source note must explicitly describe the supplied business assumptions')
    _write(directory, 'input-manifest.json', {'schema_version': 'contractor-tender-development-input.v1' if source_note is None else 'integration-development-input.v1',
        'source_note': NOTE if source_note is None else source_note, 'files': {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.rglob('*')) if path.is_file()}})


def build_bundle(directory, *, run_id, project_id='dev-tender-project', tender_tick=2,
        source_namespace='', feedback_followup=False,allow_saved_recovery=False,query_saved_tender_on_error=False,
        owner_id='dev-owner', qs_id='dev-qs', contractor_ids=('dev-contractor-a','dev-contractor-b'),
        organization_capacity_totals=None,
        clock_id='dev-clock', authority_namespace='', organization_locations=None,
        clock_tick_unit='explicit_synthetic_macro_month',query_prior_submissions=False,
        continue_unstarted_actions_on_error=False,with_clarification_request=False,
        with_clarification_response=False,clarification_publication_permitted=True,continue_clarification=False,
        observe_current_occupancy=False, initial_screening_policies=None, model_options=None,
        allow_followup_bids=False):
    """Write explicit inputs; does not build an engine, run actions or call models."""
    model_config = None
    if model_options is not None:
        from integration.tender_model_development import TenderModelDevelopmentSettings
        model_config = TenderModelDevelopmentSettings.model_validate(model_options).model_copy(deep=True)
    if continue_clarification:
        with_clarification_response = True
    if with_clarification_response:
        with_clarification_request = True
    if query_saved_tender_on_error and not allow_saved_recovery:
        raise ValueError('Tender query on error requires explicit saved-result recovery authorization')
    if query_prior_submissions and not feedback_followup:
        raise ValueError('Prior tender query requires the explicit later feedback policy')
    if type(allow_followup_bids) is not bool or allow_followup_bids and not feedback_followup:
        raise ValueError('Followup bids require an explicit boolean and the later feedback window')
    observe_current_occupancy = observe_current_occupancy or allow_followup_bids
    if (not 2 <= len(contractor_ids) <= 24 or len({owner_id,qs_id,*contractor_ids})!=len(contractor_ids)+2
            or any(not isinstance(value,str) or not value for value in (owner_id,qs_id,*contractor_ids,clock_id))):
        raise ValueError('Tender inputs require one Owner, one QS and 2 to 24 distinct explicit Contractors and a clock')
    if organization_capacity_totals is not None and (
            not isinstance(organization_capacity_totals, dict)
            or set(organization_capacity_totals) - set(contractor_ids)
            or any(type(value) not in {int, float} or not math.isfinite(value) or value <= 0
                for value in organization_capacity_totals.values())):
        raise ValueError('Initial tender capacity totals must name its original Contractors with finite positive native values')
    organization_capacity_totals = deepcopy(organization_capacity_totals or {})
    policies = _screening_policies(initial_screening_policies, contractor_ids)
    enable_gba_imports()
    from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
    from integration.contractor_tender_configuration import build_configuration
    from integration.contractor_bid_quantities import ContractorQuantityMappingView
    from integration.contractor_bid_costs import ContractorBidCostAdoptionView
    from integration.bindings.gba_v1_contractor_screening import gba_contractor_screening_source_schemas
    from integration.bindings.gba_v1_tender_package import GbaTenderPackageTermsView
    from integration.bindings.gba_v1_bid_capacity import gba_bid_capacity_source_schemas
    from integration.contractor_bid_quantities import contractor_quantity_source_schemas
    from integration.contractor_tender_quantity_validation import ObservedTenderQuantityRelation
    from integration.contractor_tender_cost_validation import ObservedTenderCostAdoption
    from src.actions.contracts.contractor_bid_objects import ContractorBidPackageView, ContractorBidQuantityView
    from src.actions.contracts.qs_procurement_objects import (
        QSProcurementDocumentView, QSProcurementQuantityView, QSProcurementDesignView, QSMeasurementRuleView,
    )
    from src.actions.contracts.qs_cost_objects import QSCostPriceView

    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    roles = {owner_id: 'Owner', qs_id: 'QS', **{org: 'Contractor' for org in contractor_ids}}
    native_roles = dict(roles)
    design_author = qs_id + '-design-source'
    if with_clarification_response:
        # Independent initial professional source; this is not a native
        # Architect invocation or a claimed runtime design release.
        if design_author in roles:
            raise ValueError('Synthetic design source must have an independent organization identity')
        roles[design_author] = 'Architect'
    region, unit = 'Hong Kong', 'normalized_enterprise_capacity'
    clock = ref('ClockProfile', clock_id)
    scope = {'kind': 'project', 'ref': ref('Project', project_id), 'coverage_refs': [ref('WorkScope', source_namespace + 'dev-work')]}

    def point(offset):
        return {'clock_ref': clock, 'offset': offset}

    def window(start=0, end=100, bounds='closed_open'):
        return {'start': point(start), 'end': point(end), 'bounds': bounds}

    # The original lifecycle uses tick 1 for invitations and only requests
    # contractor bids on tick 2. Micro time follows that actual request.
    now, work_window = point(tender_tick), window(10, 20)
    basis = {name: ref('Evidence', authority_namespace + name + '-assumptions') for name in roles}
    function = {name: ref('FunctionAssignment', authority_namespace + name + '-function') for name in roles}
    grant = {name: ref('Authorization', authority_namespace + name + '-grant') for name in roles}
    actions = {'Owner': ['OWN-A09'], 'QS': ['QS-A04', 'QS-A05'], 'Contractor': ['CONTRACTOR-A01', 'CONTRACTOR-A02'],
        'Architect': ['ARCHITECT-A04']}
    organizations = [{'organization_id': name, 'actor_id': name, 'source_ids': ['synthetic:' + name],
        'public_description': NOTE, 'public_location': {'state': 'unknown', 'reason_code': 'synthetic', 'missing_refs': []},
        'members': [], 'evidence_refs': [basis[name]], 'assignments': [{'role': role, 'function_ref': function[name],
            'configuration_version': '1', 'basis_refs': [basis[name]]}]} for name, role in roles.items()]
    for organization in organizations:
        if organization_locations is not None and organization['organization_id'] in organization_locations:
            organization['public_location'] = deepcopy(organization_locations[organization['organization_id']])
    authorizations = {name: {'ref': grant[name], 'organization_id': name, 'actor_id': name, 'function_ref': function[name],
        'action_ids': actions[role], 'scopes': [scope], 'readable_refs': [], 'tool_ids': [],
        'basis_refs': [basis[name]], 'validity': window()} for name, role in roles.items()}

    def authored(name, action_id):
        return {'scope': scope, 'available_at': now, 'effective_window': window(), 'evidence_refs': [basis[name]],
            'author_actor_id': name, 'author_organization_id': name, 'author_function_ref': function[name],
            'author_authority_ref': grant[name], 'author_action_id': action_id, 'authored_at': now}

    def common(evidence):
        return {'scope': scope, 'available_at': now, 'effective_window': window(), 'evidence_refs': [evidence]}

    shared = []
    for name in (owner_id, qs_id, *([design_author] if with_clarification_response else [])):
        shared.extend([{'ref': basis[name], 'value': {'ref': basis[name], 'source_kind': 'synthetic', 'basis_kind': 'assumed',
            'locator': 'development:' + name, 'content_hash': task_digest([NOTE, name]), 'effective_window': window()}},
            {'ref': function[name], 'value': organizations[list(roles).index(name)]['assignments'][0]},
            {'ref': grant[name], 'value': authorizations[name]},
            {'ref': ref('Organization', name), 'value': {'ref': ref('Organization', name), 'evidence_refs': [basis[name]]}}])
    shared.extend([{'ref': clock, 'value': {'ref': clock, 'tick_unit': clock_tick_unit, 'evidence_refs': [basis[owner_id]]}},
        {'ref': scope['ref'], 'value': {'ref': scope['ref'], 'evidence_refs': [basis[owner_id]]}},
        {'ref': scope['coverage_refs'][0], 'value': {'ref': scope['coverage_refs'][0], 'parent_ref': scope['ref'], 'evidence_refs': [basis[owner_id]]}}])
    snapshots, quantity_snapshots, plans, native_sources, handoffs = [], [], [], {}, {}
    quantity_relations, cost_adoptions, indicator_documents = [], [], {}

    for organization_id in contractor_ids:
        prefix = organization_id + '-' + source_namespace

        def r(kind, name):
            return ref(kind, prefix + name)

        package, qualification = r('ProcurementPackage', 'package'), r('Qualification', 'qualification')
        invitation = r('Invitation', 'native-invitation')
        if continue_clarification:
            package['version'] = invitation['version'] = '2'
        method, quantity, cost = r('WorkMethod', 'method'), r('QuantityBasis', 'quantity'), r('CostBasis', 'cost')
        pool, resource = r('ResourcePool', 'capacity'), r('Resource', 'capacity')
        calendar, native_resource, native_tender = r('Evidence', 'calendar'), r('Evidence', 'native-resource'), r('Evidence', 'native-tender')
        relation_evidence, adoption_evidence = r('Evidence', 'quantity-relation'), r('Evidence', 'cost-adoption')
        package_terms, screening_facts, bid_facts = r('GbaTenderPackageTerms', 'terms'), r('GbaScreeningEnterpriseFacts', 'facts'), r('GbaBidEnterpriseFacts', 'facts')
        if continue_clarification:
            package_terms['version'] = '2'
        mapping_a01, mapping_a02 = r('GbaCapacityMapping', 'screening'), r('GbaCapacityMapping', 'bid')
        capability, commitments = r('ContractorCapability', 'capability'), r('CommitmentSnapshot', 'commitments')
        profile, pricing, capacity = r('OpportunityScreeningProfile', 'policy'), r('ContractorPricingProfile', 'pricing'), r('ContractorCapacity', 'capacity')
        decline_pricing = r('ContractorPricingProfile', 'nonparticipation-pricing') if allow_followup_bids else pricing
        feedback_profile, feedback_evidence = r('OpportunityScreeningProfile', 'feedback-policy'), r('Evidence', 'prior-native-submissions')
        work_slot, validity, submission = r('TimeWindow', 'work'), r('TimeWindow', 'validity'), r('TimeWindow', 'submission')
        round_ref, rule, terms = r('TenderRound', 'round'), r('MeasurementRule', 'measurement'), r('ContractTerms', 'terms')
        programme, released, design = r('ProgrammeProposal', 'programme'), r('ReleasedDeliverable', 'design'), r('Deliverable', 'design')
        qs_schedule, qs_document = r('QuantitySchedule', 'schedule'), r('ProcurementDocument', 'document')
        qs_scope, qs_round = r('ProcurementScope', 'scope'), r('ProcurementRound', 'round')
        quantity_mapping, cost_adoption = r('ContractorQuantityMapping', 'relation'), r('ContractorCostAdoption', 'adoption')
        handoff_ref, proposal_mapping = r('ContractorProcurementHandoffBasis', 'handoff'), r('GbaTenderProposalMapping', 'proposal')
        handoff_native, handoff_result = r('Evidence', 'handoff-native'), r('Evidence', 'handoff-result')
        indicator_input, indicator_result = r('Evidence', 'indicator-input'), r('Evidence', 'indicator-result')
        own_common = common(basis[organization_id])
        objects_common = deepcopy(shared)
        objects_common.extend([{'ref': function[organization_id], 'value': organizations[list(roles).index(organization_id)]['assignments'][0]},
            {'ref': grant[organization_id], 'value': authorizations[organization_id]},
            {'ref': ref('Organization', organization_id), 'value': {'ref': ref('Organization', organization_id), 'evidence_refs': [basis[organization_id]]}}])
        for evidence_ref in (basis[organization_id], calendar):
            objects_common.append({'ref': evidence_ref, 'value': {'ref': evidence_ref, 'source_kind': 'synthetic', 'basis_kind': 'assumed',
                'locator': 'development:' + evidence_ref['id'], 'content_hash': task_digest([NOTE, evidence_ref]), 'effective_window': window()}})
        for evidence_ref in (native_resource, native_tender):
            objects_common.append({'ref': evidence_ref, 'value': {'ref': evidence_ref, 'source_kind': 'synthetic', 'basis_kind': 'observed',
                'locator': 'native-source:' + evidence_ref['id'], 'content_hash': None, 'effective_window': window()}})
        qualification_value = {'ref': qualification, 'organization_ref': ref('Organization', organization_id),
            'evidence_refs': [basis[organization_id]], 'qualification_code': 'synthetic-general-work', 'region_ids': [region],
            'work_types': ['synthetic-work'], 'effective_window': window(), 'standing': known(True)}
        objects_common.append({'ref': qualification, 'value': qualification_value})

        def capacity_mapping(target, action_id, resource_ref):
            return {**authored(organization_id, action_id), 'allow_synthetic_assumptions': True, 'ref': target,
                'organization_id': organization_id, 'run_id': run_id, 'simulation_id': None, 'source_record_sha256': None,
                'source_evidence_ref': native_resource, 'calendar_evidence_refs': [calendar], 'supported': known(True),
                'coverage': 'complete', 'as_of': now, 'data': {'clock_ref': clock,
                    'resources': [{'resource_ref': resource_ref, 'resource_kind': unit, 'region_id': region,
                        'total': {'value': str(organization_capacity_totals.get(organization_id, 1)),
                            'unit': unit, 'basis_ref': native_resource}, 'effective_window': window()}],
                    'commitments': [{'commitment_ref': r('ResourceCommitment', action_id + '-invitation'), 'resource_ref': resource_ref,
                        # Native submission changes the first engagement from
                        # 0.10 to 0.15; the second invitation adds another 0.10.
                        # This declared calendar is still checked against the
                        # actual current scalar; provenance binding never fills it.
                        'quantity': {'value': '0.25' if feedback_followup else '0.1', 'unit': unit, 'basis_ref': calendar}, 'window': window(0, tender_tick + 1)}],
                    'demands': [{'resource_kind': unit, 'region_id': region, 'unit': unit, 'amount': {'numerator': 1, 'denominator': 5},
                        'window': work_window, 'basis_refs': [basis[owner_id]]}], 'source_refs': [target, native_resource, calendar]}}

        requirement = r('Requirement', 'resources')
        if continue_clarification:
            requirement['version'] = '2'
        clarification_requirement = r('Requirement', 'published-quantity')
        a01 = deepcopy(objects_common)
        a01.extend([{'ref': requirement, 'value': {'ref': requirement, 'package_ref': package,
                'description': 'Explicit synthetic normalized capacity demand',
                'evidence_refs': [basis[owner_id]]}},
            {'ref': method, 'value': {'ref': method, 'region_ids': [region], 'work_types': ['synthetic-work'],
                'effective_window': window(), 'evidence_refs': [basis[organization_id]]}},
            {'ref': profile, 'value': {'ref': profile, 'organization_ref': ref('Organization', organization_id),
                'effective_window': window(), 'policy': policies.get(organization_id, 'participate_if_eligible'), 'require_known_funding_signal': False,
                'decline_on_negative_funding_signal': True, 'resource_comparison': 'fixed_location_half_open_exact_v1', 'evidence_refs': [basis[organization_id]]}},
            {'ref': mapping_a01, 'value': capacity_mapping(mapping_a01, 'CONTRACTOR-A01', resource)},
            {'ref': package_terms, 'value': {**authored(owner_id, 'OWN-A09'), 'allow_synthetic_assumptions': True,
                'ref': package_terms, 'package_ref': package, 'invitation_ref': invitation, 'employer_ref': ref('Organization', owner_id),
                'recipient_organization_id': organization_id, 'run_id': run_id, 'simulation_id': None, 'project_id': project_id,
                'source_record_sha256': None, 'source_evidence_ref': native_tender, 'terms_evidence_refs': [basis[owner_id]],
                'as_of': now, 'work_types': known(['synthetic-work']), 'participation_window': known(window(0, 5)),
                'work_window': known(work_window), 'qualification_requirements': known([]), 'required_method_refs': known([method]),
                'resource_demands': known([{'requirement_ref': requirement, 'resource_kind': unit, 'region_id': region,
                    'quantity': {'value': '0.2', 'unit': unit, 'basis_ref': basis[owner_id]}, 'window': work_window}]),
                'funding_signal': known(True), 'clarification_requirement_refs': [clarification_requirement] if with_clarification_request else []}},
            {'ref': screening_facts, 'value': {**authored(organization_id, 'CONTRACTOR-A01'), 'allow_synthetic_assumptions': True,
                'ref': screening_facts, 'organization_ref': ref('Organization', organization_id), 'run_id': run_id, 'as_of': now,
                'capability_ref': capability, 'commitments_ref': commitments, 'mapping_ref': mapping_a01, 'capability_window': window(),
                'work_types': known(['synthetic-work']), 'method_refs': known([method]), 'qualification_coverage': 'complete',
                'qualification_refs': [qualification], 'competence_evidence_refs': [basis[organization_id]]}}])
        if with_clarification_request:
            a01.append({'ref':clarification_requirement,'value':{'ref':clarification_requirement,'package_ref':package,
                'description':'Confirm the published procurement quantity and measurement rule',
                'evidence_refs':[basis[owner_id]]}})

        def typed(cls, value):
            return cls.model_validate(value).model_dump(mode='json')

        bid_package = typed(ContractorBidPackageView, {**common(basis[owner_id]), 'ref': package, 'round_ref': round_ref,
            'recipient_organization_ids': [organization_id], 'status': 'open', 'submission_window_ref': submission,
            'region_id': region, 'object_type': 'synthetic-work', 'work_type': 'synthetic-work', 'special_condition_codes': [],
            'coverage_keys': ['work'], 'deliverable_refs': [released], 'quantity_refs': [quantity],
            'required_qualification_codes': ['synthetic-general-work'], 'permitted_maturities': ['tender_design'],
            'allowed_method_refs': [method], 'allowed_exclusion_refs': [], 'allow_limited_bid': False})
        qs_author = {'author_actor_id': qs_id, 'author_function_ref': function[qs_id], 'author_authority_ref': grant[qs_id], 'author_action_id': 'QS-A05'}
        qs_design = typed(QSProcurementDesignView, {**common(basis[qs_id]), **qs_author, 'ref': design,
            'allowed_uses': ['procurement'], 'coverage_keys': ['work'], 'limitations': ['synthetic_assumption_no_construction_release']})
        if with_clarification_response:
            qs_design.update(author_actor_id=design_author, author_function_ref=function[design_author],
                author_authority_ref=grant[design_author], author_action_id='ARCHITECT-A04', evidence_refs=[basis[design_author]])
        qs_rule = typed(QSMeasurementRuleView, {**common(basis[qs_id]), 'ref': rule, 'supported_units': ['normalized_work_item'],
            'provisional_quantities_supported': False, 'allowed_uses': ['procurement']})
        qs_quantities = typed(QSProcurementQuantityView, {**common(basis[qs_id]), **qs_author,
            'ref': qs_schedule, 'procurement_scope_ref': qs_scope, 'round_ref': qs_round, 'design_refs': [design],
            'measurement_rule_ref': rule, 'lines': [{'line_key': 'work', 'covered_scope': scope, 'design_ref': design,
                'coverage_keys': ['work'], 'quantity': known({'value': '1', 'unit': 'normalized_work_item', 'basis_ref': basis[qs_id]}),
                'basis_refs': [basis[qs_id]], 'provisional_question_ref': r('EvidenceTarget', 'quantity-question'), 'predecessor_line_keys': []}]})
        qs_doc = typed(QSProcurementDocumentView, {**common(basis[qs_id]), **qs_author, 'ref': qs_document, 'round_ref': qs_round,
            'status': 'published', 'draft': {'procurement_scope_ref': qs_scope, 'design_refs': [design], 'quantity_schedule_ref': qs_schedule,
                'measurement_rule_ref': rule, 'pricing_rule_ref': r('PricingRule', 'rule'), 'exclusions': [], 'prior_document_ref': None, 'open_questions': []}})
        released_value = {**common(basis[qs_id]), **qs_author, 'ref': released, 'package_ref': package,
            'allowed_uses': ['procurement'], 'maturity': 'tender_design'}
        target_rule = {**common(basis[qs_id]), 'ref': rule, 'package_ref': package, 'organization_id': organization_id,
            'allowed': known(True), 'excluded_coverage_keys': []}
        from src.actions.contracts.contractor_bid_objects import ContractorBidDeliverableView, ContractorBidReferenceView
        released_value, target_rule = typed(ContractorBidDeliverableView, released_value), typed(ContractorBidReferenceView, target_rule)
        quantity_mapping_value = typed(ContractorQuantityMappingView, {**own_common, 'ref': quantity_mapping, 'run_id': run_id,
            'organization_id': organization_id, 'package_ref': package, 'package_sha256': task_digest(bid_package), 'quantity_ref': quantity,
            'document_ref': qs_document, 'document_sha256': task_digest(qs_doc), 'schedule_ref': qs_schedule, 'schedule_sha256': task_digest(qs_quantities),
            'measurement_rule_ref': rule, 'source_rule_sha256': task_digest(qs_rule), 'target_rule_sha256': task_digest(target_rule),
            'design_links': [{'design_ref': design, 'design_sha256': task_digest(qs_design), 'released_ref': released, 'released_sha256': task_digest(released_value)}],
            'relation_evidence_refs': [relation_evidence], 'author_actor_id': organization_id, 'author_function_ref': function[organization_id],
            'author_authority_ref': grant[organization_id], 'author_action_id': 'CONTRACTOR-A02', 'authored_at': now, 'allow_synthetic_assumptions': True})
        relation_doc = typed(ObservedTenderQuantityRelation, {'schema_version': 'contractor-quantity-relation-observation.v1',
            'source_mode': 'synthetic_assumption', 'run_id': run_id, 'organization_id': organization_id, 'scope': scope,
            'available_at': now, 'effective_window': window(), 'mapping_ref': quantity_mapping, 'mapping_sha256': task_digest(quantity_mapping_value),
            **{name: quantity_mapping_value[name] for name in ('package_ref', 'package_sha256', 'quantity_ref', 'document_ref', 'document_sha256',
                'schedule_ref', 'schedule_sha256', 'measurement_rule_ref', 'source_rule_sha256', 'target_rule_sha256', 'design_links')},
            'source_open_questions': [], 'source_designs': [{'ref': design, 'projection_sha256': task_digest(qs_design), 'limitations': qs_design['limitations']}]})
        relation_file = _write(directory, prefix + 'quantity-relation.json', relation_doc)
        relation_config = {**relation_file, 'evidence_ref': relation_evidence, 'evidence_locator': 'development:' + relation_evidence['id'],
            'mapping_ref': quantity_mapping, 'allow_synthetic': True}
        quantity_relations.append(relation_config)
        # This is independently declared source data, not an A02 execution result.
        expected_quantity = typed(ContractorBidQuantityView, {'ref': quantity, 'package_ref': package, 'deliverable_refs': [released],
            'measurement_rule_ref': rule, 'lines': [{'local_key': 'work', 'coverage_keys': ['work'], 'quantity': qs_quantities['lines'][0]['quantity']}],
            'status': 'ok', 'scope': scope, 'available_at': now, 'effective_window': window(tender_tick, tender_tick, 'closed_closed'),
            'evidence_refs': list({task_digest(value):value for value in
                [basis[organization_id],basis[qs_id],basis[owner_id],relation_evidence,*qs_design['evidence_refs']]}.values())})
        price_ref = r('Price', 'declared-price')
        price = typed(QSCostPriceView, {**common(basis[qs_id]), 'ref': price_ref, 'cost_component_ref': r('CostComponent', 'work'),
            'coverage_keys': ['work'], 'unit_rate': known({'value': '100', 'currency': 'HKD', 'basis_ref': basis[qs_id]}),
            'quantity_unit': 'normalized_work_item', 'measurement_rule_code': 'synthetic-item', 'region_id': region,
            'delivery_code': 'synthetic-delivery', 'valid_pricing_window': window(), 'source_locator': 'development:declared-price', 'excluded_coverage_keys': []})
        # This is the private adoption permission, not the host's executable
        # pricing MethodRef. Its content names this firm's own package.
        cost_method = r('Method', 'declared-cost-adoption')
        adoption_value = typed(ContractorBidCostAdoptionView, {**own_common, 'ref': cost_adoption, 'run_id': run_id, 'organization_id': organization_id,
            'cost_ref': cost, 'package_ref': package, 'package_sha256': task_digest(bid_package), 'quantity_basis_ref': quantity,
            'quantity_sha256': task_digest(expected_quantity), 'quantity_line_key': 'work', 'price_ref': price_ref, 'price_sha256': task_digest(price),
            'measurement_rule_ref': rule, 'measurement_rule_code': 'synthetic-item', 'delivery_code': 'synthetic-delivery', 'method_ref': cost_method,
            'adoption_evidence_refs': [adoption_evidence], 'author_actor_id': organization_id, 'author_function_ref': function[organization_id],
            'author_authority_ref': grant[organization_id], 'author_action_id': 'CONTRACTOR-A02', 'authored_at': now, 'allow_synthetic_assumptions': True})
        cost_doc = typed(ObservedTenderCostAdoption, {'schema_version': 'contractor-cost-adoption-observation.v1', 'source_mode': 'synthetic_assumption',
            'run_id': run_id, 'organization_id': organization_id, 'scope': scope, 'available_at': now, 'effective_window': window(),
            'adoption_ref': cost_adoption, 'adoption_sha256': task_digest(adoption_value),
            **{name: adoption_value[name] for name in ('cost_ref', 'package_ref', 'package_sha256', 'quantity_basis_ref', 'quantity_sha256',
                'quantity_line_key', 'price_ref', 'price_sha256', 'measurement_rule_ref', 'measurement_rule_code', 'delivery_code', 'method_ref',
                'author_actor_id', 'author_function_ref', 'author_authority_ref', 'authored_at')},
            'quantity_line': expected_quantity['lines'][0], 'price_source_locator': price['source_locator'],
            **{name: price[name] for name in ('unit_rate', 'quantity_unit', 'region_id', 'coverage_keys', 'excluded_coverage_keys')}})
        cost_file = _write(directory, prefix + 'cost-adoption.json', cost_doc)
        cost_adoptions.append({**cost_file, 'evidence_ref': adoption_evidence, 'evidence_locator': 'development:' + adoption_evidence['id'],
            'adoption_ref': cost_adoption, 'allow_synthetic': True})
        a02 = deepcopy(objects_common)
        a02.extend([{'ref': package, 'value': bid_package}, {'ref': released, 'value': released_value}, {'ref': rule, 'value': target_rule},
            {'ref': quantity_mapping, 'value': quantity_mapping_value}, {'ref': cost_adoption, 'value': adoption_value}, {'ref': price_ref, 'value': price},
            {'ref': cost_method, 'value': {**own_common, 'ref': cost_method, 'package_ref': package, 'organization_id': organization_id,
                'allowed': known(True), 'excluded_coverage_keys': []}},
            {'ref': mapping_a02, 'value': capacity_mapping(mapping_a02, 'CONTRACTOR-A02', pool)},
            {'ref': bid_facts, 'value': {**authored(organization_id, 'CONTRACTOR-A02'), 'allow_synthetic_assumptions': True,
                'ref': bid_facts, 'organization_id': organization_id, 'run_id': run_id, 'as_of': now, 'capacity_ref': capacity,
                'mapping_ref': mapping_a02, 'qualification_coverage': 'complete', 'qualification_refs': [qualification],
                'qualification_evidence_refs': [basis[organization_id]]}},
            {'ref': method, 'value': {**own_common, 'ref': method, 'region_ids': [region], 'object_types': ['synthetic-work'],
                'work_types': ['synthetic-work'], 'special_condition_codes': [], 'quantity_unit': 'normalized_work_item', 'capacity_unit': unit,
                'resource_kind': unit, 'quantity_per_capacity_tick': known('1'), 'productivity_basis_ref': basis[organization_id], 'output_quantity_basis_refs': [quantity]}},
            {'ref': programme, 'value': {**own_common, 'ref': programme, 'organization_id': organization_id, 'package_ref': package, 'quantity_refs': [quantity],
                'author_actor_id': organization_id, 'author_function_ref': function[organization_id], 'author_authority_ref': grant[organization_id],
                'tasks': [{'local_key': 'work', 'scope_ref': scope, 'work_method_ref': method, 'target_quantities': [{'value': '1', 'unit': 'normalized_work_item', 'basis_ref': basis[qs_id]}],
                    'dependency_refs': [], 'allocations': [{'resource_ref': pool, 'task_scope_ref': scope, 'window_ref': work_slot,
                        'quantity': {'value': '0.2', 'unit': unit, 'basis_ref': calendar}}], 'window_ref': work_slot,
                    'quantity_sources': [{'quantity_basis_ref': quantity, 'quantity_line_key': 'work'}]}]}},
            {'ref': pricing, 'value': {**own_common, 'ref': pricing, 'organization_id': organization_id, 'package_ref': package,
                'authority_ref': grant[organization_id], 'choice': 'decline_bid' if (feedback_followup and not allow_followup_bids) or policies.get(organization_id) == 'decline_new_work' else 'submit_bid', 'currency': 'HKD', 'markup_fraction': '0.1', 'markup_basis_ref': basis[organization_id],
                'commercial_allowance': {'value': '0', 'currency': 'HKD', 'basis_ref': basis[organization_id]}, 'programme_ref': programme,
                'terms_ref': terms, 'validity_ref': validity, 'exclusion_refs': [], 'decline_reason': (
                    'Explicit independent commercial policy declines this subsequent tender request.' if feedback_followup and not allow_followup_bids
                    else 'Explicit initial commercial policy declines new work.' if policies.get(organization_id) == 'decline_new_work'
                    else 'Explicit synthetic submit-bid pricing policy.')}}])
        if allow_followup_bids:
            decline_value = deepcopy(next(row['value'] for row in a02 if row['ref'] == pricing))
            decline_value.update(ref=decline_pricing, choice='decline_bid',
                decline_reason='Explicit independent refusal if the original A01 does not participate.')
            a02.append({'ref': decline_pricing, 'value': decline_value})
        for reference in (round_ref, terms):
            a02.append({'ref': reference, 'value': {**common(basis[owner_id]), 'ref': reference, 'package_ref': package,
                'organization_id': organization_id, 'allowed': known(True), 'excluded_coverage_keys': []}})
        for reference, value in ((work_slot, work_window), (validity, window(1, 8)), (submission, window(0, 5))):
            a02.append({'ref': reference, 'value': value})
        for evidence_ref, file in ((relation_evidence, relation_file), (adoption_evidence, cost_file)):
            a02.append({'ref': evidence_ref, 'value': {'ref': evidence_ref, 'source_kind': 'synthetic', 'basis_kind': 'assumed',
                'locator': 'development:' + evidence_ref['id'], 'content_hash': file['file_sha256'], 'effective_window': window()}})
        source_quantities = [row for row in deepcopy(objects_common) if row['ref']['kind'] != 'Qualification']
        source_quantities.extend([{'ref': row['ref'], 'value': row} for row in (qs_design, qs_rule, qs_quantities, qs_doc)])
        targets = [package, invitation, capability, commitments, quantity, cost, capacity, pool,
            r('ResourceCommitment', 'CONTRACTOR-A02-invitation'), handoff_ref, handoff_native, handoff_result,
            proposal_mapping, indicator_input, indicator_result]
        if feedback_followup:
            targets.extend([feedback_profile, feedback_evidence])
        if observe_current_occupancy:
            targets.extend(r('ResourceCommitment', action_id + '-observed-current')
                for action_id in ('CONTRACTOR-A01','CONTRACTOR-A02'))
        all_refs = {task_digest(row['ref']): row['ref'] for row in [*a01, *a02, *source_quantities]}
        all_refs.update({task_digest(item): item for item in targets})
        candidate_a01, candidate_a02 = r('CandidateSet', 'screening'), r('CandidateSet', 'bid')
        if continue_clarification:
            candidate_a01['version'] = '2'
        response_evidence = r('Evidence', 'consumed-clarification-response')
        previous_refs = {task_digest(value):dict(value,version='1') for value in
            (package,invitation,package_terms,requirement,candidate_a01)} if continue_clarification else {}
        def previous(value):
            if isinstance(value,dict):
                if isinstance(value.get('ref'),dict) and value['ref'].get('kind')=='Authorization':
                    return deepcopy(value)
                if set(value)=={'kind','id','version'} and task_digest(value) in previous_refs:
                    return deepcopy(previous_refs[task_digest(value)])
                return {k:previous(v) for k,v in value.items()}
            if isinstance(value,list):return [previous(v) for v in value]
            return value
        if continue_clarification:
            all_refs.update({task_digest(item):item for item in [*previous_refs.values(),response_evidence]})
        all_refs.update({task_digest(item): item for item in (candidate_a01, candidate_a02)})
        authorizations[organization_id]['readable_refs'] = list(all_refs.values())
        # Own grant projections were intentionally shared until this complete
        # explicit source/target set was available; no competitor refs are added.
        for collection in (a01, a02, source_quantities):
            for row in collection:
                if row['ref'] == grant[organization_id]:
                    row['value'] = deepcopy(authorizations[organization_id])
        for collection, candidate, choices in ((a01, candidate_a01, ['participate', 'decline', 'clarify']),
                (a02, candidate_a02, ['submit_bid', 'decline_bid'])):
            collection.append({'ref': candidate, 'value': {'operation_id': prefix + ('screening' if candidate == candidate_a01 else 'bid'),
                'scope': scope, 'as_of': now, 'candidates': [{'ref': package, 'permitted_choices': choices}],
                'search_profile_ref': r('Profile', 'explicit-exposure')}})
        successor_a01 = None
        if continue_clarification:
            successor_a01 = [deepcopy(row) for row in a01 if row['ref'] != clarification_requirement]
            for row in successor_a01:
                if row['ref']==package_terms:
                    row['value']['clarification_requirement_refs']=[]
                    row['value']['terms_evidence_refs'].append(response_evidence)
                if row['ref']==candidate_a01:
                    row['value']['operation_id']=prefix+'screening-after-clarification'
            a01 = previous(a01)

        def context(stage, action_id):
            return {'run_id': run_id, 'actor_id': organization_id, 'function_ref': function[organization_id], 'authorization_refs': [grant[organization_id]],
                'operation_id': prefix + ('screening' if action_id == 'CONTRACTOR-A01' else 'bid'), 'contract_ref': ref('ActionContract', action_id),
                'task_ref': r('DecisionTask', stage), 'scope': scope, 'business_time': now, 'read_token': prefix + stage,
                'visible_refs': list(all_refs.values()), 'candidate_set_ref': candidate_a01 if action_id == 'CONTRACTOR-A01' else candidate_a02,
                'execution_mode': 'llm' if model_config is not None else 'rule'}

        contexts = {stage: context(stage, 'CONTRACTOR-A01' if stage in ('screening-source', 'screening') else 'CONTRACTOR-A02')
            for stage in ('screening-source', 'screening', 'capacity', 'quantity', 'cost', 'bid', 'handoff-source', 'mapping', 'exposure')}
        if allow_followup_bids:
            for stage in ('capacity', 'quantity', 'cost', 'bid'):
                contexts['decline-' + stage] = context('decline-' + stage, 'CONTRACTOR-A02')
        if continue_clarification:
            for stage in ('screening-source','screening'):
                contexts[stage]['candidate_set_ref']=previous(candidate_a01)
            for stage in ('screening-resolved-source','screening-resolved'):
                contexts[stage]=context(stage,'CONTRACTOR-A01')
                contexts[stage]['operation_id']=prefix+'screening-after-clarification'

        def snapshot(ctx, objects):
            objects = deepcopy(objects)
            occupancy_bindings = []
            if observe_current_occupancy:
                for row in objects:
                    if row['ref']['kind'] != 'GbaCapacityMapping':
                        continue
                    mapping = row['value']
                    commitment = mapping['data']['commitments'][0]
                    # The independently supplied calendar remains an assumption.
                    # Split off only its current integer point for an actual read.
                    commitment['window']['end'] = deepcopy(now)
                    observed = deepcopy(commitment)
                    observed['commitment_ref'] = r('ResourceCommitment', mapping['author_action_id'] + '-observed-current')
                    observed['window'] = {'start':deepcopy(now),
                        'end':{**deepcopy(now),'offset':now['offset']+1},'bounds':'closed_open'}
                    observed['quantity'].update(value=None,basis_ref=native_resource)
                    mapping['data']['commitments'].append(observed)
                    occupancy_bindings.append({'mapping_ref':row['ref'],'commitment_ref':observed['commitment_ref']})
            bindings = [{'ref': native_resource, 'source': 'enterprise_resources'}, {'ref': native_tender, 'source': 'invited_tender'}]
            if any(row['ref'] == mapping_a01 for row in objects):
                bindings.append({'ref': mapping_a01, 'source': 'enterprise_resources'})
            for row in objects:
                if row['ref']['kind']=='GbaTenderPackageTerms':
                    bindings.append({'ref':row['ref'],'source':'invited_tender'})
            if any(row['ref'] == mapping_a02 for row in objects):
                bindings.append({'ref': mapping_a02, 'source': 'enterprise_resources'})
            return {'context': ctx, 'project_id': project_id, 'native_resource_sha256': None, 'native_tender_sha256': None,
                'clarification_evidence_ref':response_evidence if continue_clarification and ctx['read_token'] in
                    (contexts['screening-resolved-source']['read_token'],contexts['screening-resolved']['read_token']) else None,
                **({'current_occupancy_bindings':occupancy_bindings} if occupancy_bindings else {}),
                'native_bindings': bindings, 'projection': {'run_id': run_id, 'macro_version': 'gba-public-2026-08-21',
                    'state_version': 'explicit-synthetic-source-v1', 'read_token': ctx['read_token'], 'business_time': now,
                    'organization_id': organization_id, 'objects': objects}}

        # Different original readers have deliberately different closed
        # schemas, notably the QS and Contractor measurement-rule views.
        # Author each projection for that reader and validate before writing.
        def reader_objects(objects, schemas):
            from integration.contractor_tender_snapshot_sources import bind_snapshot_provenance

            selected = [deepcopy(row) for row in objects if row['ref']['kind'] in schemas.registered_kinds]
            # Validate the template's professional fields with dummy provenance
            # in a temporary copy only. The written template retains nulls;
            # actual source hashes can only come from the current request.
            template = snapshot(contexts['screening'], selected)
            temporary = bind_snapshot_provenance(template, resource_sha256='0' * 64,
                tender_sha256='0' * 64, simulation_id='schema-validation-only')
            for row in temporary['projection']['objects']:
                if row['ref']['kind']=='GbaCapacityMapping':
                    for commitment in row['value']['data']['commitments']:
                        if commitment['quantity']['value'] is None:
                            commitment['quantity']['value']='1'  # Temporary schema check only.
            bound_refs = {Reference.model_validate(row['ref']).key() for row in template['native_bindings']}
            for original, resolved in zip(selected, temporary['projection']['objects']):
                parsed = schemas.validate_projection(Reference.model_validate(resolved['ref']), resolved['value'])
                if parsed is not None and Reference.model_validate(original['ref']).key() not in bound_refs:
                    original['value'] = parsed.model_dump(mode='json')
            return selected

        screening_schemas = gba_contractor_screening_source_schemas()
        source_schemas = gba_contractor_screening_source_schemas()
        source_schemas.register_kind('GbaTenderPackageTerms', GbaTenderPackageTermsView, str)
        for stage, ctx in contexts.items():
            source_stage = stage in ('screening-source','screening-resolved-source')
            screening_stage = source_stage or stage in ('screening','screening-resolved')
            schemas = source_schemas if source_stage else screening_schemas if screening_stage else gba_bid_capacity_source_schemas()
            objects = successor_a01 if stage in ('screening-resolved-source','screening-resolved') else a01 if screening_stage else a02
            snapshots.append(snapshot(ctx, reader_objects(objects, schemas)))
        quantity_snapshots.append(snapshot(contexts['quantity'], reader_objects(source_quantities, contractor_quantity_source_schemas())))
        if allow_followup_bids:
            quantity_snapshots.append(snapshot(contexts['decline-quantity'], reader_objects(source_quantities, contractor_quantity_source_schemas())))
        native_sources[prefix + 'screening'] = {'project_id': project_id, 'terms_ref': previous(package_terms), 'screening_facts_ref': screening_facts}
        if continue_clarification:
            native_sources[prefix+'screening-after-clarification'] = {'project_id':project_id,
                'terms_ref':package_terms,'screening_facts_ref':screening_facts}
        native_sources[prefix + 'bid'] = {'project_id': project_id, 'bid_facts_ref': bid_facts}
        request_id = f'proposal-tick{tender_tick}-{project_id}-{organization_id}-consider_tender'
        handoffs[prefix + 'bid'] = {'project_id': project_id, 'request_id': request_id}
        indicator_doc = {**authored(organization_id, 'CONTRACTOR-A02'), 'schema_version': 'contractor-tender-indicator-input.v1',
            'run_id': run_id, 'simulation_id': None, 'organization_id': organization_id, 'project_id': project_id, 'package_ref': package,
            'mapping_ref': proposal_mapping, 'input_evidence_ref': indicator_input, 'result_evidence_ref': indicator_result,
            'source_kind': 'synthetic', 'basis_kind': 'assumed', 'source_note': NOTE, 'legacy_currency': 'HKD',
            **{name: {'value': value, 'unit': 'score' if name == 'utility' else 'probability' if name == 'bid_probability' else 'fraction',
                'basis_ref': indicator_input} for name, value in
                [('utility', '0.5'), ('bid_probability', '1'), ('risk_level', '0.2'), ('regional_friction', '0'), ('expected_profit', '0.1')]},
            'declined_reference_price': {'value': '100', 'currency': 'HKD', 'basis_ref': indicator_input}
                if feedback_followup or policies.get(organization_id) == 'decline_new_work' else None}
        indicator_doc['evidence_refs'] = [basis[organization_id], indicator_input, indicator_result]
        indicator_file = _write(directory, prefix + 'indicators.json', indicator_doc)
        indicator_config = {**indicator_file, 'evidence_locator': 'development:' + indicator_input['id'],
            'allow_synthetic': True, 'bind_simulation_on_request': True}
        indicator_documents[request_id] = indicator_config
        plans.append({'request_binding': 'current_native_request', 'organization_id': organization_id, 'project_id': project_id, 'tick': tender_tick,
            'screening_context': contexts['screening'], 'screening_inputs': {'package_ref': previous(package), 'capability_ref': capability, 'commitments_ref': commitments,
                'screening_profile_ref': profile, 'qualification_refs': [qualification], 'invitation_refs': [previous(invitation)]}, 'screening_mapping_ref': mapping_a01,
            'screening_publication': {'source_context': contexts['screening-source'], 'terms_ref': previous(package_terms), 'facts_ref': screening_facts},
            'bid_plan': {'capacity_context': contexts['capacity'], 'quantity_context': contexts['quantity'], 'cost_context': contexts['cost'],
                'bid_context': contexts['bid'], 'capacity_facts_ref': bid_facts, 'quantity_mapping_refs': [quantity_mapping], 'cost_adoption_refs': [cost_adoption],
                'pricing_profile_ref': pricing, 'capacity_ref': capacity, 'handoff_basis_ref': handoff_ref, 'allowed_method_refs': [method]},
            'handoff_production': {'source_context': contexts['handoff-source'], 'author': authored(organization_id, 'CONTRACTOR-A02'),
                'procurement_source_evidence_ref': handoff_native, 'screening_result_evidence_ref': handoff_result},
            'mapping_source_context': contexts['mapping'], 'exposure_context': contexts['exposure'], 'mapping_ref': proposal_mapping,
            'indicator_document': indicator_config})
        if continue_clarification:
            plans[-1]['clarification_continuation'] = {'screening_context':contexts['screening-resolved'],
                'screening_inputs':{**deepcopy(plans[-1]['screening_inputs']),'package_ref':package,'invitation_refs':[invitation]},
                'screening_mapping_ref':mapping_a01,'screening_publication':{'source_context':contexts['screening-resolved-source'],
                    'terms_ref':package_terms,'facts_ref':screening_facts},'response_evidence_ref':response_evidence}
        if with_clarification_response:
            from integration.contractor_tender_clarification_development import build_response_plan
            plans[-1]['clarification_response'] = build_response_plan(run_id=run_id,qs_id=qs_id,owner_id=owner_id,
                scope=scope,now=now,prefix=prefix,shared_sources=shared,authorizations=authorizations,
                function_refs=function,grant_refs=grant,basis_refs=basis,design=qs_design,rule=qs_rule,
                quantity=qs_quantities,document=qs_doc,requirement_refs=[clarification_requirement],
                publication_permitted=clarification_publication_permitted)
        if feedback_followup:
            plan = plans[-1]
            plan['screening_inputs']['screening_profile_ref'] = feedback_profile
            if continue_clarification:
                plan['clarification_continuation']['screening_inputs']['screening_profile_ref']=feedback_profile
            plan['feedback_policy'] = {'base_profile_ref': profile, 'evidence_ref': feedback_evidence,
                'decline_after_prior_submissions': 1, 'project_only': False,
                'query_prior_submissions':query_prior_submissions}
        if allow_followup_bids:
            plan = plans[-1]
            source_plan = deepcopy(plan['bid_plan'])
            source_plan.pop('handoff_basis_ref')
            source_plan['pricing_profile_ref'] = decline_pricing
            for stage in ('capacity', 'quantity', 'cost', 'bid'):
                source_plan[stage + '_context'] = contexts['decline-' + stage]
            plan['decline'] = {'context': contexts['decline-bid'], 'pricing_profile_ref': decline_pricing,
                'capacity_ref': capacity, 'cost_refs': [], 'allowed_method_refs': [method], 'source_plan': source_plan}
        elif feedback_followup or policies.get(organization_id) == 'decline_new_work':
            plan = plans[-1]
            source_plan = plan.pop('bid_plan')
            source_plan.pop('handoff_basis_ref')
            plan.pop('handoff_production')
            plan['decline'] = {'context': contexts['bid'], 'pricing_profile_ref': pricing, 'capacity_ref': capacity,
                'cost_refs': [], 'allowed_method_refs': [method], 'source_plan': source_plan}

    # Complete the QS read grant only after both private source plans are known.
    # Every read point carries that same original immutable grant projection.
    if with_clarification_response:
        collections = [s['projection']['objects'] for s in [*snapshots,*quantity_snapshots]]
        collections += [p['clarification_response']['objects'] for p in plans]
        for collection in collections:
            for row in collection:
                if row['ref'] == grant[qs_id]:
                    row['value'] = deepcopy(authorizations[qs_id])

    if model_config is not None:
        from integration.tender_model_development import add_initial_model_options
        add_initial_model_options(config=model_config, snapshots=snapshots,
            quantity_snapshots=quantity_snapshots, plans=plans, authorizations=authorizations)

    def source_file(name, values):
        file = _write(directory, name, {'schema_version': 'contractor-tender-source-snapshots.v1', 'version': '1',
            'run_id': run_id, 'simulation_id': None, 'snapshots': values})
        return {'version': '1', 'snapshot_path': file['file_path'], 'snapshot_sha256': file['file_sha256'], 'bind_native_on_request': True}

    source_settings, quantity_settings = source_file('sources.json', snapshots), source_file('quantity-sources.json', quantity_snapshots)
    professional = {'versions': {name: 'development-v1' for name in ('publication', 'quantity', 'cost', 'handoff', 'exposure', 'mapping', 'final')},
        'publication': {'native_sources': native_sources}, 'quantity': {'relations': quantity_relations}, 'cost': {'adoptions': cost_adoptions},
        'handoff': {'handoffs': handoffs}, 'exposure': {'request_documents': indicator_documents}, 'mapping': {'request_documents': indicator_documents},
        'final': {'use_request_trigger': True}}
    configuration_input = {'schema_version': 'contractor-tender-configuration-input.v1', 'host_id': run_id, 'version': '1', 'source_version': '1',
        'application_version': '1', 'macro_version': 'gba-public-2026-08-21', 'proposal_client_version': 'development-proposal-v1',
        'final_client_version': 'development-final-v1', 'policy_version': 'development-explicit-assumptions-v1', 'mode': 'offline',
        'authority': {'runtime_id': run_id, 'version': '1', 'organization_snapshot': {'schema_version': 'organization.v2', 'run_id': run_id,
            'organizations': organizations, 'authorizations': list(authorizations.values())}},
        'snapshots': source_settings, 'quantity_snapshots': quantity_settings, 'task_selector': {'selector_id': run_id, 'version': '1'},
        'current_validation': {'validator_id': run_id, 'version': '1'}, 'professional': professional,
        'native_publication': {'project_ids': {ctx['operation_id']:project_id for plan in plans for ctx in
            [plan['screening_context'], *([plan['clarification_continuation']['screening_context']] if continue_clarification else [])]}},
        'request_work_factory': 'integration.contractor_tender_request_sources:build_request_work',
        'allow_saved_recovery':allow_saved_recovery,
        'continue_unstarted_actions_on_error':continue_unstarted_actions_on_error,
        'publish_native_clarification_requests':with_clarification_request,
        'request_recovery_factory':'integration.contractor_tender_saved_recovery:recover_request_work' if allow_saved_recovery else None,
        'request_work_settings': {'version': '1', 'requests': plans}}
    if model_config is not None:
        configuration_input.update(mode='llm',
            model_host_factory='integration.contractor_tender_model_options:build_model_host',
            model_host_settings=model_config.host_settings(run_id))
    configuration = build_configuration(configuration_input)
    _write(directory, 'tender-configuration-input.json', configuration_input)
    _write(directory, 'tender-host.json', configuration.model_dump(mode='json'))
    native_request = SimulationCreateRequest.model_validate({'agent_source': 'explicit', 'agents': [{'agent_id': name, 'name': name, 'role': role,
        'region': region, 'enterprise_type': 'synthetic_development',
        'total_resource_capacity': organization_capacity_totals.get(name, 1.0)} for name, role in native_roles.items()],
        'initial_projects': [{'project_id': project_id, 'name': 'Synthetic native tender window', 'project_type': 'building', 'region': region,
            'owner_id': owner_id, 'selected_qs_id': qs_id, 'initial_budget': 1000, 'current_stage': 'tendering'}],
        'enable_project_generation': False, 'use_prior_network_edges': False, 'ticks': tender_tick, 'random_seed': 42})
    _write(directory, 'macro-request.json', native_request.model_dump(mode='json'))
    native_settings = {
        'run_id': run_id, 'query_saved_tender_on_error':query_saved_tender_on_error,
        'native_proposals': [{'role': role, 'operation': 'decide_monthly_operation'} for role in sorted(set(native_roles.values()))]
            + [{'role': 'Owner', 'operation': 'select_tender_invitees'}],
        'native_decisions': [{'role': role, 'decision_type': 'monthly_enterprise_operation'} for role in sorted(set(native_roles.values()))]
            + [{'role': 'Owner', 'decision_type': 'owner_tender_shortlist'}]}
    _write(directory, 'native-host.json', {'schema_version': 'gba-module-host-config.v1', 'host_id': run_id, 'version': '1',
        'settings': native_settings if model_config is None else {'native': native_settings,
            'expected_provider': model_config.provider, 'expected_model': model_config.model}})
    _write(directory, 'assembly-host.json', {'schema_version': 'gba-module-host-config.v1', 'host_id': run_id, 'version': '1',
        'settings': {'tender_configuration_path': str(directory / 'tender-host.json')}} if model_config is None
        else configuration.model_dump(mode='json'))
    if initial_screening_policies is not None:
        _write(directory, 'initial-screening-policies.json', policies)
    if model_config is None:
        _write_launch_files(directory)
    else:
        from integration.tender_model_development import write_model_launch_files
        write_model_launch_files(directory)
    return {'status': 'synthetic_input_bundle_unverified', 'directory': str(directory), 'run_id': run_id, 'source_note': NOTE}


def build_feedback_bundle(directory, *, run_id,allow_saved_recovery=False,query_saved_tender_on_error=False,
        project_id='dev-tender-project',followup_project_id='dev-followup-project',source_namespace='',
        query_prior_submissions=False,continue_unstarted_actions_on_error=False,evaluation_feedback=False,
        initial_screening_policies=None, decline_after_prior_declines=None, decline_after_prior_final_accounts=None,
        decline_after_prior_payment_delays=None,
        observe_current_occupancy=False, allow_followup_bids=False, **initial_bindings):
    """Compose two independently scoped inputs into one original native run.

    Only initial input authoring happens here. Native lifecycle timing creates
    both requests; no request, event, decision or final result is replayed.
    """
    from integration.contractor_tender_configuration import build_configuration

    model_config = None
    if initial_bindings.get('model_options') is not None:
        from integration.tender_model_development import TenderModelDevelopmentSettings
        model_config = TenderModelDevelopmentSettings.model_validate(initial_bindings['model_options'])
    if type(evaluation_feedback) is not bool:
        raise ValueError('Evaluation feedback scenario requires an explicit boolean declaration')
    if type(allow_followup_bids) is not bool:
        raise ValueError('Followup bid permission requires an explicit boolean')
    _screening_policies(initial_screening_policies, initial_bindings.get('contractor_ids', ('dev-contractor-a','dev-contractor-b')))
    if decline_after_prior_declines is not None and (type(decline_after_prior_declines) is not int or decline_after_prior_declines < 1):
        raise ValueError('Decline feedback requires an explicit positive integer limit')
    if evaluation_feedback and decline_after_prior_declines is not None:
        raise ValueError('Use a separate initial bundle for evaluation and decline feedback strategies')
    if decline_after_prior_final_accounts is not None and (
            type(decline_after_prior_final_accounts) is not int or decline_after_prior_final_accounts < 1):
        raise ValueError('Final-account feedback requires an explicit positive integer limit')
    if decline_after_prior_payment_delays is not None and (
            type(decline_after_prior_payment_delays) is not int or decline_after_prior_payment_delays < 1):
        raise ValueError('Payment-delay feedback requires an explicit positive integer limit')
    observe_current_occupancy = (observe_current_occupancy or evaluation_feedback or bool(initial_screening_policies) or allow_followup_bids
        or decline_after_prior_final_accounts is not None or decline_after_prior_payment_delays is not None)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    first, followup = directory / 'first', directory / 'followup'
    build_bundle(first, run_id=run_id,project_id=project_id,source_namespace=source_namespace,
        tender_tick=1 if evaluation_feedback else 2,observe_current_occupancy=observe_current_occupancy,
        allow_saved_recovery=allow_saved_recovery,query_saved_tender_on_error=query_saved_tender_on_error,
        continue_unstarted_actions_on_error=continue_unstarted_actions_on_error,
        initial_screening_policies=initial_screening_policies, **initial_bindings)
    build_bundle(followup, run_id=run_id, project_id=followup_project_id, tender_tick=4 if evaluation_feedback else 3,
        source_namespace=source_namespace+'followup-', feedback_followup=True,allow_saved_recovery=allow_saved_recovery,
        allow_followup_bids=allow_followup_bids,
        observe_current_occupancy=observe_current_occupancy,
        query_saved_tender_on_error=query_saved_tender_on_error,query_prior_submissions=query_prior_submissions,
        continue_unstarted_actions_on_error=continue_unstarted_actions_on_error,**initial_bindings)

    def read(folder, name):
        return json.loads((folder / name).read_text(encoding='utf-8'))

    initial, later = [read(folder, 'tender-configuration-input.json') for folder in (first, followup)]
    authority = initial['authority']['organization_snapshot']
    grants = {row['organization_id']: row for row in authority['authorizations']}
    for row in later['authority']['organization_snapshot']['authorizations']:
        target = grants[row['organization_id']]
        for name in ('scopes', 'readable_refs'):
            target[name] = list({task_digest(value): value for value in [*target[name], *row[name]]}.values())
    # Each immutable grant version has one combined initial value everywhere.
    # Contexts retain their project-local visible set and private recipient.
    for name, setting in [('sources.json', 'snapshots'), ('quantity-sources.json', 'quantity_snapshots')]:
        document = read(first, name)
        document['snapshots'].extend(read(followup, name)['snapshots'])
        for snapshot in document['snapshots']:
            for row in snapshot['projection']['objects']:
                if row['ref']['kind'] == 'Authorization':
                    row['value'] = deepcopy(grants[row['value']['organization_id']])
        file = _write(directory, name, document)
        initial[setting].update(snapshot_path=file['file_path'], snapshot_sha256=file['file_sha256'])
    for section, key in [('publication', 'native_sources'), ('handoff', 'handoffs'),
            ('exposure', 'request_documents'), ('mapping', 'request_documents')]:
        initial['professional'][section][key].update(later['professional'][section][key])
    for section, key in [('quantity', 'relations'), ('cost', 'adoptions')]:
        initial['professional'][section][key].extend(later['professional'][section][key])
    initial['request_work_settings']['requests'].extend(later['request_work_settings']['requests'])
    if decline_after_prior_declines is not None:
        for plan in initial['request_work_settings']['requests']:
            if plan.get('feedback_policy') is not None:
                plan['feedback_policy'].update(decline_after_prior_submissions=None,
                    decline_after_prior_declines=decline_after_prior_declines)
    if evaluation_feedback:
        for plan in initial['request_work_settings']['requests']:
            if plan.get('feedback_policy') is not None:
                plan['feedback_policy'].update(decline_after_prior_submissions=999,decline_after_prior_evaluations=1)
    if decline_after_prior_final_accounts is not None:
        for plan in initial['request_work_settings']['requests']:
            if plan.get('feedback_policy') is not None:
                plan['feedback_policy'].update(decline_after_prior_submissions=None,
                    decline_after_prior_final_accounts=decline_after_prior_final_accounts)
    if decline_after_prior_payment_delays is not None:
        for plan in initial['request_work_settings']['requests']:
            if plan.get('feedback_policy') is not None:
                plan['feedback_policy'].update(decline_after_prior_submissions=None,
                    decline_after_prior_payment_delays=decline_after_prior_payment_delays)
    for plan in initial['request_work_settings']['requests']:
        if plan.get('clarification_response') is not None:
            for row in plan['clarification_response']['objects']:
                if row['ref']['kind'] == 'Authorization':
                    row['value'] = deepcopy(grants[row['value']['organization_id']])
    initial['native_publication']['project_ids'].update(later['native_publication']['project_ids'])
    configuration = build_configuration(initial)
    _write(directory, 'tender-configuration-input.json', initial)
    _write(directory, 'tender-host.json', configuration.model_dump(mode='json'))
    native_request = read(first, 'macro-request.json')
    next_project = read(followup, 'macro-request.json')['initial_projects'][0]
    next_project['current_stage'] = 'tender_preparation'
    next_project['stage_tick'] = 0 if evaluation_feedback else 1
    next_project['performance']['information_quality'] = 0.8
    native_request['initial_projects'].append(next_project)
    native_request['ticks'] = 4 if evaluation_feedback else 3
    if evaluation_feedback:
        first_project=native_request['initial_projects'][0]
        contractors=[a['agent_id'] for a in native_request['agents'] if a['role']=='Contractor']
        first_project['flags'].update(contractors_invited=True,invited_contractor_ids=contractors,bids_collected=False)
        first_project['engagements']=[{'engagement_id':'initial-invitation-'+org,
            'project_id':project_id,'agent_id':org,'role':'Contractor','status':'invited',
            'start_stage':'tendering','joined_at_tick':0,'resource_allocation':0.15} for org in contractors]
        for agent in native_request['agents']:
            if agent['agent_id'] in contractors:agent['occupied_resource']=0.15
        _write(directory,'initial-invitation-source.json',{'source_kind':'synthetic','basis_kind':'assumed',
            'note':'Explicit pre-existing invitations and 0.15 native occupation at tick zero; not current-run Owner actions or events.',
            'project_id':project_id,'contractor_ids':contractors,'first_bid_tick':1,'later_bid_tick':4,
            'decline_after_prior_submissions':999,'decline_after_prior_evaluations':1})
    enable_gba_imports()
    from gba_construction_sim.backend.models.simulation import SimulationCreateRequest

    _write(directory, 'macro-request.json', SimulationCreateRequest.model_validate(native_request).model_dump(mode='json'))
    native_host = read(first, 'native-host.json')
    _write(directory, 'native-host.json', native_host)
    _write(directory, 'assembly-host.json', {'schema_version': 'gba-module-host-config.v1', 'host_id': run_id,
        'version': '1', 'settings': {'tender_configuration_path': str(directory / 'tender-host.json')}} if model_config is None
        else configuration.model_dump(mode='json'))
    if model_config is None:
        _write_launch_files(directory, feedback_followup=True)
    else:
        from integration.tender_model_development import write_model_launch_files
        write_model_launch_files(directory)
    return {'status': 'synthetic_feedback_bundle_unverified', 'directory': str(directory), 'run_id': run_id, 'source_note': NOTE}


def configure_assembly(*, assembly, request, output_directory, offline, configuration):
    """Attach explicit native routes, then install the existing tender host."""
    from integration.contractor_tender_module_host import configure_assembly as configure_tender
    from integration.module_host import GbaModuleHostConfiguration, GbaModuleHostExtension, load_module_host_configuration

    configuration = GbaModuleHostConfiguration.model_validate(configuration)
    if offline is not True or set(configuration.settings) != {'tender_configuration_path'}:
        raise ValueError('Development assembly requires explicit offline mode and one tender configuration path')
    routes = getattr(assembly.client, 'native_routes', None)
    if routes is None:
        raise ValueError('Development assembly requires the explicit native-route client factory')
    routes.attach(assembly)
    path = Path(configuration.settings['tender_configuration_path'])
    pinned_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    extension = configure_tender(assembly=assembly, request=request, output_directory=output_directory, offline=offline,
        configuration=load_module_host_configuration(path))

    def evidence():
        if hashlib.sha256(path.read_bytes()).hexdigest() != pinned_sha:
            raise ValueError('Development tender configuration changed during execution')
        return {'schema_version': 'contractor-tender-development.v1', 'source_note': NOTE,
            'tender': extension.evidence(), 'native_routes': routes.evidence()}

    return GbaModuleHostExtension(version='contractor-tender-development.v1', evidence=evidence,
        close=extension.close, writer_guard=extension.writer_guard)


def verify_bundle(directory):
    """Read-only byte verification of an explicitly generated input bundle."""
    directory = Path(directory).resolve()
    manifest = json.loads((directory / 'input-manifest.json').read_text(encoding='utf-8'))
    policy_ok=(manifest.get('schema_version')=='contractor-tender-development-input.v1' and manifest.get('source_note')==NOTE
        or manifest.get('schema_version')=='integration-development-input.v1'
        and isinstance(manifest.get('source_note'),str) and bool(manifest['source_note'].strip()))
    if not policy_ok or not manifest.get('files'):
        raise ValueError('Development input manifest is incomplete or has a different source policy')
    for name, expected in manifest['files'].items():
        path = (directory / name).resolve()
        if (Path(name).is_absolute() or '..' in Path(name).parts or not path.is_relative_to(directory)
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
            raise ValueError('Development input file differs from the frozen manifest: ' + name)
    return {'status': 'input_bytes_verified', 'file_count': len(manifest['files']), 'directory': str(directory)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--output', type=Path)
    mode.add_argument('--verify', type=Path)
    parser.add_argument('--run-id')
    parser.add_argument('--feedback-followup', action='store_true', help='Author a two-project actual-feedback consumption window')
    parser.add_argument('--allow-saved-recovery', action='store_true')
    parser.add_argument('--query-saved-tender-on-error', action='store_true')
    parser.add_argument('--query-prior-submissions', action='store_true')
    parser.add_argument('--continue-unstarted-actions-on-error', action='store_true')
    parser.add_argument('--with-clarification-request', action='store_true')
    parser.add_argument('--with-clarification-response', action='store_true')
    parser.add_argument('--continue-clarification', action='store_true')
    parser.add_argument('--initial-screening-policies', type=Path, help='JSON organization-to-original-A01-policy map for the first project')
    parser.add_argument('--decline-after-prior-declines', type=int, help='Later explicit A01 policy uses actual own declined outcomes')
    parser.add_argument('--decline-after-prior-final-accounts', type=int)
    parser.add_argument('--decline-after-prior-payment-delays', type=int)
    parser.add_argument('--allow-followup-bids', action='store_true')
    args = parser.parse_args(argv)
    if args.verify:
        if args.run_id is not None or args.feedback_followup or args.allow_saved_recovery or args.query_saved_tender_on_error or args.query_prior_submissions or args.continue_unstarted_actions_on_error or args.with_clarification_request or args.with_clarification_response or args.continue_clarification or args.initial_screening_policies is not None or args.decline_after_prior_declines is not None or args.decline_after_prior_final_accounts is not None or args.decline_after_prior_payment_delays is not None or args.allow_followup_bids:
            parser.error('--verify does not accept generation options')
        result = verify_bundle(args.verify)
    else:
        if not args.run_id:
            parser.error('--output requires an explicit --run-id')
        if args.decline_after_prior_declines is not None and not args.feedback_followup:
            parser.error('--decline-after-prior-declines requires --feedback-followup')
        if args.decline_after_prior_final_accounts is not None and not args.feedback_followup:
            parser.error('--decline-after-prior-final-accounts requires --feedback-followup')
        if args.decline_after_prior_payment_delays is not None and not args.feedback_followup:
            parser.error('--decline-after-prior-payment-delays requires --feedback-followup')
        if args.allow_followup_bids and not args.feedback_followup:
            parser.error('--allow-followup-bids requires --feedback-followup')
        builder = build_feedback_bundle if args.feedback_followup else build_bundle
        result = builder(args.output, run_id=args.run_id,allow_saved_recovery=args.allow_saved_recovery,
            query_saved_tender_on_error=args.query_saved_tender_on_error,query_prior_submissions=args.query_prior_submissions,
            continue_unstarted_actions_on_error=args.continue_unstarted_actions_on_error,
            with_clarification_request=args.with_clarification_request,
            with_clarification_response=args.with_clarification_response,continue_clarification=args.continue_clarification,
            initial_screening_policies=json.loads(args.initial_screening_policies.read_text(encoding='utf-8-sig'))
                if args.initial_screening_policies is not None else None,
            **({'decline_after_prior_declines': args.decline_after_prior_declines,
                'decline_after_prior_final_accounts': args.decline_after_prior_final_accounts,
                'decline_after_prior_payment_delays': args.decline_after_prior_payment_delays,
                'allow_followup_bids': args.allow_followup_bids} if args.feedback_followup else {}))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
