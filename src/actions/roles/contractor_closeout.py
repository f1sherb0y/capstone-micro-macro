"""CONTRACTOR-A11 separates pending handover, remedy and itemized settlement."""
from src.actions.contracts.common import EvidenceRecord, Known, TimeWindow
from src.actions.contracts.contractor_closeout_objects import (
    ContractorCloseoutContractView, ContractorHandoverProfileView, ContractorHandoverProcedureView,
    ContractorAsBuiltView, ContractorCloseoutVerificationView, ContractorCloseoutMethodView,
    ContractorAsBuiltDesignView, ContractorAsBuiltBatchView,
    ContractorCloseoutRequirementView, ContractorCloseoutIssueView,
    ContractorContinuingResponsibilityView, ContractorHandoverRequestView, ContractorFinalAccountView,
    ContractorCloseoutRemedyPlanView, ContractorCloseoutTaskAuthorityView,
    ContractorCloseoutDependencyView, ContractorBidMethodView, ContractorBidResourceView,
    ContractorVisibleDefectView, ContractorInspectionEvidenceView, ContractorWorkRecordView,
    OwnerPaymentObligationView, ContractorRequestableComponentView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def request_closeout(context, action_input, reading):
    now, org, scope = context.business_time, reading.organization_id, context.scope
    collected = {}

    def keys(refs):
        unique_refs(refs)
        return {r.key() for r in refs}

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('contractor-closeout-clock-alignment')

    def evidence(refs, *, at=None, historic=False):
        point = now if at is None else at
        clock(point)
        if point.offset > now.offset:
            _needs('received_original_closeout_evidence_time')
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord) or row.ref != ref:
                _unsupported('contractor-closeout-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                clock(row.effective_window.end)
                if row.effective_window.start.offset > now.offset:
                    _needs('received_original_closeout_evidence', [ref])
                if (at is not None or not historic) and not row.effective_window.contains(point):
                    _needs('original_closeout_evidence_valid_at_use', [ref])
            collected[ref.key()] = ref

    def read(ref, schema, historic=False, linked=False, *, evidence_at_field=None, source_at=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', ref)) != ref:
            _unsupported('contractor-closeout-projection:' + ref.kind)
        if hasattr(row, 'scope') and not linked and not scope_covers(scope, row.scope):
            raise ValueError('Closeout source widens original authorized scope')
        use = now if source_at is None else source_at
        clock(use)
        if use.offset > now.offset:
            _needs('received_original_closeout_source_time', [ref])
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > use.offset:
                _needs('received_original_closeout_source', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            clock(row.effective_window.end)
            if (source_at is not None or not historic) and not row.effective_window.contains(use):
                _needs('current_original_closeout_source', [ref])
        point = source_at if evidence_at_field is None else getattr(row, evidence_at_field)
        if point is not None:
            clock(point)
            if evidence_at_field is not None and point.offset > row.available_at.offset:
                raise ValueError('Closeout source precedes its actual event or authorship')
        evidence(getattr(row, 'evidence_refs', []), at=point, historic=historic)
        return row

    def true(value):
        return isinstance(value, Known) and value.value is True

    def authorize(ref, actor, function, organization, action, at, target):
        grant = read(ref, Authorization, historic=True, linked=True)
        assignment = read(function, RoleAssignment, historic=True, linked=True)
        roles = {'CONTRACTOR': 'Contractor', 'OWN': 'Owner', 'ENGINEER': 'Engineer',
            'ARCHITECT': 'Architect', 'QS': 'QS', 'GOV': 'Government', 'SUPPLIER': 'Supplier', 'BANK': 'Bank'}
        if (grant.actor_id != actor or grant.function_ref != function or grant.organization_id != organization
                or assignment.function_ref != function or assignment.role != roles.get(action.split('-')[0])
                or action not in grant.action_ids
                or not any(scope_covers(s, target) for s in grant.scopes)):
            raise ValueError('Closeout source substitutes actual author, function or independent authority')
        clock(at); clock(grant.validity.start); clock(grant.validity.end)
        if at.offset > now.offset:
            _needs('received_original_closeout_author_time', [ref])
        if not grant.validity.contains(at):
            _needs('original_closeout_authority_at_execution', [ref])
        for basis_ref in (*grant.basis_refs, *assignment.basis_refs):
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref], at=at)
            else:
                basis = reading.resolve(basis_ref)
                if getattr(basis, 'ref', getattr(basis, 'function_ref', None)) != basis_ref:
                    raise ValueError('Closeout authority basis changes its exact original reference')
                if hasattr(basis, 'available_at'):
                    clock(basis.available_at)
                    if basis.available_at.offset > at.offset:
                        _needs('original_closeout_authority_basis_available_at_use', [basis_ref])
        return grant

    def author(row):
        clock(row.authored_at)
        if row.authored_at.offset > row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Closeout source precedes original actual author execution')
        return authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_organization_id, row.author_action_id, row.authored_at, row.scope)

    def complete(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, **fields,
            'note': profile.note + ' Request/draft only. Pending inspections and mixed actual configurations remain explicit; handover, use permission, acceptance, defect closure and settlement are separate. Downstream unpaid debts, guarantees and applicable defect duties remain.'}}

    def wait(code, refs):
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {
            'trigger': 'dependency_change', 'object_refs': refs, 'earliest_time': None,
            'condition_code': code}}

    try:
        if action_input.scope_ref != scope:
            raise ValueError('Closeout changes original invocation scope')
        contract = read(action_input.contract_ref, ContractorCloseoutContractView, linked=True)
        profile = read(action_input.handover_profile_ref, ContractorHandoverProfileView)
        if (contract.contractor_id != org or not scope_covers(contract.scope, scope)
                or profile.contract_ref != contract.ref or profile.organization_id != org
                or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
                or profile.scope != scope or profile.authority_ref not in context.authorization_refs):
            raise ValueError('Closeout changes original contract, contractor, actor or authority')
        authorize(profile.authority_ref, context.actor_id, context.function_ref, org, 'CONTRACTOR-A11', now, scope)
        procedure = read(profile.procedure_ref, ContractorHandoverProcedureView)
        if (procedure.contract_ref != contract.ref or profile.choice not in procedure.permitted_choices
                or not true(procedure.permitted) or not procedure.recipient_ids):
            _needs('independent_current_contract_closeout_procedure', [procedure.ref])
        if contract.coverage != 'complete' or contract.as_of != now:
            _needs('complete_current_contract_closeout_history_and_residual_duties')
        for supplied, original in [('as_built_refs', 'as_built_refs'), ('verification_refs', 'verification_refs'),
                ('defect_refs', 'defect_refs'), ('settlement_components', 'settlement_component_refs')]:
            if keys(getattr(action_input, supplied)) != keys(getattr(contract, original)):
                _needs('complete_original_closeout_' + original)
        evidence(profile.evidence_refs_received)

        obligations = {}
        for ref in contract.obligation_refs:
            row = read(ref, OwnerPaymentObligationView, linked=True)
            if org not in {row.debtor_id, row.payee_id} or not scope_covers(contract.scope, row.origin_scope):
                raise ValueError('Closeout drops original legal organization or debt scope')
            clock(row.as_of)
            if row.as_of != now:
                _needs('current_original_remaining_closeout_obligations', [ref])
            evidence(row.verification_evidence_refs)
            for value in (row.actual_due, row.actual_paid, row.actual_offset):
                if isinstance(value, Known):
                    evidence([value.value.basis_ref])
                    if value.value.currency != contract.currency or decimal_fraction(value.value.value) < 0:
                        raise ValueError('Closeout obligation changes original currency or actual amount')
            obligations[ref.key()] = row
        keys(contract.obligation_refs)
        for ref in contract.continuing_responsibility_refs:
            row = read(ref, ContractorContinuingResponsibilityView, linked=True)
            if row.contract_ref != contract.ref or row.organization_id != org:
                raise ValueError('Closeout replaces original continuing responsibility')
            if not keys(row.obligation_refs) <= set(obligations) or not keys(row.defect_refs) <= keys(contract.defect_refs):
                raise ValueError('Continuing responsibility omits original debt or defect coverage')
        keys(contract.continuing_responsibility_refs)

        issues = {}
        for ref in contract.issue_refs:
            row = read(ref, ContractorCloseoutIssueView, linked=True)
            if row.contract_ref != contract.ref:
                raise ValueError('Closeout issue belongs to another contract')
            if (not keys(row.as_built_refs) <= keys(contract.as_built_refs)
                    or not keys(row.defect_refs) <= keys(contract.defect_refs)
                    or not keys(row.component_refs) <= keys(contract.settlement_component_refs)):
                raise ValueError('Closeout issue substitutes original configuration, defect or settlement coverage')
            if row.status != 'resolved':
                issues[ref.key()] = row
        keys(contract.issue_refs)
        defects = {}
        for ref in action_input.defect_refs:
            defect = read(ref, ContractorVisibleDefectView)
            observed = read(defect.observation_ref, ContractorInspectionEvidenceView, historic=True, evidence_at_field='authored_at')
            work = read(defect.work_record_ref, ContractorWorkRecordView, historic=True)
            if work.available_at.offset > observed.authored_at.offset:
                raise ValueError('Closeout observation uses work history unavailable to its actual author')
            evidence([work.gross_quantity.basis_ref, work.net_quantity.basis_ref], historic=True)
            author(observed); clock(observed.observed_at)
            if (defect.physical_work_key != observed.physical_work_key or defect.physical_work_key != work.physical_work_key
                    or observed.work_record_ref != work.ref or defect.ref.key() not in keys(observed.defect_refs)
                    or observed.kind != 'actual_observation' or observed.observed_at.offset > observed.authored_at.offset
                    or not scope_covers(work.scope, observed.scope) or not scope_covers(observed.scope, defect.scope)):
                raise ValueError('Closeout defect substitutes original actual observed work')
            if any(reading.resolve(ref).basis_kind != 'observed' for ref in observed.evidence_refs):
                _needs('actual_observed_closeout_defect_basis', [observed.ref])
            defects[ref.key()] = defect

        if profile.choice == 'submit_handover':
            if not action_input.as_built_refs:
                _needs('original_actual_as_built_configuration')
            configs = {}; coverage = set(); physical = set(); configuration_keys = set()
            for ref in action_input.as_built_refs:
                row = read(ref, ContractorAsBuiltView, evidence_at_field='authored_at'); grant = author(row)
                if (row.contract_ref != contract.ref or row.author_organization_id != org
                        or not true(row.actual) or not row.work_record_refs or row.configuration_key in configuration_keys):
                    raise ValueError('As-built source is not unique actual contractor configuration')
                configuration_keys.add(row.configuration_key); keys(row.product_batch_refs)
                if not keys([row.design_ref, *row.product_batch_refs, *row.work_record_refs]) <= keys(grant.readable_refs):
                    raise ValueError('As-built author lacks original design, batch or work-record read authority')
                # Exact design/batch versions stay in the original authored content.
                design = read(row.design_ref, ContractorAsBuiltDesignView, historic=True, linked=True, source_at=row.authored_at)
                if design.contract_ref != contract.ref or not scope_covers(design.scope, row.scope):
                    raise ValueError('As-built record substitutes original applicable design version')
                for batch in row.product_batch_refs:
                    batch_record = read(batch, ContractorAsBuiltBatchView, historic=True, linked=True, source_at=row.authored_at)
                    if batch_record.contract_ref != contract.ref or row.ref.key() not in keys(batch_record.configuration_refs):
                        raise ValueError('As-built product batch lacks original actual configuration binding')
                keys(row.work_record_refs)
                for work_ref in row.work_record_refs:
                    work = read(work_ref, ContractorWorkRecordView, historic=True)
                    if work.available_at.offset > row.authored_at.offset:
                        raise ValueError('As-built record uses work history unavailable to its actual author')
                    evidence([work.gross_quantity.basis_ref, work.net_quantity.basis_ref], historic=True)
                    if not scope_covers(row.scope, work.scope) or work.physical_work_key in physical:
                        raise ValueError('As-built configuration repeats physical work or leaves its actual scope')
                    physical.add(work.physical_work_key)
                configs[ref.key()] = row; coverage.update(keys(row.scope.coverage_refs))
            if not keys(procedure.required_as_built_scope_refs) <= coverage:
                _needs('actual_as_built_coverage_for_requested_handover')
            requirements = {}
            for ref in procedure.required_requirement_refs:
                row = read(ref, ContractorCloseoutRequirementView)
                if row.contract_ref != contract.ref or not keys(row.as_built_refs) <= set(configs) or not row.as_built_refs:
                    raise ValueError('Handover requirement changes actual configuration or contract')
                requirements[ref.key()] = row
            pairs = set(); pending = set(); seen = set()
            for ref in action_input.verification_refs:
                row = read(ref, ContractorCloseoutVerificationView, evidence_at_field='authored_at'); grant = author(row)
                if (row.contract_ref != contract.ref or row.as_built_ref.key() not in configs
                        or row.as_built_sha256 != configs[row.as_built_ref.key()].content_sha256
                        or row.requirement_ref.key() not in requirements):
                    raise ValueError('Verification substitutes actual as-built version or original requirement')
                if row.as_built_ref.key() not in keys(requirements[row.requirement_ref.key()].as_built_refs):
                    raise ValueError('Verification does not apply to this original configuration')
                configuration = configs[row.as_built_ref.key()]
                if (row.authored_at.offset < configuration.available_at.offset
                        or not keys([row.as_built_ref, row.requirement_ref, row.method_ref]) <= keys(grant.readable_refs)):
                    raise ValueError('Verification predates original configuration or lacks original source read authority')
                read(row.requirement_ref, ContractorCloseoutRequirementView, historic=True, source_at=row.authored_at)
                method = read(row.method_ref, ContractorCloseoutMethodView, historic=True, source_at=row.authored_at)
                if (not true(method.supported) or row.author_action_id not in method.allowed_author_action_ids
                        or row.requirement_ref.key() not in keys(method.requirement_refs)):
                    _unsupported('original_closeout_verification_method_support')
                if procedure.require_independent_verification and row.author_organization_id == org:
                    raise ValueError('Contractor self-verification substitutes independent acceptance')
                pair = (row.as_built_ref.key(), row.requirement_ref.key())
                if pair in seen:
                    raise ValueError('Handover repeats verification for an original configuration/requirement')
                seen.add(pair)
                if row.status == 'failed':
                    raise ObservationGap({'kind': 'technical_error', 'error': {'kind': 'unrecorded',
                        'correlation_id': context.operation_id, 'code': 'original-closeout-verification-failed'}, 'retryability': 'unknown'})
                if row.status == 'unsupported':
                    _unsupported('original_closeout_verification_unsupported')
                if row.status == 'ok' and true(row.passed):
                    pairs.add(pair)
                else:
                    pending.add(pair)
            required = {(ref.key(), requirement.ref.key()) for requirement in requirements.values() for ref in requirement.as_built_refs}
            pending.update(required - pairs)
            if pending and not procedure.allow_pending_handover:
                _needs('original_required_handover_verifications')
            if keys(profile.remaining_issue_refs) != set(issues):
                raise ValueError('Handover must retain every original unresolved issue')
            issue_defects = set(); issue_pairs = set()
            for issue in issues.values():
                issue_defects.update(keys(issue.defect_refs))
                issue_pairs.update((a.key(), r.key()) for a in issue.as_built_refs for r in issue.requirement_refs)
            if not pending <= issue_pairs or not {k for k,d in defects.items() if d.status != 'closed'} <= issue_defects:
                _needs('explicit_remaining_issue_for_pending_inspection_or_defect')
            business = set()
            for ref in contract.handover_request_refs:
                previous = read(ref, ContractorHandoverRequestView, historic=True, linked=True); author(previous)
                if previous.contract_ref != contract.ref or previous.author_organization_id != org or previous.business_key in business:
                    raise ValueError('Handover history substitutes contractor or repeats business request')
                business.add(previous.business_key)
                if previous.business_key == profile.business_key:
                    if previous.scope != scope or keys(previous.as_built_refs) != set(configs):
                        raise ValueError('Existing handover identity substitutes original scope/configuration')
                    return wait('continue_original_handover_request', [previous.ref])
            keys(contract.handover_request_refs)
            return complete('submit_handover', scope_ref=scope, evidence_refs=list(collected.values()),
                remaining_issue_refs=profile.remaining_issue_refs)

        if profile.choice == 'rectify':
            if profile.remedy_plan_ref is None:
                _needs('original_authorized_closeout_remedy_task_draft')
            plan = read(profile.remedy_plan_ref, ContractorCloseoutRemedyPlanView, evidence_at_field='authored_at'); author(plan)
            mandate = read(plan.task_authority_ref, ContractorCloseoutTaskAuthorityView)
            if (plan.contract_ref != contract.ref or plan.author_organization_id != org or not plan.tasks
                    or mandate.contract_ref != contract.ref or mandate.organization_id != org
                    or mandate.actor_id != context.actor_id or mandate.function_ref != context.function_ref
                    or not true(mandate.permitted)):
                _needs('independent_original_closeout_remedy_task_authority')
            task_keys = {task.local_key for task in plan.tasks}
            if len(task_keys) != len(plan.tasks) or set(plan.task_defect_refs) != task_keys:
                raise ValueError('Remedy requires unique original task keys and exact defect bindings')
            windows = {}; graph = {}; covered = set()
            for task in plan.tasks:
                if not scope_covers(scope, task.scope_ref) or not task.target_quantities:
                    raise ValueError('Remedy task widens scope or omits concrete work')
                targets = plan.task_defect_refs[task.local_key]
                if not targets or not keys(targets) <= set(defects) or not keys(targets) <= keys(mandate.defect_refs):
                    raise ValueError('Remedy task lacks original authorized unresolved defects')
                covered.update(keys(targets))
                for ref in targets:
                    defect = defects[ref.key()]
                    if defect.status == 'closed' or not scope_covers(task.scope_ref, defect.scope):
                        raise ValueError('Remedy task replaces closed or unrelated original defect')
                if task.work_method_ref.key() not in keys(mandate.allowed_method_refs):
                    raise ValueError('Remedy uses an unauthorized work method')
                method = read(task.work_method_ref, ContractorBidMethodView)
                if not scope_covers(method.scope, task.scope_ref):
                    raise ValueError('Remedy work method leaves original task scope')
                evidence([method.productivity_basis_ref])
                for quantity in task.target_quantities:
                    evidence([quantity.basis_ref])
                    if quantity.unit != method.quantity_unit or decimal_fraction(quantity.value) <= 0:
                        raise ValueError('Remedy task requires positive original method quantities')
                window = read(task.window_ref, TimeWindow); clock(window.start); clock(window.end)
                if window.start.offset < now.offset:
                    raise ValueError('New remedy task starts before original request')
                windows[task.local_key] = window; graph[task.local_key] = set()
                keys(task.dependency_refs); keys([a.resource_ref for a in task.allocations])
                for allocation in task.allocations:
                    resource = read(allocation.resource_ref, ContractorBidResourceView, linked=True)
                    evidence([allocation.quantity.basis_ref, resource.total.basis_ref])
                    if (resource.organization_id != org or resource.resource_kind != method.resource_kind
                            or allocation.task_scope_ref != task.scope_ref or allocation.window_ref != task.window_ref
                            or allocation.quantity.unit != method.capacity_unit or resource.total.unit != method.capacity_unit
                            or not 0 < decimal_fraction(allocation.quantity.value) <= decimal_fraction(resource.total.value)):
                        raise ValueError('Remedy draft substitutes original own resource or positive input')
            for task in plan.tasks:
                for ref in task.dependency_refs:
                    dependency = read(ref, ContractorCloseoutDependencyView)
                    if dependency.plan_ref != plan.ref or dependency.dependent_task_key != task.local_key:
                        raise ValueError('Remedy task substitutes original dependency graph')
                    for predecessor in dependency.predecessor_task_keys:
                        if predecessor not in task_keys or predecessor == task.local_key:
                            raise ValueError('Remedy dependency omits or repeats original predecessor')
                        graph[task.local_key].add(predecessor)
                        if windows[predecessor].end.offset > windows[task.local_key].start.offset:
                            _needs('original_remedy_predecessor_window_completion')
            visited = set(); active = set()
            def visit(key):
                if key in active:
                    raise ValueError('Remedy task dependency cycle')
                if key not in visited:
                    active.add(key)
                    for predecessor in graph[key]: visit(predecessor)
                    active.remove(key); visited.add(key)
            for key in task_keys: visit(key)
            if not covered:
                _needs('original_remedy_defects')
            # Draft task creation reserves no capacity and grants no construction
            # release. A06/A08 and the core recheck actual gates before execution.
            return complete('rectify', tasks=[task.model_dump(mode='python') for task in plan.tasks])

        if profile.choice not in {'propose_final_account', 'respond_settlement'}:
            _unsupported('contractor-closeout-choice')
        accepted, disputed = keys(profile.component_refs), keys(profile.disputed_refs)
        if accepted & disputed or accepted | disputed != keys(action_input.settlement_components) or not accepted | disputed:
            raise ValueError('Final account must partition every original component into accepted or disputed')
        dispute_components = {r.key() for issue in issues.values() for r in issue.component_refs}
        if not disputed <= dispute_components:
            _needs('original_component_specific_settlement_dispute_basis')
        for ref in action_input.settlement_components:
            component = read(ref, ContractorRequestableComponentView, linked=True)
            if (component.contract_ref != contract.ref or component.obligation_ref.key() not in obligations
                    or org not in {component.debtor_id, component.payee_id} or component.as_of != now):
                raise ValueError('Final account substitutes original contract, debt or current component')
            obligation = obligations[component.obligation_ref.key()]
            if (component.debtor_id != obligation.debtor_id or component.payee_id != obligation.payee_id
                    or component.source_ref != obligation.source_ref or component.debt_ref != obligation.debt_ref
                    or ref.key() not in keys(obligation.component_refs)):
                raise ValueError('Final-account component changes original debt lineage, parties or coverage')
            for value in [component.actual_due, component.actual_cash_paid, component.actual_offset]:
                if isinstance(value, Known):
                    evidence([value.value.basis_ref])
                    if value.value.currency != contract.currency or decimal_fraction(value.value.value) < 0:
                        raise ValueError('Final account changes original currency or actual amount')
        histories = {}; business = set()
        for ref in contract.final_account_refs:
            previous = read(ref, ContractorFinalAccountView, historic=True, linked=True); author(previous)
            identity = (previous.author_organization_id, previous.business_key)
            if previous.contract_ref != contract.ref or identity in business:
                raise ValueError('Final-account history substitutes contract or repeats business identity')
            business.add(identity); histories[ref.key()] = previous
            if (profile.choice == 'propose_final_account' and previous.author_organization_id == org
                    and previous.business_key == profile.business_key):
                if previous.author_organization_id != org or keys(previous.component_refs) != accepted | disputed:
                    raise ValueError('Existing final-account business identity changes original author/components')
                return wait('continue_original_final_account', [previous.ref])
        keys(contract.final_account_refs)
        if profile.choice == 'respond_settlement':
            if profile.final_account_ref is None or profile.final_account_ref.key() not in histories:
                _needs('original_existing_final_account_for_response')
            original = histories[profile.final_account_ref.key()]
            if original.status == 'withdrawn' or keys(original.component_refs) != accepted | disputed:
                raise ValueError('Settlement response changes original itemized account coverage')
        return complete(profile.choice, component_refs=profile.component_refs, disputed_refs=profile.disputed_refs)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
