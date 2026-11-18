"""Execute one isolated zero-network Capstone V0/V1 batch; prepare V2 separately."""
from __future__ import annotations
import argparse
import asyncio
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import socket
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from src.run_audit import atomic_write_json, utc_now
from src.models import ParticipationDecision, SimulationState, dump, load_simulation_state
from src.agent_runtime import AgentRuntime
from src.verification import conditions, record_review, require_condition_disposition
from src.stages.bid_documents import generate_bid_documents
from tests.test_bid_document_stage import _state, BidLLM
from tests.test_verification_conditions import message
from capstone_core_cases_20261108 import prepare_task, expected, ADAPTERS

BASE = ROOT / 'Capstone报告/验证体系'
OUT = BASE / '实验/2026-11-08_微观验证核心批次'
DRAFT = BASE / '论文图表/微观验证证据图册/24题形式验证草案.json'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    atomic_write_json(path, data)


def serial(value):
    if hasattr(value, 'model_dump'):
        return value.model_dump(mode='json')
    if hasattr(value, '__dataclass_fields__'):
        return asdict(value)
    return value


class NoProviderNetwork:
    def __init__(self):
        self.attempts = 0
    def block(self, *args, **kwargs):
        self.attempts += 1
        raise RuntimeError('This batch has a zero network/provider budget')


class FixtureBidClient(BidLLM):
    """Deterministic responses used solely to test downstream condition handling."""
    calls = 0
    async def achat(self, messages, temperature=0.2):
        self.calls += 1
        text = await super().achat(messages, temperature)
        data = json.loads(text)
        prompt = messages[1]['content']
        if prompt.startswith('BID_DOCUMENT'):
            records, _ = json.JSONDecoder().raw_decode(prompt.rsplit('Complete condition register (not truncated):\n', 1)[1])
            data.update(unresolved_condition_ids=[r['condition_id'] for r in records if r['status'] != 'verified'],
                        verified_condition_ids=[r['condition_id'] for r in records if r['status'] == 'verified'],
                        bid_assumptions=['Synthetic planned scope; no real external resources are asserted.'])
        return json.dumps(data)


def condition_state(content=None):
    state = _state()
    state.companies = state.companies[:1]
    state.consortiums = []
    state.participation_decisions = [ParticipationDecision('designer_001', 'design_package', 'bid', 'synthetic conditional intent')]
    if content is None:
        state.agent_discussion_history = [message('Synthetic fixture proposes two tracked conditions.', verification_requests=[
            {'question': '人员档期是否满足本包', 'required_before_submission': True},
            {'question': '资格资料是否获接受', 'required_before_submission': True}])]
    else:
        state.agent_discussion_history = [message(content)]
    return state


def scoped(state):
    return conditions(state, 'designer_001', 'design_package')


