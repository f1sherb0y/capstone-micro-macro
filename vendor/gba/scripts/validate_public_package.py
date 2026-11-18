"""Validate the public integration archive before distribution."""

from __future__ import annotations

import csv
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED = [
    "README.md",
    "NOTICE.md",
    ".env.example",
    "pyproject.toml",
    "docs/gba_multi_agent_simulation_specification.md",
    "docs/simulation_model_specification.md",
    "docs/agent_module_integration_guide.md",
    "docs/agent_operation_contracts.md",
    "outputs/gba_construction_agents_batch001.csv",
    "gba_construction_sim/backend/agents/contracts.py",
    "gba_construction_sim/backend/agents/external_adapter.py",
    "frontend/package-lock.json",
]

FORBIDDEN_PATH_PARTS = {
    ".git",
    ".worktrees",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "screenshots",
    "camel_ai_docs",
}

FORBIDDEN_SUFFIXES = {".ppt", ".pptx", ".sqlite", ".db", ".pyc", ".DS_Store"}
PRIVATE_MARKERS = [
    re.compile(r"/Users/[^/\s]+/"),
    re.compile(r"DEEPSEEK_API_KEY[ \t]*=[ \t]*[^#\r\n\s][^\r\n]*"),
    re.compile(r"OPENAI_API_KEY[ \t]*=[ \t]*[^#\r\n\s][^\r\n]*"),
    re.compile(r"CAMEL_API_KEY[ \t]*=[ \t]*[^#\r\n\s][^\r\n]*"),
]


def main() -> None:
    errors: list[str] = []
    for relative in REQUIRED:
        if not (ROOT / relative).is_file():
            errors.append(f"Missing required file: {relative}")

    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if any(part in FORBIDDEN_PATH_PARTS for part in relative.parts):
            errors.append(f"Forbidden path: {relative}")
        if path.is_file() and path.suffix in FORBIDDEN_SUFFIXES:
            errors.append(f"Forbidden artifact: {relative}")
        if (
            path.is_file()
            and path.name != Path(__file__).name
            and path.suffix.lower() in {".md", ".py", ".js", ".ts", ".vue", ".example"}
        ):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for marker in PRIVATE_MARKERS:
                if marker.search(text):
                    errors.append(f"Private marker in {relative}: {marker.pattern}")

    demo_csv = ROOT / "outputs" / "gba_construction_agents_batch001.csv"
    if demo_csv.is_file():
        with demo_csv.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            errors.append("Synthetic demo CSV is empty")
        if len(rows) < 1200:
            errors.append(f"Synthetic demo CSV has {len(rows)} rows; at least 1200 are required")
        for index, row in enumerate(rows, start=2):
            if row.get("is_synthetic", "").lower() != "true":
                errors.append(f"Non-synthetic row in demo CSV at line {index}")
            if row.get("data_source_type") != "generated_public_demo":
                errors.append(f"Unexpected demo data source at line {index}")

    if errors:
        raise SystemExit("Public package validation failed:\n- " + "\n- ".join(sorted(set(errors))))
    print(f"Public package validation passed: {ROOT}")


if __name__ == "__main__":
    main()
