"""Generate separate coverage dimensions; registration never implies execution."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from integration.action_catalog import ROOT, validate_coverage


def applicability_denominators(registry: dict, coverage: dict) -> dict:
    """Keep unassessed actions in scope; exemptions need declared frozen-source basis.

    Applicability declarations describe reviewed scope, not verification. No
    runtime/branch completion or professional support is inferred from them.
    """
    source_actions = {action['action_id']: action for action in registry['actions']}
    result = {}
    for dimension in ('method', 'binding'):
        states = Counter()
        unassessed, declarations = [], []
        for record in coverage['actions']:
            applicability = record.get('applicability', {})
            if not isinstance(applicability, dict) or set(applicability) - {'method', 'binding'}:
                raise ValueError('Action applicability must declare only method and binding scope')
            declaration = applicability.get(dimension)
            state = 'unassessed'
            if declaration is not None:
                action = source_actions[record['action_id']]
                if (not isinstance(declaration, dict)
                        or set(declaration) != {'state', 'source_sha256', 'source_quote'}
                        or declaration['state'] not in {'required', 'not_required', 'unassessed'}
                        or declaration['source_sha256'] != action['source_sha256']
                        or not isinstance(declaration['source_quote'], str)
                        or not declaration['source_quote'].strip()
                        or declaration['source_quote'] not in action['source_card']):
                    raise ValueError('Action applicability needs a valid explicit frozen action-card basis')
                state = declaration['state']
                declarations.append({'action_id': record['action_id'], **declaration})
            states[state] += 1
            if state == 'unassessed':
                unassessed.append(record['action_id'])
        result[dimension] = {
            'total_actions': len(coverage['actions']), 'required': states['required'],
            'not_required': states['not_required'], 'unassessed': states['unassessed'],
            'conservative_applicable_denominator': states['required'] + states['unassessed'],
            'unassessed_action_ids': unassessed, 'declared_source_bases': declarations,
            'status': 'source_scope_declarations_not_completion_evidence',
        }
    return result


def coverage_report(registry: dict, coverage: dict) -> dict:
    validate_coverage(registry, coverage)
    records = coverage["actions"]
    return {"schema_version": "coverage-report.v1", "registered": len(registry["actions"]),
            "dimensions": {dimension: dict(Counter(record[dimension] for record in records))
                           for dimension in ("contract", "decision", "method", "binding", "feedback", "validation")},
            "structural_schemas_verified": sum(record.get("contract_schema", {}).get("status") == "structural_verified" for record in records),
            "applicability_denominators": applicability_denominators(registry, coverage),
            "branches": dict(Counter(status for record in records for status in record["branches"].values())),
            "gaps": [{"action_id": record["action_id"], "gaps": record["gaps"]} for record in records if record["gaps"]]}


def acceptance_matrix(registry: dict, coverage: dict, *, evidence_map=None, root: Path = ROOT) -> dict:
    """Expose the complete frozen acceptance scope without upgrading declarations.

    Optional explicit claims are checked against original artifact bytes and
    locators. Unmapped items never inherit aggregate action validation. Neither
    historical statuses nor correlated claims prove full completion.
    """
    validate_coverage(registry, coverage)
    from integration.action_evidence_map import validate_evidence_map
    mapped = validate_evidence_map(registry, evidence_map, root=root) if evidence_map is not None else None
    by_action = {}
    for claim in mapped['claims'] if mapped is not None else ():
        by_action.setdefault(claim['action_id'], []).append(claim)

    def claims_for(action_id, target):
        return [row for row in by_action.get(action_id, ()) if row['target'] == target]

    applicability = applicability_denominators(registry, coverage)
    dimensions = dict(zip("CDMBFV", ("contract", "decision", "method", "binding", "feedback", "validation")))
    records = {record["action_id"]: record for record in coverage["actions"]}
    actions, branches, checks = [], [], []
    role_checks = {}
    for action in registry["actions"]:
        action_id = action["action_id"]
        record = records[action_id]
        scope = {dimension: record.get("applicability", {}).get(dimension, {}).get("state", "unassessed")
            for dimension in ("method", "binding")}
        actions.append({"action_id": action_id, "role": action["role"], "phase": action["implementation_batch"],
            "source": action["source"], "source_line": action["source_line"], "source_sha256": action["source_sha256"],
            "declared_dimensions": {letter: record[field] for letter, field in dimensions.items()},
            "applicability": scope, "primary_evidence_paths": list(record["evidence"]),
            "coding_record_count": len(set(record.get("implementation_evidence", []))),
            "evidence_record_action_id": action_id,
            "supported_scenario_mapping": "correlated_claims_not_support_proof" if any(
                row['target']['kind'] == 'scenario' for row in by_action.get(action_id, ())) else "unassessed",
            "dimension_claims": {letter: claims_for(action_id, {'kind': 'dimension', 'dimension': letter})
                for letter in dimensions},
            "scenario_claims": [row for row in by_action.get(action_id, ()) if row['target']['kind'] == 'scenario'],
            "gaps": deepcopy(record["gaps"])})
        branches.extend({"action_id": action_id, "choice": choice, "declared_status": record["branches"][choice],
            "claims": claims_for(action_id, {'kind': 'branch', 'choice': choice}),
            "evidence_mapping": "correlated_claims_not_completion_proof" if claims_for(action_id, {'kind': 'branch', 'choice': choice})
                else "action_record_only_not_branch_proof"} for choice in action["choices"])
        checks.extend({"action_id": action_id, "check_id": check,
            "claims": claims_for(action_id, {'kind': 'check', 'check_id': check}),
            "evidence_mapping": "correlated_claims_not_completion_proof" if claims_for(action_id, {'kind': 'check', 'check_id': check}) else "unmapped"}
            for check in action["checks"])
        role_checks.setdefault(action["role"], set()).update(action["role_checks"])
    return {"schema_version": "coverage-acceptance-matrix.v1", "status": "declared_scope_not_completion_audit",
        "dimension_fields": dimensions, "action_denominator": len(actions),
        "legal_branch_denominator": len(branches), "action_card_check_pair_denominator": len(checks),
        "unique_role_check_denominator": sum(len(values) for values in role_checks.values()),
        "unmapped_check_pairs": sum(not row['claims'] for row in checks),
        "unmapped_branch_count": sum(not row['claims'] for row in branches),
        "unassessed_scenario_action_count": sum(not row['scenario_claims'] for row in actions),
        "dimension_denominators": {letter: applicability[field]["conservative_applicable_denominator"]
            if field in applicability else len(actions) for letter, field in dimensions.items()},
        "declared_branch_status_counts": dict(Counter(row["declared_status"] for row in branches)),
        "phase_action_counts": dict(Counter(row["phase"] for row in actions)),
        "completion_proven": False,
        "limitations": "Statuses and evidence links are historical declarations. Aggregate validation cannot prove individual CHECKs, scenarios or all legal branches. Unassessed applicability stays in the denominator; no code-completion percentage or business success is inferred.",
        "evidence_map": mapped,
        "actions": actions, "branches": branches, "action_card_checks": checks,
        "role_checks": {role: sorted(values) for role, values in role_checks.items()}}


def implementation_inventory(coverage: dict, *, root: Path = ROOT) -> dict:
    """Index linked coding records without promoting any verification dimension.

    Historical manifests describe their own batch. Their presence does not prove
    a complete action, current source equivalence or a working external endpoint.
    Read each distinct manifest once, and retain broken or unclassified links.
    """
    root = Path(root).resolve()
    evidence = {}
    actions = []
    for record in coverage["actions"]:
        paths = sorted(set(record.get("implementation_evidence", [])))
        for name in paths:
            if name in evidence:
                continue
            path = (root / name).resolve()
            if Path(name).is_absolute() or not path.is_relative_to(root):
                evidence[name] = {"link_status": "outside_repository"}
                continue
            try:
                raw = path.read_bytes()
            except OSError:
                evidence[name] = {"link_status": "unreadable"}
                continue
            digest = hashlib.sha256(raw).hexdigest()
            try:
                manifest = json.loads(raw)
            except (ValueError, UnicodeError):
                evidence[name] = {"link_status": "invalid_json", "sha256": digest}
                continue
            status = manifest.get("status") if isinstance(manifest, dict) else None
            if not isinstance(status, str) or not status:
                evidence[name] = {"link_status": "missing_status", "sha256": digest}
                continue
            evidence[name] = {"link_status": "readable", "declared_status": status, "sha256": digest}
        counts = Counter(evidence[name].get("declared_status") for name in paths)
        actions.append({"action_id": record["action_id"], "evidence_paths": paths,
            "coded_unverified_manifest_count": counts["implemented_unverified"],
            "source_review_manifest_count": counts["source_review_only"],
            "other_or_broken_manifest_count": len(paths) - counts["implemented_unverified"] - counts["source_review_only"],
            "validation": record["validation"], "binding": record["binding"], "feedback": record["feedback"]})
    return {"schema_version": "coverage-implementation-inventory.v1",
        "status": "static_inventory_not_completion_audit", "action_count": len(actions),
        "distinct_linked_manifest_count": len(evidence),
        "manifest_status_counts": dict(Counter(item["declared_status"] for item in evidence.values()
            if item["link_status"] == "readable")),
        "link_status_counts": dict(Counter(item["link_status"] for item in evidence.values())),
        "actions_with_coding_evidence": sum(row["coded_unverified_manifest_count"] > 0 for row in actions),
        "exact_remaining_code_gap_count": None,
        "limitations": "Linked batch records only; source reviews do not count as coding. No runtime, endpoint, branch or full-action completion is inferred; remaining code gaps require requirement-by-requirement review.",
        "manifests": evidence, "actions": actions}


def record_structural_schemas(coverage: dict, evidence_path: Path, root: Path = ROOT) -> dict:
    evidence_path = Path(evidence_path).resolve()
    if not evidence_path.is_relative_to(root.resolve()):
        raise ValueError("Coverage evidence must be stored in the repository")
    manifest = json.loads(evidence_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "action-schema-evidence.v1" or manifest.get("status") != "structural_verified":
        raise ValueError("Expected verified structural schema evidence")
    evidence = {action["action_id"]: action for action in manifest["actions"]}
    if len(evidence) != 106 or set(evidence) != {record["action_id"] for record in coverage["actions"]}:
        raise ValueError("Structural evidence action set differs")
    for record in coverage["actions"]:
        action = evidence[record["action_id"]]
        if action["source_sha256"] != record["source_sha256"] or set(action["choices"]) != set(record["branches"]):
            raise ValueError("Structural evidence source or branch mismatch")
        record["contract_schema"] = {"status": "structural_verified", "version": "role-contract.v1",
                                     "code": "src/actions/contracts/catalog.py", "evidence": evidence_path.relative_to(root).as_posix(),
                                     "limitations": "Field/shape validation only; full source CHECK and authorized business branches are not yet verified"}
    return coverage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--record-structural", type=Path)
    parser.add_argument("--implementation-inventory", action="store_true",
                        help="Include a static inventory of linked coding and source-review manifests")
    parser.add_argument("--acceptance-matrix", action="store_true",
                        help="Include all action dimensions, legal branches and unmapped source CHECKs")
    parser.add_argument("--evidence-map", type=Path,
                        help="Explicit action-evidence-map.v1 claims; requires --acceptance-matrix")
    args = parser.parse_args()
    if args.evidence_map and not args.acceptance_matrix:
        parser.error('--evidence-map requires --acceptance-matrix')
    registry_raw = (ROOT / "config/action_registry.json").read_bytes()
    registry = json.loads(registry_raw)
    path = ROOT / "宏微观衔接方案/新版方案/action_coverage.json"
    coverage_raw = path.read_bytes()
    coverage = json.loads(coverage_raw)
    if args.record_structural:
        coverage = record_structural_schemas(coverage, args.record_structural)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        coverage_raw = path.read_bytes()
    report = coverage_report(registry, coverage)
    if args.implementation_inventory:
        report["implementation_inventory"] = implementation_inventory(coverage)
    if args.acceptance_matrix:
        evidence_map = None
        if args.evidence_map:
            from integration.scenario_v2 import parse_input_json
            evidence_raw = args.evidence_map.read_bytes()
            _, evidence_map = parse_input_json(evidence_raw)
        report["acceptance_matrix"] = acceptance_matrix(registry, coverage, evidence_map=evidence_map)
        report["acceptance_matrix"]["input_files"] = [
            {"path": "config/action_registry.json", "sha256": hashlib.sha256(registry_raw).hexdigest()},
            {"path": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(coverage_raw).hexdigest()}]
        if args.evidence_map:
            report['acceptance_matrix']['input_files'].append({'path': str(args.evidence_map.resolve()),
                'sha256': hashlib.sha256(evidence_raw).hexdigest()})
    if args.output:
        from integration.action_catalog import write_new
        write_new(args.output, report)
    summary = {key: value for key, value in report.items() if key not in {"gaps", "implementation_inventory", "applicability_denominators", "acceptance_matrix"}}
    summary['applicability_denominators'] = {dimension: {key: value for key, value in counts.items()
        if key not in {'unassessed_action_ids', 'declared_source_bases'}}
        for dimension, counts in report['applicability_denominators'].items()}
    if args.implementation_inventory:
        summary["implementation_inventory"] = {key: value for key, value in report["implementation_inventory"].items()
            if key not in {"manifests", "actions"}}
    if args.acceptance_matrix:
        summary["acceptance_matrix"] = {key: value for key, value in report["acceptance_matrix"].items()
            if key not in {"actions", "branches", "action_card_checks", "role_checks", "limitations", "input_files", "evidence_map"}}
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
