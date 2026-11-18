"""Freeze same-fact S/D3/S4 organization tasks from all 48 core projects."""
from collections import Counter
from copy import deepcopy
import random

from capstone_cp_common_20261112 import ROOT, PARENT, CP01, no_provider, read, save, sha
from prepare_capstone_business_metrics_20261112 import task_card

BASE = ROOT / 'Capstone报告/验证体系'
OUT = BASE / '实验/2026-11-13_CP07组织质量对照'

POSITIONS = {
    'contractor': [
        ('施工负责人', '审视施工范围、现场组织及拟议分包接口，区分本方施工责任与外部支持。'),
        ('资源与商务负责人', '审视人员档期、资源与资格证据及成本或承诺风险，勿将总体档案当作本包已落实资源。'),
        ('质量与合同负责人', '审视质量复核、提交前提、合同责任及项目条件带来的具体安排。')],
    'supplier': [
        ('供货与物流负责人', '审视档案支持的供货方向、拟议配送和交付安排，区分既有产品库存与暂定方案。'),
        ('采购与商务负责人', '审视分项价格、总额与暂定依据及渠道资源，不把假设当作已收到的供应报价。'),
        ('质量与保修负责人', '审视质量文档、保修责任和外部支持接口，保持原有核查请求的必要或可选性质。')],
    'designer': [
        ('设计负责人', '审视设计服务范围、拟议成果及专业接口，区分设计责任与整包施工责任。'),
        ('项目与资源负责人', '审视设计团队的拟议组织、人员档期与顾问接口，勿把企业总体人员资料当作实际派驻。'),
        ('设计复核与合同负责人', '审视设计复核、文件交付、提交前提和责任取舍，普通专业支持不自动要求联合体。')],
    'supervisor': [
        ('监督服务负责人', '审视监督职责、检查记录和复核计划，区分监督与施工责任以及计划与已完成检查。'),
        ('人员与现场接口负责人', '审视人员档期、拟议派驻和施工方接口，未给现场情况仅能作为待确认事项。'),
        ('质量与责任复核负责人', '审视质量监督重点、记录责任、提交前提及对外承诺，不虚构监管权限或实际认可。')],
}

COMMON_PROCESS = (
    'This is an intermediate internal business comment, not a final document or a verified external receipt. '
    'Use only the shared task facts and clearly marked proposals; earlier internal comments supply no new external facts. '
    'Do not invent staff availability, credentials, accepted partners, prices or completed checks. '
    'Give a concise actionable business comment, without private reasoning or a thoughts field. '
    'Return one JSON object with exactly one nonempty string field: {"comment":"..."}. '
    'The comment may identify a proposed arrangement, a supported objection, or a concrete information gap.'
)
FINAL_INSTRUCTION = (
    'FINAL_ANSWER: Return the original task-required final JSON document or management intention, '
    'including all original evidence/condition/role fields. Use only the original shared facts. '
    'Internal process text, if present, consists of proposals to assess, not additional verified facts or accepted commitments. '
    'The original drafting scope and final response requirements remain in effect.'
)


def stages(arm, role):
    if arm == 'S':
        return []
    if arm == 'D3':
        return [{'step': i, 'position': title,
                 'instruction': COMMON_PROCESS + '\nYour assigned internal business position: ' + title + '。' + purpose}
                for i, (title, purpose) in enumerate(POSITIONS[role], 1)]
    assert arm == 'S4'
    instructions = [
        '以原任务同一公司决策角色给出简短的初步业务方案或有据等待／拒绝意向，保留资料与责任边界。',
        '仍以原任务同一公司决策角色自检前一步方案，指出事实、未知信息、角色或承诺方面的实质问题及可行修改。',
        '仍以原任务同一公司决策角色复核原任务与先前文本，提出应在最终方案保留或修正的业务安排及取舍。']
    return [{'step': i, 'position': '原任务同一决策角色', 'instruction': COMMON_PROCESS + '\n' + purpose}
            for i, purpose in enumerate(instructions, 1)]


def messages_for(window, arm, stage, history):
    messages = deepcopy(window['messages']['v2_5'])
    if history:
        import json
        messages.append({'role': 'user', 'content': 'INTERNAL_PROPOSALS_NOT_EXTERNAL_RECEIPTS:\n' + json.dumps(history, ensure_ascii=False)})
    instruction = FINAL_INSTRUCTION if stage == 4 else stages(arm, window['role'])[stage - 1]['instruction']
    messages.append({'role': 'user', 'content': instruction})
    return messages


