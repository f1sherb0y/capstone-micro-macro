"""Rejudge the original research task without extending its spending permission."""
from copy import deepcopy
from dataclasses import dataclass

from pydantic import TypeAdapter

from src.actions.contracts.common import ActionContext, EvidenceRecord, ScopeRef, ref_type
from src.actions.contracts.qs_cost_objects import QSCostBriefView
from src.actions.contracts.qs_research_objects import (
    QSResearchTaskView, QSResearchAuthorityView, QSResearchBasisView, QSResearchLimitView,
    QSResearchOptionView, QSResearchAssessmentView, QSResearchCostPlanView, QSResearchProfileView,
    QSResearchExpenseView, QSResearchCostFactView,
)
from src.coordination.continuations import ConditionProfile
from src.coordination.tasks import TaskConflict, task_digest
from src.actions.contracts.references import ActionReadView
from src.methods.pricing import decimal_fraction
from src.organization.models import Authorization, RoleAssignment
from src.organization.registry import scope_covers


_CODE = 'qs.research.task_ready'
_FIELDS = frozenset({'scope', 'brief_ref', 'research_authority_ref', 'task_ref', 'option_refs',
    'assessment_refs', 'cost_plan_refs', 'comparison_basis_ref', 'expenditure_limit_ref'})
_BASES = (('brief_ref', 'Brief', QSCostBriefView), ('task_ref', 'Task', QSResearchTaskView),
    ('research_authority_ref', 'Authority', QSResearchAuthorityView),
    ('comparison_basis_ref', 'ComparisonBasis', QSResearchBasisView),
    ('expenditure_limit_ref', 'ResearchLimit', QSResearchLimitView))


@dataclass(frozen=True)
class QSResearchConditionReading:
    context: ActionContext
    reading: ActionReadView
    original_action_input: dict
    action_input: dict


