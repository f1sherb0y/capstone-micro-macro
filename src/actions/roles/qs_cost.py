"""QS-A04 consumes original authorized cost inputs and rechecks saved arithmetic."""
from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.qs_cost_objects import (
    QSCostBriefView, QSCostOptionView, QSCostTaskView, QSCostScopeView,
    QSCostComparisonBasisView, QSCostComponentView, QSQuantityBasisView,
    QSQuantityScheduleView, QSCostPriceView, QSCostQuestionView,
    QSCostResponseRequirementView, QSCostCalculationView, QSCostMethodView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.methods.qs_cost import COST_METHOD, CostArithmeticInput, unknown
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def compile_cost_plan(context, action_input, reading):
    return _compile_cost_plan(context, action_input, reading)


def prepare_cost_arithmetic(context, action_input, reading):
    """Reuse source/authority checks without forming a decision or inventing a saved result."""
    reading.check_method_context(context, 'QS-A04')
    if action_input.method_result_refs:
        raise ValueError('Cost production requires a fresh source input without an existing calculation result')
    return _compile_cost_plan(context, action_input, reading, arithmetic_only=True)


def _compile_cost_plan(context, action_input, reading, *, arithmetic_only=False):
    now, scope, sources = context.business_time, action_input.scope, {}

    def state(value):
        return value.state if hasattr(value, 'state') else value['state']

    def clock(point):
        if point.clock_ref != now.clock_ref: _unsupported('qs-cost-clock-conversion')

    def current(window, point=now):
        clock(window.start); clock(point)
        return window.contains(point)

    def evidence(refs):
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord): _unsupported('qs-cost-evidence-schema')
            if row.effective_window is not None and not current(row.effective_window):
                _needs('current_qs_cost_evidence', [ref])

    def read(ref, schema, require_current=True):
        row = reading.resolve(ref)
        if not isinstance(row, schema): _unsupported('qs-cost-projection:' + ref.kind)
        evidence(getattr(row, 'evidence_refs', []))
        if hasattr(row, 'scope') and row.scope != scope:
            raise ValueError('Cost source changes original requested scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset: _needs('received_qs_cost_input', [ref])
            if require_current and not current(row.effective_window): _needs('current_qs_cost_input', [ref])
        sources[ref.key()] = ref
        return row

    def authority(ref, actor, function, action, roles, at=now, organization=None):
        grant = read(ref, Authorization); assignment = read(function, RoleAssignment)
        evidence(grant.basis_refs + assignment.basis_refs)
        if (grant.actor_id != actor or grant.function_ref != function or assignment.role not in roles
                or (organization is not None and grant.organization_id != organization)):
            raise ValueError('Cost source author or legal organization differs from original grant')
        if not current(grant.validity, at) or action not in grant.action_ids or not any(scope_covers(s, scope) for s in grant.scopes):
            _needs('original_qs_cost_authority', [ref])

    def author(row, roles, organization=None):
        assignment = read(row.author_function_ref, RoleAssignment)
        supported = {'Architect': {'ARCHITECT-A04', 'ARCHITECT-A05', 'ARCHITECT-A13'},
            'Engineer': {'ENGINEER-A04', 'ENGINEER-A05', 'ENGINEER-A13'}, 'QS': {'QS-A04', 'QS-A13'}}
        if row.author_action_id not in supported.get(assignment.role, set()):
            _unsupported('qs-cost-original-author-function')
        authority(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_action_id, roles, getattr(row, 'calculated_at', row.available_at), organization)

    def completed(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'scope': scope,
            'note': 'Original scoped estimate only; exclusions, proxy assumptions and design limitations remain applicable; no budget, obligation, cash or work effect', **fields}}

    try:
        brief = read(action_input.brief_ref, QSCostBriefView)
        option = read(action_input.option_ref, QSCostOptionView)
        task = read(action_input.task_ref, QSCostTaskView)
        cost_scope = read(action_input.cost_scope_ref, QSCostScopeView)
        comparison = read(action_input.comparison_basis_ref, QSCostComparisonBasisView)
        if (option.brief_ref != brief.ref or cost_scope.option_ref != option.ref
                or task.brief_ref != brief.ref or task.option_ref != option.ref
                or task.cost_scope_ref != cost_scope.ref or task.comparison_basis_ref != comparison.ref
                or task.organization_id != reading.organization_id or task.function_ref != context.function_ref):
            raise ValueError('Cost task changes original design, brief, scope, comparison or QS organization')
        authority(task.authority_ref, context.actor_id, task.function_ref, 'QS-A04', {'QS'}, organization=reading.organization_id)
        author(option, {'Architect', 'Engineer'})
        if any('cost_estimation' not in row.allowed_uses for row in (brief, option, task)):
            _needs('authorized_original_cost_estimation_use')
        if task.status != 'authorized':
            return {'kind': 'deferred', 'reason_code': 'qs_cost_task_not_ready', 'resume_condition': {
                'trigger': 'dependency_change', 'object_refs': [task.ref], 'earliest_time': None,
                'condition_code': 'qs.cost.task_authorized'}}
        clock(comparison.pricing_time)
        if comparison.pricing_time.offset > now.offset: _needs('received_cost_comparison_time')
        for values in (action_input.quantity_basis_refs, action_input.price_refs, action_input.method_result_refs): unique_refs(values)
        required_quantities = {r.quantity_basis_ref for r in cost_scope.items if r.quantity_basis_ref is not None}
        required_prices = {r.price_ref for r in cost_scope.items if r.price_ref is not None}
        if set(action_input.quantity_basis_refs) != required_quantities or set(action_input.price_refs) != required_prices:
            _needs('exact_original_cost_quantity_and_price_versions')

        questions, question_keys = [], set()

        def question(item, issue):
            ref = getattr(item, issue + '_question_ref')
            row = read(ref, QSCostQuestionView)
            requirement = read(row.response_requirement_ref, QSCostResponseRequirementView)
            if (row.task_ref != task.ref or row.line_key != item.line_key or row.issue != issue
                    or requirement.task_ref != task.ref or not set(row.recipient_ids) <= set(requirement.recipient_ids)
                    or not set(row.recipient_ids) <= set(brief.recipient_ids)
                    or not set(row.blocking_uses) <= set(task.allowed_uses)):
                raise ValueError('Cost missing-item question changes original task, line, issue or authorized recipients')
            if row.ref.key() not in question_keys:
                question_keys.add(row.ref.key())
                questions.append({'scope': scope, 'target_refs': [row.ref], 'question': row.question,
                    'recipient_ids': row.recipient_ids, 'evidence_refs': row.evidence_refs,
                    'blocking_uses': row.blocking_uses, 'response_requirement_ref': requirement.ref})

        inputs, output_lines, schedules = [], [], set()
        input_times = [r.available_at for r in (brief, option, task, cost_scope, comparison)]
        for item in cost_scope.items:
            if not scope_covers(scope, item.covered_scope): raise ValueError('Cost line lies outside authorized estimate scope')
            component = read(item.cost_component_ref, QSCostComponentView)
            if set(component.coverage_keys) != set(item.coverage_keys):
                raise ValueError('Cost item hides original physical component coverage')
            quantity, price, applicable = None, None, False
            line_quantity = unknown('missing_original_quantity')
            line_basis = list(cost_scope.evidence_refs + component.evidence_refs)
            if item.quantity_basis_ref is not None:
                quantity = read(item.quantity_basis_ref, QSQuantityBasisView, False)
                input_times.append(quantity.available_at)
                author(quantity, {'Architect', 'Engineer', 'QS'})
                if quantity.option_ref != option.ref or quantity.line_key != item.line_key or quantity.cost_component_ref != item.cost_component_ref:
                    raise ValueError('Quantity basis changes original option, cost component or line')
                if current(quantity.effective_window): line_quantity = quantity.quantity
                else: line_quantity = unknown('stale_original_quantity')
                line_basis += quantity.evidence_refs
                if quantity.quantity.state == 'known':
                    evidence([quantity.quantity.value.basis_ref])
                    line_basis.append(quantity.quantity.value.basis_ref)
                if quantity.mode == 'proxy':
                    profile = read(quantity.proxy_method_ref, QSCostMethodView)
                    if 'cost_estimation' not in profile.permitted_uses: _needs('authorized_original_proxy_use')
                elif quantity.quantity_schedule_ref is not None:
                    schedule = read(quantity.quantity_schedule_ref, QSQuantityScheduleView)
                    unique_refs(schedule.quantity_basis_refs)
                    if schedule.option_ref != option.ref or quantity.ref not in schedule.quantity_basis_refs:
                        raise ValueError('Quantity schedule changes original design or quantity identity')
                    schedules.add(schedule.ref)
                elif state(line_quantity) == 'known':
                    line_quantity = unknown('missing_registered_quantity_schedule')
            coverage = item.coverage_keys
            if item.price_ref is not None:
                price = read(item.price_ref, QSCostPriceView, False)
                input_times.append(price.available_at)
                line_basis += price.evidence_refs
                if price.unit_rate.state == 'known':
                    evidence([price.unit_rate.value.basis_ref])
                    line_basis.append(price.unit_rate.value.basis_ref)
                applicable = (current(price.effective_window) and current(price.valid_pricing_window, comparison.pricing_time)
                    and price.cost_component_ref == item.cost_component_ref and price.region_id == comparison.region_id
                    and price.delivery_code == comparison.delivery_code and set(item.coverage_keys) <= set(price.coverage_keys)
                    and not set(price.coverage_keys) & set(price.excluded_coverage_keys)
                    and (quantity is None or price.measurement_rule_code == quantity.measurement_rule_code))
                # An included installation/child/region scope is still occupied by this price.
                coverage = list(dict.fromkeys([*item.coverage_keys, *price.coverage_keys]))
            line_basis = list(dict.fromkeys(line_basis))
            inputs.append({'line_key': item.line_key, 'quantity': line_quantity,
                'unit_rate': price.unit_rate if price is not None else None, 'price_unit': price.quantity_unit if price is not None else None,
                'price_applicable': applicable, 'coverage_keys': coverage, 'basis_refs': line_basis})
            output_lines.append({'line_key': item.line_key, 'covered_scope': item.covered_scope,
                'cost_component_ref': item.cost_component_ref, 'quantity': line_quantity, 'price_ref': item.price_ref,
                'amount': unknown('cost_calculation_not_recorded'), 'basis_refs': line_basis,
                'calculation_ref': None, 'predecessor_line_keys': item.predecessor_line_keys})
        if len(schedules) > 1: _unsupported('qs-cost-single-registered-quantity-schedule')
        schedule_ref = next(iter(schedules), None)
        if arithmetic_only:
            reading.recheck()
            return {'kind': 'prepared',
                'input': CostArithmeticInput(currency=comparison.currency, lines=inputs, source_refs=list(sources.values())),
                'quantity_schedule_ref': schedule_ref}
        calculation_ref, subtotal, total = None, unknown('cost_calculation_not_recorded'), None
        if len(action_input.method_result_refs) > 1: _needs('unique_original_cost_calculation')
        if action_input.method_result_refs:
            saved = read(action_input.method_result_refs[0], QSCostCalculationView)
            author(saved, {'QS'}, reading.organization_id)
            clock(saved.calculated_at)
            if saved.calculated_at.offset > saved.available_at.offset: _needs('received_original_cost_calculation')
            if any(t.offset > saved.calculated_at.offset for t in input_times):
                _needs('cost_execution_after_original_input_versions', [saved.ref])
            if (saved.task_ref != task.ref or saved.brief_ref != brief.ref or saved.option_ref != option.ref
                    or saved.cost_scope_ref != cost_scope.ref or saved.comparison_basis_ref != comparison.ref
                    or set(saved.quantity_basis_refs) != required_quantities or set(saved.price_refs) != required_prices
                    or saved.quantity_schedule_ref != schedule_ref):
                raise ValueError('Saved cost calculation changes exact original input versions or schedule')
            if saved.method_ref != COST_METHOD: _unsupported('qs-cost-saved-calculation-method')
            if saved.status == 'unsupported': _unsupported('qs-cost-upstream-method-domain')
            if saved.status == 'failed':
                return {'kind': 'technical_error', 'error': {'kind': 'unrecorded', 'correlation_id': context.operation_id,
                    'code': 'original_cost_calculation_failed'}, 'retryability': 'unknown'}
            result = reading.calculate(COST_METHOD, CostArithmeticInput(currency=comparison.currency, lines=inputs, source_refs=list(sources.values())))
            if result.kind != 'ok':
                raw = result.model_dump(mode='python')
                if result.kind == 'needs_information': raw['requested_refs'] = []
                if result.kind == 'invalid_input': raise ValueError('Invalid original quantity/cost arithmetic')
                raise ObservationGap(raw)
            report = result.value
            if ([(r.line_key, r.quantity, r.amount) for r in saved.lines] != [(r.line_key, r.quantity, r.amount) for r in report.lines]
                    or saved.known_subtotal != report.known_subtotal or saved.complete_total != report.complete_total):
                raise ValueError('Saved cost amounts or totals disagree with exact original arithmetic/coverage')
            for original, computed in zip(saved.lines, report.lines):
                evidence(original.basis_refs)
                if not set(original.basis_refs) <= set(computed.basis_refs): raise ValueError('Saved line introduces another numeric basis')
            calculation_ref, subtotal, total = saved.ref, saved.known_subtotal, saved.complete_total
            for item, line, computed in zip(cost_scope.items, output_lines, report.lines):
                line.update(quantity=computed.quantity, amount=computed.amount, calculation_ref=saved.ref)
                for issue in computed.issues: question(item, issue)
        else:
            # No registered execution: retain inputs/unknown amounts, never invent a MethodResultRef.
            for item, line in zip(cost_scope.items, inputs):
                if state(line['quantity']) != 'known': question(item, 'quantity')
                rate = line['unit_rate']
                quantity = line['quantity']
                if (rate is None or rate.state != 'known' or not line['price_applicable']
                        or (rate.state == 'known' and rate.value.currency != comparison.currency)
                        or (state(quantity) == 'known' and quantity.value.unit != line['price_unit'])):
                    question(item, 'price')
                question(item, 'coverage')
        draft = {'option_ref': option.ref, 'cost_scope_ref': cost_scope.ref, 'comparison_basis_ref': comparison.ref,
            'quantity_schedule_ref': schedule_ref, 'lines': output_lines, 'calculation_ref': calculation_ref,
            'known_subtotal': subtotal, 'complete_total': total, 'missing_items': questions}
        if task.delivery_mode == 'request_inputs':
            for issue in ('quantity', 'price'):
                selected = [q for q in questions if read(q['target_refs'][0], QSCostQuestionView).issue == issue]
                if selected: return completed('request_' + issue, questions=selected)
        if calculation_ref is not None and subtotal.state == 'known': return completed('estimate', draft=draft)
        return completed('report_limits', draft=draft, reason='No applicable computed range; original missing items and limits remain unresolved')
    except ObservationGap as exc:
        reading.recheck()
        return exc.result
