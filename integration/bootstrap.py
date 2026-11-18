"""Resolve the bundled macro package once, without editing sys.path in GBA."""
from pathlib import Path
import sys


def enable_gba_imports():
    root = Path(__file__).resolve().parents[1]
    macro = root / "vendor" / "gba"
    if not (macro / "gba_construction_sim").is_dir():
        raise RuntimeError("Bundled GBA package not found")
    from integration.asset_setup import ensure_macro_database
    ensure_macro_database(root)
    if str(macro) not in sys.path:
        sys.path.insert(0, str(macro))
    return macro
