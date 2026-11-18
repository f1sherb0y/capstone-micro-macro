"""Recover original A07 case readiness with formal-command history kept authoritative."""
from copy import deepcopy
from dataclasses import dataclass

from pydantic import TypeAdapter

from src.actions.contracts.common import ActionContext, EvidenceRecord, ScopeRef, ref_type, walk_references
from src.actions.contracts.government_review_objects import GovReviewSubmissionView
from src.actions.contracts.government_decision_objects import (
    GovDecisionCaseView, GovDecisionBasisView, GovProcedureCompletionView, GovDecisionCommandView, GovFormalDecisionView,
)
from src.actions.contracts.references import ActionReadView
from src.actions.roles.qs_change import content_digest
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.coordination.government_decision_query import GovernmentDecisionQueryRecord
from src.coordination.government_decision_notification import NOTIFICATION_CODE
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


_CODE = 'government_decision_case_not_ready'
_QUERY_CODE = 'government_decision_query_unknown_submission_before_retry'
_UNRESOLVED_CODE = 'government_decision_query_unresolved_formal_fact'
_CODES = (_CODE, _QUERY_CODE, _UNRESOLVED_CODE, NOTIFICATION_CODE)
_FIELDS = frozenset({'scope', 'case_ref', 'current_submission_ref', 'assessment_refs', 'unresolved_issue_refs',
    'procedure_completion_ref', 'decision_basis_ref'})
_BASES = (('case_ref', 'RegulatoryCase', GovDecisionCaseView),
    ('current_submission_ref', 'Submission', GovReviewSubmissionView),
    ('procedure_completion_ref', 'ProcedureCompletion', GovProcedureCompletionView),
    ('decision_basis_ref', 'DecisionBasis', GovDecisionBasisView))
_LISTS = {'assessment_refs': 'Assessment', 'unresolved_issue_refs': 'Issue'}


@dataclass(frozen=True)
class GovernmentDecisionConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict
    decision_sources: list[dict] | None = None
    unavailable_targets: list[dict] | None = None
    original_context: ActionContext | None = None
    command_query: dict | None = None
    notification_completion: dict | None = None
    notification_snapshot: dict | None = None


def government_original_decision_case_profile(read_current, validate_relation):
    """Readiness permits fresh judgment only while the original command has no formal fact."""
    return _original_decision_source_profile(read_current, validate_relation, _CODE)


def government_original_decision_query_profile(read_current, validate_relation):
    """Actual original-command absence permits fresh judgment; found facts never permit replay."""
    return _original_decision_source_profile(read_current, validate_relation, _QUERY_CODE)


def government_original_decision_unresolved_profile(read_current, validate_relation):
    """Resolve an unknown formal lookup without inventing a submitted command or signed fact."""
    return _original_decision_source_profile(read_current, validate_relation, _UNRESOLVED_CODE)


