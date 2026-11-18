"""Original private A16 drafts precede A03; neither step manufactures research."""
from copy import deepcopy
from decimal import Decimal

from integration.contractor_tender_development import known, ref
from integration.owner_proposal_actions import OwnerProposalActionAssembler
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.owner_objects import OwnerObjectiveView
from src.actions.contracts.owner_proposal_objects import ProposalCaseView
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.organization.models import Authorization


def proposal_evidence_ref(source):
    return ref('Evidence', source['context'].operation_id + '-actual-proposal')


def prepare_proposal_sources(source, policy, request):
    """Initial candidates/rights are explicit assumptions, never executed facts.

    Review cash and management capacity retain the original current source and
    unpaid obligations. The review estimates create no spending or reservation.
    """
    if not policy.with_proposal or not policy.with_observation:
        raise TaskConflict('Original proposal requires its explicit observation and private assessment mandate')
    context = source['context']
    owner, now = policy.organization_id, context.business_time.model_dump(mode='json')
    rr = lambda kind, name: ref(kind, context.operation_id + '-proposal-' + name)
    get = lambda reference: next(r['value'] for r in source['objects'] if r['ref'] == reference)
    case = get(source['action_input']['case_ref'])
    objective = get(source['action_input']['objective_ref'])
    pool, = [r['value'] for r in source['objects'] if r['ref']['kind'] == 'ResourcePool']
    account, = [r['value'] for r in source['objects'] if r['ref']['kind'] == 'FundingSource']
    if pool['as_of'] != now or pool['coverage'] != 'complete' or account['as_of'] != now or account['coverage'] != 'complete':
        raise TaskConflict('Proposal needs the original complete current private cash and management sources')
    basis = objective['evidence_refs'][0]
    native = source['native_evidence_ref']
    window = objective['effective_window']
    objects = [deepcopy(r) for r in source['objects']
        if r['ref']['kind'] == 'Evidence' and r['ref'] != proposal_evidence_ref(source)]

    def add(identity, value):
        objects.append({'ref': identity, 'value': value})
        return identity

    def sourced(identity, **fields):
        return add(identity, {'ref': identity, 'evidence_refs': [basis], **fields})

    private_case = {k: deepcopy(v) for k, v in case.items() if k in ProposalCaseView.model_fields}
    private_case['prior_brief_refs'] = []
    private_case['evidence_refs'] = [r for r in private_case['evidence_refs'] if r != proposal_evidence_ref(source)]
    private_objective = {k: deepcopy(v) for k, v in objective.items() if k in OwnerObjectiveView.model_fields}
    # Reuse the exact actual global observation from the current A01 source.
    # It remains a global index, not a regional demand survey or forecast.
    demand = rr('DemandObservation', 'native-index')
    observation = rr('Observation', 'native-index')
    private_case['observation_refs'] = [demand]
    add(case['ref'], private_case)
    add(objective['ref'], private_objective)
    sourced(observation, demand_ref=demand, evidence_refs=[native])
    sourced(demand, source_ref=observation, region_id=request.inputs['opportunity']['region'],
        use_code=case['use_code'], signal_code='native_global_market_demand_index',
        measure=known({'value': str(request.inputs['macro_environment']['market_demand_index']), 'unit': 'index', 'basis_ref': native}),
        research_permitted=known(True), observed_at=now, learned_at=now, effective_window=window, evidence_refs=[native])
    # Keep all supplied existing unpaid obligations as unavailable review cash.
    # This is a private budgeting restriction, not a formal reservation/payment.
    protected = Decimal(0)
    for row in source['objects']:
        if row['ref']['kind'] != 'Obligation':
            continue
        debt = row['value']
        if debt['debtor_organization_id'] != owner:
            raise TaskConflict('Proposal cannot borrow another debtor obligation')
        due, paid = debt['actual_due'], debt['actual_paid']
        if due['state'] != 'known' or paid['state'] != 'known':
            raise TaskConflict('Proposal review budget requires original known outstanding obligations')
        if due['value']['currency'] != 'HKD' or paid['value']['currency'] != 'HKD':
            raise TaskConflict('Proposal review cannot convert original obligation currency')
        outstanding = Decimal(due['value']['value']) - Decimal(paid['value']['value'])
        if outstanding < 0:
            raise TaskConflict('Proposal review cannot clear or negate an original obligation')
        protected += outstanding
    funding = rr('FundingPosition', 'original-private-funds')
    sourced(funding, organization_id=owner, as_of=now, coverage='complete',
        actual_cash=deepcopy(account['actual_cash']), restricted_cash=deepcopy(account['restricted_cash']),
        committed_cash=known({'value': str(protected), 'currency': 'HKD', 'basis_ref': basis}),
        deduction_policy=known('disjoint_committed_and_restricted'))
    capacity = rr('ManagementCapacity', 'original-management')
    sourced(capacity, organization_id=owner, effective_window=deepcopy(pool['effective_window']),
        total=deepcopy(pool['total']), screening_requirement=known({'value': policy.proposal_review_effort,
            'unit': pool['total']['value']['unit'], 'basis_ref': basis}), commitments=[{
                'commitment_ref': r['ref'], 'window': deepcopy(r['window']), 'quantity': deepcopy(r['quantity'])}
                for r in pool['commitments']])
    function = context.function_ref.model_dump(mode='json')
    add(function, deepcopy(get(function)))
    briefs = [r['value'] for r in source['objects'] if r['ref']['kind'] == 'OwnerBrief']
    if not briefs or len(briefs) > 64:
        raise TaskConflict('Proposal needs a finite independent complete candidate set')
    purposes, technologies, candidates, bindings, inserted = [], [], [], [], set()
    for index, target in enumerate(briefs):
        draft = deepcopy(target['brief'])
        if (target['organization_id'] != owner or target['case_ref'] != case['ref']
                or target['objective_ref'] != objective['ref'] or draft['alternatives'] or draft['unresolved_refs']
                or draft['rights_refs'] or draft['scale']['lower']['state'] != 'known'
                or draft['scale']['upper']['state'] != 'known'):
            raise TaskConflict('Initial proposal supports only independently supplied unambiguous bounded candidates')
        purpose = draft['purpose_ref']
        if task_digest(purpose) not in inserted:
            sourced(purpose, organization_id=owner, template=objective['template'], use_code=case['use_code'],
                asset_kind=case['use_code'], effective_window=window)
            purposes.append(purpose)
            inserted.add(task_digest(purpose))
        scale = draft['scale']['basis_ref']
        if task_digest(scale) not in inserted:
            sourced(scale, purpose_ref=purpose, asset_kind=case['use_code'], interventions=['new_build', 'non_build'],
                algorithm_code='declared_inclusive_bounds_v1', applicability='range',
                minimum=deepcopy(draft['scale']['lower']), maximum=deepcopy(draft['scale']['upper']),
                applicability_rule_ref=None, effective_window=window)
            inserted.add(task_digest(scale))
        delivery = draft['delivery_window_ref']
        if task_digest(delivery) not in inserted:
            duration = request.inputs['opportunity']['planned_duration']
            if type(duration) is not int or duration <= 0:
                raise TaskConflict('Proposal delivery needs the exact positive native monthly planned duration')
            add(delivery, {'start': deepcopy(now), 'end': {**now, 'offset': now['offset'] + duration}, 'bounds': 'closed_open'})
            inserted.add(task_digest(delivery))
        rights = rr('RightsEvidence', 'assumed-initial-right-' + str(index))
        # Separate declared initial source; never infer rights from A01 follow,
        # a proposed brief, a native budget or macro project creation.
        sourced(rights, case_ref=case['ref'], purpose_ref=purpose, region_ids=list(draft['region_ids']),
            status='current_right', holder_organization_id=known(owner), research_permitted=known(True),
            available_at=now, effective_window=window)
        draft['rights_refs'] = [rights]
        candidate = rr('ProposalCandidate', str(index))
        sourced(candidate, local_key='current-proposal-' + str(index), organization_id=owner, case_ref=case['ref'],
            objective_ref=objective['ref'], brief=draft, prior_brief_ref=None, demand_refs=[demand], internal_need_refs=[],
            research_permitted=known(True), priority=known(index + 1),
            review_cost=known({'value': policy.proposal_review_cost, 'currency': 'HKD', 'basis_ref': basis}),
            review_effort=known({'value': policy.proposal_review_effort, 'unit': pool['total']['value']['unit'], 'basis_ref': basis}),
            available_at=now, effective_window=window)
        candidates.append(candidate)
        bindings.append({'candidate_ref': candidate, 'brief_ref': target['ref']})
    space = rr('ProposalSpace', 'finite-current-candidates')
    sourced(space, organization_id=owner, case_ref=case['ref'], objective_ref=objective['ref'], policy='evaluate',
        mode='propose', algorithm_code='declared_private_candidates_v1', maximum_briefs=known(len(candidates)),
        allowed_purpose_refs=purposes, allowed_region_ids=list(policy.allowed_regions),
        allowed_interventions=['new_build', 'non_build'], allowed_technology_refs=technologies,
        candidate_refs=candidates, capacity_ref=capacity, available_at=now, effective_window=window)
    grant = deepcopy(get(context.authorization_refs[0].model_dump(mode='json')))
    grant.update(ref=rr('Authorization', 'current-private-proposal'), action_ids=['OWN-A16'], readable_refs=[])
    add(grant['ref'], grant)
    operation = context.operation_id + '-proposal'
    candidate_set = rr('CandidateSet', 'current-proposal')
    add(candidate_set, {'operation_id': operation, 'scope': context.scope.model_dump(mode='json'), 'as_of': now,
        'candidates': [{'ref': r, 'permitted_choices': ['propose']} for r in purposes],
        'search_profile_ref': rr('Profile', 'explicit-private-drafts')})
    visible = [r['ref'] for r in objects]
    grant['readable_refs'] = deepcopy(visible)
    new_context = ActionContext.model_validate({**context.model_dump(mode='json'), 'operation_id': operation,
        'contract_ref': ref('ActionContract', 'OWN-A16'), 'task_ref': rr('DecisionTask', 'private-proposal'),
        'authorization_refs': [grant['ref']], 'read_token': operation + '-read',
        'visible_refs': visible, 'candidate_set_ref': candidate_set})
    schemas = OwnerProposalActionAssembler.SOURCE_SCHEMAS()
    objects = [{'ref': r['ref'], 'value': schemas.validate_projection(
        Reference.model_validate(r['ref']), r['value']).model_dump(mode='json')} for r in objects]
    return {'context': new_context, 'objects': objects, 'grants': [Authorization.model_validate(grant)],
        'action_input': {'case_ref': case['ref'], 'objective_ref': objective['ref'], 'demand_refs': [demand],
            'internal_need_refs': [], 'candidate_space_ref': space, 'funding_ref': funding},
        'brief_bindings': bindings, 'observed': {'native_context': deepcopy(source['observed']),
            'scope': deepcopy(source['observed']['scope']), 'cash_source_sha256': task_digest(account),
            'management_source_sha256': task_digest(pool), 'protected_old_obligations': str(protected),
            'brief_bindings': bindings, 'review_cost': policy.proposal_review_cost,
            'review_effort': policy.proposal_review_effort,
            'rights_source': 'explicit-synthetic-initial-owner-rights-not-created-by-private-proposal'}}