def v0(attempt_dir, async_runner):
    # Predeclared outcomes include continuation; "block everything" cannot pass.
    plan = [
        ('V0-01-no-source', 'defer', {}), ('V0-02-received-only', 'defer', {'hr': 'received'}),
        ('V0-03-rejected', 'defer', {'hr': 'rejected'}),
        ('V0-04-wrong-company', 'scope_error_defer', {'wrong_company': True}),
        ('V0-05-wrong-package', 'scope_error_defer', {'wrong_package': True}),
        ('V0-06-partial-verified', 'defer', {'hr': 'verified'}),
        ('V0-07-all-verified', 'submit_fixture', {'hr': 'verified', 'qualification': 'verified'}),
        ('V0-08-new-prerequisite', 'defer', {'content': '提交前须完成关键人员档期确认。'}),
        ('V0-09-ordinary-plan', 'submit_fixture', {'content': '拟使用普通分包支持，投标人为单一责任主体。'}),
    ]
    save(attempt_dir / 'v0/expected.json', {'origin': 'synthetic; not actual firm resources or regulatory decisions',
        'cases': [{'task_id': i, 'expected': e, 'input_changes': c} for i, e, c in plan]})
    rows = []
    for task_id, expectation, changes in plan:
        folder = attempt_dir / 'v0' / task_id
        state = condition_state(changes.get('content'))
        save(folder / 'input.json', dump(state))
        initial = scoped(state)
        errors, steps = [], []
        for marker, status in [('hr', changes.get('hr')), ('qualification', changes.get('qualification'))]:
            if status:
                target = next(r for r in initial if ('人员' if marker == 'hr' else '资格') in r['question'])
                record_review(state, 'designer_001', 'design_package', target['condition_id'],
                              source_ref=f'fixture:{task_id}:{marker}', source_text=f'SYNTHETIC REVIEW SOURCE: {marker}; outcome={status}',
                              reviewer='synthetic:operator-reviewer', status=status)
                steps.append({'reviewed_condition_id': target['condition_id'], 'source_ref': f'fixture:{task_id}:{marker}',
                              'states_after_review': scoped(state)})
        for name, company_id, package_id in [('wrong_company', 'other-company', 'design_package'),
                                             ('wrong_package', 'designer_001', 'other-package')]:
            if changes.get(name):
                try:
                    record_review(state, company_id, package_id, initial[0]['condition_id'], source_ref='fixture:wrong-scope',
                                  source_text='SYNTHETIC source for a different scope', reviewer='fixture:operator', status='verified')
                except ValueError as exc:
                    errors.append({'type': type(exc).__name__, 'message': str(exc)})
        # Durable checkpoint roundtrip must not close the remaining condition.
        save(folder / 'before_submission_checkpoint.json', dump(state))
        state = load_simulation_state(read(folder / 'before_submission_checkpoint.json'))
        records = scoped(state)
        claim_rejected = None
        if changes.get('content') is None:
            data = {'decision': 'bid', 'content': '关键岗位人员档期已初步确认',
                    'unresolved_condition_ids': [r['condition_id'] for r in records if r['status'] != 'verified'],
                    'verified_condition_ids': [r['condition_id'] for r in records if r['status'] == 'verified'],
                    'bid_assumptions': ['Synthetic conditional bid']}
            try:
                require_condition_disposition(data, records)
                claim_rejected = False
            except ValueError:
                claim_rejected = True
        client = FixtureBidClient()
        runtime = AgentRuntime(client, profile='smoke')
        async_runner.run(generate_bid_documents(state, runtime))
        submitted = len(state.bid_documents) == 1
        actual = 'submit_fixture' if submitted else 'defer'
        passed = actual == ('defer' if expectation == 'scope_error_defer' else expectation)
        if expectation == 'scope_error_defer':
            passed &= len(errors) == 1 and all(r['status'] == 'requested' for r in records)
        if changes.get('content') is None:
            hr = next(r for r in records if '人员' in r['question'])
            passed &= claim_rejected == (hr['status'] != 'verified')
        if task_id == 'V0-06-partial-verified':
            passed &= [r['status'] for r in records] == ['verified', 'requested'] and client.calls == 0
        if actual == 'defer':
            passed &= client.calls == 0 and state.participation_decisions[0].decision == 'bid'
        save(folder / 'trace.json', {'reviews': steps, 'errors': errors, 'conditions_before_submission': records,
                                    'unsupported_confirmation_rejected': claim_rejected,
                                    'fixture_response_calls': client.calls, 'provider_requests': 0})
        save(folder / 'output.json', dump(state))
        rows.append({'task_id': task_id, 'expected': expectation, 'actual': actual, 'passed': bool(passed),
                     'fixture_response_calls': client.calls, 'evidence': str(folder.relative_to(attempt_dir))})
    save(attempt_dir / 'v0/results.json', rows)
    return rows


def build_v1_manifest(attempt_dir):
    tasks = []
    for draft in read(DRAFT):
        task = deepcopy(draft)
        task.update(expected=expected(draft['role'], draft['condition']),
                    origin='synthetic business fixture reused from existing tests; not a real project',
                    oracle_established_by='author-assisting AI from declared role boundaries and existing fixed business scenarios',
                    oracle_limitation='program/business-property verification, not independent professional judgment or real-world validity',
                    forbidden_facts=['No new actual project/contract/loan/inventory/payment/qualification acceptance'],
                    model_connected_for_this_run=False,
                    currency={'Owner':'HKD','Bank':'HKD','Architect':'HKD','Engineer':'HKD','QS':'CNY',
                              'Supplier':'HKD','Contractor':'HKD','Government':'not_applicable'}[draft['role']],
                    authority_scenario='Original fixture grant' if draft['condition'] != 'out_of_authority' else 'Ungrant​​ed actor, well-formed context',
                    oracle_sources=['Existing fixed synthetic fixture declarations', 'Exact action contract/skill',
                                    'Explicit source/ref/authority business boundary; arithmetic if applicable'])
        tasks.append(task)
    save(attempt_dir / 'v1/manifest.json', tasks)
    return tasks