def prepare():
    if (OUT / 'protocol.json').exists():
        raise ValueError('CP07 already frozen; verify, do not regenerate')
    with no_provider() as counts:
        windows, manifest, cards, jobs, ratings, process_rows = {}, [], [], [], [], []
        source_paths = []
        for cohort, directory in [('CP00', PARENT), ('CP01', CP01)]:
            original = read(directory / 'windows.json')
            source_paths += [directory / name for name in ['protocol.json', 'windows.json', 'sample_manifest.json']]
            for row in read(directory / 'sample_manifest.json'):
                unit = cohort + '-' + row['base_unit']
                manifest.append({**deepcopy(row), 'base_unit': unit, 'source_base_unit': row['base_unit'], 'source_cohort': cohort})
                for variant in ['full', 'missing_core']:
                    source_id = row['base_unit'] + '-' + variant
                    w = deepcopy(original[source_id])
                    wid = unit + '-' + variant
                    w.update(window_id=wid, base_unit=unit, source_cohort=cohort, source_window_id=source_id)
                    windows[wid] = w
                    cards.append(dict(task_card(w), cohort='CP07'))
                    for arm in ['S', 'D3', 'S4']:
                        job = {'window_id': wid, 'arm': arm, 'repeat': 1, 'calls': 1 if arm == 'S' else 4}
                        jobs.append(job)
                        ratings.append({'cohort': 'CP07', 'job': job, 'state': 'awaiting_real_final_response',
                            'D1_appropriateness': None, 'D2_factor_ratings': None,
                            'D3_feasibility': None, 'D4_tradeoff': None, 'evidence_recheck': None})
                        for process in stages(arm, w['role']):
                            process_rows.append({'cohort': 'CP07', 'window_id': wid, 'arm': arm,
                                'step': process['step'], 'position': process['position'],
                                'supported_new_issues': None, 'prior_issue_refs': None,
                                'final_response_disposition': None, 'state': 'awaiting_real_process_text'})
        random.Random(2026111307).shuffle(jobs)
        assert len(manifest) == len({r['project_group'] for r in manifest}) == 48
        assert Counter(r['role'] for r in manifest) == {role: 12 for role in POSITIONS}
        assert len(windows) == 96 and len(jobs) == 288 and sum(j['calls'] for j in jobs) == 864
        targets = [{'window_id': wid, 'evaluation': 'Original V2.5 final contract plus common business task card'} for wid in windows]
        for name, value in [('windows.json', windows), ('sample_manifest.json', manifest), ('task_cards.json', cards),
                            ('targets.json', targets), ('ratings_template.json', ratings), ('process_issues_template.json', process_rows),
                            ('position_templates.json', {role: {arm: stages(arm, role) for arm in ['S', 'D3', 'S4']} for role in POSITIONS})]:
            save(OUT / name, value)
        parent = read(CP01 / 'protocol.json')
        code = dict(parent['code_sha256'])
        for path in ['scripts/prepare_capstone_cp07_20261113.py', 'scripts/run_capstone_cp07_20261113.py',
                     'scripts/continue_capstone_cp01_20261112.py', 'scripts/run_capstone_phase1_goal_20261112.py']:
            code[path] = sha(ROOT / path)
        protocol = {'version': 'CP07-same-V25-free-generation.v1', 'run_id': 'capstone-CP07-core48-20261113',
            'budget_id': 'CP07-independent-cap864', 'model': parent['model'], 'temperature': .2,
            'concurrency': 2, 'max_calls': 864, 'max_repairs': 0, 'jobs': jobs,
            'groups': 48, 'final_answers': 288, 'repeats': 1, 'calls_per_arm': {'S': 1, 'D3': 4, 'S4': 4},
            'intermediate_output_cap': 800, 'final_output_cap': 4096,
            'primary_comparison': 'D3-minus-S4, project-equal D2; S comparisons supporting',
            'scope': 'Role positions are configured simulation assumptions, not actual employees; all arms use identical original V2.5 facts and final requirements.',
            'resource_boundary': 'Matched call counts and per-stage output caps; not matched actual tokens or compute.',
            'final_instruction': FINAL_INSTRUCTION,
            'windows_sha256': sha(OUT / 'windows.json'), 'targets_sha256': sha(OUT / 'targets.json'),
            'manifest_sha256': sha(OUT / 'sample_manifest.json'), 'code_sha256': code,
            'source_sha256': {**parent['source_sha256'], **{str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in source_paths}},
            'supplementary_sha256': {name: sha(OUT / name) for name in ['task_cards.json', 'ratings_template.json', 'position_templates.json', 'process_issues_template.json']},
            'stop': 'Any new provider failure/unknown, frozen mismatch, invalid intermediate JSON/comment or unexpected evaluator error stops all paid work; preserve attempts, never replay.',
            'paid_calls_in_preparation': 0}
        save(OUT / 'protocol.json', protocol)
        save(OUT / 'preparation.json', {'groups': 48, 'windows': 96, 'final_slots': 288, 'process_slots': len(process_rows),
             'role_groups': dict(Counter(r['role'] for r in manifest)), 'first_calls': 864, 'model_calls': 0, **counts})
    print('CP07 frozen: 48 groups, 96 conditions, 288 final slots, 864 calls, no paid preparation')


if __name__ == '__main__':
    prepare()
