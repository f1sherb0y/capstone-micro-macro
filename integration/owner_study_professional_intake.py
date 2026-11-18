"""Run original professional A02 before publishing a bounded research offer.

Initial professional disclosures remain assumptions. The professional decision
and its recipient-scoped handoff are actual micro results, not appointments.
"""
from copy import deepcopy
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from integration.architect_intake_actions import ArchitectIntakeActionAssembler
from integration.architect_intake_results import ArchitectIntakeResultWorker
from integration.qs_intake_actions import QSIntakeActionAssembler
from integration.qs_intake_results import QSIntakeResultWorker
from integration.bank_financing_private import checked_result
from integration.contractor_tender_development import known, ref
from integration.owner_study_service_offer import OwnerStudyServiceOfferPolicy
from integration.owner_study_actions import OwnerStudyActionAssembler
from src.actions.contracts.common import ActionContext, DecimalString, Reference, StrictRecord, TextId, ValueState
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest
from src.organization.models import Authorization


COMPONENTS = {'QS': (QSIntakeActionAssembler, QSIntakeResultWorker, 'terms_ref'),
              'Architect': (ArchitectIntakeActionAssembler, ArchitectIntakeResultWorker, 'accepted_terms_ref')}


class StudyResourceCommitment(StrictRecord):
    commitment_id: TextId
    region_id: TextId
    start_tick: int = Field(ge=0, strict=True)
    end_tick: int = Field(ge=1, strict=True)
    capacity: DecimalString

    @model_validator(mode='after')
    def bounded_load(self):
        if self.end_tick <= self.start_tick or not Decimal(self.capacity).is_finite() or Decimal(self.capacity) <= 0:
            raise ValueError('Initial study commitment requires a positive finite load and a nonempty window')
        return self


class OwnerStudyProfessionalIntakePolicy(OwnerStudyServiceOfferPolicy):
    source_declaration: Literal['independent_initial_professional_service_inputs']
    minimum_fee_amount: ValueState[DecimalString]
    payment_risk: ValueState[DecimalString]
    maximum_payment_risk: ValueState[DecimalString]
    new_work_policy: ValueState[Literal['evaluate', 'decline', 'defer']]
    capacity_by_region: dict[str, ValueState[DecimalString]] = Field(min_length=1)
    resource_commitments: list[StudyResourceCommitment]
    effort_amount: ValueState[DecimalString]
    effort_per_capacity_tick: DecimalString
    object_types: list[TextId] = Field(min_length=1)
    service_code: TextId
    responsibility_code: TextId
    qualification_code: TextId
    available_until_tick: int = Field(ge=1, strict=True)
    conflict_status: Literal['clear', 'conflict', 'unknown', 'failed'] | None = None
    conflict_codes: list[TextId] = Field(default_factory=list)

    @model_validator(mode='after')
    def independent_capacity_and_pricing(self):
        rate = Decimal(self.effort_per_capacity_tick)
        if not rate.is_finite() or rate <= 0:
            raise ValueError('Study work conversion requires a finite positive independent rate')
        values = [self.minimum_fee_amount, self.payment_risk, self.maximum_payment_risk,
                  self.effort_amount, *self.capacity_by_region.values()]
        if any(v.state == 'known' and (not Decimal(v.value).is_finite() or Decimal(v.value) < 0) for v in values):
            raise ValueError('Study pricing, effort and physical capacities must be finite and nonnegative')
        if self.effort_amount.state == 'known' and Decimal(self.effort_amount.value) == 0:
            raise ValueError('Study service effort must be positive')
        if (len(set(self.object_types)) != len(self.object_types)
                or len({c.commitment_id for c in self.resource_commitments}) != len(self.resource_commitments)
                or any(c.region_id not in self.capacity_by_region for c in self.resource_commitments)):
            raise ValueError('Study disclosures repeat domains/loads or omit a committed physical resource')
        if (len(set(self.conflict_codes)) != len(self.conflict_codes)
                or self.conflict_status == 'conflict' and not self.conflict_codes
                or self.conflict_status == 'clear' and self.conflict_codes):
            raise ValueError('Study conflict findings require distinct explicit categories consistent with their status')
        return self


