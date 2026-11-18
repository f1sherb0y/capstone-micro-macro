"""Consume actual investment study requests as private bounded authorizations."""
from copy import deepcopy
from decimal import Decimal

from integration.contractor_tender_development import known, ref
from integration.owner_study_actions import OwnerStudyActionAssembler
from integration.owner_study_service_offer import prepare_study_service_offer
from src.actions.contracts.common import ActionContext, Reference
from src.actions.contracts.owner_study_objects import StudyCaseView
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.organization.models import Authorization


def declared_study_scope(objects, policy):
    """Select explicitly named interventions and their original comparison work."""
    comparison, = [r['value'] for r in objects if r['ref']['kind'] == 'OptionComparison']
    scope = deepcopy(comparison['scope'])
    if not policy.study_target_interventions:
        return [], scope, []
    sources = {task_digest(r['ref']): r['value'] for r in objects}
    selected = [reference for reference in comparison['option_refs']
                if sources[task_digest(reference)]['intervention'] in policy.study_target_interventions]
    if {sources[task_digest(r)]['intervention'] for r in selected} != set(policy.study_target_interventions):
        raise TaskConflict('Targeted study requires every explicitly declared intervention in the original comparison')
    links = []
    for reference in comparison['scope']['coverage_refs']:
        work = sources[task_digest(reference)]
        if work['option_ref'] not in selected:
            continue
        if work['case_ref'] != comparison['case_ref']:
            raise TaskConflict('Targeted study changes original comparison work ownership')
        links.append({'work_ref': deepcopy(reference), 'option_ref': deepcopy(work['option_ref']),
                      'source_sha256': task_digest(work)})
    if {task_digest(r['option_ref']) for r in links} != {task_digest(r) for r in selected}:
        raise TaskConflict('Targeted study lacks original bounded work for a selected option')
    scope['coverage_refs'] = [r['work_ref'] for r in links]
    return selected, scope, links


def declare_study_followup(objects, policy, now):
    """Declare an unresolved initial question, never invent a research result."""
    if policy.study_question_code is None:
        return []
    get = lambda kind: next(r['value'] for r in objects if r['ref']['kind'] == kind)
    case, comparison, profile = (get(k) for k in ('OwnerCase', 'OptionComparison', 'ProjectRegistrationProfile'))
    targets, scope, _ = declared_study_scope(objects, policy)
    issue = ref('Issue', case['ref']['id'] + '-declared-study-question')
    objects.append({'ref': issue, 'value': {'ref': issue, 'evidence_refs': deepcopy(profile['evidence_refs']),
        'case_ref': case['ref'], 'comparison_ref': comparison['ref'], 'option_refs': deepcopy(targets),
        'scope': scope, 'remedy': 'study_more', 'status': 'unresolved',
        'available_at': deepcopy(now), 'effective_window': deepcopy(profile['effective_window'])}})
    case['issue_refs'] = [*case['issue_refs'], issue]
    comparison['issue_refs'] = [*comparison['issue_refs'], issue]
    if profile['policy'] == known('evaluate'):
        profile.update(policy=known('study_more'), followup_issue_refs=[issue], followup_option_refs=deepcopy(targets))
    return targets


def _original(source, saved, snapshot, action, organizations):
    context = source['context']
    identity = TaskIdentity(**saved['identity'])
    grants = organizations.grants(context, action, 'Owner')
    allowed = {r.key() for g in grants for r in g.readable_refs}
    allowed &= {r.key() for r in context.visible_refs}
    if (identity.action_id != action or identity.run_id != context.run_id
            or not grants or any(g.organization_id != identity.organization_id for g in grants)
            or snapshot['identity'] != saved['identity'] or snapshot['context'] != context.model_dump(mode='json')
            or snapshot['action_input'] != source['action_input'] or identity.context_sha256 != task_digest(snapshot['context'])
            or identity.input_sha256 != task_digest(snapshot['action_input'])
            or saved['result_sha256'] != task_digest(saved['result'])
            or saved['source_reading_sha256'] != task_digest(saved['source_reading'])
            or any(Reference.model_validate(r['ref']).key() not in allowed for r in saved['source_reading'])
            or {task_digest(r['ref']): r['projection'] for r in saved['source_reading']}
                != {task_digest(r['ref']): r['value'] for r in source['objects']}
            or saved['result']['kind'] != 'completed'):
        raise TaskConflict('Study chain changes its original invocation, current authority or exact consumed sources')
    return {'identity': identity.as_dict(), 'record_sha256': saved['record_sha256'],
        'result_sha256': saved['result_sha256'], 'source_reading_sha256': saved['source_reading_sha256']}


