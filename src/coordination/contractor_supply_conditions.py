"""Authenticate original supply commitments and keep remaining work/payment duties."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.catalog import ActionContract
from src.actions.contracts.common import ActionContext, EvidenceRecord, Reference, TimeWindow
from src.actions.contracts.contractor_planning_objects import (
    ContractorWorkMandateView, ContractorPlanningProfileView, ContractorSupplyCommitmentView,
    ContractorSupplyRequirementView,
    ContractorSupplyOfferView, ContractorSupplyTermsView,
    ContractorSupplySupplierView,
)
from src.actions.contracts.references import ActionReadView
from src.actions.roles import contractor_planning as planning_role
from src.coordination.contractor_closeout_conditions import ContractorCloseoutConditionReading
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.coordination import contractor_plan_conditions as plan_conditions
from src.coordination.contractor_plan_conditions import CYCLE_CODE, CAPACITY_CODE


CODE = 'contractor-plan-existing-supply-commitment-query-original-order'
LIMIT_CODE = 'contractor-plan-original-preparation-or-contract-procurement-limit'
RECIPIENT_CODE = 'contractor-plan-no-current-supply-inquiry-recipient'
_KINDS = {CODE: ('SupplyCommitment',), LIMIT_CODE: ('Contract', 'WorkAuthorization'),
    RECIPIENT_CODE: ('SupplyRequirement',), CYCLE_CODE: ('Dependency',), CAPACITY_CODE: ('ContractorCapacity',)}
_DISPOSITIONS = {'committed', 'paid', 'released'}
_INPUT_FIELDS = ('dependency_refs', 'design_refs', 'supplier_offer_refs', 'work_method_refs')
_METADATA = {'ref', 'mandate_ref', 'status', 'available_at', 'effective_window', 'evidence_refs'}


@dataclass(frozen=True)
class ContractorSupplyConditionReading(ContractorCloseoutConditionReading):
    contract: ActionContract | None = None


def check_contractor_supply_history(check, selected, validate_relation, *, terminal=False):
    if check.condition.condition_code == CYCLE_CODE:
        return plan_conditions.check_contractor_plan_cycle(check, selected, validate_relation, terminal=terminal)
    if check.condition.condition_code == CAPACITY_CODE:
        return plan_conditions.check_contractor_plan_capacity(check, selected, validate_relation, terminal=terminal)
    source, code = check.source['identity'], check.condition.condition_code
    if (source['action_id'] != 'CONTRACTOR-A05' or source['role'] != 'Contractor' or source['purpose'] != 'action'
            or code not in _KINDS or check.condition.trigger != 'dependency_change'
            or not check.condition.object_refs or len(check.condition.object_refs) != 1 and code != RECIPIENT_CODE
            or any(ref.kind not in _KINDS.get(code, ()) for ref in check.condition.object_refs)
            or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
            or not isinstance(selected, ContractorSupplyConditionReading) or not callable(validate_relation)
            or not isinstance(selected.context, ActionContext) or not isinstance(selected.original_context, ActionContext)
            or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.history_ref, Reference)
            or terminal and code != CODE):
        raise TaskConflict('Supply recovery requires original typed commitment query and private Contractor')
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    if (task_digest(raw) != source['input_sha256'] or task_digest(original.model_dump(mode='json')) != source['context_sha256']
            or original.operation_id != source['request_id'] or context.run_id != source['run_id']
            or context.contract_ref != original.contract_ref or context.contract_ref.id != 'CONTRACTOR-A05'
            or context.scope != original.scope or context.execution_mode != 'llm'
            or context.business_time != check.signal.business_time or context.business_time.clock_ref != original.business_time.clock_ref
            or context.business_time.offset < original.business_time.offset
            or (context.operation_id != source['request_id'] if terminal else context.operation_id == source['request_id'])
            or terminal and (raw != current_raw or context.actor_id != original.actor_id or context.function_ref != original.function_ref)
            or reading.organization_id != source['organization_id'] or reading._resolver.source_mode != 'formal'):
        raise TaskConflict('Supply recovery changes original snapshot, scope, time or current reading authority')
    reading.check_method_context(context, 'CONTRACTOR-A05')
    contract = selected.contract
    if not isinstance(contract, ActionContract) or contract.action_id != 'CONTRACTOR-A05' or contract.role != 'Contractor':
        raise TaskConflict('Supply recovery lacks its actual original registered action contract')
    original_input, current_input = contract.validate_input(raw), contract.validate_input(current_raw)
    if original_input.work_basis.kind != current_input.work_basis.kind or original_input.authorized_scope_ref != current_input.authorized_scope_ref:
        raise TaskConflict('Supply recovery promotes preparation to construction or changes authorized work scope')

    def validate_evidence(refs, at, *, historic=False):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord) or row.ref != ref:
                raise TaskConflict('Supply recovery substitutes an exact Evidence source')
            if row.effective_window is not None:
                window = row.effective_window
                if (window.start.clock_ref != at.clock_ref or window.end.clock_ref != at.clock_ref
                        or window.start.offset > at.offset or not historic and not window.contains(at)):
                    raise TaskConflict('Supply recovery evidence is not valid at its original invocation or signing time')

    def read(ref, schema, *, at, evidence_at=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Supply recovery lacks exact typed original/current sources')
        if hasattr(row, 'available_at') and (row.available_at.clock_ref != at.clock_ref or row.available_at.offset > at.offset):
            raise TaskConflict('Supply recovery injects unavailable or unrelated-clock source history')
        window = getattr(row, 'effective_window', None)
        if window is not None and (window.start.clock_ref != at.clock_ref or window.end.clock_ref != at.clock_ref):
            raise TaskConflict('Supply recovery changes original source window clock')
        point = getattr(row, 'authored_at', at) if evidence_at is None else evidence_at
        if point.clock_ref != at.clock_ref or point.offset > at.offset:
            raise TaskConflict('Supply recovery injects a future or unrelated signing time')
        validate_evidence(getattr(row, 'evidence_refs', []), point, historic=isinstance(row, ContractorSupplyCommitmentView))
        if isinstance(row, ContractorSupplyCommitmentView):
            validate_evidence([row.amount.basis_ref], at, historic=True)
        return row

    def keys(refs):
        result = {ref.key() for ref in refs}
        if len(result) != len(refs) or len({ref.key()[:2] for ref in refs}) != len(refs):
            raise TaskConflict('Supply recovery repeats physical commitment/source history')
        return result

    def same_commitment(before, after):
        return (before.model_dump(exclude=_METADATA) == after.model_dump(exclude=_METADATA)
            and before.mandate_ref.key()[:2] == after.mandate_ref.key()[:2]
            and (before.status != 'released' or after.status == 'released')
            and (before.status != 'paid' or after.status in {'paid', 'released'}))

    versions = []
    for values, invocation in ((original_input, original), (current_input, context)):
        at = original.business_time if terminal else invocation.business_time
        basis = values.work_basis
        mandate_ref = basis.contract_ref if basis.kind == 'contract' else basis.authorization_ref
        mandate = read(mandate_ref, ContractorWorkMandateView, at=at)
        profile = read(mandate.planning_profile_ref, ContractorPlanningProfileView, at=at)
        if (mandate.organization_id != source['organization_id'] or mandate.mandate_kind != basis.kind
                or profile.organization_id != source['organization_id'] or profile.mandate_ref != mandate.ref
                or profile.choice != ('request_quote' if code == RECIPIENT_CODE else 'accept_supply_offer')
                or code != RECIPIENT_CODE and not mandate.procurement_history_complete):
            raise TaskConflict('Supply recovery changes original mandate acceptance branch or loses complete history')
        keys(mandate.procurement_history_refs)
        versions.append(dict(mandate=mandate, profile=profile))
    old, current = versions
    if (old['mandate'].ref.key()[:2] != current['mandate'].ref.key()[:2]
            or any(getattr(old['mandate'], field) != getattr(current['mandate'], field)
                for field in ('mandate_kind', 'region_id', 'object_type', 'work_type', 'special_condition_codes', 'required_qualification_codes'))):
        raise TaskConflict('Supply recovery substitutes original work mandate, region or qualification domain')
    for field in _INPUT_FIELDS:
        before, after = getattr(original_input, field), getattr(current_input, field)
        keys(before); keys(after)
        if not {ref.key()[:2] for ref in before} <= {ref.key()[:2] for ref in after}:
            raise TaskConflict('Supply recovery omits original dependency, design, offer or work-method history')
    old_requirements, current_requirements = old['profile'].requirement_refs, current['profile'].requirement_refs
    keys(old_requirements); keys(current_requirements)
    actual_requirements = {ref.key()[:2]: ref for ref in current_requirements}
    if not {ref.key()[:2] for ref in old_requirements} <= set(actual_requirements):
        raise TaskConflict('Supply recovery omits original supply requirement duties')
    windows = []
    for ref in old_requirements:
        before = read(ref, ContractorSupplyRequirementView, at=original.business_time)
        after = read(actual_requirements[ref.key()[:2]], ContractorSupplyRequirementView,
            at=original.business_time if terminal else context.business_time)
        if (before.mandate_ref != old['mandate'].ref or after.mandate_ref != current['mandate'].ref
                or any(getattr(before, field) != getattr(after, field) for field in
                    ('product_ref', 'quantity', 'destination_ref', 'inspection_rule_ref', 'payment_rule_ref', 'substitution_authority_ref'))):
            raise TaskConflict('Supply recovery rewrites original product, quantity, site, inspection or payment duties')
        if code == RECIPIENT_CODE:
            if before.allowed_supplier_ids != after.allowed_supplier_ids:
                raise TaskConflict('Inquiry recovery substitutes original independently eligible supplier organizations')
            for field in ('delivery_window_ref', 'receiving_window_ref'):
                before_ref, after_ref = getattr(before, field), getattr(after, field)
                if before_ref.key()[:2] != after_ref.key()[:2]:
                    raise TaskConflict('Inquiry recovery substitutes the original delivery or site receiving window')
                before_window, after_window = reading.resolve(before_ref), reading.resolve(after_ref)
                if not isinstance(before_window, TimeWindow) or not isinstance(after_window, TimeWindow):
                    raise TaskConflict('Inquiry recovery lacks actual original/current finite delivery and receiving windows')
                windows.append(dict(field=field, original_ref=before_ref.model_dump(mode='json'),
                    current_ref=after_ref.model_dump(mode='json'), original=before_window.model_dump(mode='json'),
                    current=after_window.model_dump(mode='json')))
    original_gate = planning_role.recheck_original_contractor_supply_wait(original, original_input, reading, condition_code=code)
    if original_gate.get('resume_condition', {}).get('object_refs') != list(check.condition.object_refs):
        raise TaskConflict('Supply wait differs from original first same-offer/terms commitment')
    first_ref, ref = check.condition.object_refs[0], selected.history_ref
    if ref.key()[:2] != first_ref.key()[:2]:
        raise TaskConflict('Supply query substitutes original physical commitment')
    suppliers = []
    if code == RECIPIENT_CODE:
        keys(list(check.condition.object_refs))
        first = read(first_ref, ContractorSupplyRequirementView, at=original.business_time)
        history = read(ref, ContractorSupplyRequirementView, at=context.business_time)
        if (first.ref != old_requirements[0] or ref != actual_requirements[first_ref.key()[:2]]
                or history.mandate_ref != current['mandate'].ref):
            raise TaskConflict('Inquiry query must name the actual first original/current requirement')
        supplier_refs = current['profile'].supplier_refs
        keys(supplier_refs)
        if not supplier_refs:
            return 'waiting', None
        for supplier_ref in supplier_refs:
            row = read(supplier_ref, ContractorSupplySupplierView, at=context.business_time)
            if not row.effective_window.contains(context.business_time):
                return 'unavailable', None
            if not row.evidence_refs:
                return 'waiting', None
            suppliers.append(row)
    elif code == CODE:
        first = read(first_ref, ContractorSupplyCommitmentView, at=original.business_time)
        history = read(ref, ContractorSupplyCommitmentView, at=context.business_time)
        if not same_commitment(first, history) or history.mandate_ref.key()[:2] != old['mandate'].ref.key()[:2]:
            raise TaskConflict('Supply query rewrites original business, offer, terms, amount or established payment/release')
        query_mandate = read(history.mandate_ref, ContractorWorkMandateView, at=context.business_time)
        if query_mandate.organization_id != source['organization_id'] or query_mandate.mandate_kind != old['mandate'].mandate_kind:
            raise TaskConflict('Supply query borrows another Contractor or promotes preparation authority')
    else:
        first = read(first_ref, ContractorWorkMandateView, at=original.business_time)
        history = read(ref, ContractorWorkMandateView, at=context.business_time)
        if first.ref != old['mandate'].ref or history.ref != current['mandate'].ref:
            raise TaskConflict('Procurement limit query must name the actual original/current work mandate')
        # The original purchase stays the same; a cheaper unrelated offer cannot
        # impersonate an independently revised procurement authorization.
        offers, terms = [], []
        for version, at in ((old, original.business_time), (current, context.business_time)):
            offer_ref = version['profile'].selected_offer_ref
            if offer_ref is None:
                raise TaskConflict('Procurement limit recovery loses the original selected offer')
            offer = read(offer_ref, ContractorSupplyOfferView, at=at)
            offers.append(offer)
            terms.append(read(offer.terms_ref, ContractorSupplyTermsView, at=at, evidence_at=offer.authored_at))
        excluded = {'ref', 'available_at', 'effective_window', 'evidence_refs'}
        def purchase_content(row):
            # Permit actual new versions of the same physical linked sources;
            # immutable prices, quantities, parties and terms still match.
            # Native validation authenticates the contents of both versions.
            def physical(value):
                if isinstance(value, dict):
                    if set(value) == {'kind', 'id', 'version'}:
                        return {key: value[key] for key in ('kind', 'id')}
                    return {key: physical(child) for key, child in value.items()}
                if isinstance(value, list):
                    return [physical(child) for child in value]
                return value
            return physical(row.model_dump(mode='json', exclude=excluded))
        if (offers[0].ref.key()[:2] != offers[1].ref.key()[:2]
                or purchase_content(offers[0]) != purchase_content(offers[1])
                or terms[0].ref.key()[:2] != terms[1].ref.key()[:2]
                or purchase_content(terms[0]) != purchase_content(terms[1])):
            raise TaskConflict('Procurement limit recovery substitutes original offer, gross price or agreed terms')
    if not history.effective_window.contains(context.business_time):
        return 'unavailable', None
    if (code == CODE and history.status not in _DISPOSITIONS) or code != RECIPIENT_CODE and not history.evidence_refs:
        return 'waiting', None
    before_refs, after_refs = old['mandate'].procurement_history_refs, current['mandate'].procurement_history_refs
    if not {ref.key()[:2] for ref in before_refs} <= {ref.key()[:2] for ref in after_refs}:
        raise TaskConflict('Supply recovery drops original procurement and payment history')
    if not terminal:
        if code == CODE and (ref.key() not in keys(after_refs) or history.mandate_ref != current['mandate'].ref):
            raise TaskConflict('Supply query is absent from actual complete current mandate history')
        actual, businesses = {}, set()
        for commitment_ref in after_refs:
            row = read(commitment_ref, ContractorSupplyCommitmentView, at=context.business_time)
            if row.mandate_ref != current['mandate'].ref or row.business_key in businesses:
                raise TaskConflict('Supply recovery repeats or borrows current procurement business history')
            businesses.add(row.business_key); actual[commitment_ref.key()[:2]] = row
        for commitment_ref in before_refs:
            before = read(commitment_ref, ContractorSupplyCommitmentView, at=original.business_time)
            if not same_commitment(before, actual[commitment_ref.key()[:2]]):
                raise TaskConflict('Supply recovery rewrites prior commitment amount, business or disposition')
    evidence = []
    evidence_refs = {value.key(): value for value in history.evidence_refs}
    for supplier in suppliers:
        evidence_refs.update({value.key(): value for value in supplier.evidence_refs})
    for evidence_ref in evidence_refs.values():
        row = read(evidence_ref, EvidenceRecord, at=context.business_time)
        if row.source_kind == 'synthetic' or row.basis_kind != 'observed':
            raise TaskConflict('Supply query requires actual observed independent native evidence')
        if row.effective_window is not None and not row.effective_window.contains(context.business_time):
            return 'unavailable', None
        evidence.append(row.model_dump(mode='json'))
    current_result = None
    if not terminal:
        current_result = planning_role.plan_work_and_supply(context, current_input, reading)
        if current_result.get('kind') != 'completed':
            return 'waiting', None
        contract.validate_decision(current_input, current_result['payload'])
        current_result = contract.result_adapter.validate_python(current_result).model_dump(mode='json')
    resolution = dict(schema_version='contractor-supply-history-resolution.v1', condition_code=code,
        disposition=history.status if code == CODE else ('current_eligible_inquiry_recipients'
            if code == RECIPIENT_CODE else 'current_authorized_procurement_limit'),
        history=history.model_dump(mode='json'), original_action_input=raw, action_input=current_raw,
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_mandate=old['mandate'].model_dump(mode='json'), current_mandate=current['mandate'].model_dump(mode='json'),
        original_gate=contract.result_adapter.validate_python(original_gate).model_dump(mode='json'),
        current_result=current_result, sources=reading.evidence(), evidence=evidence,
        windows=windows, suppliers=[row.model_dump(mode='json') for row in suppliers])
    if validate_relation(source_identity=deepcopy(source), condition_code=code, terminal_supply_history=terminal,
            resolution=deepcopy(resolution), context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Supply recovery lacks native procurement/remaining work/payment/current authority authentication')
    return 'ready', resolution


def contractor_original_supply_profile(read_current, validate_relation, condition_code=CODE):
    if condition_code not in _KINDS or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Supply recovery requires original guarded history route and independent native validator')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_contractor_supply_history(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('CONTRACTOR-A05', condition_code, '2', frozenset({'dependency_change'}), evaluate)