def _original_decision_source_profile(read_current, validate_relation, condition_code):
    query_wait = condition_code in {_QUERY_CODE, _UNRESOLVED_CODE}
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('Government decision recovery requires actual sources and native command/history validation')

    def identities(refs):
        keys = {ref.key()[:2] for ref in refs}
        if len(keys) != len(refs):
            raise TaskConflict('Government decision recovery duplicates a physical source')
        return keys

    def physical(value):
        # References may advance to independently validated versions when case
        # readiness changes. Preserve every actual draft term and identity.
        if isinstance(value, dict):
            return {key: physical(item) for key, item in value.items()
                if not (key == 'version' and set(value) == {'kind', 'id', 'version'})}
        if isinstance(value, list):
            return [physical(item) for item in value]
        return value

    def unresolved(command):
        return (command.official_decision_ref is not None or command.status == 'recorded'
            or command.lookup_status in {'present', 'unknown'}
            or command.status in {'submitted_unknown', 'failed'} and command.lookup_status != 'absent')

    def evaluate(check):
        source, waited = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'GOV-A07' or source['role'] != 'Government' or source['purpose'] != 'action'
                or check.condition.condition_code != condition_code or check.condition.trigger != 'dependency_change'
                or tuple(ref.kind for ref in waited) != (('DecisionCommand',) if query_wait else ('RegulatoryCase', 'Submission'))
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']):
            raise TaskConflict('Government decision recovery replaces original case/final-submission wait')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, GovernmentDecisionConditionReading)
                or not isinstance(selected.context, ActionContext) or not isinstance(selected.reading, ActionReadView)
                or not isinstance(selected.original_context, ActionContext)
                or not isinstance(selected.original_action_input, dict) or not isinstance(selected.action_input, dict)):
            raise TaskConflict('Government decision recovery requires typed original/current sources and context')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        original_input, action_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
        try:
            if (set(original_input) != _FIELDS or set(action_input) != _FIELDS
                    or task_digest(original_input) != source['input_sha256']
                    or task_digest(selected.original_context.model_dump(mode='json')) != source['context_sha256']
                    or original_input['scope'] != action_input['scope'] or context.run_id != source['run_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'GOV-A07'
                    or context.execution_mode != 'llm' or reading._resolver.source_mode != 'formal'
                    or reading.organization_id != source['organization_id'] or context.business_time != check.signal.business_time
                    or context.operation_id == source['request_id']):
                raise TaskConflict('Government decision recovery changes original snapshot/scope/current invocation')
            scope = TypeAdapter(ScopeRef).validate_python(action_input['scope'])
            if not scope_covers(context.scope, scope):
                raise TaskConflict('Government decision recovery leaves original coverage')
            reading.check_method_context(context, 'GOV-A07')
            versions, proof_rows = [], []

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref or not scope_covers(scope, row.scope):
                    raise TaskConflict('Government decision recovery lacks exact scoped source versions')
                proof_rows.append(row)
                return row

            for raw, invocation in ((original_input, selected.original_context), (action_input, context)):
                rows = {field: read(ref_type(kind).model_validate(raw[field]), schema) for field, kind, schema in _BASES}
                case, submission, completion, basis = (rows[field] for field, _, _ in _BASES)
                command = read(basis.command_ref, GovDecisionCommandView)
                if (case.organization_id != source['organization_id'] or case.current_submission_ref != submission.ref
                        or submission.recipient_organization_id != source['organization_id']
                        or submission.applicant_id != case.applicant_id or submission.matter_ref != case.matter_ref
                        or submission.procedure_ref != case.procedure_ref or submission.jurisdiction_ref != case.jurisdiction_ref
                        or basis.case_ref != case.ref or basis.submission_ref != submission.ref
                        or basis.content_sha256 != submission.content_sha256 or basis.procedure_ref != case.procedure_ref
                        or basis.draft.case_ref != case.ref or basis.draft.submission_ref != submission.ref
                        or basis.draft.decision_basis_ref != basis.ref or basis.draft.covered_scope != scope
                        or basis.draft.prior_decision_ref is not None
                        or basis.signer_actor_id != invocation.actor_id or basis.signer_function_ref != invocation.function_ref
                        or command.case_ref != case.ref or command.submission_ref != submission.ref
                        or command.decision_basis_ref != basis.ref or command.operation_id != invocation.operation_id
                        or command.draft_sha256 != content_digest(basis.draft)):
                    raise TaskConflict('Government decision recovery substitutes agency/final content/signer/command draft')
                lists = {field: [ref_type(kind).model_validate(ref) for ref in raw[field]] for field, kind in _LISTS.items()}
                for refs in lists.values():
                    identities(refs)
                identities(case.decision_refs)
                decisions = [read(ref, GovFormalDecisionView) for ref in case.decision_refs]
                if any(row.case_ref != case.ref for row in decisions):
                    raise TaskConflict('Government decision recovery borrows another case formal decision')
                versions.append(dict(**rows, command=command, input_lists=lists,
                    same_business=[row for row in decisions if row.business_key == command.business_key]))
            old, current = versions
            old_case, case = old['case_ref'], current['case_ref']
            old_submission, submission = old['current_submission_ref'], current['current_submission_ref']
            old_basis, basis = old['decision_basis_ref'], current['decision_basis_ref']
            old_command, command = old['command'], current['command']
            if not query_wait and (tuple(waited) != (old_case.ref, old_submission.ref) or old['same_business'] or unresolved(old_command)
                    or old_case.status not in {'closed', 'withdrawn'}
                        and old_submission.status == 'active' and old_submission.receipt_status == 'received'):
                raise TaskConflict('Government decision recovery differs from original readiness gap without a formal fact')
            query = None
            if query_wait:
                if (tuple(waited) != (old_command.ref,) or old['same_business']
                        or old_command.official_decision_ref is not None or old_command.lookup_status == 'present'
                        or old_command.status == 'recorded'):
                    raise TaskConflict('Government decision recovery differs from original uncertain submitted command')
                if (condition_code == _QUERY_CODE and (old_command.status not in {'submitted_unknown', 'failed'}
                        or old_command.lookup_status == 'absent')):
                    raise TaskConflict('Government decision submission query lacks original uncertain submission gate')
                if (condition_code == _UNRESOLVED_CODE and (old_command.lookup_status != 'unknown'
                        or old_command.status in {'submitted_unknown', 'failed'})):
                    raise TaskConflict('Government decision unresolved lookup replaces original lookup gate order')
                if selected.command_query is None:
                    return 'waiting'
                query = GovernmentDecisionQueryRecord.model_validate(deepcopy(selected.command_query))
                if (query.source_identity_sha256 != task_digest(source) or query.run_id != source['run_id']
                        or query.organization_id != source['organization_id'] or query.command_ref != old_command.ref
                        or query.operation_id != old_command.operation_id or query.business_key != old_command.business_key
                        or query.draft_sha256 != old_command.draft_sha256 or query.queried_at != context.business_time
                        or query.queried_at.clock_ref != selected.original_context.business_time.clock_ref
                        or query.queried_at.offset < selected.original_context.business_time.offset):
                    raise TaskConflict('Government decision lookup replaces original command/business/draft/time')
                if query.result != 'absent':
                    return 'waiting'
                if command.lookup_status != 'absent':
                    return 'waiting'
            if (any(old[field].ref.key()[:2] != current[field].ref.key()[:2] for field, _, _ in _BASES)
                    or old_submission.content_sha256 != submission.content_sha256
                    or old_case.applicant_id != case.applicant_id or old_case.matter_ref != case.matter_ref
                    or old_case.procedure_ref.key()[:2] != case.procedure_ref.key()[:2]
                    or old_case.jurisdiction_ref.key()[:2] != case.jurisdiction_ref.key()[:2]
                    or old_command.ref.key()[:2] != command.ref.key()[:2] or old_command.business_key != command.business_key
                    or old_basis.signer_actor_id != basis.signer_actor_id
                    or old_basis.signer_function_ref.key()[:2] != basis.signer_function_ref.key()[:2]
                    or any(getattr(old_basis, field).key()[:2] != getattr(basis, field).key()[:2]
                        for field in ('signer_authorization_ref', 'decision_authority_ref', 'decision_rule_ref'))
                    or physical(old_basis.draft.model_dump(mode='json')) != physical(basis.draft.model_dump(mode='json'))
                    or identities(old_case.linked_submission_refs) - identities(case.linked_submission_refs)
                    or identities(old_case.task_refs) - identities(case.task_refs)
                    or identities(old_case.assessment_refs) - identities(case.assessment_refs)
                    or identities(old_case.unresolved_issue_refs) - identities(case.unresolved_issue_refs)
                    or identities(old_case.decision_refs) - identities(case.decision_refs)
                    or identities(old_basis.condition_basis_refs) - identities(basis.condition_basis_refs)
                    or any(identities(old['input_lists'][field]) - identities(current['input_lists'][field]) for field in _LISTS)):
                raise TaskConflict('Government decision recovery rewrites original command/terms/signer/retained history')
            if (current['same_business'] or unresolved(command) or case.status in {'closed', 'withdrawn'}
                    or submission.status != 'active' or submission.receipt_status != 'received'
                    or case.history_coverage != 'complete' or case.as_of != context.business_time):
                return 'waiting'
            now = context.business_time
            if any(row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                    or not row.effective_window.contains(now) for row in (case, submission, basis, command)):
                return 'unavailable'
            grant, function = reading.resolve(basis.signer_authorization_ref), reading.resolve(context.function_ref)
            if (not isinstance(grant, Authorization) or grant.ref != basis.signer_authorization_ref
                    or not isinstance(function, RoleAssignment) or function.function_ref != context.function_ref
                    or function.role != 'Government' or grant.actor_id != context.actor_id
                    or grant.organization_id != source['organization_id'] or grant.function_ref != context.function_ref
                    or 'GOV-A07' not in grant.action_ids or not grant.validity.contains(now)
                    or not any(scope_covers(covered, scope) for covered in grant.scopes)):
                raise TaskConflict('Government decision recovery lacks actual current signing actor authority')
            proof_refs = [*grant.basis_refs, *function.basis_refs]
            if query is not None:
                proof_refs.extend(query.evidence_refs)
            proof_refs.extend(ref for row in proof_rows for ref in walk_references(row) if ref.kind == 'Evidence')
            evidence = {}
            for ref in proof_refs:
                row = reading.resolve(ref)
                if not isinstance(row, EvidenceRecord) or row.source_kind == 'synthetic' or row.basis_kind != 'observed':
                    raise TaskConflict('Government decision recovery requires observed command/readiness/history evidence')
                evidence[ref.key()] = row.model_dump(mode='json')
            native = dict(source_identity=deepcopy(source), condition_code=condition_code,
                original_action_input=original_input, action_input=action_input,
                original_context=selected.original_context.model_dump(mode='json'),
                original_command=old_command.model_dump(mode='json'), command=command.model_dump(mode='json'),
                decision_sources=deepcopy(selected.decision_sources), unavailable_targets=deepcopy(selected.unavailable_targets),
                evidence=deepcopy(list(evidence.values())), context=context.model_copy(deep=True), reading=reading)
            if query is not None:
                native.update(command_query=query.model_dump(mode='json'))
            if validate_relation(**native) is not True:
                raise TaskConflict('Government decision recovery lacks native fresh command binding and retained formal history authentication')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('GOV-A07', condition_code, '1', frozenset({'dependency_change'}), evaluate)