def prepare_study_sources(source, policy, request, saved, snapshot, organizations):
    origin = _original(source, saved, snapshot, 'OWN-A03', organizations)
    payload = saved['result']['payload']
    if policy.study_question_code is None or payload['choice'] != 'study_more':
        raise TaskConflict('Bounded study requires its actual original research followup')
    context, owner = source['context'], policy.organization_id
    now = context.business_time.model_dump(mode='json')
    rr = lambda kind, name: ref(kind, context.operation_id + '-study-' + name)
    get = lambda reference: next(r['value'] for r in source['objects'] if r['ref'] == reference)
    case = get(source['action_input']['case_ref'])
    comparison = get(source['action_input']['comparison_ref'])
    profile = get(source['action_input']['registration_profile_ref'])
    expected = ref('Issue', case['ref']['id'] + '-declared-study-question')
    targets, original_scope, work_links = declared_study_scope(source['objects'], policy)
    if (payload['issue_refs'] != [expected] or get(expected)['status'] != 'unresolved'
            or payload['target_option_refs'] != targets or get(expected)['option_refs'] != targets
            or get(expected)['scope'] != original_scope):
        raise TaskConflict('Study followup changes its independently declared unresolved question')
    window = profile['effective_window']
    basis = profile['evidence_refs'][0]
    evidence = rr('Evidence', 'actual-investment-followup')
    work, issue = rr('WorkScope', 'bounded-question'), rr('Issue', 'bounded-question')
    work_refs = deepcopy(original_scope['coverage_refs']) if targets else [work]
    scope = {'kind': 'assessment_case', 'ref': case['ref'], 'coverage_refs': work_refs}
    observed = {'native_context': deepcopy(source['observed']), 'investment_origin': origin,
        'original_issue_refs': deepcopy(payload['issue_refs']), 'study_issue_refs': [issue],
        'question_code': policy.study_question_code, 'boundary': 'private authorization only; question remains unresolved'}
    if targets:
        observed.update(target_option_refs=deepcopy(targets), original_investment_scope=original_scope,
                        study_scope=deepcopy(scope), work_option_links=work_links)
    objects = [deepcopy(r) for r in source['objects'] if r['ref']['kind'] == 'Evidence']

    def add(identity, **values):
        objects.append({'ref': identity, 'value': {'ref': identity, 'evidence_refs': [basis, evidence], **values}})

    objects.append({'ref': evidence, 'value': {'ref': evidence, 'source_kind': 'synthetic', 'basis_kind': 'observed',
        'locator': 'actual-original-OWN-A03-study-more-not-a-research-report',
        'content_hash': task_digest(observed), 'effective_window': None}})
    private_case = {k: deepcopy(v) for k, v in case.items() if k in StudyCaseView.model_fields}
    private_case.update(issue_refs=[issue], study_refs=[], linked_project_ref=None)
    private_case['evidence_refs'] = [*private_case['evidence_refs'], evidence]
    objects.append({'ref': case['ref'], 'value': private_case})
    for work_ref in work_refs:
        add(work_ref, case_ref=case['ref'], research_permitted=known(True),
            question_codes=[policy.study_question_code],
            effective_window=deepcopy(get(work_ref)['effective_window']) if targets else window)
    add(issue, case_ref=case['ref'], scope=scope, question_code=policy.study_question_code, status='unresolved',
        available_at=now, effective_window=window)
    account, = [r['value'] for r in source['objects'] if r['ref']['kind'] == 'FundingSource']
    pool, = [r['value'] for r in source['objects'] if r['ref']['kind'] == 'ResourcePool']
    if any(v['organization_id'] != owner or v['as_of'] != now or v['coverage'] != 'complete' for v in (account, pool)):
        raise TaskConflict('Study needs the same original complete current owner cash and management load')
    protected = Decimal(0)
    for row in source['objects']:
        if row['ref']['kind'] != 'Obligation':
            continue
        debt = row['value']
        due, paid = debt['actual_due'], debt['actual_paid']
        if (debt['debtor_organization_id'] != owner or due['state'] != 'known' or paid['state'] != 'known'
                or due['value']['currency'] != 'HKD' or paid['value']['currency'] != 'HKD'):
            raise TaskConflict('Study cannot substitute or omit original outstanding obligations')
        outstanding = Decimal(due['value']['value']) - Decimal(paid['value']['value'])
        if outstanding < 0:
            raise TaskConflict('Study cannot clear an original obligation')
        protected += outstanding
    funding, grant_ref = rr('FundingPosition', 'original-funds'), rr('Authorization', 'private-study')
    money = lambda value: {'value': value, 'currency': 'HKD', 'basis_ref': basis}
    quantity = {'value': policy.study_resource_requirement, 'unit': pool['total']['value']['unit'], 'basis_ref': basis}
    add(funding, organization_id=owner, actual_cash=deepcopy(account['actual_cash']),
        restricted_cash=deepcopy(account['restricted_cash']), committed_cash=known(money(str(protected))),
        deduction_policy=known('disjoint_committed_and_restricted'), as_of=now, coverage='complete')
    add(pool['ref'], organization_id=owner, authorization_ref=grant_ref,
        function_ref=context.function_ref.model_dump(mode='json'), supported_question_codes=known([policy.study_question_code]),
        qualified=known(policy.study_qualified), research_permitted=known(True), total=deepcopy(pool['total']),
        commitments=deepcopy(pool['commitments']), as_of=now, coverage='complete', effective_window=deepcopy(pool['effective_window']))
    function = context.function_ref.model_dump(mode='json')
    objects.append({'ref': function, 'value': deepcopy(get(function))})
    planning, candidate, study_profile = rr('TimeWindow', 'planned'), rr('StudyCandidate', 'internal'), rr('StudyProfile', 'current')
    objects.append({'ref': planning, 'value': {'start': now, 'end': {**now, 'offset': now['offset'] + policy.study_duration}, 'bounds': 'closed_open'}})
    local_key = context.operation_id + '-bounded-study'
    add(candidate, local_key=local_key, organization_id=owner, case_ref=case['ref'], choice='internal_study',
        task_scope={'scope_ref': scope, 'basis_refs': [evidence], 'condition_refs': []}, issue_refs=[issue],
        expenditure_cap=known(money(policy.study_budget)), future_cost=known(money(policy.study_estimated_cost)),
        window_ref=planning, allocations=[{'resource_ref': pool['ref'], 'window_ref': planning, 'quantity': quantity,
            'task_target': {'kind': 'proposed', 'local_key': local_key, 'scope_ref': scope}}], offer_ref=None,
        prior_study_ref=None, reassessment_refs=[], priority=known(1), research_permitted=known(True),
        available_at=now, effective_window=window)
    add(study_profile, organization_id=owner, case_ref=case['ref'], permitted_scope=scope, authority_ref=grant_ref,
        funding_ref=funding, algorithm_code='declared_limited_study_v1', policy=known('evaluate'),
        on_unavailable=known('stop'), candidate_refs=[candidate], history_refs=[], history_coverage='complete',
        as_of=now, available_at=now, effective_window=window)
    grant = deepcopy(get(context.authorization_refs[0].model_dump(mode='json')))
    grant.update(ref=grant_ref, action_ids=['OWN-A02'], scopes=[scope], readable_refs=[])
    objects.append({'ref': grant_ref, 'value': grant})
    operation, candidates = context.operation_id + '-study', rr('CandidateSet', 'internal')
    objects.append({'ref': candidates, 'value': {'operation_id': operation, 'scope': scope, 'as_of': now,
        'candidates': [], 'search_profile_ref': rr('Profile', 'bounded-research')}})
    offers, offer_grants, declaration = prepare_study_service_offer(source, policy, objects,
        scope=scope, issue=issue, planning=planning, candidate=candidate, now=now, window=window)
    if declaration is not None:
        next(r['value'] for r in objects if r['ref'] == candidates)['candidates'] = [
            {'ref': offer, 'permitted_choices': ['commission']} for offer in offers]
        observed['service_offer_declaration'] = declaration
        # Seal the complete observed lineage before its evidence is consumed.
        next(r['value'] for r in objects if r['ref'] == evidence)['content_hash'] = task_digest(observed)
    visible = [r['ref'] for r in objects]
    grant['readable_refs'] = deepcopy(visible)
    current = ActionContext.model_validate({**context.model_dump(mode='json'), 'operation_id': operation,
        'contract_ref': ref('ActionContract', 'OWN-A02'), 'task_ref': rr('DecisionTask', 'authorization'),
        'authorization_refs': [grant_ref], 'scope': scope, 'read_token': operation + '-read',
        'visible_refs': visible, 'candidate_set_ref': candidates})
    schemas = OwnerStudyActionAssembler.SOURCE_SCHEMAS()
    objects = [{'ref': r['ref'], 'value': schemas.validate_projection(Reference.model_validate(r['ref']), r['value']).model_dump(mode='json')} for r in objects]
    return {'context': current, 'objects': objects, 'grants': [Authorization.model_validate(g) for g in [grant, *offer_grants]],
        'action_input': {'case_ref': case['ref'], 'brief_ref': None, 'issue_refs': [issue], 'service_candidates': offers,
            'study_profile_ref': study_profile, 'spending_limit': money(policy.study_budget)},
        'observed': observed}


