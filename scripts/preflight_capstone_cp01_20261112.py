"""Reuse existing 96 synthetic interface probes in the NEW CP01 namespace."""
from unittest.mock import patch

from capstone_cp_common_20261112 import CP01, engine_binding, read
from run_capstone_cp01_20261112 import verify_frozen, run


def main():
    import preflight_capstone_expansion_20261109 as original
    with engine_binding(CP01, verify_frozen), patch.object(original, 'OUT', CP01), \
         patch.object(original, 'verify_frozen', verify_frozen), patch.object(original, 'run', run):
        original.main()
    result = read(CP01 / 'preflight.json')
    assert result['passed'] and result['provider_requests'] == 0


if __name__ == '__main__':
    main()
