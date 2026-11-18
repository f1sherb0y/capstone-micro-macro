"""Read actual native design results into existing professional A12 methods.

Only original selected firms see their own project aggregate observations.
No design task, published deliverable, cost plan or formal state is created.
"""
from copy import deepcopy

from integration.architect_portfolio_native import PortfolioComposition
from integration.professional_methods_native import ProfessionalMethodsApplication, bind_sources, result_judgment
from integration.module_host import GbaModuleHostConfiguration, GbaModuleHostExtension
from src.coordination.tasks import TaskConflict
from src.coordination.tasks import task_digest


BOUNDARY = ('Native design/information quality and estimated cost inform original professional A12 background-method '
    'judgments. Actual native monthly execution remains macro-owned. No detailed design, quantities, prices, approval, '
    'service completion or qualification renewal is inferred. The owner-only design_coordination_task archive remains '
    'an archive; its detailed work dispatch is not supplied or claimed here.')


class DesignFeedbackApplication(ProfessionalMethodsApplication):
    VERSION = 'professional-design-feedback.v1'
    PREFIX = 'professional_design_feedback_request:'

    def __init__(self, *, professional, settings):
        self.professional = professional
        super().__init__(assembly=professional.assembly, settings=settings,
            authority=professional.authority, install=False)

    def history(self, org, tick):
        history = super().history(org, tick)
        for h in history:
            from integration.bank_financing_private import checked_result
            from src.coordination.tasks import TaskIdentity
            identity = TaskIdentity(**h['micro_identity'])
            saved = checked_result(self.workers[identity.role], identity)
            h['design_review'] = result_judgment(saved).design_review
        return history

    def design_results(self, plan):
        engine = self.assembly.engine
        result = []
        field = {'Architect': 'selected_architect_id', 'Engineer': 'selected_engineer_id'}[plan.role]
        events = [e.model_dump(mode='json') for e in engine.events.events]
        for project in engine.projects.values():
            if project.current_stage.value != 'design' or getattr(project, field) != plan.organization_id:
                continue
            updates = [e for e in events if e['project_id'] == project.project_id
                and e['tick'] == plan.tick and e['event_type'] == 'project_state_updated' and e['stage'] == 'design']
            appointments = [e for e in events if e['project_id'] == project.project_id
                and e['tick'] <= plan.tick and e['event_type'] == 'consultant_team_appointed'
                and e['data'].get(field.removeprefix('selected_')) == plan.organization_id]
            transitions = [e for e in events if e['project_id'] == project.project_id
                and e['tick'] <= plan.tick and e['event_type'] == 'stage_transition'
                and e['data'].get('to_stage') == 'design']
            if len(updates) != 1 or len(appointments) != 1 or len(transitions) != 1:
                raise TaskConflict('Own design feedback lacks its actual original update, appointment or coordination transition')
            event, appointment, transition = updates[0], appointments[0], transitions[0]
            app = self.professional.appointment
            inbox = [r for r in self.assembly.client.inbox.for_organization(
                run_id=self.assembly.client.run_id, organization_id=plan.organization_id)
                if r['event_id'] == appointment['event_id']]
            receipt = app._record(appointment['event_id'], plan.organization_id)
            appointment_plans = [p for p in app.plans if (p.organization_id,p.project_id,p.tick)
                == (plan.organization_id,project.project_id,appointment['tick'])]
            if (len(inbox) != 1 or len(appointment_plans) != 1 or receipt is None
                    or receipt['state'] != 'formed' or receipt['choice'] != 'confirm'):
                raise TaskConflict('Design feedback awaits actual own received and privately confirmed appointment')
            saved = app._formed(receipt, appointment_plans[0], inbox[0])
            if (any(event['data'][k] != getattr(project.performance, k) for k in ('design_quality', 'information_quality'))
                    or event['data']['planned_cost'] != project.estimated_cost):
                raise TaskConflict('Design feedback differs from actual native state')
            result.append({'project_id': project.project_id, 'tick': plan.tick,
                'event': event, 'event_sha256': task_digest(event),
                'appointment_event': appointment, 'appointment_event_sha256': task_digest(appointment),
                'appointment_identity': receipt['identity'], 'appointment_result_sha256': saved['result_sha256'],
                'coordination_transition': transition, 'coordination_transition_sha256': task_digest(transition),
                'design_quality': project.performance.design_quality,
                'information_quality': project.performance.information_quality,
                'estimated_cost': project.estimated_cost, 'initial_budget': project.initial_budget})
        return result

    def sources(self, plan, request):
        _, observed = super().sources(plan, request)
        observed['design_results'] = self.design_results(plan)
        objects = bind_sources(plan, observed)
        observation, = [r['value'] for r in objects if r['ref'] == plan.observation_ref.model_dump(mode='json')]
        if observation.get('design_results') is not None:
            raise TaskConflict('Design results must be unbound until the original native update')
        observation['design_results'] = deepcopy(observed['design_results'])
        return objects, observed


class DesignFeedbackComposition(PortfolioComposition):
    VERSION = 'professional-design-feedback-composition.v1'
    MONTHLY_APPLICATION = DesignFeedbackApplication
    BOUNDARY = BOUNDARY

    def decide(self, request):
        self.check()
        if request.agent.role in self.monthly.COMPONENTS and request.decision_type == 'monthly_enterprise_operation':
            return self.monthly.decide(request)
        return self.professional.decide(request)


def configure_assembly(*, assembly, request, output_directory, offline, configuration):
    if offline is not True:
        raise ValueError('Fixed design feedback scenario requires explicit offline mode')
    assembly.client.native_routes.attach(assembly)
    app = DesignFeedbackComposition(assembly=assembly,
        settings=GbaModuleHostConfiguration.model_validate(configuration).settings)
    return GbaModuleHostExtension(version=app.VERSION, evidence=app.evidence,
        close=app.close, writer_guard=app.read_guard)
