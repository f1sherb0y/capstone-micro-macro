"""CONTRACTOR-A09 preserves proposal, instruction, cost and entitlement boundaries."""
from src.actions.contracts.common import EvidenceRecord, Known
from src.actions.contracts.contractor_claim_objects import (
    ContractorClaimContractView, ContractorClaimProfileView, ContractorClaimProcedureView,
    ContractorClaimDesignView, ContractorClaimTaskView, ContractorClaimInstructionView,
    ContractorInstructionAuthorityView, ContractorInterfaceIssueView, ContractorClaimRequirementView,
    ContractorChangeProposalView, ContractorActualCostView, ContractorClaimAmountView,
    ContractorTimeImpactView, ContractorClaimView,
    ContractorClaimCostLineView, ContractorClaimMethodView,
)
from fractions import Fraction
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.qs_change import CHANGE_METHOD
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def handle_interfaces_and_claims(context, action_input, reading):
    return _handle_interfaces_and_claims(context, action_input, reading)


def recheck_original_contractor_claim_wait(context, action_input, reading):
    """Reproduce only original notice/claim gates, without invoking valuation."""
    return _handle_interfaces_and_claims(context, action_input, reading, original_wait_only=True)


def _handle_interfaces_and_claims(context, action_input, reading, *, original_wait_only=False):
    now, org, scope = context.business_time, reading.organization_id, context.scope
    evidence_refs = {}

    def keys(refs):
        unique_refs(refs)
        return {ref.key() for ref in refs}

    def true(value):
        return isinstance(value, Known) and value.value is True

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('contractor-claim-clock-alignment')

    def evidence(refs, *, at=None, historic=False):
        point = now if at is None else at
        clock(point)
        if point.offset > now.offset:
            _needs('received_original_claim_evidence_time')
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord) or row.ref != ref:
                _unsupported('contractor-claim-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                clock(row.effective_window.end)
                if row.effective_window.start.offset > now.offset:
                    _needs('received_original_claim_evidence', [ref])
                if (at is not None or not historic) and not row.effective_window.contains(point):
                    _needs('original_claim_evidence_valid_at_use', [ref])
            evidence_refs[ref.key()] = ref

    def read(ref, schema, historic=False, linked=False, *, evidence_at_field=None, source_at=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref:
            _unsupported('contractor-claim-projection:' + ref.kind)
        if hasattr(row, 'scope') and not linked and not scope_covers(scope, row.scope):
            raise ValueError('Claim source widens original authorized scope')
        use = now if source_at is None else source_at
        clock(use)
        if use.offset > now.offset:
            _needs('received_original_claim_source_time', [ref])
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > use.offset:
                _needs('received_original_claim_source', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            clock(row.effective_window.end)
            if (source_at is not None or not historic) and not row.effective_window.contains(use):
                _needs('current_original_claim_source', [ref])
        point = source_at if evidence_at_field is None else getattr(row, evidence_at_field)
        if point is not None:
            clock(point)
            if evidence_at_field is not None and point.offset > row.available_at.offset:
                raise ValueError('Claim source precedes actual authorship')
        evidence(getattr(row, 'evidence_refs', []), at=point, historic=historic)
        return row

    def authorize(ref, actor, function, organization, action, at, target_scope):
        grant = read(ref, Authorization, True, True); assignment = read(function, RoleAssignment, True, True)
        roles = {'CONTRACTOR': 'Contractor', 'OWN': 'Owner', 'ENGINEER': 'Engineer', 'ARCHITECT': 'Architect',
            'QS': 'QS', 'GOV': 'Government', 'SUPPLIER': 'Supplier', 'BANK': 'Bank'}
        if (grant.actor_id != actor or grant.function_ref != function or grant.organization_id != organization
                or assignment.function_ref != function or assignment.role != roles.get(action.split('-')[0])
                or action not in grant.action_ids
                or not any(scope_covers(s, target_scope) for s in grant.scopes)):
            raise ValueError('Claim source substitutes independent actual author/function/scope authority')
        clock(at); clock(grant.validity.start); clock(grant.validity.end)
        if at.offset > now.offset:
            _needs('received_original_claim_author_time', [ref])
        if not grant.validity.contains(at):
            _needs('original_claim_authority_at_execution', [ref])
        for basis_ref in (*grant.basis_refs, *assignment.basis_refs):
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref], at=at)
            else:
                basis = reading.resolve(basis_ref)
                if hasattr(basis, 'available_at'):
                    clock(basis.available_at)
                    if basis.available_at.offset > at.offset:
                        _needs('original_claim_authority_basis_available_at_use', [basis_ref])
        return grant

    def author(row):
        clock(row.authored_at)
        if row.authored_at.offset > row.available_at.offset or not row.effective_window.contains(row.authored_at):
            raise ValueError('Claim source predates its original actual execution')
        return authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_organization_id, row.author_action_id, row.authored_at, row.scope)

    def complete(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'scope_ref': scope, **fields,
            'note': profile.note + ' Original notice/proposal/response only. Estimate and incurred cost remain separate; no entitlement, recognized amount, extension, permit change, debt or suspension is created. Existing obligations and lawful urgent procedures remain applicable.'}}

    def technical(code):
        raise ObservationGap({'kind': 'technical_error', 'error': {'kind': 'unrecorded',
            'correlation_id': context.operation_id, 'code': code}, 'retryability': 'unknown'})

    def wait(code, refs):
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {'trigger': 'dependency_change',
            'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    try:
        contract = read(action_input.contract_ref, ContractorClaimContractView, True, True)
        profile = read(action_input.claim_profile_ref, ContractorClaimProfileView)
        if (contract.contractor_id != org or not scope_covers(contract.scope, scope) or profile.contract_ref != contract.ref
                or profile.organization_id != org or profile.scope != scope or profile.authority_ref not in context.authorization_refs):
            raise ValueError('Claim changes original contract, contractor, scope or acting authority')
        authorize(profile.authority_ref, context.actor_id, context.function_ref, org, 'CONTRACTOR-A09', now, scope)
        for input_field, field in [('baseline_design_refs', 'design_refs'), ('instruction_refs', 'instruction_refs'), ('issue_refs', 'issue_refs'), ('actual_cost_refs', 'actual_cost_refs')]:
            if keys(getattr(action_input, input_field)) != keys(getattr(profile, field)):
                _needs('complete_original_claim_' + field)
        procedure = read(profile.procedure_ref, ContractorClaimProcedureView)
        if (procedure.contract_ref != contract.ref or profile.choice not in procedure.permitted_choices
                or not procedure.recipient_ids or not true(procedure.permitted)):
            _needs('independent_original_contract_claim_or_notice_procedure')
        if procedure.deadline is not None:
            clock(procedure.deadline)
            if now.offset > procedure.deadline.offset and not true(procedure.late_notice_permitted):
                return wait('contractor-claim-original-notice-deadline-procedure', [procedure.ref])
        if not keys(action_input.baseline_design_refs) <= keys(contract.design_refs):
            raise ValueError('Claim substitutes baseline contract design versions')
        for ref in action_input.baseline_design_refs:
            design = read(ref, ContractorClaimDesignView, True, evidence_at_field='authored_at'); author(design)
            if design.contract_ref != contract.ref or design.author_action_id not in {'ARCHITECT-A05', 'ARCHITECT-A06', 'ARCHITECT-A07', 'ENGINEER-A05', 'ENGINEER-A06', 'ENGINEER-A07'}:
                raise ValueError('Claim baseline design substitutes original author/function or contract')
        for ref in action_input.instruction_refs:
            instruction = read(ref, ContractorClaimInstructionView); author(instruction)
            authority = read(instruction.authority_ref, ContractorInstructionAuthorityView, historic=True, linked=True, source_at=instruction.authored_at)
            if (instruction.contract_ref != contract.ref or authority.contract_ref != contract.ref
                    or authority.actor_id != instruction.author_actor_id or authority.function_ref != instruction.author_function_ref
                    or authority.organization_id != instruction.author_organization_id
                    or not scope_covers(authority.scope, instruction.scope)
                    or not keys(instruction.affected_task_refs) <= keys(contract.task_refs)
                    or not keys(instruction.design_refs) <= keys(action_input.baseline_design_refs)):
                raise ValueError('Instruction substitutes independent original contract scope/author authority')
            if instruction.status != 'issued' or not true(authority.permitted):
                _needs('issued_independently_authorized_contract_instruction')
        issues = []
        for ref in action_input.issue_refs:
            issue = read(ref, ContractorInterfaceIssueView)
            requirement = read(issue.requirement_ref, ContractorClaimRequirementView)
            if (issue.contract_ref != contract.ref or requirement.contract_ref != contract.ref or requirement.issue_ref != issue.ref
                    or not keys(issue.affected_task_refs) <= keys(contract.task_refs)
                    or not keys(issue.design_refs) <= keys(action_input.baseline_design_refs)):
                raise ValueError('Interface issue substitutes original contract requirement/design/task scope')
            issues.append({'scope_ref': issue.scope, 'requirement_ref': issue.requirement_ref, 'evidence_refs': issue.evidence_refs,
                'disposition': issue.disposition, 'responsible': issue.responsible.model_dump(mode='python')})
        costs = []; components = set()
        for ref in action_input.actual_cost_refs:
            cost = read(ref, ContractorActualCostView, True, evidence_at_field='authored_at'); author(cost)
            component = (cost.event_id, cost.cost_component_key)
            if (cost.contract_ref != contract.ref or cost.task_ref.key() not in keys(contract.task_refs)
                    or cost.author_organization_id != org or component in components or cost.amount.currency != contract.currency
                    or decimal_fraction(cost.amount.value) < 0 or cost.status != 'incurred'):
                raise ValueError('Actual cost substitutes original incurred component/event, contractor, contract or currency')
            # The signed incurred amount has an author time, not an invented
            # physical/financial occurrence inferred from availability.
            evidence([cost.amount.basis_ref], at=cost.authored_at); components.add(component); costs.append(cost)
        if profile.choice in {'clarify', 'respond'}:
            if not issues:
                _needs('concrete_original_interface_issues_for_response')
            return complete(profile.choice, issues=issues)
        if profile.choice == 'dispute':
            if profile.claim_ref is None or profile.claim_ref.key() not in keys(contract.claim_refs):
                _needs('original_existing_contract_claim_for_dispute')
            claim = read(profile.claim_ref, ContractorClaimView, True); author(claim)
            if claim.contract_ref != contract.ref or claim.claimant_id != org or claim.status == 'withdrawn':
                raise ValueError('Dispute substitutes original claimant/contract or withdrawn claim')
            return complete('dispute', claim_ref=claim.ref)
        if profile.change_ref is None:
            _needs('concrete_original_change_scope_and_affected_tasks')
        change = read(profile.change_ref, ContractorChangeProposalView); change_grant = author(change)
        if (change.contract_ref != contract.ref or change.author_organization_id != org or change.author_action_id != 'CONTRACTOR-A09'
                or keys(change.design_refs) != keys(action_input.baseline_design_refs)
                or keys(change.instruction_refs) != keys(action_input.instruction_refs) or keys(change.issue_refs) != keys(action_input.issue_refs)
                or not change.change_description.strip() or change.status != 'proposal' or not change.affected_task_refs
                or not scope_covers(scope, change.changed_scope)):
            raise ValueError('Change proposal substitutes original concrete scope, basis versions, affected tasks or author')
        affected = keys(change.affected_task_refs); unaffected = keys(change.unaffected_task_refs)
        if affected & unaffected or affected | unaffected != keys(contract.task_refs):
            raise ValueError('Change proposal drops or affects unchanged original tasks without explicit partition')
        original_sources = [*change.design_refs, *change.instruction_refs, *change.issue_refs, *change.affected_task_refs]
        if not keys(original_sources) <= keys(change_grant.readable_refs):
            raise ValueError('Change author lacks original design, instruction, issue or affected-task read authority')
        for ref in original_sources:
            source = reading.resolve(ref)
            if hasattr(source, 'available_at'):
                clock(source.available_at)
                if source.available_at.offset > change.authored_at.offset:
                    raise ValueError('Change proposal uses sources unavailable to its actual author')
        source_affected = set()
        for ref in action_input.instruction_refs:
            source_affected.update(keys(read(ref, ContractorClaimInstructionView).affected_task_refs))
        for ref in action_input.issue_refs:
            source_affected.update(keys(read(ref, ContractorInterfaceIssueView).affected_task_refs))
        if not source_affected <= affected:
            raise ValueError('Change proposal omits tasks affected by original instructions or interface issues')
        covered = set()
        for ref in change.affected_task_refs:
            task = read(ref, ContractorClaimTaskView)
            if task.contract_ref != contract.ref or task.organization_id != org or not keys(task.design_refs) <= keys(contract.design_refs):
                raise ValueError('Change task substitutes original contract/task/design')
            covered.update(r.key() for r in task.scope.coverage_refs)
        if not keys(change.changed_scope.coverage_refs) <= covered:
            raise ValueError('Change scope has no actual affected original task coverage')
        if not contract.claim_history_complete or contract.as_of != now:
            _needs('complete_current_original_contract_claim_history')
        evidence(contract.evidence_refs, at=now)
        history = [read(ref, ContractorClaimView, True) for ref in contract.claim_refs]; business = set()
        for row in history:
            author(row)
            if row.contract_ref != contract.ref or row.claimant_id != org or row.business_key in business:
                raise ValueError('Claim history repeats or substitutes original contract/business')
            business.add(row.business_key)
            if row.business_key == change.business_key and row.status != 'withdrawn':
                return wait('contractor-claim-existing-original-claim-continuation', [row.ref])
        if original_wait_only:
            _unsupported('contractor-claim-original-history-wait-not-reproduced')
        amount = profile.proposed_amount
        if isinstance(amount, Known):
            if profile.amount_result_ref is None:
                _needs('original_successful_change_amount_calculation')
            saved = read(profile.amount_result_ref, ContractorClaimAmountView, evidence_at_field='authored_at'); grant = author(saved)
            if saved.status == 'failed':
                technical('contractor-claim-original-valuation-failed')
            if saved.status == 'unsupported':
                _unsupported('contractor-claim-amount-method-unmodeled')
            if saved.status != 'ok' or saved.report is None:
                _needs('original_executed_amount_calculation')
            if (saved.change_ref != change.ref or saved.method_ref != CHANGE_METHOD or saved.author_organization_id != org
                    or saved.author_action_id != 'CONTRACTOR-A09' or saved.data.currency != contract.currency
                    or saved.data.decimal_places != contract.decimal_places or saved.data.basis != 'incremental'
                    or saved.input_sha256 != content_digest(saved.data) or not keys(saved.data.source_refs) <= keys(grant.readable_refs)
                    or keys(saved.cost_record_refs) != keys(action_input.actual_cost_refs)):
                raise ValueError('Claim valuation changes original amount inputs, cost provenance or read authority')
            if not {contract.ref.key(), change.ref.key()} <= keys(saved.data.source_refs):
                raise ValueError('Claim valuation omits original contract/change provenance')
            lines = [read(ref, ContractorClaimCostLineView, historic=True, evidence_at_field='authored_at') for ref in saved.line_refs]; keys(saved.line_refs)
            if [line.line for line in lines] != saved.data.lines or not keys(saved.line_refs) <= keys(saved.data.source_refs):
                raise ValueError('Claim valuation changes original sourced line versions')
            cost_map = {r.ref.key(): r for r in costs}; cost_used = set()
            for line in lines:
                line_grant = author(line)
                if line.change_ref != change.ref or line.task_ref.key() not in affected or line.author_organization_id != org:
                    raise ValueError('Claim line changes original change/affected task or author')
                if not {ref.key() for ref in [line.change_ref, line.task_ref, *line.cost_record_refs,
                        line.line.quantity_delta.basis_ref, line.line.unit_rate.basis_ref]} <= keys(line_grant.readable_refs):
                    raise ValueError('Claim line author lacks original change, task or incurred cost read authority')
                for ref in (line.change_ref, line.task_ref):
                    source = reading.resolve(ref)
                    clock(source.available_at)
                    if source.available_at.offset > line.authored_at.offset:
                        raise ValueError('Claim line predates its original change or task availability')
                evidence([line.line.quantity_delta.basis_ref, line.line.unit_rate.basis_ref], at=line.authored_at)
                if line.available_at.offset > saved.authored_at.offset:
                    raise ValueError('Claim valuation predates its original line content')
                line_costs = keys(line.cost_record_refs)
                if line.kind == 'actual_cost':
                    if not line_costs or not line_costs <= set(cost_map) or cost_used & line_costs:
                        raise ValueError('Claim valuation repeats or invents an incurred original cost component')
                    cost_used.update(line_costs)
                    if any(cost_map[key].available_at.offset > line.authored_at.offset for key in line_costs):
                        raise ValueError('Claim line uses incurred cost unavailable to its actual author')
                    total = sum((decimal_fraction(cost_map[key].amount.value) for key in line_costs), Fraction())
                    if (any(cost_map[key].task_ref != line.task_ref for key in line_costs)
                            or total != decimal_fraction(line.line.quantity_delta.value) * decimal_fraction(line.line.unit_rate.value)):
                        raise ValueError('Claim actual-cost line differs from original incurred task components')
                elif line.cost_record_refs:
                    raise ValueError('Estimate line cannot relabel already incurred costs')
            if saved.amount_kind == 'actual_cost_based' and any(line.kind != 'actual_cost' for line in lines):
                raise ValueError('Actual-cost estimate cannot include forecast lines')
            for ref in saved.data.source_refs:
                source = reading.resolve(ref)
                if ref.kind == 'Evidence':
                    evidence([ref], at=saved.authored_at)
                if hasattr(source, 'available_at'):
                    clock(source.available_at)
                    if source.available_at.offset > saved.authored_at.offset:
                        raise ValueError('Claim valuation predates original input availability')
            for line in saved.data.lines:
                evidence([line.quantity_delta.basis_ref, line.unit_rate.basis_ref], at=saved.authored_at)
                if not {line.quantity_delta.basis_ref.key(), line.unit_rate.basis_ref.key()} <= keys(grant.readable_refs):
                    raise ValueError('Claim valuation author lacks original quantity/rate evidence read authority')
            result = reading.calculate(CHANGE_METHOD, saved.data)
            if result.kind != 'ok':
                if result.kind == 'invalid_input':
                    _unsupported('contractor-claim-amount-arithmetic-domain')
                raw = result.model_dump(mode='python')
                if result.kind == 'needs_information':
                    raw['requested_refs'] = []
                raise ObservationGap(raw)
            if saved.report != result.value or amount.value != result.value.assessed_amount:
                raise ValueError('Proposed claim amount differs from original sourced arithmetic')
        elif amount.state != 'unknown':
            _needs('unknown_or_original_calculated_initial_claim_amount')
        if isinstance(profile.time_impact, Known):
            impact = read(profile.time_impact.value, ContractorTimeImpactView, evidence_at_field='authored_at'); grant = author(impact)
            method = read(impact.method_ref, ContractorClaimMethodView, historic=True, linked=True, source_at=impact.authored_at)
            if impact.status == 'failed':
                technical('contractor-claim-original-time-assessment-failed')
            if (impact.status == 'unsupported' or not true(impact.supported) or not true(method.supported)
                    or impact.author_action_id not in method.allowed_author_action_ids):
                _unsupported('contractor-claim-time-impact-method-unmodeled')
            if (impact.change_ref != change.ref or keys(impact.affected_task_refs) != affected
                    or not scope_covers(impact.scope, change.changed_scope) or not scope_covers(method.scope, impact.scope)
                    or not keys(impact.source_refs) <= keys(grant.readable_refs)
                    or not keys([impact.change_ref, impact.method_ref]) <= keys(grant.readable_refs)
                    or not affected <= keys(impact.source_refs)):
                raise ValueError('Time estimate substitutes original affected tasks/change or source read authority')
            if change.available_at.offset > impact.authored_at.offset:
                raise ValueError('Time estimate predates its original change source')
            for ref in impact.source_refs:
                source = reading.resolve(ref)
                clock(source.available_at)
                if getattr(source, 'contract_ref', None) != contract.ref or source.available_at.offset > impact.authored_at.offset:
                    raise ValueError('Time estimate substitutes original contract sources or execution availability')
                evidence(source.evidence_refs, at=impact.authored_at)
            if impact.status != 'ok':
                _needs('original_successful_time_impact_estimate')
        elif profile.time_impact.state != 'unknown':
            _needs('unknown_or_original_assessed_time_impact')
        return complete(profile.choice, basis_refs=list(evidence_refs.values()), proposed_amount=amount.model_dump(mode='python'),
            time_impact=profile.time_impact.model_dump(mode='python'), affected_task_refs=change.affected_task_refs)
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