def validate_study_intake_policy(policy):
    declaration = policy.study_professional_intake
    if declaration is not None and (policy.study_question_code is None or policy.study_service_offer is not None
            or declaration.provider_organization_id not in (policy.cost_organization_id, policy.schedule_organization_id)
            or not policy.allow_scoped_template_authorizations
            or declaration.provider_organization_id == policy.cost_organization_id and declaration.conflict_status is None):
        raise ValueError('Professional study intake requires its exact question, independent original provider mandate and QS conflict disclosure; standing offers are exclusive')


def prepare_intake_sources(app, study, policy, request, scope):
    """Expose the exact question and independent provider inputs, never owner cash."""
    declaration = policy.study_professional_intake
    validate_study_intake_policy(policy)
    provider = declaration.provider_organization_id
    role = 'QS' if provider == policy.cost_organization_id else 'Architect'
    organization = app.organizations.get(provider)
    assignment = organization.assignments[0].model_dump(mode='json')
    now = study['context'].business_time.model_dump(mode='json')
    clock = now['clock_ref']
    point = lambda tick: {'clock_ref': deepcopy(clock), 'offset': tick}
    window = lambda start, end: {'start': point(start), 'end': point(end), 'bounds': 'closed_open'}
    validity = window(0, declaration.available_until_tick)
    exact_scope = study['context'].scope.model_dump(mode='json')
    tag = study['context'].operation_id + '-professional'
    rr = lambda kind, name: ref(kind, tag + '-' + name)
    basis, actual, grant_ref = rr('Evidence', 'independent-inputs'), rr('Evidence', 'actual-owner-question'), rr('Authorization', 'intake')
    service_request, terms, capability, calendar, pricing, work, candidates = [rr(k, n) for k, n in (
        ('ServiceRequest', 'request'), ('ServiceTerms', 'terms'), ('Capability', 'capability'),
        ('ResourceCalendar', 'calendar'), ('FeeBasis', 'fees'), ('WorkProfile', 'work'), ('CandidateSet', 'terms'))]
    client_authority, payer_authority = rr('Authority', 'client'), rr('Authority', 'payer')
    objects = [deepcopy(r) for r in study['objects'] if r['ref'] in assignment['basis_refs']]
    objects.append({'ref': assignment['function_ref'], 'value': assignment})
    observed = {'investment_origin': deepcopy(study['observed']['investment_origin']),
        'native_request_sha256': task_digest(request.model_dump(mode='json')), 'scope': deepcopy(scope),
        'question_code': policy.study_question_code, 'study_scope': exact_scope,
        'declaration_sha256': task_digest(declaration.model_dump(mode='json'))}
    objects.extend([
        {'ref': basis, 'value': {'ref': basis, 'source_kind': 'synthetic', 'basis_kind': 'assumed',
            'locator': 'independent-initial-study-professional-disclosures-not-action-execution',
            'content_hash': observed['declaration_sha256'], 'effective_window': None}},
        {'ref': actual, 'value': {'ref': actual, 'source_kind': 'synthetic', 'basis_kind': 'observed',
            'locator': 'actual-original-owner-study-question-not-appointment',
            'content_hash': task_digest(observed), 'effective_window': None}}])
    clock_basis = ref('Evidence', study['context'].run_id + '-study-monthly-clock')
    objects.append({'ref': clock_basis, 'value': {'ref': clock_basis, 'source_kind': 'synthetic', 'basis_kind': 'assumed',
        'locator': 'declared-original-shared-monthly-business-clock',
        'content_hash': task_digest({'clock_ref': clock, 'tick_unit': 'month'}), 'effective_window': None}})

    def put(reference, **values):
        objects.append({'ref': reference, 'value': {'ref': reference, 'evidence_refs': [basis, actual], **values}})

    def measured(state, *, unit=None):
        raw = state.model_dump(mode='json')
        return known({'value': raw['value'], **({'currency': declaration.currency} if unit is None else {'unit': unit}),
                      'basis_ref': basis}) if raw['state'] == 'known' else raw

    put(clock, evidence_refs=[clock_basis], tick_unit='month')
    put(exact_scope['ref'], organization_id=policy.organization_id)
    for work_ref in exact_scope['coverage_refs']:
        put(work_ref, parent_ref=exact_scope['ref'])
    for identity, purpose in [(client_authority, 'commission_service'), (payer_authority, 'authorize_payment')]:
        put(identity, organization_id=policy.organization_id, actor_id=study['context'].actor_id,
            purposes=[purpose], scopes=[exact_scope], service_codes=[declaration.service_code], validity=validity)
    put(service_request, scope=exact_scope, provider_id=organization.actor_id, provider_organization_id=provider,
        client_id=study['context'].actor_id, client_organization_id=policy.organization_id,
        payer_id=study['context'].actor_id, payer_organization_id=policy.organization_id,
        client_authority_ref=client_authority, payer_authority_ref=payer_authority,
        offered_terms_ref=terms, fee_basis_ref=pricing, permitted_offer_scopes=[exact_scope],
        permitted_service_codes=[declaration.service_code], open_question_refs=[], received_at=now,
        effective_window=validity, status='active')
    planned, = [r['value'] for r in study['objects'] if r['ref']['kind'] == 'TimeWindow']
    permission = declaration.research_permitted.model_dump(mode='json')
    allowed_uses = known(['research'] if permission['value'] else []) if permission['state'] == 'known' else permission
    deliverable = rr('DeliverableRequirement', 'bounded-question')
    put(deliverable, request_ref=service_request, scope=exact_scope, requested_use='research',
        description='bounded-preliminary-study-question:' + policy.study_question_code)
    put(terms, scope=exact_scope, request_ref=service_request, prior_terms_ref=None, provider_id=organization.actor_id,
        client_id=study['context'].actor_id, payer_id=study['context'].actor_id, relation='external',
        region_id=known(request.inputs['opportunity']['region']), service_code=known(declaration.service_code),
        object_type=known(request.inputs['opportunity']['project_type']), requested_uses=known(['research']),
        responsibility_codes=known([declaration.responsibility_code]),
        required_qualification_codes=known([declaration.qualification_code]), required_method_refs=known([]),
        fee=measured(declaration.fee_amount), payment_risk=measured(declaration.payment_risk, unit='risk'),
        work_profile_ref=work, effort_estimate=measured(declaration.effort_amount, unit='effort'),
        desired_window=known(deepcopy(planned)), deliverable_requirement_refs=[deliverable], issued_at=now,
        effective_window=validity, status='offered', selection_priority=known(1))
    regions = list(declaration.capacity_by_region)
    qualification = rr('Qualification', 'license')
    put(capability, organization_id=provider, effective_window=validity, region_ids=known(regions),
        service_codes=known([declaration.service_code]), object_types=known(declaration.object_types), allowed_uses=allowed_uses,
        responsibility_codes=known([declaration.responsibility_code]), method_refs=known([]),
        qualification_refs=[qualification], qualification_coverage='complete')
    put(qualification, organization_id=provider, code=declaration.qualification_code, region_ids=regions,
        service_codes=[declaration.service_code], effective_window=validity, standing=declaration.qualified.model_dump(mode='json'))
    put(work, region_ids=regions, service_codes=[declaration.service_code], object_types=declaration.object_types,
        effective_window=validity, clock_ref=clock, resource_kind=role.lower(), effort_unit='effort', capacity_unit='capacity',
        effort_per_capacity_tick=declaration.effort_per_capacity_tick, method='constant_capacity_over_half_open_window_v1')
    physical = lambda region: ref('Resource', provider + '-initial-study-' + region)
    put(calendar, organization_id=provider, as_of=now, coverage='complete',
        resources=[{'resource_ref': physical(region), 'resource_kind': role.lower(), 'region_id': known(region),
            'total': measured(amount, unit='capacity'), 'effective_window': validity}
            for region, amount in declaration.capacity_by_region.items()],
        commitments=[{'commitment_ref': ref('ResourceCommitment', provider + '-study-' + c.commitment_id),
            'resource_ref': physical(c.region_id), 'window': window(c.start_tick, c.end_tick),
            'quantity': {'value': c.capacity, 'unit': 'capacity', 'basis_ref': basis}}
            for c in declaration.resource_commitments])
    put(pricing, organization_id=provider, scope=exact_scope, effective_window=validity,
        minimum_fee=measured(declaration.minimum_fee_amount), maximum_payment_risk=measured(declaration.maximum_payment_risk, unit='risk'),
        new_work_policy=declaration.new_work_policy.model_dump(mode='json'), counteroffer_terms_refs=[], counteroffer_calculation_refs=[])
    action_input = {'scope': exact_scope, 'request_ref': service_request, 'terms_ref': terms,
                    'capability_ref': capability, 'capacity_ref': calendar}
    if role == 'Architect':
        action_input['price_basis_ref'] = pricing
    else:
        conflict = rr('ConflictCheck', 'independent')
        put(conflict, organization_id=provider, request_ref=service_request, scope=exact_scope,
            status=declaration.conflict_status, conflict_codes=declaration.conflict_codes, checked_at=now, effective_window=validity)
        action_input['conflict_check_ref'] = conflict
    objects.append({'ref': candidates, 'value': {'operation_id': tag, 'scope': exact_scope, 'as_of': now,
        'candidates': [{'ref': service_request, 'permitted_choices': ['decline']}, {'ref': terms, 'permitted_choices': ['accept']}],
        'search_profile_ref': rr('Profile', 'terms')}})
    grant = {'ref': grant_ref, 'organization_id': provider, 'actor_id': organization.actor_id,
        'function_ref': assignment['function_ref'], 'action_ids': [role.upper() + '-A02'], 'scopes': [exact_scope],
        'readable_refs': [], 'tool_ids': [], 'validity': validity, 'basis_refs': [basis, *assignment['basis_refs']]}
    objects.append({'ref': grant_ref, 'value': grant})
    grant['readable_refs'] = [r['ref'] for r in objects]
    context = ActionContext.model_validate({'run_id': study['context'].run_id, 'actor_id': organization.actor_id,
        'function_ref': assignment['function_ref'], 'authorization_refs': [grant_ref], 'operation_id': tag,
        'contract_ref': ref('ActionContract', role.upper() + '-A02'), 'task_ref': rr('DecisionTask', 'service'),
        'scope': exact_scope, 'business_time': now, 'read_token': tag + '-read', 'visible_refs': grant['readable_refs'],
        'candidate_set_ref': candidates, 'execution_mode': 'rule'})
    schemas = COMPONENTS[role][0].SOURCE_SCHEMAS()
    objects = [{'ref': r['ref'], 'value': schemas.validate_projection(Reference.model_validate(r['ref']), r['value']).model_dump(mode='json')}
               for r in objects]
    return {'role': role, 'context': context, 'objects': objects, 'action_input': action_input,
            'grants': [Authorization.model_validate(grant)], 'observed': observed}


