"""SUPPLIER-A06 validates actual inputs and queries original execution facts."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known, TimeWindow
from src.actions.contracts.supplier_execution_objects import (
    SupplierExecutionTaskView, SupplierExecutionProfileView, SupplierProductionReleaseView,
    SupplierProductionGateView, SupplierProductionRequirementView, SupplierProductionMethodView,
    SupplierProductionRuleView, SupplierActualResourceView, SupplierProductionAllocationView,
    SupplierProductionReservationView, SupplierActualInventoryView, SupplierActualMaterialView,
    SupplierActualInventoryAllocationView, SupplierProductionRequestView, SupplierProductionExecutionView,
    SupplierStockMovementView, SupplierExecutionOrderView, SupplierExternalDeliveryView,
    SupplierProductionRecoveryView,
    SupplierGoodsReceiptRuleView, SupplierGoodsReceiptView, SupplierMaintenanceIssueView,
    SupplierResourceObservationView, validate_supplier_reconciliation_task,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _known, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def request_supply_execution(context, action_input, reading):
    now, org, scope = context.business_time, reading.organization_id, context.scope

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('supplier-execution-clock-alignment')

    def evidence(refs, *, at=None, historic=False):
        point = now if at is None else at
        clock(point)
        if point.offset > now.offset:
            _needs('received_original_supply_execution_evidence_time')
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord):
                _unsupported('supplier-execution-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                if row.effective_window.start.offset > now.offset:
                    _needs('received_original_supply_execution_evidence', [ref])
                if (at is not None or not historic) and not row.effective_window.contains(point):
                    _needs('original_supply_execution_evidence_valid_at_use', [ref])

    def read(ref, schema, historic=False, linked=False, *, at=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema):
            _unsupported('supplier-execution-projection:' + ref.kind)
        if hasattr(row, 'scope') and not linked and not scope_covers(scope, row.scope):
            raise ValueError('Supply execution source widens original authorized scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset:
                _needs('received_original_supply_execution_source', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            if not historic and not row.effective_window.contains(now):
                _needs('current_original_supply_execution_source', [ref])
        if at is not None:
            clock(at)
            if at.offset > now.offset:
                _needs('received_original_supply_execution_evidence_time', [ref])
            if at.offset > row.available_at.offset:
                raise ValueError('Supply execution source receipt precedes original event')
        evidence(getattr(row, 'evidence_refs', []), at=at, historic=historic)
        return row

    def true(value):
        return isinstance(value, Known) and value.value is True

    def quantity(value, unit, positive=False, *, at=None, historic=False):
        evidence([value.basis_ref], at=at, historic=historic)
        q = decimal_fraction(value.value)
        if value.unit != unit or q < 0 or positive and q == 0:
            raise ValueError('Actual supply quantities require original units and nonnegative amounts')
        return q

    def covers(window, inner):
        clock(window.start); clock(window.end); clock(inner.start); clock(inner.end)
        if window.bounds != 'closed_open' or inner.bounds != 'closed_open':
            _unsupported('supplier-execution-half-open-window-domain')
        return window.start.offset <= inner.start.offset and window.end.offset >= inner.end.offset

    def authorize(profile):
        grant = read(profile.authority_ref, Authorization, linked=True)
        function = read(context.function_ref, RoleAssignment, linked=True)
        if (profile.authority_ref not in context.authorization_refs or grant.actor_id != context.actor_id
                or grant.organization_id != org or grant.function_ref != context.function_ref
                or function.function_ref != context.function_ref or function.role != 'Supplier' or 'SUPPLIER-A06' not in grant.action_ids
                or not any(scope_covers(s, scope) for s in grant.scopes)):
            raise ValueError('Supply execution substitutes actual actor/function/scope authority')
        clock(grant.validity.start)
        if not grant.validity.contains(now):
            _needs('current_original_supply_execution_authority', [grant.ref])
        for basis_ref in [*grant.basis_refs, *function.basis_refs]:
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref])
            else:
                reading.resolve(basis_ref)

    def complete(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, **fields,
            'note': profile.note + ' Input/query/maintenance request only. Core determines actual consumption, work in progress, pending inspection, loss, lineage and cost once. Procurement creates no own production; arrival does not imply usable stock or quality approval.'}}

    def wait(code, refs):
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
            'trigger': 'dependency_change', 'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    def technical(code):
        raise ObservationGap({'kind': 'technical_error', 'error': {'kind': 'unrecorded',
            'correlation_id': context.operation_id, 'code': code}, 'retryability': 'unknown'})

    def history(refs):
        keys(refs); rows = []; operations = set(); business = set(); events = set(); movement_keys = set()
        all_consumed = {}
        for ref in refs:
            row = read(ref, SupplierProductionExecutionView, historic=True)
            if setup.kind == 'reconciliation':
                original_task = read(row.task_ref, SupplierExecutionTaskView, historic=True)
                validate_supplier_reconciliation_task(original_task, task, row,
                    run_id=context.run_id, organization_id=org)
            elif row.task_ref != task.ref:
                raise ValueError('New production history substitutes another exact task version')
            if (row.organization_id != org or row.run_id != context.run_id
                    or row.operation_id in operations or row.business_key in business):
                raise ValueError('Production history repeats or substitutes original organization/run/task/command')
            operations.add(row.operation_id); business.add(row.business_key)
            request = read(row.request_ref, SupplierProductionRequestView, historic=True)
            if (request.organization_id != org or request.task_ref != row.task_ref or request.run_id != row.run_id
                    or request.operation_id != row.operation_id or request.business_key != row.business_key
                    or request.scope != row.scope or content_digest(request) != row.request_sha256):
                raise ValueError('Production history changes original submitted request identity or content')
            keys([i.allocation_ref for i in request.inputs]); keys([r.resource_ref for r in request.resources])
            if row.status == 'recorded':
                if row.query_status != 'present' or row.core_event_id is None or row.recorded_at is None or row.core_event_id in events:
                    raise ValueError('Recorded production needs original unique core event and receipt time')
                clock(row.recorded_at); events.add(row.core_event_id)
                if row.recorded_at.offset > row.available_at.offset or row.recorded_at.offset > now.offset or not row.movement_refs:
                    raise ValueError('Production receipt is future or omits actual stock movements')
                evidence(row.evidence_refs, at=row.recorded_at)
                requested = {i.allocation_ref.key():i for i in request.inputs}; consumed = {}
                keys(row.movement_refs)
                for movement_ref in row.movement_refs:
                    movement = read(movement_ref, SupplierStockMovementView, historic=True, at=row.recorded_at)
                    if (movement.organization_id != org or movement.execution_ref != row.ref
                            or movement.core_event_id != row.core_event_id or movement.physical_movement_key in movement_keys):
                        raise ValueError('Stock history repeats or substitutes original physical movement/event')
                    movement_keys.add(movement.physical_movement_key)
                    q = quantity(movement.quantity, movement.quantity.unit, at=row.recorded_at)
                    if q == 0 or not movement.lineage_batch_refs:
                        raise ValueError('Actual stock movement needs positive quantity and original batch lineage')
                    keys(movement.lineage_batch_refs); keys(movement.source_allocation_refs)
                    if not keys(movement.source_allocation_refs) <= set(requested):
                        raise ValueError('Stock movement substitutes original submitted input allocations')
                    if movement.kind == 'input_consumed':
                        if len(movement.source_allocation_refs) != 1:
                            raise ValueError('Actual input consumption needs explicit per-allocation quantity')
                        key = movement.source_allocation_refs[0].key(); original = requested[key]
                        if original.batch_ref.key() not in keys(movement.lineage_batch_refs):
                            raise ValueError('Input movement replaces original material batch lineage')
                        quantity(movement.quantity, original.quantity.unit, at=row.recorded_at)
                        consumed[key] = consumed.get(key, Fraction(0)) + q
                        if consumed[key] > quantity(original.quantity, original.quantity.unit, historic=True):
                            raise ValueError('Actual movements consume one submitted material allocation twice')
                        allocation = read(original.allocation_ref, SupplierActualInventoryAllocationView, historic=True, linked=True)
                        if allocation.task_ref != row.task_ref or allocation.batch_ref != original.batch_ref or allocation.organization_id != org:
                            raise ValueError('Consumed allocation changes original actual material/task identity')
                        physical = (allocation.ref.kind, allocation.ref.id)
                        all_consumed[physical] = all_consumed.get(physical,Fraction(0)) + q
                        if all_consumed[physical] > quantity(allocation.quantity, movement.quantity.unit, historic=True):
                            raise ValueError('Original production commands consume the same physical allocation twice')
                if task.mode == 'rework' and not keys(task.source_rework_batch_refs) <= {
                        r.key() for i in request.inputs for r in [i.batch_ref]}:
                    raise ValueError('Rework history drops original damaged batch lineage')
            elif row.core_event_id is not None or row.movement_refs:
                raise ValueError('Unknown/rejected/failed production cannot carry invented recorded stock')
            rows.append(row)
        return rows

    try:
        setup = action_input.execution_setup
        task = read(action_input.task_ref, SupplierExecutionTaskView, historic=setup.kind == 'reconciliation')
        profile = read(task.profile_ref, SupplierExecutionProfileView)
        if (task.organization_id != org or profile.task_ref != task.ref or profile.organization_id != org
                or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref or profile.scope != scope):
            raise ValueError('Supply execution changes original task, organization or acting author')
        authorize(profile)
        for refs in (action_input.available_input_refs, action_input.upstream_delivery_refs, action_input.prior_execution_refs):
            keys(refs)

        if profile.choice == 'request_maintenance':
            if profile.maintenance_resource_ref is None or not profile.issue_refs:
                _needs('original_actual_resource_maintenance_issue')
            resource = read(profile.maintenance_resource_ref, SupplierActualResourceView, linked=True)
            if resource.organization_id != org:
                raise ValueError('Maintenance request targets another organization resource')
            keys(profile.issue_refs)
            for ref in profile.issue_refs:
                issue = read(ref, SupplierMaintenanceIssueView)
                observation = read(issue.observation_ref, SupplierResourceObservationView, historic=True)
                clock(observation.observed_at)
                if (issue.organization_id != org or issue.resource_ref != resource.ref or issue.status == 'resolved'
                        or observation.organization_id != org or observation.resource_ref != resource.ref
                        or not true(observation.actual) or observation.observed_at.offset > now.offset):
                    raise ValueError('Maintenance substitutes original actual resource fault or observation')
                if observation.observed_at.offset > observation.available_at.offset:
                    raise ValueError('Resource observation receipt precedes its actual observation')
                evidence(observation.evidence_refs, at=observation.observed_at)
            return complete('request_maintenance', resource_ref=resource.ref, issue_refs=profile.issue_refs)

        if setup.kind == 'reconciliation':
            if profile.choice != 'reconcile_execution' or not setup.execution_refs or not keys(setup.execution_refs) <= keys(action_input.prior_execution_refs):
                raise ValueError('Production reconciliation must query original existing execution IDs')
            history(setup.execution_refs)
            return complete('reconcile_execution', execution_refs=setup.execution_refs)

        clock(task.as_of)
        if task.history_coverage != 'complete' or task.as_of != now:
            _needs('complete_current_original_supply_task_history')
        if (keys(action_input.prior_execution_refs) != keys(task.prior_execution_refs)
                or keys(action_input.upstream_delivery_refs) != keys(task.upstream_delivery_refs)):
            _needs('complete_original_supply_executions_and_external_deliveries')

        if setup.kind == 'purchase':
            if profile.choice != 'reconcile_upstream' or task.mode != 'purchase' or task.purchase_order_ref != setup.purchase_order_ref:
                raise ValueError('External delivery reconciliation cannot create manufacture or replace original purchase')
            order = read(setup.purchase_order_ref, SupplierExecutionOrderView, linked=True)
            rule = read(setup.receipt_rule_ref, SupplierGoodsReceiptRuleView)
            if (order.buyer_id != org or order.supplier_id == org or not true(order.effective)
                    or rule.order_ref != order.ref or rule.buyer_id != org or not true(rule.permitted)):
                _needs('independent_effective_upstream_order_and_goods_receipt_authority')
            if not true(rule.supported):
                _unsupported('original_external_goods_receipt_rule_support')
            clock(order.as_of)
            if order.history_coverage != 'complete' or order.as_of != now:
                _needs('complete_current_original_upstream_delivery_history')
            if not action_input.upstream_delivery_refs or not keys(action_input.upstream_delivery_refs) <= keys(order.delivery_refs):
                raise ValueError('External reconciliation requires original deliveries of this effective order')
            keys([l.line_ref for l in order.lines]); lines = {l.line_ref.key():l for l in order.lines}
            commands = set(); business = set(); events = set(); receipt_events = set(); receipt_ids = set()
            for ref in action_input.upstream_delivery_refs:
                delivery = read(ref, SupplierExternalDeliveryView, historic=True, linked=True)
                if (delivery.order_ref != order.ref or delivery.buyer_id != org or delivery.supplier_id != order.supplier_id
                        or delivery.command_id in commands or delivery.business_key in business):
                    raise ValueError('External delivery repeats or substitutes original order/parties/command')
                commands.add(delivery.command_id); business.add(delivery.business_key)
                if delivery.status in {'arrived', 'receipt_recorded', 'rejected'}:
                    if delivery.core_event_id is None or delivery.core_event_id in events or not delivery.lines:
                        raise ValueError('Actual external delivery needs distinct original core event and physical lines')
                    events.add(delivery.core_event_id)
                keys([l.batch_ref for l in delivery.lines]); actual = {}
                for line in delivery.lines:
                    if line.order_line_ref.key() not in lines:
                        raise ValueError('External delivery invents an original order line')
                    quantity(line.actual_quantity, lines[line.order_line_ref.key()].product.quantity.unit, positive=True, historic=True)
                    actual[(line.order_line_ref.key(), line.batch_ref.key(), line.product_ref.key())] = decimal_fraction(line.actual_quantity.value)
                received = {}; keys(delivery.receipt_refs)
                if delivery.status == 'receipt_recorded' and not delivery.receipt_refs:
                    _needs('original_recorded_external_goods_receipt', [delivery.ref])
                for receipt_ref in delivery.receipt_refs:
                    receipt = read(receipt_ref, SupplierGoodsReceiptView, historic=True, linked=True)
                    if (receipt.delivery_ref != delivery.ref or receipt.order_ref != order.ref or receipt.buyer_id != org
                            or receipt.command_id != delivery.command_id or receipt.business_key != delivery.business_key
                            or receipt.core_event_id in receipt_events or (receipt_ref.kind, receipt_ref.id) in receipt_ids):
                        raise ValueError('Goods receipt repeats or changes original delivery command/physical receipt')
                    receipt_events.add(receipt.core_event_id); receipt_ids.add((receipt_ref.kind, receipt_ref.id))
                    if receipt.status == 'accepted' and rule.inspection_required:
                        if not receipt.inspection_evidence_refs:
                            _needs('original_required_inspection_basis_of_recorded_goods_receipt', [receipt.ref])
                        evidence(receipt.inspection_evidence_refs, historic=True)
                    for line in receipt.lines:
                        key = (line.order_line_ref.key(), line.batch_ref.key(), line.product_ref.key())
                        if key not in actual:
                            raise ValueError('Goods receipt substitutes original actual delivery product or batch')
                        q = quantity(line.actual_quantity, lines[line.order_line_ref.key()].product.quantity.unit, positive=True, historic=True)
                        received[key] = received.get(key, Fraction(0)) + q
                        if received[key] > actual[key]:
                            raise ValueError('Partial receipts repeat or exceed original actual delivered quantity')
                        if receipt.status == 'accepted' and line.product_ref != lines[line.order_line_ref.key()].product.product_ref:
                            raise ValueError('Accepted goods receipt substitutes an unagreed original product specification')
            return complete('reconcile_upstream', delivery_refs=action_input.upstream_delivery_refs)

        if setup.kind != 'production' or profile.choice not in {'execute', 'rebalance'} or task.mode == 'purchase':
            raise ValueError('Production requires original manufacture/rework task and production setup')
        rows = history(action_input.prior_execution_refs)
        pending = [r.ref for r in rows if r.status == 'submitted_unknown' or r.query_status in {'unknown', 'not_queried'}]
        if pending:
            return wait('query_original_production_execution_before_replay', pending)
        existing = [r.ref for r in rows if r.operation_id == context.operation_id]
        if existing:
            return wait('continue_original_production_operation', existing)
        for row in rows:
            if row.status == 'failed':
                if row.recovery_ref is None:
                    technical('original-production-command-failed-requires-explicit-recovery')
                recovery = read(row.recovery_ref, SupplierProductionRecoveryView)
                if (recovery.execution_ref != row.ref or recovery.organization_id != org or recovery.task_ref != task.ref
                        or recovery.authority_ref not in context.authorization_refs or recovery.new_operation_id != context.operation_id
                        or not true(recovery.original_effects_absent) or not true(recovery.retry_permitted)
                        or row.query_status in {'unknown', 'not_queried'}):
                    _needs('explicit_authorized_recovery_after_original_production_effect_query', [row.ref])
                authorize(recovery)
        if task.state not in {'released', 'working'} or not task.execution_window.contains(now):
            _needs('current_original_supply_task_execution_window')
        if task.production_method_ref != setup.method_ref:
            raise ValueError('Production setup replaces original task consequence method')
        release = read(setup.release_ref, SupplierProductionReleaseView)
        if (release.organization_id != org or release.task_ref != task.ref or release.method_ref != setup.method_ref
                or release.status != 'released' or not covers(release.effective_window, task.execution_window)):
            _needs('actual_current_core_production_release')
        gate = read(release.gate_ref, SupplierProductionGateView)
        clock(gate.as_of)
        if (gate.task_ref != task.ref or gate.release_ref != release.ref or gate.as_of != now
                or gate.coverage != 'complete' or not true(gate.satisfied)):
            _needs('complete_current_core_production_gates')
        for ref in gate.requirement_refs:
            req = read(ref, SupplierProductionRequirementView)
            if req.task_ref != task.ref or not true(req.satisfied):
                _needs('current_original_production_requirement', [ref])
        keys(gate.requirement_refs)
        method = read(setup.method_ref, SupplierProductionMethodView)
        rule = read(method.consequence_rule_ref, SupplierProductionRuleView)
        if method.mode != task.mode or not true(method.supported) or rule.method_ref != method.ref or not true(rule.supported):
            _unsupported('original_production_conversion_and_consequence_method_support')
        if method.accelerated and not true(rule.acceleration_modeled):
            _unsupported('original_production_acceleration_not_modeled')
        evidence([rule.conversion_basis_ref, rule.throughput_basis_ref, rule.loss_basis_ref, rule.quality_basis_ref, rule.cost_basis_ref])
        if quantity(task.remaining_target, method.output_unit, positive=True) == 0 or not profile.resources:
            _needs('remaining_original_production_target_and_actual_nonzero_resources')
        selected_allocations = [read(ref, SupplierProductionAllocationView) for ref in action_input.available_input_refs]
        keys([row.resource_ref for row in selected_allocations]); keys([r.resource_ref for r in profile.resources])
        by_pool = {row.resource_ref.key():row for row in selected_allocations}
        if keys([r.resource_ref for r in profile.resources]) != set(by_pool):
            raise ValueError('Production intention drops or replaces selected original resource allocations')
        total_resource = Fraction(0)
        for proposed in profile.resources:
            allocation = by_pool[proposed.resource_ref.key()]
            pool = read(proposed.resource_ref, SupplierActualResourceView, linked=True)
            window = read(proposed.window_ref, TimeWindow)
            if (allocation.organization_id != org or allocation.task_ref != task.ref or allocation.status not in {'reserved', 'available'}
                    or pool.organization_id != org or pool.resource_kind != method.resource_kind or not true(pool.actually_present)
                    or allocation.as_of != now or pool.as_of != now or pool.coverage != 'complete'
                    or proposed.scope_ref != task.scope or not window.contains(now)
                    or not covers(allocation.window, window) or not covers(task.execution_window, window)):
                _needs('actual_current_original_production_resource_and_exclusive_allocation')
            if pool.pending_execution_refs:
                return wait('query_original_resource_production_before_reallocation', pool.pending_execution_refs)
            q = quantity(proposed.quantity, method.minimum_resource.unit, positive=True)
            if q > quantity(allocation.quantity, proposed.quantity.unit, positive=True):
                raise ValueError('Production intention exceeds original resource allocation')
            actual_capacity = _known(pool.actual_capacity, 'actual_present_production_capacity')
            reservations = []; events = set(); keys(pool.reservation_refs)
            for ref in pool.reservation_refs:
                original = read(ref, SupplierProductionReservationView, linked=True)
                if original.resource_ref != pool.ref or original.core_event_id in events:
                    raise ValueError('Production reservations repeat an original core event or physical pool')
                events.add(original.core_event_id)
                quantity(original.quantity, proposed.quantity.unit)
                clock(original.window.start); clock(original.window.end)
                if original.window.bounds != 'closed_open':
                    _unsupported('production-reservation-half-open-window-domain')
                reservations.append(original)
            bound = [r for r in reservations if r.ref == allocation.reservation_ref]
            if (len(bound) != 1 or bound[0].allocation_ref != allocation.ref or bound[0].task_ref != task.ref
                    or bound[0].quantity != allocation.quantity or bound[0].window != allocation.window or bound[0].status != 'reserved'):
                raise ValueError('Production allocation lacks matching original exclusive core reservation')
            boundaries = {window.start.offset, window.end.offset}
            for row in reservations:
                if row.status == 'reserved' and row.window.start.offset < window.end.offset and row.window.end.offset > window.start.offset:
                    boundaries.update({max(window.start.offset,row.window.start.offset),min(window.end.offset,row.window.end.offset)})
            for tick in sorted(boundaries)[:-1]:
                occupied = sum((decimal_fraction(r.quantity.value) for r in reservations
                    if r.status == 'reserved' and r.window.start.offset <= tick < r.window.end.offset),Fraction(0))
                if occupied > quantity(actual_capacity, proposed.quantity.unit):
                    _needs('actual_exclusive_production_capacity_for_current_window')
            total_resource += q
        if total_resource < quantity(method.minimum_resource, method.minimum_resource.unit, positive=True):
            _needs('original_production_minimum_nonzero_resource_inputs')

        inventory = read(action_input.inventory_ref, SupplierActualInventoryView, linked=True)
        clock(inventory.as_of)
        if inventory.organization_id != org or inventory.as_of != now or inventory.coverage != 'complete':
            _needs('complete_current_actual_production_inventory_snapshot')
        if inventory.pending_execution_refs:
            return wait('query_original_inventory_production_before_reuse', inventory.pending_execution_refs)
        keys([p.batch_ref for p in inventory.positions]); keys([i.allocation_ref for i in profile.inputs])
        recipe = {i.product_ref.key():i for i in method.input_recipe}; keys([i.product_ref for i in method.input_recipe])
        actual_inputs = {}; batch_totals = {}; used_events = set()
        for position in inventory.positions:
            unit = position.actual.unit
            actual = quantity(position.actual,unit); usable = quantity(position.usable,unit); reserved = quantity(position.reserved,unit)
            if usable > actual or reserved > actual:
                raise ValueError('Actual inventory usable/reserved quantities exceed original physical stock')
            held = Fraction(0); ledger_events = set(); keys(position.allocation_refs)
            for ref in position.allocation_refs:
                row = read(ref, SupplierActualInventoryAllocationView, linked=True)
                clock(row.as_of)
                if (row.organization_id != org or row.inventory_ref != inventory.ref or row.batch_ref != position.batch_ref
                        or row.as_of != now or row.core_event_id in ledger_events):
                    raise ValueError('Stock reservation ledger replaces original batch, snapshot or core event')
                ledger_events.add(row.core_event_id)
                original = quantity(row.quantity,unit); used = quantity(row.used_quantity,unit)
                if used > original:
                    raise ValueError('Actual stock allocation consumed quantity exceeds original reservation')
                if row.status == 'unknown':
                    _needs('known_original_stock_allocation_disposition', [row.ref])
                if row.status == 'reserved': held += original - used
            if held != reserved:
                raise ValueError('Current reserved stock differs from complete original allocation ledger')
            if position.state == 'usable' and held > usable:
                _needs('actual_usable_stock_for_original_exclusive_reservations', [inventory.ref])
        for proposed in profile.inputs:
            allocation = read(proposed.allocation_ref, SupplierActualInventoryAllocationView)
            batch = read(proposed.batch_ref, SupplierActualMaterialView)
            positions = [p for p in inventory.positions if p.batch_ref == proposed.batch_ref]
            if (allocation.organization_id != org or allocation.task_ref != task.ref or allocation.inventory_ref != inventory.ref
                    or allocation.batch_ref != batch.ref or allocation.purpose != task.mode or allocation.status != 'reserved'
                    or batch.organization_id != org or not true(batch.actual_received) or len(positions) != 1
                    or allocation.core_event_id in used_events):
                raise ValueError('Production input substitutes actual batch, task, reserved allocation or original core event')
            used_events.add(allocation.core_event_id); position = positions[0]
            if (position.product_ref != batch.product_ref or position.state != batch.state or position.actual != batch.actual_quantity
                    or position.usable != batch.usable or allocation.ref.key() not in keys(position.allocation_refs)):
                raise ValueError('Actual production batch differs from complete original inventory snapshot')
            rework_source = task.mode == 'rework' and batch.ref.key() in keys(task.source_rework_batch_refs)
            if batch.state != ('awaiting_rework' if rework_source else 'usable'):
                _needs('actual_inspected_usable_material_or_original_rework_source', [batch.ref])
            unit = batch.actual_quantity.unit; q = quantity(proposed.quantity, unit, positive=True)
            if q > quantity(allocation.quantity, unit, positive=True) - quantity(allocation.used_quantity,unit):
                raise ValueError('Production input exceeds original reserved material allocation')
            if batch.product_ref.key() not in recipe:
                raise ValueError('Production input is absent from original supported material recipe')
            ingredient = recipe[batch.product_ref.key()]
            if ingredient.unit != unit:
                raise ValueError('Production conversion changes original ingredient units')
            batch_totals[batch.ref.key()] = batch_totals.get(batch.ref.key(),Fraction(0)) + q
            if batch_totals[batch.ref.key()] > min(quantity(position.reserved,unit),
                    quantity(position.actual if rework_source else position.usable,unit)):
                raise ValueError('Production inputs reuse or exceed original actual reserved material batch')
            actual_inputs[batch.product_ref.key()] = actual_inputs.get(batch.product_ref.key(),Fraction(0)) + q
        if set(actual_inputs) != set(recipe):
            _needs('complete_original_production_recipe_inputs')
        equivalents = set()
        for key,ingredient in recipe.items():
            evidence([ingredient.basis_ref]); ratio = decimal_fraction(ingredient.quantity_per_output)
            if ratio <= 0:
                _unsupported('original_positive_production_conversion_ratio')
            equivalents.add(actual_inputs[key] / ratio)
        if len(equivalents) > 1 or any(q > decimal_fraction(task.remaining_target.value) for q in equivalents):
            raise ValueError('Production inputs change original recipe proportions or exceed remaining task target')
        if task.mode == 'rework' and (not task.source_rework_batch_refs or not keys(task.source_rework_batch_refs) <= keys([i.batch_ref for i in profile.inputs])):
            raise ValueError('Rework request omits original damaged batch lineage')
        return complete(profile.choice, task_ref=task.ref,
            inputs=[i.model_dump(mode='python') for i in profile.inputs], resources=[r.model_dump(mode='python') for r in profile.resources])
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
