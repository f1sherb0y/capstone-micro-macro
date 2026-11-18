from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


BUNDLE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BUNDLE_DIR.parents[1]
CONFIG_PATH = BUNDLE_DIR / "config.json"
DEFAULT_OUTPUT_DIR = BUNDLE_DIR / "results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the complete 352-case validation bundle."
    )
    parser.add_argument("--profile", choices=["smoke", "full"], default="full")
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--case-id", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--resume-batch", default="")
    parser.add_argument("--local-test-client", action="store_true")
    parser.add_argument("--list-cases", action="store_true")
    return parser.parse_args()


def required_files() -> list[Path]:
    return [
        CONFIG_PATH,
        BUNDLE_DIR / "bundle_summary.json",
        BUNDLE_DIR / "enterprise_coverage.csv",
        BUNDLE_DIR / "data" / "simulation_input_projects.csv",
        BUNDLE_DIR / "data" / "simulation_input_enterprises.csv",
        BUNDLE_DIR / "data" / "hidden_benchmark_project_enterprises.csv",
        BUNDLE_DIR / "data" / "match_report.csv",
    ]


def resolve_project_path(value: str, default: Path) -> Path:
    if not value:
        return default
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> None:
    args = parse_args()
    missing = [str(path) for path in required_files() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Validation bundle is incomplete: {missing}")

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    case_ids = list(config.get("batch_case_ids", []))
    if args.list_cases:
        print("\n".join(case_ids))
        return

    if args.resume_batch and (args.case_id or args.max_cases):
        raise ValueError("--resume-batch cannot be combined with --case-id or --max-cases")

    output_dir = resolve_project_path(args.output_dir, DEFAULT_OUTPUT_DIR)
    resume_batch = resolve_project_path(args.resume_batch, Path()) if args.resume_batch else None
    command = [
        sys.executable,
        str(PROJECT_ROOT / "main.py"),
        "--mode",
        "case",
        "--config",
        str(CONFIG_PATH),
        "--output-dir",
        str(output_dir),
    ]
    if resume_batch is not None:
        command.extend(["--resume-batch", str(resume_batch)])
    elif args.case_id:
        command.extend(["--profile", args.profile])
        if args.case_id not in case_ids:
            raise ValueError(f"Case is not in this validation bundle: {args.case_id}")
        command.extend(["--case-id", args.case_id])
    else:
        command.extend(["--profile", args.profile])
        command.extend(["--run-scope", "all"])
        if args.max_cases:
            command.extend(["--max-cases", str(args.max_cases)])

    env = os.environ.copy()
    if args.local_test_client:
        env["CODEDEMO_USE_LOCAL_TEST_CLIENT"] = "1"

    print(f"Bundle cases: {len(case_ids)}")
    print(f"Profile: {args.profile}")
    print(f"Max cases: {args.max_cases or 'all'}")
    print(f"Local test client: {args.local_test_client}")
    print(f"Output directory: {output_dir}")
    print(f"Resume batch: {resume_batch or 'no'}")
    print("Command:", " ".join(command))
    subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
