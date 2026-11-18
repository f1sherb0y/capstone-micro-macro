"""Bounded 3I source gaps and original monthly subaction inventory, not routing."""
import ast
import importlib
from integration.contractor_construction_source_review import _source
from integration.verify_tender_closed_loop import ROOT,macro_hashes,require


GATES={
    'detailed_final_account':{'actions':['QS-A09','CONTRACTOR-A11'],
        'handlers':['integration.qs_final_account_actions:QSFinalAccountActionAssembler','integration.contractor_closeout_actions:ContractorCloseoutActionAssembler'],
        'missing':['complete_actual_work_variation_claim_certificate_payment_and_offset_histories','independent_final_account_authority_and_signed_component_disposition','actual_formal_settlement_issuer_and_original_query'],
        'private_branch':'Original positions/questions and actual room communication run, not formal agreement or detailed cleared components'},
    'handover_acceptance':{'actions':['OWN-A12','CONTRACTOR-A11'],
        'handlers':['integration.owner_closeout_actions:OwnerCloseoutActionAssembler','integration.contractor_handover_reader:ContractorHandoverReader'],
        'missing':['actual_original_handover_and_as_built_deliverables','independent_work_specific_verification_permits_and_complete_defects','authentic_acceptance_use_rights_and_remaining_duties_query']},
    'owner_continuing_operations':{'actions':['OWN-A13','OWN-A14','OWN-A15'],
        'handlers':['integration.owner_continuation_actions:OwnerContinuationActionAssembler','integration.owner_asset_actions:OwnerAssetActionAssembler','integration.owner_operating_actions:OwnerOperatingActionAssembler'],
        'missing':['actual_accepted_asset_and_operating_rights','complete_current_obligations_operating_cash_demand_and_maintenance_sources','actual_operation_disposal_issuer_and_query']},
    'commercial_continuing_obligations':{'actions':['CONTRACTOR-A12','SUPPLIER-A12'],
        'handlers':['integration.commercial_actions:CommercialActionAssembler'],
        'missing':['complete_current_goods_rights_obligations_and_original_execution_history','actual_unresolved_warranty_remedy_payment_and_release_evidence','authorized_current_commercial_profile_and_original_outcome_query']},
    'professional_fees_and_transition':{'actions':['ARCHITECT-A10','ARCHITECT-A11','ENGINEER-A10','ENGINEER-A11','QS-A10','QS-A11'],
        'handlers':['integration.architect_billing_actions:ArchitectBillingActionAssembler','integration.architect_transition_actions:ArchitectTransitionActionAssembler',
            'integration.engineer_billing_actions:EngineerBillingActionAssembler','integration.engineer_transition_actions:EngineerTransitionActionAssembler',
            'integration.qs_billing_actions:QSBillingActionAssembler','integration.qs_transition_actions:QSTransitionActionAssembler'],
        'missing':['actual_registered_deliverables_acceptance_fee_and_receivable_histories','independent_release_handover_access_and_unresolved_duty_evidence','authentic_billing_receipt_or_transition_issuer_and_query']},
    'bank_debt_monitoring_resolution_closeout':{'actions':['BANK-A08','BANK-A09','BANK-A10','BANK-A11'],
        'handlers':['integration.bank_monitoring_actions:BankMonitoringActionAssembler','integration.bank_debt_actions:BankDebtActionAssembler',
            'integration.bank_resolution_actions:BankResolutionActionAssembler','integration.bank_closeout_actions:BankCloseoutActionAssembler'],
        'missing':['actual_registered_facility_and_complete_principal_interest_debt_and_execution_history','independent_current_borrower_collateral_risk_and_received_repayment_evidence','authentic_debt_resolution_closeout_and_remaining_obligation_query']},
}

MONTHLY_NEEDS={
    'Owner':['current_own_cash_debt_commitments_and_investment_scope','authorized_market_study_or_financing_capacity_basis'],
    'Contractor':['current_own_qualifications_capacity_costs_and_commitments','authorized_tender_region_partner_or_relationship_targets'],
    'Supplier':['actual_stock_orders_capacity_and_commercial_obligations','authorized_prices_reliability_or_opportunity_basis'],
    'Architect':['current_own_qualification_service_capacity_and_relationship_scope','authorized_market_learning_or_reputation_basis'],
    'Engineer':['current_own_qualification_service_capacity_and_task_scope','authorized_professional_qualification_learning_or_market_basis'],
    'QS':['current_own_market_workload_and_cost_dataset_scope','authorized_cost_learning_publication_or_appointment_basis'],
    'Bank':['actual_current_borrower_loan_debt_execution_and_risk_history','authorized_independent_monitoring_scope_and_current_judgment'],
    'Government':['actual_current_regulatory_task_scope_and_received_evidence','authorized_policy_compliance_or_guidance_basis_and_consumer'],
}


