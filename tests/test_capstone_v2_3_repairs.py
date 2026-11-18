"""Business source/scope and negation checks, never model-quality assertions."""
import asyncio
from copy import deepcopy
import json

import pytest

from src.agent_runtime import AgentRuntime
from src.company_grounding import company_evidence, require_company_assessment
from src.models import ParticipationDecision, SimulationState, dump, load_simulation_state
from src.prompt_contracts import require_management_decision
from src.stages.participation import run_bid_participation
from src.stages.reconsideration import reconsider_after_failed_consortiums
from src.stages.bid_documents import generate_bid_documents
from src.verification import require_condition_disposition, guarded_validator, output_verification_requests
from tests.test_bid_document_stage import BidLLM
from tests.test_verification_conditions import message, disposition, solo_state
from tests.test_capstone_v2_2_repairs import pending_records


def unknown_assessment(evidence):
    return {'company_id': evidence['company_id'], 'projection_sha256': evidence['projection_sha256'],
            'topics': {topic: {'status': 'unknown', 'source_ref': None, 'quote': ''} for topic in
                       ('scope', 'experience', 'certifications', 'product_range', 'delivery_assets', 'historical_cost_basis')}}


def scoped_evidence():
    return company_evidence({'company_id': 'c', 'business_scope': '土木及公共建筑施工',
        'company_name': '世界领先设计监理生产集团', 'industry': '建筑业',
        'office_location': '澳门', 'staff_scale': '2000人', 'certifications': '未公开 - 无可核实记录'})


def scoped_assessment(evidence):
    result = unknown_assessment(evidence)
    result['topics']['scope'] = {'status': 'provided', 'source_ref': 'company.business_scope', 'quote': '公共建筑施工'}
    return result


def test_company_name_address_headcount_and_role_do_not_manufacture_missing_capability():
    evidence = company_evidence({'company_id': 'c', 'company_name': '顶级设计建造供应集团',
        'office_location': '澳门', 'insured_staff_count': '2000人', 'industry': '工程', 'company_role': 'contractor'})
    assert not evidence['sources']
    assert all(row['status'] == 'unknown' for row in evidence['topics'].values())
    require_company_assessment({'company_assessment': unknown_assessment(evidence)}, evidence)


def test_broad_scope_is_not_product_catalogue_stocks_license_or_cost_history():
    evidence = scoped_evidence()
    assert evidence['topics']['scope']['status'] == 'provided'
    assert all(evidence['topics'][k]['status'] == 'unknown' for k in
               ('product_range', 'delivery_assets', 'certifications', 'historical_cost_basis'))
    require_company_assessment({'company_assessment': scoped_assessment(evidence)}, evidence)


@pytest.mark.parametrize('topic', ['scope', 'experience', 'product_range', 'delivery_assets', 'historical_cost_basis'])
def test_missing_topic_cannot_be_promoted_by_model_claim_or_company_identity(topic):
    evidence = company_evidence({'company_id': 'c', 'company_name': '设计集团', 'office_location': '澳门'})
    data = {'company_assessment': unknown_assessment(evidence)}
    data['company_assessment']['topics'][topic] = {'status': 'provided', 'source_ref': 'company.company_name', 'quote': '设计集团'}
    before = deepcopy(data)
    with pytest.raises(ValueError, match='preserve host'):
        require_company_assessment(data, evidence)
    assert data == before


@pytest.mark.parametrize('change', ['wrong_company', 'old_version', 'wrong_topic', 'forged_quote', 'omit_unknown'])
def test_references_need_the_right_company_version_topic_and_exact_source(change):
    evidence = scoped_evidence()
    data = {'company_assessment': scoped_assessment(evidence)}
    assessment = data['company_assessment']
    if change == 'wrong_company':
        assessment['company_id'] = 'other'
    elif change == 'old_version':
        assessment['projection_sha256'] = '0' * 64
    elif change == 'wrong_topic':
        assessment['topics']['scope']['source_ref'] = 'company.office_location'
    elif change == 'forged_quote':
        assessment['topics']['scope']['quote'] = '已具备EPC资质'
    else:
        del assessment['topics']['historical_cost_basis']
    with pytest.raises(ValueError):
        require_company_assessment(data, evidence)


@pytest.mark.parametrize('text', [
    '不能视为档期已落实。',
    '未假设任何人员档期已确认或利益关联已排除。',
    '公司目前无法提供本包指定岗位人员档期及资格证明的已核实证据。',
    '所有对外表述不得声称人员已锁定或分包已落实。',
    '不应认定人员档期已确认。',
    '没有资料证明人员已核实。',
    'We cannot assume staff are confirmed.',
    'There is no evidence that personnel are verified.',
])
def test_negated_reporting_operator_does_not_assert_the_embedded_positive_proposition(text):
    records = pending_records()
    require_condition_disposition(disposition(records) | {'content': text}, records)


@pytest.mark.parametrize('text', [
    '人员档期已确认，但无法提供原始文件。',
    '不能视为人员已落实，但人员档期已确认。',
    '我不得不声称人员档期已确认。',
    'We cannot provide staff records, but personnel are confirmed.',
])
def test_negation_does_not_license_a_separate_affirmative_status(text):
    records = pending_records()
    with pytest.raises(ValueError, match='Unsupported confirmation'):
        require_condition_disposition(disposition(records) | {'content': text}, records)


