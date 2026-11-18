"""Explicit simulation-only private learning; no formal judgment application.

Reuse the existing fixture-mode assessment save/publication APIs. Actual event
authentication and original A12 workers remain owned by NativeLifecycleApplication.
Synthetic evidence keeps its original provenance and formal source gates stay intact.
"""
from copy import deepcopy
import importlib

from typing import Literal

from src.actions.contracts.common import Reference, StrictRecord, ref_type
from src.coordination.tasks import TaskConflict, task_digest
from src.methods.architect_learning import LEARNING_METHOD


class NativePrivateIntakeJudgment(StrictRecord):
    effect: Literal['simulation_private_intake_recommendation_only']
    learning_profile_ref: ref_type('LearningProfile')
    dimension_ref: ref_type('JudgmentDimension')
    evaluate_value_ref: ref_type('JudgmentValue')
    pause_value_ref: ref_type('JudgmentValue')
    assessment_ref: Reference


def preparation_context(plan):
    return plan.context.model_copy(update={'read_token': plan.context.read_token + '-assessment'}, deep=True)


def validate_plan(plan):
    declared = plan.private_intake_judgment
    if declared is None:
        return
    role = {'ARCHITECT-A12': 'Architect', 'ENGINEER-A12': 'Engineer', 'QS-A12': 'QS'}.get(plan.context.contract_ref.id)
    if (role is None or plan.event_type != 'consultant_team_appointed'
            or plan.context.execution_mode != 'offline_fixture' or plan.appointment_feedback_ref is None
            or plan.settlement_feedback_ref is not None or plan.depends_on
            or declared.assessment_ref.kind != role + 'LearningAssessment'
            or declared.assessment_ref in [Reference.model_validate(row['ref']) for row in plan.objects]
            or declared.assessment_ref not in plan.context.visible_refs):
        raise ValueError('Private simulated intake learning requires its exact selected-professional A12 and future assessment target')
    rows = {task_digest(row['ref']): row['value'] for row in plan.objects}
    get = lambda ref: rows.get(task_digest(ref.model_dump(mode='json') if isinstance(ref, Reference) else ref), {})
    strategy = get(plan.action_input['strategy_ref'])
    profile, dimension = get(declared.learning_profile_ref), get(declared.dimension_ref)
    rules = [get(ref) for ref in profile.get('rule_refs', [])]
    state = get(strategy.get('learning_state_ref'))
    if (profile.get('strategy_ref') != plan.action_input['strategy_ref']
            or profile.get('enabled') != {'state': 'known', 'value': True}
            or profile.get('calculation_method_ref') != LEARNING_METHOD.model_dump(mode='json')
            or profile.get('dimension_refs') != [declared.dimension_ref.model_dump(mode='json')]
            or dimension.get('purpose') != 'cooperation'
            or dimension.get('outcome_codes') != ['appointed']
            or dimension.get('value_refs') != [declared.evaluate_value_ref.model_dump(mode='json'), declared.pause_value_ref.model_dump(mode='json')]
            or len(rules) != 1 or rules[0].get('rule') != {
                'rule_ref': profile['rule_refs'][0], 'dimension_ref': declared.dimension_ref.model_dump(mode='json'),
                'outcome_codes': ['appointed'], 'selected_value_ref': declared.pause_value_ref.model_dump(mode='json'),
                'minimum_samples': 1, 'priority': 0}
            or state.get('learning_profile_ref') != declared.learning_profile_ref.model_dump(mode='json')
            or state.get('applied_feedback_refs') != [] or state.get('execution_refs') != []
            or get(plan.context.candidate_set_ref).get('candidates') != [{
                'ref': declared.pause_value_ref.model_dump(mode='json'), 'permitted_choices': ['update_judgment']}]
            or strategy.get('judgments') != [{'dimension_ref': declared.dimension_ref.model_dump(mode='json'),
                'selected_value_ref': declared.evaluate_value_ref.model_dump(mode='json'),
                'explanation': 'Initial explicit preference: evaluate new intake.'}]):
        raise ValueError('Private intake judgment must preserve its explicit finite cooperation rule and unapplied baseline')


