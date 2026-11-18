"""Source requirements from appointment reception to private professional work.

Native engagements are real project-role allocations. Their normalized resource
scale and aggregate stage updates retain their own meaning throughout this map.
The records below do not create relationships, tasks, investments or receipts.
"""
from copy import deepcopy
from pathlib import Path

from integration.contractor_construction_source_review import _source


_ACTIONS = {
    'ARCHITECT-A03': ('architect_appointment', 'confirm_appointment', {
        'confirm': (
            'Own actually received appointment; independently accepted exact service terms and recorded A02 '
            'acceptance; client/payer authority, original function grants and complete current capacity.',
            'Private confirmation of the compatible appointment; does not activate a formal relationship or reserve resources.',
            'Authorized appointment/relationship reception and original ARCHITECT-A04 planner; retain selected status '
            'until a verified producer supplies the actual relationship and detailed task authorities.'),
        'request_amendment': (
            'Original received appointment/terms, exact compatibility mismatch and permitted amendment targets.',
            'Amendment request retaining the original acceptance and terms versions.',
            'Original client/provider terms recipient and independent amended-terms reception before a new confirmation.'),
        'decline_incompatible': (
            'Original appointment, explicit incompatible scope and actual independent private compatibility decision.',
            'Private incompatibility response; does not terminate an existing native engagement.',
            'Actual appointment issuer and authorized response reception; query any original withdrawal separately.'),
    }),
    'ARCHITECT-A04': ('architect_planning', 'plan_design_work', {
        'allocate': (
            'Original active appointment and actual relationship; authorized detailed tasks, original work estimates, '
            'complete investment slices/remaining effort, exact personnel calendars/qualifications and received dependencies.',
            'Private remaining-work plan; no actual work, resource commitment, fee or released deliverable.',
            'Original detailed task/relationship producers, authorized allocation consumer and ARCHITECT-A05 design-work inputs.'),
        'revise_plan': (
            'The same actual tasks and calendars; original prior plan/allocation identities and complete original '
            'occupancy reconciliation, without counting a reservation twice.',
            'Private replacement plan preserving original completed investment and existing commitments.',
            'Original allocation amendment/receipt consumer before later design execution; never rewrite old work facts.'),
        'request_inputs': (
            'Exact original task requirements, missing authorized dependencies and original responsible recipients.',
            'Scoped input request; missing design, permission or capacity remains missing.',
            'Original responsible party and independent dependency reception, then an explicit new planning invocation.'),
    }),
    'ENGINEER-A03': ('engineer_appointment', 'confirm_engineer_appointment', {
        'confirm': (
            'Actually received own appointment, original independently accepted engineering terms, current functions, '
            'capacity and actual independence/conflict evidence.',
            'Private appointment confirmation; not a formal relationship, task release or resource reservation.',
            'Original appointment/relationship reception and ENGINEER-A04 planner using independently authorized engineering tasks.'),
        'disclose_conflict': (
            'Original own appointment, exact independence/conflict evidence and authorized disclosure scope.',
            'Conflict disclosure proposal retaining the underlying evidence and private boundaries.',
            'Authorized client/independence recipient and independently received resolution; no waiver is inferred.'),
        'request_amendment': (
            'Original appointment/acceptance/terms versions and explicit engineering compatibility or authority gap.',
            'Amendment request; accepted terms and existing obligations remain unchanged.',
            'Original requesting party and independent amended appointment/terms reception.'),
    }),
    'ENGINEER-A04': ('engineer_planning', 'plan_professional_work', {
        'allocate': (
            'Original active authorized engineering appointment/relationship; exact technical tasks and supported '
            'work estimates, actual remaining investment, independent investigation/test dependencies, personnel/equipment calendars.',
            'Private engineering work plan; no technical work, test, certificate or committed resource is produced.',
            'Actual relationship/task producers and authorized allocation consumer, then original ENGINEER-A05/A06 work/review inputs.'),
        'revise_plan': (
            'Original prior work plan and allocation/commitment identities, actual task effort and current complete calendars.',
            'Private revised plan preserving already completed investment and original occupancy identities.',
            'Original allocation-change consumer and independently received original outcome; no fabricated capacity release.'),
        'request_investigation': (
            'Exact original engineering task, independently defined missing investigation/test requirements and authorized recipients.',
            'Investigation request; no investigation, test result or revised engineering judgment is inferred.',
            'Existing original investigation intake/task registration and actual investigation-result reception before replanning.'),
    }),
    'QS-A03': ('qs_appointment', 'confirm_qs_appointment', {
        'confirm': (
            'Own received appointment, original independent acceptance and matching terms, current professional '
            'functions/qualifications and complete original capacity.',
            'Private compatible appointment confirmation without a detailed task plan or formal activation.',
            'Actual relationship/task reception before an explicitly authorized QS task-planning invocation.'),
        'confirm_and_plan': (
            'Original compatible appointment plus nonempty independently authorized detailed QS tasks, actual '
            'remaining effort, complete current personnel calendars and received task dependencies.',
            'Private confirmation and work plan; no resource commitment, performed QS service or service fee.',
            'Original task/allocation consumer and actual plan reception before QS-A04 costing or other authorized services.'),
        'request_amendment': (
            'Original appointment/terms/acceptance and actual responsibility, service, window or task compatibility gap.',
            'Scoped amendment request retaining original independently accepted terms.',
            'Original client/provider recipient and independent amended appointment/terms reception.'),
        'revise_plan': (
            'Original prior QS work plan, exact actual task/allocation/commitment history and current complete calendars.',
            'Private revised remaining-work plan without duplicate occupancy or inferred completed work.',
            'Original allocation amendment/receipt consumer, preserving original prior plan and completed investment.'),
    }),
    'QS-A04': ('qs_cost', 'compile_cost_plan', {
        'estimate': (
            'Original authorized brief/design option/task/cost scope; independently produced quantities and '
            'comparable prices, complete coverage/method support, actual saved original cost-method execution and comparison basis.',
            'Private cost plan retaining subtotal/completeness and original calculation provenance; not an approved budget or incurred cost.',
            'Reuse original QSCost calculation preparation, independent validation, saved publication and fresh authorized reading; '
            'then original QS-A05 procurement or authorized Owner comparison via actual disclosure/reception.'),
        'request_quantity': (
            'Original authorized costing scope and exact missing/incompatible quantity requirements with responsible authors.',
            'Quantity evidence request; no measurement or quantity is created.',
            'Original design/quantity producer and independently received measurement-rule/quantity version before recalculation.'),
        'request_price': (
            'Original cost components and exact missing/noncomparable price evidence, including unit, currency, region and validity.',
            'Price evidence request; no quote, conversion or calibration is inferred.',
            'Authorized original price producer and independent price reception before a new original calculation.'),
        'report_limits': (
            'Actual original cost scope, known/unknown quantities and prices, method support and explicit incomplete coverage.',
            'Cost limitations; a known partial subtotal remains partial and is not back-solved from the native project budget.',
            'Original commissioning party and authorized limited-report reception; subsequent decisions preserve the reported limits.'),
    }),
}

