"""Meaningful no-network regressions for verified status and tender arithmetic."""
import asyncio
from copy import deepcopy
import json

import pytest

from src.agent_runtime import AgentRuntime
from src.models import SimulationState, ParticipationDecision
from src.prompt_contracts import require_bid_document_shape
from src.stages.bid_documents import _require_bid_response, generate_bid_documents
from src.verification import conditions, record_review, evidence_context, require_condition_disposition
from tests.test_bid_document_stage import BidLLM
from tests.test_verification_conditions import message, solo_state


def verified_state():
    state=solo_state()
    state.agent_discussion_history=[message('本包指定岗位人员档期是否可用',
        verification_requests=[{'question':'本包指定岗位人员档期是否可用','required_before_submission':True}])]
    key=conditions(state,'designer_001','design_package')[0]['condition_id']
    record_review(state,'designer_001','design_package',key,source_ref='fixture:v2.1:hr-available',
        source_text='SYNTHETIC: Within this fictional task, the specified personnel are available for this package period and that condition has passed review. This makes no statement about any real company.',
        reviewer='synthetic:fixture-operator',status='verified')
    state.participation_decisions=[ParticipationDecision('designer_001','design_package','bid','conditional')]
    return state


def output(records,content):
    return dict(thoughts='',decision='bid',reason='conditional',content=content,
        unresolved_condition_ids=[r['condition_id'] for r in records if r['status']!='verified'],
        verified_condition_ids=[r['condition_id'] for r in records if r['status']=='verified'],bid_assumptions=[])


@pytest.mark.parametrize('text',[
    '按条件投标处理：在提交前确认指定岗位排期。',
    '投标前提是本包指定岗位人员档期核验闭环；该条件标记为已验证，排期核验未闭环前不提交。',
    '提交前必须完成指定岗位档期核实，未落实前不提交。',
    'We must verify personnel availability before submission.',
])
def test_known_reopening_of_a_scoped_verified_condition_is_rejected(text):
    state=verified_state();records=conditions(state,'designer_001','design_package')
    with pytest.raises(ValueError,match='Verified condition reopened'):
        require_condition_disposition(output(records,text),records)
    assert state.verification_reviews[records[0]['condition_id']]['status']=='verified'


@pytest.mark.parametrize('text',[
    '本包岗位排期已核查，在该虚构任务范围内继续，不代表真实企业可用性。',
    '无需提交前重新核实指定岗位排期；按已核查范围继续。',
    '提交前已经确认人员排期。',
    '若人员发生变更，提交前须重新核实新人员档期。',
    '人员档期已核查，提交前须核实资质证明。',
    '团队安排按已核查排期执行，报价依据仍待补充。',
])
def test_valid_closure_and_distinct_checks_are_not_overblocked(text):
    records=conditions(verified_state(),'designer_001','design_package')
    require_condition_disposition(output(records,text),records,submission=True)


def test_status_summary_excludes_verified_prerequisite_but_retains_pending_one():
    state=verified_state()
    state.agent_discussion_history.append(message('提交前须核实资格证明。'))
    records=conditions(state,'designer_001','design_package')
    context=evidence_context(records)
    summary,_=json.JSONDecoder().raw_decode(context.split('Host-derived current disposition (IDs, not new evidence):\n')[1])
    assert summary['active_submission_prerequisite_ids']==[r['condition_id'] for r in records if r['status']!='verified']
    assert len(summary['verified_condition_ids'])==1
    data=output(records,'岗位排期已核查，提交前须核实资格证明。')
    data['bid_assumptions']=['资格证明待核实']
    require_condition_disposition(data,records)
    with pytest.raises(ValueError,match='Submission blocked'):
        require_condition_disposition(data,records,submission=True)


def test_exact_verified_question_cannot_be_rerequested_as_a_hard_prerequisite():
    records=conditions(verified_state(),'designer_001','design_package')
    data=output(records,'本包排期在虚构任务内已核查。')
    data['verification_requests']=[{'question':records[0]['question'],'required_before_submission':True}]
    with pytest.raises(ValueError,match='Verified condition reopened'):
        require_condition_disposition(data,records)
    data['verification_requests']=[];data['verified_condition_ids']=[]
    with pytest.raises(ValueError,match='Carry ALL application-verified'):
        require_condition_disposition(data,records)