def bind_outcome(plan, feedback, observed):
    if plan.private_intake_judgment is None:
        return
    if observed['data']['status'] != 'appointed':
        raise TaskConflict('Private intake judgment requires actual own Owner selection, not an acceptance intention')
    feedback['event']['outcomes'] = [{'dimension_ref': plan.private_intake_judgment.dimension_ref.model_dump(mode='json'),
        'outcome_code': 'appointed'}]


class NativePrivateIntakeJudgments:
    def __init__(self, application):
        self.application = application
        self._bindings = {}

    def attach(self, plan, assembler):
        if plan.private_intake_judgment is None:
            return
        role = self.application.assembly.client.organization_roles[plan.organization_id]
        module = importlib.import_module('integration.' + role.lower() + '_learning_assessment_publication')
        store_type = getattr(module, role + 'LearningAssessmentPublicationStore')
        provider_type = getattr(module, role + 'LearningAssessmentPublishedViewProvider')
        authority = self.application.authority
        if assembler.methods is None:
            from src.methods.capacity import local_method_registry
            assembler.methods = local_method_registry()
        store = store_type(store=self.application.assembly.client.tasks, registry=authority.registry,
            methods=assembler.methods, organizations=authority.organizations, validate_source=self.validate_source)
        provider = provider_type(provider=self.application, publications=store)
        assembler.provider = provider
        assembler._views.provider = provider
        self._bindings[plan.plan_id] = (assembler, store, provider)

    def provider_for(self, plan):
        return self.application if plan.private_intake_judgment is None else self._bindings[plan.plan_id][2]

    def check(self):
        app = self.application
        expected = {p.plan_id for p in app.plans if p.private_intake_judgment is not None}
        if set(self._bindings) != expected:
            raise TaskConflict('Private learning lost its explicitly declared original plans')
        for plan_id, (assembler, store, provider) in self._bindings.items():
            if (app._actions[plan_id][0] is not assembler or provider.provider is not app
                    or provider.publications is not store or assembler._views.provider is not provider
                    or store.store is not app.assembly.client.tasks or store.registry is not app.authority.registry
                    or store.organizations is not app.authority.organizations or store.methods is not assembler.methods
                    or store.validate_source != self.validate_source or assembler.source_mode != 'fixture'):
                raise TaskConflict('Private learning changed its original store, provider, source mode or authorizations')

    def _sources(self, context):
        matches = [plan for plan in self.application.plans if plan.private_intake_judgment is not None
            and context in (plan.context, preparation_context(plan))]
        if len(matches) != 1:
            raise TaskConflict('Private assessment requires its exact original preparation or publication context')
        plan, = matches
        record = self.application._record(plan)
        events = [] if record is None else [event for event in self.application.assembly.engine.events.events
            if event.event_id == record['observed']['event_id']]
        if len(events) != 1 or self.application.assembly.engine.current_tick < plan.tick:
            raise TaskConflict('Private assessment lost its actual original event or knowledge chronology')
        objects, observed, dependencies = self.application._sources(plan, events[0])
        if (record['observed'] != observed or record['dependencies'] != dependencies
                or record['source_sha256'] != task_digest(objects)):
            raise TaskConflict('Private assessment changed its actual event, sources or dependency record')
        assembler = self._bindings[plan.plan_id][0]
        schemas = assembler.SOURCE_SCHEMAS()
        typed = {task_digest(row['ref']): schemas.validate_projection(Reference.model_validate(row['ref']),
            row['value']).model_dump(mode='json') for row in objects}
        return plan, typed

    def _check_reading(self, context, rows):
        plan, sources = self._sources(context)
        if any(sources.get(task_digest(row['ref'])) != row['projection'] for row in rows):
            raise TaskConflict('Private assessment substitutes original authenticated simulation sources')
        return plan

    def validate_current(self, *, context, action_input, assessment_input, assessment_ref, dependencies, reading):
        plan = self._check_reading(context, reading.evidence())
        if (context != preparation_context(plan) or assessment_ref.model_dump(mode='json') != plan.private_intake_judgment.assessment_ref.model_dump(mode='json')
                or action_input.model_dump(mode='json') != self.application._build_arguments(plan)
                or dependencies):
            raise TaskConflict('Private assessment changes its original finite input, target or calculation dependencies')

    def validate_source(self, record, context):
        plan = self._check_reading(context, record['prepared']['source_reading'])
        if (record['context'] != preparation_context(plan).model_dump(mode='json')
                or record['action_input'] != self.application._build_arguments(plan)
                or record['prepared']['source_mode'] != 'fixture'
                or record['prepared']['projection']['ref'] != plan.private_intake_judgment.assessment_ref.model_dump(mode='json')):
            raise TaskConflict('Private assessment publication changes its simulation-only source or original record')
        return True

    def prepare(self, plan):
        assembler, store, _provider = self._bindings[plan.plan_id]
        if self.application.assembly.engine.current_tick != plan.tick:
            raise TaskConflict('Private assessment cannot execute against a historical event clock')
        context = preparation_context(plan)
        # The runner owns a snapshot of the declared method registry. Bind the
        # original saving store to that actual reading snapshot, preserving its
        # identity check rather than replacing methods or relaxing provenance.
        from integration.service_learning_assessments import prepare_service_learning_assessment
        prepared = assembler.build(context, **self.application._build_arguments(plan))
        calculation = prepare_service_learning_assessment(context=context, action_input=prepared.action_input,
            reading=prepared.reading, action_id=context.contract_ref.id,
            assessment_ref=plan.private_intake_judgment.assessment_ref.model_dump(mode='json'),
            author_authority_ref=plan.context.authorization_refs[0], validate_current=self.validate_current)
        if calculation['kind'] != 'prepared':
            raise TaskConflict('Private intake assessment did not produce its original saved finite report: '
                + str(calculation))
        writer = type(store)(store=store.store, registry=store.registry, methods=prepared.reading._methods,
            organizations=store.organizations, validate_source=self.validate_source)
        saved = writer.save(calculation, context=context, action_input=prepared.action_input, reading=prepared.reading)
        publication = writer.publish(saved['record_sha256'], source_context=context, next_context=plan.context)
        return {'source_mode': 'fixture', 'effect': 'simulation_private_intake_recommendation_only',
            'assessment_record_sha256': saved['record_sha256'],
            'publication_sha256': publication['record_sha256']}

    def validate_saved_reading(self, plan, saved):
        _assembler, store, _provider = self._bindings[plan.plan_id]
        grants = self.application.authority.organizations.grants(plan.context, store.ACTION_ID, store.ROLE)
        publication = store.read(plan.context, organization_id=plan.organization_id, grants=grants)
        if publication is None:
            raise TaskConflict('Private judgment lost its original persisted assessment publication')
        _, sources = self._sources(plan.context)
        projection = publication['object']['value']
        sources[task_digest(projection['ref'])] = projection
        if (not any(row['ref'] == projection['ref'] for row in saved['source_reading'])
                or any(sources.get(task_digest(row['ref'])) != row['projection'] for row in saved['source_reading'])):
            raise TaskConflict('Private judgment result changes its original published assessment or authenticated sources')
        return publication

    def recommendation(self, plan, saved):
        publication = self.validate_saved_reading(plan, saved)
        declared = plan.private_intake_judgment
        payload = saved['result'].get('payload', {})
        revision = payload.get('revision', {})
        changes = revision.get('changes', [])
        if (saved['result'].get('kind') != 'completed' or payload.get('choice') != 'update_judgment'
                or revision.get('prior_strategy_ref') != plan.action_input['strategy_ref']
                or revision.get('learning_profile_ref') != declared.learning_profile_ref.model_dump(mode='json')
                or len(changes) != 1 or changes[0]['dimension_ref'] != declared.dimension_ref.model_dump(mode='json')
                or changes[0]['selected_value_ref'] != declared.pause_value_ref.model_dump(mode='json')):
            raise TaskConflict('Private intake consumption requires its one original declared cooperation recommendation')
        return {'effect': declared.effect, 'choice': 'pause_new_intake',
            'dimension_ref': deepcopy(changes[0]['dimension_ref']),
            'selected_value_ref': deepcopy(changes[0]['selected_value_ref']),
            'assessment_record_sha256': publication['execution_sha256'],
            'publication_sha256': publication['record_sha256']}
