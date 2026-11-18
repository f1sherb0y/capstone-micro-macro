"""Rejudge an original investment wait without clearing portfolio obligations."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.owner_investment_objects import (
    InvestmentCaseView, InvestmentObjectiveView, InvestmentComparisonView, InvestmentRegistrationView,
    InvestmentPortfolioView, InvestmentFundingSourceView, InvestmentResourceView, InvestmentObligationView,
    InvestmentOptionView, InvestmentPlanView,
)
from src.actions.roles.owner_investment import decide_investment
from src.coordination.continuations import ConditionProfile
from src.coordination.owner_saved_wait_conditions import OwnerSavedWaitConditionReading, read_owner_saved_wait
from src.coordination.tasks import TaskConflict
from src.methods.pricing import decimal_fraction


CODE = 'owner.investment.inputs_changed'


@dataclass(frozen=True)
class OwnerInvestmentConditionReading(OwnerSavedWaitConditionReading):
    """Actual saved A03 result and independently authorized current comparison."""


def check_owner_investment_conditions(check, selected, validate_relation):
    old_input, current_input, saved = read_owner_saved_wait(check, selected, validate_relation,
        action_id='OWN-A03', code=CODE,
        kinds=('OptionComparison', 'ProjectRegistrationProfile', 'OwnerPortfolio'),
        reading_type=OwnerInvestmentConditionReading)
    source = check.source['identity']
    context, original, reading = selected.context, selected.original_context, selected.reading
    old_sources = {tuple(row['ref'][key] for key in ('kind', 'id', 'version')) for row in saved['source_reading']}

    def physical(refs):
        rows = {ref.key()[:2]: ref for ref in refs}
        if len(rows) != len(refs):
            raise TaskConflict('Owner investment recovery aliases physical portfolio/source/history identities')
        return rows

    def read(ref, schema, at):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Owner investment recovery requires exact typed original/current sources')
        point = getattr(row, 'available_at', getattr(row, 'updated_at', None))
        if point is not None and (point.clock_ref != at.clock_ref or point.offset > at.offset):
            raise TaskConflict('Owner investment recovery imports information unavailable at its read time')
        return row

    fields = ('case_ref', 'comparison_ref', 'objective_ref', 'portfolio_ref', 'registration_profile_ref')
    if (tuple(getattr(old_input, name) for name in ('comparison_ref', 'registration_profile_ref', 'portfolio_ref'))
                != tuple(check.condition.object_refs)
            or selected.history_ref != current_input.comparison_ref
            or any(getattr(old_input, name).key()[:2] != getattr(current_input, name).key()[:2] for name in fields)):
        raise TaskConflict('Owner investment recovery substitutes its original case, comparison, objective or portfolio')
    versions = []
    for values, invocation in ((old_input, original), (current_input, context)):
        at = invocation.business_time
        case = read(values.case_ref, InvestmentCaseView, at)
        objective = read(values.objective_ref, InvestmentObjectiveView, at)
        comparison = read(values.comparison_ref, InvestmentComparisonView, at)
        profile = read(values.registration_profile_ref, InvestmentRegistrationView, at)
        portfolio = read(values.portfolio_ref, InvestmentPortfolioView, at)
        if (any(row.organization_id != source['organization_id'] for row in (case, objective, comparison, profile, portfolio))
                or case.objective_ref != objective.ref or comparison.case_ref != case.ref
                or comparison.objective_ref != objective.ref or profile.case_ref != case.ref
                or profile.comparison_ref != comparison.ref or comparison.ref not in case.comparison_refs
                or invocation.scope.kind != 'assessment_case' or invocation.scope.ref != case.ref
                or portfolio.as_of != at or portfolio.coverage != 'complete'
                or values.funding_lines != portfolio.funding_lines):
            raise TaskConflict('Owner investment recovery changes its owner or complete same-version comparison/portfolio')
        inventories = {}
        for name, refs, schema, owner_field in (
                ('funding', portfolio.source_refs, InvestmentFundingSourceView, 'organization_id'),
                ('resources', portfolio.resource_refs, InvestmentResourceView, 'organization_id'),
                ('obligations', portfolio.obligation_refs, InvestmentObligationView, 'debtor_organization_id')):
            rows = {}
            for key, ref in physical(refs).items():
                # An early policy wait may precede dependency reads. Missing
                # original projections stay explicit; they never become zero.
                row = None if values is old_input and ref.key() not in old_sources else read(ref, schema, at)
                if row is not None and (getattr(row, owner_field) != source['organization_id'] or row.as_of != at):
                    raise TaskConflict('Owner investment recovery borrows another organization resources, money or debt')
                rows[key] = row
            inventories[name] = rows
        plans = {}
        for ref in comparison.option_refs:
            if values is old_input and ref.key() not in old_sources:
                continue
            option = read(ref, InvestmentOptionView, at)
            if (option.organization_id != source['organization_id'] or option.case_ref != case.ref
                    or option.comparison_ref != comparison.ref or option.objective_ref != objective.ref):
                raise TaskConflict('Owner investment recovery substitutes compared option ownership or versions')
            for plan_ref in (option.preparation_plan_ref, option.investment_plan_ref):
                if plan_ref is None or values is old_input and plan_ref.key() not in old_sources:
                    continue
                plan = read(plan_ref, InvestmentPlanView, at)
                if (plan.organization_id != source['organization_id'] or plan.case_ref != case.ref
                        or plan.option_ref != option.ref or plan.ref.key()[:2] in plans):
                    raise TaskConflict('Owner investment recovery aliases a plan or changes its original owner/case/option')
                plans[plan.ref.key()[:2]] = plan
        versions.append(dict(case=case, objective=objective, comparison=comparison,
            profile=profile, portfolio=portfolio, plans=plans, **inventories))
    old, current = versions
    if old['objective'].template != current['objective'].template:
        raise TaskConflict('Owner investment recovery changes its original objective template')
    for name in ('funding', 'resources', 'obligations'):
        if not set(old[name]) <= set(current[name]):
            raise TaskConflict('Owner investment recovery omits original portfolio accounts, resource pools or obligations')

    def retained_money(before, after):
        if before.state != 'known':
            return True
        if after.state != 'known':
            return False
        if (before.value.currency != after.value.currency
                or decimal_fraction(after.value.value) < decimal_fraction(before.value.value)):
            raise TaskConflict('Owner investment recovery clears an incurred, owed or already paid amount')
        return True

    obligations = []
    for key, before in old['obligations'].items():
        after = current['obligations'][key]
        if before is not None:
            if (before.origin_ref.key()[:2] != after.origin_ref.key()[:2]
                    or before.source_ref.key()[:2] != after.source_ref.key()[:2]
                    or before.debtor_organization_id != after.debtor_organization_id):
                raise TaskConflict('Owner investment recovery transfers existing debt to a new origin, account or debtor')
            if not all(retained_money(getattr(before, name), getattr(after, name)) for name in ('actual_due', 'actual_paid')):
                return 'waiting', None
        obligations.append({'original_ref': physical(old['portfolio'].obligation_refs)[key].model_dump(mode='json'),
            'original': None if before is None else before.model_dump(mode='json'), 'current': after.model_dump(mode='json')})
    plans = []
    for key, before in old['plans'].items():
        after = current['plans'].get(key)
        if before.incurred_cost.state == 'known' and decimal_fraction(before.incurred_cost.value.value) > 0:
            if after is None:
                raise TaskConflict('Owner investment recovery drops an existing plan with actual incurred costs')
            if not retained_money(before.incurred_cost, after.incurred_cost):
                return 'waiting', None
        plans.append({'original': before.model_dump(mode='json'), 'current': None if after is None else after.model_dump(mode='json')})
    loads = []
    for key, before in old['resources'].items():
        after = current['resources'][key]
        current_loads = {row.ref.key()[:2]: row for row in after.commitments}
        for load in before.commitments if before is not None else ():
            updated = current_loads.get(load.ref.key()[:2])
            if updated is not None and load.ref == updated.ref and load != updated:
                raise TaskConflict('Owner investment recovery rewrites an immutable resource commitment')
            loads.append({'resource_ref': before.ref.model_dump(mode='json'), 'original': load.model_dump(mode='json'),
                'current': None if updated is None else updated.model_dump(mode='json')})

    result = decide_investment(context, current_input, reading)
    if result.get('kind') != 'completed':
        return 'waiting', None
    selected.contract.validate_decision(current_input, result['payload'])
    actual_evidence = []

    def observed(state):
        if state.state != 'known':
            return
        record = read(state.value.basis_ref, EvidenceRecord, context.business_time)
        if (record.source_kind == 'synthetic' or record.basis_kind != 'observed'
                or record.effective_window is not None and not record.effective_window.contains(context.business_time)):
            raise TaskConflict('Formal investment recovery requires observed actual money, costs and resource loads')
        actual_evidence.append(record.model_dump(mode='json'))

    for row in current['funding'].values():
        observed(row.actual_cash)
        observed(row.restricted_cash)
    for row in current['obligations'].values():
        observed(row.actual_due)
        observed(row.actual_paid)
    for row in current['plans'].values():
        observed(row.incurred_cost)
    for row in current['resources'].values():
        observed(row.total)
        for load in row.commitments:
            record = read(load.quantity.basis_ref, EvidenceRecord, context.business_time)
            if record.source_kind == 'synthetic' or record.basis_kind != 'observed':
                raise TaskConflict('Formal investment recovery cannot fabricate actual resource commitments')
            actual_evidence.append(record.model_dump(mode='json'))
    resolution = dict(schema_version='owner-investment-conditions-resolution.v1', condition_code=CODE,
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_action_input=deepcopy(selected.original_action_input), action_input=deepcopy(selected.action_input),
        original_record=saved, retained_obligations=obligations, retained_plans=plans,
        original_commitments=loads, actual_evidence=actual_evidence,
        original_comparison=old['comparison'].model_dump(mode='json'), comparison=current['comparison'].model_dump(mode='json'),
        sources=reading.evidence(), methods=reading.method_evidence(),
        current_result=selected.contract.result_adapter.validate_python(result).model_dump(mode='json'))
    if validate_relation(source_identity=deepcopy(source), condition_code=CODE, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Owner investment recovery lacks native original-audit, comparison, cash, debt and capacity authentication')
    return 'ready', resolution


def owner_original_investment_profile(read_current, validate_relation, condition_code=CODE):
    if condition_code != CODE or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Owner investment recovery requires guarded original/current sources and native validation')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_owner_investment_conditions(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('OWN-A03', CODE, '1', frozenset({'dependency_change'}), evaluate)
