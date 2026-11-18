"""Relate an original authorized decision draft to actual signed permit sources."""
from copy import deepcopy
from dataclasses import dataclass

from integration.government_decision_results import SavedGovernmentDecision
from integration.government_submission_host import GovernmentSubmissionHost
from src.actions.contracts.common import EvidenceRecord, Reference
from src.actions.contracts.government_decision_objects import GovDecisionBasisView
from src.actions.contracts.government_permit_objects import GovPermitView, GovPermitDecisionView
from src.coordination.tasks import TaskConflict, task_digest


@dataclass(frozen=True)
class GovernmentDecisionPublicationSource:
    """Application owns original decision and submission resources and guard."""
    saved: SavedGovernmentDecision
    submission_host: GovernmentSubmissionHost


def read_registered_decision_permit(prepared, *, source_task_sha256, native_evidence_ref,
        read_decision, validate_registration):
    """Read actual signed records without issuing a decision, permit or effect.

    Independent registration binds the original command/business identity,
    signed record and complete draft conditions to native permit conditions.
    Permit validity, expiry, action coverage, fulfillment, dependencies and
    actual delivery when required remain the original A08 processor's checks.
    """
    if not callable(read_decision) or not callable(validate_registration):
        raise TaskConflict('Permit registration requires original decision reader and independent native registration validator')
    try:
        context, reading = prepared.context, prepared.reading
        source = read_decision(context=context.model_copy(deep=True), source_task_sha256=source_task_sha256)
        saved = source.saved if isinstance(source, GovernmentDecisionPublicationSource) else source
        if (not isinstance(saved, SavedGovernmentDecision) or saved.identity.key != source_task_sha256
                or saved.identity.action_id != 'GOV-A07' or saved.identity.role != 'Government' or saved.identity.purpose != 'action'
                or saved.identity.organization_id != reading.organization_id
                or saved.identity.run_id != context.run_id or saved.context.run_id != context.run_id
                or saved.context.contract_ref.id != 'GOV-A07' or context.contract_ref.id != 'GOV-A08'
                or saved.context.execution_mode != context.execution_mode
                or saved.result.kind != 'completed' or saved.result.payload.choice not in {'approve', 'approve_with_conditions'}
                or task_digest(saved.context.model_dump(mode='json')) != saved.identity.context_sha256
                or task_digest(saved.action_input.model_dump(mode='json')) != saved.identity.input_sha256
                or task_digest(list(saved.source_reading)) != saved.source_reading_sha256):
            raise TaskConflict('Permit source requires original same-agency approving draft and current A08 input')
        reading.check_method_context(context, 'GOV-A08')
        result_sha = task_digest(saved.result.model_dump(mode='json'))
        if any(saved.audit.get(k) != v for k, v in {'run_id': context.run_id, 'action_id': 'GOV-A07',
                'operation_id': saved.context.operation_id, 'input_sha256': saved.identity.input_sha256,
                'result_sha256': result_sha, 'result_kind': 'completed'}.items()):
            raise TaskConflict('Permit source lacks original successful decision draft audit')
        publication = None
        if context.execution_mode != 'offline_fixture':
            if (not isinstance(source, GovernmentDecisionPublicationSource)
                    or not isinstance(source.submission_host, GovernmentSubmissionHost)):
                raise TaskConflict('Formal permit source requires original confirmed decision submission')
            publication = source.submission_host.read_receipt(saved.identity)
            receipt = publication.get('receipt', {})
            if (publication.get('schema_version') != 'government-decision-saved-receipt.v1'
                    or publication.get('identity') != saved.identity.as_dict()
                    or publication.get('record_sha256') != saved.record_sha256
                    or publication.get('receipt_sha256') != task_digest(receipt) or receipt.get('disposition') != 'accepted'
                    or any(receipt.get(k) != v for k, v in {'run_id': context.run_id,
                        'organization_id': saved.identity.organization_id, 'request_id': saved.identity.request_id,
                        'task_sha256': task_digest(saved.identity.as_dict()), 'output_sha256': result_sha}.items())):
                raise TaskConflict('Permit source changes original accepted decision submission provenance')
        originals = {}
        for row in saved.source_reading:
            key = Reference.model_validate(row['ref']).key()
            if key in originals:
                raise TaskConflict('Decision source repeats an original projection')
            originals[key] = row['projection']
        basis = GovDecisionBasisView.model_validate(originals[saved.action_input.decision_basis_ref.key()])
        permit = reading.resolve(prepared.action_input.permit_ref)
        if not isinstance(permit, GovPermitView):
            raise TaskConflict('Permit registration lacks the exact concrete current permit')
        decision = reading.resolve(permit.decision_ref)
        evidence = reading.resolve(Reference.model_validate(native_evidence_ref))
        draft = saved.result.payload.draft
        draft_sha = task_digest(draft.model_dump(mode='json'))
        if (not isinstance(decision, GovPermitDecisionView) or not isinstance(evidence, EvidenceRecord)
                or permit.organization_id != reading.organization_id or decision.permit_ref != permit.ref
                or decision.case_ref != saved.action_input.case_ref or decision.submission_ref != saved.action_input.current_submission_ref
                or decision.case_ref != draft.case_ref or decision.submission_ref != draft.submission_ref
                or draft.decision_basis_ref != basis.ref or decision.draft_sha256 != draft_sha
                or decision.outcome != draft.outcome or decision.outcome != saved.result.payload.choice
                or decision.scope != draft.covered_scope or decision.effect_rule_ref != draft.effect_rule_ref
                or decision.signer_actor_id != basis.signer_actor_id or decision.signer_function_ref != basis.signer_function_ref
                or evidence.ref not in decision.evidence_refs or evidence.ref not in permit.evidence_refs
                or evidence.basis_kind != 'observed'
                or (evidence.source_kind == 'synthetic') != (context.execution_mode == 'offline_fixture')):
            raise TaskConflict('Signed permit sources substitute the original draft, scope, signer or actual native evidence')
        now = context.business_time
        if (saved.context.business_time.clock_ref != now.clock_ref or decision.available_at.clock_ref != now.clock_ref
                or permit.available_at.clock_ref != now.clock_ref
                or not saved.context.business_time.offset <= decision.available_at.offset <= permit.available_at.offset <= now.offset
                or evidence.effective_window is not None and not evidence.effective_window.contains(now)):
            raise TaskConflict('Decision or permit registration changes original signing/availability chronology')
        relation = {'schema_version': 'government-decision-permit-registration.v1',
            'source_identity': saved.identity.as_dict(), 'source_record_sha256': saved.record_sha256,
            'source_result_sha256': result_sha, 'source_reading_sha256': saved.source_reading_sha256,
            'draft_sha256': draft_sha, 'decision_sha256': task_digest(decision.model_dump(mode='json')),
            'permit_sha256': task_digest(permit.model_dump(mode='json'))}
        if publication is not None:
            relation['publication'] = deepcopy(publication)
        if evidence.content_hash != task_digest(relation) or validate_registration(
                deepcopy(saved), decision.model_copy(deep=True), permit.model_copy(deep=True),
                evidence.model_copy(deep=True), context.model_copy(deep=True)) is not True:
            raise TaskConflict('Application did not confirm original command identity, actual signing and complete permit/condition registration')
        return {**relation, 'native_evidence_ref': evidence.ref.model_dump(mode='json'),
            'native_evidence_sha256': task_digest(evidence.model_dump(mode='json')),
            'execution_source_reading_sha256': prepared.reading_sha256}
    finally:
        prepared.reading.recheck()
        if (task_digest(prepared.reading.evidence()) != prepared.reading_sha256
                or task_digest(prepared.context.model_dump(mode='json')) != prepared.context_sha256
                or task_digest(prepared.action_input.model_dump(mode='json')) != prepared.input_sha256):
            raise TaskConflict('Decision reader changed original permit sources or invocation')
