"""Relate an actually received QS A13 report to supplied owner A03 inputs."""
from copy import deepcopy

from integration.qs_research_results import SavedQSResearch
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.owner_investment_objects import (
    InvestmentComparisonView, InvestmentResearchReceiptView,
)
from src.actions.contracts.qs_research_objects import QSResearchAuthorityView
from src.actions.contracts.owner_study_objects import unique_refs
from src.coordination.tasks import TaskConflict, task_digest


def read_received_qs_research(prepared, *, source_task_sha256, receipt_ref,
        read_qs_research, validate_reception):
    """Read the selected original QS report through independent application sources.

    Caller holds the source guard. Preserve all exclusions/missing items and
    actual option links; a limited comparison does not supply a cash forecast.
    """
    if not callable(read_qs_research) or not callable(validate_reception):
        raise TaskConflict('Research reception requires original QS reader and independent receiver validator')
    try:
        saved = read_qs_research(context=prepared.context.model_copy(deep=True),
            source_task_sha256=source_task_sha256)
        if not isinstance(saved, SavedQSResearch) or saved.identity.key != source_task_sha256:
            raise TaskConflict('Research reader substituted the selected original QS task')
        validate_received_qs_research(saved, prepared=prepared, receipt_ref=receipt_ref,
            validate_reception=validate_reception)
        receipt = prepared.reading.resolve(Reference.model_validate(receipt_ref))
        return {'source_task_sha256': saved.identity.key, 'source_record_sha256': saved.record_sha256,
            'source_result_sha256': task_digest(saved.result.model_dump(mode='json')),
            'source_reading_sha256': saved.source_reading_sha256,
            'report_sha256': task_digest(saved.result.payload.comparison.model_dump(mode='json')),
            'receipt_ref': receipt.ref.model_dump(mode='json'),
            'receipt_sha256': task_digest(receipt.model_dump(mode='json')),
            'option_links_sha256': task_digest([link.model_dump(mode='json') for link in receipt.option_links]),
            'execution_source_reading_sha256': prepared.reading_sha256}
    finally:
        prepared.reading.recheck()
        if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
                or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Research reader changed original Owner sources or invocation')


def validate_received_qs_research(saved, *, prepared, receipt_ref, validate_reception):
    """Check original report and current recipient without inventing forecasts.

    Actual reception/publication, privacy and mapping validation belongs to the
    independently supplied application callback. Caller holds the source guard.
    The original report retains exclusions, missing items and tied/no ranking.
    """
    context, reading = prepared.context, prepared.reading
    if (not isinstance(saved, SavedQSResearch) or saved.identity.action_id != 'QS-A13'
            or saved.identity.role != 'QS' or saved.identity.run_id != context.run_id
            or saved.context.contract_ref.id != 'QS-A13'
            or saved.context.run_id != context.run_id or prepared.ACTION_ID != 'OWN-A03'
            or context.contract_ref.id != 'OWN-A03' or not callable(validate_reception)
            or saved.result.kind != 'completed'
            or saved.result.payload.choice not in {'compare', 'cannot_rank', 'deliver_at_limit'}
            or saved.context.execution_mode != context.execution_mode
            or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
            or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
            or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
        raise TaskConflict('Research handoff requires original completed QS report and current owner input')
    reading.check_method_context(context, 'OWN-A03')
    before = task_digest(reading.evidence())
    if before != prepared.reading_sha256:
        raise TaskConflict('Research handoff changed the original owner source snapshot')
    result_sha = task_digest(saved.result.model_dump(mode='json'))
    if any(saved.audit.get(key) != value for key, value in {
            'run_id': context.run_id, 'action_id': 'QS-A13',
            'operation_id': saved.context.operation_id, 'input_sha256': saved.identity.input_sha256,
            'result_sha256': result_sha, 'result_kind': 'completed'}.items()):
        raise TaskConflict('Research handoff lacks original successful QS audit')
    try:
        receipt = reading.resolve(Reference.model_validate(receipt_ref))
        comparison = reading.resolve(prepared.action_input.comparison_ref)
        report = saved.result.payload.comparison.model_dump(mode='json')
        if (not isinstance(receipt, InvestmentResearchReceiptView)
                or not isinstance(comparison, InvestmentComparisonView)
                or receipt.run_id != context.run_id
                or receipt.recipient_organization_id != reading.organization_id
                or receipt.author_organization_id != saved.identity.organization_id
                or receipt.case_ref != prepared.action_input.case_ref
                or receipt.comparison_ref != comparison.ref or receipt.report != report
                or receipt.source_task_sha256 != saved.identity.key
                or receipt.source_record_sha256 != saved.record_sha256
                or receipt.source_result_sha256 != result_sha
                or receipt.source_reading_sha256 != saved.source_reading_sha256):
            raise TaskConflict('Received research substitutes original report, author, recipient or owner case')
        now = context.business_time
        if (saved.context.business_time.clock_ref != now.clock_ref
                or receipt.available_at.clock_ref != now.clock_ref
                or not saved.context.business_time.offset <= receipt.available_at.offset <= now.offset
                or not receipt.effective_window.contains(now)):
            raise TaskConflict('Received research changes original report/receipt chronology')
        originals = {}
        for row in saved.source_reading:
            key = Reference.model_validate(row['ref']).key()
            if key in originals:
                raise TaskConflict('Research handoff repeats an original source')
            originals[key] = row['projection']
        grant = QSResearchAuthorityView.model_validate(originals[saved.action_input.research_authority_ref.key()])
        if (grant.client_organization_id != reading.organization_id
                or grant.delegate_organization_id != saved.identity.organization_id
                or grant.delegate_actor_id != saved.context.actor_id
                or grant.delegate_function_ref != saved.context.function_ref
                or grant.brief_ref != saved.action_input.brief_ref
                or grant.task_ref != saved.action_input.task_ref):
            raise TaskConflict('Research handoff changes original independent delegation or client')
        research_keys = [link.research_option_ref.key() for link in receipt.option_links]
        investment_keys = [link.investment_option_ref.key() for link in receipt.option_links]
        if (len(set(research_keys)) != len(research_keys)
                or len(set(investment_keys)) != len(investment_keys)
                or set(research_keys) != {ref.key() for ref in saved.result.payload.comparison.option_refs}
                or not set(investment_keys) <= {ref.key() for ref in comparison.option_refs}):
            raise TaskConflict('Research handoff changes option versions or supplies an ambiguous option mapping')
        report_hash = task_digest(report)
        unique_refs(receipt.evidence_refs)
        for ref in receipt.evidence_refs:
            evidence = reading.resolve(ref)
            if (not isinstance(evidence, EvidenceRecord) or evidence.content_hash != report_hash
                    or evidence.basis_kind != 'observed'
                    or evidence.effective_window is not None and not evidence.effective_window.contains(now)
                    or (evidence.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')
                    or ref not in comparison.evidence_refs):
                raise TaskConflict('Owner comparison lacks lawful original received-report evidence')
        if validate_reception(deepcopy(saved), receipt.model_copy(deep=True),
                context.model_copy(deep=True), prepared.action_input.model_copy(deep=True)) is not True:
            raise TaskConflict('Actual application did not confirm research reception and option mapping')
    finally:
        reading.recheck()
        if (task_digest(reading.evidence()) != before
                or task_digest(context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Research reception validation changed original owner inputs or sources')
