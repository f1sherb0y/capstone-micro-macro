"""Resume the original cost task after independently authenticated authorization."""
from copy import deepcopy
from dataclasses import dataclass

from pydantic import TypeAdapter

from src.actions.contracts.common import ActionContext, EvidenceRecord, ScopeRef, ref_type
from src.actions.contracts.qs_cost_objects import (
    QSCostBriefView, QSCostOptionView, QSCostTaskView, QSCostScopeView,
    QSCostComparisonBasisView, QSQuantityBasisView, QSCostPriceView, QSCostCalculationView,
)
from src.actions.contracts.references import ActionReadView
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


_CODE = 'qs.cost.task_authorized'
_FIELDS = frozenset({'scope', 'brief_ref', 'option_ref', 'task_ref', 'cost_scope_ref',
    'quantity_basis_refs', 'price_refs', 'method_result_refs', 'comparison_basis_ref'})
_BASES = (('brief_ref', 'Brief', QSCostBriefView), ('option_ref', 'DesignOption', QSCostOptionView),
    ('task_ref', 'Task', QSCostTaskView), ('cost_scope_ref', 'CostScope', QSCostScopeView),
    ('comparison_basis_ref', 'ComparisonBasis', QSCostComparisonBasisView))


@dataclass(frozen=True)
class QSCostConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict


