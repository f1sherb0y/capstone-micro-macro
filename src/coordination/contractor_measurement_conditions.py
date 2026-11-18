"""Recover immutable measurement requests while retaining net work and cash history."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import ActionContext, EvidenceRecord, Known, Reference, TimeWindow, ref_type, walk_references
from src.actions.contracts import contractor_payment_objects as payment_objects
from src.actions.contracts.contractor_payment_objects import (
    ContractorMeasurementApplicationView, ContractorPaymentContractView, ContractorSettlementRuleView,
    ContractorSettlementProcedureView, ContractorValuationBasisView, ContractorWorkRecordView,
    ContractorMeasurementWorkRecordView,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.contractor_closeout_conditions import ContractorCloseoutConditionReading
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


CODE = 'continue_original_measurement_application'
_TERMINAL = {'certified', 'withdrawn', 'rejected'}
_INPUT_FIELDS = ('work_record_refs', 'certificate_refs', 'obligation_refs', 'account_refs', 'execution_refs')


@dataclass(frozen=True)
class ContractorMeasurementConditionReading(ContractorCloseoutConditionReading):
    """Original saved input/context and the selected actual application query."""


def check_contractor_measurement_history(check, selected, validate_relation, *, terminal=False):
    source = check.source['identity']
    if (source['action_id'] != 'CONTRACTOR-A10' or source['role'] != 'Contractor' or source['purpose'] != 'action'
            or check.condition.condition_code != CODE or check.condition.trigger != 'dependency_change'
            or tuple(ref.kind for ref in check.condition.object_refs) != ('MeasurementApplication',)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, ContractorMeasurementConditionReading) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)):
        raise TaskConflict('Measurement recovery requires original typed A10 wait and private Contractor')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id'] or context.run_id != source['run_id']
            or context.contract_ref != original.contract_ref or context.contract_ref.id != 'CONTRACTOR-A10'
            or context.scope != original.scope or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and (raw != current_raw or context.actor_id != original.actor_id or context.function_ref != original.function_ref)
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Measurement recovery changes original snapshot, working scope or current read authority')
    reading.check_method_context(context, 'CONTRACTOR-A10')
    now = context.business_time

    def evidence(refs, *, at=None):
        if at is not None and (at.clock_ref != now.clock_ref or at.offset > now.offset):
            raise TaskConflict('Measurement recovery changes actual evidence-use clock or time')
        for evidence_ref in refs:
            row = reading.resolve(evidence_ref)
            if not isinstance(row, EvidenceRecord) or row.ref != evidence_ref:
                raise TaskConflict('Measurement recovery lacks exact original/current Evidence')
            window = row.effective_window
            if window is not None and (window.start.clock_ref != now.clock_ref or window.end.clock_ref != now.clock_ref
                    or window.start.offset > now.offset or at is not None and not window.contains(at)):
                raise TaskConflict('Measurement recovery evidence is unavailable or invalid at actual use')

    def keys(refs):
        result = {ref.key() for ref in refs}
        if len(result) != len(refs) or len({ref.key()[:2] for ref in refs}) != len(refs):
            raise TaskConflict('Measurement recovery repeats physical source histories')
        return result

    def read(ref, schema=None, *, at=None, evidence_at=None):
        row = reading.resolve(ref)
        if (schema is not None and not isinstance(row, schema)
                or hasattr(row, 'ref') and row.ref != ref
                or hasattr(row, 'function_ref') and not hasattr(row, 'ref') and row.function_ref != ref):
            raise TaskConflict('Measurement recovery lacks exact typed original/current sources')
        if at is not None and hasattr(row, 'available_at') and (row.available_at.clock_ref != at.clock_ref or row.available_at.offset > at.offset):
            raise TaskConflict('Measurement recovery injects sources unavailable at their recorded time')
        evidence(getattr(row, 'evidence_refs', []), at=evidence_at)
        return row

    versions = []
    for values, invocation in ((raw, original), (current_raw, context)):
        at = original.business_time if terminal else invocation.business_time
        contract = read(ref_type('Contract').model_validate(values['contract_ref']), ContractorPaymentContractView, at=at, evidence_at=at)
        rule = read(ref_type('SettlementRule').model_validate(values['settlement_rule_ref']), ContractorSettlementRuleView, at=at, evidence_at=at)
        if (contract.contractor_id != source['organization_id'] or not scope_covers(contract.scope, invocation.scope)
                or contract.settlement_rule_ref != rule.ref or rule.contract_ref != contract.ref
                or rule.organization_id != source['organization_id'] or rule.actor_id != invocation.actor_id
                or rule.function_ref != invocation.function_ref or rule.scope != invocation.scope
                or contract.as_of != at or not contract.measurement_history_complete
                or not isinstance(contract.effective, Known) or contract.effective.value is not True
                or (not terminal or values is raw) and rule.authority_ref not in invocation.authorization_refs
                or any(row.effective_window.start.clock_ref != at.clock_ref or row.effective_window.end.clock_ref != at.clock_ref
                    or not row.effective_window.contains(at) for row in (contract, rule))):
            raise TaskConflict('Measurement recovery changes original effective contract, rule or complete history')
        grant, function = read(rule.authority_ref, Authorization), read(rule.function_ref, RoleAssignment)
        if (grant.organization_id != source['organization_id'] or grant.actor_id != invocation.actor_id
                or grant.function_ref != invocation.function_ref or function.function_ref != invocation.function_ref
                or function.role != 'Contractor' or grant.validity.start.clock_ref != at.clock_ref
                or grant.validity.end.clock_ref != at.clock_ref
                or 'CONTRACTOR-A10' not in grant.action_ids or not grant.validity.contains(at)
                or not any(scope_covers(item, invocation.scope) for item in grant.scopes)):
            raise TaskConflict('Measurement recovery lacks original independent Contractor action authority')
        for basis_ref in (*grant.basis_refs, *function.basis_refs):
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref], at=at)
            else:
                read(basis_ref, at=at)
        evidence(rule.basis_refs, at=at)
        for field in _INPUT_FIELDS:
            refs = [Reference.model_validate(ref) for ref in values[field]]
            keys(refs)
            for ref in refs:
                read(ref, at=at)
        keys(contract.measurement_application_refs)
        versions.append(dict(contract=contract, rule=rule))
    old, current = versions
    if (old['contract'].ref.key()[:2] != current['contract'].ref.key()[:2]
            or any(getattr(old['contract'], field) != getattr(current['contract'], field) for field in ('contractor_id', 'client_id', 'currency'))):
        raise TaskConflict('Measurement recovery changes original physical contract, parties or currency')
    for field in ('measurement_application_refs', 'certificate_refs', 'obligation_refs', 'execution_refs'):
        before, after = getattr(old['contract'], field), getattr(current['contract'], field)
        keys(before); keys(after)
        if not {ref.key()[:2] for ref in before} <= {ref.key()[:2] for ref in after}:
            raise TaskConflict('Measurement recovery drops original application, certificate, debt or payment history')
        for ref in (*before, *after):
            read(ref)
    for field in _INPUT_FIELDS:
        if not {Reference.model_validate(ref).key()[:2] for ref in raw[field]} <= {Reference.model_validate(ref).key()[:2] for ref in current_raw[field]}:
            raise TaskConflict('Measurement recovery omits original work, obligations, accounts or executions')
    draft = old['rule'].measurement
    if (old['rule'].choice != 'apply_measurement' or draft is None or draft.contract_ref != old['contract'].ref
            or keys(draft.prior_application_refs) != keys(old['contract'].measurement_application_refs)
            or not draft.lines or not draft.basis_refs):
        raise TaskConflict('Measurement wait bypasses original apply-measurement and complete history gates')
    procedure = read(old['rule'].procedure_ref, ContractorSettlementProcedureView, at=original.business_time, evidence_at=original.business_time)
    if (procedure.contract_ref != old['contract'].ref or not procedure.effective_window.contains(original.business_time)
            or procedure.effective_window.start.clock_ref != original.business_time.clock_ref
            or procedure.effective_window.end.clock_ref != original.business_time.clock_ref
            or 'apply_measurement' not in procedure.permitted_choices
            or not isinstance(procedure.permitted, Known) or procedure.permitted.value is not True or not procedure.recipient_ids):
        raise TaskConflict('Measurement wait lacks original independently permitted settlement procedure')
    window = read(draft.measurement_window_ref, TimeWindow)
    if (window.start.clock_ref != original.business_time.clock_ref or window.end.clock_ref != original.business_time.clock_ref
            or window.end.offset > original.business_time.offset):
        raise TaskConflict('Measurement wait includes work from a future or unrelated clock')
    works, physical = {}, set()
    evidence(draft.basis_refs, at=original.business_time)
    for line in draft.lines:
        basis = read(line.valuation_basis_ref, ContractorValuationBasisView, at=original.business_time, evidence_at=original.business_time)
        quantity = decimal_fraction(line.quantity.value)
        if (not scope_covers(original.scope, line.scope_ref) or not line.work_record_refs
                or basis.contract_ref != old['contract'].ref or not scope_covers(basis.scope, line.scope_ref)
                or basis.ref.key() not in keys(procedure.valuation_basis_refs)
                or basis.effective_window.start.clock_ref != original.business_time.clock_ref
                or basis.effective_window.end.clock_ref != original.business_time.clock_ref
                or not basis.effective_window.contains(original.business_time)
                or not isinstance(basis.effective, Known) or basis.effective.value is not True
                or line.quantity.unit != basis.quantity_unit or quantity <= 0):
            raise TaskConflict('Measurement wait changes original valuation units, authorization or work scope')
        keys(line.work_record_refs)
        evidence([line.quantity.basis_ref], at=original.business_time)
        total = 0
        for ref in line.work_record_refs:
            work = read(ref, ContractorWorkRecordView, at=original.business_time)
            if (not isinstance(work, ContractorMeasurementWorkRecordView) or work.occurred_at is None
                    or not work.occurrence_evidence_refs):
                raise TaskConflict('Measurement wait lacks original actual work occurrence and observed evidence')
            if (work.occurred_at.clock_ref != original.business_time.clock_ref
                    or work.occurred_at.offset > work.available_at.offset or not window.contains(work.occurred_at)):
                raise TaskConflict('Measurement wait replaces actual occurrence with source availability or another period')
            keys(work.occurrence_evidence_refs)
            evidence(work.occurrence_evidence_refs, at=work.occurred_at)
            for evidence_ref in work.occurrence_evidence_refs:
                occurrence = read(evidence_ref, EvidenceRecord)
                if occurrence.basis_kind != 'observed' or occurrence.source_kind == 'synthetic':
                    raise TaskConflict('Measurement wait lacks actual observed native work-occurrence provenance')
            gross, net = decimal_fraction(work.gross_quantity.value), decimal_fraction(work.net_quantity.value)
            if (ref.key() in works or work.physical_work_key in physical
                    or not scope_covers(line.scope_ref, work.scope)
                    or work.gross_quantity.unit != basis.quantity_unit or work.net_quantity.unit != basis.quantity_unit
                    or not 0 <= net <= gross or work.work_kind == 'rework' and (work.original_work_record_ref is None or net != 0)
                    or work.work_kind == 'new_work' and work.original_work_record_ref is not None):
                raise TaskConflict('Measurement wait repeats physical work or turns rework into new net quantity')
            evidence([work.gross_quantity.basis_ref, work.net_quantity.basis_ref], at=work.occurred_at)
            if work.original_work_record_ref is not None:
                prior_work = read(work.original_work_record_ref, ContractorWorkRecordView, at=original.business_time)
                if prior_work.ref == work.ref or prior_work.work_kind != 'new_work' or not scope_covers(line.scope_ref, prior_work.scope):
                    raise TaskConflict('Measurement recovery substitutes original rework provenance')
            works[ref.key()] = work
            physical.add(work.physical_work_key)
            total += net
        if quantity > total or len(line.work_record_refs) > 1 and quantity != total:
            raise TaskConflict('Measurement recovery exceeds actual net work or substitutes physical slice allocation')
    if set(works) != keys([Reference.model_validate(ref) for ref in raw['work_record_refs']]):
        raise TaskConflict('Measurement wait differs from original exact supplied work')
    try:
        payment_objects.validate_contractor_measurement_work_events(works.values())
    except ValueError as error:
        raise TaskConflict('Measurement wait changes original execution event provenance') from error
    first, businesses = None, set()
    for ref in draft.prior_application_refs:
        application = read(ref, ContractorMeasurementApplicationView, at=original.business_time)
        if application.organization_id != source['organization_id'] or application.request.contract_ref != old['contract'].ref or application.business_key in businesses:
            raise TaskConflict('Measurement wait duplicates or borrows original application business')
        businesses.add(application.business_key)
        if application.business_key == old['rule'].business_key:
            first = application
            break
    if (first is None or tuple(check.condition.object_refs) != (first.ref,)
            or first.request.model_dump(exclude={'prior_application_refs'}) != draft.model_dump(exclude={'prior_application_refs'})):
        raise TaskConflict('Measurement wait differs from original first same-business immutable request')
    ref = selected.history_ref
    if ref.key()[:2] != first.ref.key()[:2]:
        raise TaskConflict('Measurement query substitutes original physical application')
    history = read(ref, ContractorMeasurementApplicationView, at=context.business_time)
    for request_ref in walk_references(history.request):
        read(request_ref)
    query_contract = read(history.request.contract_ref, ContractorPaymentContractView, at=context.business_time)
    if (query_contract.ref.key()[:2] != old['contract'].ref.key()[:2]
            or any(getattr(query_contract, field) != getattr(old['contract'], field) for field in ('contractor_id', 'client_id', 'currency'))):
        raise TaskConflict('Measurement query borrows another original contract or payer')
    metadata = {'ref', 'request', 'status', 'available_at', 'effective_window', 'evidence_refs'}
    if (first.model_dump(exclude=metadata) != history.model_dump(exclude=metadata)
            or first.request.model_dump(exclude={'contract_ref'}) != history.request.model_dump(exclude={'contract_ref'})
            or history.request.contract_ref.key()[:2] != first.request.contract_ref.key()[:2]
            or first.status in _TERMINAL and history.status != first.status):
        raise TaskConflict('Measurement query rewrites original request, measured quantities or known disposition')
    if (history.effective_window.start.clock_ref != now.clock_ref or history.effective_window.end.clock_ref != now.clock_ref
            or not history.effective_window.contains(now)):
        return 'unavailable', None
    if history.status not in _TERMINAL or not history.evidence_refs:
        return 'waiting', None
    if not terminal and (ref.key() not in keys(current['contract'].measurement_application_refs)
            or history.request.contract_ref != current['contract'].ref):
        raise TaskConflict('Measurement query is absent from actual current contract history')
    if not terminal:
        actual, businesses = {}, set()
        for application_ref in current['contract'].measurement_application_refs:
            application = read(application_ref, ContractorMeasurementApplicationView, at=context.business_time)
            if (application.organization_id != source['organization_id'] or application.request.contract_ref != current['contract'].ref
                    or application.business_key in businesses):
                raise TaskConflict('Measurement recovery duplicates or borrows actual current application history')
            businesses.add(application.business_key)
            actual[application_ref.key()[:2]] = application
        for application_ref in old['contract'].measurement_application_refs:
            before = read(application_ref, ContractorMeasurementApplicationView, at=original.business_time)
            after = actual[application_ref.key()[:2]]
            if (before.model_dump(exclude=metadata) != after.model_dump(exclude=metadata)
                    or before.request.model_dump(exclude={'contract_ref'}) != after.request.model_dump(exclude={'contract_ref'})
                    or before.status in _TERMINAL and after.status != before.status):
                raise TaskConflict('Measurement recovery rewrites prior application quantities or established disposition')
    native_evidence = []
    for evidence_ref in history.evidence_refs:
        row = read(evidence_ref, EvidenceRecord)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Measurement query requires independent observed actual native evidence')
        if row.effective_window is not None and (row.effective_window.start.clock_ref != now.clock_ref
                or row.effective_window.end.clock_ref != now.clock_ref or not row.effective_window.contains(now)):
            return 'unavailable', None
        native_evidence.append(row.model_dump(mode='json'))
    resolution = dict(schema_version='contractor-measurement-history-resolution.v1',condition_code=CODE,
        disposition=history.status,history=history.model_dump(mode='json'),original_action_input=raw,action_input=current_raw,
        original_context=original.model_dump(mode='json'),context=context.model_dump(mode='json'),
        original_contract=old['contract'].model_dump(mode='json'),current_contract=current['contract'].model_dump(mode='json'),
        sources=reading.evidence(),evidence=native_evidence)
    if validate_relation(source_identity=deepcopy(source),condition_code=CODE,terminal_measurement_history=terminal,
            resolution=deepcopy(resolution),context=context.model_copy(deep=True),reading=reading) is not True:
        raise TaskConflict('Measurement recovery lacks native work/application/certificate/debt/cash/current authority authentication')
    if not terminal and current['rule'].business_key == first.business_key:
        return 'waiting', None
    return 'ready', resolution


def contractor_original_measurement_profile(read_current, validate_relation, condition_code=CODE):
    if condition_code != CODE or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Measurement recovery requires original guarded reader and actual native validator')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_contractor_measurement_history(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('CONTRACTOR-A10', CODE, '3', frozenset({'dependency_change'}), evaluate)