def qs_original_research_task_profile(read_current, validate_relation):
    """Ready allows fresh comparison/closure judgment, creating no research expense."""
    if not callable(read_current) or not callable(validate_relation):
        raise ValueError('QS research recovery requires actual sources and native task/permission/history validation')

    def indexed(refs):
        rows = {ref.key()[:2]: ref for ref in refs}
        if len(rows) != len(refs):
            raise TaskConflict('QS research recovery duplicates a physical source')
        return rows

    def evaluate(check):
        source, old_refs = check.source['identity'], check.condition.object_refs
        if (source['action_id'] != 'QS-A13' or source['role'] != 'QS' or source['purpose'] != 'action'
                or check.condition.condition_code != _CODE or check.condition.trigger != 'dependency_change'
                or check.signal.run_id != source['run_id'] or check.signal.organization_id != source['organization_id']
                or len(old_refs) != 1 or old_refs[0].kind != 'Task'):
            raise TaskConflict('QS research recovery substitutes original task wait or recipient')
        selected = read_current(deepcopy(check))
        if (not isinstance(selected, QSResearchConditionReading) or not isinstance(selected.context, ActionContext)
                or not isinstance(selected.reading, ActionReadView) or not isinstance(selected.original_action_input, dict)
                or not isinstance(selected.action_input, dict)):
            raise TaskConflict('QS research recovery requires typed current reading and original snapshot input')
        context, reading = selected.context.model_copy(deep=True), selected.reading
        try:
            old_input, action_input = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
            if (set(old_input) != _FIELDS or set(action_input) != _FIELDS or task_digest(old_input) != source['input_sha256']
                    or context.run_id != source['run_id'] or reading.organization_id != source['organization_id']
                    or context.contract_ref.kind != 'ActionContract' or context.contract_ref.id != 'QS-A13'
                    or context.execution_mode == 'offline_fixture' or reading._resolver.source_mode != 'formal'
                    or context.business_time != check.signal.business_time or context.operation_id == source['request_id']
                    or old_input['scope'] != action_input['scope']):
                raise TaskConflict('QS research recovery changes original snapshot, scope or current invocation')
            scope, now = TypeAdapter(ScopeRef).validate_python(action_input['scope']), context.business_time
            if context.scope != scope:
                raise TaskConflict('QS research recovery changes original comparison coverage')
            reading.check_method_context(context, 'QS-A13')
            proof_rows, proof_refs = [], []

            def read(ref, schema):
                row = reading.resolve(ref)
                if not isinstance(row, schema) or row.ref != ref or row.scope != scope:
                    raise TaskConflict('QS research recovery lacks an exact scoped original/current source')
                proof_rows.append(row)
                return row

            versions = []
            for raw in (old_input, action_input):
                rows = {field: read(ref_type(kind).model_validate(raw[field]), schema) for field, kind, schema in _BASES}
                brief, task, grant, basis, limit = (rows[field] for field, _, _ in _BASES)
                if (task.brief_ref != brief.ref or task.comparison_basis_ref != basis.ref or task.expenditure_limit_ref != limit.ref
                        or task.organization_id != source['organization_id'] or limit.task_ref != task.ref
                        or limit.organization_id != source['organization_id'] or grant.brief_ref != brief.ref or grant.task_ref != task.ref
                        or grant.delegate_organization_id != source['organization_id'] or grant.delegate_function_ref != task.function_ref
                        or grant.permission.state != 'known' or not grant.permission.value
                        or 'research' not in grant.allowed_uses or 'research' not in brief.allowed_uses):
                    raise TaskConflict('QS research recovery substitutes original task, client permission, comparison or spending limit')
                versions.append(rows)
            old, current = versions
            original, task = old['task_ref'], current['task_ref']
            old_grant, grant = old['research_authority_ref'], current['research_authority_ref']
            old_basis, basis = old['comparison_basis_ref'], current['comparison_basis_ref']
            old_limit, limit = old['expenditure_limit_ref'], current['expenditure_limit_ref']
            if (original.ref != old_refs[0] or original.status != 'waiting'
                    or any(old[field].ref.key()[:2] != current[field].ref.key()[:2] for field, _, _ in _BASES)
                    or original.function_ref != task.function_ref or task.function_ref != context.function_ref
                    or grant.delegate_actor_id != context.actor_id or task.authority_ref not in context.authorization_refs
                    or limit.authority_ref not in context.authorization_refs
                    or any(getattr(old_grant, field) != getattr(grant, field) for field in (
                        'delegate_actor_id', 'client_actor_id', 'client_organization_id', 'client_function_ref', 'client_action_id', 'allowed_uses', 'allowed_purposes'))
                    or any(getattr(old_basis, field) != getattr(basis, field) for field in ('currency', 'region_id', 'delivery_code', 'pricing_time'))
                    or old_limit.budget_cap.currency != limit.budget_cap.currency or old_limit.effort_cap.unit != limit.effort_cap.unit
                    or decimal_fraction(old_limit.budget_cap.value) != decimal_fraction(limit.budget_cap.value)
                    or decimal_fraction(old_limit.effort_cap.value) != decimal_fraction(limit.effort_cap.value)):
                raise TaskConflict('QS research recovery changes original task, client, comparison domain or research caps')
            # The original processor treats closed as a non-waiting task and
            # stops further research at its limit. Preserve that judgment path.
            if task.status == 'waiting':
                return 'waiting'
            if limit.as_of != now or any(row.available_at.clock_ref != now.clock_ref or row.available_at.offset > now.offset
                    or not row.effective_window.contains(now) for row in current.values()):
                return 'unavailable'

            def authorize(ref, actor, function_ref, action, at, roles, organization=None):
                authorization, function = reading.resolve(ref), reading.resolve(function_ref)
                actions = {'QS': {'QS-A04', 'QS-A13'}, 'Owner': {'OWN-A02', 'OWN-A04'},
                    'Architect': {'ARCHITECT-A04', 'ARCHITECT-A05', 'ARCHITECT-A13'},
                    'Engineer': {'ENGINEER-A04', 'ENGINEER-A05', 'ENGINEER-A13'}, 'Supplier': {'SUPPLIER-A02', 'SUPPLIER-A03', 'SUPPLIER-A13'}}
                if (not isinstance(authorization, Authorization) or not isinstance(function, RoleAssignment)
                        or function.function_ref != function_ref or function.role not in roles or action not in actions.get(function.role, set())
                        or authorization.actor_id != actor or authorization.function_ref != function_ref or action not in authorization.action_ids
                        or at.clock_ref != now.clock_ref or at.offset > now.offset or not authorization.validity.contains(at)
                        or organization is not None and authorization.organization_id != organization
                        or not any(scope_covers(s, scope) for s in authorization.scopes)):
                    raise TaskConflict('QS research recovery lacks original author/client or current QS task/limit authority')
                proof_refs.extend([*authorization.basis_refs, *function.basis_refs])

            for ref in (task.authority_ref, limit.authority_ref):
                authorize(ref, context.actor_id, task.function_ref, 'QS-A13', now, {'QS'}, source['organization_id'])
            for delegation in (old_grant, grant):
                if delegation.granted_at.clock_ref != delegation.available_at.clock_ref or delegation.granted_at.offset > delegation.available_at.offset:
                    raise TaskConflict('QS research delegation is available before its actual grant')
                authorize(delegation.client_authority_ref, delegation.client_actor_id, delegation.client_function_ref,
                    delegation.client_action_id, delegation.granted_at, {'Owner'}, delegation.client_organization_id)
            histories = {}
            for field, kind, schema in (('option_refs', 'DesignOption', QSResearchOptionView),
                    ('assessment_refs', 'Assessment', QSResearchAssessmentView), ('cost_plan_refs', 'CostPlan', QSResearchCostPlanView)):
                pair = []
                for raw, bases in ((old_input, old), (action_input, current)):
                    refs = indexed([ref_type(kind).model_validate(value) for value in raw[field]])
                    declared = getattr(bases['task_ref'], field)
                    if raw is action_input and {ref.key() for ref in refs.values()} != {ref.key() for ref in declared}:
                        raise TaskConflict('QS research successor lacks its exact complete current task source set')
                    for key, ref in indexed(declared).items():
                        if key in refs and refs[key] != ref:
                            raise TaskConflict('QS research history selects two versions of one declared source')
                        refs[key] = ref
                    rows = {key: read(ref, schema) for key, ref in refs.items()}
                    if any(row.brief_ref != bases['brief_ref'].ref for row in rows.values()):
                        raise TaskConflict('QS research history borrows another original brief')
                    pair.append(rows)
                if not pair[0].keys() <= pair[1].keys():
                    raise TaskConflict('QS research recovery drops original known option/assessment/cost-plan identities')
                histories[field] = {'original': [row.model_dump(mode='json') for row in pair[0].values()],
                    'current': [row.model_dump(mode='json') for row in pair[1].values()]}
            profiles, expenses = [], []
            for bases in (old, current):
                task_row, basis_row, limit_row = bases['task_ref'], bases['comparison_basis_ref'], bases['expenditure_limit_ref']
                profile = None if basis_row.comparison_profile_ref is None else read(basis_row.comparison_profile_ref, QSResearchProfileView)
                if profile is not None and (profile.task_ref != task_row.ref or profile.comparison_basis_ref != basis_row.ref):
                    raise TaskConflict('QS research profile substitutes its original task or comparison basis')
                profiles.append(None if profile is None else profile.model_dump(mode='json'))
                rows = {}
                for key, ref in indexed(limit_row.expense_refs).items():
                    expense = read(ref, QSResearchExpenseView); fact = read(expense.cost_fact_ref, QSResearchCostFactView)
                    if (expense.task_ref != task_row.ref or fact.task_ref != task_row.ref or fact.organization_id != source['organization_id']
                            or expense.status != fact.status or expense.amount != fact.amount or expense.effort != fact.effort):
                        raise TaskConflict('QS research expense substitutes original task, cost fact, amount or effort')
                    rows[key] = {'expense': expense.model_dump(mode='json'), 'fact': fact.model_dump(mode='json')}
                    proof_refs.extend([expense.amount.basis_ref, expense.effort.basis_ref])
                expenses.append(rows)
                proof_refs.extend([limit_row.budget_cap.basis_ref, limit_row.effort_cap.basis_ref])
            if not expenses[0].keys() <= expenses[1].keys():
                raise TaskConflict('QS research recovery drops original committed/incurred expense history')
            if old_basis.comparison_profile_ref is not None and (basis.comparison_profile_ref is None
                    or old_basis.comparison_profile_ref.key()[:2] != basis.comparison_profile_ref.key()[:2]
                    or any(profiles[0][field] != profiles[1][field] for field in (
                        'required_scope_keys', 'required_dimensions', 'criteria', 'missing_policy'))):
                raise TaskConflict('QS research recovery replaces its known original comparison profile or criteria')
            histories['comparison_profile'] = {'original': profiles[0], 'current': profiles[1]}
            histories['expenses'] = {'original': list(expenses[0].values()), 'current': list(expenses[1].values())}
            for row in proof_rows:
                proof_refs.extend(row.evidence_refs)
                if isinstance(row, (QSResearchOptionView, QSResearchAssessmentView, QSResearchCostPlanView)):
                    roles = {'Architect', 'Engineer'} if isinstance(row, QSResearchOptionView) else {'QS'} if isinstance(row, QSResearchCostPlanView) else {'Architect', 'Engineer', 'QS', 'Supplier'}
                    authorize(row.author_authority_ref, row.author_actor_id, row.author_function_ref,
                        row.author_action_id, row.available_at, roles)
            observed = {}
            for ref in proof_refs:
                evidence = reading.resolve(ref)
                if not isinstance(evidence, EvidenceRecord) or evidence.source_kind == 'synthetic' or evidence.basis_kind != 'observed':
                    raise TaskConflict('QS research recovery requires actual observed native task/cost/expense evidence')
                observed[ref.key()] = evidence.model_dump(mode='json')
            if validate_relation(source_identity=deepcopy(source), original_action_input=old_input, action_input=action_input,
                    original_sources={field: row.model_copy(deep=True) for field, row in old.items()},
                    current_sources={field: row.model_copy(deep=True) for field, row in current.items()},
                    research_history=deepcopy(histories), evidence=deepcopy(list(observed.values())),
                    context=context.model_copy(deep=True), reading=reading) is not True:
                raise TaskConflict('QS research recovery lacks native original-task readiness and complete research/expense history validation')
            return 'ready'
        finally:
            reading.recheck()

    return ConditionProfile('QS-A13', _CODE, '1', frozenset({'dependency_change'}), evaluate)