_COMPONENTS = {
    'ARCHITECT-A03': [('integration/architect_appointment_actions.py', 'ArchitectAppointmentActionAssembler'),
                     ('integration/professional_appointment_native_sources.py', 'appointment_sources')],
    'ENGINEER-A03': [('integration/engineer_appointment_actions.py', 'EngineerAppointmentActionAssembler'),
                    ('integration/professional_appointment_native_sources.py', 'appointment_sources')],
    'QS-A03': [('integration/qs_appointment_actions.py', 'QSAppointmentActionAssembler'),
              ('integration/qs_appointment_reader.py', 'QSAppointmentReader'),
              ('integration/professional_appointment_native_sources.py', 'appointment_sources')],
    'ARCHITECT-A04': [('integration/architect_planning_actions.py', 'ArchitectPlanningActionAssembler'),
                     ('integration/architect_planning_recovery_reader.py', 'ArchitectPlanningRecoveryReader')],
    'ENGINEER-A04': [('integration/engineer_planning_actions.py', 'EngineerPlanningActionAssembler'),
                    ('integration/engineer_planning_recovery_reader.py', 'EngineerPlanningRecoveryReader')],
    'QS-A04': [('integration/qs_cost_actions.py', 'QSCostActionAssembler'),
              ('integration/qs_cost_calculations.py', 'prepare_qs_cost_calculation'),
              ('integration/qs_cost_calculation_validation.py', 'QSCostCalculationSourceValidator'),
              ('integration/qs_cost_calculation_publication.py', 'QSCostCalculationPublicationStore'),
              ('integration/qs_cost_reader.py', 'QSCostReader')],
}