def proposal_origin(original, saved, snapshot, organizations):
    context, identity = original['context'], TaskIdentity(**saved['identity'])
    grants = organizations.grants(context, 'OWN-A16', 'Owner')
    permitted = {r.key() for g in grants for r in g.readable_refs} & {r.key() for r in context.visible_refs}
    if (identity.action_id != 'OWN-A16' or identity.run_id != context.run_id
            or not grants or any(g.organization_id != identity.organization_id for g in grants)
            or identity.organization_id != original['observed']['native_context']['scope']['owner_id']
            or snapshot['identity'] != saved['identity'] or identity.context_sha256 != task_digest(snapshot['context'])
            or identity.input_sha256 != task_digest(snapshot['action_input'])
            or snapshot['context'] != context.model_dump(mode='json') or snapshot['action_input'] != original['action_input']
            or saved['result_sha256'] != task_digest(saved['result'])
            or saved['source_reading_sha256'] != task_digest(saved['source_reading'])
            or any(Reference.model_validate(r['ref']).key() not in permitted for r in saved['source_reading'])
            or saved['result']['kind'] != 'completed' or saved['result']['payload']['choice'] not in {'propose', 'no_proposal'}
            or {task_digest(r['ref']): r['projection'] for r in saved['source_reading']}
                != {task_digest(r['ref']): r['value'] for r in original['objects']}):
        raise TaskConflict('Proposal handoff changed its exact original private invocation or current consumed sources')
    return saved['result']['payload']['choice'], {'source': 'actual_original_private_owner_proposal',
        'identity': identity.as_dict(), 'record_sha256': saved['record_sha256'],
        'result_sha256': saved['result_sha256'], 'source_reading_sha256': saved['source_reading_sha256'],
        'native_request_sha256': original['observed']['native_context']['native_request_sha256'],
        'brief_bindings': deepcopy(original['brief_bindings'])}