def bid_payload():
    return json.loads(asyncio.run(BidLLM().achat([{}, {'content':'BID_DOCUMENT'}])))


def test_bad_total_is_rejected_in_response_validator_without_mutating_any_amount():
    data=bid_payload();data['quotation']=950000;before=deepcopy(data)
    with pytest.raises(ValueError,match='quotation minus breakdown = -50000'):
        _require_bid_response(data)
    assert data==before


@pytest.mark.parametrize('field,value',[('quotation',float('nan')),('quotation',float('inf')),
    ('quotation',True),('quotation','1000000'),('amount',float('-inf')),('amount',False)])
def test_non_finite_or_non_numeric_money_is_rejected(field,value):
    data=bid_payload()
    if field=='amount':data['quotation_breakdown'][0]['amount']=value
    else:data[field]=value
    with pytest.raises((ValueError,TypeError),match='finite JSON number'):
        require_bid_document_shape(data)


def test_decimal_subtotal_and_explicit_discount_remain_valid():
    data=bid_payload();data['quotation']=100.3
    data['quotation_breakdown']=[{'item':'base','amount':101,'basis':'declared estimate'},
        {'item':'discount','amount':-.7,'basis':'explicit proposed discount'}]
    require_bid_document_shape(data)


class FixtureClosureClient(BidLLM):
    """A deterministic valid response; not evidence that an LLM obeys the prompt."""
    def __init__(self):super().__init__();self.final_calls=0
    async def achat(self,messages,temperature=.2):
        data=json.loads(await super().achat(messages,temperature))
        if messages[1]['content'].startswith('BID_DOCUMENT'):
            self.final_calls+=1
            records,_=json.JSONDecoder().raw_decode(messages[1]['content'].rsplit('Complete condition register (not truncated):\n',1)[1])
            data.update({k:v for k,v in output(records,'本包指定岗位排期已核查，无需再次核查。').items()
                         if k in {'unresolved_condition_ids','verified_condition_ids','bid_assumptions'}})
        return json.dumps(data,ensure_ascii=False)


def test_real_bid_stage_can_continue_after_verified_fixture_without_new_receipt():
    state=verified_state();before=deepcopy(state.verification_reviews);client=FixtureClosureClient()
    asyncio.run(generate_bid_documents(state,AgentRuntime(client,profile='smoke')))
    assert len(state.bid_documents)==1 and client.final_calls==1
    assert state.bid_documents[0].verified_condition_ids==list(before)
    assert state.verification_reviews==before


class CorrectedEstimateClient(BidLLM):
    def __init__(self):super().__init__();self.outputs=[]
    async def achat(self,messages,temperature=.2):
        text=await super().achat(messages,temperature)
        if messages[1]['content'].startswith('BID_DOCUMENT'):
            data=json.loads(text)
            # Both calls propose the same total; only the second model fixture
            # returns a consistent bucket. The host must not make that edit.
            data['quotation']=950000
            if len(messages)>2 and 'SCHEMA_REPAIR_REQUIRED' in messages[-1]['content']:
                data['quotation_breakdown'][0]['amount']=950000
            self.outputs.append(deepcopy(data));return json.dumps(data)
        return text


def test_corrected_response_uses_existing_audited_retry_not_silent_normalization():
    state=solo_state();state.participation_decisions=[ParticipationDecision('designer_001','design_package','bid','plan')]
    client=CorrectedEstimateClient();runtime=AgentRuntime(client,profile='smoke')
    asyncio.run(generate_bid_documents(state,runtime))
    assert len(client.outputs)==2 and len(state.bid_documents)==1
    assert client.outputs[0]['quotation_breakdown'][0]['amount']==1000000
    assert state.bid_documents[0].quotation_breakdown[0]['amount']==950000
    assert any(e['kind']=='response_contract_retry' for e in runtime.recovery_events)
    assert not any(e['kind']=='response_normalized' for e in runtime.recovery_events)