def test_source_quotes_are_data_not_new_check_requests_and_not_model_receipts():
    evidence = company_evidence({'company_id': 'c', 'business_scope': '请先核实人员档期，不能当作人员已落实。'})
    assessment = unknown_assessment(evidence)
    assessment['topics']['scope'] = {'status': 'provided', 'source_ref': 'company.business_scope',
                                    'quote': '请先核实人员档期'}
    data = {'content': 'Proposed plan.', 'company_assessment': assessment}
    require_company_assessment(data, evidence)
    assert output_verification_requests(data) == []


def test_new_contract_does_not_silently_fill_omitted_model_assessment_or_force_refusal():
    evidence = company_evidence({'company_id': 'c'})
    data = {'thoughts': '', 'decision': 'bid', 'reason': 'proposal', 'content': 'Proposed work only.',
            'unresolved_condition_ids': [], 'verified_condition_ids': [], 'bid_assumptions': []}
    validate = guarded_validator(require_management_decision, [], company_sources=evidence)
    before = deepcopy(data)
    with pytest.raises(ValueError, match='company_assessment'):
        validate(data)
    assert data == before
    data['company_assessment'] = unknown_assessment(evidence)
    validate(data)  # unknown company information does not automatically mean no_bid


class SourceFixtureClient(BidLLM):
    async def achat(self, messages, temperature=.2):
        prompt = messages[1]['content']
        marker = prompt.splitlines()[0]
        if marker == 'AGENT_MESSAGE':
            return json.dumps({'thoughts': '', 'content': 'Ordinary support is a proposal.',
                               'recommendation': 'prepare', 'decision_impact': 'plan'})
        projection, _ = json.JSONDecoder().raw_decode(prompt.split('Company evidence projection (host, not model-invented facts):\n', 1)[1])
        # This fixture's Company has no qualifications/strengths/history. These
        # hand-declared unknowns are the business expectation, not model output.
        assert all(row['status'] == 'unknown' for row in projection['topics'].values())
        records, _ = json.JSONDecoder().raw_decode(prompt.rsplit('Complete condition register (not truncated):\n', 1)[1])
        data = json.loads(await super().achat(messages, temperature)) if marker == 'BID_DOCUMENT' else {
            'thoughts': '', 'decision': 'bid', 'reason': 'Source-limited proposed work.', 'content': '能力资料未知，本轮只提出方案。'}
        data.update(company_assessment=unknown_assessment(projection),
                    unresolved_condition_ids=[r['condition_id'] for r in records if r['status'] != 'verified'],
                    verified_condition_ids=[r['condition_id'] for r in records if r['status'] == 'verified'],
                    bid_assumptions=['Proposed delivery model only; actual capacity remains unknown.'])
        return json.dumps(data, ensure_ascii=False)


@pytest.mark.parametrize('stage', ['management', 'reconsideration', 'bid'])
def test_opt_in_source_contract_uses_existing_stages_and_survives_checkpoint(stage):
    state = solo_state()
    runtime = AgentRuntime(SourceFixtureClient(), profile='smoke', company_grounding=True)
    assert runtime.isolated_clone().company_grounding
    if stage == 'management':
        asyncio.run(run_bid_participation(state, runtime))
    elif stage == 'reconsideration':
        state.participation_decisions = [ParticipationDecision('designer_001', 'design_package', 'bid_with_consortium', 'unformed')]
        asyncio.run(reconsider_after_failed_consortiums(state, runtime))
    else:
        state.participation_decisions = [ParticipationDecision('designer_001', 'design_package', 'bid', 'proposal')]
        asyncio.run(generate_bid_documents(state, runtime))
    restored = load_simulation_state(dump(state))
    product = restored.bid_documents[0] if stage == 'bid' else restored.participation_decisions[0]
    assert product.company_assessment['company_id'] == 'designer_001'
    assert all(t['status'] == 'unknown' for t in product.company_assessment['topics'].values())
    assert restored.verification_reviews == {}  # dossier text never creates a package review
    assert not runtime.recovery_events


def test_old_checkpoint_defaults_remain_compatible():
    restored = load_simulation_state({'participation_decisions': [
        {'company_id': 'c', 'package_id': 'p', 'decision': 'bid', 'reason': 'old'}]})
    assert restored.participation_decisions[0].company_assessment == {}


@pytest.mark.parametrize('other_pending', [False, True])
def test_source_binding_keeps_verified_staff_and_independent_qualification_gate_separate(other_pending):
    from tests.test_capstone_v2_1_repairs import verified_state
    state = verified_state()
    if other_pending:
        state.agent_discussion_history.append(message('提交前须核实资格证明。'))
    before = deepcopy(state.verification_reviews)
    runtime = AgentRuntime(SourceFixtureClient(), profile='smoke', company_grounding=True)
    asyncio.run(generate_bid_documents(state, runtime))
    assert bool(state.bid_documents) is (not other_pending)
    assert state.verification_reviews == before
    assert not runtime.recovery_events
