"""Predeclared role/context counterexamples, all synthetic and offline."""
import asyncio
from copy import deepcopy
import json
import pytest
from src.company_narrative import review_company_narrative
from src.company_grounding import company_evidence
from src.task_role_contract import require_task_role,TaskRoleIssue
from src.agent_runtime import AgentRuntime
from src.models import ParticipationDecision,dump,load_simulation_state
from src.stages.participation import run_bid_participation
from src.stages.reconsideration import reconsider_after_failed_consortiums
from src.stages.bid_documents import generate_bid_documents
from tests.test_capstone_v2_4_repairs import no_provider,SourceFixtureClient
from tests.test_verification_conditions import solo_state
from tests.test_capstone_v2_2_repairs import pending_records
from tests.test_verification_conditions import disposition
from src.verification import require_condition_disposition

CASES=[
 ('no-proof',{},'没有可引用的来源证明我们具备该角色的能力。','limited_checks_passed'),
 ('question',{},'是否与公司既有业务方向相符，尚待核实。','limited_checks_passed'),
 ('question-after-company',{},'公司是否具备监管服务能力仍待核实。','limited_checks_passed'),
 ('missing-records',{},'公司档案中业务范围与人员经验均无可用记录。','limited_checks_passed'),
 ('not-described',{},'公司档案未载明业务范围。','limited_checks_passed'),
 ('negative-then-positive',{},'没有证据证明公司具备能力，但本公司具备实际交付能力。','blocked'),
 ('question-then-positive',{},'是否具备能力仍待核实，但公司具备实际资源。','blocked'),
 ('coordinated-positive',{},'是否符合业务方向尚待核实，且公司有能力独立承接。','blocked'),
 ('scope-paraphrase',{'business_scope':'建筑设计与工程监理'},'与本公司建筑设计业务方向相符。','limited_checks_passed'),
 ('scope-conflicting-direction',{'business_scope':'公共工程施工'},'与本公司建筑设计业务方向相符。','review_required'),
 ('scope-not-capacity',{'business_scope':'建筑设计'},'公司有能力独立承担所有EPC施工。','review_required'),
 ('direction-foundation',{'business_scope':'工程监理'},'公司具备作为单一责任投标人的角色基础。','limited_checks_passed'),
 ('unknown-foundation',{},'公司具备作为单一责任投标人的角色基础。','blocked'),
 ('scope-not-stock',{'business_scope':'建筑材料销售'},'拟利用公司既有仓储网络。','blocked'),
 ('negative-absence',{},'公司没有本地团队。','blocked'),
 ('double-negative',{},'并非没有证据证明公司具备管理能力。','blocked'),
 ('unrelated-scope',{'business_scope':'餐饮服务'},'公司具备作为单一责任投标人的角色基础。','review_required'),
]
@pytest.mark.parametrize('ident,fields,text,expected',CASES,ids=[x[0] for x in CASES])
def test_context_and_source_properties(ident,fields,text,expected):
    e=company_evidence({'company_id':'SYNTHETIC-c',**fields});data={'content':text,'task_role':'supervisor'}
    before=deepcopy(data)
    r=review_company_narrative(data,e,contextual=True)
    assert r['status']==expected and data==before
    assert r['original_outward']==r['adopted_outward']

@pytest.mark.parametrize('role,text,bad',[
 ('supervisor','公司作为单一责任总承包主体承担施工。',True),
 ('supervisor','拟由本公司担任施工总包。',True),
 ('designer','本包要求投标方承担设计与施工的整体责任。',True),
 ('designer','施工与采购由其他EPC牵头方负责，公司拟主导设计。',False),
 ('supervisor','监理将审查总承包商提交的记录。',False),
 ('contractor','公司拟作为总承包商牵头施工。',False),
 ('supplier','公司拟供应材料，施工由承建商负责。',False),
 ('supervisor','公司不担任施工总包。',False),
 ('supervisor','公司不承担监理而承担施工总包责任。',True),
])
def test_own_role_not_project_title_or_other_actor(role,text,bad):
    data={'task_role':role,'content':text}
    if bad:
        with pytest.raises(TaskRoleIssue):require_task_role(data,role)
    else:
        assert require_task_role(data,role)['task_role']==role

def test_missing_role_not_filled_or_treated_as_source_capability():
    data={'content':'拟议方案'};before=deepcopy(data)
    with pytest.raises(TaskRoleIssue):require_task_role(data,'supervisor')
    assert data==before
    assert company_evidence({'company_id':'SYNTHETIC-c','company_role':'supervisor'})['topics']['scope']['status']=='unknown'

@pytest.mark.parametrize('text,bad',[
 ('人员档期、认证及交付资源均无已确认资料。',False),
 ('本方案为拟议计划。产品拟由经审核的外部供货渠道承担。渠道审核尚未完成。',False),
 ('本方案为拟议计划。产品已经由经审核的外部供货渠道承担。',True),
 ('本方案为拟议计划。但供应商已通过审核。',True),
])
def test_documentary_absence_and_future_qualified_actor_are_not_receipts(text,bad):
    records=pending_records();data=disposition(records)|{'content':text}
    if bad:
        with pytest.raises(ValueError):require_condition_disposition(data,records)
    else:require_condition_disposition(data,records)

class RoleClient(SourceFixtureClient):
    async def achat(self,messages,temperature=.2):
        raw=await super().achat(messages,temperature)
        if messages[1]['content'].startswith('AGENT_MESSAGE'):return raw
        assert 'CURRENT TASK ROLE CONTRACT' in messages[1]['content']
        data=json.loads(raw);data['task_role']='designer'
        return json.dumps(data,ensure_ascii=False)

@pytest.mark.parametrize('stage',['management','reconsideration','bid'])
def test_role_reaches_actual_stage_and_checkpoint(stage):
    s=solo_state();rt=AgentRuntime(RoleClient(),profile='smoke',company_grounding=True,company_narrative_grounding=True,task_role_grounding=True)
    assert rt.isolated_clone().task_role_grounding
    if stage=='management':asyncio.run(run_bid_participation(s,rt))
    elif stage=='reconsideration':
        s.participation_decisions=[ParticipationDecision('designer_001','design_package','bid_with_consortium','unformed')]
        asyncio.run(reconsider_after_failed_consortiums(s,rt))
    else:
        s.participation_decisions=[ParticipationDecision('designer_001','design_package','bid','proposal')]
        asyncio.run(generate_bid_documents(s,rt))
    restored=load_simulation_state(dump(s));p=restored.bid_documents[0] if stage=='bid' else restored.participation_decisions[0]
    assert p.task_role=='designer'
    assert p.company_narrative_review['task_role_review']['task_role']=='designer'
    assert not restored.verification_reviews and not rt.recovery_events