def v1(attempt_dir, tasks):
    rows = []
    for task in tasks:
        role, condition, task_id = task['role'], task['condition'], task['task_id']
        folder = attempt_dir / 'v1' / task_id
        row = {'task_id': task_id, 'role': role, 'condition': condition, 'action_id': task['action_id'],
               'expected': task['expected'], 'passed': False, 'evidence': str(folder.relative_to(attempt_dir))}
        adapter = None
        try:
            adapter = prepare_task(role, condition)
            if adapter is None:
                row.update(outcome='not_assembled', gap=task['expected']['gap'])
                save(folder / 'result.json', row)
                rows.append(row)
                continue
            runner, context, data = adapter['runner'], adapter['context'], adapter['input']
            assert context.contract_ref.id == task['action_id'], 'Adapter must execute the exact draft action'
            save(folder / 'input.json', {'origin': task['origin'], 'context': context.model_dump(mode='json'),
                 'action_input': data, 'authorized_fixture_objects': adapter['objects'], 'source_fixture': adapter['source_fixture'],
                 'adapter': adapter['adapter'], 'execution_mode': 'offline_fixture',
                 'isolation': 'Fresh runner, organization registry, resolver and method registry per task; no shared task/model cache'})
            before = deepcopy(adapter['objects'])
            result = runner.run_action(context, data)
            result_data = serial(result)
            choice = getattr(result.payload, 'choice', None) if result.kind == 'completed' else None
            save(folder / 'raw_result.json', result_data)
            row.update(outcome='business_wait' if result.kind == 'needs_information' else
                       'business_refusal' if choice in {'decline', 'reject'} else 'business_completed',
                       result_kind=result.kind, choice=choice,
                       unchanged_sources=adapter['objects'] == before)
            row['passed'] = any(a['kind'] == result.kind and a['choice'] == choice for a in task['expected']['allowed']) and row['unchanged_sources']
            if role == 'QS' and condition == 'in_scope':
                row['independent_arithmetic_observed'] = result.payload.draft.complete_total.model_dump(mode='json')
                row['passed'] &= result.payload.draft.complete_total.value == '520' and result.payload.draft.complete_total.currency == 'CNY'
            if role == 'Supplier' and condition == 'in_scope':
                row['observed_batch_price'] = result.payload.offer.lines[0].price.value
                row['passed'] &= row['observed_batch_price'] == '1215.5'
            if role == 'Government' and condition == 'in_scope':
                row['observed_rule_findings'] = [c.finding for c in result.payload.assessment.checks]
                row['passed'] &= row['observed_rule_findings'] == ['conforms']
        except Exception as exc:
            from src.actions.runner import ActionRunError
            from src.organization.registry import AccessDenied
            from pydantic import ValidationError
            row.update(error_type=type(exc).__name__, error=str(exc))
            audits = adapter['runner'].audit_records if adapter is not None else []
            audit = audits[-1].as_dict() if audits else {}
            stages = audit.get('stages', {})
            if isinstance(exc, (ActionRunError, AccessDenied)) and condition == 'out_of_authority' and stages.get('authorization') in {'denied', 'rejected'}:
                row['outcome'] = 'authorization_blocked'
                row['passed'] = stages.get('processor') in {'not_started', 'not_run', 'not_checked'}
            elif isinstance(exc, ValidationError) or stages.get('input_validation') == 'failed':
                row['outcome'] = 'schema_blocked'
            else:
                row['outcome'] = 'technical_failure'
        finally:
            if adapter is not None:
                save(folder / 'action_audit.json', [a.as_dict() for a in adapter['runner'].audit_records])
            save(folder / 'result.json', row)
        rows.append(row)
        print(task_id, role, condition, row['outcome'], 'passed=', row['passed'], flush=True)
    save(attempt_dir / 'v1/results.json', rows)
    return rows


