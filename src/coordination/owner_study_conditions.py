"""Recover bounded study waits while retaining actual costs and original debtors."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.owner_proposal_objects import ProposalFundingView
from src.actions.contracts.owner_study_objects import (
    StudyCaseView, StudyProfileView, StudyPriorPlanView, StudyObligationView, StudyResourceView,
)
from src.actions.roles.owner_study import authorize_study
from src.coordination.continuations import ConditionProfile
from src.coordination.owner_saved_wait_conditions import OwnerSavedWaitConditionReading, read_owner_saved_wait
from src.coordination.tasks import TaskConflict
from src.methods.pricing import decimal_fraction


CODE = 'owner.study.conditions_changed'


@dataclass(frozen=True)
class OwnerStudyConditionReading(OwnerSavedWaitConditionReading):
    """Saved original A02 and current study input under the actual read guard."""


def check_owner_study_conditions(check, selected, validate_relation):
    old_input, current_input, saved = read_owner_saved_wait(check, selected, validate_relation,
        action_id='OWN-A02', code=CODE, kinds=('StudyProfile', 'FundingPosition'),
        reading_type=OwnerStudyConditionReading)
    source = check.source['identity']
    context, original, reading = selected.context, selected.original_context, selected.reading
    raw, current_raw = deepcopy(selected.original_action_input), deepcopy(selected.action_input)
    contract = selected.contract

    def physical(refs):
        rows = {ref.key()[:2]: ref for ref in refs}
        if len(rows) != len(refs):
            raise TaskConflict('Owner study recovery repeats physical issue, history or obligation identities')
        return rows

    def read(ref, schema, at):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Owner study recovery requires exact typed source versions')
        point = getattr(row, 'available_at', getattr(row, 'updated_at', None))
        if point is not None and (point.clock_ref != at.clock_ref or point.offset > at.offset):
            raise TaskConflict('Owner study recovery imports future information into an original/current snapshot')
        return row

    if (old_input.study_profile_ref != check.condition.object_refs[0]
            or current_input.study_profile_ref != selected.history_ref
            or old_input.study_profile_ref.key()[:2] != current_input.study_profile_ref.key()[:2]
            or old_input.case_ref.key()[:2] != current_input.case_ref.key()[:2]
            or old_input.spending_limit != current_input.spending_limit
            or old_input.brief_ref is not None and (current_input.brief_ref is None
                or current_input.brief_ref.key()[:2] != old_input.brief_ref.key()[:2])):
        raise TaskConflict('Owner study recovery substitutes its case/profile, brief or original expenditure authority')
    for name in ('issue_refs', 'service_candidates'):
        if not set(physical(getattr(old_input, name))) <= set(physical(getattr(current_input, name))):
            raise TaskConflict('Owner study recovery drops originally supplied questions or received offers')
    versions = []
    for values, at, scope in ((old_input, original.business_time, original.scope),
            (current_input, context.business_time, context.scope)):
        case = read(values.case_ref, StudyCaseView, at)
        profile = read(values.study_profile_ref, StudyProfileView, at)
        if (scope.kind != 'assessment_case' or scope.ref != case.ref
                or case.organization_id != source['organization_id'] or profile.organization_id != source['organization_id']
                or profile.case_ref != case.ref or profile.as_of != at or profile.history_coverage != 'complete'
                or set(profile.history_refs) != set(case.study_refs)):
            raise TaskConflict('Owner study recovery changes its own case or complete original/current study history')
        histories, debts = {}, {}
        for key, ref in physical(profile.history_refs).items():
            prior = read(ref, StudyPriorPlanView, at)
            if (prior.organization_id != source['organization_id'] or prior.case_ref != case.ref
                    or prior.linked_project_ref != case.linked_project_ref):
                raise TaskConflict('Owner study recovery changes original cost/case/project lineage')
            histories[key] = prior
            for debt_key, debt_ref in physical(prior.obligation_refs).items():
                debt = read(debt_ref, StudyObligationView, at)
                if (debt_key in debts or debt.debtor_organization_id != source['organization_id']
                        or debt.origin_case_ref != case.ref or debt.origin_study_ref != prior.ref
                        or debt.linked_project_ref != case.linked_project_ref or debt.as_of != at):
                    raise TaskConflict('Owner study recovery changes a debtor or duplicates/hides original obligations')
                debts[debt_key] = debt
        versions.append(dict(case=case, profile=profile, histories=histories, debts=debts))
    old, current = versions
    if (old['profile'].funding_ref != check.condition.object_refs[1]
            or old['profile'].funding_ref.key()[:2] != current['profile'].funding_ref.key()[:2]
            or old['case'].objective_ref.key()[:2] != current['case'].objective_ref.key()[:2]
            or old['case'].linked_project_ref is not None and (current['case'].linked_project_ref is None
                or old['case'].linked_project_ref.key()[:2] != current['case'].linked_project_ref.key()[:2])):
        raise TaskConflict('Owner study recovery substitutes its original funding/objective or existing project')
    for name in ('histories', 'debts'):
        if not set(old[name]) <= set(current[name]):
            raise TaskConflict('Owner study recovery erases actual costs or obligations from complete history')

    def retain_money(before, after):
        if before.currency != after.currency or decimal_fraction(after.value) < decimal_fraction(before.value):
            raise TaskConflict('Owner study recovery clears already incurred/owed/paid amounts or changes their currency')

    retained = []
    for key, before in old['histories'].items():
        after = current['histories'][key]
        if before.incurred_cost.state != 'known' or after.incurred_cost.state != 'known':
            return 'waiting', None
        retain_money(before.incurred_cost.value, after.incurred_cost.value)
        if not set(physical(before.obligation_refs)) <= set(physical(after.obligation_refs)):
            raise TaskConflict('Owner study recovery moves old fees away from the original study')
        retained.append({'original': before.model_dump(mode='json'), 'current': after.model_dump(mode='json')})
    for key, before in old['debts'].items():
        after = current['debts'][key]
        if (before.debtor_organization_id != after.debtor_organization_id
                or before.origin_case_ref.key()[:2] != after.origin_case_ref.key()[:2]
                or before.origin_study_ref.key()[:2] != after.origin_study_ref.key()[:2]):
            raise TaskConflict('Owner study recovery transfers a historical debt to another debtor/case/study')
        retain_money(before.actual_due, after.actual_due)
        retain_money(before.actual_paid, after.actual_paid)

    # Saved method evidence belongs to the original operation. Only the current
    # judgment calculates methods; no historical calculation is run or invented.
    current_result = authorize_study(context, current_input, reading)
    if current_result.get('kind') != 'completed':
        return 'waiting', None
    payload = contract.validate_decision(current_input, current_result['payload'])
    actual_evidence = []

    def observed_amount(value):
        record = read(value.basis_ref, EvidenceRecord, context.business_time)
        if (record.source_kind == 'synthetic' or record.basis_kind != 'observed'
                or record.effective_window is not None and not record.effective_window.contains(context.business_time)):
            raise TaskConflict('Formal study recovery requires observed actual costs, funding and resource loads')
        actual_evidence.append(record.model_dump(mode='json'))

    for prior in current['histories'].values():
        observed_amount(prior.incurred_cost.value)
    for debt in current['debts'].values():
        observed_amount(debt.actual_due)
        observed_amount(debt.actual_paid)
    if payload.choice == 'internal_study':
        for allocation in payload.allocations:
            pool = read(allocation.resource_ref, StudyResourceView, context.business_time)
            if pool.total.state != 'known':
                return 'waiting', None
            observed_amount(pool.total.value)
            for load in pool.commitments:
                observed_amount(load.quantity)
    if payload.choice != 'stop':
        funding = read(current['profile'].funding_ref, ProposalFundingView, context.business_time)
        if funding.organization_id != source['organization_id'] or funding.as_of != context.business_time or funding.coverage != 'complete':
            return 'waiting', None
        for value in (funding.actual_cash, funding.committed_cash, funding.restricted_cash):
            if value.state != 'known':
                return 'waiting', None
            observed_amount(value.value)
    resolution = dict(schema_version='owner-study-conditions-resolution.v1', condition_code=CODE,
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_action_input=raw, action_input=current_raw, original_record=saved,
        retained_studies=retained,
        retained_obligations=[{'original': before.model_dump(mode='json'),
            'current': current['debts'][key].model_dump(mode='json')} for key, before in old['debts'].items()],
        actual_evidence=actual_evidence, sources=reading.evidence(), methods=reading.method_evidence(),
        current_result=contract.result_adapter.validate_python(current_result).model_dump(mode='json'))
    if validate_relation(source_identity=deepcopy(source), condition_code=CODE, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Owner study recovery lacks native original-audit, debt, funding and resource authentication')
    return 'ready', resolution


def owner_original_study_profile(read_current, validate_relation, condition_code=CODE):
    if condition_code != CODE or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Owner study recovery requires guarded original/current sources and native validation')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_owner_study_conditions(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('OWN-A02', CODE, '1', frozenset({'dependency_change'}), evaluate)
