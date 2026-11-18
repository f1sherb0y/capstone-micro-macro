"""Record and verify immutable source baselines without importing the macro engine."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from integration.action_catalog import ROOT, sha256, write_new


def protected_hashes(root: Path = ROOT) -> dict[str, str]:
    paths = []
    excluded = {"__pycache__", ".pytest_cache", "node_modules", "outputs", "processed"}
    for directory in ("zwtnew", "vendor/gba"):
        for parent, directories, files in os.walk(root / directory):
            directories[:] = sorted(name for name in directories if name not in excluded)
            paths.extend(Path(parent) / name for name in sorted(files)
                         if Path(name).suffix.lower() in {".py", ".md", ".json", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".txt", ".js", ".ts", ".tsx", ".css", ".html"})
    if not paths:
        raise ValueError("Protected macro sources not found")
    return {path.relative_to(root).as_posix(): sha256(path) for path in sorted(paths)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    current = protected_hashes()
    if args.verify:
        original = json.loads(args.output.read_text(encoding="utf-8"))["protected_hashes"]
        changed = sorted(key for key in set(original) | set(current) if original.get(key) != current.get(key))
        if changed:
            raise ValueError(f"Protected files changed: {changed}")
        print(json.dumps({"protected_files": len(current), "unchanged": True}))
        return
    git = subprocess.run(["git", "status", "--porcelain=v1", "-uall"], cwd=ROOT,
                         check=True, capture_output=True, text=True, encoding="utf-8")
    write_new(args.output, {"schema_version": "plan-baseline.v1", "python": sys.version,
                           "git_status": git.stdout.splitlines(), "protected_hashes": current})
    print(json.dumps({"protected_files": len(current), "baseline": str(args.output)}))


if __name__ == "__main__":
    main()
