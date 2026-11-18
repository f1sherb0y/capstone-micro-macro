"""Scoped claim/condition regressions with deterministic, synthetic responses."""
import asyncio
from copy import deepcopy
import json

import pytest

from src.agent_runtime import AgentRuntime
from src.models import SimulationState, ParticipationDecision, dump, load_simulation_state
from src.stages.participation import run_bid_participation
from src.stages.reconsideration import reconsider_after_failed_consortiums
from src.stages.bid_documents import generate_bid_documents
from src.verification import conditions, record_review, require_condition_disposition, output_verification_requests
from tests.test_verification_conditions import message, solo_state, disposition
from tests.test_bid_document_stage import BidLLM


def pending_records():
    return conditions(SimulationState(agent_discussion_history=[message()]), 'designer_001', 'design_package')


@pytest.mark.parametrize('text', [
    '公司118人为总量，不代表本包驻场人员已落实。',
    '本决定为意向，不构成对任何外部资源、资质或人员已落实的确认。',
    '不构成对任何伙伴资质、资源到位或清单完整性的已核实结论。',
    '团队可用性摘要只能写已核实的人员安排。',
    '不得写人员已落实。',
    '并非人员已确认。',
    'This does not mean staff are confirmed.',
    'Only write personnel availability is confirmed when supported by a reviewed source.',
    '须采用经我方审核的供应商；当前来源尚待核实。',
    '拟采用经我司审核的合格外部供应商，尚未取得承诺。',
])
def test_scoped_disclosures_and_normative_instructions_remain_allowed(text):
    records = pending_records()
    require_condition_disposition(disposition(records) | {'content': text}, records)


@pytest.mark.parametrize('text', [
    '人员可用性已核实，将编制文件。',
    '不代表人员已落实，但人员档期已确认。',
    '人员尚未确认，然而关键岗位人员档期已初步确认。',
    '外部设备由经我司审核的合格外部供应商提供。',
    '我方與承包商無隸屬或利益關係。',
    'Our company has no conflict of interest.',
])
def test_actual_unsupported_claims_still_fail(text):
    records = pending_records()
    with pytest.raises(ValueError, match='Unsupported confirmation'):
        require_condition_disposition(disposition(records) | {'content': text}, records)


def test_assertion_in_assumptions_and_cost_basis_is_not_hidden_from_guard():
    records = pending_records()
    for extra in [{'bid_assumptions': ['人员档期已确认']},
                  {'quotation_breakdown': [{'item': 'support', 'amount': 100, 'basis': '经我方审核的供应商供货'}]}]:
        data = disposition(records) | extra
        before = deepcopy(data)
        with pytest.raises(ValueError, match='Unsupported confirmation'):
            require_condition_disposition(data, records)
        assert data == before


@pytest.mark.parametrize('question,text', [
    ('本包供应商渠道审核是否通过', '设备由经我方审核的供应商供货。'),
    ('我方与承包商是否存在利益关联', '我方与承包商无利益关联。'),
])
def test_actual_scoped_review_can_support_the_bounded_claim(question, text):
    state = SimulationState(agent_discussion_history=[message('Synthetic source review.', verification_requests=[
        {'question': question, 'required_before_submission': False}])])
    key = conditions(state, 'designer_001', 'design_package')[0]['condition_id']
    record_review(state, 'designer_001', 'design_package', key, source_ref='fixture:review',
        source_text='SYNTHETIC: This precise question passed operator review inside this fictional task.',
        reviewer='synthetic:operator', status='verified')
    records = conditions(state, 'designer_001', 'design_package')
    data = disposition(records) | {'content': text, 'verified_condition_ids': [key]}
    require_condition_disposition(data, records)


def test_contradictory_blanket_boundary_is_rejected_but_distinct_optional_work_is_allowed():
    records = pending_records()
    with pytest.raises(ValueError, match='Conflicting submission boundary'):
        require_condition_disposition(disposition(records) | {
            'content': '所有核查事项在提交前完成，不设为提交前置条件。'}, records)
    require_condition_disposition(disposition(records) | {
        'content': '资格核查为提交前硬前提。普通支持计划不作为提交前置条件。'}, records)