def study_origin(source, saved, snapshot, organizations):
    bound = _original(source, saved, snapshot, 'OWN-A02', organizations)
    choice = saved['result']['payload']['choice']
    if choice not in {'internal_study', 'commission', 'stop'}:
        raise TaskConflict('Unresolved study authorization cannot become a native business outcome')
    return {**bound, 'choice': choice, 'investment_origin': deepcopy(source['observed']['investment_origin']),
        **({'service_offer_declaration': deepcopy(source['observed']['service_offer_declaration'])}
           if 'service_offer_declaration' in source['observed'] else {}),
        'original_issue_refs': deepcopy(source['observed']['original_issue_refs']),
        **({'target_option_refs':deepcopy(source['observed']['target_option_refs']),
            'study_scope':deepcopy(source['observed']['study_scope'])} if 'target_option_refs' in source['observed'] else {})}


def prior_study_authorization(record, investment, worker, snapshots, *, organizations, tick, service_workers=None):
    """Authenticate past private intention; never turn it into executed research."""
    from integration.bank_financing_private import checked_result
    technical = record.get('study')
    if worker is None or not technical or 'result_sha256' not in technical:
        raise TaskConflict('Prior study followup lost its original bounded authorization')
    identity = TaskIdentity(**technical['identity'])
    saved = checked_result(worker, identity)
    snapshot = snapshots.get(identity)
    from integration.owner_opportunity_native_feedback import authorize_owner_history
    authorize_owner_history(saved, snapshot, organizations=organizations, tick=tick)
    observed = technical['observed']
    origin = observed['investment_origin']
    actual = {k: investment[k] for k in ('identity', 'record_sha256', 'result_sha256', 'source_reading_sha256')}
    evidence = [r['projection'] for r in saved['source_reading']
        if r['ref']['kind'] == 'Evidence' and r['ref']['id'].endswith('-study-actual-investment-followup')]
    choice = saved['result']['payload']['choice']
    if (identity.request_id != record['key'] + ':OWN-A02' or identity.action_id != 'OWN-A02'
            or identity.organization_id != record['scope']['owner_id'] or identity.run_id != investment['identity']['run_id']
            or saved['result_sha256'] != technical['result_sha256'] or snapshot['identity'] != saved['identity']
            or origin != actual or observed['native_context'] != record['observed']
            or observed['original_issue_refs'] != investment['result']['payload']['issue_refs']
            or choice not in {'internal_study', 'commission', 'stop'} or len(evidence) != 1
            or evidence[0]['content_hash'] != task_digest(observed)):
        raise TaskConflict('Prior study followup substitutes its original private authorization or unresolved question')
    targeted = {}
    targets = investment['result']['payload']['target_option_refs']
    if targets:
        originals = {task_digest(r['ref']): r['projection'] for r in investment['source_reading']}
        original_issue, = [originals[task_digest(r)] for r in investment['result']['payload']['issue_refs']]
        original_scope = original_issue['scope']
        links = [{'work_ref': deepcopy(r), 'option_ref': deepcopy(originals[task_digest(r)]['option_ref']),
                  'source_sha256': task_digest(originals[task_digest(r)])} for r in original_scope['coverage_refs']]
        if (original_issue['option_refs'] != targets or observed.get('target_option_refs') != targets
                or observed.get('original_investment_scope') != original_scope
                or observed.get('work_option_links') != links or observed.get('study_scope') != original_scope
                or snapshot['context']['scope'] != original_scope
                or {task_digest(r['option_ref']) for r in links} != {task_digest(r) for r in targets}
                or choice in {'internal_study', 'commission'} and saved['result']['payload']['task_scope']['scope_ref'] != original_scope):
            raise TaskConflict('Prior targeted study changes its original options or bounded work')
        targeted = {'target_option_refs': deepcopy(targets), 'study_scope': deepcopy(original_scope)}
    elif observed.get('target_option_refs'):
        raise TaskConflict('Prior whole-comparison study imports undeclared targeted options')
    offer_history = {}
    declaration = observed.get('service_offer_declaration')
    actual_intake = declaration is not None and declaration['source_declaration'] == 'original_professional_intake_result'
    if choice == 'commission' or actual_intake:
        projections = {task_digest(r['ref']): r['projection'] for r in saved['source_reading']}
        offer_ref = saved['result']['payload']['offer_ref'] if choice == 'commission' else declaration['offer_ref']
        offer = projections.get(task_digest(offer_ref))
        locator = ('independent-initial-study-professional-disclosures-not-action-execution' if actual_intake else
            'independent-initial-standing-research-offer-not-a-professional-action-receipt')
        basis = [r for r in projections.values() if r.get('locator') == locator]
        if (not declaration or declaration['source_declaration'] not in {'independent_initial_standing_offer','original_professional_intake_result'}
                or declaration['offer_ref'] != offer_ref or not offer or len(basis) != 1
                or basis[0]['basis_kind'] != 'assumed' or basis[0]['content_hash'] != declaration['declaration_sha256']
                or offer['provider_organization_id'] != declaration['provider_organization_id']
                or offer['authority_ref'] != declaration['authority_ref']
                or offer['scope'] != snapshot['context']['scope']
                or choice == 'commission' and saved['result']['payload']['task_scope']['scope_ref'] != offer['scope']):
            raise TaskConflict('Prior commission substitutes its exact independently declared standing offer')
        if actual_intake:
            from integration.owner_study_professional_intake import original_intake_result
            professional, origin = original_intake_result(record,None,service_workers or {},snapshots,organizations,tick=tick)
            originals = {task_digest(r['ref']): r['projection'] for r in professional['source_reading']}
            original_terms = originals.get(task_digest(declaration['original_terms_ref']))
            execution_evidence = projections.get(task_digest(declaration['actual_producer_evidence_ref']))
            if (origin != declaration['provider_origin'] or not original_terms or not execution_evidence
                    or execution_evidence['basis_kind'] != 'observed' or execution_evidence['content_hash'] != task_digest(declaration)
                    or original_terms['fee'] != offer['fee'] or original_terms['scope'] != offer['scope']
                    or original_terms['provider_id'] != offer['author_actor_id']
                    or origin['identity']['organization_id'] != offer['provider_organization_id']
                    or declaration['accepted'] != (professional['result']['payload']['choice'] == 'accept')
                    or (offer['status'] == 'offered') != declaration['accepted']):
                raise TaskConflict('Prior research offer changes its actual original professional decision or scoped handoff')
        offer_history = {'service_offer_declaration': deepcopy(declaration), 'offer_ref': deepcopy(offer_ref)}
    return {'identity': identity.as_dict(), 'result_sha256': saved['result_sha256'],
        'record_sha256': saved['record_sha256'], 'choice': choice,
        **targeted, **offer_history,
        'boundary': 'private authorization intention; no research execution, report, fee or reservation'}