def attach_proposal(source, original, saved, snapshot, organizations):
    choice, bound = proposal_origin(original, saved, snapshot, organizations)
    if choice != 'propose' or bound['native_request_sha256'] != source['observed']['native_request_sha256']:
        raise TaskConflict('Investment needs its original same-request formed private proposal')
    actual = saved['result']['payload']['briefs']
    candidates = {task_digest(r['ref']): r['value'] for r in original['objects'] if r['ref']['kind'] == 'ProposalCandidate'}
    expected = [candidates[task_digest(r['candidate_ref'])]['brief'] for r in original['brief_bindings']]
    if len(actual) != len(expected) or {task_digest(r) for r in actual} != {task_digest(r) for r in expected}:
        raise TaskConflict('Partial proposal retains its formed drafts; investment awaits the complete declared comparison and baseline')
    result = deepcopy(source)
    evidence = proposal_evidence_ref(source)
    slot, = [r['value'] for r in result['objects'] if r['ref'] == evidence]
    if slot['content_hash'] is not None:
        raise TaskConflict('Private proposal evidence may bind only after the original action completes')
    slot['content_hash'] = task_digest(bound)
    for binding, draft in zip(original['brief_bindings'], expected, strict=True):
        target, = [r['value'] for r in result['objects'] if r['ref'] == binding['brief_ref']]
        target['brief'] = deepcopy(next(row for row in actual if row == draft))
        target['evidence_refs'] = [*target['evidence_refs'], evidence]
    result['observed']['proposal'] = bound
    native, = [r['value'] for r in result['objects'] if r['ref'] == result['native_evidence_ref']]
    native['content_hash'] = task_digest(result['observed'])
    return result
