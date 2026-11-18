"""Persist the four explicitly read draft reviews and their evidence recheck.

These judgments were authored after reading each complete outward response.
This script validates their locations; it does not infer any semantic grade.
"""
from copy import deepcopy
from capstone_cp_common_20261112 import ROOT, read, save, sha
from review_capstone_phase1_20261112 import OUT as OLD, locate, source

MASTER = ROOT / 'Capstone报告/验证体系/实验/2026-11-13_总实验收尾'


def main():
    calibration = MASTER / 'calibration/six_block_calibration.json'
    assert calibration.exists()
    records = []
    for arm in ['v2_4', 'v2_5']:
        for repeat in [1, 2]:
            name = f'EXPAND-02-full-{arm}-r{repeat}-a1.json'
            old_path = OLD / 'business_review/CP00' / name
            original = read(old_path)
            response, data, outward = source('CP00', 'EXPAND-02-full', arm, repeat)
            assert sha(response) == original['response_sha256']
            assert locate(outward, original['D1_evidence']['quote']) == original['D1_evidence']
            for factor in original['factor_ratings']:
                evidence = factor['response_evidence']
                assert locate(outward, evidence['quote']) == evidence
            record = deepcopy(original)
            changes = []
            if arm == 'v2_4' and repeat == 1:
                factor = record['factor_ratings'][1]
                factor.update(rating='correct',
                    reason='已提出设计主导、界面协调和文件质量管理，满足两项设计交付／接口安排的共同标准；范围判断错误另在D1及D4记录，不能据整体低评价抹去已有安排。',
                    response_evidence=locate(outward, '我方承担设计主导、界面协调、文件与质量管理'))
                assert factor['response_evidence']
                changes.append({'factor_id': 'D2', 'before': 'partial', 'after': 'correct',
                                'reason': factor['reason']})
                factor = record['factor_ratings'][3]
                factor.update(rating='partial',
                    reason='人员提交前提和伙伴未接受状态保留正确，但把未给定的设计施工整包责任当作强制共享投标身份的依据，未完整满足普通协作不自动升级组合体的同一事项。',
                    response_evidence=locate(outward, '若以单一主体承接，投标身份与包级交付责任将不匹配。'))
                assert factor['response_evidence']
                changes.append({'factor_id': 'D4', 'before': 'correct', 'after': 'partial',
                                'reason': factor['reason']})
            record['D2_correct_coverage'] = sum(f['rating'] == 'correct' for f in record['factor_ratings']) / len(record['factor_ratings'])
            record['evidence_recheck'] = {
                'complete': True, 'reviewer': original['reviewer'],
                'basis': 'Re-read complete outward response and supplied task card after the six-block calibration; all stored quotes/offsets verified.',
                'initial_record_path': str(old_path.relative_to(ROOT)).replace('\\', '/'),
                'initial_record_sha256': sha(old_path), 'calibration_sha256': sha(calibration),
                'changes': changes,
                'notes': 'Same assistant evidence recheck; not an independent expert, blinded assessment or second-rater reliability estimate.'}
            save(MASTER / 'business_review/CP00' / name, record)
            records.append({'key': ['CP00', record['window_id'], arm, repeat, 1],
                            'D1': record['D1_appropriateness'], 'D2': record['D2_correct_coverage'],
                            'changes': changes})
    save(MASTER / 'business_review/initial_four_recheck.json', {
        'outward_answers_read': 4, 'rechecked': 4, 'original_files_overwritten': 0,
        'provider_calls': 0, 'formal_review_records_saved': records,
        'aggregation': 'Four old exploratory records only; not a cohort/model performance result.'})
    print('4 explicit initial reviews rechecked; 2 item corrections; old records retained; 0 provider calls')


if __name__ == '__main__':
    main()
