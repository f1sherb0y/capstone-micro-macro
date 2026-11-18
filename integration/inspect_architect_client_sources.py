"""Inspect preserved actual client sources, without replaying any business."""
import argparse
import hashlib
import json
from pathlib import Path
from integration.architect_client_sources import inspect_sources
from integration.contractor_tender_development import _write
from integration.verify_tender_closed_loop import ROOT,read,require,macro_hashes
from integration.verify_tender_basic import verify_history


def write_delivery(directory,checks):
    lines=['# GOAL 3C 客户关系来源实查记录','',
        '本次没有运行宏观或重新执行业务。读取并校验已保存的真实专业委任、原 A03 结果、原月度反馈和记忆，输出可复用的客户选择历史。',
        '状态：waiting_authorized_client_followup_sources；仍不计为微观接线覆盖。','',
        '| 机构 | 原月度轮次 | 实际原生事件 | 严格较早的本机构客户选择 | 微观覆盖 |','| --- | --- | --- | --- | --- |']
    for row in checks['native_only_monthly_observations']:
        prior=', '.join(s['team_event_id']+' / '+s['client_organization_id'] for s in row['strictly_prior_own_client_selections']) or '无；不能借用未来或另一机构选择'
        lines.append(f"| {row['organization_id']} | {row['tick']} | {row['event_id']} | {prior} | 否 |")
    lines+=['',
        '共核对两项真实 A03 选择确认、两项原生客户关系月度反馈。只有第二轮 professional-architect 的选择历史来自较早的同机构真实事件；另一机构第一轮不能使用第二轮才发生的选择。',
        '原 A01 express_interest 明确不发送消息；原 A03 仍为 selected，service_relationship_ref 和 reservation_ref 为空。原生月度事件存在，但其判断来源为 native_macro，没有微观任务映射。',
        '缺口：当前客户跟进任务、范围、目的、收件权限；适当原微观判断；受支持的实际联系交付或内部关系更新及真实反馈；同一反馈的后轮微观消费者。独立授权的联系历史可以作为来源，不要求每种非正式联系都先有完整服务合同。',
        '通用会话/消息 API 的存在不能证明适用于客户维护。现有项目会话的真实参与者和业务目的不能挪用；本次没有新建会话或发送消息。','',
        '复现（输出目录须全新）：','```powershell',"& '.venv-integration/Scripts/python.exe' -m integration.inspect_architect_client_sources `",'  --config config/architect_client_sources.json `','  --output output/integration/goal3c_client_sources_my_run','```','',
        '只读核验：','```powershell',f"& '.venv-integration/Scripts/python.exe' -m integration.inspect_architect_client_sources --check-only --output '{directory.as_posix()}'",'```','',
        '两类状态分开：文件和来源核验通过；客户维护业务仍等待，未接通。月度累计仍为 18/32，14 项月度动作及 50 项来源/接口阻塞，GOAL 3 未完成。']
    (directory/'RUN_RECORD.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    (directory/'run.ps1').write_text("param([Parameter(Mandatory=$true)][string]$OutputDirectory)\n& '.venv-integration/Scripts/python.exe' -m integration.inspect_architect_client_sources --config config/architect_client_sources.json --output $OutputDirectory\n",encoding='utf8')
    names=['integration/architect_client_sources.py','integration/inspect_architect_client_sources.py','tests/test_architect_client_sources.py',
        'config/architect_client_sources.json','config/gba_v1_monthly_business_wiring.json','config/gba_v1_business_wiring.json',
        'docs/建筑师客户关系来源等待.md','docs/宏观动作接线清单.md']
    _write(directory,'artifact-manifest.json',{'schema_version':'architect-client-source-artifacts.v1',
        'files':{p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file() and p.name!='artifact-manifest.json'},
        'implementations':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}})


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--config',type=Path,default=ROOT/'config/architect_client_sources.json');p.add_argument('--check-only',action='store_true')
    a=p.parse_args(argv);directory=a.output.resolve()
    if a.check_only:
        verify_history(directory);config=read(directory/'source-config.json')
    else:
        directory.mkdir(parents=True,exist_ok=False);config=read(a.config);_write(directory,'source-config.json',config);_write(directory,'macro-before.json',macro_hashes())
    checks=inspect_sources(config);require(checks['macro']==read(directory/'macro-before.json'),'Frozen macro source changed')
    if a.check_only:require(checks==read(directory/'checks.json'),'Saved source findings differ from preserved actual evidence')
    else:_write(directory,'checks.json',checks);write_delivery(directory,checks)
    print(json.dumps({'verification':'passed','business_status':checks['status'],'counts_as_micro_coverage':False,'output':str(directory)}))


if __name__=='__main__':main()