def qs_original_cost_task_profile(read_current, validate_relation):
    """Ready permits fresh costing; it approves no budget, quantity or expense."""
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('QS cost recovery requires actual sources and native authorization/history validation')

    def indexed(refs):
        rows = {ref.key()[:2]: ref for ref in refs}
        if len(rows) != len(refs):
            raise TaskConflict('QS cost recovery repeats a physical source')
        return rows

    def evaluate(check):
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'QS-A04' or source['role'] != 'QS' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 1 or old_refs[0].kind != 'Task'):
            raise TaskConflict('QS cost recovery substitutes original task wait or recipient')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, QSCostConditionReading) or not isinstance(selected.context, ActionContext)
                or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.original_action_input, dict)
                or not isinstance(selected.action_input, dict)):
            raise TaskConflict('QS cost recovery requires typed current reading and original snapshot input')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        try:
            old_input, action_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
            if (set(old_input) != _FIELDS or set(action_input) != _FIELDS or task_digest(old_input) != source['input_sha256']
                    or context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'QS-A04'
                    or context.execution_mode == 'offline_fixture' or reading._resolver.source_mode != 'formal'
                    or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                    or old_input['scope'] != action_input['scope']):
                raise TaskConflict('QS cost recovery changes original snapshot, scope or current invocation')
            scope, now = TypeAdapter(ScopeRef).validate_python(action_input['scope']), context.business_time
            if context.scope != scope:
                raise TaskConflict('QS cost recovery changes original estimate coverage')
            reading.check_method_context(context, 'QS-A04')
            proof_rows, proof_refs = [], []

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref or row.scope != scope:
                    raise TaskConflict('QS cost recovery lacks an exact scoped original/current source')
                proof_rows.append(row)
                return row

            versions = []
            for raw in (old_input, action_input):
                rows = {field: read(ref_type(kind).model_validate(raw[field]), schema) for field, kind, schema in _BASES}
                brief, option, task, cost_scope, comparison = (rows[field] for field, _, _ in _BASES)
                if (option.brief_ref != brief.ref or cost_scope.option_ref != option.ref or task.brief_ref != brief.ref
                        or task.option_ref != option.ref or task.cost_scope_ref != cost_scope.ref
                        or task.comparison_basis_ref != comparison.ref or task.organization_id != source['organization_id']
                        or any('cost_estimation' not in row.allowed_uses for row in (brief, option, task))):
                    raise TaskConflict('QS cost recovery substitutes original task, brief, design, comparison or permitted use')
                versions.append(rows)
            old, current = versions
            original, task = old['task_ref'], current['task_ref']
            if (original.ref != old_refs[0] or original.status not in {'waiting', 'withdrawn'}
                    or any(old[field].ref.key()[:2] != current[field].ref.key()[:2] for field, _, _ in _BASES)
                    or original.organization_id != task.organization_id or original.function_ref != task.function_ref
                    or task.function_ref != context.function_ref or task.authority_ref not in context.authorization_refs
                    or original.allowed_uses != task.allowed_uses or original.delivery_mode != task.delivery_mode):
                raise TaskConflict('QS cost recovery changes original costing task, organization, function or delivery mode')
            if task.status != 'authorized':
                return 'waiting'
            if any(row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                    or not row.effective_window.contains(now) for row in current.values()):
                return 'unavailable'
            for field, facts in (('brief_ref', ('allowed_uses', 'recipient_ids')),
                    ('option_ref', ('allowed_uses', 'limitations', 'author_actor_id', 'author_function_ref', 'author_authority_ref', 'author_action_id')),
                    ('cost_scope_ref', ('exclusions',)),
                    ('comparison_basis_ref', ('currency', 'region_id', 'delivery_code', 'pricing_time'))):
                if any(getattr(old[field], fact) != getattr(current[field], fact) for fact in facts):
                    raise TaskConflict('QS cost recovery rewrites original estimate terms, limitations or pricing basis')
            old_items = {row.line_key: row for row in old['cost_scope_ref'].items}
            items = {row.line_key: row for row in current['cost_scope_ref'].items}
            if old_items.keys() != items.keys():
                raise TaskConflict('QS cost recovery replaces the original complete cost-line set')
            for key, item in old_items.items():
                row = items[key]
                if (item.cost_component_ref.key()[:2] != row.cost_component_ref.key()[:2]
                        or any(getattr(item, fact) != getattr(row, fact) for fact in ('covered_scope', 'coverage_keys', 'predecessor_line_keys'))):
                    raise TaskConflict('QS cost recovery rewrites known original physical coverage')
                for field in ('quantity_basis_ref', 'price_ref'):
                    before, after = getattr(item, field), getattr(row, field)
                    if before is not None and (after is None or before.key()[:2] != after.key()[:2]):
                        raise TaskConflict('QS cost recovery drops known original line quantity/price identity')

            def authorize(ref, actor, function_ref, action, at, roles, organization=None):
                grant, function = reading.resolve(ref), reading.resolve(function_ref)
                if (not isinstance(grant, Authorization) or not isinstance(function, RoleAssignment)
                        or function.function_ref != function_ref or function.role not in roles
                        or grant.actor_id != actor or grant.function_ref != function_ref or action not in grant.action_ids
                        or at.clock_ref != now.clock_ref or at.offset > now.offset or not grant.validity.contains(at)
                        or organization is not None and grant.organization_id != organization
                        or not any(scope_covers(s, scope) for s in grant.scopes)):
                    raise TaskConflict('QS cost recovery lacks the original author or current QS task authority')
                supported = {'Architect': {'ARCHITECT-A04', 'ARCHITECT-A05', 'ARCHITECT-A13'},
                    'Engineer': {'ENGINEER-A04', 'ENGINEER-A05', 'ENGINEER-A13'}, 'QS': {'QS-A04', 'QS-A13'}}
                if action not in supported.get(function.role, set()):
                    raise TaskConflict('QS cost recovery changes original author function/action')
                proof_refs.extend([*grant.basis_refs, *function.basis_refs])

            authorize(task.authority_ref, context.actor_id, task.function_ref, 'QS-A04', now, {'QS'}, source['organization_id'])
            histories = {}
            for field, kind, schema, known_field in (
                    ('quantity_basis_refs', 'QuantityBasis', QSQuantityBasisView, 'quantity'),
                    ('price_refs', 'Price', QSCostPriceView, 'unit_rate'),
                    ('method_result_refs', 'MethodResult', QSCostCalculationView, None)):
                pair = []
                selected_refs = None
                for raw, bases in ((old_input, old), (action_input, current)):
                    refs = indexed([ref_type(kind).model_validate(value) for value in raw[field]])
                    if raw is action_input:
                        selected_refs = dict(refs)
                    # Waiting may precede the processor's completeness check.
                    # Preserve declared history even if not selected originally.
                    if known_field is not None:
                        declared_field = 'quantity_basis_ref' if known_field == 'quantity' else 'price_ref'
                        for item in bases['cost_scope_ref'].items:
                            ref = getattr(item, declared_field)
                            if ref is not None:
                                if ref.key()[:2] in refs and refs[ref.key()[:2]] != ref:
                                    raise TaskConflict('QS cost history selects two versions of one declared physical source')
                                refs[ref.key()[:2]] = ref
                    pair.append({key: read(ref, schema) for key, ref in refs.items()})
                before, after = pair
                if known_field is not None:
                    if not before.keys() <= after.keys():
                        raise TaskConflict('QS cost recovery drops original supplied quantity/price history')
                    for key, row in before.items():
                        if getattr(row, known_field).state == 'known':
                            facts = ('quantity', 'line_key', 'measurement_rule_code', 'mode', 'proxy_method_ref', 'limitations') if known_field == 'quantity' else (
                                'unit_rate', 'quantity_unit', 'measurement_rule_code', 'coverage_keys', 'excluded_coverage_keys', 'region_id', 'delivery_code', 'source_locator')
                            if (row.cost_component_ref.key()[:2] != after[key].cost_component_ref.key()[:2]
                                    or any(getattr(row, fact) != getattr(after[key], fact) for fact in facts)):
                                raise TaskConflict('QS cost recovery rewrites a known original quantity, unit rate or measurement basis')
                    expected = {getattr(item, 'quantity_basis_ref' if known_field == 'quantity' else 'price_ref') for item in items.values()}
                    expected.discard(None)
                    if {ref.key() for ref in selected_refs.values()} != {ref.key() for ref in expected}:
                        raise TaskConflict('QS cost successor lacks the exact complete current line quantity/price set')
                histories[field] = {'original': [row.model_dump(mode='json') for row in before.values()],
                    'current': [row.model_dump(mode='json') for row in after.values()]}
            for row in proof_rows:
                proof_refs.extend(row.evidence_refs)
                if isinstance(row, (QSCostOptionView, QSQuantityBasisView, QSCostCalculationView)):
                    roles = {'Architect', 'Engineer'} if isinstance(row, QSCostOptionView) else {'QS'} if isinstance(row, QSCostCalculationView) else {'Architect', 'Engineer', 'QS'}
                    authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref, row.author_action_id,
                        getattr(row, 'calculated_at', row.available_at), roles,
                        source['organization_id'] if isinstance(row, QSCostCalculationView) else None)
                for field in ('quantity', 'unit_rate', 'known_subtotal'):
                    value = getattr(row, field, None)
                    if value is not None and value.state == 'known':
                        proof_refs.append(value.value.basis_ref)
                if isinstance(row, QSCostCalculationView) and row.complete_total is not None:
                    proof_refs.append(row.complete_total.basis_ref)
            observed = {}
            for ref in proof_refs:
                evidence = reading.resolve(ref)
                if not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic' or evidence.basis_kind != 'observed':
                    raise TaskConflict('QS cost recovery requires actual observed native authorization and cost evidence')
                observed[ref.key()] = evidence.model_dump(mode='json')
            if validate_relation(source_identity=deepcopy(source), original_action_input=old_input, action_input=action_input,
                    original_sources={field: row.model_copy(deep=True) for field, row in old.items()},
                    current_sources={field: row.model_copy(deep=True) for field, row in current.items()},
                    cost_history=deepcopy(histories), evidence=deepcopy(list(observed.values())),
                    context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('QS cost recovery lacks native original-task authorization and complete cost-history validation')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('QS-A04', _CODE, '1', frozenset({'dependency_change'}), evaluate)
