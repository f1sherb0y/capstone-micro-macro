"""Exact original author-reference consistency; no compatibility or approvals."""
import hashlib
import json
from pathlib import Path

from src.actions.contracts.architect_integration_objects import (
    ArchitectIntegrationConsistencyInput, ArchitectIntegrationConsistencyReport,
    ArchitectIntegrationInterfaceView, ArchitectIntegrationIssueView, ArchitectIntegrationOptionView,
    ArchitectIntegrationSourceView,
)
from src.actions.contracts.common import ref_type

INTERFACE_CONSISTENCY_METHOD = ref_type('Method')(
    kind='Method', id='micro.architect.original_interface_reference_consistency', version='1')


def check_original_interface_references(data):
    """Preserve exact content and all issues, including unknown/conflicting ones."""
    issues = set()
    objects = {row.ref.key(): row for row in data.original_objects}
    expected = {row.input_ref.key(): row.content_sha256 for row in data.input_digests}
    if len(objects) != len(data.original_objects) or len(expected) != len(data.input_digests):
        issues.add('duplicate_original_reference')
    if set(objects) != set(expected):
        issues.add('incomplete_original_content_digests')
    for key, row in objects.items():
        raw = json.dumps(row.model_dump(mode='json'), sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
        if expected.get(key) != hashlib.sha256(raw.encode()).hexdigest():
            issues.add('original_author_content_digest_mismatch')
    options = [row for row in data.original_objects if isinstance(row, ArchitectIntegrationOptionView)]
    if len(options) != 1 or options[0].ref != data.option_ref:
        issues.add('original_option_version_mismatch')
    sources = {ref.key() for ref in data.source_refs}
    if len(sources) != len(data.source_refs) or not set(objects) <= sources:
        issues.add('incomplete_or_duplicate_original_source_refs')
    basis = {ref.key() for ref in data.basis_refs}
    if len(basis) != len(data.basis_refs) or not all(
            {ref.key() for ref in row.evidence_refs} <= basis for row in data.original_objects):
        issues.add('incomplete_or_duplicate_original_evidence_refs')
    interfaces = {row.ref.key() for row in data.original_objects if isinstance(row, ArchitectIntegrationInterfaceView)}
    open_issues = {row.ref.key() for row in data.original_objects if isinstance(row, ArchitectIntegrationIssueView)}
    if (interfaces != {ref.key() for ref in data.interface_refs}
            or len(data.interface_refs) != len(interfaces)
            or open_issues != {ref.key() for ref in data.retained_issue_refs}
            or len(data.retained_issue_refs) != len(open_issues)):
        issues.add('original_interfaces_or_issues_dropped_or_repeated')
    required_issues = set()
    for row in data.original_objects:
        if isinstance(row, ArchitectIntegrationOptionView):
            continue
        if row.option_ref != data.option_ref:
            issues.add('original_option_version_mismatch')
        if isinstance(row, (ArchitectIntegrationSourceView, ArchitectIntegrationInterfaceView)):
            required_issues.update(ref.key() for ref in row.unresolved_issue_refs)
        if isinstance(row, ArchitectIntegrationInterfaceView) and not {ref.key() for ref in row.input_refs} <= set(objects):
            issues.add('undeclared_original_interface_inputs')
        if isinstance(row, ArchitectIntegrationIssueView):
            if row.status == 'closed':
                issues.add('original_open_issue_claimed_closed')
            if (not {ref.key() for ref in row.author_reference_refs} <= set(objects)
                    or not {ref.key() for ref in row.interface_refs} <= interfaces):
                issues.add('undeclared_original_issue_inputs')
    if not required_issues <= open_issues:
        issues.add('original_unresolved_issue_not_retained')
    return ArchitectIntegrationConsistencyReport(option_ref=data.option_ref, input_digests=data.input_digests,
        interface_refs=data.interface_refs, retained_issue_refs=data.retained_issue_refs,
        status='unknown' if issues else 'ok', issues=sorted(issues), technical_approval=False)


def register_architect_interface_consistency_method(registry):
    basis = Path(__file__).with_name('ARCHITECT_INTERFACES.md')
    registry.register({'method_ref': INTERFACE_CONSISTENCY_METHOD, 'namespace': 'micro_local',
        'effect_kind': 'pure_calculation', 'invocation': 'trusted_processor',
        'input_schema_id': INTERFACE_CONSISTENCY_METHOD.id + ':input',
        'output_schema_id': INTERFACE_CONSISTENCY_METHOD.id + ':report', 'action_ids': ['ARCHITECT-A06'],
        'support_domain': ['Exact original option, author projections, interface and open issue references',
            'Canonical SHA-256 content equality and retention of every declared unresolved issue'],
        'unit_rule': 'exact_declared_units_no_conversion', 'basis_locator': 'src/methods/ARCHITECT_INTERFACES.md',
        'basis_sha256': hashlib.sha256(basis.read_bytes()).hexdigest(), 'calibration': 'mathematical_only',
        'limitations': ['No engineering, cost, supply or spatial compatibility determination',
            'No independent source authority, observation or privacy verification; original role and host gates remain required',
            'No technical approval, issue closure, inferred consent or formal integration effects']},
        ArchitectIntegrationConsistencyInput, ArchitectIntegrationConsistencyReport, check_original_interface_references)
