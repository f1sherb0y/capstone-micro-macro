"""Recover actual original Contractor handover/account history without clearing residual duties."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, ref_type
from src.actions.contracts.contractor_closeout_objects import (
    ContractorCloseoutContractView, ContractorHandoverProfileView,
    ContractorHandoverRequestView, ContractorFinalAccountView,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


HANDOVER_CODE = 'continue_original_handover_request'
ACCOUNT_CODE = 'continue_original_final_account'
_ROUTES = {HANDOVER_CODE: ('HandoverRequest', ContractorHandoverRequestView, 'handover_request_refs',
    'submit_handover', frozenset({'accepted', 'withdrawn', 'rejected'})),
    ACCOUNT_CODE: ('FinalAccount', ContractorFinalAccountView, 'final_account_refs',
    'propose_final_account', frozenset({'determined', 'withdrawn'}))}
_HISTORY_METADATA = {'ref', 'status', 'available_at', 'effective_window', 'evidence_refs'}
_ROLES = {'CONTRACTOR': 'Contractor', 'OWN': 'Owner', 'ENGINEER': 'Engineer',
    'ARCHITECT': 'Architect', 'QS': 'QS', 'GOV': 'Government', 'SUPPLIER': 'Supplier', 'BANK': 'Bank'}


@dataclass(frozen=True)
class ContractorCloseoutConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_context: ActionContext
    original_action_input: dict
    action_input: dict
    history_ref: Reference


def check_contractor_closeout_history(check, selected, validate_relation, *, terminal=False):
    source, code = check.source['identity'], check.condition.condition_code
    route = _ROUTES.get(code)
    if (route is None or source['action_id'] != 'CONTRACTOR-A11' or source['role'] != 'Contractor'
            or source['purpose'] != 'action' or check.condition.trigger != 'dependency_change'
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, ContractorCloseoutConditionReading)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)
            or not callable(validate_relation)):
        raise TaskConflict('Closeout recovery requires original typed history wait and private recipient')
    kind, schema, history_field, choice, terminal_statuses = route
    if tuple(ref.kind for ref in check.condition.object_refs) != (kind,):
        raise TaskConflict('Closeout recovery changes original handover/account selection')
    context, original_context, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original_context.model_dump(mode='json')) != source['context_sha256']
            or original_context.operation_id != source['request_id'] or context.run_id != source['run_id']
            or context.contract_ref != original_context.contract_ref or context.contract_ref.id != 'CONTRACTOR-A11'
            or context.execution_mode != 'llm' or context.scope != original_context.scope
            or raw['scope_ref'] != current_raw['scope_ref'] or context.business_time != check.signal.business_time
            or context.business_time.clock_ref != original_context.business_time.clock_ref
            or context.business_time.offset < original_context.business_time.offset
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and (raw != current_raw or context.actor_id != original_context.actor_id
                or context.function_ref != original_context.function_ref)
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Closeout recovery replaces original snapshot, scope or current read authority')
    reading.check_method_context(context, 'CONTRACTOR-A11')

    now = context.business_time

    def evidence(refs, *, at=None):
        if at is not None and (at.clock_ref != now.clock_ref or at.offset > now.offset):
            raise TaskConflict('Closeout recovery changes actual evidence-use clock or time')
        for evidence_ref in refs:
            row = reading.resolve(evidence_ref)
            if not isinstance(row, EvidenceRecord) or row.ref != evidence_ref:
                raise TaskConflict('Closeout recovery lacks exact original/current Evidence')
            window = row.effective_window
            if window is not None and (window.start.clock_ref != now.clock_ref
                    or window.end.clock_ref != now.clock_ref or window.start.offset > now.offset
                    or at is not None and not window.contains(at)):
                raise TaskConflict('Closeout recovery evidence is unavailable or invalid at actual use')

    def read(ref, expected, *, at=None, evidence_at=None):
        row = reading.resolve(ref)
        if not isinstance(row, expected) or getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref:
            raise TaskConflict('Closeout recovery lacks exact typed original/current sources')
        if at is not None and hasattr(row, 'available_at') and (row.available_at.clock_ref != at.clock_ref or row.available_at.offset > at.offset):
            raise TaskConflict('Closeout recovery injects a source unavailable at its original/query time')
        evidence(getattr(row, 'evidence_refs', []), at=evidence_at)
        return row

    def keys(refs):
        values = {ref.key() for ref in refs}
        if len(values) != len(refs):
            raise TaskConflict('Closeout recovery repeats original source versions')
        return values

    def authority(ref, actor, function_ref, organization_id, action_id, at, scope):
        grant, function = read(ref, Authorization), read(function_ref, RoleAssignment)
        if (grant.actor_id != actor or grant.organization_id != organization_id or grant.function_ref != function_ref
                or function.function_ref != function_ref or at.clock_ref != now.clock_ref or at.offset > now.offset
                or action_id not in grant.action_ids or function.role != _ROLES.get(action_id.split('-')[0])
                or grant.validity.start.clock_ref != at.clock_ref or grant.validity.end.clock_ref != at.clock_ref
                or not grant.validity.contains(at) or not any(scope_covers(item, scope) for item in grant.scopes)):
            raise TaskConflict('Closeout recovery lacks independent original author/working authority')
        for basis_ref in (*grant.basis_refs, *function.basis_refs):
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref], at=at)
            else:
                basis = reading.resolve(basis_ref)
                if (getattr(basis, 'ref', getattr(basis, 'function_ref', None)) != basis_ref
                        or hasattr(basis, 'available_at') and (basis.available_at.clock_ref != at.clock_ref
                            or basis.available_at.offset > at.offset)):
                    raise TaskConflict('Closeout recovery changes original typed authority basis or its availability')

    versions = []
    for values, invocation in ((raw, original_context), (current_raw, context)):
        at = original_context.business_time if terminal else invocation.business_time
        contract = read(ref_type('Contract').model_validate(values['contract_ref']), ContractorCloseoutContractView, at=at, evidence_at=at)
        profile = read(ref_type('HandoverProfile').model_validate(values['handover_profile_ref']), ContractorHandoverProfileView, at=at, evidence_at=at)
        evidence(profile.evidence_refs_received, at=at)
        if (contract.contractor_id != source['organization_id'] or contract.coverage != 'complete' or contract.as_of != at
                or not scope_covers(contract.scope, invocation.scope) or profile.contract_ref != contract.ref
                or profile.organization_id != source['organization_id'] or profile.scope != invocation.scope
                or profile.actor_id != invocation.actor_id or profile.function_ref != invocation.function_ref
                or (not terminal or values is raw) and profile.authority_ref not in invocation.authorization_refs
                or any(row.effective_window.start.clock_ref != at.clock_ref or row.effective_window.end.clock_ref != at.clock_ref
                    or not row.effective_window.contains(at) for row in (contract, profile))):
            raise TaskConflict('Closeout recovery changes original complete contract, profile or working scope')
        authority(profile.authority_ref, invocation.actor_id, invocation.function_ref, source['organization_id'],
            'CONTRACTOR-A11', at, invocation.scope)
        for input_field, field in (('as_built_refs', 'as_built_refs'), ('verification_refs', 'verification_refs'),
                ('defect_refs', 'defect_refs'), ('settlement_components', 'settlement_component_refs')):
            refs = [Reference.model_validate(ref) for ref in values[input_field]]
            if keys(refs) != keys(getattr(contract, field)):
                raise TaskConflict('Closeout recovery drops original configurations, verifications, defects or settlement items')
        versions.append(dict(contract=contract, profile=profile))
    old, current = versions
    if old['profile'].choice != choice:
        raise TaskConflict('Closeout history wait differs from its original proposal branch')
    for field in ('contractor_id', 'client_id', 'currency', 'scope'):
        if getattr(old['contract'], field) != getattr(current['contract'], field):
            raise TaskConflict('Closeout recovery changes original contract parties, currency or scope')
    if old['contract'].ref.key()[:2] != current['contract'].ref.key()[:2]:
        raise TaskConflict('Closeout recovery substitutes another contract identity')
    for field in ('obligation_refs', 'continuing_responsibility_refs', 'defect_refs'):
        before, after = getattr(old['contract'], field), getattr(current['contract'], field)
        if not {ref.key()[:2] for ref in before} <= {ref.key()[:2] for ref in after}:
            raise TaskConflict('Closeout recovery drops an original debt, defect or continuing responsibility')
        for ref in (*before, *after):
            reading.resolve(ref)
    first, businesses = None, set()
    for ref in getattr(old['contract'], history_field):
        row = read(ref, schema, at=original_context.business_time)
        business = (row.author_organization_id, row.business_key)
        if (row.contract_ref != old['contract'].ref or business in businesses
                or code == HANDOVER_CODE and row.author_organization_id != source['organization_id']):
            raise TaskConflict('Closeout recovery substitutes or duplicates original handover/account business history')
        businesses.add(business)
        if row.author_organization_id == source['organization_id'] and row.business_key == old['profile'].business_key:
            first = row
            break
    if first is None or tuple(check.condition.object_refs) != (first.ref,):
        raise TaskConflict('Closeout recovery differs from original first same-business history gate')
    if code == HANDOVER_CODE:
        if first.scope != original_context.scope or keys(first.as_built_refs) != keys(old['contract'].as_built_refs):
            raise TaskConflict('Closeout recovery rewrites original handover scope/configuration')
    elif (keys(old['profile'].component_refs) & keys(old['profile'].disputed_refs)
            or keys(first.component_refs) != keys(old['profile'].component_refs) | keys(old['profile'].disputed_refs)
            or keys(first.component_refs) != keys(old['contract'].settlement_component_refs)):
        raise TaskConflict('Closeout recovery rewrites original itemized account coverage')
    authority(first.author_authority_ref, first.author_actor_id, first.author_function_ref,
        first.author_organization_id, first.author_action_id, first.authored_at, first.scope)
    if (first.authored_at.clock_ref != original_context.business_time.clock_ref
            or first.authored_at.offset > first.available_at.offset
            or first.effective_window.start.clock_ref != first.authored_at.clock_ref
            or first.effective_window.end.clock_ref != first.authored_at.clock_ref
            or not first.effective_window.contains(first.authored_at)):
        raise TaskConflict('Closeout recovery replaces original history author chronology')
    ref = selected.history_ref
    if ref.key()[:2] != first.ref.key()[:2]:
        raise TaskConflict('Closeout query replaces the original physical request/account')
    history = read(ref, schema, at=context.business_time)
    if (first.model_dump(exclude=_HISTORY_METADATA) != history.model_dump(exclude=_HISTORY_METADATA)
            or first.status in terminal_statuses and first.status != history.status):
        raise TaskConflict('Closeout query rewrites original request/account content or known disposition')
    if (history.effective_window.start.clock_ref != now.clock_ref or history.effective_window.end.clock_ref != now.clock_ref
            or not history.effective_window.contains(now)):
        return 'unavailable', None
    if history.status not in terminal_statuses or not history.evidence_refs:
        return 'waiting', None
    if not terminal and ref.key() not in keys(getattr(current['contract'], history_field)):
        raise TaskConflict('Closeout query is absent from the actual current contract history')
    native_evidence = []
    for evidence_ref in history.evidence_refs:
        row = read(evidence_ref, EvidenceRecord)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Closeout query requires actual observed native history evidence')
        if row.effective_window is not None and (row.effective_window.start.clock_ref != now.clock_ref
                or row.effective_window.end.clock_ref != now.clock_ref or not row.effective_window.contains(now)):
            return 'unavailable', None
        native_evidence.append(row.model_dump(mode='json'))
    resolution = dict(schema_version='contractor-closeout-history-resolution.v1', condition_code=code,
        disposition=history.status, history=history.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original_context.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_contract=old['contract'].model_dump(mode='json'), current_contract=current['contract'].model_dump(mode='json'),
        sources=reading.evidence(), evidence=native_evidence)
    if validate_relation(source_identity=deepcopy(source), condition_code=code, terminal_closeout_history=terminal,
            resolution=deepcopy(resolution), context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Closeout recovery lacks native original branch/query/debt/defect/duty authentication')
    if not terminal and current['profile'].business_key == old['profile'].business_key:
        return 'waiting', None
    return 'ready', resolution


def contractor_original_closeout_history_profile(read_current, validate_relation, condition_code):
    if condition_code not in _ROUTES or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Closeout recovery requires an original history route and actual source/native callbacks')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_contractor_closeout_history(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('CONTRACTOR-A11', condition_code, '2', frozenset({'dependency_change'}), evaluate)