class OwnerStudyProfessionalIntakeStep:
    def __init__(self, app):
        self.app = app
        self.bound = {}
        self.assemblers, self.workers = {}, {}
        for role, (assembler, worker, _) in COMPONENTS.items():
            self.assemblers[role] = assembler(registry=app.registry, organizations=app.organizations,
                provider=self, macro_version='gba-public-2026-08-21', source_mode='formal',
                policy_version=app.settings.policy_version, model_version=app.assembly.client.versions['model'])
            self.workers[role.upper() + '-A02'] = worker(store=app.assembly.client.tasks, snapshots=app.snapshots,
                registry=app.registry, client_version=app.VERSION + ':study:' + role,
                model_version=app.assembly.client.versions['model'], validate_invocation=self.validate_invocation,
                validate_wait=app.validate_wait)

    def project(self, *, context, organization_id, grants):
        policy, request = self.bound[task_digest(context.model_dump(mode='json'))]
        _, scope = self.app._current(request)
        source = self.app._sources(policy, request, scope, stage='study-intake')
        if context != source['context'] or organization_id != policy.study_professional_intake.provider_organization_id:
            raise TaskConflict('Professional study intake substitutes original provider/question/context')
        return {'run_id': context.run_id, 'macro_version': 'gba-public-2026-08-21',
            'state_version': 'native-study-professional:' + task_digest(source['objects']), 'read_token': context.read_token,
            'business_time': context.business_time.model_dump(mode='json'), 'organization_id': organization_id, 'objects': source['objects']}

    def validate_invocation(self, row, prepared):
        self.project(context=prepared.context, organization_id=row['identity']['organization_id'], grants=[])
        if prepared.runner.registry is not self.app.registry:
            raise TaskConflict('Professional study intake changes its original registry')
        prepared.reading.recheck()
        return True

    def execute(self, policy, request, scope, key, record):
        source = self.app._sources(policy, request, scope, stage='study-intake')
        for grant in source['grants']:
            self.app.organizations.authorize(grant)
        self.bound[task_digest(source['context'].model_dump(mode='json'))] = (policy, request.model_copy(deep=True))
        prepared = self.assemblers[source['role']].build(source['context'], **deepcopy(source['action_input']))
        worker = self.workers[source['role'].upper() + '-A02']
        identity = worker.register(prepared, request_id=key + ':study:' + worker.ACTION_ID)
        record['study_intake'] = {'identity': identity.as_dict(), 'source_sha256': task_digest(source['objects']), 'observed': source['observed']}
        record = self.app._save(key, record)
        worker.execute(identity, prepared)
        saved = checked_result(worker, identity)
        record['study_intake']['result_sha256'] = saved['result_sha256']
        return self.app._save(key, record)

    def attach(self, study, policy, request, scope):
        source = prepare_intake_sources(self.app, study, policy, request, scope)
        record, = [r for r in self.app._records() if r['scope'] == scope and r['native_request'] == request.model_dump(mode='json')]
        return attach_original_intake_result(self.app, study, policy, source, record, self.workers)


