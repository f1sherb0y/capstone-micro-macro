"""Input-only selection of another 24 groups; reuses frozen V2.4/V2.5 logic."""
from copy import deepcopy
import hashlib
from pathlib import Path
from unittest.mock import patch

from capstone_cp_common_20261112 import CP01, PARENT, ROOT, no_provider, read, save, sha, verify_parent


def main():
    if CP01.exists():
        raise ValueError('CP01 already prepared; use preflight, never reselect after outputs')
    import prepare_capstone_expansion_20261109 as original
    parent_protocol = verify_parent()
    parent_manifest = read(PARENT / 'sample_manifest.json')
    parent_groups = {r['project_group'] for r in parent_manifest}
    parent_firms = {r['company_id'] for r in parent_manifest}
    original_read = original.read
    original_retrieval = original.Retrieval

    def expanded_exclusions(path):
        value = original_read(path)
        if Path(path) == original.PREVIOUS / 'protocol.json':
            value = deepcopy(value)
            value['excluded_process_groups'] = sorted(set(value['excluded_process_groups']) | parent_groups)
        return value

    class DisjointEnterpriseRetrieval(original_retrieval):
        def rank(self, project):
            return {key: [cid for cid in ranking if cid not in parent_firms]
                    for key, ranking in super().rank(project).items()}

    def rank(value):
        return hashlib.sha256(('CP01-new24/20261112/' + value).encode()).hexdigest()

    with no_provider() as counts, patch.object(original, 'OUT', CP01), \
         patch.object(original, 'read', expanded_exclusions), \
         patch.object(original, 'Retrieval', DisjointEnterpriseRetrieval), \
         patch.object(original, 'rank', rank):
        original.prepare()
    # The reused writer has now produced a NEW, not-yet-published preparation.
    # Bind the concrete new runner and its distinct run/budget before freezing.
    protocol = read(CP01 / 'protocol.json')
    protocol.update(version='capstone-CP01-new24.v1', preparation_date='2026-11-12',
                    run_id='capstone-CP01-new24-20261112', budget_id='CP01-independent-cap240',
                    provider_calls_authorized=0, excluded_parent_groups=sorted(parent_groups),
                    parent_protocol_sha256=sha(PARENT / 'protocol.json'),
                    selection='Input-only type cycling; 24 new groups, four roles x6; firms disjoint from parent24. Known corpus, not external blind testing.')
    for name in ['scripts/capstone_cp_common_20261112.py', 'scripts/prepare_capstone_cp01_20261112.py',
                 'scripts/run_capstone_cp01_20261112.py', 'scripts/preflight_capstone_cp01_20261112.py']:
        protocol['code_sha256'][name] = sha(ROOT / name)
    # Replace only this unpublished new protocol; no historical file is edited.
    (CP01 / 'protocol.json').write_text(__import__('json').dumps(protocol, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    manifest = read(CP01 / 'sample_manifest.json')
    assert len({m['project_group'] for m in manifest}) == 24
    assert not parent_groups & {m['project_group'] for m in manifest}
    assert not parent_firms & {m['company_id'] for m in manifest}
    save(CP01 / 'selection_constraints.json', {
        'parent_groups': 24, 'new_groups': 24, 'combined_target_groups': 48,
        'project_group_overlap': 0, 'enterprise_overlap_with_parent24': 0,
        'parent_first_jobs': len(parent_protocol['jobs']), 'new_first_jobs': len(protocol['jobs']),
        'provider_requests': 0, **counts})


if __name__ == '__main__':
    main()
