"""Actual own construction events feed original professional A12 background judgments."""
from copy import deepcopy
from integration.professional_methods_native import ProfessionalMethodsApplication, bind_sources
from integration.module_host import GbaModuleHostConfiguration, GbaModuleHostExtension
from src.actions.roles.professional_construction_feedback import EVENT_TYPES
from src.coordination.tasks import TaskConflict, task_digest

BOUNDARY = ('Initial existing professional engagements authorize only own aggregate feedback. '
    'Original A12 background judgments and native monthly execution do not issue work, measurements, '
    'certificates, variation authority or prices. Native execute_work interface failure remains N11.')


class ConstructionFeedbackApplication(ProfessionalMethodsApplication):
    VERSION = 'professional-construction-feedback.v1'
    PREFIX = 'professional_construction_feedback_request:'

    def __init__(self, *, initial_projects, **kwargs):
        self.initial_projects = deepcopy(initial_projects)
        self._initial_sha = task_digest(self.initial_projects)
        super().__init__(**kwargs)

    def check(self):
        super().check()
        if task_digest(self.initial_projects) != self._initial_sha:
            raise TaskConflict('Original initial professional assignment snapshot changed')

    def construction_results(self, plan):
        engine = self.assembly.engine; result = []
        field = {'Architect': 'selected_architect_id', 'Engineer': 'selected_engineer_id'}[plan.role]
        for initial in self.initial_projects:
            if initial[field] != plan.organization_id:
                continue
            project = engine.projects[initial['project_id']]
            if getattr(project, field) != plan.organization_id or not any(
                    e['agent_id'] == plan.organization_id and e['role'] == plan.role for e in initial['engagements']):
                raise TaskConflict('Construction feedback lacks its actual own existing professional relationship')
            for event in engine.events.events:
                if event.project_id != project.project_id or event.tick >= plan.tick or event.event_type not in EVENT_TYPES:
                    continue
                raw = event.model_dump(mode='json')
                result.append({'run_id': plan.context.run_id, 'project_id': project.project_id,
                    'event': raw, 'event_sha256': task_digest(raw), 'initial_assignment': deepcopy(initial),
                    'initial_assignment_sha256': self._assignment_hash(initial)})
        return result

    @staticmethod
    def _assignment_hash(initial):
        return task_digest(initial)

    def sources(self, plan, request):
        _, observed = super().sources(plan, request)
        observed['construction_results'] = self.construction_results(plan)
        objects = bind_sources(plan, observed)
        observation, = [r['value'] for r in objects if r['ref'] == plan.observation_ref.model_dump(mode='json')]
        if observation.get('construction_results') is not None:
            raise TaskConflict('Construction outcomes must remain unbound until actual original execution')
        observation['construction_results'] = deepcopy(observed['construction_results'])
        return objects, observed

    def evidence(self):
        result = super().evidence(); result['boundary'] = BOUNDARY
        result['initial_projects'] = deepcopy(self.initial_projects)
        return result


def configure_assembly(*, assembly, request, output_directory, offline, configuration):
    if offline is not True:
        raise ValueError('Construction feedback scenario requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app = ConstructionFeedbackApplication(assembly=assembly,
        initial_projects=[p.model_dump(mode='json') for p in request.initial_projects],
        settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION, evidence=app.evidence,
        close=app.authority.close, writer_guard=app.read_guard)