def original_intake_result(record, source, workers, snapshots, organizations, *, tick):
    technical = record.get('study_intake')
    if not technical or 'result_sha256' not in technical:
        raise TaskConflict('Study awaits its saved original professional service result; no replay or assumed offer')
    identity = TaskIdentity(**technical['identity'])
    if identity.action_id not in workers:
        raise TaskConflict('Study history requires its original professional result worker')
    saved = checked_result(workers[identity.action_id], identity)
    snapshot = snapshots.get(identity)
    context = ActionContext.model_validate(snapshot['context'])
    current = context.model_copy(update={'business_time': context.business_time.model_copy(update={'offset': tick})}, deep=True)
    grants = organizations.grants(current, identity.action_id, identity.role)
    allowed = {r.key() for g in grants for r in g.readable_refs} & {r.key() for r in current.visible_refs}
    if (not grants or identity.request_id != record['key'] + ':study:' + identity.action_id
            or identity.run_id != record['investment']['identity']['run_id']
            or identity.role not in COMPONENTS or identity.action_id != identity.role.upper() + '-A02'
            or identity.organization_id != grants[0].organization_id):
        raise TaskConflict('Study substitutes the original professional result identity or current mandate')
    if (technical['result_sha256'] != saved['result_sha256'] or snapshot['identity'] != saved['identity']
            or any(Reference.model_validate(r['ref']).key() not in allowed for r in saved['source_reading'])
            or source is not None and (snapshot['context'] != source['context'].model_dump(mode='json')
                or snapshot['action_input'] != source['action_input']
                or task_digest(source['objects']) != technical['source_sha256'] or source['observed'] != technical['observed']
                or {task_digest(r['ref']): r['projection'] for r in saved['source_reading']}
                    != {task_digest(r['ref']): r['value'] for r in source['objects']})
            or saved['result']['kind'] != 'completed' or saved['result']['payload']['choice'] not in {'accept', 'decline'}):
        raise TaskConflict('Study changes its original service sources, decision, snapshot or current readable authority')
    return saved, {'identity': identity.as_dict(), 'record_sha256': saved['record_sha256'],
        'result_sha256': saved['result_sha256'], 'source_reading_sha256': saved['source_reading_sha256']}


