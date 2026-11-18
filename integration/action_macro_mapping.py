"""Export source-backed action/branch wiring candidates for the frozen GBA core.

This is an engineering map, not an acceptance or progress ledger. Native
operation contracts describe proposal shapes; matching names alone never
authorizes a micro branch or proves that its formal effect was executed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from integration.bootstrap import enable_gba_imports


ROOT = Path(__file__).resolve().parents[1]

# Only explicitly reviewed candidate relationships belong here. Internal
# preparation is listed too so it cannot be mistaken for an independent API.
ROUTES = {
    'OWN-A01': ('evaluate_project_opportunity', 'internal_preparation', ('follow','ignore')),
    'OWN-A16': ('evaluate_project_opportunity', 'internal_preparation', ('propose', 'revise', 'no_proposal')),
    'OWN-A02': ('evaluate_project_opportunity', 'internal_preparation', ('internal_study', 'commission', 'stop')),
    'OWN-A03': ('evaluate_project_opportunity', 'existing_bridge', ('invest', 'reject', 'study_more')),
    'OWN-A04': ('select_appointment', 'existing_bridge', ('accept','reject_all')),
    'OWN-A05': ('select_financing_offer', 'existing_bridge', ('own_funds', 'accept_offer')),
    'OWN-A09': ('select_tender_invitees', 'existing_bridge', ('invite',)),
    'OWN-A10': ('decide_contract_award', 'existing_bridge', ('accept', 'revise')),
    'BANK-A01': ('consider_financing', 'internal_preparation', ('retain_strategy', 'revise_strategy')),
    'BANK-A02': ('consider_financing', 'internal_preparation', ('accept_for_review', 'decline')),
    'BANK-A03': ('consider_financing', 'internal_preparation', ('recommend', 'conditional', 'decline')),
    'BANK-A04': ('consider_financing', 'existing_bridge', ('offer', 'conditional_offer', 'decline')),
    'BANK-A05': (None, 'existing_internal_bridge', ('confirm',)),
    'GOV-A02': ('consider_review_assignment', 'existing_bridge', ('accept_for_processing', 'decline_processing')),
    'GOV-A04': ('decide_approval', 'internal_preparation', ('assess', 'propose_conditions')),
    'GOV-A07': ('decide_approval', 'existing_bridge', ('approve', 'defer_by_procedure')),
    'GOV-A12': ('decide_monthly_operation', 'existing_bridge', ('record_feedback',)),
    'CONTRACTOR-A01': ('consider_tender', 'internal_preparation', ('participate', 'clarify', 'decline')),
    'CONTRACTOR-A02': ('consider_tender', 'existing_bridge', ('submit_bid', 'decline_bid')),
    'CONTRACTOR-A04': ('decide_contract_terms', 'existing_bridge', ('accept', 'revise')),
    'CONTRACTOR-A05': ('select_supplier', 'existing_bridge', ('accept_supply_offer',)),
    'SUPPLIER-A01': ('consider_supply_order', 'internal_preparation', ('respond', 'clarify', 'decline')),
    'SUPPLIER-A02': ('consider_supply_order', 'internal_preparation', ('propose_original', 'propose_substitute', 'decline')),
    'SUPPLIER-A03': ('consider_supply_order', 'internal_preparation', ('quote', 'decline_quote')),
    'SUPPLIER-A04': ('consider_supply_order', 'existing_bridge', ('accept', 'reject')),
    'QS-A06': ('evaluate_bid', 'existing_bridge', ('evaluate','exclude_authorized','no_valid_bid')),
    'QS-A12': (None, 'existing_internal_bridge', ('record_feedback',)),
}
for _role in ('ARCHITECT', 'ENGINEER', 'QS'):
    ROUTES[_role + '-A01'] = ('consider_appointment', 'internal_preparation', ('express_interest',))
    ROUTES[_role + '-A02'] = ('consider_appointment', 'existing_bridge', ('accept', 'decline'))
    ROUTES[_role + '-A03'] = (None, 'existing_internal_bridge',
        ('confirm', 'request_amendment', 'decline_incompatible') if _role == 'ARCHITECT'
        else ('confirm', 'request_amendment'))
    ROUTES[_role + '-A12'] = (None, 'existing_internal_bridge', ('record_feedback',))


def build_mapping():
    macro = enable_gba_imports()
    from integration.contractor_construction_source_review import construction_source_reviews
    construction_reviews = construction_source_reviews(ROOT, macro / 'gba_construction_sim/backend')
    from integration.supplier_fulfillment_source_review import supplier_fulfillment_reviews
    from integration.funding_fulfillment_source_review import funding_fulfillment_reviews
    from integration.professional_work_source_review import professional_work_reviews
    from integration.qs_evaluation_source_review import qs_evaluation_reviews
    source_reviews = {**construction_reviews,
        **supplier_fulfillment_reviews(ROOT, macro / 'gba_construction_sim/backend'),
        **funding_fulfillment_reviews(ROOT, macro / 'gba_construction_sim/backend'),
        **professional_work_reviews(ROOT, macro / 'gba_construction_sim/backend'),
        **qs_evaluation_reviews(ROOT, macro / 'gba_construction_sim/backend')}
    from integration.native_lifecycle_actions import ACTION_RANGES
    from gba_construction_sim.backend.agents.operation_specs import get_operation_contract, list_operation_contracts
    from src.actions.processors import register_representative_processors
    from src.actions.registry import ActionRegistry

    catalog_path = ROOT / 'config/action_registry.json'
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    registry = register_representative_processors(ActionRegistry())
    actions = []
    for action in catalog['actions']:
        action_id = action['action_id']
        if (action_id in source_reviews
                and set(action['choices']) != set(source_reviews[action_id])):
            raise ValueError('Source review differs from the original branch scope: ' + action_id)
        registration = registry.get(action_id)
        route = ROUTES.get(action_id)
        contract = get_operation_contract(route[0], action['role']) if route and route[0] else None
        branches = []
        for choice in action['choices']:
            selected = route is not None and (not route[2] or choice in route[2])
            use = route[1] if selected else 'requires_branch_review'
            if action_id == 'BANK-A02' and choice == 'decline':
                use = 'existing_bridge'
            if action_id == 'OWN-A16' and choice == 'no_proposal':
                use = 'existing_bridge'
            branches.append({
                'choice': choice,
                'use': use,
                'candidate_operation': route[0] if selected else None,
                'status': 'bridge_exists_application_pending' if selected and use in {'existing_bridge', 'existing_internal_bridge'}
                          else 'requires_adaptation' if selected else 'requires_semantic_review',
                'closure': 'Execute the original typed branch from authorized current sources; '
                           'prove its next consumer. For formal effects, also prove native '
                           'request consumption, execution and recipient-scoped feedback.',
                **({'reviewed_source_requirements': source_reviews[action_id][choice]}
                   if action_id in source_reviews else {}),
            })
        actions.append({
            **({'native_authorized_bid_exclusion': {
                'implementation': 'integration.qs_bid_admissibility:QSBidAdmissibility v2; QSBidNativeBridge v7; QSEvaluationLearning v5; earlier v1/v6/v4 evidence retained separately',
                'input_producer': 'integration.qs_bid_admissibility_development:prepare_admissibility_sources',
                'enable': 'qs_bid_native_development --with-native-owner-selection --exclude-contractor-id ORIGINAL_CONTRACTOR_ID; shared financing_professional_development --with-contractor-tender --with-qs-evaluation --qs-exclude-contractor-id ORIGINAL_CONTRACTOR_ID. Explicit initial declarations only.',
                'source': 'Original known same-round rule failure, effective received buyer OWN-A09 delegation, matching delegate/function/round/bid and independently evidenced native score.',
                'native_stages': 'Original evaluate_bid positive score proposal remains distinct from the original qs_bid_evaluation exclude_bid negative final decision. The original native loop filters the rejected bid.',
                'consumer': 'Existing actual later QS-A12 includes original exclusion identity/result and original proposal/final/event provenance in authorized_exclusions. The original full comparison snapshot and all submitted prices remain unchanged.',
                'evidence': 'output/integration/qs_authorized_exclusion_20261017_01/manifest.json',
                'shared_evidence': 'output/integration/shared_qs_authorized_exclusion_20261017_01/manifest.json; exact original v6/v4 runtime revision is retained in that evidence.',
                'limits': 'Explicitly synthetic initial sources; no inferred private delivery to an excluded bidder, release of its resources, signed contract or cash. Model/restart combinations, missing-delegation repair and old task migration need their own evidence.',
            }} if action_id in {'QS-A06','QS-A12'} else {}),
            **({'native_no_valid_bid_deferral': {
                'implementation': 'integration.qs_no_valid_outcome; QSBidNativeBridge v7; QSBidAdmissibility v2; QSEvaluationLearning v5',
                'input_producer': 'integration.qs_bid_all_excluded_development:prepare_all_excluded_rounds',
                'enable': 'qs_bid_native_development --with-native-owner-selection --with-evaluation-feedback --with-qs-learning --exclude-all-bids',
                'source': 'Both original known failed qualifications, independent positive score evidence and effective buyer delegation for each bid; distinct initial source contexts for each actual native review.',
                'native_effect': 'Each original final exclusion filters that bid; the original Owner defers selection when none remains. Submitted bids and original project stage are retained.',
                'owner_final': 'The bounded final adapter verifies every original negative QS final and the actual empty Owner candidate set, then preserves the original negative native Owner proposal. Private QS task identities are not added to the Owner response.',
                'consumer': 'Later original QS-A12 consumes the earlier native deferral with both original exclusion identities/results. Matching local/global events and current private-source grants are required.',
                'evidence': 'output/integration/qs_no_valid_bid_20261017_01/manifest.json',
                'limits': 'A bounded standalone synthetic scenario; no terminal buyer refusal, private bidder receipt, resource release, signed contract, actual costs or cash. Shared all-bid exclusion, model and restart combinations need separate evidence.',
            }} if action_id in {'QS-A06','QS-A12'} else {}),
            **({'native_evaluation_outcome_query': {
                'endpoint': 'QSBidNativeBridge.query_native_outcome(original_identity, organization_id=own_id, tick=current_tick)',
                'implementation': 'integration.qs_evaluation_outcome_query:query_qs_evaluation_outcome',
                'versions': 'QSBidNativeBridge v7; QSEvaluationLearning v5; earlier v5/v3 and v6/v4 evidence retained separately',
                'source': 'Original QS-A06 saved round, immutable invocation, per-bid proposal/final tasks and matching project/global completion event; fully delegated no-valid-bid rounds instead authenticate the actual native selection deferral.',
                'consumer': 'Existing later original QS-A12 _sources reads the same authenticated published outcome; default history remains strictly earlier.',
                'authority': 'Original saved private sources require live grants at the actual current engine clock; original context time is retained.',
                'evidence': 'output/integration/qs_evaluation_outcome_query_20261017_01/manifest.json',
                'limits': 'Read-only unknown/observed result, no replay or resubmission. Published scores/native selection do not prove a signed contract, actual costs, cash or improved capability. Old tasks are not migrated.',
            }} if action_id in {'QS-A06','QS-A12'} else {}),
            **({'native_government_actor_ownership': {
                'implementation': 'integration.government_intake_native:GovernmentIntakeApplication v16; integration.government_approval_native:GovernmentApprovalApplication; integration.government_monthly_native:GovernmentMonthlyApplication v4',
                'configuration': 'government_intake_development --organization-actor-ids JSON; initial declarations only.',
                'shared_configuration': 'financing_professional_development --with-government-and-supply --government-actor-ids JSON; original two regulatory organizations only, may coexist with --bank-actor-ids.',
                'shared_identity_evidence': 'output/integration/shared_government_actor_20261017_01/manifest.json',
                'scope': 'Original GOV-A02 intake, GOV-A04 review, GOV-A07 decision and GOV-A12 approval/monthly feedback.',
                'binding': 'Original registry grants bind actual executing actors to organizations. Contexts, author, signer and authority actor fields retain actual actors; native enterprises, applicant, recipient organizations and technical tasks retain organization IDs. Changing executing actors does not appoint a different submission agent or replace the original direct applicant submission.',
                'pending_authority': 'integration.government_native_wait:validate_pending_result verifies original context/task/result/source digests and current registry grants for the task organization. It does not assume actor ID equals organization ID or resolve missing information automatically.',
                'history_authority': 'integration.government_history_authority:authorize_government_history rechecks original grants at the actual engine clock before private intake/approval/completion/monthly history and source handoffs. Original snapshot times and task/result identities remain unchanged. Missing live registry, expired or revoked grants and undisclosed saved sources are rejected.',
                'history_authority_evidence': 'output/integration/government_history_authority_20261017_01/manifest.json',
                'evidence': 'output/integration/government_actor_identity_20261017_01/manifest.json',
                'limits': 'Initial binding only. Original independent synthetic submissions and monthly feedback stay explicit; no migration of sealed inputs, old tasks or histories. The shared identity case is separately scoped; model/restart combinations, detailed filing, permits and inspections require their own evidence. Macro sources stay frozen.',
            }} if action_id in {'GOV-A02','GOV-A04','GOV-A07','GOV-A12'} else {}),
            **({'native_owner_actor_ownership': {
                'implementation': 'integration.owner_opportunity_native:OwnerOpportunityApplication v13',
                'source_producer': 'integration.owner_opportunity_native_sources:prepare_opportunity_sources',
                'configuration': 'owner_opportunity_native_development --organization-actor-ids JSON; initial Owner/QS/Architect declarations only.',
                'scope': 'Original OWN-A01 observation, OWN-A16 private proposal, OWN-A03 investment/preparation/study judgment and OWN-A02 bounded research authorization.',
                'binding': 'Native enterprise, project owner and technical task organizations retain organization IDs. Executing Owner and independent cost/schedule authors use their actual registered actors. Original current grants determine ownership for observation, proposal and study handoffs; actor and organization IDs are never assumed equal.',
                'current_history_authority': 'integration.owner_opportunity_native_feedback:authorize_owner_history rechecks original initiation/decline results and linked A02 authorization against actual current read time and readable references. Original snapshots and business times are retained; reading does not execute research or resubmit a decision.',
                'evidence': 'output/integration/owner_opportunity_actor_20261017_01/business-checks.json',
                'observed': 'Three actual two-tick business artifacts: distinct-actor investment 24 original actions, distinct-actor study 32 and default identity investment 24. Own actual initiation/non-initiation feeds later decisions. Seven retained handoffs reject revoked authority; foreign actors are rejected. Six invalid initial declarations fail before input creation.',
                'verification_boundary': 'Default pytest case passed separately. The first process was interrupted after Windows fatal diagnostics; its two complete business artifacts and original SQLite results were independently verified read-only, without replay. No claim of three terminal pytest passes or full regression.',
                'limits': 'Independent synthetic commercial sources; bounded research authorization creates no completed report, spending, reservation or external appointment. Shared-host actor declarations, model/restart combinations and migration of old sealed histories remain unverified. Macro sources stay frozen.',
            }} if action_id in {'OWN-A01','OWN-A02','OWN-A03','OWN-A16'} else {}),
            **({'native_professional_actor_ownership': {
                'configuration': 'professional_intake_development --organization-actor-ids JSON; initial declarations only.',
                'scope': 'Original professional A01/A02, Owner A04, selected professional A03 and original professional A12 with later A02 consumption.',
                'binding': 'Native enterprise IDs, task organizations, event recipients and selected providers remain organization IDs. Original ServiceRequest/ServiceTerms provider_id, client_id and payer_id are actors; their explicit organization fields retain ownership. Inviter/interest recipient, commercial author/payer and A03 recorded decision use the actual registered actor.',
                'authority': 'Original OrganizationRegistry actor/function/action/scope grants remain mandatory. Cross-organization actor substitution is rejected; source and result hashes remain bound to original inputs.',
                'verification': 'Legacy and distinct-actor actual two-tick cases each completed 40 original micro actions and 88 formed technical tasks; five A03 confirmations, eight intake-decision A12 records and five actual-selection A12 records. Later original Engineer A02 consumes its own record and declines new work.',
                'evidence': 'output/integration/professional_actor_identity_checks_20261017_01/checks.json',
                'completed_tick_restart_evidence': 'output/integration/professional_checkpoint_checks_20261017_01/checks.json',
                'limits': 'Independent synthetic initial sources; five organizations in four roles. No runtime renaming, history migration, detailed active service relationship, task release, charge or cash receipt. Distinct-actor completed-tick feedback consumption is verified separately; unresolved branches and eight-role identity composition remain for concentrated integration.',
            }} if action_id == 'OWN-A04' or action_id in {r + '-' + a
                for r in ('ARCHITECT','ENGINEER','QS') for a in ('A01','A02','A03','A12')} else {}),
            **({'appointment_to_planning_source_boundary': {
                'producer': 'integration.professional_appointment_native_sources:appointment_sources',
                'producer_state': 'Original A03 receives an actual native selection, with Appointment.status selected and service_relationship_ref null; it creates no active detailed service relationship.',
                'consumer': ('src.actions.roles.architect_planning:plan_design_work' if action_id == 'ARCHITECT-A04'
                    else 'src.actions.roles.engineer_planning:plan_professional_work'),
                'required_source': 'Original A04 requires Appointment.status active and a non-null service_relationship_ref, in addition to separately authorized task, personnel, calendar, methods and actual investment facts.',
                'status': 'requires_authorized_detailed_relationship_and_task_producer',
                'boundary': 'Do not promote native team selection or private A03 confirm into an active service relationship, work release or completed investment. This identifies the current producer/consumer mismatch; it is not a claim that all native service interfaces are absent.',
            }} if action_id in {'ARCHITECT-A04','ENGINEER-A04'} else {}),
            **({'native_appointment_feedback': {
                'implementation': 'integration.native_lifecycle_actions:NativeLifecycleApplication',
                'source_reader': 'integration.professional_intake_feedback:authenticate_intake_decision',
                'input_producer': 'integration.professional_feedback_development:feedback_plan',
                'option': 'professional_intake_development --with-feedback; shared --with-professional-feedback',
                'trigger': 'Actual recipient appointment_decision event, after its original A02 proposal and final decision.',
                'consumer': 'Original private Architect/Engineer/QS A12 record_feedback worker in the same authority and journal.',
                'supported_choice': 'record_feedback',
                'source_binding': 'Exact global/project event, original recipient projection and inbox delivery, '
                    'same formed own A02 task, proposal and final decision. Bind original Feedback subject/event '
                    'digests and record-only interpretation; no other organization result is read.',
                'outcomes': ['accepted_pending_owner_selection', 'declined', 'appointed'],
                'status': 'three_role_native_decision_and_selection_feedback_verified_shared_selection_pending',
                'evidence': 'output/integration/professional_feedback_checks_20261017_03/test_native_acceptance_and_dec0/runtime/professional-feedback.json',
                'selection_and_consumption_evidence': 'output/integration/professional_selection_feedback_checks_20261017_01/test_native_acceptance_and_dec0/runtime/professional-feedback.json',
                'next_consumer': 'Later original own A02 binds its completed actual-selection A12 record into prior-appointment Evidence and uses the existing explicit appointment-count policy. Actual later Engineer decline verified; no automatic judgment update.',
                'completed_tick_restart': {
                    'evidence': 'output/integration/professional_checkpoint_checks_20261017_01/checks.json',
                    'implementation': 'integration.native_checkpoint; original professional configure_assembly and original CLI',
                    'actual_result': 'Two actual processes preserve the same simulation, 45 old task records and the first result file; continuation reaches 88 formed tasks and 40 original micro actions. Later Engineer A02 consumes its pre-checkpoint own A12 selection record and declines under the existing explicit count policy.',
                    'identity': 'Distinct organization and execution actor IDs; original same journal, sources, event and result digests.',
                    'limits': 'Completed tick 1 to tick 2 in the separate professional composition only. No in-progress replay, unknown formal receipt, runtime native organization change or automatic judgment update.',
                },
                'shared_assembly': 'output/integration/shared_professional_feedback_assembly_20261017_01/runtime-02/assembly.json',
                'shared_decision_feedback_runtime': 'output/integration/shared_final_account_discussion_20261017_02/runtime/result.json',
                'limits': 'Private feedback recording only; acceptance is not Owner appointment, service delivery, '
                    'fee, cash, changed judgment, capability improvement or qualification renewal. '
                    'Actual appointed feedback does not create a detailed service Appointment/Task. '
                    'Update_judgment/training and shared selection-feedback business verification remain pending. '
                    'Completed-tick original-engine restart and later own feedback consumption have the separate evidence above; failed or in-progress ticks are not replayed.',
            }} if action_id in {r + '-' + a for r in ('ARCHITECT', 'ENGINEER', 'QS') for a in ('A02', 'A12')} else {}),
            **({'native_judgment_assessment_source_boundary': {
                'evidence': 'output/integration/professional_checkpoint_checks_20261017_01/judgment-boundary.json',
                'existing_components': 'Original role save_assessment, same-journal publication and finite declared-rule processor already exist.',
                'current_binding': 'Default native appointment feedback remains record_feedback. Explicit private_intake_judgment plans reuse original fixture-mode assessment publication and A12 update_judgment; initial and simulated-event Evidence remain synthetic.',
                'source_gate': 'integration.service_learning_assessments:prepare_service_learning_assessment and the shared original publication validator reject synthetic Evidence in formal mode.',
                'private_simulation_route': {
                    'implementation': 'integration.native_private_intake_judgment:NativePrivateIntakeJudgments',
                    'input_producer': 'integration.professional_intake_development:build_bundle --with-feedback --with-private-intake-judgment',
                    'shared_input_option': '--with-professional-feedback --with-professional-private-intake-judgment',
                    'evidence': 'output/integration/professional_judgment_implementation_20261017_01/checks-06.json',
                    'actual_result': 'Original native two-tick run: 32 micro results, 76 formed tasks, three original saved/published finite assessments and three original A12 recommendations. Later Architect and QS A02 consume their own exact saved recommendation and decline with all count policies disabled.',
                    'earlier_all_role_example_boundary': 'The first all-role case does not reach a later Engineer request: the original macro suspends after no QS accepts, before collecting Engineer decisions. Its three saved assessments and A12 recommendations remain valid; the separate Engineer evidence below proves its later consumer.',
                    'initial_policy_selection': '--private-intake-judgment-role and shared --professional-private-intake-judgment-role select initial roles; omitted means all three roles. Other roles retain record-only feedback. No running history or identity migration.',
                    'engineer_selection_and_consumption_evidence': 'output/integration/professional_judgment_implementation_20261017_02/checks-engineer.json',
                    'actual_engineer_result': 'Separate original two-tick run: 40 micro results and 88 formed tasks. Only Engineer uses the declared private preference, all count limits are disabled, and its later A02 consumes the exact original published assessment and A12 recommendation before the actual native decline.',
                    'shared_completed_tick_restart': {
                        'evidence': 'output/integration/professional_judgment_implementation_20261017_02/checks-shared-05.json',
                        'actual_result': 'Eight actual micro roles, 104 original micro results, 264 formed tasks. Two actual CLI processes save tick 2 and resume tick 3, preserving 195 old task records and the original result file. Later Engineer A02 consumes its pre-checkpoint assessment/publication/A12 recommendation, with the appointment-count policy disabled.',
                        'initial_window': 'The opt-in shared generator includes the third declared professional intake tick and the corresponding optional Government monthly source window.',
                        'source_checks': 'Actual native region, project type, financing tick and independent professional sources must match. Earlier Dongguan/type mismatch and a late-created project outside the Bank source window remain retained failures; no source, event or failed tick was rewritten.',
                        'scope': 'Existing financing, Owner opportunity, regulatory/supply and final-account composition; completed ticks only. Other configurations and in-progress/unknown formal receipts are not proved.',
                    },
                    'effect': 'Explicit simulation-only private intake recommendation. No formal judgment application, capacity, training, qualification or cash effect.',
                    'mapping_scope': 'Additional fixture-mode internal route; formal/default branch classifications remain unchanged.',
                },
                'remaining': 'Formal-mode assessment still requires original authorized non-synthetic sources. Preserve provenance, existing formal checks and the distinction between a proposed and applied strategy.',
                'scope': 'Current micro/integration source and binding limitation; no claim that the frozen macro lacks learning capabilities.',
            }} if action_id in {'ARCHITECT-A12', 'ENGINEER-A12', 'QS-A12'} else {}),
            **({'lifecycle_private_application': {
                'implementation': 'integration.native_lifecycle_actions:NativeLifecycleApplication',
                'input_contract': 'integration.native_lifecycle_actions:NativeLifecycleInput',
                'schema': 'integration/examples/native_lifecycle_actions_input.schema.json',
                'input_producer': 'integration.financing_professional_development:build_bundle --lifecycle-input',
                'trigger': 'The unchanged native EventSystem.add_observer API, exact live global/project events and actual named parties.',
                'processing': 'Reuse the original role host action routing, original typed assembler and durable result worker; '
                    'share the existing authority, registry, task journal and engine writer guard.',
                'dependencies': 'Explicit topological dependencies require original completed results of the same organization, '
                    'project, scope and clock. Trigger and dependency evidence enter the original typed reading/audit. '
                    'Cross-organization copying is rejected; it still needs original authorized reception components.',
                'dependency_waits': {
                    'implementation': 'integration.native_lifecycle_dependencies',
                    'version': 'gba-v1-native-lifecycle-actions.v10',
                    'behavior': 'Not-started, unresolved and unknown predecessor executions retain a technical waiting_dependencies record without registering or executing the successor. Independent plans for the same actual event continue. Source corruption and authorization failures remain errors.',
                    'continuation': 'NativeLifecycleApplication.resume_waiting_dependencies(plan_id) starts only a never-registered successor whose actual event and original clock still match. A ready wait does not start on observation redelivery; saved-result recovery never reexecutes a predecessor.',
                    'authority': 'Recheck original predecessor action grants and retained private readable references, exact current invocation versions, sealed sources and actual global/project event. Keep the original wait provenance when the successor starts.',
                    'actual_verification': 'Actual native two-tick final-account review retains original Owner reconciliation needs_information; its dependent action remains unregistered, independent original Owner dispute completes, duplicate delivery does not retry, and historical continuation is rejected. Existing six-action/five-message closeout chain remains compatible.',
                    'technical_verification': 'Synthetic retained events and real original Supplier A05 workers verify unknown predecessor recovery without result changes, independent work, no automatic ready-wait start, explicit two-successor continuation and duplicate prevention.',
                    'evidence': 'output/integration/native_lifecycle_dependency_checks_20261017_01/checks.json',
                    'limits': 'Control flow only, no new formal business endpoint, source completion, payment, task release or ledger. This is not verification of all 32 action types or every shared/checkpoint combination.',
                },
                'status': 'implemented_sources_required_business_unverified',
                'formal_execution': 'No command is submitted by this application. A private execution intent, verification '
                    'draft or plan does not prove formal production, shipment, certificate, cash or cleared obligations.',
                'source_boundary': 'Independent detailed inputs remain independent. Detailed core_event_id objects require '
                    'their verified native readers; an aggregate trigger cannot authenticate them. No unknown action is replayed.',
                'current_read_authority': {
                    'version': 'gba-v1-native-lifecycle-actions.v15',
                    'implementation': 'integration.native_lifecycle_dependencies:authorize_private_sources',
                    'behavior': 'Original saved-result queries, same-organization dependency reads and private evidence exports recheck original action grants and retained readable references at the actual current engine tick. An authorization-only copy carries current read time; original invocation, input, task identity, event, snapshots and worker result retain original business time. Expired or revoked authority never permits replay or resubmission.',
                    'evidence': 'output/integration/lifecycle_current_authority_20261017_01/manifest.json',
                    'limits': 'Authorization and existing recovery/dependency behavior only; not runtime coverage of all 32 supported action types, detailed formal business effects, old task-version migration or a new full lifecycle regression.',
                },
                  'saved_result_recovery': 'Query the original registration, invocation, seven execution versions and retained '
                      'authorized sources. Finalize only an existing validated saved result through the original worker; '
                      'missing results remain unknown. Native observer diagnostics are retained separately and cannot change '
                      'business event fields. Application reattachment requires the actual retained engine and journal; '
                      'this is not full native-engine restart acceptance.',
                'coverage_boundary': 'This shared private entry point does not resolve each choice-specific formal mapping '
                    'or promote any branch to runtime acceptance.',
            }} if action['role'] in ACTION_RANGES and int(action_id.split('-A')[1]) in ACTION_RANGES[action['role']] else {}),
            'action_id': action_id, 'role': action['role'], 'title': action['title'],
            'source': {'path': action['source'], 'line': action['source_line'], 'sha256': action['source_sha256']},
            'processor_id': registration.processor_id,
            'processor': registration.processor.__module__ + ':' + registration.processor.__qualname__,
            'skill': str(registration.skill.manifest.skill_id),
            'methods': [ref.model_dump(mode='json') if hasattr(ref, 'model_dump') else str(ref)
                        for ref in registration.skill.manifest.method_refs],
            'input_contract': action['input_definition'], 'output_contract': action['payload_definition'],
            'trigger': 'Current native role/operation request' if contract else
                       'Authorized internal workflow or current native result; concrete producer pending',
            'read_boundary': 'Current organization grants intersect context.visible_refs; '
                             'same run, project, business clock and read token',
            'clock_and_units': 'Keep typed micro units/currency/clock. Any native scalar mapping '
                               'requires an explicit sourced conversion; native monthly resource '
                               'scalars do not imply detailed work or bank transaction records.',
            **({'native_decline_policy_feedback': {
                'implementation':'integration.supplier_screening_decline_feedback:screening_decline_feedback',
                'input_producer':'integration.supplier_order_native_development:build_bundle',
                'evidence':'output/integration/supplier_decline_policy_checks_20261017_01/checks.json',
                'enable':'--decline-after-prior-declines N; shared --supplier-decline-after-prior-declines N. '
                    'Independent first-decline inputs may now compose original micro Contractor A05.',
                'verified_chain':'Original A01/A02/A03 actual refusal -> native confirmed supply decision -> '
                    'later own original A01 reads the exact earlier result and tightens its explicit private '
                    'evaluate policy to decline_new_work -> native refusal -> original Contractor A05 '
                    'chooses an actually accepted Supplier B quote in both rounds.',
                'checks':'Strictly earlier actual own events, original workflow/result, current original-source '
                    'grants and readable references. Acceptances and selections are not refusals. Reject duplicate '
                    'outcomes, changed accepted flags and revoked predecessor authority; preserve old sources/results.',
                'limits':'Three independent synthetic two-tick cases verified with distinct original actors; '
                    'default selection feedback compatible. No missing/unknown result becomes a refusal, no '
                    'partial quote becomes whole acceptance, and no detailed order/stock/delivery/cash is inferred. '
                    'Shared screening refusal, later consumption, same-call B order continuation and completed-tick restart are verified in shared_business_recovery_case. Other negative business/recovery combinations remain pending.',
            }} if action_id in {'SUPPLIER-A01','SUPPLIER-A02','SUPPLIER-A03','CONTRACTOR-A05'} else {}),
            **({'native_partial_supply_boundary': {
                'evidence':'output/integration/supplier_decline_policy_checks_20261017_01/partial-scope-boundary.json',
                'existing_internal_support':'Original screening handoff supports limited_scope with actual buyer '
                    'permission and complete received-line correspondence.',
                'reviewed_native_boundary':'Reviewed supply proposals and supplier selection operate at project '
                    'willingness/one selected supplier. They do not apply original accepted line subsets or '
                    'partial quantities. Current complete-demand composition cannot relabel limited_scope '
                    'or accept_partial as native whole acceptance.',
                'scope':'Only these reviewed native callsites and composition; locate equivalent original '
                    'receiver and actual partial-demand/quantity sources before formal wiring.',
            }} if action_id in {'SUPPLIER-A01','SUPPLIER-A04'} else {}),
            **({'native_decline_bridge': {
                'implementation':'integration.supplier_order_native_decline:decline_for_supply',
                'application':'integration.supplier_order_native:SupplierOrderNativeApplication',
                'choice':'decline_quote' if action_id=='SUPPLIER-A03' else 'decline',
                'native_action':'decline_supply_order',
                'enable':'Original optional screening/product/quote stages; development --first-decline-stage screening|product|quote',
                'checks':'Original completed worker result and invocation; one exact active received inquiry, full project '
                    'scope, buyer/payer, product, quantity, requirements and delivery correspondence to independent order terms. '
                    'Proposal and final confirmation reuse the actual deciding A01/A02/A03 identity and current sources. '
                    'No later stage or A04 acceptance/rejection is fabricated.',
                'feedback_reader':'integration.supplier_order_native_feedback:prior_supply_decisions',
                'observed':'Three independent two-tick native scenarios execute original A01, A02 or A03 refusal; '
                    'native Contractor selects B, then A accepts the next project. All four later original Supplier '
                    'stages resolve observed Evidence bound to the earlier actual own decline, proposal/final and micro result. '
                    'This is willingness history, not a selected order or capacity/cash commitment.',
                'evidence':'output/integration/implementation_20261016_28/checks.json',
                'limits':'The original evidence used explicit synthetic sources and native Contractor selection. '
                    'The newer native_decline_policy_feedback composition also verifies original micro Contractor A05. Clarification, partial scope, deferred, '
                    'unresolved and mismatched demands stop for review. Shared eight-role negative scenarios and '
                    'detailed fulfillment remain pending; no full-action or formal-source acceptance claimed.',
            }} if action_id in {'SUPPLIER-A01','SUPPLIER-A02','SUPPLIER-A03'} else {}),
            'native_contract': contract.model_dump(mode='json') if contract else None,
            'native_execution': ('gba_construction_sim/backend/simulation/simulation_engine.py:_rank_owner_project_decisions/_maybe_generate_projects'
                if action_id in {'OWN-A01','OWN-A02','OWN-A03','OWN-A16'} else 'gba_construction_sim/backend/simulation/agent_operation_scheduler.py:step'
                if action_id=='GOV-A12' else 'gba_construction_sim/backend/simulation/project_lifecycle_engine.py'),
            'result_source': 'Original core state/events only for formal facts; audited micro output for internal products',
            'next_consumer': 'Original bounded decision then own-result feedback' if contract else
                             'Role workflow/handoff; concrete consumer pending',
            **({'native_interest_predecessor':{
                'implementation':'integration.professional_opportunity_native:ProfessionalOpportunityStep',
                'application':'integration.professional_intake_native:ProfessionalIntakeApplication',
                'option':'--with-opportunity; shared: --with-professional-opportunity',
                'status':'actual_original_interest_intake_owner_selection_and_private_confirmation_partial',
                'evidence':'output/integration/development_professional_opportunity_checks_20261016_07/test_actual_interest_precedes_0/runtime/professional-opportunity.json',
                'negative_evidence':'output/integration/development_professional_opportunity_checks_20261016_07/test_actual_interest_precedes_1/runtime/professional-opportunity.json',
                'non_interest_continuation':{
                    'policy':'ProfessionalOpportunityPlan.non_interest_policy=decline_new_work; default require_resolution',
                    'option':'--decline-after-no-interest with --with-opportunity; shared --with-professional-opportunity',
                    'source_option':'--without-interest; shared --without-professional-interest',
                    'semantics':'Original completed Architect/QS ignore or Engineer decline is private evidence for '
                        'the original A02 FeeBasis.new_work_policy=decline evaluation. Only that independent A02 '
                        'result is returned through the original native decline proposal and final decision. '
                        'Other unresolved or incomplete A01 results remain unresolved.',
                    'status':'architect_qs_native_declines_verified_engineer_and_shared_pending',
                    'evidence':'output/integration/professional_no_interest_checks_20261017_01/test_actual_interest_precedes_0/runtime/professional-opportunity.json',
                    'observed':'Two native ticks, six original Architect/QS A01/A02 chains, four OWN-A04, '
                        '16 micro actions and 56 formed technical tasks; six actual negative appointment_decision '
                        'events and no appointed team. Both projects actually suspend. Engineer is not triggered '
                        'because no Architect is appointed. Later consumption of negative native outcomes remains pending.'},
                'shared_evidence':'output/integration/development_shared_professional_opportunity_20261016_01/runtime-native/professional-opportunity.json',
                'semantics':'Within the actual current consider_appointment request, use the original Architect/Engineer '
                    'opportunity or QS market assembler and worker. The exact saved express_interest and actual native '
                    'request observation become private Evidence required by the original A02. A02 independently '
                    'checks service acceptance; original OWN-A04 and the core select professionals, then original A03 '
                    'authenticates and carries the same own interest evidence. No interest message, fee or reservation '
                    'is created, and private interest Evidence is not disclosed to the Owner.',
                'observed':'Two native ticks, eight original A01/A02 chains, six OWN-A04 and five A03, 27 micro actions '
                    'and 75 formed technical tasks. Two actual teams; later Engineer A02 consumes earlier own '
                    'appointment and declines. Disabled interest permission preserves one original Architect ignore '
                    'without A02 or native team appointment. New positive/negative and existing default cases pass.',
                'shared_observed':'Three native ticks, eight actual micro roles, 93 original micro actions, 269 formed '
                    'technical tasks and eight original interest/intake chains in one authority/registry/store. '
                    'Actual financing, professional teams, regulator/supply and tender feedback routes continue.',
                'limits':'By default only express_interest advances to A02. With explicit decline_new_work policy, '
                    'original ignore/decline advances to independent A02 decline evaluation; A01 itself never becomes '
                    'native acceptance or rejection. Other A01 branches stop with their saved state. Explicit synthetic professional '
                    'sources and policy; other preparation, research, service execution and full-action acceptance pending.',
            }} if action_id in {role+'-'+stage for role in ('ARCHITECT','ENGINEER','QS') for stage in ('A01','A02')} else {}),
            **({'native_clarification_request':{
                'implementation':'integration.bindings.gba_v1_tender_clarification:publish_clarification_request',
                'query':'ContractorTenderApplication.query_clarification_request(original_request)',
                'option':'--with-clarification-request; shared: --with-tender-clarification-request',
                'status':'actual_question_optional_qs_response_and_same_call_successor_available',
                'evidence':'output/integration/development_native_clarification_checks_20261016_02/test_original_clarification_qu0/runtime/clarification-question.json',
                'unknown_send_evidence':'output/integration/development_native_clarification_checks_20261016_02/test_original_clarification_qu1/runtime/clarification-question.json',
                'semantics':'Preserve the original completed A01 clarify output and exact requirement descriptions. '
                    'Within the original still-waiting native request, authenticate the existing project session, '
                    'opening event, participants and currently selected QS. Persist intent before using the original '
                    'InteractionSessionManager.append_message. Repeated sends only query the exact own message; '
                    'unknown sends never auto-repeat. Match the actual session message to its native bus publication. '
                    'Opening messages and questions are not answers, revisions, bid/decline decisions or formal receipts.',
                'observed':'Normal and post-send journal-interruption scenarios each retain one original A01 clarify, '
                    'one native question to the actual QS and twelve technical tasks; no A02, bid or decline. '
                    'After native step rollback, the actual message remains queryable with request tick 2 and '
                    'macro current tick 1 reported separately. Querying changes no messages, events or tasks.',
                'limits':'This question-only evidence does not include a QS answer. Optional original QS-A05 '
                    'response, explicit same-call successor and saved-result recovery are recorded separately below. '
                    'Missing-stage continuation and process restart remain pending.',
            }} if action_id=='CONTRACTOR-A01' else {}),
            **({'native_clarification_response':{
                'implementation':'integration.contractor_tender_clarification_response:respond_to_clarification',
                'query':'ContractorTenderApplication.query_clarification_response(original_request)',
                'option':'--with-clarification-response; shared: --with-tender-clarification-response',
                'status':'actual_original_qs_publication_and_native_reply_partial',
                'private_review_query': 'ContractorTenderApplication.query_clarification_review(original_request)',
                'private_review_evidence': 'output/integration/tender_clarification_review_20261017_01/checks.json',
                'private_review_semantics': 'Read the original QS result, identity, current authority, actual question and exact finalized task conditions. A completed request_publication still leaves the business request waiting_input; deferred/needs_information/unsupported retain their original worker conditions. This private host query publishes no document or native response and executes no successor.',
                'private_review_observed': 'Actual request_publication and deferred reviews retain explicit trigger waits and send no answer or bid/decline. Authorized native answers and exact query after interrupted native send remain compatible; the existing three-tick amended-package bid and later-feedback chain also passes.',
                'private_review_limits': 'Original synchronous native request stops unresolved. No automatic grant, source revision, missing-stage retry, in-tick restart or unauthorized disclosure. New host/trigger versions require unchanged-source recovery; old history is not migrated.',

                'evidence_directory':'output/integration/development_native_clarification_combined_checks_20261016_01',
                'shared_evidence':'output/integration/development_shared_clarification_response_20261016_01/runtime-native/clarification-response.json',
                'shared_observed':'Eight-role configuration, shared authority/registry/store; 59 original micro actions '
                    'in six roles and 142 technical tasks before original unresolved clarification stops the native call. '
                    'The actual QS reply is queryable; no tender bid or decline is fabricated.',
                'semantics':'After the original native Contractor question is actually observed, run the original '
                    'QS-A05 assembler/worker in the same shared registry and durable task store. Bind the actual '
                    'question digest as observed Evidence read by the processor. Only a finalized publish_authorized '
                    'decision can release the original quantity schedule and measurement rule to the actual asking '
                    'Contractor through the existing native session. Independent initial sources and publication '
                    'grants remain explicit synthetic assumptions, not invented runtime approval receipts.',
                'unknown_reply':'Save technical send intent before original append_message. An interruption after '
                    'actual native publication permits exact own-message query only, with no action replay or resend.',
                'negative':'An actual original request_publication decision when permission is false sends no reply.',
                'limits':'The published answer does not revise a package, clear the original A01 requirement, '
                    'prove recipient consumption or submit a bid. The optional normal continuation below '
                    'has separate version/action/native evidence and saved-result recovery below. '
                    'Missing-stage continuation and process restart remain pending.',
            }} if action_id in {'CONTRACTOR-A01','QS-A05'} else {}),
            **({'native_payment_delay_tender_feedback': {
                'reader': 'integration.bindings.gba_v1_progress_payments:with_own_progress_payment_history',
                'input': 'integration.contractor_tender_request_sources:TenderScreeningFeedbackPolicy.decline_after_prior_payment_delays',
                'enable': 'Independent --feedback-followup --decline-after-prior-payment-delays N; shared --with-tender-feedback --tender-decline-after-prior-payment-delays N. Default disabled.',
                'shared_identity': '--tender-contractor-ids can reuse finance-contractor with one of the existing supported tender Contractors. Author exact original native capacity totals before source/configuration digests; current occupancy remains an actual read. No grant, result or native source validator is bypassed.',
                'evidence': 'output/integration/contractor_payment_delay_feedback_20261017_01/checks.json',
                'observed': 'Actual original payment delay at tick 2 is read by that Contractor at tick 3; original A01 declines new work and original A02 forms native bid_declined. A second Contractor has no own delay, participates and forms native bid_submitted. The original A10 payment review still needs complete current original payment history.',
                'source_guards': 'Bind original own current native request/context, query original dual logs, count strictly earlier distinct delayed requests with their exact request once; saved original A01 must read the derived profile/evidence and reproduce current history before recording consumption.',
                'limits': 'Independent initial construction/contract and tender commercial sources. Aggregate delay changes private new-work preference only, not detailed payment history, independent QS certification, debt/cash, dispute resolution or a new project completing its whole lifecycle. New-option restart/model combinations remain pending.',
            }} if action_id in {'CONTRACTOR-A01', 'CONTRACTOR-A10'} else {}),
            **({'native_final_account_tender_feedback': {
                'reader': 'integration.bindings.gba_v1_final_accounts:with_own_final_account_history',
                'existing_query': 'read_own_final_accounts; exact original Contractor named party, current writer guard, strictly earlier events and dual native logs',
                'consumer': 'Original A01 reads a derived private policy and Evidence; original A02 independently forms the bid/decline returned through original native propose/decide.',
                'options': '--feedback-followup --decline-after-prior-final-accounts N',
                'shared_options': '--with-contractor-tender --with-tender-feedback --tender-decline-after-prior-final-accounts N; optional initial --final-account-contractor-id',
                'status': 'actual_shared_native_settlement_and_later_original_screening_consumption',
                'continued_bid_option': '--feedback-followup --allow-followup-bids; shared: --with-tender-feedback --allow-tender-followup-bids',
                'continued_bid_source': 'Declare separate original submit/decline pricing references, unique read tokens and quantity source snapshots before registration. Original A01 selects one original pipeline; no runtime source/choice rewriting or failed-source fallback.',
                'continued_bid_evidence': 'output/integration/contractor_followup_bid_20261017_01/checks.json',
                'continued_bid_observed': 'Actual native review at 1, settlement at 2, later own A01 at 3: A declines and original A02 produces native bid_declined; B has no own settlement, participates, and original A02 produces native bid_submitted. Exactly one later original A02 per organization with its explicitly selected pricing/context.',
                'continued_bid_limits': 'Default remains decline-only. Explicit independent synthetic tender sources; no award, signature, work release, cash, debt clearance, real-model or restart proof for this option.',

                'observed': 'Three native ticks, 42 original micro results and 190 formed tasks. Actual own review at 1 and aggregate settlement at 2 enter A01 at 3: A has one own settlement and declines; B has none and participates. Both independently declared A02 commercial policies decline and native bid_declined events retain their original result hashes.',
                'evidence': 'output/integration/contractor_settlement_feedback_20261017_01/checks.json',
                'limits': 'Eight roles configured; five roles actually execute in this case. Explicit initial closeout project and synthetic detailed commercial sources. No complete new-project lifecycle, cash, debt clearance, profit, resource release, unknown receipt or restart proof for this policy. Existing submission/evaluation/decline limits remain separate; this scenario disables submission-count triggering.',
            }} if action_id in {'CONTRACTOR-A01', 'CONTRACTOR-A02'} else {}),
            **({'native_decline_feedback': {
                'implementation': 'integration.contractor_tender_snapshot_sources:derive_screening_feedback_profile',
                'request_wiring': 'integration.contractor_tender_request_sources:build_request_work',
                'commercial_decline': 'integration.contractor_bid_pipeline:GbaContractorBidPipeline.prepare_decline',
                'options': '--initial-screening-policies JSON; --feedback-followup --decline-after-prior-declines N',
                'shared_options': '--tender-initial-screening-policies JSON; --with-tender-feedback --tender-decline-after-prior-declines N',
                'source_semantics': 'Initial policies apply to the first project before sealing. Later base profiles retain participate_if_eligible. An explicit positive decline threshold uses strictly earlier own native_bid_declined outcomes; submission-count triggering may explicitly be null when another positive limit is supplied. No all-null or boolean limits.',
                'business_semantics': 'Original A01 participation is intent only. A separately sourced original A02 commercial refusal may follow participate or decline; unresolved and clarify results cannot produce that refusal. Source-production errors never choose the refusal path.',
                'observed': 'An actual three-tick native run retains four original QS clarification/versioned-screening chains, one bid submission, three declines, and two later own-feedback consumers. A later base participation policy changes to decline for the firm with an actual earlier refusal; the submitted-only firm retains participation and independently declines at A02.',
                'evidence': 'output/integration/tender_decline_feedback_checks_20261017_01/checks.json',
                'limits': 'Explicit synthetic initial commercial sources. Not withdrawal, disqualification, award, loss, contract or cash. Current-source entry rejects a historical snapshot after native state changes; query the exact original receipt. Shared-host configuration is wired, with shared and checkpoint business combinations pending concentrated integration.',
            }} if action_id in {'CONTRACTOR-A01', 'CONTRACTOR-A02'} else {}),
            **({'clarification_continuation':{
                'implementation':'integration.contractor_tender_clarification_continuation:publish_response_consumption',
                'source_recheck':'integration.contractor_tender_clarification_continuation:response_consumption',
                'handoff_recheck':'integration.contractor_tender_clarification_continuation:effective_screening',
                'option':'--continue-clarification; shared: --continue-tender-clarification',
                'status':'actual_normal_same_call_versioned_screening_bid_and_later_feedback',
                'evidence':'output/integration/development_native_clarification_continuation_checks_20261016_04/test_actual_clarification_repl0/runtime/clarification-continuation.json',
                'negative_evidence':'output/integration/development_native_clarification_continuation_checks_20261016_04/test_actual_clarification_repl1/runtime/clarification-continuation.json',
                'shared_evidence':'output/integration/development_shared_clarification_continuation_20261016_01/runtime-native/clarification-continuation.json',
                'shared_observed':'Three original native ticks, eight actual micro roles, 93 micro actions and '
                    '269 technical tasks. Four original clarification/QS/successor chains retain version 1 '
                    'history, use version 2 in the handoff and yield two actual bids and two later own-feedback declines.',
                'semantics':'Original completed A01 clarify and package version 1 remain immutable. Only the exact '
                    'actual authorized QS quantity response makes the declared version 2 source readable. '
                    'The revision preserves all other original tender terms and resource definitions, records '
                    'response Evidence read by a new original A01 task, and passes that exact saved successor '
                    'to the original A02 handoff/pipeline. Native proposal/final execution still belongs to the core.',
                'observed':'Three original ticks, sixteen original micro actions, fifty-two technical tasks, '
                    'two actual native submissions followed by two actual native declines driven by strictly '
                    'earlier own submission feedback. Denied publication has no successor and no bid/decline.',
                'saved_result_recovery':{
                    'implementation':'integration.contractor_tender_saved_recovery:recover_request_work',
                    'option':'--allow-saved-recovery --query-saved-tender-on-error; shared: '
                        '--allow-tender-saved-recovery --query-saved-tender-on-error',
                    'evidence_directory':'output/integration/development_clarification_saved_recovery_checks_20261016_02',
                    'shared_evidence':'output/integration/development_shared_clarification_recovery_20261016_01/runtime-native/clarification-recovery.json',
                    'shared_observed':'Actual same-call saved A02 recovery after the original clarification chain '
                        'in one shared authority/registry/store. Three native ticks, eight micro roles, 93 original '
                        'micro actions and 269 formed technical tasks; two actual bids and two later own-feedback '
                        'declines. Original saved result remains byte-equivalent; duplicate/unknown requests '
                        'change neither tasks nor native events.',
                    'observed':'Original A02 technical finalization interrupts after its result is saved. '
                        'The same native call authenticates the saved original clarify, actual authorized QS reply, '
                        'consumed package-version evidence, formed successor and saved A02, then returns the '
                        'original result without processor/method/model replay. Three native ticks retain two '
                        'actual bids and two later own-feedback declines. Disabled recovery and a missing A02 '
                        'result retain the original error and no native bid or decline for the interrupted actor.',
                    'limits':'A missing result, an unformed successor or an unknown actual reply stays unresolved. '
                        'This does not execute missing stages, resume the engine or recover a different process.',
                },
                'limits':'Explicit synthetic professional sources and private policy. Micro versioning does not '
                    'assert a separate formal macro tender-amendment operation. Other question kinds, amendments '
                    'to commercial terms, missing-stage continuation, process restart and full-action acceptance pending.',
            }} if action_id in {'CONTRACTOR-A01','CONTRACTOR-A02','QS-A05'} else {}),
            **({'existing_bridge': {
                'implementation':'integration.contractor_tender_host:GbaContractorTenderHost',
                'input_producer':'integration.contractor_tender_request_sources:build_request_work',
                'native_proposal':'integration.bindings.gba_v1_tender_proposal:GbaTenderProposalAdapter',
                'source_option':'integration.contractor_tender_development --feedback-followup',
                'saved_result_recovery':{
                    'implementation':'integration.contractor_tender_saved_recovery:recover_request_work',
                    'authorization':'--allow-saved-recovery',
                    'same_call_option':'--query-saved-tender-on-error',
                    'semantics':'The original trigger persists A01/A02 identities before execution. Query both original '
                        'durable completed results, invocation snapshots, seven versions, current sources/rights and audit '
                        'before reconciling technical tasks. Restore the exact original selected proposal without running '
                        'primary source production, methods, processors or models again. A declared clarification '
                        'chain additionally authenticates its actual QS reply, consumed source evidence and formed '
                        'original successor. Missing results remain unresolved.',
                },
                'unstarted_action_continuation':{
                    'implementation':'integration.contractor_tender_request_trigger:ContractorTenderRequestTrigger._execute_stage',
                    'worker_proof':'integration.contractor_bid_results:ContractorBidResultWorker.unstarted_evidence',
                    'option':'--continue-unstarted-actions-on-error; shared: --continue-unstarted-tender-actions-on-error',
                    'default_enabled':False,
                    'evidence':'output/integration/development_unstarted_tender_checks_20261016_02/test_native_tender_continues_o0/runtime/unstarted-tender-continuation.json',
                    'semantics':'Within the same still-open native call, a failed action may continue once only when '
                        'its original task/snapshot and atomically registered execution claim prove preparation has '
                        'never started. Reuse the exact prepared input and seven versions, revalidate actual current '
                        'sources/authority, then claim preparation durably before any preparation callback. Do not '
                        'repeat source production, prior actions, model work or formal requests. Claims survive '
                        'journal reopen; registration never manufactures proof for legacy tasks. Prepared but '
                        'missing results, processing, waits, failures and unknown outcomes remain unresolved.',
                    'observed':'One controlled interruption before the original A02 claim continues within the '
                        'original request. Three ticks produce two actual bids and two later declines via original '
                        'A01/A02 feedback consumption, eight micro actions, one original audit for the interrupted '
                        'action. Disabled mode and interruption after preparation do not continue missing work.',
                },
                'submission_query':{
                    'entry':'GbaContractorTenderHost.query_submission(original_request)',
                    'implementation':'integration.bindings.gba_v1_tender_query:query_tender_submission',
                    'prior_query':'integration.bindings.gba_v1_tender_query:query_prior_tender_submissions',
                    'prior_query_option':'--feedback-followup --query-prior-submissions; shared: --with-tender-feedback --query-prior-tender-submissions',
                    'missing_notice_evidence':'output/integration/development_shared_tender_missing_notice_checks_20261016_02/test_shared_original_tender_qu0/runtime/shared-missing-notice.json',
                    'missing_notice_observed':'Two actual native submissions, four lost delivery attempts for those '
                        'two events; each later original A01/A02 queries its own strictly earlier effect and '
                        'declines new work. Three native ticks, eight roles, 85 original micro actions, 261 '
                        'formed tasks; missing notices remain absent from the inbox and repeat queries '
                        'change neither native events nor technical tasks.',
                    'missing_notice_semantics':'Default off. Before a later original A01 reads feedback, query only its '
                        'own strictly earlier original claims, optionally the same project. Authenticate original '
                        'proposal/final/event correlation and persist private query evidence; do not deliver a '
                        'synthetic observation or resubmit a native request. Unknown prior outcomes stop the '
                        'current work without assuming absence of submission or substituting a business decline.',
                    'semantics':'Query the existing original proposal identity and actual own global bid_submitted or '
                        'bid_declined event. Validate its original proposal/final correlation and retain private evidence. '
                        'No actual terminal event means outcome_unknown; a decision alone is not proof of submission. '
                        'No new macro request, action execution, formal task receipt, native submission or engine restart.',
                },
                'original_source_history':{
                    'writer':'integration.contractor_bid_source_history:save_bid_source_history',
                    'reader':'GbaContractorTenderHost.query_source_history(original_request, identity, current_context=...)',
                    'evidence':'output/integration/bid_source_history_20261017_01/checks.json',
                    'semantics':'Retain the existing runner actual A02 audit witness atomically with its original '
                        'result. Query own exact native proposal/input/audit/result/event correlation using current '
                        'Contractor authority and actual business time. Never rebuild a historical tender from '
                        'the changed current project or replay the original action.',
                    'observed':'Two actual native submissions remain source-queryable after the project enters '
                        'bid_evaluation; technical tasks and native events are unchanged. Original result commit '
                        'interruption/reopen, later own A04-authorized private read, revocation, tamper, missing '
                        'legacy witness and atomic write failure checks are covered separately.',
                    'limits':'This produces private source history and independently queried native bid evidence. '
                        'It does not execute A04, create a detailed submission/agreement receipt, sign the newly '
                        'tendered project, reserve resources or change cash. Legacy witnesses are not reconstructed.'},
                'limits':'Synthetic professional sources remain explicit. Whole-process restart, missing stages '
                    'without unstarted proof and shared-host fault execution still need continuation/verification; '
                    'the external preferred-bidder field conflict remains scoped to that transport; the separately '
                    'declared original native Owner selection path is available.',
            }} if action_id=='CONTRACTOR-A02' else {}),
            **({'internal_preparation': {
                'implementation':'integration.owner_opportunity_native:OwnerOpportunityApplication',
                'input_producer':'integration.owner_opportunity_observation:prepare_observation_sources',
                'result_consumer':'integration.owner_opportunity_observation:attach_observation',
                'source_option':'--with-observation / --with-owner-observation',
                'native_semantics':'The current native opportunity request optionally executes original OWN-A01 before '
                    'OWN-A03. Current global market demand, candidate region/use and independent management inputs '
                    'produce an actual original result. A03 reads the exact private follow result/source/audit relation; '
                    'an exact original ignore returns native defer_project without executing A03. The deciding stage '
                    'remains A01 in proposal, bounded confirmation and actual native non-initiation feedback.',
                'decline_history_reader':'integration.owner_opportunity_decline_feedback:prior_owner_declines',
                'limits':'Follow and ignore are connected; clarify, unresolved and other results stop for review. '
                    'The global index is not a regional survey or forecast. Observation does not create a formal '
                    'case/project, right, resource reservation or financial fact. Optional A16 private drafts are '
                    'recorded separately below. Optional A02 follows actual A03 study_more as bounded authorization; research/report production remains pending.',
            }} if action_id=='OWN-A01' else {}),
            **({'native_private_proposal': {
                'implementation':'integration.owner_opportunity_proposal:prepare_proposal_sources',
                'consumer':'integration.owner_opportunity_proposal:attach_proposal',
                'application':'integration.owner_opportunity_native:OwnerOpportunityApplication',
                'source_option':'--with-observation --with-proposal; shared: --with-owner-opportunity --with-owner-observation --with-owner-proposal',
                'semantics':'After original A01 follow, original A16 evaluates finite independently supplied candidates '
                    'with the actual current global demand index, same private cash, protected unpaid obligations and '
                    'original management commitments. Only actual saved briefs replace A03 demand briefs. Handoff '
                    'authenticates exact original request, invocation, completed result, source reading and current grants; '
                    'the declared non-build comparison baseline is retained. No draft creates formal state.',
                'bounded_outcomes':'Complete propose advances to original A03. Original no_proposal returns native '
                    'defer_project without A03; actual native non-initiation events are consumed by later own actions. '
                    'Partial propose preserves its saved result and waits for complete comparison inputs. Revise and '
                    'other unverified results remain review cases; no template fills missing output.',
                'standalone_evidence':'output/integration/development_owner_proposal_checks_20261016_03/test_original_private_proposal0/runtime/proposal-loop.json',
                'bounded_evidence_directory':'output/integration/development_owner_proposal_checks_20261016_05',
                'shared_evidence':'output/integration/development_shared_owner_proposal_20261016_01/runtime/result.json',
                'shared_observed':'Three native ticks, eight actual micro roles, 107 original micro actions and 283 '
                    'formed technical tasks in one authority/registry/store. Eight original A16 results feed exact A03 '
                    'briefs. Two actual projects enter design; four later opportunity requests consume the earlier own '
                    'creation, while financing, professional interest/intake/confirmation, regulatory, supply and '
                    'original tender/feedback routes continue. This is one explicit synthetic business configuration.',
                'limits':'Candidate hypotheses, rights, scale-method bounds and review estimates are explicit synthetic '
                    'initial sources. A01 follow, A16 briefs and native budget do not acquire rights or produce research, '
                    'professional analyses, external appointment, spending or resource reservations. OWN-A02 remains '
                    'a separate research-authorization step, connected as an optional A03 study_more successor below. Other branches, professional research/production, '
                    'missing-stage continuation and full-action acceptance remain pending.',
            }} if action_id in {'OWN-A01','OWN-A16','OWN-A03'} else {}),
            **({'native_preparation_feedback': {
                'implementation':'integration.owner_opportunity_preparation:preparation_origin',
                'history_reader':'integration.owner_opportunity_decline_feedback:prior_owner_declines',
                'application':'integration.owner_opportunity_native:OwnerOpportunityApplication',
                'source_option':'--initial-investment-policy prepare_only; shared: '
                    '--with-owner-opportunity --owner-initial-investment-policy prepare_only',
                'semantics':'Original OWN-A03 authorize_preparation returns the existing defer_project proposal. '
                    'Only actual native non-initiation events enter later original A01/A16/A03 evidence. '
                    'The exact stored original option, preparation plan, scope, conditions, expenditure cap and '
                    'proposed cash/resource uses are authenticated against the saved invocation and current grants.',
                'evidence':'output/integration/owner_preparation_checks_20261017_02/checks.json',
                'observed':'Two actual two-tick cases cover continuing preparation and stopping new opportunities '
                    'after one actual native deferral. Each has eight private candidate results but only two '
                    'native deferral events; four later candidate workflows consume the one earlier actual origin. '
                    'A rehashed substituted plan and revoked original authority are rejected; original results remain.',
                'limits':'Preparation authorization is private intention, not completed research, expenditure, '
                    'resource reservation or project registration. Existing max_prior_declines counts native '
                    'non-initiation events and retains the original micro choice. Shared eight-role inputs '
                    'are sealed and checked only; shared business, other branches and full regression remain pending.',
            }} if action_id in {'OWN-A01','OWN-A16','OWN-A03'} else {}),
            **({'native_saved_recovery': {
                'implementation':'integration.owner_opportunity_native_recovery:recover_saved_opportunity_proposal',
                'application':'integration.owner_opportunity_native:OwnerOpportunityApplication',
                'source_option':'--allow-saved-recovery --query-saved-opportunity-on-error; '
                    'shared: --with-owner-opportunity --allow-owner-opportunity-saved-recovery --query-saved-opportunity-on-error',
                'semantics':'Default-off saved-result query in the same still-open original native opportunity call. '
                    'Preflight requires completed saved results for the entire required A01/A16/A03/optional A02 chain. '
                    'Original identity, invocation, versions, current reading/authority and audit are revalidated; '
                    'only technical finalization and the original response are restored. No processor/model replay.',
                'evidence':'output/integration/implementation_20261016_46/checks.json',
                'observed':'Four native fault cases cover A03 investment, A02 study authorization, A01 ignore '
                    'and A16 no_proposal, with later actual own feedback consumption. Missing result, disabled '
                    'query and missing successor stages retain the original exception.',
                'limits':'No unstarted-stage execution, business resubmission, cross-process restoration or macro '
                    'engine restart. Shared eight-role configuration is assembled only; shared fault business '
                    'and whole regression remain pending. This does not upgrade whole-action coverage.',
            }} if action_id in {'OWN-A01','OWN-A02','OWN-A03','OWN-A16'} else {}),
            **({'native_study_followup': {
                'implementation':'integration.owner_opportunity_study:prepare_study_sources',
                'application':'integration.owner_opportunity_native:OwnerOpportunityApplication',
                'result_check':'integration.owner_opportunity_study:study_origin',
                'history_check':'integration.owner_opportunity_study:prior_study_authorization',
                'source_option':'--study-question-code [--study-target-intervention <intervention> ...]; '
                    'shared: --with-owner-opportunity --owner-study-question-code '
                    '[--owner-study-target-intervention <intervention> ...]',
                'semantics':'An explicitly declared unresolved whole-comparison or targeted-option question is evaluated by the original '
                    'A03 study_more branch. Its saved result, source reading, original issue and invocation feed original '
                    'A02 in the same authority/registry/store. A02 applies original resource-capacity and limited-budget '
                    'methods to the same current private cash and original management pool, protecting unpaid obligations. '
                    'Only completed internal_study/commission/stop authorizations permit the original A03 native defer confirmation. '
                    'The original A03 remains the deciding identity; neither result executes research or resolves the issue.',
                'feedback':'Only actual earlier own native project_opportunity_declined events count as outcomes. '
                    'Their linked original A03 followup and saved A02 authorization are authenticated and consumed by '
                    'later own actions without converting proposed study allocations into occupied resources or fees.',
                'evidence_directory':'output/integration/development_owner_study_checks_20261016_01',
                'standing_service_offer': {
                    'implementation': 'integration.owner_study_service_offer:prepare_study_service_offer',
                    'input_contract': 'integration.owner_study_service_offer:OwnerStudyServiceOfferPolicy',
                    'application_version': 'gba-v1-owner-opportunity.v14',
                    'source_option': '--study-service-offer JSON; shared: --owner-study-service-offer JSON',
                    'source_requirement': 'Explicit independent_initial_standing_offer, original QS/Architect '
                        'provider and scoped initial mandate, exact unresolved question/work/window, HKD fee, '
                        'qualification, research permission and supported questions. Unknown values remain unknown.',
                    'private_decision': 'Original OWN-A02 commission compares the declared fee, private cap and '
                        'same actual cash after original restricted cash and protected unpaid obligations. '
                        'A completed private authorization permits original A03/native defer; later own '
                        'non-initiation history authenticates the original offer and private decision.',
                    'authority': 'Original organization registry supplies distinct institution/actor/function. '
                        'The offer-author scoped grant does not grant access to owner funding or resources.',
                    'evidence': 'output/integration/owner_study_commission_20261017_01/manifest.json',
                    'limits': 'Assumed initial standing offer, not an executed professional A02 or received '
                        'message. No executed appointment, contract, research, report, spending, resources '
                        'reservation or original active StudyPlan. Narrow, actual professional offer '
                        'production/reception, shared runtime and saved-recovery combinations remain separate.',
                },
                'original_professional_intake': {
                    'implementation': 'integration.owner_study_professional_intake:OwnerStudyProfessionalIntakeStep',
                    'input_contract': 'integration.owner_study_professional_intake:OwnerStudyProfessionalIntakePolicy',
                    'application_version': 'gba-v1-owner-opportunity.v15',
                    'source_option': '--study-professional-intake JSON; shared: --owner-study-professional-intake JSON',
                    'producer': 'Current original OWN-A03 study_more supplies its exact unresolved assessment '
                        'question/work to original QS-A02 or ARCHITECT-A02. Independent initial disclosures '
                        'supply qualifications, permission, fee/minimum, risk, physical regional resources, '
                        'fixed original commitment windows, effort conversion and QS conflict status.',
                    'consumer': 'Original professional worker stores its actual decision and snapshot in '
                        'the shared journal. A recipient-scoped typed handoff exports exact accepted terms '
                        'and observed original-result evidence to OWN-A02; decline exports a withdrawn '
                        'offer. Owner independently decides commission/stop and original native defer '
                        'remains attributed to OWN-A03. Later own history checks both original workers '
                        'and their actual current grants without changing past sources/time/results.',
                    'privacy': 'Professional source view excludes owner funding, debt and management load; '
                        'owner handoff excludes provider pricing rules, capacity and private calendar.',
                    'evidence': 'output/integration/owner_study_actual_intake_20261017_01/manifest.json',
                    'limits': 'Initial qualifications, pricing and physical resources remain explicit '
                        'independent assumptions. The micro request/result handoff is not an external '
                        'native message receipt, appointment, contract, research report, cost, reservation '
                        'or cash transaction. Counteroffers/questions, shared actual runtime, model '
                        'and saved/process recovery combinations require their own sources and verification.',
                },
                'targeted_scope':{
                    'implementation':'integration.owner_opportunity_study:declared_study_scope',
                    'evidence':'output/integration/implementation_20261016_47/checks.json',
                    'semantics':'Explicit intervention selectors resolve only original compared ProjectOptions and '
                        'their existing WorkScopes. Original A03 checks candidate permission, registered issue and '
                        'exact option/work coverage. A02 retains those work references and their original validity '
                        'under a narrower grant; no synthetic whole-case replacement or formal task is created. '
                        'The same bounded scope, work-source digests and target options survive later own actual '
                        'non-initiation feedback. Absent interventions/work stop rather than broaden the question.',
                    'observed':'A targeted new_build case completes two ticks, 32 original actions and 84 formed '
                        'technical tasks. Each A03 targets one original option and two original work scopes, with '
                        'non-build comparison retained. Four later requests consume the earlier exact authorization.',
                },
                'observed':'Separate allowed-budget and over-budget scenarios each complete two native ticks, 32 '
                    'original actions, 84 formed technical tasks and two actual non-initiation events. Eight A03 '
                    'followups invoke A02; four later requests read the earlier own outcome and private authorization. '
                    'No project or research report is created. Original default investment/feedback remains verified.',
                'limits':'Question code, staff qualification/support, cost, cap and planned window are explicit '
                    'synthetic initial assumptions. No formal study task, service order, spending, rights, reservation '
                    'or report is manufactured. One whole-comparison or jointly targeted issue and internal_study/stop '
                    'are connected; selectors require matching original compared options. Optional commission '
                    'consumes a separately declared standing offer as described above. Narrow, '
                    'research execution/reports, other unresolved results, process '
                    'restart and shared business verification remain pending. Shared input assembly alone is not business acceptance.',
            }} if action_id in {'OWN-A02','OWN-A03'} else {}),
            **({'existing_bridge': {
                'implementation':'integration.owner_opportunity_native:OwnerOpportunityApplication',
                'input_producer':'integration.owner_opportunity_native_sources:prepare_opportunity_sources',
                'development_configuration':'integration.owner_opportunity_native_development:build_bundle',
                'scope':'integration.owner_opportunity_scope:owner_opportunity_scope',
                'actual_result_projection':'integration.owner_opportunity_native_feedback:project_owner_opportunity_event',
                'history_reader':'integration.owner_opportunity_native_feedback:prior_owner_initiations',
                'non_initiation_feedback':{
                    'reader':'integration.owner_opportunity_decline_feedback:prior_owner_declines',
                    'consumer':'integration.owner_opportunity_native_sources:prepare_opportunity_sources',
                    'source_option':'--max-prior-declines / --max-prior-opportunity-declines',
                    'semantics':'Strictly earlier own project_opportunity_declined events authenticated against '
                        'the live global collector, original A01 ignore, A16 no_proposal or A03 reject/preparation/study_more worker, source, '
                        'proposal and bounded confirmation. Later enabled A01/A16/A03 read the exact event history; an optional '
                        'count threshold pauses only private future initiation. Private candidate refusals are not events.',
                    'limits':'Default count preference off. Non-initiation is not project creation, expenditure, '
                        'cash, debt, resource reservation, formal preparation or an outstanding obligation.',
                },
                'progress_payment_feedback':{
                    'reader':'integration.bindings.gba_v1_progress_payments:read_own_progress_payments',
                    'consumer':'integration.owner_opportunity_native_sources:prepare_opportunity_sources',
                    'source_option':'--max-prior-payment-requests N [--with-payment-project]',
                    'evidence':'output/integration/development_owner_payment_feedback_20261016_02/runtime',
                    'semantics':'Strictly earlier own native payment_requested and correlated payment_delayed events; '
                        'authenticate live event collector, exact project log, actual parties and source hashes. '
                        'An explicit request-count threshold pauses only the private new-investment preference.',
                    'limits':'Default off. A request approved status is not cash execution, an independent QS '
                        'certificate, bank transfer, received payment or cleared debt. Delay is not counted twice. '
                        'No financial-capacity score or event amount is converted into a cash balance.',
                },
                'final_account_feedback': {
                    'reader': 'integration.bindings.gba_v1_final_accounts:read_own_final_accounts',
                    'consumer': 'integration.owner_opportunity_native_sources:prepare_opportunity_sources',
                    'source_option': '--max-prior-final-accounts N',
                    'semantics': 'Strictly earlier own actual native review/settlement events, matched to exact global/project '
                        'logs, original named parties, native amount units and source hashes. The explicit private count '
                        'preference pauses new initiation through the original OWN-A03 registration profile.',
                    'status': 'shared_synthetic_business_and_later_consumer_observed',
                    'shared_scenario': 'Shared --with-owner-opportunity --max-prior-final-accounts N '
                        '--with-final-account-discussion extends initial timing through tick 3. '
                        'Original generation occurs before lifecycle advancement; no same-tick settlement is consumed.',
                    'initial_professional_sources': '--professional-project-object-types explicitly declares PGEN0001/PGEN0002 '
                        'service terms, capability and method object types before sealing. Actual intake still requires an exact '
                        'project-type match; no runtime qualification expansion or source rewriting.',
                    'actual_runtime': 'output/integration/shared_final_account_feedback_checks_20261017_02/cases/test_shared_actual_final_accou0/checks.json',
                    'observed': 'Three ticks, eight actual micro roles, 83 completed original actions, 243 technical tasks. '
                        'Six closing communication actions complete; four later original OWN-A03 results read the exact prior '
                        'native settlement and return defer_project through original proposal/final confirmation. '
                        'Private cash/restricted-cash source values remain unchanged.',
                    'limits': 'Default off. No initial completed project, settlement event or formal private review is '
                        'manufactured. No available cash, received payment, cleared debt, handover or defect release is inferred.',
                },
                'supported_choices':['invest','reject','study_more'],
                'native_semantics':'Every actual opportunity request executes the original OWN-A03 assembler/worker and methods. '
                    'Original proposal contract always uses initiate_project with the exact selected_concept; accepted reflects the micro result. '
                    'The bounded final confirms initiate_project or defer_project against the same candidate summary, sources and result. '
                    'Only the native engine chooses among accepted opportunities and creates PGEN projects; an accepted candidate is not a created project.',
                'source_boundary':'Full opportunity content disambiguates same-tick candidates before formal project IDs exist. '
                    'Independent synthetic option analyses, financial disclosure, old debt, management load, qualifications and rights '
                    'are explicitly supplied. Scoped grant templates authorize private assessment views and are persisted before use. '
                    'Shared funding/debt physical identities and other-business origins remain stable; a forecast fits the native budget '
                    'and that budget fits the independently supplied expenditure authorization ceiling.',
                'feedback_consumer':'Strictly earlier own actual project_opportunity_initiated events are authenticated to the original '
                    'micro source/audit, invocation, observed Evidence, proposal, final and created project. Explicit max_prior_initiations '
                    'changes only the later private registration policy; it neither counts unselected accepted candidates nor creates cash/debt/reservations.',
                'limits':'Only original new-build invest and reject paths have actual integration evidence. Preparation is preserved as '
                    'a private result with native defer, without claiming formal preparation execution. Optional study_more consumes original A02 authorization and returns defer; revise/unresolved '
                    'results stop for diagnosis and continuation. Optional A01 follow is read as private evidence; '
                    'Optional A16 complete private briefs are consumed before A03; partial briefs stop for review. '
                    'A02 research execution/report production, professional analyses, other branches, '
                    'real source inputs and the remaining C3/C4 chain remain pending. Shared initial business and own native '
                    'payment-request feedback evidence are scoped in shared_assembly. No formal micro investment ledger is created.',
            }} if action_id=='OWN-A03' else {}),
            **({'existing_bridge': {
                'implementation':'integration.owner_commission_native:OwnerCommissionApplication',
                'input_producer':'integration.owner_commission_native_development:commission_plans',
                'enable':'integration.professional_intake_development --with-owner',
                'private_handoff':'integration.owner_commission_native_sources:commission_sources',
                'actual_result_projection':'integration.owner_commission_native_feedback:owner_commission_recipients',
                'history_reader':'integration.owner_commission_native_feedback:prior_owner_commissions',
                'supported_choices':['accept','reject_all'],
                'native_semantics':'Original A02 provider tasks, immutable source reads, original confirmations and actual '
                    'appointment_decision events authorize private received-offer views. Original OWN-A04 evaluates '
                    'exact fees, qualifications, service scope, management load and explicit preferences. Its proposal '
                    'and bounded final preserve the same result; only the native lifecycle appoints and engages providers.',
                'source_boundary':'Independent synthetic initial service, qualifications, payer/provider mandates and '
                    'complete management load are explicit inputs. Commercial terms and action-specific deliverable views '
                    'are checked against actual A02 sources, author and grant. Original read points are retained as native '
                    'acceptances append later events; current project ownership/region/type and original event-log prefixes '
                    'are validated. Provider pricing policies, private calendars and internal discussions are not projected.',
                'feedback_consumer':'Only the actual Owner receives its micro selection summary from consultant_team_appointed. '
                    'Later original OWN-A04 reads strictly earlier own same-role outcomes authenticated to original '
                    'micro sources/audit, invocation, proposal/final and native event. repeat_provider_priority_penalty '
                    'changes only private preferences, never qualifications, fees or resource balances.',
                'limits':'Default professional intake retains original native Owner selection. The opt-in micro path '
                    'currently supports accept and reject_all only; no formal retender, invite, clarification or internal '
                    'assignment is claimed. Native engagement is not detailed service-contract confirmation, a fee/payment '
                    'receipt or a physical management reservation. Professional A03, other branches, service execution '
                    'and recovery remain pending.',
            }} if action_id=='OWN-A04' else {}),
            **({'existing_bridge': {
                'implementation': 'integration.supplier_order_native:SupplierOrderNativeApplication',
                'input_producer': 'integration.supplier_order_native_development:build_bundle',
                'scope': 'integration.supplier_order_native_scope:supply_scope',
                'actual_result_projection': 'integration.supplier_order_native_feedback:project_supply_event',
                'history_reader': 'integration.supplier_order_native_feedback:prior_supply_selections',
                'supported_choices': ['accept', 'reject'],
                'native_semantics': 'Original A04 drafts and capacity method drive current native project supply willingness. '
                    'Final confirmation preserves the same result, proposal, current signed-project contractor and sources.',
                'source_snapshot': 'Freeze all declared authorized dependency versions before original worker registration, '
                    'including the actual native/history Evidence, commitment plan and independent counterpart acceptances.',
                'contractor_selection': 'Default explicit original ContractorAgent.select_supplier receives original AgentDecision '
                    'objects restored from JSON. Exact current supplier profiles, original events, utilities and confirmed '
                    'micro results are checked. Final transport preserves the same bounded native selection; no default CONTRACTOR-A05 coverage. '
                    'Optional --with-contractor installs exclusive original micro A05 and confirms the same bounded result.',
                'feedback_consumer': 'Optional explicit max_prior_selections authenticates strictly earlier own actual '
                    'selected-supplier events and original Supplier/Contractor confirmations. It changes only the private '
                    'A04 formation policy to reject_new_orders; the original processor makes the later rejection.',
                'optional_quote_preparation': 'SupplierOrderQuoteStep executes original A03 and its pricing/capacity '
                    'methods inside the same native request. Private quote_for_order checks every line and payment term '
                    'against the independent existing A04 agreement plus identical stock/capacity snapshots. '
                    'Actual quote task/result/source/audit hashes bind to authorized Evidence read by original A04. '
                    'No formal SupplyOffer publication or registration callback is synthesized.',
                'limits': 'Independent synthetic offer/proposal, preexisting buyer term acceptance, product, stock, cash, '
                    'capacity and comparison indicators. Initial acceptance is not a future native selection receipt. '
                    'Native project selection is not detailed SupplyOrder formation, stock reservation, payment or delivery. '
                    'Explicit complete-demand upstream declines now have their own original A01/A02/A03 identity. '
                    'Other screening/product/quote/order branches, real sources and C3 fulfillment remain pending.',
            }} if action_id == 'SUPPLIER-A04' else {}),
            **({'native_formation_outcome_query': {
                'contractor_endpoint': 'ContractorFormationNativeApplication.query_native_outcome(original_identity, organization_id=own_id, tick=current_tick)',
                'owner_endpoint': 'OwnerAwardNativeApplication.query_native_outcome(original_identity, organization_id=own_id, tick=current_tick)',
                'implementation': 'integration.formation_native_outcome_query',
                'evidence': 'output/integration/formation_outcome_query_20261017_01/manifest.json',
                'behavior': 'Reads the original Contractor A04 recommendation or Owner A10 contract decision. Reuses exact original worker result, invocation snapshot, source plan, proposal/final response and consistent project/global events. Missing native event remains unknown. Current authorization is rechecked without changing original business time. Default later-decision history remains strictly earlier; Contractor history now checks original current grants before private consumption.',
                'limits': 'Read-only original recommendation/decision, not subsequent signature, agreement registration, resource reservation or payment. No processor replay, task creation, feedback redelivery or resubmission. Other shared/checkpoint/model and old sealed-history migration combinations remain unverified.',
            }} if action_id in {'CONTRACTOR-A04','OWN-A10'} else {}),
            **({'native_supply_outcome_query': {
                'supplier_endpoint': 'SupplierOrderNativeApplication.query_native_outcome(original_terminal_identity, organization_id=own_id, tick=current_tick)',
                'contractor_endpoint': 'ContractorSupplyNativeApplication.query_native_outcome(original_identity, organization_id=own_id, tick=current_tick)',
                'implementation': 'integration.supply_native_outcome_query',
                'evidence': 'output/integration/supply_outcome_query_20261017_01/manifest.json',
                'behavior': 'Reads exact original Supplier terminal stage and completed prefix, or original Contractor A05; reuses original saved snapshots, workers and native proposal/final/event correlation. Rechecks grants and readable references at actual query time. Later Supplier decision/selection and Contractor selection history call the same original query before private consumption, preserving their original history projections. No event is unknown, never permission to resubmit.',
                'limits': 'Original native supply willingness and selection only; no detailed order, stock reservation, shipment, receipt or payment is inferred. Later-decision feedback remains strictly earlier than the current decision. Other shared/checkpoint/model combinations and migration of old sealed histories remain unverified.',
            }} if action_id in {'SUPPLIER-A01','SUPPLIER-A02','SUPPLIER-A03','SUPPLIER-A04','CONTRACTOR-A05'} else {}),
            **({'native_supply_actor_ownership': {
                'configuration': 'supplier_order_native_development --organization-actor-ids JSON; optional initial mapping only, default identities unchanged.',
                'scope': 'Supplier original A01/A02/A03/A04 and Contractor original A05 in the same actual native procurement workflow.',
                'binding': 'Native agent/task organization/legal buyer, payer and Supplier IDs remain organization IDs. Original inquiry recipient and executing/signing actor fields remain actor IDs. Current OrganizationRegistry.grants binds the actual actor, function, scope, action and organization.',
                'private_history': 'SupplierOrderNativeApplication._authorize_step rechecks predecessor-stage current grants and exact retained readable references. Contractor disclosure rechecks original Supplier A03/A04 grants. Revoking A01 prevents its private handoff even while A04 remains authorized.',
                'verification': 'Existing-identity and distinct-organization/actor actual two-tick chains each completed 18 original micro actions and 46 formed technical tasks. Actual native selection feedback enters later original Contractor A05 and changes Supplier A to B. Cross-organization actor and revoked predecessor grants are rejected.',
                'evidence': 'output/integration/supply_actor_identity_checks_20261017_01/checks.json',
                'limits': 'Explicit independent initial commercial sources, no runtime renaming of sealed sources or authorship. Distinct-actor decline/substitution/recovery and eight-role shared combinations remain for concentrated integration; no detailed order, stock, cash or payment receipt is inferred.',
            }} if action_id in {'SUPPLIER-A01','SUPPLIER-A02','SUPPLIER-A03','SUPPLIER-A04','CONTRACTOR-A05'} else {}),
            **({'unstarted_continuation_bridge': {
                'implementation': 'integration.unstarted_action_continuation:execute_original_stage',
                'host': 'integration.supplier_order_native:SupplierOrderNativeApplication._execute_stage',
                'standalone_enable': '--continue-unstarted-actions-on-error',
                'shared_enable': '--with-government-and-supply --continue-unstarted-supplier-actions-on-error',
                'authority': 'Original worker unstarted_evidence requires the registered immutable snapshot, '
                    'unchanged revision-zero waiting_input task, no conditions/result and a registered execution claim. '
                    'The worker rechecks current sources, authority and versions and atomically claims preparation.',
                'boundary': 'Default off and independent of saved-result queries. At most one continuation '
                    'inside the same still-open original native call, using the same prepared invocation and task. '
                    'No repeat earlier action/source production, preparation replay, missing-stage creation, '
                    'unknown-result replay, engine restart or formal business record.',
            }} if action_id in {'SUPPLIER-A01','SUPPLIER-A02','SUPPLIER-A03','SUPPLIER-A04'} else {}),
            **({'supplier_saved_recovery_bridge': {
                'implementation': 'integration.supplier_order_native_recovery:recover_saved_supply_proposal',
                'preflight': 'integration.supplier_order_native_recovery:saved_supply_preflight',
                'transport': 'integration.native_routes:NativeRouteAgentClient.propose',
                'standalone_enable': '--allow-saved-recovery --query-saved-supply-on-error',
                'shared_enable': '--with-government-and-supply --allow-supplier-saved-recovery --query-saved-supply-on-error',
                'terminal_choices': {'SUPPLIER-A01':['decline'],'SUPPLIER-A02':['decline'],
                    'SUPPLIER-A03':['decline_quote'],'SUPPLIER-A04':['accept','reject']}[action_id],
                'boundary': 'Default off. Validate original registered sequence, snapshots, currently authorized sources, '
                    'execution versions and completed results before technical finalization. Only the original in-process '
                    'native call may receive the same terminal decision. No missing-result replay, unstarted stage, '
                    'partial/clarify coercion, engine restart, detailed SupplyOrder or cash execution.',
            }} if action_id in {'SUPPLIER-A01','SUPPLIER-A02','SUPPLIER-A03','SUPPLIER-A04'} else {}),
            **({'private_quote_consumer': {
                'implementation': 'integration.supplier_order_native_quote:quote_for_order',
                'input_producer': 'integration.supplier_order_native_quote_development:extend_quote_plan',
                'enable': 'integration.supplier_order_native_development --with-quote',
                'verified_choices': ['quote'],
                'consumer': 'Original A04 reads the actual original A03 result as private same-request evidence '
                    'supporting its independently supplied unchanged offer/proposal and buyer acceptance.',
                'checks': 'Exact full delivery lines, price provenance, buyer/payer, terms/validity/conditions, '
                    'payment rules and identical current inventory/capacity sources; original worker, invocation and audit retained.',
                'limits': 'Current products, inquiry, unit costs, markup and independent agreed terms are explicit synthetic sources. '
                    'Optional --with-product executes original A02 and its authorized original handoff; '
                    'default A03 still uses an independent supplied product proposal. '
                    'No formal quote registration, detailed order or reservation is inferred. '
                    'A complete-demand decline_quote can return native decline_supply_order through native_decline_bridge. '
                    'A mismatch or unresolved result stops for review; existing independent terms are not rewritten.',
            }} if action_id == 'SUPPLIER-A03' else {}),
            **({'private_product_consumer': {
                'implementation': 'integration.supplier_order_native_product:product_for_quote',
                'input_producer': 'integration.supplier_order_native_product_development:extend_product_plan',
                'enable': 'integration.supplier_order_native_development --with-quote --with-product',
                'verified_choices': ['propose_original','propose_substitute'],
                'substitution_composition': {
                    'input_producer': 'integration.supplier_order_native_substitution_development:extend_substitution_plan',
                    'enable': '--with-quote --with-product --with-screening --with-contractor --with-product-substitution',
                    'consumer': 'Original A03/A04 preserve exact versioned deviations; original Contractor A05 '
                        'reads independently declared requirement-level substitution permission before native selection.',
                    'boundary': 'Independent initial alternate catalogue and commercial assent, not product approval. '
                        'False permission produces original A05 needs_information and no native selection. '
                        'Clarification, design issues, multiple batches and other substitutions remain pending.',
                },
                'consumer': 'Original A03 build_from_products reads actual same-request A02 worker evidence '
                    'through its original prepare_supplier_product_handoff; source/result/audit identity and '
                    'current authorized product proposals are explicitly checked by the host.',
                'checks': 'Exact original inquiry, complete product/quantity/destination/requirement/deviation lines, '
                    'identical catalog facts, actual saved result and source snapshot, authorized private relation '
                    'and observed evidence. The native proposal/final still consume the resulting original A04.',
                'limits': 'Explicit synthetic catalog material, factory/use constraint and property evidence; '
                    'no independent design checks are declared in this development scene. '
                    'Existing proposal confirmation remains an independent input, never inferred from A02. '
                    'A complete-demand decline can return native decline_supply_order through native_decline_bridge. '
                    'Unresolved design issues and changed proposal facts stop this composition. '
                    'Optional --with-screening runs original A01 and its authorized original handoff before A02. '
                    'Substitution and other A02 branches and actual source composition remain pending.',
            }} if action_id == 'SUPPLIER-A02' else {}),
            **({'private_screening_consumer': {
                'implementation': 'integration.supplier_order_native_screening:screening_for_product',
                'input_producer': 'integration.supplier_order_native_screening_development:extend_screening_plan',
                'enable': 'integration.supplier_order_native_development --with-quote --with-product --with-screening',
                'verified_choices': ['respond'],
                'consumer': 'Original A02 build_from_screening reads actual same-request A01 worker evidence '
                    'through original prepare_supplier_screening_handoff with explicit original-history/current-source callbacks.',
                'checks': 'Exact original received inquiry, complete offered scope and requirement correspondence, '
                    'actual original result/audit/source identity, current own author authority, separate observed '
                    'received-input and source-relation evidence. Original A02 consumes both declared evidence refs.',
                'limits': 'Production capability, function permission, capacity and productivity are explicit synthetic '
                    'sources, distinct from delivery pools and normalized native resources. Observing an actual read '
                    'of supplied received demand is not a native inquiry receipt. Only full respond proceeds in '
                    'the product composition. A complete-demand decline can return native decline_supply_order '
                    'through native_decline_bridge; partial scope, clarification, tracking and unresolved results await review. '
                    'No A01 response creates an order, reservation or professional product approval.',
            }} if action_id == 'SUPPLIER-A01' else {}),
            **({'existing_bridge': {
                'implementation': 'integration.contractor_supply_native:ContractorSupplyNativeApplication',
                'input_producer': 'integration.contractor_supply_native_development:contractor_plans',
                'quote_relation': 'integration.contractor_supply_native_sources:supplier_quote_for_contractor',
                'substitution_relation': 'integration.contractor_supply_native_substitution:quoted_substitutions',
                'substitution_permission': 'Each exact quoted deviation binds to an independent requirement-level '
                    'SubstitutionAuthority, read by original A05. Missing links, changed versions, foreign authority '
                    'and duplicate declarations are rejected. A false permission remains original needs_information.',
                'history_reader': 'integration.contractor_supply_native_feedback:prior_contractor_supply_selections',
                'enable': 'integration.supplier_order_native_development --with-quote --with-contractor',
                'verified_choices': ['accept_supply_offer'],
                'native_semantics': 'At actual Contractor.select_supplier, an explicit Contractor preference selects '
                    'a currently accepted disclosed candidate. Original A05 validates exact independent received '
                    'commercial terms, original supplier authorship, receiving/inspection/payment bindings, '
                    'procurement responsibility and mandate limits before native supplier selection. '
                    'Final confirmation reuses the same actual worker result, proposal and bounded candidates.',
                'source_boundary': 'Original A03 quote and A04 acceptance are authenticated to actual events/tasks '
                    'and support unchanged independently supplied received offers. Whitelisted commercial evidence '
                    'is checked; no Supplier cost, stock, cash, production capacity or strategy is disclosed. '
                    'Initial independent author grants are not attributed to the same-request A03 execution.',
                'feedback_consumer': 'Own strictly earlier actual selection is authenticated to original A05 '
                    'sources/result and native proposal/final/event. Explicit repeat_supplier_priority_penalty '
                    'changes only private candidate preference, then original A05 independently validates acceptance.',
                'limits': 'Initial detailed mandate limits, received signed commercial views, receiving/inspection/'
                    'payment permissions and empty procurement history are explicit synthetic assumptions. '
                    'This source composition currently requires one exact quoted batch without deviations. '
                    'Native selection is not a detailed order, formal contract, commitment reservation or payment. '
                    'One alternate-catalogue batch with exact deviations is supported; other A05 branches, '
                    'multiple batches, other deviations, real sources and C3 execution remain pending.',
            }} if action_id == 'CONTRACTOR-A05' else {}),
            **({'native_intake_saved_recovery': {
                'implementation': 'integration.government_intake_native_recovery:recover_saved_intake_proposal',
                'validation': 'integration.government_intake_native_recovery:original_intake_work',
                'input_producer': 'integration.government_intake_development:build_bundle',
                'actual_evidence': 'output/integration/government_intake_continuation_checks_20261017_01/checks.json',
                'verified_chain': 'Original saved A02 accept/decline after technical finish failure -> '
                    'same still-open native request -> actual review decision and approval -> later own '
                    'original A02 consumes strictly earlier actual willingness feedback.',
                'configuration': '--allow-intake-saved-recovery (shared: --allow-government-intake-saved-recovery); '
                    '--query-saved-intake-on-error returns to the original waiting call. Both default off.',
                'limits': 'Rechecks exact current request, context, input, seven versions, snapshots, '
                    'source bytes, current authority and original saved audit. No missing processor '
                    'execution, supplement receipt, wait resolution, failed-tick restart or formal resubmission. '
                    'Shared inputs verified; shared recovery business and other combinations remain pending.',
            }} if action_id == 'GOV-A02' else {}),
            **({'native_supplement_reception_boundary': {
                'evidence': 'output/integration/government_intake_continuation_checks_20261017_01/supplement-boundary.json',
                'existing_receiver': 'integration.owner_government_supplement_handoff:read_received_owner_supplement',
                'finding': 'Reviewed native intake/approval proposals pass project/resource or project/policy; '
                    'the existing detailed receiver independently requires original OWN-A08 publication '
                    'receipt, actually received Response, exact current content lineage and reception evidence. '
                    'Do not substitute sealed-file edits or technical saved-result recovery for those facts.',
                'scope': 'Specific reviewed callsites; other original macro capabilities are not ruled out.',
            }} if action_id in {'GOV-A02','GOV-A06','OWN-A08'} else {}),
            **({'same_call_unstarted_approval_continuation': {
                'implementation': 'integration.unstarted_action_continuation:execute_original_stage',
                'host': 'integration.government_approval_native:GovernmentApprovalApplication.propose',
                'enable': '--with-approval --continue-unstarted-approval-actions-on-error',
                'shared_enable': '--with-government-and-supply --continue-unstarted-government-approval-actions-on-error',
                'default_enabled': False,
                'evidence': 'output/integration/government_unstarted_20261017_01/checks.json',
                'verified': 'Each original GOV-A12/A04/A07 stage continues once after a controlled interruption '
                    'before preparation, with the same task, snapshot, current sources, authority and versions. '
                    'Predecessor results remain unchanged. Each four-tick original native run completes 13 '
                    'micro actions and 59 technical tasks, retains actual rectification/completion and later '
                    'A12-to-A04/A07 consumption. Disabled and already-preparing cases retain unresolved work.',
                'limits': 'Only an immutable original registered execution claim proving preparation has not '
                    'started authorizes continuation within the still-open native call. No preparation '
                    'replay, waiting-input cure, supplement receipt, new business request or engine restart. '
                    'Separate saved-result query policy is unchanged. Eight-role initial assembly passed; '
                    'shared review-stage fault business, new-authority use and completed-tick restart are verified in shared_business_recovery_case. Other shared stages, model and failed-tick combinations remain unverified.',
            }} if action_id in {'GOV-A04','GOV-A07','GOV-A12'} else {}),
            **({'native_outcome_query': {
                'entry': 'GovernmentApprovalApplication.query_native_outcome(original_decision_identity, organization_id=own_id, tick=current_tick)',
                'implementation': 'integration.government_native_outcome_query:query_native_approval_outcome',
                'evidence': 'output/integration/government_outcome_query_20261017_01/checks.json',
                'behavior': 'Reads the one original design/completion workflow, immutable snapshots, original results, transport and matching global/project native events. Absence returns unknown; a fully authenticated original event returns observed. Rechecks current authority at actual query time.',
                'verification': 'Two actual design/completion cases pass. Queries before execution return unknown and after execution observe original approval/rejection or rectification/completion. Repeated queries leave tasks and native events unchanged; revoked grants, wrong organization/time/identity and divergent copied event logs are rejected.',
                'limits': 'No processor replay, new task/request, clock advancement, wait resolution, formal supplement receipt, detailed signed permit or physical inspection. Later decision history still excludes the current tick by default. Shared/restart/model combinations and full regression remain pending.',
            }} if action_id in {'GOV-A04','GOV-A07','GOV-A12'} else {}),
            **({'native_pending_results': {
                'implementation': 'integration.government_native_wait:validate_pending_result',
                'workflow': 'integration.government_native_wait:completed_result_or_wait',
                'actual_evidence': 'output/integration/government_pending_checks_20261017_01/checks.json',
                'verified_results': {'GOV-A02': ['needs_information'],
                    'GOV-A04': ['needs_information'], 'GOV-A07': ['unsupported']}[action_id],
                'behavior': 'Original task, saved result and exact conditions enter waiting_input after '
                    'current request, source and authority checks. The workflow records the actual waiting '
                    'stage and stops before dependent actions or a native acceptance/approval response.',
                'limits': 'No automatic correction, supplement reception, successor, failed-tick restart '
                    'or formal resubmission. Stale queries after engine interruption are rejected by '
                    'current-source checks. Other unresolved outcomes are encoded but not business-verified.',
            }} if action_id in {'GOV-A02','GOV-A04','GOV-A07'} else {}),
            **({'existing_bridge': {
                'implementation': 'integration.government_intake_native:GovernmentIntakeApplication',
                'input_producer': 'integration.government_intake_development:build_bundle',
                'actual_result_projection': 'integration.government_intake_feedback:project_government_event',
                'history_reader': 'integration.government_intake_feedback:prior_review_decisions',
                'supported_choices': ['accept_for_processing', 'decline_processing'],
                'native_semantics': 'Original GOV-A02 preparation supplies native regulatory review willingness. '
                    'Exact final confirmation checks the original collector summary, same project/time, '
                    'worker result, current source snapshot and formed proposal.',
                'feedback_consumer': 'A later original GOV-A02 reads strictly earlier own review events, '
                    'authenticated to original proposal/final/micro tasks and bound to observed Evidence. '
                    'This history does not alter supplied jurisdiction, qualification, signature or materials.',
                'native_approval': 'Default original GovernmentAgent.decide_approval remains explicit. '
                    'Optional --with-approval composes original A04/A07 with exclusive native approval ownership.',
                'completion_scope': 'Original construction-stage completion inspection uses the same original A02 '
                    'through an explicit completion-phase plan and distinct completion_review_assignment scope. '
                    'Completion source declarations use --with-approval --completion; a four-tick synthetic '
                    'run has actual completion/rectification and subsequent own feedback consumption. '
                    'Shared-host continuation and full regression remain pending.',
                'limits': 'Independent synthetic received submissions and legal/procedural sources. '
                    'No case filing, RegulatoryCase registration, permit or invented legal authority. '
                    'Correction, referral, acknowledgement and unresolved outcomes remain unmapped. '
                    'The verified feedback is review willingness, not approval or ongoing workload.',
            }} if action_id == 'GOV-A02' else {}),
            **({'existing_bridge': {
                'implementation': 'integration.government_approval_native:GovernmentApprovalApplication',
                'input_producer': 'integration.government_approval_native_development:approval_plans',
                'actual_result_projection': 'integration.government_approval_native_feedback:project_approval_event',
                'history_reader': 'integration.government_approval_native_feedback:prior_approval_decisions',
                'completion_history_reader': 'integration.government_completion_native_feedback:own_completion_outcomes',
                'completion_binding': {'decision_type': 'government_completion_approval',
                    'scope': 'completion_approval', 'source_option': '--with-approval --completion',
                    'status': 'synthetic_completion_rectification_and_later_feedback_observed',
                    'evidence': 'output/integration/development_government_recovery_20261016_02/runtime-current',
                    'assignment': 'Exact original earlier A02 event plus actual selected Government engagement.',
                    'execution_feedback': 'Own final task, A04/A07 sources/audits and actual native '
                        'project_completed/quality_issue; no invented event recipient or delivered receipt.',
                    'outcome': 'Keep micro accepted opinion distinct from native completed/rectification_required; '
                        'the original defect gate can require rectification even when micro approves.',
                    'procedure_identity': 'A separately identified case checklist links source_procedure_ref to the exact '
                        'unchanged procedure of the original received submission and case. Never overwrite an intake '
                        'procedure version with another case or tick-specific checklist.',
                    'limits': 'Document review only; no GOV-A10 physical inspection coverage, formal permit or second ledger.'},
                'saved_result_recovery': {
                    'implementation': 'integration.government_approval_native_recovery:recover_saved_proposal',
                    'entry': 'assembly.client.recover_proposal(original_request)',
                    'enable': '--with-approval --allow-saved-recovery',
                    'shared_enable': '--with-government-and-supply --allow-government-saved-recovery',
                    'same_call_query_enable': '--query-saved-approval-on-error (also requires saved-result recovery)',
                    'same_call_query_implementation': 'integration.native_routes:NativeRouteAgentClient.propose',
                    'status': 'same_call_saved_result_continuation_observed_restart_pending',
                    'business_fault_evidence': 'output/integration/development_government_saved_feedback_checks_20261016_01/test_original_native_call_quer0/runtime/fault-continuation.json',
                    'observed': 'A controlled micro journal interruption at tick 3, after original GOV-A07 result '
                        'persistence, is reconciled once while the original macro call remains open. Original '
                        'result/audit is unchanged. Macro records actual rectification, another project completes; '
                        'tick 4 original GOV-A12 reads both earlier outcomes and its original result is consumed '
                        'by A04/A07. Four ticks, 13 original micro actions and 59 formed technical tasks. '
                        'Separate positive completion, default-disabled and missing-result cases are checked.',
                    'checks': 'Same current original native request, organization/project/time, pinned sources, '
                        'original invocation, all execution versions, saved completed results and audits. '
                        'Includes original A12 stage when configured; acquires host guard before client lock.',
                    'limits': 'Manual recover_proposal only queries and returns the original response without '
                        'delivery. The optional same-call policy returns that response to the still-waiting '
                        'original macro proposal, not a new submission. Never execute an absent stage, replay '
                        'a processor/model, create a new native request, restore an engine, advance a clock '
                        'or resubmit business. Unknown/stale work remains unresolved. Macro process restart, '
                        'micro process restart and shared business fault validation remain pending.',
                },
                'supported_choices': ['assess'] if action_id=='GOV-A04' else ['approve','defer_by_procedure'],
                'source_boundary': 'Current selected agency requires its actual accepted A02 event, original '
                    'proposal/final and micro result. Detailed initial case, assignment, jurisdiction, declared '
                    'rules, applicability and signing permissions are independent explicit sources, not inferred '
                    'from A02 willingness or native quality scores.',
                'review_handoff': 'Original A04 recomputes its disclosed saved rule execution. Actual completed '
                    'review checks, original source versions, author/grant and per-project method descriptors '
                    'form private A07 assessment/finding projections; no formal assessment registration.',
                'native_semantics': 'Explicit outcome policy selects an independently authorized approval '
                    'rule if all checks conform; an actual nonconforming check selects a no-permission '
                    'defer_by_procedure draft requiring revision. Original A07 independently validates the '
                    'draft. approve maps to native approve; defer_by_procedure maps to request_revision. '
                    'Final transport checks the same original result and bounded request, without redecision.',
                'feedback_consumer': 'Actual approval_approved/approval_rejected is projected only to the '
                    'responsible agency. Later original A04/A07 source views read strictly earlier own '
                    'outcomes authenticated to original micro sources/audits, proposal, final and native event. '
                    'History remains context; it does not change independent jurisdiction or conformity facts.',
                'limits': 'Development sources are explicitly synthetic document-code checks, not physical '
                    'design compliance or real legal validity. No initial case is created by intake, no signed '
                    'decision ID, delivery or detailed permit is fabricated. Conditional approval and formal '
                    'refusal are not request_revision. Unknown/unresolved review, other A04/A07 branches, '
                    'formal filing, delivery, permits, other regulator actions and recovery remain pending.',
            }} if action_id in {'GOV-A04','GOV-A07'} else {}),
            **({'existing_bridge': {
                'implementation': 'integration.government_approval_native:GovernmentApprovalApplication',
                'input_producer': 'integration.government_approval_native_learning_development:feedback_plan',
                'monthly_operation':{
                    'implementation':'integration.government_monthly_native:GovernmentMonthlyApplication',
                    'input_producer':'integration.government_monthly_native_development:monthly_plans',
                    'source_option':'--with-monthly-feedback / --with-government-monthly-feedback',
                    'history_reader':'integration.government_monthly_native_sources:prior_monthly_feedback',
                    'saved_result_recovery':{
                        'implementation':'integration.government_monthly_native_recovery:recover_saved_monthly_proposal',
                        'authorization':'--allow-monthly-saved-recovery / --allow-government-monthly-saved-recovery',
                        'same_call_option':'--query-saved-monthly-on-error',
                        'semantics':'Only reconcile a durable completed original GOV-A12 result under the same current '
                            'native request, source, rights and execution versions. Do not replay missing work, '
                            'restart the engine, create a new request or resubmit formal business.',
                    },
                    'native_semantics':'Current native monthly request executes original private GOV-A12 record_feedback. '
                        'The same original bounded final returns review_policy_feedback; only the native scheduler '
                        'records agent_operation and enterprise memory. Strictly earlier own outcomes are consumed '
                        'by later monthly A12 and original approval A12/A04/A07.',
                    'event_correlation':'The original scheduler retains native market factors, not micro task IDs. '
                        'Authenticate the own agent/tick/operation, unique original private record, proposal/final, '
                        'native label/description/accepted/source/utility/probability and retained enterprise memory. '
                        'Do not add micro tags to native events; unbound native work is not micro coverage.',
                    'limits':'Only private feedback recording; no formal policy publication, legal change, physical '
                        'inspection, resource reservation, permit or financial execution. Native random capability '
                        'updates remain separate outcomes. Process restart, unresolved missing results and other branches pending.',
                },
                'source_projection': 'integration.government_approval_native_learning:feedback_sources',
                'result_consumer': 'integration.government_approval_native_learning:feedback_origin',
                'supported_choices': ['record_feedback'],
                'source_option': '--with-approval --with-feedback',
                'shared_source_option': '--with-government-and-supply --with-government-feedback',
                'status': 'synthetic_own_completion_history_consumed_by_A12_A04_A07',
                'evidence': 'output/integration/development_government_recovery_20261016_02/runtime-current',
                'native_semantics': 'Original approval request runs original GOV-A12 once before original A04/A07. '
                    'Received feedback is the actual authorized own-history query result, authenticated to original '
                    'native events, proposals, final responses and micro records. It claims no external delivery.',
                'feedback_consumer': 'Original A12 saved result, audit and history evidence are bound into the '
                    'observed Evidence actually read by this request original A04/A07. Same result is rechecked '
                    'at final confirmation without rerunning A12 or changing independent document facts.',
                'limits': 'Own private reflection only. Empty history remains absence of earlier authenticated outcomes. '
                    'No policy, work assignment, formal feedback execution, legal condition or cash change. '
                    'Shared-host A12/A04/A07 execution is scoped in shared_assembly; other A12 choices and full regression remain pending.',
            }} if action_id=='GOV-A12' else {}),
            **({'existing_bridge': {
                'implementation': 'integration.owner_invitation_native:OwnerInvitationBridge',
                'input_producer': 'integration.owner_invitation_development:build_bundle',
                'actual_result_projection': 'integration.owner_invitation_feedback:project_owner_invitation_event',
                'next_consumer': 'Contractor A01 reads own native invitation origin through gba_v1_tender_package.',
                'supported_choices': ['invite'],
                'limits': 'Requires independently supplied published micro package, open round, candidate eligibility '
                          'and authority. This is not a native publication receipt or coverage of other OWN-A09 branches.',
            }} if action_id == 'OWN-A09' else {}),
            **({'existing_bridge': {
                'implementation': 'integration.professional_intake_native:ProfessionalIntakeApplication',
                'input_producer': 'integration.professional_intake_development:build_bundle',
                'actual_result_projection': 'integration.professional_intake_feedback:project_professional_event',
                'next_consumer': 'Later original A02 reads authenticated earlier own consultant_team_appointed '
                                 'and original acceptance tasks; an explicit intake policy can decline new work.',
                'supported_choices': ['accept', 'decline'],
                'owner_selection': 'Default original OwnerAgent.select_appointment, preserving the same bounded final. '
                    'Optional --with-owner executes original OWN-A04 from the same independent A02 acceptances '
                    'and actual received commercial terms; no second native choice or failure fallback.',
                'limits': 'Independent qualification, fee, work and calendar inputs must be supplied. '
                          'Development inputs are explicit synthetic assumptions. Native engagements do not '
                          'constitute detailed micro service contracts or charge micro service fees. Optional '
                          '--with-owner --with-confirmation consumes the actual own native team event in original A03 '
                          'and requires authenticated strictly earlier own confirmations before new A02 intake. Other A02 branches '
                          'remain unresolved rather than becoming acceptance or refusal.',
            }} if action_id in {'ARCHITECT-A02', 'ENGINEER-A02', 'QS-A02'} else {}),
            **({'trigger': 'Actual own committed consultant_team_appointed observation after native selection',
                'next_consumer': 'Later original A02 reads authenticated own earlier A03 compatibility through its native Evidence.',
                'existing_internal_bridge': {
                    'implementation': 'integration.professional_appointment_native:ProfessionalAppointmentApplication',
                    'input_producer': 'integration.professional_appointment_native_development:appointment_plans',
                    'enable': 'integration.professional_intake_development --with-owner --with-confirmation',
                    'source_validation': 'integration.professional_appointment_native_sources:appointment_sources',
                    'actual_result_projection': 'integration.professional_intake_feedback:project_professional_event',
                    'history_reader': 'integration.professional_appointment_native:ProfessionalAppointmentApplication.prior_confirmations',
                    'supported_choices': ['confirm','request_amendment']+(['decline_incompatible'] if action_id=='ARCHITECT-A03' else []),
                    'unresolved_history_policy': {
                        'initial_source_option':'--incompatible-confirmation-role <Architect|Engineer|QS>',
                        'later_policy_option':'--decline-after-unresolved-confirmation',
                        'consumer':'Original later own A02 reads the authenticated earlier A03 result, questions '
                            'and source-reading digest through its original native Evidence. Explicit decline_new_work '
                            'updates only the private FeeBasis policy; original A02 decides the actual refusal.',
                        'count_policy_option':'--prior-appointment-limits accepts independent role/count-or-null policy inputs.',
                        'boundary':'Default require_resolution remains unresolved. Neither policy cancels a native '
                            'appointment, resolves or delivers questions, amends terms, releases resources or charges fees. '
                            'Native QS refusal can suspend a project before any Engineer request; no request is invented.',
                    },
                    'semantics': 'The existing client continuation_dispatcher receives the actual own native team event. '
                        'Original A03 assembler/worker validates exact independent A02 acceptance, original OWN-A04, '
                        'audited terms and current authorization. Only selected providers run A03. Later original A02 '
                        'requires original own strictly earlier confirmation by default; the explicit unresolved-history '
                        'policy can instead pass its unchanged private issues to original A02. Duplicates validate saved '
                        'results without reexecution.',
                    'limits': 'Private compatibility confirmation only, not a consider_appointment proposal or new formal '
                        'command. No service relationship, reservation conversion, task allocation, fee or payment is created. '
                        'QS explicit detailed calendar/check views preserve original physical capacity and commitments. '
                        'Question delivery, replies, actual amendment resolution, task planning and other branches remain pending. '
                        'Current sources are explicitly synthetic. Macro native observer failures do not undo its appointments.',
                }} if action_id in {'ARCHITECT-A03', 'ENGINEER-A03', 'QS-A03'} else {}),
            **({'existing_bridge': {
                'implementation': 'integration.qs_bid_native:QSBidNativeBridge',
                'input_producer': 'integration.qs_bid_native_development:build_bundle',
                'shared_application': {
                    'input_producer': 'integration.financing_professional_development:build_bundle',
                    'enable': '--with-contractor-tender --with-qs-evaluation',
                    'evaluation_feedback': '--with-tender-feedback',
                    'shared_components': 'Original organization/authorization snapshot, registry, task store, engine clock and writer guard.',
                    'handler_chain': 'Tender final -> QS evaluation -> Owner invitation -> shared role applications -> declared native routes.',
                    'invitation_ownership': 'The invitation bridge owns dispatch. Explicitly listed existing background projects '
                        'retain original native invitation decisions; micro-planned projects cannot overlap that list. '
                        'Missing micro sources still fail; no rule fallback is applied.',
                    'configuration_checks': 'tests/test_shared_qs_evaluation_configuration.py',
                    'actual_runtime': 'output/integration/development_shared_qs_evaluation_20261016_03/runtime/result.json',
                    'observed': 'Four native ticks, eight actual micro roles, 72 original actions and 277 formed technical tasks. '
                        'Two bids at tick 1, original QS-A06 evaluation and native Owner selection at tick 3; '
                        'own original A01/A02 consume that actual evaluation and decline followup bids at tick 4.',
                    'coverage_boundary': 'Eight installed roles do not prove eight actual micro business participants or all QS branches.',
                },
                'input_origin': 'Actual native bid_submitted events and original Contractor proposal/final feedback tasks.',
                'supported_choices': ['evaluate','exclude_authorized','no_valid_bid'],
                'supported_status': 'Comparable rows with no unresolved questions, or independently authorized known-failure exclusions. A fully delegated no-valid-bid round retains actual native selection deferral.',
                'round_semantics': 'One original QS-A06 evaluates all actual same-round bids; each native bid request '
                                   'reads its own row and independently evidenced score. A new native review after deferral uses its separately declared context; queries never replay a round.',
                'native_owner_composition': {
                    'implementation':'integration.bindings.gba_v1_native_composition:DeclaredNativeComposition',
                    'enable':'qs_bid_native_development --with-native-owner-selection',
                    'ownership':'The Owner select_preferred_bid proposal uses the original native module. '
                        'It does not count OWN-A08. QS evaluation remains external micro. Fully excluded rounds '
                        'add a bounded final adapter that authenticates all original exclusions and retains the '
                        'original negative empty-selection proposal without disclosing private QS task identities.',
                    'validation':'Every external proposal and every external final decision retains the original macro validator. '
                        'An installed micro proposal handler cannot be routed through the native declaration; no error fallback.',
                    'actual_runtime':'output/integration/development_qs_native_composition_20261016_01/runtime/result.json',
                    'observed':'Four native ticks, original OWN-A09, two Contractor A01/A02 submissions and one QS-A06 round; '
                        'original Owner selection produces bid_evaluation_completed and stage contract_award. No signed contract.',
                    'remaining':'Original QS-A12 feedback recording and same-call saved-result recovery have bounded actual evidence; other evaluation choices remain pending.'},
                'limits': 'Explicit independently supplied micro document, eligibility, coverage and score inputs. '
                          'Clarification/no-valid-bid branches remain pending. Authorized exclusion uses the separately declared original final path; no invented ranking. Default external Owner selection still conflicts '
                          'with its frozen response contract; the explicit native-owned module composition is a separate supported route. '
                          'Saved micro evaluations alone are not committed evaluation receipts.',
            }} if action_id == 'QS-A06' else {}),
            **({'native_settlement_feedback': {
                'implementation': 'integration.native_lifecycle_actions:NativeLifecycleApplication',
                'input_producer': 'integration.final_account_learning_development:add_settlement_learning',
                'enable': '--with-final-account-discussion --with-final-account-learning (default off)',
                'trigger': 'Actual own final_account_settled event after an actual strictly earlier native review.',
                'private_prerequisite': 'Original completed own QS-A09 result, same project, scope and clock.',
                'consumer': 'Original QS-A12 record_feedback, with exact actual event Evidence and immutable saved result.',
                'verification': 'Shared three-tick eight-role run: 84 original micro results, 244 formed tasks, '
                    'seven private closeout actions and four later original Owner investment consumers. '
                    'Duplicate event creates no tasks; forged settlement is rejected.',
                'evidence': 'output/integration/qs_settlement_learning_checks_20261017_02/checks.json',
                'limits': 'Aggregate settlement feedback only. No original forecast-error comparison, judgment update, '
                    'cash receipt, cleared debt or detailed acceptance. Default-off variant and full regression pending.',
            }} if action_id == 'QS-A12' else {}),
            **({'existing_bridge': {
                'implementation': 'integration.qs_evaluation_learning:QSEvaluationLearning',
                'input_producer': 'integration.qs_evaluation_learning_development:learning_plan',
                'shared_input_producer': 'integration.financing_professional_development:build_bundle',
                'enable': '--with-contractor-tender --with-qs-evaluation --with-tender-feedback --with-qs-learning',
                'supported_choices': ['record_feedback'],
                'trigger': 'Original QS decide_monthly_operation request at the explicitly configured current tick.',
                'source': 'Own strictly earlier actual bid_evaluation_completed events, matched to native project logs, '
                    'original QS proposal/final outputs and completed original QS-A06 worker results.',
                'consumer': 'Original QSLearningActionAssembler and QSLearningResultWorker share authority, registry, '
                    'model host and task journal with the original evaluation application.',
                'formal_business': 'Declared native monthly proposal runs after private micro recording; its business decision stays native.',
                'verification': 'Actual four-tick tender/evaluation/monthly run completes after original QS-A12 '
                    'result persistence and interrupted technical finish. One original result/snapshot is preserved; '
                    'one actual evaluation query is consumed. Retained native proposal queries cause no replay. '
                    'Shared recovery is initial eight-role assembly only; full regression remains pending.',
                'actual_evidence': 'output/integration/qs_learning_continuation_checks_20261017_01/checks.json',
                'assembly_evidence': 'output/integration/qs_learning_continuation_checks_20261017_01/assembly-checks.json',
                'saved_recovery': {
                    'implementation': 'integration.qs_evaluation_learning:QSEvaluationLearning.recover_saved_proposal',
                    'query': 'QSEvaluationLearning.query_saved_result',
                    'transport': 'integration.agent_client:GbaV1AgentClient.recover_proposal',
                    'enable': '--allow-qs-learning-saved-recovery --query-saved-qs-learning-on-error (default off)',
                    'boundary': 'Exact current original request, private sources, invocation, execution versions and '
                        'current grants are checked before technical completion. Missing/unresolved results are not '
                        'executed. A native proposal with a retained response is returned unchanged; a dispatched '
                        'native step without that response stays unknown. No failed-tick or process replay.',
                    'actual_checks': 'Interrupted original micro finish, unchanged result/snapshot, original-call '
                        'return, saved native response without replay, foreign request and current revoked grant '
                        'rejection. Unknown native dispatch is explicitly injected as retained technical state; '
                        'this is not evidence of a real interrupted native call or missing-result business run.',
                },
                'limits': 'Private authorized history query, not inbox delivery, applied judgment, forecast/outcome comparison, '
                    'cost error, profit, training effect, new capability or micro ownership of a formal monthly operation. '
                    'Unknown or duplicate claims are not automatically executed again; full process restart remains pending.',
            }} if action_id == 'QS-A12' else {}),
            **({'evaluation_outcome_feedback': {
                'reader': 'integration.bindings.gba_v1_bid_evaluation:with_own_evaluation_history',
                'consumer': 'Original CONTRACTOR-A01 with the exact derived private profile and Evidence; original A02 returns the decline.',
                'enable': 'qs_bid_native_development --with-native-owner-selection --with-evaluation-feedback',
                'source': 'Authorized own query of strictly earlier actual bid_evaluation_completed events, '
                    'matched to the native project log and original own bid proposal/final tasks. This is not inbox delivery.',
                'preference': 'Explicit decline_after_prior_evaluations; existing submission-count policy retains its default behavior.',
                'current_occupancy': 'An explicit current_occupancy_bindings template reads only own native normalized occupancy '
                    'at the current integer tick [tick,tick+1). Future calendar, physical capacity and formal resource booking are not inferred.',
                'actual_runtime': 'output/integration/development_qs_evaluation_feedback_20261016_07/runtime/result.json',
                'observed': 'Two actual bids at tick 1, actual micro QS evaluation and original native Owner selection at tick 3, '
                    'then two original A01/A02 declines at tick 4 consuming own preferred/not_preferred history. '
                    'The submission threshold is 999 and is not reached; the explicit evaluation threshold is 1.',
                'limits': 'Explicit synthetic initial invitations and independently supplied future calendars/qualification/scores. '
                    'No award, signed contract, actual profit or resource release follows from preferred status; '
                    'actual occupancy is a separate native read. Shared eight-role composition is recorded under QS-A06; '
                    'later QS private recording under QS-A12 has bounded actual business and same-call recovery evidence.'
            }} if action_id in {'CONTRACTOR-A01','CONTRACTOR-A02','QS-A06'} else {}),
            **({'reviewed_native_financing_source': {
                'correlation': 'integration.project_financing_native:financing_scope',
                'input_producer': 'integration.project_financing_development:build_bundle',
                'feedback_projection': 'integration.project_financing_feedback:project_financing_event',
                'history_reader': 'integration.project_financing_feedback:own_financing_history',
                'actual_trigger': 'Original SimulationEngine._arrange_project_financing during native project generation.',
                'proposal_identity': 'Missing project on wire is correlated to one unfinished current native project creation. '
                                     'Bank scalars and Owner offer set are checked against original state/events; ambiguous sources fail.',
                'micro_status': 'BankFinancingApplication optionally composes original A01 strategy, then A02 intake, A03 recommendation and A04 quotation '
                                'inside the actual native Bank request. Optional OwnerFinancingApplication executes original '
                                'OWN-A05 within the native selection request. Its explicit repeat-lender preference consumes '
                                'strictly earlier own native selection feedback, authenticated to original micro results. '
                                'Optional Bank A01 consumes its own strictly earlier selected-lender feedback for the current borrower; '
                                'its completed strategy caps A04 within the independent original quotation limit. Other financing branches remain pending.',
                'limits': 'Intake and risk recommendation do not independently approve finance. Native offer/selection '
                          'events do not establish detailed micro terms, signed arrangements, drawdown or cash. '
                          'Forecasts, accounts and detailed terms require independent authorized sources.',
            }} if action_id in {'BANK-A01', 'BANK-A02', 'BANK-A03', 'BANK-A04', 'OWN-A05'} else {}),
            **({'bank_strategy_consumer': {
                'implementation': 'integration.bank_financing_strategy:selection_feedback',
                'quote_handoff': 'integration.bank_financing_strategy:strategy_for_quote',
                'source_generator': 'integration.bank_financing_strategy_development:extend_plans',
                'verified_choices': ['retain_strategy','revise_strategy'],
                'actual_trigger': 'Optional private A01 preparation inside the same current native consider_financing request.',
                'feedback': 'Authenticated strictly earlier selections actually disclosed to this Bank, filtered by the current borrower. '
                    'The count is an observed selection count, never a default probability or a committed/disbursed amount.',
                'consumer': 'Original A04 receives a tighter private ceiling from the completed original A01 result and source snapshot. '
                    'The independent original ceiling remains an upper bound, with both inputs hashed into private handoff evidence.',
                'limits': 'Explicit opt-in policies and initial financial assumptions. No formal strategy registration, '
                    'loan commitment, old-term mutation or cash movement. Investigate and other unresolved outcomes stop the pipeline.',
            }} if action_id == 'BANK-A01' else {}),
            **({'bank_monthly_strategy_bridge': {
                'implementation': 'integration.bank_monthly_native:BankMonthlyApplication',
                'source_generator': 'integration.bank_monthly_native_development:extend_monthly',
                'history_reader': 'integration.bank_monthly_native_sources:prior_monthly_strategies',
                'quote_handoff': 'integration.bank_monthly_native_sources:quote_from_monthly',
                'enable': 'integration.bank_financing_development --with-monthly-strategy; '
                          'integration.financing_professional_development --with-bank-monthly-strategy',
                'actual_trigger': 'Original Bank decide_monthly_operation and monthly_enterprise_operation final.',
                'mapping': {'retain_strategy': 'review_credit_pipeline', 'revise_strategy': 'adjust_credit_terms'},
                'saved_recovery': {
                    'implementation': 'integration.bank_monthly_native_recovery:recover_saved_bank_monthly_proposal',
                    'transport': 'integration.agent_client:GbaV1AgentClient.recover_proposal',
                    'enable': 'Standalone --allow-monthly-saved-recovery --query-saved-bank-monthly-on-error; '
                              'shared --allow-bank-monthly-saved-recovery --query-saved-bank-monthly-on-error',
                    'boundary': 'Default disabled. Only the same current original native request and durable completed '
                                'BANK-A01; original invocation, all execution versions, source reading and authorization '
                                'are rechecked before technical finalization. No business replay, engine restart, '
                                'new native request, policy application or credit/cash execution.',
                },
                'feedback': 'Strictly earlier own actual native agent_operation events, authenticated to the original '
                            'saved BANK-A01 result, invocation, proposal and final, supply the next monthly signal '
                            'and the future original BANK-A04 private quote ceiling.',
                'limits': 'Default disabled. Independently declared complete per-time portfolios and policy thresholds. '
                          'Only tighter private future quotation bounds; no formal strategy, existing-term mutation, '
                          'loan, cash or occupied commitment. Unresolved strategy and missing native outcomes stop. '
                          'Original OWN-A05 no_finance is unresolved where frozen native selection only allows '
                          'bank selection or equity; independent initial funding must remain explicit.',
            }} if action_id in {'BANK-A01', 'BANK-A04'} else {}),
            **({'bank_micro_pipeline': {
                'implementation': 'integration.bank_financing_native:BankFinancingApplication',
                'input_producer': 'integration.bank_financing_development:build_bundle',
                'private_handoff': 'integration.bank_financing_private',
                'sequence': ['BANK-A02', 'BANK-A03', 'BANK-A04'],
                'verified_choices': {'BANK-A02': ['accept_for_review', 'decline'], 'BANK-A03': ['recommend', 'conditional', 'decline'],
                                     'BANK-A04': ['offer', 'conditional_offer', 'decline']}[action_id],
                'native_result': 'Completed original A02 decline ends the exact pipeline before A03/A04 and returns '
                                 'reject_financing. Accepted intake continues to A04 original principal, explicitly converted '
                                 'zero-fee simple annual interest and conditions. Final confirmation rechecks all executed '
                                 'original results, invocation snapshots, current permissions and consumed sources.',
                'feedback': 'Actual bank_financing_decision is disclosed only to its own bank, retaining original '
                            'terminal A02/A04 task/result and proposal digests. Later original actions consume authenticated '
                            'strictly earlier own A02 refusal events for the same borrower as private observation evidence. '
                            'Optional A01 separately consumes its earlier own selected-lender feedback and its actual '
                            'private strategy is used by A04.',
                'intake_refusal': {
                    'input_option': '--decline-intake-bank finance-bank-b (standalone or shared producer)',
                    'independent_initial_assumption': 'Selected Bank product allows refinancing; the actual received '
                        'purpose remains project_financing. Original A02 evaluates this mismatch itself.',
                    'actual_runtime': 'output/integration/development_bank_intake_decline_checks_20261016_02/'
                        'test_actual_intake_refusal_sto0/runtime/bank-intake-decline.json',
                    'actual_pending_runtime': 'output/integration/development_bank_intake_decline_checks_20261016_02/'
                        'test_actual_intake_refusal_sto1/runtime/bank-intake-decline.json',
                    'observed': 'Two native ticks, four actual A02 refusals, 20 original micro actions and 148 technical '
                        'tasks. The two later A02 requests read only the same Bank/borrower earlier actual refusal. '
                        'Missing product scope instead saves needs_information, with no native rejection or A03/A04.',
                    'boundary': 'Rejected response uses the existing zero-amount/zero-rate/empty-conditions convention; '
                        'it is not a calculated quotation, risk rating or disbursement. History does not change independent '
                        'product permissions, cash or debt. Shared opt-in configuration has assembly-only verification; '
                        'its refusal business and whole regression remain pending.',
                },
                'limits': 'A02/A03 records are private preparation, not registered intake or credit facilities. '
                          'Account/debt/forecast/authority/quote assumptions are explicitly supplied; native project '
                          'region and requested amount bind only at the real request. Unresolved outcomes stop without '
                          'native fallback. No disbursement, cash receipt or signed detailed arrangement is claimed.',
            }} if action_id in {'BANK-A02', 'BANK-A03', 'BANK-A04'} else {}),
            **({'existing_bridge': {
                'implementation': 'integration.owner_financing_native:OwnerFinancingApplication',
                'input_producer': 'integration.owner_financing_development:extend_bundle',
                'quote_projection': 'integration.owner_financing_quote_views:quote_views',
                'supported_choices': ['own_funds','accept_offer'],
                'verified_choices': ['own_funds','accept_offer'],
                'native_amount_binding': {
                    'implementation':'integration.project_financing_native:financing_requirement',
                    'binding':'Original OWN-A05 funding line planned_use binds the actual current native requested '
                        'financing amount in HKD, replacing the old fixed 50m example. Spending timing, cash, restricted cash, '
                        'unpaid old debt and future independent approvals remain explicit sources.',
                    'actual_check':'output/integration/owner_native_funding_checks_20261017_03/checks.json',
                    'observed':'Two native ticks, four projects, 38 original micro results across Owner/Bank, 166 technical '
                        'tasks. Two original own_funds choices produce actual equity records; two accept_offer choices '
                        'produce Bank selections and two original A05 confirmations. Both later original Owner decisions '
                        'consume their actual prior outcomes. Equity is not delivered to Banks or counted as Bank selection.',
                    'compatibility':'With nonempty accepted Bank candidates, frozen AgentRegistry rejects the null bank '
                        'choice (accepted=False, choice_source=invalid_llm_choice_rejected), while the native project '
                        'retains owner_equity. Preserve and authenticate both facts; do not label the bank choice accepted.',
                    'validation':'Actual business and positive/source-corruption checks completed. Final pytest assertion '
                        'revoked an unused alternative grant. Correct actual grant denial checked against retained SQLite '
                        'and the real registry with production _history; test selector corrected. Whole pytest/shared '
                        'and default combinations remain for concentrated regression.',
                    'limits':'Requested financing exposure with independently supplied timing, not whole-project funding, '
                        'detailed cash execution or a registered financing receipt. Regenerate old development bundles '
                        'that still contain a fixed planned amount.'},
                'input_origin': 'Actual native Owner offer set, original A04 worker results, original Bank decision events, '
                                'explicit disclosure dependencies, owner portfolio and declared preference/cost cap.',
                'final_confirmation': 'Reuse the exact formed OWN-A05 result and proposal; validate current quote sources and native bank candidates.',
                'condition_projection': 'Recheck the original A04 current authority and every retained source reference before disclosure. '
                    'Preserve the exact original verifier and CreditAssessment dependency conclusion: satisfied=true, '
                    'unsatisfied=false, unknown=unknown. Missing verification is unresolved. The original Owner worker '
                    'excludes a verified unsatisfied offer and independently compares other eligible offers.',
                'feedback_consumer': 'OwnerFinancingApplication._history validates earlier own selection event, '
                    'both native journals, the exact equity/bank mode, native accepted outcome, original native '
                    'proposal/final and, when present, the completed original OWN-A05 result/snapshot plus its current '
                    'decision/source-reading authority. The original micro choice remains distinct from native acceptance. '
                    'An optional explicit repeat-lender ordinal penalty feeds the original selection method; '
                    'the actual two-tick four-project window changes later choices from Bank A to Bank B.',
                'limits': 'Private communicated proposal views do not create detailed formal quote receipts. '
                          'Initial stock debt, independent party decisions and future approved funding are explicit scenario assumptions. '
                          'No unknown result becomes equity fallback, signed agreement, drawdown or cash. '
                          'No preference rule is enabled implicitly. Other OWN-A05 branches remain pending.',
            }} if action_id == 'OWN-A05' else {}),
            **({'existing_bridge': {
                'implementation': 'integration.bank_arrangement_native:BankArrangementApplication',
                'input_producer': 'integration.bank_arrangement_native_development:extend_sources',
                'private_handoff': 'integration.bank_arrangement_native_sources:arrangement_sources',
                'enable': 'integration.bank_financing_development --with-owner --with-arrangement',
                'supported_choices': ['confirm', 'decline', 'requote'],
                'verified_choices': ['confirm', 'decline'],
                'trigger': 'Actual own project_financing_selected, after original OWN-A05 acceptance; only the selected bank runs.',
                'sources': 'Exact original A04 offer, capacity, commitments and author mandates; actual independent '
                    'OWN-A05 acceptance and both original proposal/final records. Borrower financial views and private ranking remain undisclosed.',
                'next_consumer': 'BankArrangementApplication.prior_arrangements authenticates strictly earlier own '
                    'A05 results and binds them to later Bank financing input Evidence; unresolved results require explicit diagnosis.',
                'limits': 'Private formation-condition confirmation only. No detailed registered finance arrangement, '
                    'signature, capacity reservation, disbursement or cash receipt is inferred. Existing proposed '
                    'releases remain predictions. Completed private decline can feed explicitly configured later A01/A04 '
                    'new-business policy via prior_reviews; prior_arrangements still rejects decline/requote. Actual '
                    'requote business, detailed formation, later drawdown/execution and unknown-result resolution remain pending.',
            }} if action_id == 'BANK-A05' else {}),
            **({'native_conditional_financing': {
                'input_producer': 'integration.bank_financing_development:build_bundle(credit_condition_outcomes=...)',
                'standalone_option': '--credit-condition-outcomes <JSON>',
                'shared_option': '--bank-credit-condition-outcomes <JSON>',
                'initial_source': 'Independent synthetic verified satisfied/unsatisfied template outcomes, declared before '
                    'sealing. Existing verifier, evidence, scope and authority remain exact; not runtime supplementation.',
                'actual_check': 'output/integration/bank_conditional_offer_checks_20261017_01/cases/'
                    'test_actual_conditional_offer_0/runtime/checks.json',
                'actual_chain': 'Two native ticks/four projects: A02 accepts, Bank A A03 conditional -> A04 conditional_offer, '
                    'original OWN-A05 excludes A and selects B -> actual selection reception -> four original Bank B A05 '
                    'confirmations. Two later Bank requests and two later Owner requests consume actual earlier feedback; '
                    'the four Bank A conditions stay unsatisfied. Unverified, dependency-unknown and revoked-authority '
                    'boundaries and selection redelivery are checked without another business run.',
                'limits': 'Shared input/schema/manifest verified only. Shared default A01 pauses quotations after own '
                    'selection; if every remaining offer has unmet conditions, the original Owner result stays unresolved '
                    'where the native selection call allows only bank selection or equity. No condition cure, new verifier, '
                    'registered arrangement, cash execution, shared business pass or full regression is inferred.',
            }} if action_id in {'BANK-A03', 'BANK-A04', 'OWN-A05', 'BANK-A05'} else {}),
            **({'native_financing_recovery': {
                'implementation': 'integration.bank_financing_native_recovery:saved_financing_preflight',
                'original_call': 'BankFinancingApplication.recover_saved_proposal via the existing '
                    'GbaV1AgentClient.recover_proposal and NativeRouteAgentClient error query; no engine restart.',
                'standalone_options': ['--allow-saved-recovery', '--query-saved-financing-on-error',
                    '--continue-unstarted-actions-on-error'],
                'shared_options': ['--allow-bank-financing-saved-recovery', '--query-saved-financing-on-error',
                    '--continue-unstarted-bank-financing-actions-on-error'],
                'saved_results': 'Preflight the exact registered prefix, original request/source bytes, current grants, '
                    'all original snapshots/versions/readings and completed results before any technical finalization. '
                    'Only a genuine A02 decline or a complete original quotation chain can return a native response; '
                    'an accepted intake without quotation cannot start later actions in this query.',
                'unstarted_stage': 'Reuse execute_original_stage and the original worker registered execution claim. '
                    'Within the still-open call, only unchanged revision-zero work whose preparation has not started '
                    'can execute once; preparing/unknown work is not retried.',
                'pending': 'Original needs_information/unsupported/deferred results persist as waiting_input with '
                    'their exact original condition and result digest after current source/authority revalidation. '
                    'The original native financing call still stops without an approval/refusal fallback.',
                'actual_check': 'output/integration/bank_financing_continuation_checks_20261017_01/checks.json',
                'actual_business': 'Two native ticks/four projects: one saved A04 offer and one saved A02 refusal '
                    'returned to their original calls, one proven-unstarted A03 executed once, four actual A02 refusals '
                    'and four selected-bank A05 confirmations. Two later A02 requests consume earlier actual refusal. '
                    'Saved original results and snapshots remain unchanged. Four concentrated checks passed, including '
                    'accepted-but-unquoted, preparing-without-result and actual product-scope needs_information.',
                'limits': 'All options default off. Optional A01 is checked as a predecessor; its recovery fault '
                    'combination, shared business and checkpoint combinations remain pending. This is technical '
                    'result continuation, not material supplementation: new application versions, independent new '
                    'evidence/authority and actual supplement reception still need source-backed adapter assembly. '
                    'No formal facility, cash execution or receipt is created.',
            }} if action_id in {'BANK-A01', 'BANK-A02', 'BANK-A03', 'BANK-A04'} else {}),
            **({'native_unconfirmed_arrangement_feedback': {
                'implementation': 'BankArrangementApplication.prior_reviews -> bank_financing_strategy.selection_feedback '
                    'with BankStrategyFeedback.basis=unconfirmed_arrangement_review -> original BANK-A01 -> BANK-A04',
                'standalone_options': ['--with-owner', '--with-bank-strategy', '--with-arrangement',
                    '--with-unconfirmed-arrangement-feedback', '--arrangement-principal-limits <JSON>',
                    '--arrangement-capacity-limits <JSON>'],
                'shared_options': ['--with-unconfirmed-arrangement-feedback', '--bank-arrangement-principal-limits <JSON>',
                    '--bank-arrangement-capacity-limits <JSON>'],
                'initial_source': 'Explicit independent formation-authority principal limits, finite nonnegative decimal '
                    'strings. Each declared limit has its own initial synthetic Evidence; no runtime A04/capacity rewrite. '
                    'Optional A05 current commitment-capacity limits use a distinct LendingCapacity reference and '
                    'explicit assumed Evidence, preserve the original A04 capacity and reference its unchanged portfolio.',
                'review_reader': 'Authenticate strictly earlier actual own selection, original formed A05, original '
                    'acceptance/quote sources and current A05 grants/readable references. Missing/unformed results stop. '
                    'Confirm is excluded from the unconfirmed count; decline/requote remain private review outcomes.',
                'actual_check': 'output/integration/bank_unconfirmed_review_checks_20261017_01/checks.json',
                'actual_business': 'Two native ticks/four projects: Bank A receives actual selection then original A05 '
                    'independently declines twice under initial zero formation limit. Two later A01 requests consume '
                    'their own same-borrower refusal review, select the restricted strategy, and original A04/native macro '
                    'reject new quotations. Bank B is subsequently selected and its two original A05 reviews confirm. '
                    'Old native selections remain unchanged. Historical current-source queries and revoked A05 reads '
                    'are rejected; the strict confirmed-arrangement reader still rejects the earlier declines.',
                'actual_requote_check': 'output/integration/bank_requote_feedback_20261017_01/checks.json',
                'actual_requote_business': 'Two native ticks/four projects: initial independent A05 capacity limit '
                    'zero causes original Bank A A05 to requote twice after actual own selections and original '
                    'Owner acceptances. Two later original A01 decisions consume those same-borrower requote '
                    'reviews, choose the restricted strategy, and original A04 declines new quotes. Bank B is '
                    'selected for the new projects and confirms twice. Forty original micro results/168 formed '
                    'tasks; original A04 capacity and portfolio references unchanged. Original principal-limit '
                    'decline branch also passes. Confirmed-only reader rejects both kinds; original A05 revocation '
                    'rejects history. Eight-role shared initial assembly passes with no business ticks/tasks.',
                'limits': 'Existing default selected-count/confirmation chain remains separate and passed compatibility. '
                    'Representative shared requote business with same-call credit continuation and completed-tick restart is verified in shared_business_recovery_case. Other missing-result and configuration combinations '
                    'remain pending. New-business restriction does not resolve the old review, communicate a new '
                    'borrower acceptance, register a facility, withdraw actual selection or move cash.',
            }} if action_id in {'BANK-A01', 'BANK-A04', 'BANK-A05'} else {}),
            **({'native_financing_outcome_query': {
                'bank_entry': 'bank.query_native_outcome(original_terminal_identity, organization_id=own_id, tick=current_tick)',
                'owner_entry': 'bank.owner.query_native_outcome(original_identity, organization_id=own_id, tick=current_tick)',
                'implementation': 'integration.financing_native_outcome_query',
                'evidence': 'output/integration/financing_outcome_query_20261017_01/checks.json',
                'verified_chain': 'Actual original Bank A02 refusal and A04 quotation plus Owner A05 selection over two ticks/four projects. Before original native execution queries return unknown; afterwards they read the exact original scoped event, saved private result, snapshots, proposal/final and own recipient projection. Duplicates preserve tasks/events.',
                'authority': 'Every original stage and original Owner history are checked against current grants at the actual query tick; original invocation times remain unchanged. Revocation and wrong organization/time/identity are rejected; default later history remains strictly earlier.',
                'limits': 'Indicative native financing decisions and Owner selection only. No registered application supplement receipt, formal loan, signed arrangement, reservation, drawdown, disbursement, cash receipt, debt clearance, replay or new submission. Shared/restart/model combinations and concentrated regression remain pending.',
            }} if action_id in {'BANK-A02','BANK-A04','OWN-A05'} else {}),
            **({'native_financing_actor_binding': {
                'authority': 'Original OrganizationRegistry actor ownership and per-action grants; native Bank/Owner '
                    'agents, financing parties, project selectors and task organization IDs stay organizational.',
                'standalone_option': '--organization-actor-ids <JSON>',
                'shared_option': '--bank-actor-ids <JSON> (the two original Banks only)',
                'shared_regulatory_combination': 'May coexist with --government-actor-ids for the original two agencies. Scoped actual business and initial-source checks are recorded in output/integration/shared_government_actor_20261017_01/manifest.json; other role actors, monthly strategy, restart and model combinations are not implied.',
                'actual_check': 'output/integration/financing_actor_checks_20261017_01/checks.json',
                'actual_business': 'Distinct actors for two Banks and two Owners: two ticks/four projects, 40 original '
                    'micro results, 168 formed technical tasks, four actual selections/four private A05 confirmations '
                    'and later Bank consumption of exact earlier confirmations. Another actor cannot reuse the grants.',
                'shared_assembly': 'Eight roles at tick zero, no business tasks. Initial support Bank identities may '
                    'be synchronized only without executable grants or an existing actor payload; source files and '
                    'active actors are not rewritten. Monthly sources separately pass original authorization assembly.',
                'limits': 'No saved-history migration, substituted signature, registered loan, cash execution, '
                    'actual monthly strategy run or full regression is inferred. Distinct-actor shared evidence is recorded separately and does not replace these standalone results.',
            }} if action_id in {'BANK-A01','BANK-A02','BANK-A03','BANK-A04','BANK-A05','OWN-A05'} else {}),
            **({'native_financing_material_boundary': {
                'evidence': 'output/integration/bank_unconfirmed_review_checks_20261017_01/supplement-boundary.json',
                'reviewed_call': 'SimulationEngine._arrange_project_financing -> BankAgent.consider_financing',
                'actual_inputs': ['requested_amount', 'borrower_financial_capacity', 'project_risk', 'financing_condition_index'],
                'detailed_component': 'validate_received_owner_application requires actual registered application/version, '
                    'original Owner apply result, observed independent registration/reception and exact disclosure mapping.',
                'boundary': 'The reviewed synchronous call has no material/application-version payload or supplement '
                    'reception step. Scalar proposal inputs and a local changed file do not prove a received supplement. '
                    'Locate an equivalent original receiver and versioned source/authority binding before detailed '
                    'supplement continuation. Preserve waiting_input and continue other supported chains; this is '
                    'not a claim that the macro globally lacks financing capabilities.',
            }} if action_id in {'BANK-A02', 'OWN-A05'} else {}),
            **({'existing_bridge': {
                'implementation':'integration.contractor_formation_native:ContractorFormationNativeApplication',
                'input_producer':'integration.contractor_formation_native_development:build_bundle',
                'scope':'integration.contractor_formation_native_sources:formation_scope',
                'supported_choices':['accept','revise'],
                'verified_choices':['accept','revise'],
                'native_mapping':{'accept':'accept_terms','revise':'request_revision'},
                'trigger':'Actual current decide_contract_terms for the selected Contractor in an open native negotiation.',
                'sources':'Independently declared initial bid, detailed terms, qualifications, crew, old commitments, '
                    'cash, restrictions, old payables and forecasts. Actual native parties, price, explicit HKD declaration '
                    'and programme duration are checked. No Owner acceptance is prewritten.',
                'final_confirmation':'One original completed A04 result and its transported proposal are reused by '
                    'the exact current project/tick/party contract_negotiation bounded decision.',
                'feedback_consumer':'integration.contractor_formation_native_sources:prior_negotiations authenticates '
                    'strictly earlier own native posture, original micro result, proposal and final confirmation. '
                    'An explicit private acceptance-count preference can request one independently permitted price revision.',
                'progress_payment_feedback':{
                    'reader':'integration.bindings.gba_v1_progress_payments:read_own_progress_payments',
                    'enable':'Optional max_prior_owner_payment_delays; standalone/shared --max-prior-owner-payment-delays N',
                    'semantics':'Count only strictly earlier actual delayed requests of this Contractor and the current '
                        'Owner. Match each native payment_delayed to its original payment_requested once. '
                        'The explicit private risk preference selects an independently permitted price-review request; '
                        'original A04 and the unchanged native negotiation process decide and record the result.',
                    'evidence':'output/integration/implementation_20261016_29/checks.json',
                    'observed':'Original native construction emits a delayed 200000 request at tick 1; original A04 at '
                        'tick 2 reads its exact own source Evidence, revises, and native contract_negotiation records '
                        'request_revision. Same actual delay with the preference disabled and an approved-request '
                        'control both retain original acceptance. Existing cash, debt and detailed capacity stay unchanged.',
                    'sources':'Independent existing construction/contract/progress/engagement and Owner payment reliability 0. '
                        'Explicit seed 3 is used for the delayed scene, seed 42 for approved; no RNG, event or state replacement.',
                    'shared_status':'Eight-role 79-input composition assembled at tick 0 with no business tasks; no shared delayed outcome claimed.',
                    'limits':'Historical delay is not proof of current unpaid debt. Native amounts retain native_contract_sum_unit '
                        'and no currency conversion, QS certificate, cash transfer, receipt or debt clearance is inferred. '
                        'Full fulfillment, closeout and overall regression remain pending.'},
                'construction_suspension_feedback':{
                    'reader':'integration.bindings.gba_v1_construction_suspensions:read_own_construction_suspensions',
                    'enable':'Optional standalone/shared --max-prior-construction-suspensions N',
                    'producer':'Unchanged ProjectLifecycleEngine._handle_construction publishes project_suspended.',
                    'semantics':'Strictly earlier own actual event, exact global/project logs, dated main contract and '
                        'Contractor engagement covering the original event. The independently declared private preference '
                        'asks original A04 to review an independently permitted price change for future terms.',
                    'evidence':'output/integration/implementation_20261016_51/checks.json',
                    'limits':'Aggregate safety/quality suspension contains no party author, detailed metrics, inspection '
                        'or cause attribution. No Owner/Supplier fault, physical execution, release, cash, debt clearance '
                        'or complete original A12 continuation state is inferred. Current-party query is not an external receipt.'},
                'standalone_evidence':'output/integration/development_contractor_terms_20261016_05/runtime/result.json',
                'shared_evidence':'output/integration/development_shared_terms_20261016_02/runtime/result.json',
                'actual_tender_upstream':{
                    'entry':'integration.contractor_selected_tender_sources:query_selected_tender_sources',
                    'guard':'integration.contractor_selected_tender_sources:validate_formation_original_bid',
                    'enable':'QS generator --with-native-owner-selection --with-original-bid-history declares '
                        'future own A04 history grants before input hashing; A04 plan original_tender_request_id '
                        'opts into actual submitted-draft/programme/cost/quantity preservation.',
                    'evidence':'output/integration/tender_contract_continuity_20261017_01/checks.json',
                    'state':'Actual native bid/evaluation/Owner-selection sources are joined to their original '
                        'A02 result and audit witness. A04 source guard is installed; exact draft/source '
                        'preservation is checked. The earlier four-tick source-query case does not execute A04.',
                    'actual_tender_to_signature':{
                        'projection':'integration.contractor_tender_formation_projection:project_original_tender_formation',
                        'composition':'integration.contractor_tender_formation_development:build_bundle',
                        'option':'A04 plan original_tender_projection with original_tender_request_id',
                        'evidence':'output/integration/actual_tender_formation_20261017_01/checks.json',
                        'observed':'Eight native ticks on one initially tendering project: two actual A02 bids, '
                            'original QS-A06, native Owner selection, original A04 accept, native Owner award '
                            'and native signature at tick 8. Independent initial terms file remains byte unchanged.',
                        'sources':'Exact original bid/programme/cost/quantity/resource witness; readonly accepted '
                            'submission view bound to original native bid event and original request ID; actual '
                            'current occupancy only for [tick,tick+1), independent initial future calendar and funding.',
                        'limits':'Explicit offline synthetic input. No second submission command, detailed external '
                            'receipt, cash or detailed reservation effect. Native Owner award is not micro OWN-A10. '
                            'Same-project supply and aggregate construction/payment handling are now linked below. '
                            'Detailed fulfillment, downstream feedback and new shared/model/restart combinations remain pending.'},
                    'actual_downstream_supply_payment':{
                        'composition':'integration.tender_fulfillment_development:build_bundle',
                        'evidence':'output/integration/tender_fulfillment_continuity_20261017_01/checks.json',
                        'observed':'One initially unselected tendering project: native signature tick 8, original '
                            'Supplier A01-A04 and Contractor A05 then native selection tick 9, construction tick 10, '
                            'actual payment request and original OWN-A06 negotiate tick 12. Seventeen original '
                            'micro results and 182 formed technical tasks. All initial input bytes unchanged.',
                        'sources':'Both possible original bidders have independent initial procurement and private '
                            'payment sources. Supplier plan contractor_id requires actual earlier native award; '
                            'common plan_for_scope lookup selects the actual current buyer. Payment plan '
                            'native_contractor_id filters actual event recipients and direct recovery. Source '
                            'namespaces are authored before sealing; no runtime agreement rewriting.',
                        'limits':'Explicit offline synthetic initial design quality 0.9; original computed quality '
                            'and 20-percent payment threshold retained. Unselected buyers and tick-11 payment '
                            'plans stay untriggered. No actual delay occurred. Thirteen existing native '
                            'validation_only/engagement_status diagnostics are retained. No detailed delivery, '
                            'certificate, cash or debt clearance; later feedback, closeout and broader combinations remain.'},
                    'limits':'Private preferred-bidder evidence is not a detailed SubmissionExecution receipt '
                        'or effective agreement. Signature is proved separately by the native contract event. '
                        'Old initial-selected-bid A04/Owner/signature compatibility passed separately; '
                        'it is not the new-project signature evidence.'},
                'observed':'Original A04 accepts the first terms and revises the followup after consuming its own actual '
                    'earlier posture. Native Owner then accepts the first award and the native lifecycle signs it at tick 3; '
                    'the revised followup has no contract. Original cash/capacity checks pass and allocation output preserves every field.',
                'limits':'Initial selected bids are not current tender selection. Default composition retains native '
                    'Owner award; optional original OWN-A10 is documented separately. Negotiation posture is not a '
                    'detailed effective agreement, reservation or payment. '
                    'Reject and unresolved outcomes are not mapped to revision or a fallback answer; full lifecycle/regression remain pending.',
            }} if action_id=='CONTRACTOR-A04' else {}),
            **({'existing_bridge': {
                'implementation':'integration.owner_award_native:OwnerAwardNativeApplication',
                'input_producer':'integration.owner_award_native_development:build_owner_sources',
                'enable':'--with-owner-award (requires --with-contractor-formation)',
                'scope':'integration.owner_award_native_sources:award_scope',
                'micro_choices':['accept','revise'],
                'native_mapping':{'accept':'accept_contract','revise':'request_contract_revision'},
                'sources':'Actual strictly earlier original Contractor A04 acceptance, transported proposal/final and '
                    'native negotiation event. The original complete public Contractor agreement must exactly match '
                    'the independently reviewed initial correspondence, including programme, payment, clause and '
                    'other versioned references. Original authority is retained; private Contractor cash/crew inputs '
                    'are not disclosed. Owner independently declares project award budget and management pools.',
                'execution':'Original Owner assembler/worker evaluates exact parties, agreement, actual received '
                    'acceptance, authorized budget, old commitments and original capacity method. An unmet '
                    'condition cannot become native unconditional acceptance. Same result is reused by proposal '
                    'and final owner_contract_award; native signature remains a later original lifecycle step.',
                'feedback_consumer':'integration.owner_award_native_sources:prior_owner_awards correlates own '
                    'strictly earlier actual award events, original OWN-A10 result and proposal/final. Explicit '
                    'max_prior_owner_accepts can select an independently permitted price-revision request.',
                'standalone_evidence':'output/integration/development_owner_award_20261016_05/runtime/result.json',
                'shared_evidence':'output/integration/development_shared_award_20261016_02/runtime/result.json',
                'observed':'Three ticks, two original A04 and two original OWN-A10 actions, 60 formed technical tasks. '
                    'First Owner accepts at tick 2 and macro signs at tick 3; later Owner reads that earlier '
                    'actual decision and requests revision at tick 3, with no later project contract.',
                'shared_observed':'Four native ticks, 79 frozen input files, 78 original micro actions across eight '
                    'roles and 268 formed technical tasks. Actual OWN-A10 acceptance at tick 2 precedes native '
                    'signature at tick 3 and original Supplier A01-A04 / Contractor A05 actual award consumption '
                    'and native supplier selection at tick 4. Later OWN-A10 requests revision after its own actual '
                    'earlier feedback. Independent initial supply-first remains natively suspended; task completion '
                    'does not establish all project success or detailed fulfillment.',
                'limits':'Initial selected bids are assumptions, not current Owner bid-selection execution. '
                    'Native aggregate signature is not detailed contract-core effectiveness, physical resource '
                    'reservation, debt or cash execution. Reject/unresolved are not disguised as revision. '
                    'Detailed formation and recovery remain pending.',
            }} if action_id=='OWN-A10' else {}),
            **({'shared_assembly': {
                'implementation': 'integration.financing_professional_native:FinancingProfessionalApplication',
                'input_producer': 'integration.financing_professional_development:build_bundle',
                'optional_regulatory_supply_sources': 'integration.financing_professional_execution_sources:extend_sources',
                'enable_regulatory_supply': '--with-government-and-supply',
                'enable_government_private_feedback': '--with-government-feedback',
                'enable_original_owner_opportunity': '--with-owner-opportunity',
                'enable_initial_payment_case': '--with-payment-project --max-prior-payment-requests N',
                'enable_original_contractor_terms':'--with-contractor-formation --max-prior-accept-terms N',
                'enable_original_owner_award':'--with-owner-award --max-prior-owner-accepts N (requires formation)',
                'enable_original_owner_invitation_tender':'--with-contractor-tender',
                'enable_tender_feedback':'--with-contractor-tender --with-tender-feedback',
                'tender_evidence':'output/integration/development_shared_tender_feedback_20261016_01/runtime/result.json',
                'tender_observed':'Three native ticks, 121 frozen inputs, 85 original micro actions across eight roles '
                    'and 261 formed technical tasks. Original OWN-A09 produces both invitations; original A01/A02 '
                    'submit twice at tick 2, then each consumes its own earlier actual submission and declines '
                    'the staggered project at tick 3. PGEN0001 and PGEN0002 reach design after native financing '
                    'and appointment. Final canonical monthly-unit annotation and extension-removal pin have '
                    'separate current assembly/borrowed-cleanup evidence at tick 0, not a later full-window run.',
                'tender_sources':'integration.owner_invitation_development:build_bundle authors original OWN-A09 '
                    'and Contractor A01/A02 sources with final shared identities and clock before hashing. '
                    'Optional feedback uses two explicitly scoped staggered projects.',
                'tender_runtime':'Original tender host borrows the one shared authority, registry, journal and writer lock. '
                    'Original Owner invitation wraps the shared decision dispatcher; original tender final wraps that '
                    'invitation handler. Install every route before sealing; failures never invoke the native fallback.',
                'tender_candidate_boundary':'Owner sources cover the complete original candidate set. Other original shared '
                    'Contractors have registered identity but no invitation permission or inferred eligibility. '
                    'Tender Contractors keep independently declared professional sources and capacity.',
                'tender_limits':'Initial synthetic budgets, qualification, calendar, quantities, prices and indicators are '
                    'assumptions. Actual invitation and bid effects remain native. Four-tick extensions also need '
                    'other project request plans and retain the frozen preferred-bidder field conflict.',
                'enable_same_project_signature_supply':'--with-contract-supply-handoff (requires formation and Government/Supplier composition)',
                'signature_supply_reader':'integration.native_contract_supply:signed_contract_for_supply',
                'signature_supply_evidence':'output/integration/development_contract_supply_20261016_02/runtime/result.json',
                'signature_supply_observed':'Four ticks, 76 original micro results across eight roles and 264 formed '
                    'technical tasks. terms-first has no initial contract or supplier: native signature at tick 3 is '
                    'consumed by both original Supplier A01-A04 chains and original Contractor A05 at tick 4, '
                    'then native supplier selection executes. Mobilization and detailed delivery remain pending. '
                    'Later A04 reuses the native wire request ID at a distinct original tick-scoped task. '
                    'The independent initial supply-first case is natively suspended for defect_rate above 0.75; '
                    'formed technical tasks do not mean every project succeeds.',
                'signature_supply_sources':'Original immutable global/project award event and signed-contract summary. '
                    'Additional initial commercial views declare two panels, cost 8 HKD/unit, 25% markup, '
                    '20 HKD offer, 10 HKD working-capital plan and 30 HKD procurement ceiling. Supplier cash '
                    'remains the same initial 1000 HKD. Prewritten independent buyer consent is a declared '
                    'private initial source, not a future Contractor choice, formal SupplyOrder or cash execution.',
                'initial_sources': 'Government/Supplier final identities and clock are bound before material, method, '
                    'agreement and draft digests. Owner opportunity and financing share initial-owner-funding.json. '
                    'The explicit scenario investment-region preference follows independent professional service scopes; '
                    'professional object types and appointment timing are supplied before runtime and checked against native facts.',
                'runtime': 'One native engine, organization/authorization snapshot, action registry, task store and business clock.',
                'routing': 'Explicit disjoint proposal/final ownership; both original receipt dispatchers retain recipient isolation. '
                    'All handlers are installed before any application seals its immutable client implementation.',
                'status': 'shared_synthetic_initial_business_subset_executed',
                'evidence': 'output/integration/development_shared_opportunity_20261016_06/runtime/result.json',
                'payment_feedback_evidence': 'output/integration/development_shared_payment_20261016_02/runtime/result.json',
                'contract_terms_evidence':'output/integration/development_shared_terms_20261016_02/runtime/result.json',
                'contract_terms_observed':'Seven declared initial projects; three ticks, 62 original micro results across '
                    'eight roles and 208 formed technical tasks. PGEN0001 reaches design after actual financing/appointments. '
                    'The first terms project is signed by the native lifecycle at tick 3; the followup consumes actual '
                    'earlier own A04 posture and requests revision without signing. Later OWN-A03 decisions read one '
                    'then two actual earlier own payment requests. Six applications share one authority and journal.',
                'extended_window_configuration':'The native generator includes initial projects in its horizon target. '
                    'The three-tick bundle declares a first-tick opportunity target while preserving two additional '
                    'active-project slots; input-provenance.json records the initial values. This does not promise future creation.',
                'payment_feedback_observed': 'Five explicit initial cases and the same five shared applications complete '
                    'two ticks with 56 original micro results. All four later original OWN-A03 decisions consume '
                    'one strictly earlier actual own progress-payment request and reject under the explicit request-count '
                    'preference; the supplied initiation-count limit 999 is not reached. Native approved status is not cash execution.',
                'observed': 'Two native ticks, 56 original micro action results across all eight roles, actual PGEN0001 '
                    'creation/financing/appointment and transition to design; later Owner opportunity uses its prior actual creation.',
                'limits': 'Assembly evidence alone does not prove execution, feedback consumption or full lifecycle coverage. '
                    'Optional approval and contract-preparation cases are explicit initial assumptions, not generated '
                    'project history or evidence of completed micro design, tender, signature or finance execution.',
            }} if action_id in {'BANK-A01', 'BANK-A02', 'BANK-A03', 'BANK-A04', 'BANK-A05', 'OWN-A03', 'OWN-A05', 'OWN-A04',
                'ARCHITECT-A02', 'ARCHITECT-A03', 'ENGINEER-A02', 'ENGINEER-A03', 'QS-A02', 'QS-A03',
                'GOV-A02', 'GOV-A04', 'GOV-A07', 'GOV-A12', 'SUPPLIER-A01', 'SUPPLIER-A02', 'SUPPLIER-A03', 'SUPPLIER-A04',
                'CONTRACTOR-A01', 'CONTRACTOR-A02', 'OWN-A09', 'CONTRACTOR-A04', 'CONTRACTOR-A05'} else {}),
            **({'native_progress_payment_position': {
                'input_producer': 'integration.progress_payment_development:shared_initial_sources',
                'enable': 'financing_professional_development --with-payment-positions; choose the existing initial '
                    'construction case (--with-payment-project and its Owner opportunity options), or explicitly '
                    'bind one already declared project with --payment-position-project-id.',
                'runtime': 'Existing NativeLifecycleApplication; same shared authority, registry, source guard and durable task store. No new executor.',
                'trigger': 'Actual payment_requested -> original OWN-A06 negotiate; actual payment_delayed -> original CONTRACTOR-A10 review of an independently declared disputed obligation.',
                'sources': 'Independent initial private obligation amounts/payable are unknown. Contractor payment history is explicitly incomplete; its original processor retains needs_information instead of claiming a completed dispute. HKD is a separate declared contract unit, not conversion of native request amounts.',
                'observed': 'Earlier shared two-tick native business completed: eight roles, 65 completed original micro actions, 179 formed technical tasks. Owner A06 read exact actual request evidence and formed negotiate. No delay occurred, so Contractor plan remained not_started. Actual later multi-window delay evidence follows below.',
                'business_evidence': 'output/integration/progress_payment_positions_development_20261017_01/checks.json',
                'contractor_key_behavior': 'Original A10 returns needs_information/complete_current_original_payment_history and remains unresolved. The earlier isolated synthetic delay check was not real native delay proof; the multi-window actual run below now supplies that proof without completing the missing history.',
                'multi_window_trigger': {
                    'implementation':'integration.native_progress_payment_trigger:payment_trigger_origin',
                    'enable':'--progress-payment-ticks 1 2; initial --random-seed 1 --owner-payment-reliability 0',
                    'semantics':'Independent initial contexts, grants and sources are declared per payment tick before sealing. '
                        'Only actual events trigger work. A delay is tied to exactly one earlier same-project/tick/parties/amount '
                        'native request, authenticated against both native logs; it is not a second payment.',
                    'business_evidence':'output/integration/shared_payment_feedback_checks_20261017_03/checks.json',
                    'observed':'Actual three-tick shared business: eight configured roles, four actual micro roles, '
                        '42 completed original micro actions and 171 technical tasks. Tick-two delay triggers original '
                        'Owner negotiate and Contractor A10 needs_information, with lifecycle unresolved and task waiting_input. '
                        'Four later original Owner A03 decisions read the exact delayed request and delay, followed by actual '
                        'native non-initiation. The earlier same-tick contract acceptance is preserved.',
                    'verification':'Original retained outputs and read-only original journal verified after correcting a '
                        'test assertion that confused lifecycle unresolved with task waiting_input. Business was not replayed. '
                        'New duplicate-event/forged-event runtime assertions remain for concentrated regression.',
                },
                'existing_project_target': {
                    'enable':'--payment-position-project-id supply-followup --progress-payment-ticks 3 4; '
                        'combine with the existing four-tick Government/Supplier and contract/supply window.',
                    'implementation':'financing_professional_development.build_bundle; '
                        'native_progress_payment_trigger.payment_trigger_origin; NativeLifecycleApplication v12',
                    'source':'Explicit target project and its declared Owner/selected Contractor, independent private '
                        'positions and grants. No replacement initial construction project is inserted. Runtime '
                        'payment evidence authenticates earlier actual signature and supplier-selection events '
                        'against both native logs and the original native signed contract. Initial declarations '
                        'alone produce no executed signature/selection origin; Supplier private task IDs are not disclosed.',
                    'evidence':'output/integration/shared_supply_payment_checks_20261017_01/checks.json',
                    'observed':'Four native ticks, eight actual micro roles, 148 original micro results and 367 formed '
                        'technical tasks. In supply-followup: actual signature tick 1, original Supplier A01-A04 and '
                        'Contractor A05 followed by actual supplier selection tick 2, native construction transition '
                        'tick 3, payment_requested tick 4 and original OWN-A06 negotiate reading the exact lineage. '
                        'Tick-3 payment plans remain untriggered. Changed native signature is rejected.',
                    'native_diagnostics':'22 frozen-native invalid_action events remain. '
                        'ProjectLifecycleEngine._validate_representative_actions supplies engagement_status in '
                        'validation-only action data; ActionValidator.validate rejects that reserved key. The reviewed '
                        'local path bypasses the external final provider. Preserve diagnostics and macro source; '
                        'do not label this a diagnostic-free full lifecycle.',
                    'limits':'Selected initial commercial terms are independent scenario inputs. This does not prove '
                        'one newly tendered project completed every stage, detailed production/logistics, independent '
                        'QS measurement/certification, cash execution or complete payment history. This actual target '
                        'had no delay; its Contractor A10 remains untriggered. Other target/horizon combinations '
                        'and full regression remain pending.',
                },
                'limits': 'Private processing only; no formal payment/measurement/certificate submission, external chase '
                    'message, bank transfer, receipt, derived debt/cash or obligation release. Complete detailed payment '
                    'history remains missing; other windows, formal execution and broader combinations remain pending.',
            }} if action_id in {'OWN-A06', 'CONTRACTOR-A10'} else {}),
            **({'actual_new_tender_closeout_later_owner_consumer': {
                'composition': 'integration.tender_closeout_followup_development:build_bundle',
                'evidence': 'output/integration/tender_closeout_followup_20261017_01/checks.json',
                'observed': 'One initially unselected tendering project reaches original native signature tick 8, '
                    'supplier selection 9, completion 22, six original final-account actions at 23 and native '
                    'settlement/closure with original QS-A12 at 24. Original native generation then supplies '
                    'four actual Owner opportunities at 25. Four original OWN-A03 results consume the exact '
                    'own settlement and native final decisions defer; one aggregate native non-initiation '
                    'event and no new project. Thirty-two original micro results, 465 formed tasks.',
                'implementation': 'TenderFormationComposition v2 optionally installs the existing '
                    'OwnerOpportunityApplication, shares the exact authority/registry/store, routes original '
                    'Owner proposal/final decision and seals after the existing tender wrappers.',
                'sources': 'Original supplied-agent default generation mode with max_active_projects=1 and '
                    'target_project_count=2; no second initial project or injected future opportunity. '
                    'Independent original A03 template, cost author is the actual QS and schedule author '
                    'is an initially declared Architect. Cash/restricted cash match initial template scale; '
                    'aggregate settlement retains not_proven payment and obligation-clearance statuses.',
                'verification': 'Actual business and primary assertions completed. Direct provider re-entry '
                    'then correctly raised already-claimed; test had incorrectly expected cached proposal '
                    'return. Expectation fixed; retained original results, exact task records, native events '
                    'and final decisions checked read-only without replay. Driver exit remains 1; revised '
                    'pytest and following foreign-party/future-tick assertions were not executed.',
                'limits': 'Explicit offline synthetic source assumptions; native Government and Owner award '
                    'are not micro actions. Thirty-five existing frozen local validation_only diagnostics '
                    'retained. No cash receipt, cleared debt, detailed handover/certificates or capability '
                    'change. Broader shared/model/restart combinations and full regression remain.',
            }} if action_id in {'OWN-A03','CONTRACTOR-A04','QS-A12'} else {}),
            **({'actual_new_tender_to_native_closeout': {
                'composition': 'integration.tender_closeout_development:build_bundle',
                'evidence': 'output/integration/tender_closeout_continuity_20261017_01/checks.json',
                'observed': 'One initially unselected tendering project: two actual bids, original A04 and native '
                    'signature at tick 8, supply selection at 9, construction, five actual payment requests and '
                    'original OWN-A06 consumers, native completion at 22, six original final-account communication '
                    'actions at review tick 23, native settlement and original QS-A12 record_feedback at 24. '
                    'Twenty-eight original micro results, five communication receipts and 389 formed tasks.',
                'sources': 'Independent initial private sources for both possible bidders and review windows. '
                    'Namespaced final-account source helper shifts positive business times and explicit message '
                    'ticks before sealing. Actual selected Contractor filters both dispatch and direct event '
                    'reading. Native Government reviewer profile and original native decisions are declared '
                    'initially, without a prewritten approval or micro Government action.',
                'verification': 'Original business completed early at tick 24; pytest then failed an incorrect '
                    '26-tick equality assertion. Corrected to allow original all-projects-closed termination. '
                    'Separate read-only audit verifies original global/project event hashes, original worker '
                    'results, actual QS settlement feedback and original QS-A09 dependency, unchanged initial '
                    'input/database, and untriggered losing bidder. Wrong-party early guard separately checked '
                    'as a predicate, not through the closed original live authority. One original unknown-send '
                    'compatibility pytest passed; default source generator comparison is byte-equivalent.',
                'limits': 'Explicit offline synthetic scenario. Thirty-five existing frozen native local '
                    'validation_only/engagement_status diagnostics retained. No actual delay, detailed delivery, '
                    'certificate, cash, debt discharge, complete handover, judgment/capability change inferred. '
                    'Revised main pytest, broader shared/model/restart combinations and full regression pending.',
            }} if action_id in {'CONTRACTOR-A04','OWN-A06','CONTRACTOR-A11','QS-A09','QS-A12'} else {}),
            **({'native_final_account_position': {
                'implementation': 'integration.bindings.gba_v1_final_account_positions',
                'configuration': 'NativeLifecyclePlan.final_account_disclosure: explicit recipient_ids and fields=choice_and_note',
                'shared_input_producer': 'integration.final_account_discussion_development:shared_initial_sources; financing_professional_development --with-government-and-supply --with-final-account-discussion',
                'shared_runtime': 'output/integration/shared_final_account_discussion_20261017_02/runtime/result.json',
                'trigger': 'Actual final_account_review_started after the native final_account_dispute room opens.',
                'original_action': 'Original OwnerPaymentActionAssembler and OwnerPaymentResultWorker; completed OWN-A06 dispute/negotiate only.',
                'execution': 'Existing InteractionSessionManager.append_message and actual original bus publication; no room creation or state mutation.',
                'receipt': 'query_final_account_position authenticates the durable send claim and retained native message/bus; unknown sends are never replayed.',
                'consumers': 'Actual selected Contractor/QS read addressed choice/note only. A subsequent original own action may consume the exact communication receipt as dependency Evidence. Explicit QS-A09 reception binds the delivered text and receipt Evidence into one original evidence question.',
                'actual_runtime': 'output/integration/final_account_position_checks_20261017_07/test_original_owner_position_u0/runtime/native-final-account-position.json',
                'interruption_runtime': 'output/integration/final_account_position_checks_20261017_07/test_original_owner_position_u1/runtime/native-final-account-position.json',
                'verification': 'Two targeted real-engine cases passed: dispute communication and later original Owner consumption; interrupted publication queried without duplicate delivery. Negotiate is coded, not business-validated.',
                'limits': 'Independent synthetic private obligations/instructions, not native-produced detailed debt. Contractor read access is not a Contractor action; QS processing is recorded separately. No agreement, revised terms, settlement, transfer, received cash or released obligation.',
            }} if action_id == 'OWN-A06' else {}),
            **({'native_final_account_questions': {
                'implementation': 'integration.bindings.gba_v1_final_account_positions',
                'configuration': 'NativeLifecyclePlan.final_account_question_reception declares message_tick, receipt evidence_ref and question_ref. publish_question_text defaults false and explicitly enables native question-text delivery.',
                'shared_input_producer': 'integration.final_account_discussion_development:shared_initial_sources; financing_professional_development --with-government-and-supply --with-final-account-discussion',
                'shared_runtime': 'output/integration/shared_final_account_discussion_20261017_02/runtime/result.json',
                'shared_observed': 'Two ticks, 61 original completed micro actions across all eight roles and 169 formed technical tasks. Three final-account actions and actual position/question communication coexist with generated project financing/appointments and four original professional-feedback records.',
                'trigger': 'Actual final_account_review_started; only the actual selected QS can consume one addressed Owner position at the declared tick.',
                'sources': 'Actual retained native Owner message/bus plus independent original QS contract, question prefix, request_evidence profile and initial authorizations. Source question must include separate unbound receipt Evidence.',
                'micro': 'Original QSFinalAccountActionAssembler and QSFinalAccountResultWorker consume the received text in the typed question and its exact receipt Evidence in source_reading. Private Owner input/result/obligation references are not copied.',
                'execution': 'With explicit disclosure, the exact formed original question text is published once through InteractionSessionManager.append_message to the actual Owner. Query authenticates the durable intent and retained message/bus; replay only queries.',
                'consumer': 'read_final_account_questions exposes only native messages addressed to the actual Owner. It does not expose QS private task, contract, response requirements or other recipients.',
                'actual_runtime': 'output/integration/final_account_reception_checks_20261017_02/test_original_owner_position_u2/runtime/native-final-account-position.json',
                'verification': 'Three targeted real-engine cases passed, including original QS-A09 request_evidence, exact received-text and receipt-hash consumption, actual question delivery/Owner read, wrong-recipient rejection and no duplicate delivery.',
                'limits': 'This is an evidence question, not supplied evidence, agreement, a determined final account or cash. Native aggregate settlement rules are unchanged. Initial final-account stage is an explicit assumption. Owner A06 question handling and Contractor private-history response are separately wired below; detailed fulfilment/finance and full regression remain pending.',
            }} if action_id == 'QS-A09' else {}),
            **({'native_three_party_final_account': {
                'implementation': 'integration.bindings.gba_v1_final_account_positions; integration.native_lifecycle_actions',
                'input_producer': 'integration.final_account_discussion_development:initial_sources(with_contractor=True); shared --with-final-account-discussion',
                'trigger': 'The actual native final_account_review_started event and its existing final_account_dispute room.',
                'flow': 'Original OWN-A06 dispute communicates to the actual Contractor/QS. Original CONTRACTOR-A11 consumes the addressed Owner note and separate receipt Evidence, partitions its independent unquantified disputed component, then communicates its formed propose_final_account choice/note to Owner/QS. Original QS-A09 consumes both actual received notes with distinct receipt Evidence and sends its formed evidence question to Owner. An original own Owner successor also consumes the native position receipt.',
                'privacy': 'No sender private source/task/obligation/component references are copied to recipients. Original closeout procedure limits Contractor recipients. Quoting received text cannot widen its actual original audience; actual selected parties and current original result/source versions are checked.',
                'receipt': 'Existing native append_message and bus publication with durable send claims. Duplicate deliveries query retained evidence only, without repeating workers or sends.',
                'actual_runtime': 'output/integration/three_party_final_account_checks_20261017_03/test_original_owner_position_u0/runtime/native-final-account-position.json',
                'verification': 'One new targeted actual-engine case passed: four original actions, three native communications, original Contractor consumption and original QS consumption of both parties, exact receipt Evidence and question text, recipient isolation and no repeated work/delivery.',
                'shared_assembly': 'output/integration/shared_three_party_final_account_20261017_02/runtime-assembly/lifecycle-assembly.json',
                'shared_status': 'Eight-role sources sealed; four lifecycle plans construct at tick zero with no tasks and the shared original registry/authority/store. Both clock ID and month unit match existing professional sources. New shared business execution remains pending concentrated integration.',
                'limits': 'Independent synthetic initial stage and detailed disputed components, not completed construction or native-produced debt. Choice/note delivery is communication only, not itemized final-account registration, agreement, settlement, cash, handover or release. Respond_settlement is admitted by the existing original worker/publisher but is not verified by this propose_final_account case.',
            }} if action_id in {'OWN-A06','CONTRACTOR-A11','QS-A09'} else {}),
            **({'native_owner_question_response': {
                'implementation': 'integration.native_lifecycle_actions:FinalAccountOwnerReception; integration.bindings.gba_v1_final_account_positions:receive_qs_question_for_owner',
                'input_producer': 'integration.final_account_discussion_development:initial_sources(with_owner_response=True); shared --with-final-account-discussion --with-final-account-response',
                'trigger': 'Actual original final_account_review_started, then actual addressed QS evidence question in the existing native room.',
                'flow': 'Owner original A06 consumes its own received QS question and distinct receipt Evidence, forms its declared dispute/negotiate decision, then sends choice/note back through the original native room. Quoted QS question is restricted to its original audience.',
                'original_sources': 'Independent initial private scope/obligation versions and a new A06 authorization. Existing disputed obligation ID and unknown due/paid/offset/payable values are retained; no new formal debt or determined amount is manufactured.',
                'rounds': 'QS may declare message_index at its original message_tick. The explicit ordinal selects its original addressed message even after later Owner positions append; missing/ambiguous undeclared selection is rejected.',
                'targeted_case': 'tests/test_native_final_account_positions.py::test_original_owner_position_uses_native_room_and_original_receipt[owner-responds-to-qs-question]',
                'limits': 'Receipt and negotiation only; no supplied supporting evidence, agreement, determined account, formal filing, payment or debt release. Shared assembly and exact runtime evidence are recorded in PLAN.md.',
            }} if action_id in {'OWN-A06','QS-A09'} else {}),
            **({'existing_final_account_response_source': {
                'source': 'src/actions/roles/contractor_closeout.py: request_closeout, original respond_settlement branch',
                'requirement': 'Profile final_account_ref resolves through the current contract projection to an authored ContractorFinalAccountView with the exact same original Contract reference/version, original item coverage and non-withdrawn status.',
                'current_binding': 'integration.contractor_final_account_history:bind_history derives an own proposed private account view from a currently readable completed original A11 propose_final_account result and retained authorship. An explicit same-organization dependency binds the exact result digest and communication receipt. The later private contract projection adds its history link without changing the formal Contract reference, sealed initial declarations, original readings or native state.',
                'consumer': 'Original A11 respond_settlement checks original author authority and all items; only its choice/note is sent through the existing native room. No account contents or task identity are disclosed to Owner/QS.',
                'input_producer': 'integration.final_account_discussion_development:initial_sources(with_contractor_response=True); shared --with-final-account-discussion --with-contractor-final-account-response',
                'rounds': 'QS declares contractor_message_index to retain its original message when later Contractor responses append.',
                'targeted_case': 'tests/test_native_final_account_positions.py::test_original_owner_position_uses_native_room_and_original_receipt[contractor-responds-to-own-original-proposal]',
                'boundary': 'Own request/draft history only, status proposed; not formal account registration, agreed determination, payment or discharge. Source requires the same original scope and review tick. Other-party accounts, revised-contract histories and formal submission receipts still need their actual authorized sources. An Owner-only QS question is not copied to Contractor.',
            }} if action_id == 'CONTRACTOR-A11' else {}),
            'branches': branches,
        })
    for action in actions:
        if action['action_id']=='QS-A06':
            action['native_bid_question_publication'] = {
                'bridge_version':'gba-v1-qs-bid.v8',
                'initial_option':'--clarify-contractor-id ORIGINAL_BIDDER',
                'trigger':'Original native evaluate_bid request and original completed QS-A06 clarify decision.',
                'sources':'Original same-round submitted bids, independently unknown qualification, exact evidence target and responsible bidder; declared before source sealing.',
                'communication':'Original tender_clarification session and append_message. Questions are grouped by their original permitted recipients and native organization ownership is checked.',
                'query':'QSBidNativeBridge.query_clarification_review(original_identity, organization_id=own_id, tick=current_tick)',
                'state':'Question communication only. The original evaluation stays unresolved; no answer, score, exclusion or award is manufactured.',
                'recovery':'Durable send intent and read-only observation reuse the existing helper; an unknown send is never resubmitted.',
                'evidence':'output/integration/qs_bid_clarification_20261017_01/manifest.json',
                'remaining_inputs':'Actual original bidder reply and its current authority, original versioned A03 bid/submission sources and an independently authorized new evaluation. A QS-A05 tender-document reply is not a bidder response.',
                'acceptance_effect':'none; clarify remains pending full source/consumer adaptation',
                'prior_evidence_scope':'Earlier comparable/single-exclusion/no-valid-bid results retain their exact recorded v5/v6/v7 source revisions; this question case does not rerun or broaden them.',
            }
    source_paths = ['agents/operation_specs.py', 'agents/external_adapter.py', 'agents/owner_agent.py', 'agents/bank_agent.py',
                    'agents/supplier_agent.py', 'agents/contractor_agent.py', 'models/action.py',
                    'simulation/project_lifecycle_engine.py', 'simulation/project_state_update_engine.py',
                    'simulation/enterprise_decision_scheduler.py', 'simulation/interaction_session.py',
                    'simulation/message_bus.py', 'simulation/action_applier.py', 'simulation/simulation_engine.py']
    return {
        'schema_version': 'gba-v1-action-mapping.v1', 'macro_version': 'gba-public-2026-08-21',
        'catalog_sha256': hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        'macro_source_sha256': {path: hashlib.sha256((macro / 'gba_construction_sim/backend' / path).read_bytes()).hexdigest()
                                for path in source_paths},
        'native_role_operation_count': len(list_operation_contracts()),
        'verified_lifecycle_call_sites': [{
            'handler': 'agents/bank_agent.py: consider_financing / decide_monthly_operation; simulation/simulation_engine.py: _arrange_project_financing',
            'native_behavior': 'Reviewed Bank operations produce independent financing offers and monthly enterprise decisions. The project financing path records bank_financing_decision and Owner selection; approved_amount and interest_rate describe the offered financing.',
            'decision_hook': 'These reviewed call sites contain no detailed BANK-A07 payment-command issuer or bank-execution/cash-arrival receipt query.',
            'adapter_boundary': 'Preserve existing financing selection and private processing. Do not implement BankSubmissionCallbacks.submit/query by changing aggregate capacity, emitting a synthetic cash receipt or treating an accepted financing offer as a drawdown. Detailed payment transport still requires an independently verified equivalent native issuer and receipt reader.',
            'micro_sources': ['integration/bank_execution_submission.py', 'integration/bank_execution_reader.py', 'integration/owner_payment_execution_reader.py'],
            'scope_of_finding': 'Only the reviewed BankAgent operations and native project-financing initialization. Other original finance/execution call sites must be reviewed separately; this is not a global claim that macro finance capability is absent.',
        }, {
            'handler': 'simulation/project_lifecycle_engine.py: _handle_design; simulation/project_state_update_engine.py: update_design_state',
            'native_behavior': 'Design progression uses aggregate design/information quality, Architect/QS profiles and estimated cost. _handle_design transitions to APPROVAL when design_quality >= 0.70 and information_quality >= 0.65.',
            'decision_hook': 'These reviewed methods contain no external per-draft Architect/Engineer design submission or response request. _handle_approval separately invokes actual Government approval decisions.',
            'adapter_boundary': 'Do not treat aggregate quality increments or a stage transition as receipt/approval of a specific original A04/A05 planning or design draft. Reuse supported appointment and approval requests; detailed design outputs still need an authentic producer, authorized consumer and equivalent submission call site.',
            'micro_sources': ['integration/architect_planning_actions.py', 'integration/architect_design_actions.py', 'integration/engineer_planning_actions.py', 'integration/engineer_design_actions.py'],
            'scope_of_finding': 'Only these reviewed design-stage methods and original professional agent call sites; not a global claim that macro design capabilities are absent. Macro sources remain frozen.',
        }, {
            'handler': 'simulation/project_lifecycle_engine.py: _handle_initiation / consultant_team_appointed',
            'native_behavior': 'After independent professional acceptance and actual Owner selection, stores the selected team and emits consultant_team_appointed. Only selected professionals receive their existing own membership projection.',
            'adapter_boundary': 'Original private A12 can record actual own selection after authenticating its original A02, proposal, final acceptance and actual event reception. This does not issue detailed service Appointment/Task objects, fees, capability, training or work completion.',
            'micro_sources': ['integration/professional_intake_feedback.py', 'integration/professional_feedback_development.py', 'integration/professional_intake_native.py', 'integration/native_lifecycle_actions.py'],
            'next_consumer': 'Later actual original A02 includes its own completed A12 selection record in authenticated prior-appointment Evidence, under the existing explicit max_prior_appointments preference. Unselected candidates have no appointment receipt; decision-only legacy configurations retain native history.',
            'scope_of_finding': 'Actual selected-team feedback and private later intake only; final selection is distinct from earlier acceptance intention.',
        }, {
            'handler': 'simulation/project_state_update_engine.py: update_construction_state, update_supply_state, update_construction_progress',
            'native_behavior': 'The original construction updater computes normalized material availability/reliability/quality, stochastic supply delay and aggregate progress from duration, capability, resources, material availability and risks.',
            'decision_hook': 'These methods call the original state equations, not external Supplier production/logistics or Contractor readiness/work command handlers. _handle_construction separately handles suspension, variation and completion-review assignment.',
            'adapter_boundary': 'Retain actual aggregate events as observations. Their material availability and progress do not create original detailed inventory batches, production/delivery executions, task releases, measurements or independently verified work records.',
            'micro_sources': ['integration/supplier_execution_actions.py', 'integration/supplier_logistics_actions.py', 'integration/contractor_readiness_actions.py', 'integration/contractor_execution_actions.py'],
            'scope_of_finding': 'Only these reviewed state-update/lifecycle methods. Other original execution endpoints must be reviewed separately; no global absence of macro fulfilment capability is inferred.',
        }, {
            'handler': 'simulation/action_applier.py: ActionApplier.apply_results, apply_project_update, apply_project_mutation',
            'native_behavior': 'Serializes supplied mutations under sorted project/agent locks and invokes caller-provided apply callbacks.',
            'decision_hook': 'The caller supplies the business implementation; the applier itself is not an Owner/Bank transfer issuer or detailed cash-query endpoint.',
            'adapter_boundary': 'Reuse the original lifecycle/state-update business callback and its actual evidence. A lock result or successful callback return alone is not a detailed payment receipt.',
            'scope_of_finding': 'This executor boundary and reviewed native financing selection/progress-payment/final-account call sites only; not a claim that every macro finance capability is absent.',
        }, {
            'handler':'simulation/project_lifecycle_engine.py: _handle_tendering / _start_interaction_session',
            'native_behavior':'After actual invitations, creates or reuses the project tender_clarification session '
                'for Owner, QS and shortlisted Contractors. Appends the original Owner invitation and QS '
                'channel-opening messages through InteractionSessionManager.append_message and records '
                'tender_clarification_session_started. Those messages announce the channel, not resolved answers.',
            'existing_interface':'simulation/interaction_session.py: by_project, append_message and recent_messages; '
                'simulation/message_bus.py: publish, peek and drain. These are actual native communication '
                'components. The integration adapter now publishes/queries exact original A01 questions under '
                'recipient/authority checks; professional answers and revised-source continuation remain pending.',
            'adapter_boundary':'Do not call get_or_create to manufacture a prior actual invitation or a QS answer. '
                'Do not treat opening a channel, generic message delivery or a micro clarification draft as '
                'resolved professional information, completed A02 or a submitted native bid. Existing A01 '
                'clarify remains unresolved at the tender response bridge until authorized answers and '
                'explicit continuation can be consumed without replaying completed work.',
            'micro_sources':['integration/contractor_tender_request_trigger.py',
                'integration/contractor_screening_actions.py', 'integration/bindings/gba_v1_tender_clarification.py'],
            'scope_of_finding':'Existing native communication and actual question publication/query, not a '
                'complete clarification workflow or a claim that macro clarification is absent. Native source '
                'and original opening messages are unchanged; added questions use the original message API.',
        }, {
            'handler': 'simulation/project_state_update_engine.py: ProjectStateUpdateEngine._record_payment_event',
            'native_behavior': 'On its progress threshold, computes contract_sum times the incremental threshold '
                'and emits payment_requested with cumulative certified_progress, payment_amount and approved/delayed status. '
                'A delayed request also emits payment_delayed and changes aggregate claim/dispute risk.',
            'decision_hook': 'This method contains no external Owner/Bank/QS payment decision or cash-transfer call.',
            'adapter_boundary': 'Own actual requests can inform private later decisions. Approved does not prove '
                'bank transfer, received cash, independent QS certification, cleared debt or a currency conversion.',
            'micro_sources': ['integration/bindings/gba_v1_progress_payments.py',
                'integration/owner_opportunity_native_sources.py', 'integration/progress_payment_development.py'],
            'scope_of_finding': 'Specific original aggregate event method only; other detailed execution mappings '
                'require their own source and call-site review.',
        }, {
            'handler': 'simulation/project_lifecycle_engine.py: ProjectLifecycleEngine._handle_final_account',
            'native_behavior': 'Starts final-account review interaction and emits final_account_review_started. '
                'After MIN_FINAL_ACCOUNT_TICKS, computes max(contract_sum or initial_budget, actual_cost), '
                'emits final_account_settled, releases roles and transitions to CLOSED.',
            'decision_hook': 'This handler contains no agent_module.propose or external final-account decision request.',
            'adapter_boundary': 'Its actual aggregate events can support authorized own observations. '
                'They cannot alone supply original QS-A09 certificate/cash histories, OWN-A12 independent '
                'handover/permit/defect evidence, or detailed payment/debt clearance. Do not manufacture those facts.',
            'micro_sources': ['integration/qs_final_account_actions.py', 'integration/owner_closeout_actions.py',
                'integration/contractor_closeout_actions.py', 'integration/bindings/gba_v1_final_accounts.py',
                'integration/owner_opportunity_native_sources.py', 'integration/final_account_learning_development.py'],
            'next_consumer': 'Optional --max-prior-final-accounts N supplies actual own aggregate settlement history '
                'to later original OWN-A03, verified in a three-tick eight-role shared run. Optional '
                '--with-final-account-learning also feeds actual settlement to original QS-A12 record_feedback '
                'after its own original QS-A09 review. It does not count OWN-A12, QS-A09 post-settlement '
                'acceptance, original forecast-error analysis or cash execution.',
            'supported_communication': 'Explicit original OWN-A06 dispute/negotiate choice/note can publish once into the actual existing final_account_dispute room through append_message. Original QS-A09 can consume one addressed position and its receipt Evidence, then explicitly publish its formed evidence question to the actual Owner. Three targeted cases passed, including Owner receipt consumption, original QS processing/actual question delivery and unknown Owner-send query. This does not control native aggregate settlement or execute cash.',
            'scope_of_finding': 'Specific original lifecycle handler only. Other source/transport mappings '
                'remain subject to their own review; this is not a claim that all macro settlement capability is absent.',
        }],
        'limits': [
            'Candidate mappings are not verified semantic equivalence or completed bindings.',
            'Unlisted branches require source/call-site review, not a presumption of missing macro capability.',
            'Monthly enterprise operations must not be used to manufacture formal transactions.',
            'Acceptance remains in the existing action_coverage.json; this file does not maintain completion percentages.',
        ],
        'verified_compatibility_limits': [{
            'operation': 'select_preferred_bid', 'role': 'Owner',
            'status': 'frozen_external_contract_conflict',
            'evidence': [
                'agents/operation_specs.py: select_preferred_bid requires selected_contractor_id and ranked_bids.',
                'agents/owner_agent.py: OwnerAgent.select_preferred_bid returns that selected_contractor_id.',
                'agents/external_adapter.py: ExternalAgentModuleAdapter.propose recursively rejects forbidden response keys.',
                'models/action.py: FORBIDDEN_ACTION_MUTATION_KEYS includes selected_contractor_id.',
                'simulation/project_lifecycle_engine.py: _handle_bid_evaluation consumes that exact selected_contractor_id.',
            ],
            'boundary': 'No equivalent successful Owner selection through the frozen external proposal path has been verified. '
                        'Keep this formal branch unexecuted; do not rename the field, edit the macro, or publish a success receipt.',
            'reproducer': 'tests/test_native_routes.py',
            'native_owned_alternative': {
                'source':'integration/bindings/gba_v1_native_composition.py',
                'configuration':'direct_native_proposals must be an explicit unique subset of native_proposals before engine creation.',
                'semantics':'Original AgentBehaviorRegistry.propose owns this operation; no micro response is accepted here. '
                    'All real external responses retain frozen validation, and micro route reassignment is rejected.',
                'actual_runtime':'output/integration/development_qs_native_composition_20261016_01/runtime/result.json',
                'not_micro_coverage':'The original native Owner selection is not OWN-A08 implementation or acceptance.'},
        }, {
            'operation':'_validate_representative_actions', 'role':'lifecycle required roles',
            'status':'frozen_internal_guardrail_validation_conflict',
            'evidence':[
                'simulation/project_lifecycle_engine.py: _validate_representative_actions directly builds validation_only AgentAction data including engagement_status; it does not call the external micro handler.',
                'models/action.py: FORBIDDEN_ACTION_MUTATION_KEYS includes engagement_status.',
                'simulation/action_validator.py: validate rejects forbidden mutation keys and records invalid_action.',
            ],
            'observed':'development_contract_supply_20261016_02 records invalid_action for native execute_work '
                'and deliver_materials. The same initial supply-first project is separately suspended at tick 4 '
                'because defect_rate 0.77206 exceeds _handle_construction threshold 0.75; no causal link '
                'from this validation conflict to that suspension has been established.',
            'boundary':'Preserve the actual invalid actions and suspension. Do not edit the macro validator, '
                'strip its internal action fields, or count aggregate progression as detailed micro work/delivery. '
                'This specific internal validation conflict does not establish absence of all macro construction capability.',
            'reproducer':'output/integration/development_contract_supply_20261016_02/runtime/result.json',
        }],
        'shared_business_recovery_case': {'evidence': 'output/integration/shared_business_recovery_20261017_01/checks.json', 'driver': 'tests/test_shared_business_continuation.py', 'source_mode': 'Explicit independent initial cases; sealed future review sources declare a successor grant which is initially absent from the live registry.', 'same_runtime': 'One original native simulation, authority registry and task journal across a completed-tick process restart. No failed-tick replay.', 'same_call_unstarted_stages': ['bank-credit', 'government-review', 'supplier-order'], 'actual_micro_roles': ['Architect', 'Bank', 'Contractor', 'Engineer', 'Government', 'Owner', 'QS', 'Supplier'], 'original_micro_results': 93, 'formed_tasks': 253, 'authority': 'The original registry denies the future review before the trusted host grants its exact successor after tick 1. The old checkpoint is rejected without consumption. After restoration the old version remains inactive and the actual tick-2 GOV-A04/A07 completes using the new current author grant.', 'feedback': 'Later original bank A01 consumes own A05 requote and A04 declines; the other bank is actually selected and confirms. Supplier A01 consumes actual refusal and Contractor A05 selects accepted B offers. Later Engineer A02 consumes own recorded appointment and declines. Actual aggregate settlement is consumed by later Owner A03 and the native final defers new creation.', 'limits': 'Representative shared business only, not all actions/choices, detailed financial execution, supplemental-material reception, physical inspection, detailed permits, handover or unknown formal receipts. Dynamic organizations, model combinations and failed-tick recovery remain unproven.'},
        'actions': actions,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    enable_gba_imports()
    mapping = build_mapping()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'actions': len(mapping['actions']),
                      'branches': sum(len(a['branches']) for a in mapping['actions']),
                      'output': str(args.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
