"""Recover financing waits while preserving original borrowers and actual debts."""
from copy import deepcopy
from dataclasses import dataclass

from src.actions.contracts.common import EvidenceRecord
from src.actions.contracts.owner_financing_objects import (
    FinancingProfileView, FinancingSourceView, FinancingAccountView, FinancingDebtView, FinancingObligationView,
)
from src.actions.roles.owner_financing import plan_financing
from src.coordination.continuations import ConditionProfile
from src.coordination.owner_closeout_conditions import same_closeout_scope
from src.coordination.owner_saved_wait_conditions import OwnerSavedWaitConditionReading, read_owner_saved_wait
from src.coordination.tasks import TaskConflict
from src.methods.pricing import decimal_fraction


CODE = 'owner.financing.inputs_changed'


@dataclass(frozen=True)
class OwnerFinancingConditionReading(OwnerSavedWaitConditionReading):
    """Actual original A05 wait and a new authorized funding judgment."""


def check_owner_financing_conditions(check, selected, validate_relation):
    old_input, current_input, saved = read_owner_saved_wait(check, selected, validate_relation,
        action_id='OWN-A05', code=CODE, kinds=('FundingProfile',), reading_type=OwnerFinancingConditionReading)
    source = check.source['identity']
    context, original, reading = selected.context, selected.original_context, selected.reading
    old_sources = {tuple(row['ref'][key] for key in ('kind', 'id', 'version')) for row in saved['source_reading']}
    if (old_input.funding_profile_ref != check.condition.object_refs[0]
            or current_input.funding_profile_ref != selected.history_ref
            or old_input.funding_profile_ref.key()[:2] != current_input.funding_profile_ref.key()[:2]
            or old_input.borrower_id != current_input.borrower_id
            or not same_closeout_scope(old_input.scope_ref, current_input.scope_ref)):
        raise TaskConflict('Owner financing recovery substitutes its original funding profile, borrower or bounded scope')
    borrower = old_input.borrower_id

    def physical(refs):
        rows = {ref.key()[:2]: ref for ref in refs}
        if len(rows) != len(refs):
            raise TaskConflict('Owner financing recovery aliases physical debts, obligations or funding sources')
        return rows

    def read(ref, schema, at):
        row = reading.resolve(ref)
        if not isinstance(row, schema) or row.ref != ref:
            raise TaskConflict('Owner financing recovery requires exact typed source versions')
        point = getattr(row, 'available_at', None)
        if point is not None and (point.clock_ref != at.clock_ref or point.offset > at.offset):
            raise TaskConflict('Owner financing recovery imports information unavailable at its read time')
        return row

    if not set(physical(old_input.offers)) <= set(physical(current_input.offers)):
        raise TaskConflict('Owner financing recovery drops original received offers instead of retaining their versions')
    versions = []
    for values, invocation in ((old_input, original), (current_input, context)):
        at = invocation.business_time
        profile = read(values.funding_profile_ref, FinancingProfileView, at)
        if (profile.organization_id != source['organization_id'] or profile.borrower_id != borrower
                or profile.scope_ref != values.scope_ref or profile.as_of != at
                or set(values.debt_refs) != set(profile.debt_refs) or values.funding_lines != profile.funding_lines):
            raise TaskConflict('Owner financing recovery changes its own profile or complete declared debt/funding input')
        inventories = {}
        for name, refs, schema, owner_field in (
                ('funding', profile.source_refs, FinancingSourceView, 'organization_id'),
                ('debts', profile.debt_refs, FinancingDebtView, 'borrower_id'),
                ('obligations', profile.obligation_refs, FinancingObligationView, 'debtor_id')):
            rows = {}
            for key, ref in physical(refs).items():
                row = None if values is old_input and ref.key() not in old_sources else read(ref, schema, at)
                if row is not None and (getattr(row, owner_field) != borrower or row.as_of != at):
                    raise TaskConflict('Owner financing recovery changes the legal borrower/debtor or actual read time')
                rows[key] = row
            inventories[name] = rows
        accounts = {}
        for funding in inventories['funding'].values():
            if funding is None or values is old_input and funding.account_ref.key() not in old_sources:
                continue
            account = read(funding.account_ref, FinancingAccountView, at)
            if (account.organization_id != borrower or account.source_ref != funding.ref
                    or account.as_of != at or account.ref.key()[:2] in accounts):
                raise TaskConflict('Owner financing recovery changes or repeats the original borrower account')
            accounts[account.ref.key()[:2]] = account
        versions.append(dict(profile=profile, accounts=accounts, **inventories))
    old, current = versions
    if (old['profile'].purpose_ref.key()[:2] != current['profile'].purpose_ref.key()[:2]
            or old['profile'].currency != current['profile'].currency
            or old['profile'].borrower_ref.key()[:2] != current['profile'].borrower_ref.key()[:2]):
        raise TaskConflict('Owner financing recovery changes the original borrower, funding purpose or currency')
    if current['profile'].coverage != 'complete':
        return 'waiting', None
    for name in ('funding', 'debts', 'obligations', 'accounts'):
        if not set(old[name]) <= set(current[name]):
            raise TaskConflict('Owner financing recovery omits original sources, accounts, debts or obligations')
    # Current account inventories must still expose the full native portfolio,
    # including liabilities outside this one case/project and already paid rows.
    account_debts, account_obligations = [], []
    for funding in current['funding'].values():
        if funding.coverage != 'complete':
            return 'waiting', None
        account = current['accounts'][funding.account_ref.key()[:2]]
        if (account.coverage != 'complete' or account.actual_cash != funding.actual_cash
                or account.restricted_cash != funding.restricted_cash or account.currency != current['profile'].currency):
            raise TaskConflict('Owner financing recovery changes actual account cash or complete source coverage')
        account_debts.extend(account.debt_refs)
        account_obligations.extend(account.obligation_refs)
    physical(account_debts)
    physical(account_obligations)
    if (set(account_debts) != set(current['profile'].debt_refs)
            or set(account_obligations) != set(current['profile'].obligation_refs)):
        raise TaskConflict('Owner financing recovery hides or duplicates liabilities in the account portfolio')
    for debt in current['debts'].values():
        if debt.coverage != 'complete':
            return 'waiting', None
        if (debt.arrangement_ref not in current['profile'].arrangement_refs
                or not set(debt.obligation_refs) <= set(current['profile'].obligation_refs)):
            raise TaskConflict('Owner financing recovery loses the original arrangement or debt obligations')
    for obligation in current['obligations'].values():
        if obligation.source_ref not in current['profile'].source_refs:
            raise TaskConflict('Owner financing recovery moves an obligation outside its actual funding source')
        if obligation.debt_ref is not None:
            debt = current['debts'].get(obligation.debt_ref.key()[:2])
            if (debt is None or debt.ref != obligation.debt_ref or obligation.ref not in debt.obligation_refs
                    or obligation.origin_scope != debt.origin_scope or obligation.payee_id != debt.lender_id):
                raise TaskConflict('Owner financing recovery changes a debt obligation origin, lender or version')

    def retain_money(before, after):
        if before.state != 'known':
            return True
        if after.state != 'known':
            return False
        if (before.value.currency != after.value.currency
                or decimal_fraction(after.value.value) < decimal_fraction(before.value.value)):
            raise TaskConflict('Owner financing recovery clears already owed or paid amounts')
        return True

    debts, obligations = [], []
    for key, before in old['debts'].items():
        after = current['debts'][key]
        if before is not None:
            if (before.borrower_id != after.borrower_id or before.lender_id != after.lender_id
                    or before.arrangement_ref.key()[:2] != after.arrangement_ref.key()[:2]
                    or not same_closeout_scope(before.origin_scope, after.origin_scope)
                    or not set(physical(before.obligation_refs)) <= set(physical(after.obligation_refs))):
                raise TaskConflict('Owner financing recovery transfers or clears an original borrower/lender debt')
            if before.outstanding_principal.state == 'known' and after.outstanding_principal.state != 'known':
                return 'waiting', None
        if after.coverage != 'complete':
            return 'waiting', None
        if not set(physical(after.obligation_refs)) <= set(current['obligations']):
            raise TaskConflict('Owner financing recovery hides debt obligations from the complete portfolio')
        # A changed principal requires independent native ledger authentication.
        # No reduction is inferred from an owner choice, offer, or payment label.
        debts.append({'original': None if before is None else before.model_dump(mode='json'),
            'current': after.model_dump(mode='json')})
    for key, before in old['obligations'].items():
        after = current['obligations'][key]
        if before is not None:
            if (before.debtor_id != after.debtor_id or before.payee_id != after.payee_id
                    or before.source_ref.key()[:2] != after.source_ref.key()[:2]
                    or not same_closeout_scope(before.origin_scope, after.origin_scope)
                    or (None if before.debt_ref is None else before.debt_ref.key()[:2])
                        != (None if after.debt_ref is None else after.debt_ref.key()[:2])
                    or not set(physical(before.component_refs)) <= set(physical(after.component_refs))):
                raise TaskConflict('Owner financing recovery changes an original debt/obligation beneficiary, origin or components')
            if not all(retain_money(getattr(before, name), getattr(after, name)) for name in ('actual_due', 'actual_paid')):
                return 'waiting', None
        obligations.append({'original': None if before is None else before.model_dump(mode='json'),
            'current': after.model_dump(mode='json')})
    result = plan_financing(context, current_input, reading)
    if result.get('kind') != 'completed':
        return 'waiting', None
    selected.contract.validate_decision(current_input, result['payload'])
    evidence = []
    for rows, fields in ((current['funding'].values(), ('actual_cash', 'restricted_cash')),
            (current['debts'].values(), ('outstanding_principal',)),
            (current['obligations'].values(), ('actual_due', 'actual_paid'))):
        for row in rows:
            for name in fields:
                value = getattr(row, name)
                if value.state != 'known':
                    continue
                record = read(value.value.basis_ref, EvidenceRecord, context.business_time)
                if (record.source_kind == 'synthetic' or record.basis_kind != 'observed'
                        or record.effective_window is not None and not record.effective_window.contains(context.business_time)):
                    raise TaskConflict('Formal financing recovery requires observed actual cash, principal and liabilities')
                evidence.append(record.model_dump(mode='json'))
    resolution = dict(schema_version='owner-financing-conditions-resolution.v1', condition_code=CODE,
        original_context=original.model_dump(mode='json'), context=context.model_dump(mode='json'),
        original_action_input=deepcopy(selected.original_action_input), action_input=deepcopy(selected.action_input),
        original_record=saved, retained_debts=debts, retained_obligations=obligations,
        original_profile=old['profile'].model_dump(mode='json'), profile=current['profile'].model_dump(mode='json'),
        actual_evidence=evidence, sources=reading.evidence(), methods=reading.method_evidence(),
        current_result=selected.contract.result_adapter.validate_python(result).model_dump(mode='json'))
    if validate_relation(source_identity=deepcopy(source), condition_code=CODE, resolution=deepcopy(resolution),
            context=context.model_copy(deep=True), reading=reading) is not True:
        raise TaskConflict('Owner financing recovery lacks native original-audit, principal/payment history and funding authentication')
    return 'ready', resolution


def owner_original_financing_profile(read_current, validate_relation, condition_code=CODE):
    if condition_code != CODE or not callable(read_current) or not callable(validate_relation):
        raise ValueError('Owner financing recovery requires guarded original/current sources and native validation')

    def evaluate(check):
        selected = read_current(deepcopy(check))
        try:
            return check_owner_financing_conditions(check, selected, validate_relation)[0]
        finally:
            selected.reading.recheck()

    return ConditionProfile('OWN-A05', CODE, '1', frozenset({'dependency_change'}), evaluate)