def attach_original_intake_result(app, study, policy, source, record, workers):
    saved, origin = original_intake_result(record, source, workers, app.snapshots, app.organizations, tick=source['context'].business_time.offset)
    payload = saved['result']['payload']
    originals = {task_digest(r['ref']): r['projection'] for r in saved['source_reading']}
    accepted = payload['choice'] == 'accept'
    terms_ref = payload[COMPONENTS[source['role']][2]] if accepted else source['action_input']['terms_ref']
    terms = originals[task_digest(terms_ref)]
    service = originals[task_digest(source['action_input']['request_ref'])]
    candidate, = [r['value'] for r in study['objects'] if r['ref']['kind'] == 'StudyCandidate']
    planning = next(r['value'] for r in study['objects'] if r['ref'] == candidate['window_ref'])
    if (terms_ref != source['action_input']['terms_ref'] or terms['scope'] != candidate['task_scope']['scope_ref']
            or terms['desired_window'] != known(planning) or terms['requested_uses'] != known(['research'])
            or service['client_organization_id'] != policy.organization_id or service['payer_organization_id'] != policy.organization_id):
        raise TaskConflict('Research offer changes original professional terms, requested research scope or original payer')
    requirements = [originals[task_digest(r)] for r in terms['deliverable_requirement_refs']]
    if (len(requirements) != 1 or requirements[0]['scope'] != terms['scope']
            or requirements[0]['request_ref'] != service['ref'] or requirements[0]['requested_use'] != 'research'
            or requirements[0]['description'] != 'bounded-preliminary-study-question:' + policy.study_question_code):
        raise TaskConflict('Research offer changes the exact original unresolved question deliverable')
    rr = lambda kind, name: ref(kind, source['context'].operation_id + '-' + name)
    offer_ref, actual = rr('ServiceOffer', 'actual-original-result'), rr('Evidence', 'actual-result-handoff')
    declaration = policy.study_professional_intake
    basis, = [r for r in source['objects'] if r['ref']['kind'] == 'Evidence' and r['value']['locator'] ==
        'independent-initial-study-professional-disclosures-not-action-execution']
    grant_ref = source['context'].authorization_refs[0].model_dump(mode='json')
    function = source['context'].function_ref.model_dump(mode='json')
    exported = [deepcopy(r) for r in source['objects'] if r['ref'] in [basis['ref'], grant_ref, function]
                or r['ref'] in originals[task_digest(function)]['basis_refs']]
    provenance = {'source_declaration': 'original_professional_intake_result', 'provider_origin': origin,
        'declaration_sha256': task_digest(declaration.model_dump(mode='json')), 'offer_ref': offer_ref,
        'provider_organization_id': declaration.provider_organization_id, 'authority_ref': grant_ref,
        'original_terms_ref': terms_ref, 'accepted': accepted, 'actual_producer_evidence_ref': actual,
        'boundary': 'actual original A02 decision and scoped technical handoff; no appointment or research execution'}
    exported.append({'ref': actual, 'value': {'ref': actual, 'source_kind': 'synthetic', 'basis_kind': 'observed',
        'locator': 'actual-original-professional-A02-study-result-handoff-not-appointment',
        'content_hash': task_digest(provenance), 'effective_window': None}})
    exported.append({'ref': offer_ref, 'value': {'ref': offer_ref, 'evidence_refs': [basis['ref'], actual],
        'provider_organization_id': declaration.provider_organization_id, 'author_actor_id': source['context'].actor_id,
        'author_function_ref': function, 'authority_ref': grant_ref, 'authority_action_id': origin['identity']['action_id'],
        'client_organization_id': policy.organization_id, 'payer_organization_id': policy.organization_id,
        'case_ref': terms['scope']['ref'], 'scope': terms['scope'], 'issue_refs': deepcopy(candidate['issue_refs']),
        'supported_question_codes': declaration.supported_question_codes.model_dump(mode='json'),
        'qualified': declaration.qualified.model_dump(mode='json'), 'research_permitted': declaration.research_permitted.model_dump(mode='json'),
        'fee': terms['fee'], 'window_ref': candidate['window_ref'], 'status': 'offered' if accepted else 'withdrawn',
        'available_at': terms['issued_at'], 'effective_window': terms['effective_window']}})
    existing = {task_digest(r['ref']): r for r in study['objects']}
    for row in exported:
        key = task_digest(row['ref'])
        if key in existing and existing[key] != row:
            raise TaskConflict('Research handoff replaces an existing owner source')
        if key not in existing:
            study['objects'].append(row)
    candidate.update(choice='commission', allocations=[], offer_ref=offer_ref, future_cost=deepcopy(terms['fee']))
    study['action_input']['service_candidates'] = [offer_ref]
    study['observed']['service_offer_declaration'] = provenance
    for row in study['objects']:
        if row['ref']['kind'] == 'Evidence' and row['ref']['id'].endswith('-study-actual-investment-followup'):
            row['value']['content_hash'] = task_digest(study['observed'])
        if row['ref'] == study['context'].candidate_set_ref.model_dump(mode='json'):
            row['value']['candidates'] = [{'ref': offer_ref, 'permitted_choices': ['commission']}]
    visible = [r['ref'] for r in study['objects']]
    owner_grant, = [r['value'] for r in study['objects'] if r['ref'] == study['context'].authorization_refs[0].model_dump(mode='json')]
    owner_grant['readable_refs'] = deepcopy(visible)
    study['context'] = study['context'].model_copy(update={'visible_refs': [Reference.model_validate(r) for r in visible]}, deep=True)
    study['grants'] = [Authorization.model_validate(owner_grant)]
    schemas = OwnerStudyActionAssembler.SOURCE_SCHEMAS()
    study['objects'] = [{'ref': r['ref'], 'value': schemas.validate_projection(Reference.model_validate(r['ref']), r['value']).model_dump(mode='json')}
                        for r in study['objects']]
    return study
