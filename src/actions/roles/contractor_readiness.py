"""CONTRACTOR-A06 requests a scoped core release; it never grants it itself."""
from fractions import Fraction

from src.actions.contracts.common import EvidenceRecord, Known, walk_references
from src.actions.contracts.contractor_readiness_objects import (
    ContractorReadyTaskView, ContractorReadyProfileView, ContractorReadyRequirementView,
    ContractorReadyApplicabilityView, ContractorReadyVerificationView, ContractorReadyVerificationInput,
    ContractorReadyDesignView, ContractorReadySiteView, ContractorReadyAllocationView,
    ContractorReadyInputView, ContractorReadyAllocationFactView, ContractorReadyEvidenceView,
    ContractorReadyActionView, ContractorWorkMandateView, GovPermitView,
)
from src.actions.contracts.owner_study_objects import unique_refs
from src.actions.roles.owner import ObservationGap, _needs, _unsupported
from src.actions.roles.qs_change import content_digest
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


def check_task_readiness(context, action_input, reading):
    now, org, scope = context.business_time, reading.organization_id, context.scope
    used_evidence = {}; selected_allocations = set(); quantities = {}; physical_versions = {}
    dependency_versions = {}

    def keys(refs):
        unique_refs(refs)
        return {ref.key() for ref in refs}

    def known_true(value):
        return isinstance(value, Known) and value.value is True

    def clock(point):
        if point.clock_ref != now.clock_ref:
            _unsupported('contractor-readiness-clock-alignment')

    def evidence(refs, *, at=None, historic=False):
        point = now if at is None else at
        clock(point)
        if point.offset > now.offset:
            _needs('received_original_readiness_evidence_time')
        for ref in refs:
            row = reading.resolve(ref)
            if not isinstance(row, EvidenceRecord) or row.ref != ref:
                _unsupported('contractor-readiness-evidence-schema')
            if row.effective_window is not None:
                clock(row.effective_window.start)
                clock(row.effective_window.end)
                if row.effective_window.start.offset > now.offset:
                    _needs('received_original_readiness_evidence', [ref])
                if (at is not None or not historic) and not row.effective_window.contains(point):
                    _needs('original_readiness_evidence_valid_at_use', [ref])
            used_evidence[ref.key()] = ref

    def read(ref, schema, historic=False, linked=False, *, evidence_at_field=None):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or getattr(row, 'ref', getattr(row, 'function_ref', None)) != ref:
            _unsupported('contractor-readiness-projection:' + ref.kind)
        if hasattr(row, 'scope') and not linked and not scope_covers(scope, row.scope):
            raise ValueError('Readiness source expands original authorized task scope')
        if hasattr(row, 'available_at'):
            clock(row.available_at)
            if row.available_at.offset > now.offset:
                _needs('received_original_readiness_source', [ref])
        if hasattr(row, 'effective_window'):
            clock(row.effective_window.start)
            clock(row.effective_window.end)
            if not historic and not row.effective_window.contains(now):
                _needs('current_original_readiness_source', [ref])
        point = None if evidence_at_field is None else getattr(row, evidence_at_field)
        if point is not None:
            clock(point)
            if point.offset > row.available_at.offset:
                raise ValueError('Readiness source precedes its actual original authorship')
        evidence(getattr(row, 'evidence_refs', []), at=point, historic=historic)
        return row

    def authorize(ref, actor, function, organization, action, at, target_scope):
        grant = read(ref, Authorization, True, True); assignment = read(function, RoleAssignment, True, True)
        roles = {'CONTRACTOR': 'Contractor', 'SUPPLIER': 'Supplier', 'GOV': 'Government', 'OWN': 'Owner',
            'ARCHITECT': 'Architect', 'ENGINEER': 'Engineer', 'QS': 'QS', 'BANK': 'Bank'}
        if (grant.actor_id != actor or grant.function_ref != function or grant.organization_id != organization
                or assignment.function_ref != function or assignment.role != roles.get(action.split('-')[0]) or action not in grant.action_ids
                or not any(scope_covers(s, target_scope) for s in grant.scopes)):
            raise ValueError('Readiness evidence substitutes independent original author/function/scope authority')
        clock(at); clock(grant.validity.start); clock(grant.validity.end)
        if at.offset > now.offset:
            _needs('received_original_readiness_author_time', [ref])
        if not grant.validity.contains(at):
            _needs('original_readiness_authority_at_execution', [ref])
        for basis_ref in (*grant.basis_refs, *assignment.basis_refs):
            if basis_ref.kind == 'Evidence':
                evidence([basis_ref], at=at)
            else:
                basis = reading.resolve(basis_ref)
                if hasattr(basis, 'available_at'):
                    clock(basis.available_at)
                    if basis.available_at.offset > at.offset:
                        _needs('original_readiness_authority_basis_available_at_use', [basis_ref])
        return grant

    def author(row, actions=None):
        clock(row.authored_at)
        if (actions is not None and row.author_action_id not in actions or row.authored_at.offset > row.available_at.offset
                or not row.effective_window.contains(row.authored_at)):
            raise ValueError('Readiness source predates original execution or changes responsible function')
        return authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
            row.author_organization_id, row.author_action_id, row.authored_at, row.scope)

    def covers(outer, inner):
        clock(outer.start); clock(outer.end); clock(inner.start); clock(inner.end)
        if outer.bounds != 'closed_open' or inner.bounds != 'closed_open':
            _unsupported('contractor-readiness-half-open-window')
        return outer.start.offset <= inner.start.offset < inner.end.offset <= outer.end.offset

    def completed(choice, **fields):
        reading.recheck()
        return {'kind': 'completed', 'payload': {'choice': choice, 'task_ref': task.ref, **fields,
            'note': profile.note + ' Task-specific request only; core rechecks original gates and atomically grants release. Missing evidence is unknown, no whole-project release, permit approval, stock or actual output is inferred.'}}

    def wait(code, refs):
        reading.recheck()
        return {'kind': 'deferred', 'reason_code': code, 'resume_condition': {'trigger': 'dependency_change',
            'object_refs': refs, 'earliest_time': None, 'condition_code': code}}

    def technical(code):
        raise ObservationGap({'kind': 'technical_error', 'error': {'kind': 'unrecorded',
            'correlation_id': context.operation_id, 'code': code}, 'retryability': 'unknown'})

    def dependency_cycle(root):
        visiting, seen = set(), set()
        def visit(row):
            key = (row.ref.kind, row.ref.id)
            if key in dependency_versions and dependency_versions[key] != row.ref:
                raise ValueError('Readiness dependency graph mixes versions of the same physical task')
            dependency_versions[key] = row.ref
            if key in visiting:
                return True
            if key in seen:
                return False
            visiting.add(key); keys(row.predecessor_task_refs)
            for ref in row.predecessor_task_refs:
                predecessor = read(ref, ContractorReadyTaskView, linked=True)
                if visit(predecessor):
                    return True
            visiting.remove(key); seen.add(key)
            return False
        return visit(root)

    def source_ready(ref, requirement):
        category = requirement.category
        if category == 'permit':
            if ref.kind != 'Permit' or ref.key() not in keys(action_input.permit_refs):
                return False, None
            row = read(ref, GovPermitView, historic=True, linked=True)
            evidence(row.evidence_refs, at=now)
            ready = (row.status == 'valid' and known_true(row.effective) and scope_covers(row.scope, task.scope)
                and task.action_ref.key() in keys(row.allowed_action_refs) and covers(row.effective_window, task.execution_window))
        elif category == 'design':
            if ref.kind != 'DeliverableRelease' or ref.key() not in keys(action_input.design_release_refs):
                return False, None
            row = read(ref, ContractorReadyDesignView, historic=True, linked=True, evidence_at_field='authored_at')
            author(row, {'ARCHITECT-A07', 'ENGINEER-A07', 'QS-A05'})
            ready = (row.mandate_ref == task.mandate_ref and row.purpose == task.purpose and known_true(row.released)
                and task.action_ref.key() in keys(row.allowed_action_refs) and scope_covers(row.scope, task.scope)
                and covers(row.effective_window, task.execution_window) and row.check_coverage == 'complete')
            keys(row.professional_check_refs)
            for check_ref in row.professional_check_refs:
                check = read(check_ref, ContractorReadyVerificationView, evidence_at_field='authored_at'); author(check)
                if check.status == 'failed':
                    technical('contractor-readiness-original-professional-check-failed')
                if check.status == 'unsupported':
                    _unsupported('contractor-readiness-original-professional-check-unmodeled')
                if (check.task_ref != task.ref or check.requirement_ref != requirement.ref
                        or check.status != 'ok' or not known_true(check.satisfied)):
                    ready = False
        elif category == 'site':
            if ref.kind != 'SiteReadiness' or ref.key() not in keys(action_input.site_refs):
                return False, None
            row = read(ref, ContractorReadySiteView, historic=True, linked=True, evidence_at_field='authored_at'); author(row)
            evidence(row.evidence_refs, at=now)
            ready = (row.task_ref == task.ref and row.organization_id == org and row.as_of == now
                and known_true(row.physically_delivered) and known_true(row.safe_access)
                and scope_covers(row.scope, task.scope) and covers(row.effective_window, task.execution_window))
        elif category in {'resource', 'material'}:
            if ref.kind != 'ResourceAllocation' or ref.key() not in keys(action_input.input_allocation_refs):
                return False, None
            row = read(ref, ContractorReadyAllocationView, historic=True)
            if ref.key() in selected_allocations:
                raise ValueError('Readiness counts the same original allocation for multiple necessary requirements')
            selected_allocations.add(ref.key())
            resource = read(row.resource_ref, ContractorReadyInputView, historic=True, linked=True)
            evidence([*row.evidence_refs, *resource.evidence_refs], at=now)
            physical_key = (resource.ref.kind, resource.ref.id)
            if physical_key in physical_versions and physical_versions[physical_key] != resource.ref.version:
                raise ValueError('Readiness duplicates physical input across distinct versions')
            physical_versions[physical_key] = resource.ref.version
            if row.resource_kind != category or resource.organization_id != org or row.organization_id != org or row.task_ref != task.ref:
                raise ValueError('Readiness allocation substitutes actual input owner/type/task')
            amount = decimal_fraction(row.quantity.value); evidence([row.quantity.basis_ref]); keys(resource.allocations)
            if row.commitment_ref.key() not in keys(resource.allocations):
                raise ValueError('Readiness allocation is absent from complete original input reservations')
            facts = [read(r, ContractorReadyAllocationFactView, historic=True, linked=True) for r in resource.allocations]
            if any(f.resource_ref != resource.ref or f.quantity.unit != row.quantity.unit or decimal_fraction(f.quantity.value) < 0 for f in facts):
                raise ValueError('Readiness input ledger changes original physical resource or exact unit')
            if len({f.core_event_id for f in facts}) != len(facts):
                raise ValueError('Readiness input ledger repeats the same original core allocation event')
            for fact in facts:
                clock(fact.execution_window.start); clock(fact.execution_window.end)
                if fact.execution_window.bounds != 'closed_open' or fact.execution_window.start.offset >= fact.execution_window.end.offset:
                    _unsupported('contractor-readiness-actual-allocation-window-domain')
                evidence([fact.quantity.basis_ref], historic=True)
            matching = next(f for f in facts if f.ref == row.commitment_ref)
            if (matching.task_ref != task.ref or matching.allocation_ref != row.ref or matching.quantity != row.quantity
                    or matching.execution_window != row.execution_window or matching.status != 'reserved'):
                raise ValueError('Readiness allocation changes original core reservation identity/quantity/window')
            available = resource.actual_available
            ready = (resource.history_coverage == 'complete' and resource.as_of == now and row.as_of == now
                and row.status in {'reserved', 'available'} and amount > 0 and known_true(resource.accepted)
                and isinstance(available, Known) and available.value.unit == row.quantity.unit
                and covers(row.execution_window, task.execution_window) and covers(resource.effective_window, task.execution_window))
            if isinstance(available, Known):
                evidence([available.value.basis_ref])
                basis = reading.resolve(available.value.basis_ref)
                if basis.basis_kind != 'observed' or (reading._resolver.source_mode == 'formal' and basis.source_kind == 'synthetic'):
                    ready = False
                actual = decimal_fraction(available.value.value)
                if category == 'material':
                    occupied = sum((decimal_fraction(f.quantity.value) for f in facts if f.status == 'reserved'), Fraction())
                    ready = ready and occupied <= actual and actual > 0
                else:
                    boundaries = {task.execution_window.start.offset, task.execution_window.end.offset}
                    for fact in facts:
                        clock(fact.execution_window.start)
                        boundaries.update([max(task.execution_window.start.offset, fact.execution_window.start.offset),
                            min(task.execution_window.end.offset, fact.execution_window.end.offset)])
                    points = sorted(p for p in boundaries if task.execution_window.start.offset <= p <= task.execution_window.end.offset)
                    for start, end in zip(points, points[1:]):
                        occupied = sum((decimal_fraction(f.quantity.value) for f in facts if f.status == 'reserved'
                            and f.execution_window.start.offset < end and start < f.execution_window.end.offset), Fraction())
                        ready = ready and occupied <= actual and actual > 0
            if ready:
                quantities[requirement.ref.key()] = quantities.get(requirement.ref.key(), Fraction()) + amount
        elif category == 'predecessor':
            if ref.kind != 'Task' or ref.key() not in keys(task.predecessor_task_refs):
                return False, None
            row = read(ref, ContractorReadyTaskView, linked=True)
            ready = row.state == 'complete' and row.history_coverage == 'complete' and row.as_of == now
        else:
            if ref.kind != 'ReadinessEvidence':
                return False, None
            row = read(ref, ContractorReadyEvidenceView, historic=True, evidence_at_field='authored_at'); author(row)
            ready = (row.task_ref == task.ref and row.requirement_ref == requirement.ref and row.category == category
                and known_true(row.actual) and scope_covers(row.scope, requirement.scope)
                and covers(row.effective_window, task.execution_window))
        return ready, row

    try:
        for refs in (action_input.readiness_requirement_refs, action_input.permit_refs, action_input.design_release_refs,
                action_input.site_refs, action_input.input_allocation_refs):
            keys(refs)
        task = read(action_input.task_ref, ContractorReadyTaskView)
        profile = read(action_input.readiness_profile_ref, ContractorReadyProfileView)
        mandate = read(task.mandate_ref, ContractorWorkMandateView, linked=True)
        action = read(task.action_ref, ContractorReadyActionView)
        if (task.organization_id != org or profile.organization_id != org or profile.task_ref != task.ref
                or task.readiness_profile_ref != profile.ref or profile.authority_ref not in context.authorization_refs
                or task.scope != scope or action.mandate_ref != mandate.ref or action.purpose != task.purpose
                or mandate.organization_id != org or not scope_covers(mandate.scope, task.scope)):
            raise ValueError('Readiness changes original contractor/task/action/mandate or acting scope authority')
        authorize(profile.authority_ref, context.actor_id, context.function_ref, org, 'CONTRACTOR-A06', now, scope)
        if not known_true(mandate.effective) or task.purpose not in mandate.allowed_task_purposes or mandate.mandate_kind == 'preparation' and task.purpose != 'preparation':
            _needs('effective_original_mandate_for_exact_task_purpose')
        if (task.history_coverage != 'complete' or task.as_of != now
                or keys(task.requirement_refs) != keys(profile.requirement_refs)
                or keys(task.requirement_refs) != keys(action_input.readiness_requirement_refs)):
            _needs('complete_current_original_task_readiness_requirements')
        if task.state in {'released', 'working', 'complete', 'cancelled'}:
            return wait('contractor-readiness-original-task-already-released-or-terminal', [task.ref])
        if not covers(mandate.effective_window, task.execution_window) or task.execution_window.start.offset < now.offset:
            _needs('original_current_execution_window_within_mandate')
        cyclic = dependency_cycle(task)
        if profile.choice == 'resequence':
            if not profile.replacement_task_refs:
                _needs('explicit_original_independent_replacement_tasks')
            keys(profile.replacement_task_refs)
            for ref in profile.replacement_task_refs:
                replacement = read(ref, ContractorReadyTaskView)
                if (replacement.ref.key()[:2] == task.ref.key()[:2]
                        or replacement.organization_id != org or replacement.mandate_ref != task.mandate_ref
                        or replacement.history_coverage != 'complete' or replacement.as_of != now
                        or replacement.state not in {'planned', 'blocked'} or replacement.purpose not in mandate.allowed_task_purposes
                        or replacement.ref.key()[:2] in {r.key()[:2] for r in task.predecessor_task_refs}
                        or task.ref.key()[:2] in {r.key()[:2] for r in replacement.predecessor_task_refs}):
                    raise ValueError('Resequencing changes original independent task/mandate/purpose or predecessor relation')
                if dependency_cycle(replacement):
                    return wait('contractor-readiness-replacement-task-dependency-cycle', [ref])
            return completed('resequence', replacement_task_refs=profile.replacement_task_refs)
        requirements = [read(ref, ContractorReadyRequirementView) for ref in task.requirement_refs]
        if not requirements:
            _needs('nonempty_original_necessary_readiness_requirements')
        mandatory_categories = {'permit', 'design', 'site', 'resource', 'authority'} if task.purpose == 'construction' else {'authority'}
        if task.predecessor_task_refs:
            mandatory_categories.add('predecessor')
        if not mandatory_categories <= {r.category for r in requirements if r.necessary}:
            _needs('complete_original_necessary_task_gate_categories')
        gaps = []
        for requirement in requirements:
            if requirement.task_ref != task.ref or not scope_covers(task.scope, requirement.scope):
                raise ValueError('Readiness requirement changes original task or scope')
            applicability = read(requirement.applicability_ref, ContractorReadyApplicabilityView, linked=True, evidence_at_field='authored_at')
            applicability_grant = author(applicability)
            if (not {task.ref.key(), requirement.ref.key(), *(ref.key() for ref in applicability.evidence_refs)}
                    <= keys(applicability_grant.readable_refs)
                    or max(task.available_at.offset, requirement.available_at.offset) > applicability.authored_at.offset):
                raise ValueError('Readiness applicability lacks original task/requirement read authority or availability')
            if (applicability.task_ref != task.ref or applicability.requirement_ref != requirement.ref
                    or not scope_covers(applicability.scope, requirement.scope)
                    or applicability.applicable != requirement.applicable
                    or applicability.author_organization_id != requirement.verifier_organization_id
                    or applicability.author_action_id != requirement.verifier_action_id):
                raise ValueError('Readiness requirement changes independent original applicability')
            ready = isinstance(requirement.applicable, Known) and not requirement.applicable.value
            rows = []
            if known_true(requirement.applicable):
                ready = bool(requirement.source_refs)
                keys(requirement.source_refs)
                for ref in requirement.source_refs:
                    valid, row = source_ready(ref, requirement); ready = ready and valid
                    if row is not None:
                        rows.append(row)
                if requirement.category in {'resource', 'material'}:
                    minimum = requirement.minimum_quantity
                    if minimum is None or decimal_fraction(minimum.value) <= 0:
                        raise ValueError('Required actual input must declare a positive exact minimum')
                    evidence([minimum.basis_ref])
                    if any(r.quantity.unit != minimum.unit for r in rows):
                        raise ValueError('Readiness required input does not infer unit conversion')
                    ready = ready and quantities.get(requirement.ref.key(), Fraction()) >= decimal_fraction(minimum.value)
                if requirement.verification_ref is None:
                    ready = False
                else:
                    verification = read(requirement.verification_ref, ContractorReadyVerificationView, linked=True, evidence_at_field='authored_at')
                    grant = author(verification)
                    if (verification.task_ref != task.ref or verification.requirement_ref != requirement.ref
                            or not scope_covers(verification.scope, requirement.scope)
                            or verification.author_organization_id != requirement.verifier_organization_id
                            or verification.author_action_id != requirement.verifier_action_id
                            or keys(verification.source_refs) != keys(requirement.source_refs)):
                        raise ValueError('Readiness verification substitutes original task, independent verifier or source set')
                    data = ContractorReadyVerificationInput(task_ref=task.ref, requirement_ref=requirement.ref,
                        requirement_sha256=content_digest(requirement), applicability_sha256=content_digest(applicability),
                        task_scope=task.scope, execution_window=task.execution_window, applicability_ref=applicability.ref,
                        source_refs=[r.ref for r in rows], source_sha256s=[content_digest(r) for r in rows])
                    if len(rows) == len(requirement.source_refs):
                        original_evidence = {ref.key(): ref for row in rows
                            for ref in walk_references(row) if ref.kind == 'Evidence'}
                        if (verification.input_sha256 != content_digest(data)
                                or not {task.ref.key(), requirement.ref.key(), applicability.ref.key(),
                                    *(r.ref.key() for r in rows), *(ref.key() for ref in verification.evidence_refs),
                                    *original_evidence} <= keys(grant.readable_refs)
                                or max(task.available_at.offset, requirement.available_at.offset, applicability.available_at.offset)
                                    > verification.authored_at.offset
                                or any(r.available_at.offset > verification.authored_at.offset for r in rows)):
                            raise ValueError('Readiness verification changes original saved source content/read authority/execution')
                        evidence(original_evidence.values(), at=verification.authored_at)
                    if verification.status == 'failed':
                        technical('contractor-readiness-original-verification-failed')
                    if verification.status == 'unsupported':
                        _unsupported('contractor-readiness-original-verification-unmodeled')
                    ready = ready and verification.status == 'ok' and known_true(verification.satisfied) and covers(verification.effective_window, task.execution_window)
            if requirement.category == 'predecessor' and cyclic:
                ready = False
            if requirement.necessary and not ready:
                gaps.append({'scope_ref': requirement.scope, 'requirement_ref': requirement.ref,
                    'evidence_refs': requirement.evidence_refs, 'disposition': requirement.disposition,
                    'responsible': requirement.responsible.model_dump(mode='python')})
        if profile.choice == 'rectify_dependency':
            if not gaps:
                _needs('actual_original_unresolved_readiness_requirements')
            return completed('rectify_dependency', issues=gaps)
        if cyclic:
            return wait('contractor-readiness-original-circular-dependency', task.predecessor_task_refs)
        if gaps:
            _needs('necessary_task_readiness_evidence_or_actual_inputs_missing', [g['requirement_ref'] for g in gaps])
        predecessor_sources = {ref.key() for requirement in requirements if requirement.category == 'predecessor'
            and requirement.necessary for ref in requirement.source_refs if ref.kind == 'Task'}
        if predecessor_sources != keys(task.predecessor_task_refs):
            _needs('all_original_predecessor_tasks_in_necessary_release_gates')
        return completed('request_release', evidence_refs=list(used_evidence.values()))
    except ObservationGap as gap:
        reading.recheck()
        return gap.result
