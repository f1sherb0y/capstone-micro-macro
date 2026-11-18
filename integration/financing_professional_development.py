"""One explicit input bundle for native financing followed by appointments.

Reuse existing independent synthetic sources, before any business execution.
The resulting bundle is an assembly candidate, not a business acceptance report.
"""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import re
from decimal import Decimal

from integration.bank_financing_development import build_bundle as bank_bundle, initial_organization_actors
from integration.contractor_tender_development import _write, _write_launch_files
from integration.financing_professional_native import FinancingProfessionalSettings
from integration.native_routes import NativeRouteSettings
from integration.professional_intake_development import build_bundle as professional_bundle, declared_private_judgment_roles
from src.coordination.tasks import task_digest
from src.organization.registry import OrganizationSnapshot


def _merge_snapshot(bank, professional):
    """Merge explicit initial grants without changing their readable data."""
    if bank['run_id'] != professional['run_id'] or bank['schema_version'] != professional['schema_version']:
        raise ValueError('Combined source snapshots must share their original run and schema')
    result = deepcopy(bank)
    organizations = {r['organization_id']: r for r in result['organizations']}
    for original in professional['organizations']:
        row = deepcopy(original)
        existing = organizations.get(row['organization_id'])
        if existing is None:
            organizations[row['organization_id']] = row
            continue
        if existing['actor_id'] != row['actor_id'] or existing['public_location'] != row['public_location']:
            raise ValueError('Combined organization changes its explicit actor or location')
        assignments = {task_digest(a['function_ref']): a for a in existing['assignments']}
        for assignment in row['assignments']:
            old = assignments.get(task_digest(assignment['function_ref']))
            if old is not None and old != assignment:
                raise ValueError('Combined organization changes an immutable function assignment version')
        for field in ('source_ids', 'evidence_refs', 'assignments', 'members'):
            unique = {task_digest(v) if isinstance(v, (dict, list)) else v: v for v in existing[field]}
            for value in row[field]:
                unique.setdefault(task_digest(value) if isinstance(value, (dict, list)) else value, value)
            existing[field] = list(unique.values())
    result['organizations'] = list(organizations.values())
    grants = {task_digest(r['ref']): r for r in result['authorizations']}
    for grant in professional['authorizations']:
        key = task_digest(grant['ref'])
        if key in grants and grants[key] != grant:
            raise ValueError('Combined initial authorization versions conflict')
        grants[key] = deepcopy(grant)
    result['authorizations'] = list(grants.values())
    result['inactive_authorization_refs'] = list({task_digest(r): r
        for r in bank.get('inactive_authorization_refs', []) + professional.get('inactive_authorization_refs', [])}.values())
    return OrganizationSnapshot.model_validate(result).model_dump(mode='json')


def _remap_initial(value, substitutions):
    """Rename declared initial identities; never use this on runtime results."""
    if any(not isinstance(before,str) or not before or not isinstance(after,str) or not after
            for before,after in substitutions.items()):
        raise ValueError('Initial identity substitutions require nonempty original names and string targets')
    replacements = sorted(substitutions.items(), key=lambda item: len(item[0]), reverse=True)
    pattern=re.compile('|'.join(re.escape(before) for before,_ in replacements)) if replacements else None
    def remap(item):
        if isinstance(item,str):
            return item if pattern is None else pattern.sub(lambda match:substitutions[match.group()],item)
        if isinstance(item,list):return [remap(v) for v in item]
        if isinstance(item,dict):
            # Execution identity belongs to the caller, even if its run name
            # happens to contain one of the template organization names.
            return {remap(k):deepcopy(v) if k=='run_id' else remap(v) for k,v in item.items()}
        return item
    return remap(value)