def source_boundaries():
    macro=ROOT/macro_hashes()['root']/'gba_construction_sim/backend'
    original=_source(macro,'simulation/project_lifecycle_engine.py','ProjectLifecycleEngine._handle_final_account')
    original['path']=(macro/original['path']).relative_to(ROOT).as_posix()
    stages={}
    for name,gate in GATES.items():
        handlers=[]
        for spec in gate['handlers']:
            module,symbol=spec.split(':');getattr(importlib.import_module(module),symbol)
            handlers.append(_source(ROOT,module.replace('.','/')+'.py',symbol))
        stages[name]={**gate,'status':'blocked_missing_verified_native_sources','existing_handlers':handlers,'formal_effects_verified':False}
    return {'batch':'3I','native_producer':original,'existing_feedback_components':[
        _source(ROOT,'integration/bindings/gba_v1_final_account_positions.py','read_final_account_positions'),
        _source(ROOT,'integration/bindings/gba_v1_final_accounts.py','read_own_final_accounts'),
        _source(ROOT,'integration/owner_opportunity_native_sources.py','prepare_opportunity_sources')],
        'stages':stages,'boundary':'Actual communication and aggregate project closure do not prove signed component agreement, independent handover/use rights, cash, debt clearance, fee receipt or released continuing obligations. Source gaps are scoped to bindings in this composition, not a claim of global macro API absence.',
        'next_step':'Bind equivalent original detailed producer/issuer/query and exact current authorized versions to existing typed handlers; preserve unknown duties. Do not fill complete histories with zero/empty values or fabricate core_event_id.'}


def monthly_inventory(events=(),monthly_proofs=(),*,agent_roles=None):
    macro=ROOT/macro_hashes()['root']/'gba_construction_sim/backend/agents'
    proof_keys={(p['role'],p['operation']) for p in monthly_proofs}
    require(not events or agent_roles is not None,'Actual monthly inventory requires original sender-role identities')
    supported={('Bank','review_credit_pipeline'):'integration.bank_monthly_native:BankMonthlyApplication',
        ('Bank','adjust_credit_terms'):'integration.bank_monthly_native:BankMonthlyApplication',
        ('Government','review_policy_feedback'):'integration.government_monthly_native:GovernmentMonthlyApplication'}
    entries=[]
    for role in ('Owner','Bank','Architect','Engineer','QS','Contractor','Supplier','Government'):
        relative=role.lower()+'_agent.py';p=macro/relative;tree=ast.parse(p.read_text(encoding='utf-8-sig'))
        classes=[c for c in tree.body if isinstance(c,ast.ClassDef)]
        methods=[m for c in classes for m in c.body if isinstance(m,ast.FunctionDef) and m.name=='decide_monthly_operation']
        require(len(methods)==1,'Original monthly method is not unique');method=methods[0]
        names=sorted({n.elts[0].value for n in ast.walk(method) if isinstance(n,ast.Tuple) and len(n.elts)==3
            and isinstance(n.elts[0],ast.Constant) and isinstance(n.elts[0].value,str)})
        require(bool(names),'Original monthly business names missing')
        source=_source(macro,relative,classes[0].name+'.decide_monthly_operation');source['path']=p.relative_to(ROOT).as_posix()
        for operation in names:
            key=(role,operation);executed=key in proof_keys
            entries.append({'role':role,'operation':operation,'native_source':source,
                'macro_input':'Original current macro_environment plus own normalized profile/free resource. These do not supply all private detailed decision facts.',
                'status':'executed_current_micro_judgment_and_feedback' if executed else
                    'configured_micro_judgment_not_observed' if key in supported else 'blocked_unwired_micro_judgment',
                'micro_handler':supported.get(key),'existing_role_host':'integration/'+role.lower()+'_role_contract_host.py',
                'micro_processing':'Original BANK-A01 private strategy or GOV-A12 own feedback' if key in supported else
                    'Appropriate original scoped role processor is not bound to this monthly subaction; other operation contracts do not count as this decision.',
                'return_to_macro':'Original monthly proposal/final interface and original agent_operation' if key in supported else
                    'Blocked pending a valid scoped micro result and equivalent original bounded monthly choice.',
                'feedback_consumer':'Strictly earlier own original monthly history used in later original monthly action' if key in supported else
                    'Missing authenticated micro-origin mapping and current own detailed history for this monthly decision.',
                'missing':[] if key in supported else MONTHLY_NEEDS[role],
                'actual_event_ids':[p['event_id'] for p in monthly_proofs if (p['role'],p['operation'])==key],
                'native_only_events':[e['event_id'] for e in events if e['event_type']=='agent_operation'
                    and agent_roles.get(e['agent_id'])==role
                    and e['data'].get('operation')==operation and not any(p['event_id']==e['event_id'] for p in monthly_proofs)],
                'counts_as_micro_coverage':executed})
    require(len(entries)==32,'Original monthly subaction inventory changed; review source before claiming coverage')
    return {'schema_version':'gba-v1-monthly-business-wiring.v1','batch':'3I','artifact_kind':'inventory_not_dispatcher',
        'original_role_subactions':len(entries),'executed_subactions':sum(e['counts_as_micro_coverage'] for e in entries),
        'blocked_subactions':sum(e['status']=='blocked_unwired_micro_judgment' for e in entries),'entries':entries,
        'generic_scheduler_outcomes':['fully_allocated','maintain_operations'],
        'boundary':'Role-specific original monthly business names extracted from frozen source AST, including f-string descriptions. Generic scheduler guards are not new role subactions. Native-only events or candidate mappings are not micro coverage; 106/438 branch completeness is not claimed.'}