def condition_statistics(attempt_dir):
    source = BASE / '实验/2026-11-08_条件传递修复对照'
    rows = []
    for w in read(source / 'frozen_windows.json'):
        questions = [r['question'] for r in w['conditions']]
        norm = [re.sub(r'[\s\W_]+', '', q) for q in questions]
        rows.append({'window_id': w['window_id'], 'question_count': len(questions),
            'question_characters': sum(map(len, questions)), 'unique_after_space_punctuation_only': len(set(norm)),
            'blocking_questions': [r['question'] for r in w['conditions'] if r['required_before_submission']],
            'original_prompt_characters': sum(len(m['content']) for m in w['messages']['original']),
            'repaired_prompt_characters': sum(len(m['content']) for m in w['messages']['repaired'])})
    save(attempt_dir / 'condition_statistics.json', {'source_windows_sha256': sha(source / 'frozen_windows.json'),
         'observed_token_usage_from_prior_experiment': read(source / 'summary.json')['provider_reported_usage'], 'rows': rows,
         'no_new_token_measurement': True, 'normalization_applied_to_runtime': False,
         'recommendations': ['Preserve the canonical original question and source, display repeated references once',
             'Separate active material questions from discussion requests without deleting original evidence',
             'Do not automatically merge semantically different qualification, current availability and planned-support checks',
             'Turn generic if-feasible/otherwise-withdraw into a specific reviewable question before claiming a reliable closure']})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['run'])
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    index = 1
    while (OUT / f'attempt-{index:03d}').exists():
        index += 1
    attempt_dir = OUT / f'attempt-{index:03d}'
    attempt_dir.mkdir()
    baseline_files = ['PLAN.md', 'GOALS.md', 'src/verification.py', 'src/models.py',
        'src/stages/bid_documents.py', 'src/actions/runner.py', 'src/actions/processors.py',
        'scripts/capstone_core_cases_20261108.py', 'scripts/run_capstone_core_validation_20261108.py']
    baseline_files += [v[0].replace('.', '/') + '.py' for v in ADAPTERS.values()]
    baseline_files += ['integration/contractor_bid_actions.py','integration/government_review_actions.py',
                       'integration/government_intake_development.py','integration/government_approval_native_development.py',
                       'integration/examples/role_contract_contractor_bid_host.json',
                       'integration/examples/role_contract_contractor_bid_invocation.json']
    save(attempt_dir / 'baseline.json', {'at': utc_now(), 'provider_request_cap': 0,
         'version_scope': 'post-20261108 prerequisite-recognition follow-up; no macro modification',
         'files': {p: sha(ROOT / p) for p in baseline_files}, 'draft_sha256': sha(DRAFT),
         'macro_state': 'No macro engine/database is instantiated; synthetic read-only projections only'})
    tasks = build_v1_manifest(attempt_dir)
    guard = NoProviderNetwork()
    # Windows asyncio creates a local socketpair when its event loop starts.
    # Initialize it first, then block every connect throughout business work.
    with asyncio.Runner() as async_runner:
        async_runner.get_loop()
        with patch.object(socket.socket, 'connect', guard.block), patch.object(socket.socket, 'connect_ex', guard.block):
            r0 = v0(attempt_dir, async_runner)
            r1 = v1(attempt_dir, tasks)
            condition_statistics(attempt_dir)
    save(attempt_dir / 'zero_api.json', {'provider_requests': 0, 'blocked_network_attempts': guard.attempts,
         'enforcement': 'socket connect/connect_ex blocked throughout execution; no provider client/credentials constructed',
         'legacy_fixture_client_calls': sum(r['fixture_response_calls'] for r in r0),
         'fixture_client_calls_are_not_provider_requests': True})
    save(attempt_dir / 'summary.json', {'at': utc_now(), 'v0': {'total': len(r0), 'passed': sum(r['passed'] for r in r0)},
         'v1': {'total': len(r1), 'passed': sum(r['passed'] for r in r1),
                'roles_with_three_passing': [role for role in sorted({t['role'] for t in tasks}) if sum(r['passed'] for r in r1 if r['role'] == role) == 3]},
         'api_requests': 0, 'network_attempts': guard.attempts, 'status': 'results_require_review'})
    print('Saved', attempt_dir, flush=True)


if __name__ == '__main__':
    main()
