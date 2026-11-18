"""Build an explicit synthetic native financing window for micro-source wiring.

All decisions in this preparatory bundle are original native behavior. It is
not evidence of BANK-A02/A03/A04 or OWN-A05 micro execution.
"""
import argparse
from pathlib import Path

from integration.bootstrap import enable_gba_imports
from integration.contractor_tender_development import _write, _write_launch_files
from integration.module_host import GbaModuleHostConfiguration
from integration.native_routes import NativeRouteSettings


def build_bundle(directory, *, run_id):
    enable_gba_imports()
    from gba_construction_sim.backend.models.simulation import SimulationCreateRequest

    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    roles = {'finance-owner-a': 'Owner', 'finance-owner-b': 'Owner', 'finance-bank-a': 'Bank',
             'finance-bank-b': 'Bank', **{'finance-' + role.lower(): role
             for role in ('Architect', 'Engineer', 'QS', 'Government', 'Contractor', 'Supplier')}}
    agents = []
    for organization, role in roles.items():
        agents.append({'agent_id': organization, 'name': organization, 'role': role,
            'region': 'Hong Kong', 'enterprise_type': 'explicit_synthetic', 'total_resource_capacity': 10,
            'financial_capacity': 0 if organization == 'finance-bank-b' else 1,
            'risk_preference': 0 if organization == 'finance-bank-b' else 0.5,
            'payment_reliability': 1, 'decision_speed': 1, 'management_capability': 1})
    # The original 'explicit' mode forbids generation. Its documented supplied
    # agents path with source='default' permits it; all support roles are supplied
    # so the native support merger adds no unconfigured identities.
    request = SimulationCreateRequest.model_validate({'agent_source': 'default', 'agents': agents,
        'initial_projects': [], 'enable_project_generation': True, 'use_prior_network_edges': False,
        'target_project_count': 2, 'max_active_projects': 2, 'ticks': 1, 'random_seed': 42})
    settings = NativeRouteSettings.model_validate({'run_id': run_id, 'native_project_financing_scope': True,
        'native_financing_proposal_transport': True,
        'native_proposals': [{'role': role, 'operation': 'decide_monthly_operation'} for role in sorted(set(roles.values()))]
            + [{'role': 'Owner', 'operation': 'evaluate_project_opportunity'},
               {'role': 'Bank', 'operation': 'consider_financing'}, {'role': 'Owner', 'operation': 'select_financing_offer'}],
        'native_decisions': [{'role': role, 'decision_type': 'monthly_enterprise_operation'} for role in sorted(set(roles.values()))]
            + [{'role': 'Owner', 'decision_type': 'owner_project_opportunity'},
               {'role': 'Owner', 'decision_type': 'owner_project_initiation'},
               {'role': 'Bank', 'decision_type': 'bank_project_financing'},
               {'role': 'Owner', 'decision_type': 'owner_financing_selection'}]})
    host = GbaModuleHostConfiguration.model_validate({'schema_version': 'gba-module-host-config.v1',
        'host_id': run_id, 'version': '1', 'settings': settings.model_dump(mode='json')})
    _write(directory, 'macro-request.json', request.model_dump(mode='json'))
    _write(directory, 'native-host.json', host.model_dump(mode='json'))
    _write(directory, 'assembly-host.json', {'schema_version': 'gba-module-host-config.v1',
        'host_id': run_id, 'version': '1', 'settings': {}})
    _write_launch_files(directory, assembly_hook='integration.native_routes:configure_assembly',
        allow_native_project_generation=True, readme_override="""# 原生融资来源与传输开发窗口

运行 `& './run.ps1'`。两个业主、两个银行及其余六角色，输入均为明确合成假设。
原宏观机会生成器产生项目，原银行分别判断融资，原业主选择融资，正式状态与事件由宏观创建。
银行和业主最终确认明确读取同一原生提案，保留原字段和候选范围；没有第二次商业选择。
技术任务按原生机会或正在创建的项目区分，传输请求 ID 保持原值，输入变更继续拒绝。
缺少唯一的实际当前项目时停止关联，不按金额猜测项目，也不通过补写正式状态修复。

本窗口只核实原生融资接口、关联和来源，不运行微观 BANK-A02/A03/A04 或 OWN-A05，不能计为微观完成。
宏观批准融资/选中银行不等于详细合同、授信安排、提款、现金到账或实际付款。
后续继续接现有微观 worker 与实际反馈消费；不调用模型，不修改宏观源码。
""")
    return {'status': 'synthetic_native_financing_bundle_unverified', 'directory': str(directory), 'run_id': run_id}


def main(argv=None):
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args(argv)
    print(json.dumps(build_bundle(args.output, run_id=args.run_id)))


if __name__ == '__main__':
    main()