class FinalConditionsClient(BidLLM):
    def __init__(self, *, hard=True, prose_only=False):
        super().__init__()
        self.hard = hard
        self.prose_only = prose_only
        self.final_calls = 0

    async def achat(self, messages, temperature=.2):
        marker = messages[1]['content'].splitlines()[0]
        if marker == 'AGENT_MESSAGE':
            return json.dumps({'thoughts': '', 'content': '拟用普通专业支持。',
                               'recommendation': 'conditional intention', 'decision_impact': 'plan'})
        self.final_calls += 1
        if marker == 'BID_DOCUMENT':
            data = json.loads(await super().achat(messages, temperature))
        else:
            data = {'thoughts': '', 'decision': 'bid', 'reason': 'conditional intention', 'content': '拟参与本包。'}
        data.update(unresolved_condition_ids=[], verified_condition_ids=[],
                    bid_assumptions=['人员安排尚待核实，普通支持为计划。'])
        if self.prose_only:
            # The condition exists only in reason, not in the saved content.
            data['reason'] = '须在提交前完成关键岗位档期核实；未完成前不提交。'
        else:
            data['verification_requests'] = [{'question': '本包关键岗位档期是否可用',
                                               'required_before_submission': self.hard}]
        return json.dumps(data, ensure_ascii=False)


@pytest.mark.parametrize('stage,prose_only', [('management', False), ('management', True), ('reconsideration', False)])
def test_final_only_prerequisite_survives_checkpoint_and_blocks_next_stage(stage, prose_only):
    state = solo_state()
    client = FinalConditionsClient(prose_only=prose_only)
    runtime = AgentRuntime(client, profile='smoke')
    if stage == 'management':
        asyncio.run(run_bid_participation(state, runtime))
    else:
        state.participation_decisions = [ParticipationDecision('designer_001', 'design_package', 'bid_with_consortium', 'unformed')]
        asyncio.run(reconsider_after_failed_consortiums(state, runtime))
    restored = load_simulation_state(dump(state))
    rs = conditions(restored, 'designer_001', 'design_package')
    assert rs and any(r['required_before_submission'] for r in rs)
    assert set(r['condition_id'] for r in rs) == set(restored.participation_decisions[0].unresolved_condition_ids)
    calls = client.final_calls
    asyncio.run(generate_bid_documents(restored, runtime))
    assert not restored.bid_documents and client.final_calls == calls
    assert any(e['event_type'] == 'bid_submission_pending_verification' for e in restored.tender_process_log)


@pytest.mark.parametrize('hard', [True, False])
def test_new_final_bid_request_causes_business_wait_only_when_explicitly_hard(hard):
    state = solo_state()
    state.participation_decisions = [ParticipationDecision('designer_001', 'design_package', 'bid', 'intent')]
    client = FinalConditionsClient(hard=hard)
    runtime = AgentRuntime(client, profile='smoke')
    asyncio.run(generate_bid_documents(state, runtime))
    rs = conditions(state, 'designer_001', 'design_package')
    assert rs and client.final_calls == 1  # business waiting is not a schema retry
    assert all(r['status'] == 'requested' and r['evidence'] is None for r in rs)
    assert bool(state.bid_documents) is (not hard)
    if not hard:
        assert set(state.bid_documents[0].unresolved_condition_ids) == {r['condition_id'] for r in rs}
    assert not runtime.recovery_events


def test_record_order_and_ordinary_wording_do_not_change_source_boundary():
    records = pending_records()
    for text in ['普通顾问支持为拟采用计划。', '拟用普通顾问支持；公司保持单一责任。']:
        data = disposition(records) | {'content': text}
        require_condition_disposition(data, records)
        require_condition_disposition(data, list(reversed(records)))
    # Missing or received-only evidence cannot authorize a confirmation.
    for status in ['requested', 'received', 'rejected']:
        changed = deepcopy(records)
        changed[0]['status'] = status
        with pytest.raises(ValueError, match='Unsupported confirmation'):
            require_condition_disposition(disposition(changed) | {'content': '人员可用性已核实'}, changed)


def test_negated_request_is_not_persisted_as_a_fresh_unresolved_check():
    assert output_verification_requests({'content': '本包排期已核查，无须再次核实人员档期。'}) == []
    assert output_verification_requests({'content': '不需要再次确认人员档期。'}) == []
    # A later independent request is still captured.
    requests = output_verification_requests({'content': '无须再次核实排期。请商务部核实资格证明。'})
    assert requests and all('资格证明' in r['question'] for r in requests)