def _source_files(directory, *, settings, substitutions, files, initial_support_actor_ids=None):
    result = _remap_initial(settings, substitutions)
    support_actors = initial_support_actor_ids or {}
    snapshot = result.get('authority', {}).get('organization_snapshot')
    if snapshot is not None:
        for organization in snapshot['organizations']:
            org = organization['organization_id']
            if org not in support_actors or organization['actor_id'] == support_actors[org]:
                continue
            # This source declares support organizations without executable
            # mandates. Its active actors and signed business data stay fixed.
            if (organization['actor_id'] != org
                    or any(grant['organization_id'] == org for grant in snapshot['authorizations'])
                    or {a['role'] for a in organization['assignments']} not in ({'Bank'}, {'Government'})):
                raise ValueError('Initial support actor binding cannot change an existing executable or bound identity')
            organization['actor_id'] = support_actors[org]

    def check_actor_fields(value):
        if isinstance(value,list):
            for item in value:check_actor_fields(item)
        elif isinstance(value,dict):
            for key,item in value.items():
                if (key == 'actor_id' or key.endswith('_actor_id')) and isinstance(item,str):
                    if item in support_actors and support_actors[item] != item:
                        raise ValueError('Initial support actor binding cannot reinterpret an existing source actor')
                else:check_actor_fields(item)

    for key, name in files:
        original = settings if key is None else settings[key]
        target = result if key is None else result[key]
        path = Path(original['file_path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != original['file_sha256']:
            raise ValueError('Combined source differs from its initial pinned template')
        body = _remap_initial(json.loads(path.read_bytes()), substitutions)
        check_actor_fields(body)
        target.update(_write(directory, name, body))
    return result


def _professional_sources(directory, *, settings, run_id):
    """Declare explicit identities and one clock for the same two projects."""
    substitutions = {
        'professional-owner': 'finance-owner-a',
        'professional-architect-b': 'finance-architect-b',
        'professional-architect': 'finance-architect',
        'professional-engineer': 'finance-engineer',
        'professional-qs': 'finance-qs',
        'professional-first': 'PGEN0001', 'professional-followup': 'PGEN0002',
        'professional-clock': run_id + '-monthly-clock',
    }
    files = [(None, 'professional-input.json'), ('owner', 'owner-commission-input.json'),
        ('appointment', 'professional-appointment-input.json')]
    if settings.get('feedback') is not None:
        files.append(('feedback', 'professional-feedback-input.json'))
    return _source_files(directory, settings=settings, substitutions=substitutions, files=files)


def build_bundle(directory, *, run_id, with_government_and_supply=False,with_government_feedback=False,
        allow_government_saved_recovery=False,with_owner_opportunity=False,
        allow_government_intake_saved_recovery=False,query_saved_intake_on_error=False,
        max_prior_initiations=None,max_prior_payment_requests=None,with_payment_project=False,
        with_payment_positions=False,
        max_prior_final_accounts=None,
        with_contractor_formation=False,max_prior_accept_terms=1,with_contract_supply_handoff=False,
        with_owner_award=False,max_prior_owner_accepts=1,query_saved_approval_on_error=False,
        continue_unstarted_government_approval_actions_on_error=False,
        max_prior_owner_payment_delays=None,with_owner_observation=False,
        owner_observation_minimum_demand='0',max_prior_opportunity_declines=None,with_government_monthly_feedback=False,
        allow_government_monthly_saved_recovery=False,query_saved_monthly_on_error=False,
        with_contractor_tender=False,allow_tender_saved_recovery=False,query_saved_tender_on_error=False,
        with_tender_feedback=False,query_prior_tender_submissions=False,continue_unstarted_tender_actions_on_error=False,
        with_qs_evaluation=False,with_qs_learning=False,qs_exclude_contractor_id=None,
        allow_qs_learning_saved_recovery=False,query_saved_qs_learning_on_error=False,
        lifecycle_input=None,with_final_account_discussion=False,with_final_account_response=False,
        with_contractor_final_account_response=False,with_final_account_learning=False,
        with_tender_clarification_request=False,with_tender_clarification_response=False,
        continue_tender_clarification=False, tender_initial_screening_policies=None,
        tender_decline_after_prior_declines=None, tender_decline_after_prior_final_accounts=None,
        tender_decline_after_prior_payment_delays=None,
        tender_contractor_ids=('tender-contractor-a', 'tender-contractor-b'),
        allow_tender_followup_bids=False,
        final_account_contractor_id=None, with_professional_opportunity=False,
        professional_opportunity_interest_permitted=True,decline_after_no_interest=False,with_professional_feedback=False,
        with_professional_private_intake_judgment=False,
        professional_private_intake_judgment_roles=None,
        intake_decline_banks=(),bank_credit_condition_outcomes=None,with_owner_proposal=False,
        owner_proposal_review_cost='1000000',owner_proposal_review_effort='0.5',owner_study_question_code=None,
        owner_study_budget='1000000',owner_study_estimated_cost='500000',owner_study_resource_requirement='0.5',
        owner_study_duration=1,owner_study_qualified=True,owner_study_target_interventions=(),owner_study_service_offer=None,
        owner_study_professional_intake=None,
        allow_owner_opportunity_saved_recovery=False,query_saved_opportunity_on_error=False,
        with_bank_monthly_strategy=False,bank_monthly_max_prior_reviews=1,
        allow_bank_monthly_saved_recovery=False,query_saved_bank_monthly_on_error=False,
        allow_bank_financing_saved_recovery=False,query_saved_financing_on_error=False,
        continue_unstarted_bank_financing_actions_on_error=False,
        bank_arrangement_principal_limits=None,with_unconfirmed_arrangement_feedback=False,
        bank_arrangement_capacity_limits=None,
        allow_supplier_saved_recovery=False,query_saved_supply_on_error=False,
        max_prior_construction_suspensions=None,with_suspension_project=False,suspension_project_design_quality=0.0,
        with_supplier_product_substitution=False,contractor_substitution_permitted=True,
        continue_unstarted_supplier_actions_on_error=False,
        incompatible_confirmation_roles=(),decline_after_unresolved_confirmation=False,prior_appointment_limits=None,
        professional_project_object_types=None,
        supplier_first_decline_stage=None,supplier_decline_after_prior_declines=None,
        owner_initial_investment_policy=None, random_seed=None, owner_payment_reliability=None,
        progress_payment_ticks=(1,), payment_position_project_id=None, bank_actor_ids=None,
        government_actor_ids=None):
    if bank_actor_ids is not None and (not isinstance(bank_actor_ids,dict)
            or set(bank_actor_ids) - {'finance-bank-a','finance-bank-b'}):
        raise ValueError('Shared Bank actor declarations must identify the original two Banks')
    if government_actor_ids is not None and (not with_government_and_supply
            or not isinstance(government_actor_ids,dict)
            or set(government_actor_ids) - {'finance-government','finance-government-b'}):
        raise ValueError('Shared Government actor declarations require the original regulatory composition and agencies')
    shared_actor_ids={**(bank_actor_ids or {}),**(government_actor_ids or {})}
    initial_organization_actors(shared_actor_ids,
        ['finance-owner-a','finance-owner-b','finance-bank-a','finance-bank-b','finance-architect',
            'finance-architect-b','finance-engineer','finance-qs','finance-government','finance-government-b',
            'finance-contractor','finance-supplier','finance-supplier-b','tender-contractor-a','tender-contractor-b',
            'disclosed-other-lender'])
    if payment_position_project_id is not None and (
            not isinstance(payment_position_project_id,str) or not payment_position_project_id.strip()
            or not with_payment_positions):
        raise ValueError('Explicit payment target requires payment positions and an original project ID')
    if (not isinstance(progress_payment_ticks,(list,tuple)) or not progress_payment_ticks
            or any(type(t) is not int or t < 1 for t in progress_payment_ticks)
            or list(progress_payment_ticks) != sorted(set(progress_payment_ticks))
            or list(progress_payment_ticks) != [1] and not with_payment_positions):
        raise ValueError('Shared payment windows need original payment positions and distinct increasing positive ticks')
    if random_seed is not None and type(random_seed) is not int:
        raise ValueError('Shared random seed must be an explicit integer')
    if owner_payment_reliability is not None and (
            not with_payment_project or type(owner_payment_reliability) not in {int, float}
            or not 0 <= owner_payment_reliability <= 1):
        raise ValueError('Shared initial payment reliability requires the payment project and a finite value from zero to one')
    if owner_initial_investment_policy is not None and (
            not with_owner_opportunity or owner_initial_investment_policy not in {'evaluate','prepare_only','reject'}):
        raise ValueError('Shared initial investment policy needs original Owner opportunity sources and a known policy')
    if supplier_first_decline_stage is not None and (
            not with_government_and_supply or supplier_first_decline_stage not in {'screening','product','quote'}):
        raise ValueError('Shared Supplier decline needs its original supply sources and a known stage')
    if supplier_decline_after_prior_declines is not None and (
            not with_government_and_supply or type(supplier_decline_after_prior_declines) is not int
            or supplier_decline_after_prior_declines < 1):
        raise ValueError('Shared Supplier decline feedback needs original supply sources and a positive integer threshold')
    from integration.bank_financing_development import initial_credit_conditions
    initial_credit_conditions(bank_credit_condition_outcomes)
    from integration.bank_arrangement_native_development import initial_formation_limits
    initial_formation_limits(bank_arrangement_principal_limits)
    initial_formation_limits(bank_arrangement_capacity_limits)
    if allow_government_intake_saved_recovery and not with_government_and_supply:
        raise ValueError('Government intake recovery requires explicit Government and supply sources')
    if query_saved_intake_on_error and not allow_government_intake_saved_recovery:
        raise ValueError('Government intake query requires explicit saved-result recovery')
    if query_saved_financing_on_error and not allow_bank_financing_saved_recovery:
        raise ValueError('Shared Bank financing query requires --allow-bank-financing-saved-recovery')
    if type(with_payment_positions) is not bool or with_payment_positions and not (
            with_payment_project or payment_position_project_id is not None):
        raise ValueError('Shared payment positions require --with-payment-project or an explicit existing payment target')
    if type(with_final_account_discussion) is not bool or with_final_account_discussion and not with_government_and_supply:
        raise ValueError('Shared final-account discussion requires --with-government-and-supply')
    if type(with_final_account_response) is not bool or with_final_account_response and not with_final_account_discussion:
        raise ValueError('Shared Owner response requires --with-final-account-discussion')
    if type(with_final_account_learning) is not bool or with_final_account_learning and not with_final_account_discussion:
        raise ValueError('Shared QS settlement learning requires --with-final-account-discussion')
    if type(with_contractor_final_account_response) is not bool or with_contractor_final_account_response and not with_final_account_discussion:
        raise ValueError('Shared Contractor response requires --with-final-account-discussion')
    # Generation precedes lifecycle advancement in the frozen engine. A review
    # in tick 1 settles in tick 2, and strictly earlier feedback needs tick 3.
    with_final_account_followup = (with_final_account_discussion and with_owner_opportunity
        and max_prior_final_accounts is not None)
    professional_types = ({'PGEN0001':'industrial','PGEN0002':'building'} if with_owner_opportunity
        else {'PGEN0001':'building','PGEN0002':'building'})
    from integration.contractor_tender_development import _screening_policies
    if (not isinstance(tender_contractor_ids, (list, tuple)) or len(tender_contractor_ids) != 2
            or any(not isinstance(org, str) or org not in {
                'finance-contractor', 'tender-contractor-a', 'tender-contractor-b'} for org in tender_contractor_ids)
            or len(set(tender_contractor_ids)) != 2
            or tuple(tender_contractor_ids) != ('tender-contractor-a', 'tender-contractor-b') and not with_contractor_tender):
        raise ValueError('Shared tender needs two distinct explicitly supported Contractor identities and its enabled host')
    tender_contractor_ids = tuple(tender_contractor_ids)
    _screening_policies(tender_initial_screening_policies, tender_contractor_ids)
    if tender_initial_screening_policies is not None and not with_contractor_tender:
        raise ValueError('Initial tender screening policies require the original tender application')
    if tender_decline_after_prior_declines is not None and (not (with_contractor_tender and with_tender_feedback)
            or with_qs_evaluation or type(tender_decline_after_prior_declines) is not int or tender_decline_after_prior_declines < 1):
        raise ValueError('Decline feedback needs the explicit tender feedback window and positive limit, separate from QS evaluation')
    if tender_decline_after_prior_final_accounts is not None and (
            not (with_contractor_tender and with_tender_feedback)
            or type(tender_decline_after_prior_final_accounts) is not int or tender_decline_after_prior_final_accounts < 1):
        raise ValueError('Tender final-account feedback needs the explicit tender feedback window and positive limit')
    if tender_decline_after_prior_payment_delays is not None and (
            not (with_contractor_tender and with_tender_feedback)
            or type(tender_decline_after_prior_payment_delays) is not int or tender_decline_after_prior_payment_delays < 1):
        raise ValueError('Tender payment-delay feedback needs the explicit tender feedback window and positive limit')
    if type(allow_tender_followup_bids) is not bool or allow_tender_followup_bids and not (
            with_contractor_tender and with_tender_feedback):
        raise ValueError('Followup bid permission needs the explicitly enabled shared tender feedback window')
    if final_account_contractor_id is not None and (not with_final_account_discussion
            or not isinstance(final_account_contractor_id, str) or not final_account_contractor_id.strip()
            or final_account_contractor_id != final_account_contractor_id.strip()
            or final_account_contractor_id not in ({'finance-contractor', *tender_contractor_ids}
                if with_contractor_tender else {'finance-contractor'})):
        raise ValueError('Initial final-account contractor must be an explicitly configured shared Contractor')
    if professional_project_object_types is not None:
        if (not isinstance(professional_project_object_types,dict)
                or set(professional_project_object_types) != set(professional_types)
                or any(type(value) is not str or value not in {'building','infrastructure','industrial','public_facility','digital_smart'}
                    for value in professional_project_object_types.values())):
            raise ValueError('Professional object types require explicit PGEN0001/PGEN0002 initial declarations')
        professional_types = dict(professional_project_object_types)
    if (decline_after_no_interest or not professional_opportunity_interest_permitted) and not with_professional_opportunity:
        raise ValueError('Shared no-interest policy requires --with-professional-opportunity')
    declared_private_judgment_roles(enabled=with_professional_private_intake_judgment,
        with_feedback=with_professional_feedback, roles=professional_private_intake_judgment_roles)
    if type(with_qs_evaluation) is not bool or with_qs_evaluation and not with_contractor_tender:
        raise ValueError('Shared QS evaluation requires the explicitly enabled original tender application')
    if qs_exclude_contractor_id is not None and (not with_qs_evaluation
            or not isinstance(qs_exclude_contractor_id,str)
            or qs_exclude_contractor_id not in tender_contractor_ids):
        raise ValueError('Shared authorized exclusion requires QS evaluation and one declared tender Contractor ID')
    if type(with_qs_learning) is not bool or with_qs_learning and not (with_qs_evaluation and with_tender_feedback):
        raise ValueError('Shared QS learning requires evaluation and its strictly earlier feedback window')
    if allow_qs_learning_saved_recovery and not with_qs_learning:
        raise ValueError('Shared QS learning recovery requires --with-qs-learning')
    if query_saved_qs_learning_on_error and not allow_qs_learning_saved_recovery:
        raise ValueError('Shared QS learning query requires --allow-qs-learning-saved-recovery')
    if continue_unstarted_supplier_actions_on_error and not with_government_and_supply:
        raise ValueError('Unstarted Supplier continuation requires --with-government-and-supply')
    if with_supplier_product_substitution and not with_government_and_supply:
        raise ValueError('Alternate Supplier product requires Government/Supplier composition')
    if not contractor_substitution_permitted and not with_supplier_product_substitution:
        raise ValueError('Withheld Contractor substitution permission requires the alternate-product scene')
    if max_prior_construction_suspensions is not None and (not with_contractor_formation
            or type(max_prior_construction_suspensions) is not int or max_prior_construction_suspensions<1):
        raise ValueError('Shared suspension preference requires original Contractor formation and a positive event count')
    if with_suspension_project and not with_contractor_formation:
        raise ValueError('Shared initial suspension source requires original Contractor formation')
    if (type(suspension_project_design_quality) not in {int,float} or not 0<=suspension_project_design_quality<=1
            or not with_suspension_project and suspension_project_design_quality!=0):
        raise ValueError('Shared initial design quality requires its explicit source project and a bounded score')
    if allow_supplier_saved_recovery and not with_government_and_supply:
        raise ValueError('Supply recovery requires --with-government-and-supply')
    if query_saved_supply_on_error and not allow_supplier_saved_recovery:
        raise ValueError('Supply query requires --allow-supplier-saved-recovery')
    if allow_bank_monthly_saved_recovery and not with_bank_monthly_strategy:
        raise ValueError('Bank monthly recovery requires --with-bank-monthly-strategy')
    if query_saved_bank_monthly_on_error and not allow_bank_monthly_saved_recovery:
        raise ValueError('Bank monthly query requires --allow-bank-monthly-saved-recovery')
    if allow_owner_opportunity_saved_recovery and not with_owner_opportunity:
        raise ValueError('Saved opportunity recovery requires --with-owner-opportunity')
    if query_saved_opportunity_on_error and not allow_owner_opportunity_saved_recovery:
        raise ValueError('Saved opportunity query requires --allow-owner-opportunity-saved-recovery')
    if owner_study_question_code is not None and not with_owner_opportunity:
        raise ValueError('Bounded Owner study followup requires --with-owner-opportunity')
    if owner_study_target_interventions and owner_study_question_code is None:
        raise ValueError('Targeted Owner study requires --owner-study-question-code')
    if owner_study_service_offer is not None:
        from integration.owner_study_service_offer import OwnerStudyServiceOfferPolicy
        owner_study_service_offer=OwnerStudyServiceOfferPolicy.model_validate(owner_study_service_offer)
        if (owner_study_question_code is None or owner_study_service_offer.provider_organization_id not in
                {'finance-qs','finance-architect'}):
            raise ValueError('Standing Owner research offer requires its question and original professional provider')
    if owner_study_professional_intake is not None:
        from integration.owner_study_professional_intake import OwnerStudyProfessionalIntakePolicy
        owner_study_professional_intake=OwnerStudyProfessionalIntakePolicy.model_validate(owner_study_professional_intake)
        if (owner_study_question_code is None or owner_study_service_offer is not None
                or owner_study_professional_intake.provider_organization_id not in {'finance-qs','finance-architect'}
                or owner_study_professional_intake.provider_organization_id=='finance-qs' and owner_study_professional_intake.conflict_status is None):
            raise ValueError('Original professional study intake requires its question, provider and conflict source; standing offer is exclusive')
    if with_owner_proposal and not with_owner_observation:
        raise ValueError('Original Owner proposal requires --with-owner-observation')
    if continue_tender_clarification:
        with_tender_clarification_response = True
    if with_tender_clarification_response:
        with_tender_clarification_request = True
    if with_tender_clarification_request and not with_contractor_tender:
        raise ValueError('Shared clarification questions require the original tender application')
    if continue_unstarted_tender_actions_on_error and not with_contractor_tender:
        raise ValueError('Unstarted tender continuation requires the explicit shared tender application')
    if query_prior_tender_submissions and not with_tender_feedback:
        raise ValueError('Prior tender query requires explicit shared tender feedback')
    if with_tender_feedback and not with_contractor_tender:
        raise ValueError('Shared tender feedback requires the original tender application')
    if allow_tender_saved_recovery and not with_contractor_tender:
        raise ValueError('Saved tender recovery requires the explicit shared tender application')
    if query_saved_tender_on_error and not allow_tender_saved_recovery:
        raise ValueError('Tender query on error requires explicit saved-result recovery')
    if allow_government_monthly_saved_recovery and not with_government_monthly_feedback:
        raise ValueError('Saved Government monthly recovery requires the explicit monthly application')
    if query_saved_monthly_on_error and not allow_government_monthly_saved_recovery:
        raise ValueError('Monthly query on error requires explicit saved-result recovery')
    if with_government_monthly_feedback and not with_government_and_supply:
        raise ValueError('Government monthly feedback requires the explicit shared Government application')
    if with_owner_observation and not with_owner_opportunity:
        raise ValueError('Original Owner observation requires the explicit current-opportunity route')
    if max_prior_opportunity_declines is not None and not with_owner_opportunity:
        raise ValueError('Own non-initiation preference requires the explicit current-opportunity route')
    if not with_owner_observation and owner_observation_minimum_demand!='0':
        raise ValueError('Owner demand threshold requires the explicitly enabled original observation')
    if query_saved_approval_on_error and (not with_government_and_supply or not allow_government_saved_recovery):
        raise ValueError('Approval query on error requires explicit shared Government and saved-result recovery')
    if continue_unstarted_government_approval_actions_on_error and not with_government_and_supply:
        raise ValueError('Unstarted approval continuation requires explicit shared Government')
    if with_owner_award and not with_contractor_formation:
        raise ValueError('Original Owner award requires explicit original Contractor formation')
    if max_prior_owner_payment_delays is not None and (not with_contractor_formation
            or type(max_prior_owner_payment_delays) is not int or max_prior_owner_payment_delays<1):
        raise ValueError('Shared Contractor delay preference requires original formation and a positive request count')
    if with_contract_supply_handoff and (not with_contractor_formation or not with_government_and_supply):
        raise ValueError('Same-project signature/supply handoff requires explicit formation and Government/Supplier composition')
    if with_payment_project and (not with_owner_opportunity or max_prior_payment_requests is None):
        raise ValueError('Shared payment-feedback case requires original Owner opportunity processing and an explicit request-count preference')
    if with_government_feedback and not with_government_and_supply:
        raise ValueError('Government feedback requires explicitly enabled Government and Supplier composition')
    if allow_government_saved_recovery and not with_government_and_supply:
        raise ValueError('Government saved recovery requires explicitly enabled Government and Supplier composition')
    if max_prior_final_accounts is not None and (type(max_prior_final_accounts) is not int or max_prior_final_accounts < 1):
        raise ValueError('Shared final-account review preference requires a positive integer event count')
    if not with_owner_opportunity and (max_prior_initiations is not None or max_prior_payment_requests is not None
            or max_prior_final_accounts is not None):
        raise ValueError('Private opportunity preferences require the explicitly enabled original Owner application')
    lifecycle_document=None
    if lifecycle_input is not None:
        from integration.native_lifecycle_actions import NativeLifecycleInput
        lifecycle_document=NativeLifecycleInput.model_validate_json(Path(lifecycle_input).read_bytes())
        if lifecycle_document.run_id!=run_id:
            raise ValueError('Lifecycle inputs must already use the shared run and original identities; sealed sources are not renamed')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    if government_actor_ids is not None:
        _write(directory,'initial-government-actors.json',{'organization_actor_ids':government_actor_ids,
            'boundary':'Initial execution actors before source sealing. Native applicant, enterprises and task organizations remain unchanged; no old input, authority or history migration.'})
    if bank_actor_ids is not None:
        _write(directory,'initial-bank-actors.json',{'organization_actor_ids':bank_actor_ids,
            'boundary':'Initial execution actors only. Native Bank agents and business parties retain organization IDs; no saved source or result is migrated.'})
    bank_dir, professional_dir = directory / 'sources/bank', directory / 'sources/professional'
    owner_funding=None
    if with_owner_opportunity:
        # A single declared synthetic balance, not a runtime account or a
        # conversion of normalized macro financial capacity into money.
        owner_funding={'organization_id':'finance-owner-a','currency':'HKD','actual_cash':'50000000',
            'restricted_cash':'5000000','old_due':'15000000','actual_paid':'0'}
        _write(directory,'initial-owner-funding.json',owner_funding)
    bank_bundle(bank_dir, run_id=run_id, with_owner=True, feedback_followup=True,
        organization_actor_ids={key:value for key,value in shared_actor_ids.items()
            if key!='finance-government-b'} if shared_actor_ids else None,
        with_monthly_strategy=with_bank_monthly_strategy,monthly_max_prior_reviews=bank_monthly_max_prior_reviews,
        monthly_strategy_ticks=4 if with_bank_monthly_strategy else None,
        allow_monthly_saved_recovery=allow_bank_monthly_saved_recovery,
        query_saved_bank_monthly_on_error=query_saved_bank_monthly_on_error,
        allow_saved_recovery=allow_bank_financing_saved_recovery,
        query_saved_financing_on_error=query_saved_financing_on_error,
        continue_unstarted_actions_on_error=continue_unstarted_bank_financing_actions_on_error,
        arrangement_principal_limits=bank_arrangement_principal_limits,
        arrangement_capacity_limits=bank_arrangement_capacity_limits,
        with_unconfirmed_arrangement_feedback=with_unconfirmed_arrangement_feedback,
        with_bank_strategy=True, with_arrangement=True, project_schedule=[('PGEN0001', 1), ('PGEN0002', 2)],
        intake_decline_banks=intake_decline_banks,
        credit_condition_outcomes=bank_credit_condition_outcomes,
        write_launch=False,owner_funding=owner_funding)
    professional_bundle(professional_dir, run_id=run_id, with_owner=True, with_confirmation=True,
        with_opportunity=with_professional_opportunity,
        with_feedback=with_professional_feedback,
        with_private_intake_judgment=with_professional_private_intake_judgment,
        private_intake_judgment_roles=professional_private_intake_judgment_roles,
        opportunity_interest_permitted=professional_opportunity_interest_permitted,
        decline_after_no_interest=decline_after_no_interest,
        incompatible_confirmation_roles=incompatible_confirmation_roles,
        decline_after_unresolved_confirmation=decline_after_unresolved_confirmation,
        prior_appointment_limits=prior_appointment_limits,
        project_schedule=[('professional-first',2),('professional-followup',3)],
        project_object_types={'professional-first':professional_types['PGEN0001'],
            'professional-followup':professional_types['PGEN0002']})
    _write(directory,'initial-professional-object-types.json',{
        'project_object_types':professional_types,
        'source':'Explicit initial service terms, capability and work-method declarations.',
        'boundary':'Not inferred professional competence. Native project type must still match at actual intake; '
            'a runtime mismatch is not repaired by rewriting terms, qualifications or prior readings.'})
    read = lambda path: json.loads(path.read_bytes())
    bank_settings = read(bank_dir / 'assembly-host.json')['settings']
    professional_settings = _professional_sources(directory,
        settings=read(professional_dir / 'assembly-host.json')['settings'], run_id=run_id)
    snapshot = _merge_snapshot(bank_settings['authority']['organization_snapshot'],
        professional_settings['authority']['organization_snapshot'])
    components = {'bank': bank_settings, 'professional': professional_settings}
    request = read(bank_dir / 'macro-request.json')
    if random_seed is not None:
        request['random_seed'] = random_seed
    # One actual Owner generates one project per time point. Unused alternate
    # Owner source plans stay explicit initial assumptions, not native agents.
    request['agents'] = [a for a in request['agents'] if a['agent_id'] != 'finance-owner-b']
    alternate = deepcopy(next(a for a in request['agents'] if a['role'] == 'Architect'))
    alternate.update(agent_id='finance-architect-b', name='finance-architect-b')
    request['agents'].append(alternate)
    # Professional generation/financing precedes intake by one tick. Its second
    # declared intake is tick 3, so a private recommendation needs that original
    # consumer window; no appointment or feedback is supplied in advance.
    request.update(target_project_count=2, max_active_projects=2,
        ticks=3 if with_final_account_followup or with_professional_private_intake_judgment else 2)
    routes = read(bank_dir / 'native-host.json')['settings']
    routes.update(native_professional_intake_scope=False, micro_professional_intake_scope=True,
        micro_owner_commission_scope=True)
    routes['native_proposals'] = [r for r in routes['native_proposals']
        if r['operation'] not in {'consider_appointment', 'select_appointment'}]
    routes['native_decisions'] = [r for r in routes['native_decisions'] if r['decision_type'] not in {
        'architect_appointment_acceptance', 'engineer_appointment_acceptance', 'qs_appointment_acceptance',
        'owner_select_architect', 'owner_select_engineer', 'owner_select_qs'}]
    provenance=None
    if with_government_and_supply:
        from integration.financing_professional_execution_sources import extend_sources
        provenance=extend_sources(directory, run_id=run_id, components=components, request=request, routes=routes,
            with_government_monthly_feedback=with_government_monthly_feedback,
            allow_government_monthly_saved_recovery=allow_government_monthly_saved_recovery,
            query_saved_monthly_on_error=query_saved_monthly_on_error,
            monthly_feedback_ticks=range(1,5 if with_contract_supply_handoff or with_qs_evaluation else 4 if with_contractor_formation or with_tender_feedback or with_final_account_followup or with_professional_private_intake_judgment else 3),
            with_government_feedback=with_government_feedback,allow_government_saved_recovery=allow_government_saved_recovery,
            allow_government_intake_saved_recovery=allow_government_intake_saved_recovery,
            query_saved_intake_on_error=query_saved_intake_on_error,
            write_provenance=False,with_contract_supply_handoff=with_contract_supply_handoff,
            query_saved_approval_on_error=query_saved_approval_on_error,
            with_supplier_product_substitution=with_supplier_product_substitution,
            supplier_first_decline_stage=supplier_first_decline_stage,
            supplier_decline_after_prior_declines=supplier_decline_after_prior_declines,
            government_actor_ids=government_actor_ids,
            contractor_substitution_permitted=contractor_substitution_permitted)
        components['government']['approval']['continue_unstarted_actions_on_error']=continue_unstarted_government_approval_actions_on_error
        components['supplier']['allow_saved_recovery']=allow_supplier_saved_recovery
        components['supplier']['continue_unstarted_actions_on_error']=continue_unstarted_supplier_actions_on_error
        routes['query_saved_supply_on_error']=query_saved_supply_on_error
        for key in ('government', 'supplier'):
            snapshot = _merge_snapshot(snapshot, components[key]['authority']['organization_snapshot'])
    if with_owner_opportunity:
        from integration.owner_opportunity_native_development import build_bundle as opportunity_bundle
        # Explicit initial scenario preference from the original independent
        # service declarations. Do not widen providers' qualifications or
        # rewrite sources after a native project has been created.
        owner_plans=read(Path(professional_settings['owner']['file_path']))['plans']
        service_regions={}
        for plan in owner_plans:
            service,=[row['value'] for row in plan['objects']
                if row['ref']==plan['action_input']['service_scope_ref']]
            service_regions.setdefault((plan['project_id'],plan['tick'],plan['role']),set()).add(service['region_id'])
        if {key[2] for key in service_regions}!={'Architect','Engineer','QS'}:
            raise ValueError('Shared investment needs independent service-region declarations for all three professions')
        initiation_regions=sorted(set.intersection(*service_regions.values()))
        if not initiation_regions:
            raise ValueError('Shared initial professional sources have no common declared investment service region')
        _write(directory,'initial-owner-investment-preference.json',{
            'organization_id':'finance-owner-a','initiation_region_ids':initiation_regions,
            'basis':'Explicit initial scenario preference using the intersection of independent professional service scopes.',
            'source':professional_settings['owner']['file_path'],
            'source_sha256':professional_settings['owner']['file_sha256'],
            'planned_professional_object_types':deepcopy(professional_types),
            'boundary':'A private initiation preference, not a global region limitation or an expansion of provider qualifications.'})
        opportunity_dir=directory/'sources/opportunity'
        opportunity_bundle(opportunity_dir,run_id=run_id,max_prior_initiations=max_prior_initiations,
            initial_investment_policy=owner_initial_investment_policy,
            max_prior_payment_requests=max_prior_payment_requests,owner_funding=owner_funding,
            max_prior_final_accounts=max_prior_final_accounts,
            initiation_region_ids=initiation_regions,with_payment_project=with_payment_project,
            with_observation=with_owner_observation,observation_minimum_demand=owner_observation_minimum_demand,
            with_proposal=with_owner_proposal,proposal_review_cost=owner_proposal_review_cost,
            proposal_review_effort=owner_proposal_review_effort,
            study_question_code=owner_study_question_code,study_budget=owner_study_budget,
            study_target_interventions=owner_study_target_interventions,
            study_estimated_cost=owner_study_estimated_cost,study_resource_requirement=owner_study_resource_requirement,
            study_duration=owner_study_duration,study_qualified=owner_study_qualified,
            study_service_offer=owner_study_service_offer,
            study_professional_intake=owner_study_professional_intake,
            allow_saved_recovery=allow_owner_opportunity_saved_recovery,
            query_saved_opportunity_on_error=query_saved_opportunity_on_error,
            max_prior_declines=max_prior_opportunity_declines)
        if with_payment_project:
            native=read(opportunity_dir/'macro-request.json')
            initial=native['initial_projects']
            if len(initial)!=1 or initial[0]['project_id'] in {p['project_id'] for p in request['initial_projects']}:
                raise ValueError('Shared payment source must supply one distinct explicit initial construction project')
            project=initial[0];contractor=project['selected_contractor_id']
            agent,=[a for a in request['agents'] if a['agent_id']==contractor and a['role']=='Contractor']
            original,=[a for a in native['agents'] if a['agent_id']==contractor and a['role']=='Contractor']
            load=sum((Decimal(str(e['resource_allocation'])) for e in project['engagements']
                if e['agent_id']==contractor and e['status']=='active'),Decimal(0))
            combined=Decimal(str(agent['occupied_resource']))+load
            if (project['owner_id']!='finance-owner-a' or load<=0
                    or load!=Decimal(str(original['occupied_resource']))
                    or combined>Decimal(str(agent['total_resource_capacity']))):
                raise ValueError('Shared payment case must retain its independently declared parties and initial engagement load')
            # Add disjoint initial engagement declarations before engine
            # creation, never infer or update live resource reservations.
            agent['occupied_resource']=float(combined)
            request['initial_projects'].append(deepcopy(project))
            request['target_project_count']+=1;request['max_active_projects']+=1
            provenance=(provenance if provenance is not None else {
                'schema_version':'shared-role-initial-cases.v1','run_id':run_id,'initial_projects':[],
                'planned_generated_project_ids':['PGEN0001','PGEN0002']})
            provenance['initial_projects'].append({'project_id':project['project_id'],'owner_id':project['owner_id'],
                'current_stage':project['current_stage'],'source':str(opportunity_dir/'macro-request.json'),
                'status':'explicit_initial_assumption','additional_initial_contractor_load':str(load),
                'boundary':'Existing construction/contract/progress and allocation are initial declarations, not micro execution or payment.'})
        opportunity_settings=read(opportunity_dir/'assembly-host.json')['settings']
        components['opportunity']=_source_files(directory,settings=opportunity_settings,substitutions={},
            initial_support_actor_ids=shared_actor_ids,
            files=[(None,'owner-opportunity-input.json')])
        snapshot=_merge_snapshot(snapshot,components['opportunity']['authority']['organization_snapshot'])
        routes['micro_owner_opportunity_scope']=True
        routes['query_saved_opportunity_on_error']=query_saved_opportunity_on_error
        routes['native_proposals']=[r for r in routes['native_proposals']
            if (r['role'],r['operation'])!=('Owner','evaluate_project_opportunity')]
        routes['native_decisions']=[r for r in routes['native_decisions'] if (r['role'],r['decision_type']) not in {
            ('Owner','owner_project_opportunity'),('Owner','owner_project_initiation')}]
    if with_contractor_formation:
        from integration.contractor_formation_native_development import build_bundle as formation_bundle
        formation_dir=directory/'sources/formation'
        # Declare the final shared actors before original agreement digests,
        # grants and any business result exist. No sealed template is renamed.
        participants={role:sorted(a['agent_id'] for a in request['agents'] if a['role']==role)[0]
            for role in ('Owner','Contractor','QS','Bank','Architect','Engineer','Government','Supplier')}
        formation_bundle(formation_dir,run_id=run_id,max_prior_accept_terms=max_prior_accept_terms,
            organization_ids=participants,clock_id=run_id+'-monthly-clock',
            followup_ticks=(2,4) if with_contract_supply_handoff else (2,),
            with_owner_award=with_owner_award,max_prior_owner_accepts=max_prior_owner_accepts,
            max_prior_owner_payment_delays=max_prior_owner_payment_delays,
            max_prior_construction_suspensions=max_prior_construction_suspensions,
            with_suspension_project=with_suspension_project,suspension_project_design_quality=suspension_project_design_quality)
        components['formation']=_source_files(directory,
            initial_support_actor_ids=shared_actor_ids,
            settings=read(formation_dir/'assembly-host.json')['settings'],substitutions={},
            files=[(None,'contractor-formation-input.json')]+([('owner','owner-award-input.json')] if with_owner_award else []))
        snapshot=_merge_snapshot(snapshot,components['formation']['authority']['organization_snapshot'])
        original=read(formation_dir/'macro-request.json')
        existing_ids={p['project_id'] for p in request['initial_projects']}
        if any(p['project_id'] in existing_ids for p in original['initial_projects']):
            raise ValueError('Initial contract terms repeat a shared project identity')
        request['initial_projects'].extend(deepcopy(original['initial_projects']))
        if with_suspension_project:
            # Merge the explicitly declared initial native engagement, rather
            # than treating a later suspension as capacity release.
            contractor=next(a for a in request['agents'] if a['agent_id']==participants['Contractor'])
            contractor['occupied_resource']=contractor.get('occupied_resource',0)+sum(
                e['resource_allocation'] for p in original['initial_projects'] for e in p.get('engagements',[])
                if e['agent_id']==participants['Contractor'])
        request['target_project_count']+=len(original['initial_projects'])
        request['max_active_projects']+=len(original['initial_projects'])
        request['ticks']=4 if with_contract_supply_handoff else 3
        # The original generator includes initial projects in its target and
        # spreads that target over floor(0.75*ticks). Preserve a first-tick
        # opportunity window for the original financing/appointment sources.
        # This is an initial scenario target, not a promise of future projects;
        # max_active_projects still allows only the two original new slots.
        initial_count=len(request['initial_projects'])
        generation_horizon=max(1,min(request['ticks'],int(request['ticks']*0.75) or request['ticks']))
        request['target_project_count']=max(request['target_project_count'],initial_count*generation_horizon+1)
        routes['micro_contractor_formation_scope']=True
        routes['micro_owner_award_scope']=with_owner_award
        if not with_owner_award:
            routes['native_proposals'].append({'role':'Owner','operation':'decide_contract_award'})
            routes['native_decisions'].append({'role':'Owner','decision_type':'owner_contract_award'})
        if with_contract_supply_handoff:
            # The older regulatory case now reaches tendering. This request
            # is explicitly outside this window's micro ownership; no tender
            # completion or micro A01/A02 coverage is claimed for that case.
            routes['native_proposals'].append({'role':'Contractor','operation':'consider_tender'})
            routes['native_decisions'].append({'role':'Contractor','decision_type':'tender_decision'})
        provenance=(provenance if provenance is not None else {
            'schema_version':'shared-role-initial-cases.v1','run_id':run_id,'initial_projects':[],
            'planned_generated_project_ids':['PGEN0001','PGEN0002']})
        provenance['native_generation_configuration']={
            'initial_project_count':initial_count,'ticks':request['ticks'],
            'original_generation_horizon':generation_horizon,
            'target_project_count':request['target_project_count'],
            'max_active_projects':request['max_active_projects'],
            'purpose':'Permit first-tick opportunities in the existing native generator while retaining two additional active-project slots.',
            'boundary':'Initial configuration only; actual opportunity, acceptance, creation and timing remain native outcomes.'}
        for project in original['initial_projects']:
            provenance['initial_projects'].append({'project_id':project['project_id'],'owner_id':project['owner_id'],
                'current_stage':project['current_stage'],'source':str(formation_dir/'macro-request.json'),
                'status':'explicit_initial_assumption','initial_identity_bindings':participants,
                'identity_binding_phase':'before initial agreement, evidence and business-result digests',
                'boundary':'Selected bid and initial terms are independent sources; current A04 posture, signature and allocation must come from actual native execution.'})
    tender_configuration=None
    if with_contractor_tender:
        from integration.owner_invitation_development import build_bundle as invitation_bundle
        native_invitation_project_ids=[p['project_id'] for p in request['initial_projects']]
        tender_dir=directory/'sources/tender'
        invitation_options=dict(owner_id='finance-owner-a',qs_id='finance-qs',
            contractor_ids=tender_contractor_ids,clock_id=run_id+'-monthly-clock',
            organization_capacity_totals={row['agent_id']: row['total_resource_capacity']
                for row in request['agents'] if row['agent_id'] in tender_contractor_ids},
            clock_tick_unit='month',
            project_id='shared-tender-project',source_namespace='shared-',authority_namespace='shared-tender-',
            feedback_followup=with_tender_feedback,followup_project_id='shared-tender-followup',
            query_prior_submissions=query_prior_tender_submissions,
            organization_locations={row['organization_id']:row['public_location'] for row in snapshot['organizations']},
            additional_candidate_organizations=[row for row in snapshot['organizations']
                if row['organization_id'] not in tender_contractor_ids
                and any(assignment['role']=='Contractor' for assignment in row['assignments'])],
            allow_saved_recovery=allow_tender_saved_recovery,query_saved_tender_on_error=query_saved_tender_on_error,
            continue_unstarted_actions_on_error=continue_unstarted_tender_actions_on_error,
            with_clarification_request=with_tender_clarification_request,
            with_clarification_response=with_tender_clarification_response,
            continue_clarification=continue_tender_clarification,
            initial_screening_policies=tender_initial_screening_policies,
            decline_after_prior_declines=tender_decline_after_prior_declines,
            decline_after_prior_final_accounts=tender_decline_after_prior_final_accounts,
            decline_after_prior_payment_delays=tender_decline_after_prior_payment_delays,
            allow_followup_bids=allow_tender_followup_bids)
        if with_qs_evaluation:
            from integration.qs_bid_native_development import build_bundle as evaluation_bundle
            evaluation_bundle(tender_dir,run_id=run_id,with_native_owner_selection=True,
                with_evaluation_feedback=with_tender_feedback,with_qs_learning=with_qs_learning,
                allow_qs_learning_saved_recovery=allow_qs_learning_saved_recovery,
                query_saved_qs_learning_on_error=query_saved_qs_learning_on_error,owner_options=invitation_options,
                exclude_contractor_id=qs_exclude_contractor_id)
        else:
            invitation_bundle(tender_dir,run_id=run_id,**invitation_options)
        tender_configuration=read(tender_dir/'tender-host.json')
        tender_settings=tender_configuration['settings']['source_settings']['application_settings']
        owner_settings=tender_settings['owner_contractor'] if with_qs_evaluation else tender_settings
        if with_qs_evaluation:
            owner_settings['owner_invitation']['native_project_ids']=native_invitation_project_ids
        tender_application=owner_settings['contractor']
        snapshot=_merge_snapshot(snapshot,tender_application['authority']['organization_snapshot'])
        original=read(tender_dir/'macro-request.json')
        for agent in original['agents']:
            existing=next((row for row in request['agents'] if row['agent_id']==agent['agent_id']),None)
            if existing is None:request['agents'].append(deepcopy(agent))
            elif existing['role']!=agent['role'] or existing['region']!=agent['region']:
                raise ValueError('Shared tender changes an original actor role or region')
        if {p['project_id'] for p in original['initial_projects']} & {p['project_id'] for p in request['initial_projects']}:
            raise ValueError('Shared tender repeats an initial project identity')
        request['initial_projects'].extend(deepcopy(original['initial_projects']))
        request['ticks']=max(request['ticks'],original['ticks'])
        request['target_project_count']+=len(original['initial_projects'])
        request['max_active_projects']+=len(original['initial_projects'])
        initial_count=len(request['initial_projects'])
        generation_horizon=max(1,min(request['ticks'],int(request['ticks']*0.75) or request['ticks']))
        request['target_project_count']=max(request['target_project_count'],initial_count*generation_horizon+1)
        routes['native_proposals']=[row for row in routes['native_proposals']
            if (row['role'],row['operation']) not in {('Owner','select_tender_invitees'),('Contractor','consider_tender')}]
        routes['native_decisions']=[row for row in routes['native_decisions']
            if (row['role'],row['decision_type']) not in {('Owner','owner_tender_shortlist'),('Contractor','tender_decision')}]
        routes['query_saved_tender_on_error']=query_saved_tender_on_error
        if with_qs_evaluation:
            routes['micro_qs_evaluation_scope']=True
            routes['mixed_qs_learning_scope']=with_qs_learning
            routes['query_saved_qs_learning_on_error']=query_saved_qs_learning_on_error
            routes['mixed_owner_invitation_scope']=True
            routes['native_proposals']=[row for row in routes['native_proposals']
                if (row['role'],row['operation'])!=('QS','evaluate_bid')]
            routes['native_decisions']=[row for row in routes['native_decisions']
                if (row['role'],row['decision_type'])!=('QS','qs_bid_evaluation')]
            proposal_routes=[{'role':'Owner','operation':'select_preferred_bid'},
                {'role':'Owner','operation':'select_tender_invitees'}]
            final_routes=[{'role':'Owner','decision_type':'owner_preferred_bidder_selection'},
                {'role':'Owner','decision_type':'owner_tender_shortlist'}]
            if with_tender_feedback:
                if not with_contractor_formation:
                    proposal_routes.append({'role':'Contractor','operation':'decide_contract_terms'})
                    final_routes.append({'role':'Contractor','decision_type':'contract_negotiation'})
                if not with_owner_award:
                    proposal_routes.append({'role':'Owner','operation':'decide_contract_award'})
                    final_routes.append({'role':'Owner','decision_type':'owner_contract_award'})
            for key,extra in [('native_proposals',proposal_routes),('native_decisions',final_routes)]:
                existing={task_digest(row):row for row in routes[key]}
                existing.update({task_digest(row):row for row in extra})
                routes[key]=list(existing.values())
            routes['direct_native_proposals']=[{'role':'Owner','operation':'select_preferred_bid'}]
        provenance=(provenance if provenance is not None else {
            'schema_version':'shared-role-initial-cases.v1','run_id':run_id,'initial_projects':[],
            'planned_generated_project_ids':['PGEN0001','PGEN0002']})
        for project in original['initial_projects']:
            provenance['initial_projects'].append({'project_id':project['project_id'],'owner_id':project['owner_id'],
                'current_stage':project['current_stage'],'source':str(tender_dir/'macro-request.json'),
                'status':'explicit_initial_assumption',
                'initial_identity_bindings':{'owner':'finance-owner-a','qs':'finance-qs',
                    'contractors':list(tender_contractor_ids),'clock':run_id+'-monthly-clock'},
                'identity_binding_phase':'before initial source, authorization and business-input digests',
                **({'evaluation_source_note':read(tender_dir/'source-note.json')} if with_qs_evaluation else {}),
                'boundary':('Explicit pre-existing invitations in the first project; original OWN-A09 selects later invitees. '
                    if with_qs_evaluation and with_tender_feedback else
                    'Original OWN-A09 selects actual eligible native candidates; invitations and bids remain native outcomes. ')+
                    'Other original shared Contractors do not inherit these independent professional records.'})
        provenance['native_generation_configuration']={
            'initial_project_count':initial_count,'ticks':request['ticks'],'original_generation_horizon':generation_horizon,
            'target_project_count':request['target_project_count'],'max_active_projects':request['max_active_projects'],
            'boundary':'Initial configuration only; actual creation and timing remain native outcomes.'}
    if with_payment_positions:
        from integration.progress_payment_development import shared_initial_sources as payment_sources
        from integration.native_lifecycle_actions import NativeLifecycleInput
        payment_projects=[p for p in request['initial_projects']
            if p['project_id']==(payment_position_project_id or 'owner-existing-construction')]
        if len(payment_projects)!=1:
            raise ValueError('Shared payment positions require exactly one declared original target project')
        payment_project,=payment_projects
        if (not payment_project.get('selected_contractor_id') or not payment_project.get('owner_id')
                or payment_project['selected_contractor_id']==payment_project['owner_id']):
            raise ValueError('Shared payment target requires distinct declared Owner and selected Contractor')
        if max(progress_payment_ticks) > request['ticks']:
            raise ValueError('Shared payment windows extend beyond the declared native horizon')
        payment_windows=[]
        payment_document={'run_id':run_id,'plans':[]}
        for tick in progress_payment_ticks:
            payment_snapshot,window=payment_sources(run_id=run_id,
                project_id=payment_project['project_id'],organization_snapshot=snapshot,
                owner_id=payment_project['owner_id'],contractor_id=payment_project['selected_contractor_id'],
                clock_id=run_id+'-monthly-clock',tick=tick)
            snapshot=_merge_snapshot(snapshot,payment_snapshot)
            payment_document={**window,'plans':payment_document['plans']+window['plans']}
            payment_windows.append({'tick':tick,'initial_snapshot_sha256':task_digest(payment_snapshot),
                'independent_input_sha256':task_digest(window)})
        if lifecycle_document is not None:
            payment_document['plans']=[p.model_dump(mode='json') for p in lifecycle_document.plans]+payment_document['plans']
        if len({p['plan_id'] for p in payment_document['plans']})!=len(payment_document['plans']):
            raise ValueError('Shared payment positions repeat a lifecycle plan identity')
        lifecycle_document=NativeLifecycleInput.model_validate(payment_document)
        provenance['progress_payment_positions']={
            'project_id':payment_project['project_id'],
            'target_source':'explicit_existing_project' if payment_position_project_id is not None else 'initial_construction_case',
            'initial_stage':payment_project['current_stage'],
            'initial_snapshot_sha256':task_digest(payment_snapshot),
            'windows':payment_windows,
            'independent_input_sha256':task_digest(payment_document),
            'boundary':'Independent private disputed obligations with unknown money. Actual payment request '
                'triggers original Owner negotiation; only actual delay triggers original Contractor A10 review. '
                'Incomplete private payment history must remain needs-info, not a completed dispute. '
                'No certificate, formal submission, cash, debt or external receipt is created.'}
    if with_final_account_discussion:
        from integration.final_account_discussion_development import shared_initial_sources
        from integration.native_lifecycle_actions import NativeLifecycleInput
        final_snapshot, final_document, final_project = shared_initial_sources(run_id=run_id,
            project_id='shared-final-account-review', organization_snapshot=snapshot,
            owner_id='finance-owner-a', contractor_id=final_account_contractor_id or 'finance-contractor', qs_id='finance-qs',
            clock_id=run_id+'-monthly-clock', with_owner_response=with_final_account_response,
            with_contractor_response=with_contractor_final_account_response)
        if with_final_account_learning:
            from integration.final_account_learning_development import add_settlement_learning
            final_snapshot, final_document = add_settlement_learning(snapshot=final_snapshot, document=final_document)
        if final_project['project_id'] in {p['project_id'] for p in request['initial_projects']}:
            raise ValueError('Shared final-account discussion repeats an initial project identity')
        snapshot=_merge_snapshot(snapshot,final_snapshot)
        if lifecycle_document is not None:
            final_document['plans']=[p.model_dump(mode='json') for p in lifecycle_document.plans]+final_document['plans']
        if len({p['plan_id'] for p in final_document['plans']}) != len(final_document['plans']):
            raise ValueError('Shared final-account discussion repeats a lifecycle plan identity')
        lifecycle_document=NativeLifecycleInput.model_validate(final_document)
        request['initial_projects'].append(final_project)
        request['max_active_projects']+=1
        generation_horizon=max(1,min(request['ticks'],int(request['ticks']*0.75) or 1))
        request['target_project_count']+=generation_horizon
        if with_final_account_followup:
            # Keep the already-declared first-tick opportunity window despite
            # extra initial cases and the longer native generation horizon.
            request['target_project_count']=max(request['target_project_count'],
                len(request['initial_projects'])*generation_horizon+1)
        provenance['initial_projects'].append({'project_id':final_project['project_id'],
            'owner_id':final_project['owner_id'],'source':'explicit_final_account_discussion_initial_case',
            'boundary':'Initial final-account stage and selected parties are assumptions, not generated design, award, work, debt or cash history.'})
        provenance['final_account_discussion']={'project_id':final_project['project_id'],
            'initial_snapshot_sha256':task_digest(final_snapshot),
            'independent_input_sha256':task_digest(final_document),
            'boundary':'Explicit initial private sources. Only actual current native review can trigger communication; no settled agreement or payment is supplied.'}
        if with_final_account_learning:
            provenance['final_account_discussion']['qs_settlement_learning'] = {
                'action_id': 'QS-A12', 'event_type': 'final_account_settled',
                'boundary': 'Original own QS review prerequisite and actual aggregate settlement only. '
                    'No forecast error, cash receipt, debt clearance or capability improvement is inferred.'}
        if with_final_account_followup:
            provenance['final_account_discussion']['later_owner_feedback']={
                'earliest_consumer_tick':3, 'max_prior_final_accounts':max_prior_final_accounts,
                'boundary':'Only actual strictly earlier native settlement events enter the private preference. '
                    'The longer initial horizon supplies no settlement, cash, debt clearance or promised opportunity.'}
        provenance['native_generation_configuration']={
            'initial_project_count':len(request['initial_projects']),'ticks':request['ticks'],
            'original_generation_horizon':generation_horizon,
            'target_project_count':request['target_project_count'],'max_active_projects':request['max_active_projects'],
            'boundary':'Initial configuration only; actual creation and timing remain native outcomes.'}
    if owner_payment_reliability is not None:
        owner, = [a for a in request['agents'] if a['agent_id']=='finance-owner-a' and a['role']=='Owner']
        original_reliability = owner['payment_reliability']
        owner['payment_reliability'] = owner_payment_reliability
        provenance['initial_native_payment_conditions'] = {
            'owner_id':owner['agent_id'],'payment_reliability':owner_payment_reliability,
            'default_payment_reliability':original_reliability,'random_seed':request['random_seed'],
            'status':'explicit_initial_assumption',
            'boundary':'Initial scenario conditions only. The unchanged native engine decides actual payment '
                'request status and delay; no event, due amount, debt or cash execution is supplied.'}
    if provenance is not None:_write(directory,'input-provenance.json',provenance)
    authority = {'runtime_id': run_id + '-combined-authority', 'version': '1', 'organization_snapshot': snapshot}
    for body in components.values():
        body['authority'] = deepcopy(authority)
    if lifecycle_document is not None:
        # These are explicit initial grants. No runtime authority or native
        # business state is written, and existing grant versions cannot change.
        grants=[deepcopy(row['value']) for plan in lifecycle_document.plans
            for row in plan.objects if row['ref']['kind']=='Authorization']
        snapshot=_merge_snapshot(snapshot,{**deepcopy(snapshot),'authorizations':grants,'inactive_authorization_refs':[]})
        authority['organization_snapshot']=snapshot
        for body in components.values():
            body['authority']=deepcopy(authority)
        components['lifecycle']={'version':'1','policy_version':'native-lifecycle-independent-inputs.v1',
            **_write(directory,'lifecycle-actions-input.json',lifecycle_document.model_dump(mode='json'))}
    if tender_configuration is not None:
        tender_application['authority']=deepcopy(authority)
        components['tender']=tender_configuration
    settings = FinancingProfessionalSettings.model_validate(components)
    from gba_construction_sim.backend.models.simulation import SimulationCreateRequest
    request = SimulationCreateRequest.model_validate(request)
    routes = NativeRouteSettings.model_validate(routes)
    _write(directory, 'macro-request.json', request.model_dump(mode='json'))
    for name, body in [('native-host.json', routes.model_dump(mode='json')),
            ('assembly-host.json', settings.model_dump(mode='json'))]:
        _write(directory, name, {'schema_version': 'gba-module-host-config.v1', 'host_id': run_id, 'version': '1', 'settings': body})
    readme = '''# 融资与专业委任的同一运行装配

运行 `& ./run.ps1`，已有输出时指定新的 OutputDirectory。此输入包尚待集中业务联调。
同一个原生引擎、组织/授权快照、动作登记器、任务库和业务时钟，覆盖八角色。
--professional-project-object-types 接受包含 PGEN0001/PGEN0002 的 JSON 对象，在封装前声明两个专业来源的对象类型；原服务条款、能力与方法支持域由已有生成器一起生成，运行期仍要求与实际项目匹配。它不推断真实资质，也不在来源不匹配时改写原资料。
一个业主、两个银行、两名建筑师及其余支持角色均预先明确提供；宏观产生实际项目。
--bank-actor-ids 接受原两家银行组织到执行 actor 的初始 JSON 映射。银行业务复用原授权表，其他初始来源仅同步没有授权、没有业务 actor 载荷的银行支持身份；已有授权或已绑定来源不改写。其他角色的执行身份沿用各自既有来源，不能用此参数迁移旧任务或代签。
融资复用原 Bank A01—A05 与 OWN-A05，专业委任复用三专业 A02/A03 与 OWN-A04。
微观动作仅在实际请求/本机构事件到达时执行；两类确认分别消费自己的实际选中事件。
后续业务仅读取严格较早的本机构真实反馈。专业费率、财务和物理容量仍是明确合成假设。
月度操作保留显式宏观原生路由；机会判断默认使用宏观原实现，可显式启用原 OWN-A03。未接管的后续业务不计入微观完成。
原生正式状态继续由宏观维护，不创建详细贷款、放款、服务付款或独立资源预留账本。
sources/bank/ 只提供初始资料，业务统一从顶层 run.ps1 启动。
sources/ 保留初始输入，顶层输入固定共享身份和时钟；历史输入和失败记录不改写。
监管、供应的主体、函数与时钟在生成材料及其内容/方法/协议/草稿摘要前绑定，不对已封装的来源做字符串换名。
'''
    if lifecycle_document is not None:
        readme+='\n--lifecycle-input 使用已绑定本运行身份、项目、时钟和授权的履约/收尾输入文件。原 EventSystem 观察器在真实合同、选供、付款请求或结算事件后调用既有原动作 assembler/worker，同组织依赖读取其原始保存结果；独立明细来源不改写为宏观事实。未知执行不重跑，未解决依赖不推进。默认形成私有产物；显式 final_account_disclosure 可将原 OWN-A06 意见发送至原结算会话，final_account_question_reception 可将实际送达意见交原 QS-A09 补证，publish_question_text 显式允许把原问题经原会话送回实际业主。沟通不证明材料已提供、双方同意或结算确定。正式生产、物流、核证及资金命令仍须具体原生提交/查询绑定。详细 core_event_id 来源须有经核定的原生读取器，本入口不以汇总事件替代。共享业务仍待集中联调。\n'
        readme+='已有原结果通过 query_saved_result/recover_saved_result 查询及完成技术状态，核验原注册、快照、七版本、来源与授权；不调用动作构建、执行或正式提交。原生观察器报错诊断单独保留，业务字段仍严格核对。重新挂接要求原引擎事件和任务库可核验，不代表完整宏观进程重启已实现。\n'
        readme+='前序未开始、需补资料或执行未知时，后继保留 waiting_dependencies 技术记录，不注册原动作；同事件中无依赖的其他计划继续。query_saved_result 只报告等待及是否就绪；补齐原结果后，须通过原应用 resume_waiting_dependencies(plan_id) 在原业务时点显式启动尚未注册的后继。事件重投不会自动启动已等待计划，未知前序不重跑；跨过原时点须另有有权的新业务接续。\n'
    if with_final_account_discussion:
        readme+='\n--with-final-account-discussion 声明一个期初结算审查项目及四项独立微观计划，复用本运行的业主、承包商和 QS 身份、授权、任务库及月度时钟。原生审查实际发生后，原 OWN-A06 发出争议意见，后继原业主任务消费送达回执；原 CONTRACTOR-A11 读取实际业主意见及独立未量化争议项，形成原结算提议并向业主/QS 发送 choice/note；原 QS-A09 读取双方实际收件及独立 Evidence，再将补证问题发回业主。引用收到的意见不得扩大原实际收件范围。私有组件/债务不跨机构复制；期初阶段不是本轮施工完成，通信不等于结算申报登记、双方同意或现金清偿。\n'
        if with_final_account_response:
            readme+='\n--with-final-account-response 增加原业主 A06 后续处理：读取实际送达的 QS 补证问题及独立收件 Evidence，按事先声明的私有协商输入形成 negotiate，再通过原会话仅答复 QS。同一时点的原 QS 收件按显式消息序号固定，后续通信不替换早先读取。答复不表示已补齐证据、承认金额、正式登记或付款。\n'
        if with_contractor_final_account_response:
            readme+='\n--with-contractor-final-account-response 增加承包商原 A11 respond_settlement：从本机构已保存且当前可读的原提议生成 proposed 私有历史视图，再读取原业主实际意见作答。合同引用版本、未量化组件及持续义务保留；不创建正式登记、同意或清偿。原 QS 读取固定较早承包商消息序号，后继通信不替换旧输入。\n'
    if with_government_and_supply:
        readme += '''
已显式启用 --with-government-and-supply：原 Government A02/A04/A07、Supplier A01—A04
及 Contractor A05 与融资、专业应用共用同一登记器、授权快照、任务库和业务时钟。
监管与供应分别收到本机构原生请求后执行，后续消费原有本机构反馈；无新增正式账本。
input-provenance.json 列明四个独立初始项目：审批/设计项目与既有合同准备项目。
它们是输入假设，不是本轮投资、设计、评标或合同谈判已经完成的证据；生成的 PGEN 项目仍单独追踪。
新增两个机构/供应商均事先声明，承包商初始占用 0.8 与显式既有 engagement 一致。
该候选覆盖八角色的既有接线装配，不能据此宣称 106 动作或完整项目生命周期运行通过。
政府完工审批、生产/物流/收货、实际计量/资金执行等后续业务仍待接入和集中验证。
'''
    if with_government_feedback:
        readme+='\n已显式启用 --with-government-feedback：监管应用在实际审批前执行原 GOV-A12 record_feedback，原 A04/A07 读取同一次已审计的私有反馈结果。来源为本机构有权查询且核实的较早审批历史；不改政策、独立合规事实或宏观账本。原 A12 与其他动作共用授权、登记器、任务库和业务时钟；实际消费仍待集中联调。\n'
    if with_government_monthly_feedback:
        readme+='\n已显式启用 --with-government-monthly-feedback：原监管月度请求执行原 GOV-A12，经原 bounded decision 返回 review_policy_feedback；实际执行和企业记忆仍由原宏观记录。后续月度与审批读取本机构严格较早的原事件、微观结果、提案及最终确认，不修改政策参数，不将经验记录当作正式规章、现场检查或资金执行。\n'
    if allow_government_monthly_saved_recovery:
        readme+='\n已启用 --allow-government-monthly-saved-recovery，可查询当前原生月度请求中已保存的原 GOV-A12 结果；--query-saved-monthly-on-error 在原调用仍等待时自动查询。核对原请求/来源/权限/版本及审计，不重跑微观、不重启引擎、不新建或重提业务；缺结果保持未决。\n'
    if allow_government_intake_saved_recovery:
        readme+='\n已启用 --allow-government-intake-saved-recovery：查询同一当前原生受理请求下已保存的原 GOV-A02 完成结果，补全技术状态并还原原响应；--query-saved-intake-on-error 可返回同一仍在等待的原宏观调用。缺结果、等待及未知保持未决，不重跑处理器、不执行缺失阶段、不恢复失败时点、不创建补件接收或重提正式业务。\n'
    if allow_government_saved_recovery:
        readme+='\n已显式启用 --allow-government-saved-recovery：`assembly.client.recover_proposal(original_request)` 仅读取同一当前原生请求下已持久化的原监管阶段结果，补全技术状态并还原原响应。无原结果不重跑；不恢复宏观引擎、不推进时点、不投递或重提正式业务。默认关闭，故障场景留待集中验证。\n'
    if query_saved_approval_on_error:
        readme+='\n已显式启用 --query-saved-approval-on-error：原生审批调用仍在等待时，技术收尾异常可触发原已完成结果的查询与核验，成功后只将同一响应交回同一调用。缺阶段、未知、来源/权限/版本/当前请求变化时继续报原错误；不重跑微观、启动新请求、重启宏观或重复提交。\n'
    if continue_unstarted_government_approval_actions_on_error:
        readme+='\n--continue-unstarted-government-approval-actions-on-error 允许原审批调用仍等待时，原 GOV-A12/A04/A07 已注册而原执行声明证明准备未开始的阶段继续一次。共用原授权、登记器及任务库，重新核对当前来源和版本。默认关闭，独立于已保存结果查询；已开始但缺结果、补件等待或未知状态不重跑，不重启宏观或重提业务。\n'
    if with_owner_opportunity:
        readme+='\ninitial-owner-funding.json 是立项、融资及借款人资料共用的初始合成现金/旧债声明；不是运行期资金账本。initial-owner-investment-preference.json 从原专业服务声明的共同地域形成显式场景立项偏好，由原 OWN-A03 拒绝不符合条件的机会；不扩大专业资质，也不限制其他输入场景支持的地域。专业委任资料按原生融资后下一时点发出委任的时序提供。\n'
    if allow_owner_opportunity_saved_recovery:
        readme+='\n已启用 --allow-owner-opportunity-saved-recovery：只查询同一当前业主机会请求已保存的原动作结果；--query-saved-opportunity-on-error 允许原调用仍等待时核验并补齐技术收尾。完整所需链必须已有原结果；缺阶段不执行、不重跑、不新建或重提原生业务，不提供引擎重启恢复。\n'
    if with_owner_opportunity:
        if max_prior_final_accounts is not None:
            readme+='\n--max-prior-final-accounts N 需 --with-owner-opportunity：在后续真实立项机会中读取本业主严格较早的实际原生汇总结算事件，达到独立声明的次数阈值后由原 OWN-A03 暂缓新增投资。正式项目仍由宏观决定；不生成结算项目、不自动运行私有复核、不把汇总结算当作到账、清债、缺陷关闭或移交完成。三时点组合已有定向业务证据，其他配置与全量回归仍待集中核验。\n'
            if with_final_account_followup:
                readme+='\n与 --with-final-account-discussion 组合时，初始运行至少覆盖时点 3：原宏观先在时点 1 审查、时点 2 结算，后轮原 OWN-A03 才能读取严格较早的实际反馈。初始生成目标保留原第一时点机会窗口；不生成结算事件或强制未来立项。\n'
        readme+='\n已显式启用 --with-owner-opportunity：原 OWN-A03 复用同一授权运行时、登记器、任务库和锁处理真实立项机会，再由原宏观选择候选并创建项目。独立合成的财务、旧债、管理容量、资质和权利保持显式来源；不从能力分推现金，也不声称执行 OWN-A01/A02/A16。--max-prior-initiations 和 --max-prior-payment-requests 可配置原私有偏好，均默认不限制；无本项开关时不接管立项。实际创建及可选付款请求历史仅供本业主后续使用，不创建正式资金或资源账本。\n'
    if with_owner_observation:
        readme=readme.replace('也不声称执行 OWN-A01/A02/A16。','也不声称执行 OWN-A02/A16。')
        readme+='\n已显式启用 --with-owner-observation：当前机会请求先执行原 OWN-A01，再将真实 follow 结果、原来源与审计摘要交原 OWN-A03 读取。--owner-observation-minimum-demand 声明私有筛选阈值，默认 0；原 ignore 直接返回原宏观 defer_project，不执行 A03。观察使用当前原宏观全局需求指数，不冒充地区调查或专业预测；独立管理池、筛选工作量和研究许可均为场景声明。候选跟踪不创建正式项目、案件、权利或资源承诺；其他结果保留并停止复核。\n'
    if owner_initial_investment_policy is not None:
        readme+='\n--owner-initial-investment-policy 显式声明原 A03 初始私有策略，prepare_only 只允许原处理器选有界准备方案，宏观暂不立项。后轮原动作读取当前有权的原计划/范围/条件和拟议投入，不推造项目、现金执行、资源预留或准备已完成。既有 --max-prior-opportunity-declines 计原生暂不立项事件，保留原微观决定语义。\n'
    if max_prior_opportunity_declines is not None:
        readme+='\n已声明 --max-prior-opportunity-declines：后续原投资仅按本业主严格较早的真实原生不立项事件数采用私有偏好。每个实际事件关联原 A01 ignore 或 A03 拒绝/准备结果、原提案和最终确认；不按多个私有候选数量计数，不视为创建、支出、债务或未清义务。默认关闭。\n'
    if with_payment_project:
        readme+='\n已显式启用 --with-payment-project：从原立项输入包接入一个已声明合同、工期和进度的既有施工项目。其实际进度款请求由原宏观在本共享运行中产生，后续原 OWN-A03 可按显式请求数偏好消费；同一承包商初始占用仅叠加两份互不重叠的初始 engagement 声明。请求 approved/delayed 不代表划款、到账或清债，所有原财务余额保持初始声明，不从事件推导运行期余额。\n'
    if with_payment_positions:
        readme+='\n已显式启用 --with-payment-positions：复用原履约事件应用，真实 payment_requested 触发原 OWN-A06 negotiate，真实 payment_delayed 才触发原 CONTRACTOR-A10 付款审查；未延期时承包商计划保持未触发。双方独立声明未量化争议义务、机构职能和授权，原动作读取实际事件 Evidence。承包商付款历史明确不完整，原工作器应保留 needs-info，不宣称争议决定已完成。HKD 仅为独立合同输入，不换算宏观请求金额。当前仅形成私有处理，不提交付款、发送对外催款、改变义务或证明到账。\n'
        if payment_position_project_id is not None:
            readme+='\n--payment-position-project-id '+payment_position_project_id+' 将上述私有处理绑定到已有初始项目，不添加替代施工项目。可与既有签约/选供窗口组合；只有原宏观实际产生付款请求或延期才触发。原生签约及选供历史存在时，付款来源保留其精确双日志和事件摘要；不从初始声明制造运行期签约或选供。\n'
    if random_seed is not None or owner_payment_reliability is not None:
        readme+='\n--random-seed 及 --owner-payment-reliability 仅声明最初场景条件；付款可靠性需 --with-payment-project。原宏观自行决定真实请求和延期，不预设事件或到账。延期处理核对同项目、时点、双方及金额的唯一较早真实请求，后轮条款判断仅按实际延期记录收紧私有偏好，不推算欠款。\n'
    if with_payment_positions:
        readme+='\n--progress-payment-ticks 1 2 可声明多个独立付款处理时点，默认仅 1。各时点使用不同原始来源、授权和任务身份，并在初始封装前绑定业务时钟；没有真实请求或延期的计划保持未触发。后轮只能读取严格较早的反馈，不回改同轮较早已经作出的合同决定。\n'
    if with_contractor_formation:
        if max_prior_owner_payment_delays is not None:
            readme+='\n已显式声明 --max-prior-owner-payment-delays：原承包商 A04 只按本企业、当前业主严格较早的真实延迟请求数要求独立允许的价格复核；不重复计算延迟事件，不由请求或 approved 状态推断现金、欠款或清偿。共享初始付款可靠度和财务来源保留原值，只有本次原引擎实际产生的延迟可触发偏好。\n'
        readme+='\n已显式启用 --with-contractor-formation：原 Contractor A04 与其他应用共用主体、时钟、授权、登记器及任务库，窗口延长到三个原生时点。两个已选投标及首项目已开启谈判是独立初始输入；实际请求才执行原容量/现金方法，同一结果返回原谈判有界决定。后轮可按 --max-prior-accept-terms 私有偏好消费较早本企业实际谈判姿态而要求修订，不推导新现金或详细资源承诺。业主授标仍走显式原宏观路由，不计 OWN-A10 微观覆盖；签署与标准资源占用仅由宏观执行。\n'
    if with_owner_award:
        readme=readme.replace('业主授标仍走显式原宏观路由，不计 OWN-A10 微观覆盖；',
            '业主授标由下述原 OWN-A10 显式配置接管；')
        readme+='\n已启用 --with-owner-award：原 OWN-A10 读取较早实际 Contractor A04 接受，核对事先审阅的完整协议与签署权限，按独立项目授权预算和管理资源形成业主决定。同一结果交原生提案/最终确认；所有条件需已满足，拒绝不冒充修订。--max-prior-owner-accepts 仅驱动本业主较早实际授标反馈后的私有修订偏好，不新增债务或资源占用。详细协议的签署/生效与原生汇总合同分开，正式状态仍由宏观维护。\n'
    if with_contract_supply_handoff:
        readme+='\n已显式启用 --with-contract-supply-handoff，窗口进一步延长到四时点：terms-first 必须先产生真实宏观签约事件，后续原 Supplier A01—A04 及 Contractor A05 才能消费原事件摘要并处理同一项目。初始状态没有该项目的合同、选供或资源占用；未来微观资料和独立预先买方商业同意不代表未来正式结果。两件板材、工厂单价 8 HKD、25% 加成、报价 20 HKD、备料资金计划 10 HKD 及采购限额 30 HKD 均在运行前独立声明，供应商现金仍为 1000 HKD。未启用共享微观投标时，旧审批项目在本窗口到达的投标判断显式保留原宏观路由，不计本轮微观投标覆盖；动员、交货、付款与完整生命周期继续待验。\n'
    if with_contractor_tender:
        readme+='''

已显式启用 --with-contractor-tender：原 OWN-A09 邀请桥和 Contractor A01/A02 宿主借用共享授权、登记器、任务库及同一写锁，
全部路由安装完才固定运行拓扑；同一结果通过原提案/最终决定返回，由宏观创建实际邀请和投标。
finance-owner-a / finance-qs 沿用原身份，两名显式配置的投标承包商使用独立专业资料和各自原生初始容量；
其他承包商只声明其已登记身份与“不邀请”权限，不据此推断其资质，不混用投标资料。
所有主体、职能、授权与时钟在来源封装前绑定。授标、签约、履约不由微观投标完成结果代替。
--with-tender-feedback 增加错峰的 shared-tender-followup 项目并延长到至少三个时点：
两项目都由原 OWN-A09 形成邀请；后轮原 A01/A02 消费较早本企业实际收标/拒投结果，按显式私有策略处理后续投标。
--tender-initial-screening-policies <JSON> 在初始封装前声明首项目各承包商原 A01 策略；未指定机构默认 participate_if_eligible。
--tender-decline-after-prior-declines N 需共享投标和后轮反馈，后轮以独立参与基准及实际较早本企业拒投次数产生新私有策略；不以提交代替拒投，不强制 A02 报价。
--allow-tender-saved-recovery --query-saved-tender-on-error 可独立授权原调用内查询保存结果，两项默认关闭。
--query-prior-tender-submissions 需同时启用 --with-tender-feedback，默认关闭；在后轮 A01 前核对本企业严格较早原请求的实际收标/拒绝事件。
--with-tender-clarification-response 需启用共享投标，同时开启原问题与独立 QS-A05 来源计划：
原问题实际发布后才执行发布权限判断，并通过原会话答复已授权的采购数量及计量规则。
设计、数量、文件及初始授权均为合成假设；答复不是修订包件、重新筛选或投标成功。
它补上通知未送达时的私有反馈读取，不伪造收件箱投递、不重提正式业务；查不到实际执行就保持未决并停止处理。
此共享投标输入覆盖首轮和可选后轮；延长到四时点还会到达其他项目邀请/投标与原选标字段兼容限制，
其余窗口仍需逐项配置合法来源和接线，不对缺资料或已接管失败切换为宏观规则回答。
'''
    if with_qs_evaluation:
        readme+='\n--with-qs-evaluation 需 --with-contractor-tender：原 QS-A06 与既有邀请/投标应用共用原组织授权、登记器、任务库及写锁；业主选标显式保留原生模块实现，不计微观 OWN-A08。窗口延长到四时点，整轮只执行一次 QS-A06；资格、文件、范围和评分仍为独立合成来源。此选项不证明授标、签约、履约或其他评标分支完成。\n'
        if with_qs_learning:
            readme+='\n--with-qs-learning 还需 --with-tender-feedback：时点 4 的原生 QS 月度请求触发原 QS-A12，核对本机构较早真实评标事件、原提案/最终决定及原微观结果，再记录私有反馈。正式月度操作仍由已声明的原生处理器决定；评分和中选不作为实际成本、利润、培训效果或能力提升。此功能已编码，业务结果待集中联调。\n'
            readme+='--allow-qs-learning-saved-recovery / --query-saved-qs-learning-on-error 显式启用原月度请求内的已保存结果查询；重核当前来源及授权，不重跑 QS-A12 或未知原生调用，不从失败时点重启。\n'
        if with_tender_feedback:
            readme=readme.replace('两项目都由原 OWN-A09 形成邀请；后轮原 A01/A02 消费较早本企业实际收标/拒投结果，按显式私有策略处理后续投标。',
                '首项目期初邀请及占用为显式初始假设，不计本轮 OWN-A09；时点 1 投标、时点 3 评标，后项目时点 3 经原 OWN-A09 邀请，时点 4 原 A01/A02 消费本企业严格较早的真实评标结果。提交次数阈值 999 不触发，独立评标次数阈值为 1；当前占用单独读取原宏观，未来日历仍独立声明。')
    if qs_exclude_contractor_id is not None:
        readme+='\n--qs-exclude-contractor-id declares independent initial failed qualification, score and buyer delegation for the named original tender bidder. Original QS-A06 exclusion uses the existing negative native final decision after a positive scoring proposal. With --with-qs-learning, later original QS-A12 consumes the actual exclusion. Published ranking does not prove delivery of a private notice or resource release.\n'
    if with_professional_opportunity:
        readme+='\n已启用 --with-professional-opportunity：三个专业方在实际委任请求内执行原 A01，已形成的 express_interest 及当前请求证据交原 A02 消费；共用原授权、登记器和任务库。表达兴趣不等于接受、报价发布、收费或正式委任；其他 A01 结果保留并停止本次接单评估。\n'
        if decline_after_no_interest:
            readme+='\n已启用 --decline-after-no-interest：仅原 A01 的 ignore/decline 通过明确私有策略进入原 A02 拒单评估，再由宏观原接口执行；其他未决结果保持未决。--without-professional-interest 声明三个专业方的初始兴趣权限为 false，不改变正式委任状态。\n'
    if with_professional_feedback:
        readme+='\n已启用 --with-professional-feedback：共享宿主复用原事件观察器及三专业 A12，分别记录实际接单接受/拒绝和原宏观团队中选结果；核对本机构原 A02、原提案/最终决定及真实收件。后轮原 A02 可读取自身已完成的中选记录，继续按既有次数策略接单；接受意向仍不等于中选。未中选计划保持未触发，已声明但缺失的历史反馈不自动重跑。记录不创建详细委任、收费、能力提升或训练。新增中选消费在独立真实业务中通过，共享组合留集中联调。\n'
    if incompatible_confirmation_roles or decline_after_unresolved_confirmation:
        readme+='\n--incompatible-confirmation-role 显式提供首轮详细委任不兼容来源，原 A03 自行处理；--decline-after-unresolved-confirmation 让后轮原 A02 消费本机构较早真实 A03 未决结果并拒绝新增工作。既有宏观委任保留，不送达或解决修订问题，不建立详细服务合同或资源账本。\n'
    if prior_appointment_limits is not None:
        readme+='\n--prior-appointment-limits 接收按角色配置的 JSON 对象，例如 {"Engineer":null} 关闭工程师的历史委任次数限制；正整数为拒绝新增工作的次数门槛，未声明角色保留默认策略。次数限制与 A03 未决结果策略独立，不改变专业能力或已有委任。\n'
    if intake_decline_banks:
        readme+='\n--decline-intake-bank 显式限制指定银行初始产品用途为 refinancing；原 BANK-A02 对当前 project_financing 自行判断 decline，不执行 A03/A04，原宏观记录融资拒绝。共享原 OWN-A05 只比较实际接受的报价；后轮本银行读取同借款人严格较早的真实受理拒绝，不据此改写产品许可、信用风险、现金或债务。\n'
    if bank_credit_condition_outcomes is not None:
        readme+='\n--bank-credit-condition-outcomes <JSON> 在封装前声明各银行模板条件的独立初始核验结果（satisfied/unsatisfied），保留原核验人、授权和证据。原 BANK-A03/A04 自行形成附条件报价，原 OWN-A05 按实际有效核验结论排除未满足条件的报价；未核验或依赖未决仍待补证，不改成满足。这不是运行中补件、条件治愈、正式资金安排或到账；共享组合待集中联调。\n'
    if with_owner_proposal:
        readme+='\n--with-owner-proposal 需同时启用 --with-owner-observation 与 --with-owner-opportunity：当前 A01 跟踪后，原 A16 实算有限草案与审阅预算/工作量，完整草案由原 A03 消费，非建设比较基线保留。原 no_proposal 不立即立项，部分草案保持待补；当前权利、规模支持域和审阅成本为明确合成初始假设，未执行 OWN-A02、专业报告、权利取得或支出。\n'
    if owner_study_question_code is not None:
        readme+='\n--owner-study-question-code 显式声明未解决的初始比较问题；当前原 A03 study_more 触发同宿主原 A02 有限研究授权。预计成本、预算、拟用管理量和计划时长为独立合成输入；原 internal_study/stop 均不立项，问题不标为解决，不创建正式研究任务、报告、外部委任、费用或资源预留。\n'
    if owner_study_service_offer is not None:
        readme+='\n--owner-study-service-offer 声明期初独立专业研究报价，source_declaration 必须为 independent_initial_standing_offer。原 OWN-A02 据原报价、限定预算及原现金保护独立形成 commission/stop；未知资料保持等待。报价为明确假设，不计实际专业 A02 或收件；委托决定仅为私有授权，不创建正式委任、研究、支出或报告。\n'
    if owner_study_professional_intake is not None:
        readme+='\n--owner-study-professional-intake 声明独立初始专业资质、收费、风险、工作量、资源日历及冲突来源。当前原 A03 问题触发原专业 A02 实际判断，再由业主 A02 消费实际接受/拒绝及原条款，原宏观仍裁定暂不立项。后轮重核双方原结果及当前授权；不计正式委任、外部消息回执、报告、支出或资源预留。\n'
    if owner_study_target_interventions:
        readme+='\n--owner-study-target-intervention 可重复声明 new_build/alter/extend/non_build；须同时声明研究问题。原 A03 的目标方案和原比较工作范围完整传入 A02，后续实际不立项反馈保留范围；目标不存在时停止，不扩大研究或生成正式任务/报告。\n'
    if with_bank_monthly_strategy:
        readme+='\n--with-bank-monthly-strategy 接管银行月度请求，复用原 BANK-A01；--bank-monthly-max-prior-reviews 显式声明本行较早实际月度操作数阈值。原策略只收紧后续原 A04 的独立报价上限；不改已有条款、现金或正式授信，不把原生能力变化当作资金。逐时点完整组合/容量为独立合成来源。\n'
    if allow_bank_monthly_saved_recovery:
        readme+='\n--allow-bank-monthly-saved-recovery 与 --query-saved-bank-monthly-on-error 均默认关闭；只将当前原银行月度调用的已保存原 BANK-A01 结果交回同一原调用。来源、授权、版本或输入变化及缺结果保持未决，不重跑处理器，不重启宏观或重提业务。共享装配不等于已验证共享故障续办。\n'
    if allow_bank_financing_saved_recovery or continue_unstarted_bank_financing_actions_on_error:
        readme+='\n--allow-bank-financing-saved-recovery / --query-saved-financing-on-error 只查询完整原银行融资结果（真实 A02 拒绝或完整报价链），返回仍在等待的同一宏观调用。--continue-unstarted-bank-financing-actions-on-error 另允许原注册且准备未开始的阶段执行一次。默认均关闭，接受受理但未报价、缺资料、已开始而缺结果不重跑；不修改来源、补齐条件、重启宏观或重提业务。共享故障组合待集中联调。\n'
    if bank_arrangement_capacity_limits is not None:
        readme+='\n--bank-arrangement-capacity-limits <JSON> supplies independent initial A05 HKD commitment-capacity views. Original A04 capacities and portfolio commitments are preserved; no native capacity change or cash effect is inferred.\n'
    if bank_arrangement_principal_limits is not None or with_unconfirmed_arrangement_feedback:
        readme+='\n--bank-arrangement-principal-limits <JSON> 声明各银行独立初始原 A05 形成权限本金上限；--with-unconfirmed-arrangement-feedback 显式改用同借款人严格较早的本行 A05 未确认复核次数作为原 A01 策略观察。缺失结果保持未决，确认不计未确认；旧安排/中选项目不更改，原确认安排读取器仍拒绝 decline/requote。只收紧后续新报价，不创建详细资金安排、现金或旧事项解决结果；共享组合待集中联调。\n'
    if supplier_first_decline_stage is not None or supplier_decline_after_prior_declines is not None:
        readme+='\n--supplier-first-decline-stage 显式提供首项目供应商的独立拒绝来源；--supplier-decline-after-prior-declines N 让原 A01 按本机构较早实际拒绝次数收紧私有接单策略。原承包商 A05 只读取当前实际接受的报价，不伪造被拒供应商的 A04、报价或中选。接受和中选不计拒绝，缺结果及未知不变成拒绝。新来源组合的共享业务留集中联调。\n'
    if with_supplier_product_substitution:
        readme+='\n--with-supplier-product-substitution 需 --with-government-and-supply：独立初始替代目录和逐版本偏差供原供应 A02/A03/A04 处理，原承包商 A05 独立核对需求级替代许可。--withhold-contractor-substitution-permission 显式撤去该初始许可，原 A05 保留 needs_information，宏观选供不执行。买方初始商业同意与产品使用许可分开，不代表设计批准、实际交付、详细订单或付款。\n'
    if continue_unstarted_supplier_actions_on_error:
        readme+='\n--continue-unstarted-supplier-actions-on-error 只在原生供应调用仍等待、原任务及快照已登记而决策准备确未开始时继续一次；重新核对来源、权限和执行版本，前序及来源生产不重做。开关默认关闭，独立于保存结果查询；已开始准备而缺结果保持未决，不重启宏观或进程。\n'
    if allow_supplier_saved_recovery:
        readme+='\n--allow-supplier-saved-recovery 与 --query-saved-supply-on-error 均默认关闭；核对全部原阶段后，只将当前原供应商调用已保存的完整接单/拒单决定交回同一调用。部分供应、澄清、缺结果或未开始阶段保持未决，不重跑处理器，不重启宏观，不创建详细订单或付款。\n'
    if max_prior_construction_suspensions is not None or with_suspension_project:
        readme+='\n--max-prior-construction-suspensions N 在原承包商 A04 中消费严格较早、本承包商合同及委任可核对的真实施工暂停，形成新条款价格复核偏好；默认关闭。--with-suspension-project / --suspension-project-design-quality 是明确合成初始工程及质量来源，不能当作本轮施工、检查或既成暂停，不归责其他主体、不变更资金、资源或旧债。\n'
    if with_professional_private_intake_judgment:
        readme+='\n--professional-private-intake-judgment-role may be repeated to select initial professional policies; omitted means all three roles. Other roles retain record-only feedback.\n'
        readme+='\n--with-professional-private-intake-judgment enables explicit simulation-only private intake recommendations after actual own selection. Original fixture-mode assessment saving/publication and A12 are reused; later A02 reads the completed own recommendation. Synthetic provenance remains synthetic. No formal strategy, capability, appointment, fee or capacity is applied. Existing count policies remain independent.\n'
    if government_actor_ids is not None:
        readme+='\n--government-actor-ids accepts the two original regulatory organizations as JSON keys, with distinct executing actors as values. Requires --with-government-and-supply. Identity is declared before sealing each source and checked by the shared original registry. Native organizations and direct applicant submission stay unchanged; this does not migrate old inputs, tasks, signatures or histories.\n'
    _write_launch_files(directory, assembly_hook='integration.financing_professional_native:configure_assembly',
        allow_native_project_generation=True, source_note='Explicit combined initial synthetic sources; business validation pending.',
        readme_override=readme, allow_native_initial_projects_with_generation=with_government_and_supply or with_payment_project or with_contractor_formation or with_contractor_tender)
    return {'status': 'combined_financing_professional_assembly_unverified', 'directory': str(directory), 'run_id': run_id}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--with-government-and-supply', action='store_true')
    parser.add_argument('--with-payment-positions', action='store_true')
    parser.add_argument('--payment-position-project-id',help='Bind private payment handling to one already declared original project')
    parser.add_argument('--lifecycle-input',type=Path)
    parser.add_argument('--with-final-account-discussion',action='store_true')
    parser.add_argument('--final-account-contractor-id')
    parser.add_argument('--with-final-account-learning',action='store_true')
    parser.add_argument('--with-final-account-response',action='store_true')
    parser.add_argument('--with-contractor-final-account-response',action='store_true')
    parser.add_argument('--with-government-feedback',action='store_true')
    parser.add_argument('--with-government-monthly-feedback',action='store_true')
    parser.add_argument('--allow-government-monthly-saved-recovery',action='store_true')
    parser.add_argument('--query-saved-monthly-on-error',action='store_true')
    parser.add_argument('--allow-government-saved-recovery',action='store_true')
    parser.add_argument('--allow-government-intake-saved-recovery',action='store_true')
    parser.add_argument('--query-saved-intake-on-error',action='store_true')
    parser.add_argument('--query-saved-approval-on-error',action='store_true')
    parser.add_argument('--with-owner-opportunity',action='store_true')
    parser.add_argument('--with-bank-monthly-strategy',action='store_true')
    parser.add_argument('--bank-actor-ids',type=Path)
    parser.add_argument('--government-actor-ids',type=Path)
    parser.add_argument('--bank-monthly-max-prior-reviews',type=int,default=1)
    parser.add_argument('--allow-bank-monthly-saved-recovery',action='store_true')
    parser.add_argument('--query-saved-bank-monthly-on-error',action='store_true')
    parser.add_argument('--allow-bank-financing-saved-recovery',action='store_true')
    parser.add_argument('--query-saved-financing-on-error',action='store_true')
    parser.add_argument('--continue-unstarted-bank-financing-actions-on-error',action='store_true')
    parser.add_argument('--bank-arrangement-principal-limits',type=Path)
    parser.add_argument('--bank-arrangement-capacity-limits',type=Path)
    parser.add_argument('--with-unconfirmed-arrangement-feedback',action='store_true')
    parser.add_argument('--allow-supplier-saved-recovery',action='store_true')
    parser.add_argument('--query-saved-supply-on-error',action='store_true')
    parser.add_argument('--allow-owner-opportunity-saved-recovery',action='store_true')
    parser.add_argument('--query-saved-opportunity-on-error',action='store_true')
    parser.add_argument('--with-owner-observation',action='store_true')
    parser.add_argument('--with-owner-proposal',action='store_true')
    parser.add_argument('--owner-proposal-review-cost',default='1000000')
    parser.add_argument('--owner-initial-investment-policy',choices=['evaluate','prepare_only','reject'])
    parser.add_argument('--owner-proposal-review-effort',default='0.5')
    parser.add_argument('--owner-observation-minimum-demand',default='0')
    parser.add_argument('--owner-study-question-code')
    parser.add_argument('--owner-study-target-intervention',action='append',default=[],
        choices=['new_build','alter','extend','non_build'])
    parser.add_argument('--owner-study-budget',default='1000000')
    parser.add_argument('--owner-study-estimated-cost',default='500000')
    parser.add_argument('--owner-study-resource-requirement',default='0.5')
    parser.add_argument('--owner-study-duration',type=int,default=1)
    parser.add_argument('--owner-study-unqualified',action='store_true')
    parser.add_argument('--owner-study-service-offer',type=Path,help='Independent standing offer JSON; requires --owner-study-question-code')
    parser.add_argument('--owner-study-professional-intake',type=Path,help='Independent original professional study service inputs JSON')
    parser.add_argument('--max-prior-opportunity-declines',type=int)
    parser.add_argument('--max-prior-initiations',type=int)
    parser.add_argument('--max-prior-payment-requests',type=int)
    parser.add_argument('--max-prior-final-accounts',type=int)
    parser.add_argument('--with-payment-project',action='store_true')
    parser.add_argument('--random-seed',type=int)
    parser.add_argument('--owner-payment-reliability',type=float)
    parser.add_argument('--progress-payment-ticks',type=int,nargs='+',default=[1])
    parser.add_argument('--with-contractor-formation',action='store_true')
    parser.add_argument('--with-owner-award',action='store_true')
    parser.add_argument('--max-prior-owner-accepts',type=int,default=1)
    parser.add_argument('--max-prior-accept-terms',type=int,default=1)
    parser.add_argument('--max-prior-owner-payment-delays',type=int)
    parser.add_argument('--max-prior-construction-suspensions',type=int)
    parser.add_argument('--with-suspension-project',action='store_true')
    parser.add_argument('--with-supplier-product-substitution',action='store_true')
    parser.add_argument('--supplier-first-decline-stage',choices=['screening','product','quote'])
    parser.add_argument('--supplier-decline-after-prior-declines',type=int)
    parser.add_argument('--withhold-contractor-substitution-permission',action='store_true')
    parser.add_argument('--continue-unstarted-supplier-actions-on-error',action='store_true')
    parser.add_argument('--continue-unstarted-government-approval-actions-on-error',action='store_true')
    parser.add_argument('--incompatible-confirmation-role',action='append',choices=['Architect','Engineer','QS'],default=[])
    parser.add_argument('--decline-after-unresolved-confirmation',action='store_true')
    parser.add_argument('--prior-appointment-limits',type=json.loads)
    parser.add_argument('--professional-project-object-types',type=json.loads)
    parser.add_argument('--suspension-project-design-quality',type=float,default=0.0)
    parser.add_argument('--with-contract-supply-handoff',action='store_true')
    parser.add_argument('--with-contractor-tender',action='store_true')
    parser.add_argument('--with-qs-evaluation',action='store_true')
    parser.add_argument('--with-qs-learning',action='store_true')
    parser.add_argument('--qs-exclude-contractor-id',
        help='Explicit initial failed qualification and buyer delegation for one original tender bidder')
    parser.add_argument('--allow-qs-learning-saved-recovery',action='store_true')
    parser.add_argument('--query-saved-qs-learning-on-error',action='store_true')
    parser.add_argument('--allow-tender-saved-recovery',action='store_true')
    parser.add_argument('--query-saved-tender-on-error',action='store_true')
    parser.add_argument('--continue-unstarted-tender-actions-on-error',action='store_true')
    parser.add_argument('--with-tender-clarification-request',action='store_true')
    parser.add_argument('--with-tender-clarification-response',action='store_true')
    parser.add_argument('--continue-tender-clarification',action='store_true')
    parser.add_argument('--tender-initial-screening-policies',type=Path)
    parser.add_argument('--tender-decline-after-prior-declines',type=int)
    parser.add_argument('--tender-decline-after-prior-final-accounts',type=int)
    parser.add_argument('--tender-decline-after-prior-payment-delays',type=int)
    parser.add_argument('--tender-contractor-ids',nargs=2,default=('tender-contractor-a','tender-contractor-b'))
    parser.add_argument('--allow-tender-followup-bids',action='store_true')
    parser.add_argument('--with-professional-opportunity',action='store_true')
    parser.add_argument('--with-professional-feedback',action='store_true')
    parser.add_argument('--with-professional-private-intake-judgment',action='store_true')
    parser.add_argument('--professional-private-intake-judgment-role',action='append',choices=['Architect','Engineer','QS'])
    parser.add_argument('--without-professional-interest',action='store_true')
    parser.add_argument('--decline-after-no-interest',action='store_true')
    parser.add_argument('--decline-intake-bank', action='append', default=[],
        choices=['finance-bank-a', 'finance-bank-b'])
    parser.add_argument('--bank-credit-condition-outcomes', type=Path)
    parser.add_argument('--with-tender-feedback',action='store_true')
    parser.add_argument('--query-prior-tender-submissions',action='store_true')
    args = parser.parse_args(argv)
    print(json.dumps(build_bundle(args.output, run_id=args.run_id,
        with_government_and_supply=args.with_government_and_supply,
        with_government_feedback=args.with_government_feedback,
        with_government_monthly_feedback=args.with_government_monthly_feedback,
        allow_government_monthly_saved_recovery=args.allow_government_monthly_saved_recovery,
        query_saved_monthly_on_error=args.query_saved_monthly_on_error,
        allow_government_saved_recovery=args.allow_government_saved_recovery,
        with_owner_opportunity=args.with_owner_opportunity,max_prior_initiations=args.max_prior_initiations,
        owner_initial_investment_policy=args.owner_initial_investment_policy,
        with_bank_monthly_strategy=args.with_bank_monthly_strategy,bank_monthly_max_prior_reviews=args.bank_monthly_max_prior_reviews,
        bank_actor_ids=json.loads(args.bank_actor_ids.read_text(encoding='utf-8-sig'))
            if args.bank_actor_ids is not None else None,
        government_actor_ids=json.loads(args.government_actor_ids.read_text(encoding='utf-8-sig'))
            if args.government_actor_ids is not None else None,
        allow_bank_monthly_saved_recovery=args.allow_bank_monthly_saved_recovery,
        query_saved_bank_monthly_on_error=args.query_saved_bank_monthly_on_error,
        allow_bank_financing_saved_recovery=args.allow_bank_financing_saved_recovery,
        query_saved_financing_on_error=args.query_saved_financing_on_error,
        continue_unstarted_bank_financing_actions_on_error=args.continue_unstarted_bank_financing_actions_on_error,
        bank_arrangement_principal_limits=json.loads(args.bank_arrangement_principal_limits.read_text(encoding='utf-8-sig'))
            if args.bank_arrangement_principal_limits is not None else None,
        bank_arrangement_capacity_limits=json.loads(args.bank_arrangement_capacity_limits.read_text(encoding='utf-8-sig'))
            if args.bank_arrangement_capacity_limits is not None else None,
        with_unconfirmed_arrangement_feedback=args.with_unconfirmed_arrangement_feedback,
        allow_supplier_saved_recovery=args.allow_supplier_saved_recovery,
        query_saved_supply_on_error=args.query_saved_supply_on_error,
        allow_owner_opportunity_saved_recovery=args.allow_owner_opportunity_saved_recovery,
        query_saved_opportunity_on_error=args.query_saved_opportunity_on_error,
        with_owner_observation=args.with_owner_observation,
        with_owner_proposal=args.with_owner_proposal,owner_proposal_review_cost=args.owner_proposal_review_cost,
        owner_proposal_review_effort=args.owner_proposal_review_effort,
        owner_study_question_code=args.owner_study_question_code,owner_study_budget=args.owner_study_budget,
        owner_study_target_interventions=args.owner_study_target_intervention,
        owner_study_estimated_cost=args.owner_study_estimated_cost,owner_study_resource_requirement=args.owner_study_resource_requirement,
        owner_study_duration=args.owner_study_duration,owner_study_qualified=not args.owner_study_unqualified,
        owner_study_service_offer=json.loads(args.owner_study_service_offer.read_text(encoding='utf-8-sig')) if args.owner_study_service_offer else None,
        owner_study_professional_intake=json.loads(args.owner_study_professional_intake.read_text(encoding='utf-8-sig')) if args.owner_study_professional_intake else None,
        owner_observation_minimum_demand=args.owner_observation_minimum_demand,
        max_prior_opportunity_declines=args.max_prior_opportunity_declines,
        max_prior_payment_requests=args.max_prior_payment_requests,with_payment_project=args.with_payment_project,
        random_seed=args.random_seed,owner_payment_reliability=args.owner_payment_reliability,
        progress_payment_ticks=args.progress_payment_ticks,
        with_payment_positions=args.with_payment_positions,
        payment_position_project_id=args.payment_position_project_id,
        max_prior_final_accounts=args.max_prior_final_accounts,
        with_contractor_formation=args.with_contractor_formation,max_prior_accept_terms=args.max_prior_accept_terms,
        with_contract_supply_handoff=args.with_contract_supply_handoff,
        with_contractor_tender=args.with_contractor_tender,
        with_qs_evaluation=args.with_qs_evaluation,
        qs_exclude_contractor_id=args.qs_exclude_contractor_id,
        with_qs_learning=args.with_qs_learning,
        allow_qs_learning_saved_recovery=args.allow_qs_learning_saved_recovery,
        query_saved_qs_learning_on_error=args.query_saved_qs_learning_on_error,
        lifecycle_input=args.lifecycle_input,
        with_final_account_discussion=args.with_final_account_discussion,
        with_final_account_response=args.with_final_account_response,
        with_final_account_learning=args.with_final_account_learning,
        with_contractor_final_account_response=args.with_contractor_final_account_response,
        allow_tender_saved_recovery=args.allow_tender_saved_recovery,
        query_saved_tender_on_error=args.query_saved_tender_on_error,
        continue_unstarted_tender_actions_on_error=args.continue_unstarted_tender_actions_on_error,
        with_tender_clarification_request=args.with_tender_clarification_request,
        with_tender_clarification_response=args.with_tender_clarification_response,
        continue_tender_clarification=args.continue_tender_clarification,
        tender_initial_screening_policies=json.loads(args.tender_initial_screening_policies.read_text(encoding='utf-8-sig'))
            if args.tender_initial_screening_policies is not None else None,
        tender_decline_after_prior_declines=args.tender_decline_after_prior_declines,
        tender_decline_after_prior_final_accounts=args.tender_decline_after_prior_final_accounts,
        tender_decline_after_prior_payment_delays=args.tender_decline_after_prior_payment_delays,
        tender_contractor_ids=args.tender_contractor_ids,
        allow_tender_followup_bids=args.allow_tender_followup_bids,
        final_account_contractor_id=args.final_account_contractor_id,
        with_professional_opportunity=args.with_professional_opportunity,
        with_professional_feedback=args.with_professional_feedback,
        with_professional_private_intake_judgment=args.with_professional_private_intake_judgment,
        professional_private_intake_judgment_roles=args.professional_private_intake_judgment_role,
        professional_opportunity_interest_permitted=not args.without_professional_interest,
        decline_after_no_interest=args.decline_after_no_interest,
        intake_decline_banks=args.decline_intake_bank,
        bank_credit_condition_outcomes=json.loads(args.bank_credit_condition_outcomes.read_text(encoding='utf-8-sig'))
            if args.bank_credit_condition_outcomes is not None else None,
        with_tender_feedback=args.with_tender_feedback,
        query_prior_tender_submissions=args.query_prior_tender_submissions,
        with_owner_award=args.with_owner_award,max_prior_owner_accepts=args.max_prior_owner_accepts,
        query_saved_approval_on_error=args.query_saved_approval_on_error,
        continue_unstarted_government_approval_actions_on_error=args.continue_unstarted_government_approval_actions_on_error,
        allow_government_intake_saved_recovery=args.allow_government_intake_saved_recovery,
        query_saved_intake_on_error=args.query_saved_intake_on_error,
        max_prior_owner_payment_delays=args.max_prior_owner_payment_delays,
        max_prior_construction_suspensions=args.max_prior_construction_suspensions,
        with_suspension_project=args.with_suspension_project,
        suspension_project_design_quality=args.suspension_project_design_quality,
        with_supplier_product_substitution=args.with_supplier_product_substitution,
        supplier_first_decline_stage=args.supplier_first_decline_stage,
        supplier_decline_after_prior_declines=args.supplier_decline_after_prior_declines,
        contractor_substitution_permitted=not args.withhold_contractor_substitution_permission,
        continue_unstarted_supplier_actions_on_error=args.continue_unstarted_supplier_actions_on_error,
        incompatible_confirmation_roles=args.incompatible_confirmation_role,
        decline_after_unresolved_confirmation=args.decline_after_unresolved_confirmation,
        prior_appointment_limits=args.prior_appointment_limits,
        professional_project_object_types=args.professional_project_object_types), ensure_ascii=True))


if __name__ == '__main__':
    main()