def professional_work_reviews(root: Path, macro_backend: Path) -> dict:
    """Locate reviewed producers and consumers; preserve runtime acceptance."""
    native = [
        _source(macro_backend, 'simulation/project_lifecycle_engine.py', 'ProjectLifecycleEngine.' + name)
        for name in ('_handle_initiation', '_collect_appointment_decisions', '_handle_design', '_record_lifecycle_task')]
    native += [_source(macro_backend, 'simulation/engagement_manager.py', 'EngagementManager.create_engagement')]
    native += [_source(macro_backend, 'simulation/project_state_update_engine.py', 'ProjectStateUpdateEngine.' + name)
               for name in ('update_design_state', 'update_cost')]
    for row in native:
        row['path'] = (macro_backend / row['path']).relative_to(root).as_posix()
    own_reader = _source(root, 'integration/bindings/gba_v1_views.py', 'read_enterprise_resources')
    result = {}
    for action_id, (module, symbol, choices) in _ACTIONS.items():
        source = _source(root, 'src/actions/roles/' + module + '.py', symbol)
        reuse = [_source(root, path, name) for path, name in _COMPONENTS[action_id]]
        result[action_id] = {
            choice: {
                'status': 'source_requirements_reviewed_runtime_unverified',
                'micro_source': deepcopy(source), 'reviewed_native_sources': deepcopy(native),
                'existing_native_reader': deepcopy(own_reader), 'existing_source_components': deepcopy(reuse),
                'required_producer_outputs': required, 'micro_result_semantics': semantics,
                'next_code_step': consumer,
                'native_source_boundary': (
                    'The original initiation path independently accepts/selects consultants, creates ACTIVE '
                    'project-role engagements with normalized resource allocations and emits the actual team event. '
                    'The existing own-enterprise reader already reads these real engagements; they are not absent. '
                    'The reviewed engagement record does not bind a detailed ServiceRelationship/Appointment/ServiceTerms '
                    'version or per-task personnel commitments. Design-state updates calculate aggregate '
                    'design/information quality, coordination, estimated/planned cost and planned duration; '
                    'cost updates calculate aggregate performance cost. '
                    'Owner-side completed lifecycle tasks are stage archives. None of those reviewed outputs '
                    'alone is the detailed professional task, independent quantity/price or original saved cost '
                    'calculation required by these branches. Other equivalent native producers remain open.'),
                'existing_component_boundary': (
                    'Reuse the original assemblers/workers/readers and cost-method publication components. '
                    'Their existence does not supply an independently registered relationship, actual task release, '
                    'personnel calendar, investment slice or received report. Native A03 reception currently binds '
                    'selected appointment and exact original A02/Owner results; it intentionally keeps '
                    'service_relationship_ref and reservation_ref absent. No activation, allocation, source '
                    'migration or original-core endpoint is synthesized by this review.'),
                'acceptance_effect': 'none',
            } for choice, (required, semantics, consumer) in choices.items()}
    return result
