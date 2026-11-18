"""Explicit initial regulatory and supply cases for the shared native host.

This produces inputs before engine construction. It never writes runtime
projects, approvals, contracts, resources or receipts.
"""
from copy import deepcopy
import json

from integration.contractor_tender_development import _write
from integration.government_intake_development import build_bundle as government_bundle
from integration.supplier_order_native_development import build_bundle as supplier_bundle


def extend_sources(directory, *, run_id, components, request, routes, with_government_feedback=False,
        allow_government_saved_recovery=False,write_provenance=True,with_contract_supply_handoff=False,
        query_saved_approval_on_error=False,with_government_monthly_feedback=False,monthly_feedback_ticks=None,
        allow_government_monthly_saved_recovery=False,query_saved_monthly_on_error=False,
        allow_government_intake_saved_recovery=False,query_saved_intake_on_error=False,
        with_supplier_product_substitution=False,contractor_substitution_permitted=True,
        supplier_first_decline_stage=None,supplier_decline_after_prior_declines=None,
        government_actor_ids=None):
    from integration.financing_professional_development import _source_files

    read = lambda path: json.loads(path.read_bytes())
    government_dir, supplier_dir = directory / 'sources/government', directory / 'sources/supplier'
    government_bindings={'owner_id':'finance-owner-a',
        'agency_ids':('finance-government','finance-government-b'),
        'owner_function_id':'finance-owner-a-regulatory-function','clock_id':run_id+'-monthly-clock'}
    supplier_bindings={'owner_id':'finance-owner-a','contractor_id':'finance-contractor',
        'supplier_ids':('finance-supplier','finance-supplier-b'),
        'owner_function_id':'finance-owner-a-supply-function','clock_id':run_id+'-monthly-clock'}
    # Bind parties before documents, agreements, method inputs and drafts are
    # hashed. Renaming a sealed template cannot preserve its old digests.
    government_bundle(government_dir, run_id=run_id, with_approval=True,with_feedback=with_government_feedback,
        with_monthly_feedback=with_government_monthly_feedback,monthly_feedback_ticks=monthly_feedback_ticks,
        allow_monthly_saved_recovery=allow_government_monthly_saved_recovery,
        query_saved_monthly_on_error=query_saved_monthly_on_error,
        allow_saved_recovery=allow_government_saved_recovery,
        allow_intake_saved_recovery=allow_government_intake_saved_recovery,
        query_saved_intake_on_error=query_saved_intake_on_error,
        query_saved_approval_on_error=query_saved_approval_on_error,
        organization_actor_ids=government_actor_ids,**government_bindings)
    supplier_bundle(supplier_dir, run_id=run_id, with_quote=True, with_product=True,
        first_decline_stage=supplier_first_decline_stage,
        decline_after_prior_declines=supplier_decline_after_prior_declines,
        with_product_substitution=with_supplier_product_substitution,
        contractor_substitution_permitted=contractor_substitution_permitted,
        with_screening=True, with_contractor=True,additional_project_windows=([
            {'project_id':'terms-first','tick':4,'delivery_start':5,'delivery_end':6,
                'business_money_scale':'0.1','procurement_limit':'30','require_native_award':True}]
            if with_contract_supply_handoff else []),**supplier_bindings)
    declarations = [
        ('government', government_dir, government_bindings,
            [(None, 'government-intake-input.json'), ('approval', 'government-approval-input.json')]
            +([('monthly','government-monthly-input.json')] if with_government_monthly_feedback else [])),
        ('supplier', supplier_dir, supplier_bindings,
            [(None, 'supplier-order-input.json'), ('contractor', 'contractor-supply-input.json')]),
    ]
    agents = {a['agent_id']: a for a in request['agents']}
    project_ids = {p['project_id'] for p in request['initial_projects']}
    provenance = []
    for key, source_dir, bindings, files in declarations:
        source_settings = read(source_dir / 'assembly-host.json')['settings']
        components[key] = _source_files(directory, settings=source_settings, substitutions={}, files=files)
        original = read(source_dir / 'macro-request.json')
        native = deepcopy(original)
        for agent in native['agents']:
            existing = agents.get(agent['agent_id'])
            if existing is None:
                agents[agent['agent_id']] = deepcopy(agent)
            elif existing['role'] != agent['role'] or existing['region'] != agent['region']:
                raise ValueError('Initial shared case changes an existing native role or region')
            if key == 'supplier' and agent['role'] == 'Contractor':
                # Copy an explicit initial value from the same input that
                # declares its existing engagement; never infer runtime load.
                agents[agent['agent_id']]['occupied_resource'] = agent['occupied_resource']
        for project in native['initial_projects']:
            if project['project_id'] in project_ids:
                raise ValueError('Independent initial shared cases repeat a project identity')
            project_ids.add(project['project_id'])
            request['initial_projects'].append(deepcopy(project))
            provenance.append({'project_id': project['project_id'], 'owner_id': project['owner_id'],
                'current_stage': project['current_stage'], 'source': str(source_dir / 'macro-request.json'),
                'initial_identity_bindings':bindings,
                'identity_binding_phase':'before content, method, agreement and draft digests are formed',
                'status': 'explicit_initial_assumption',
                'boundary': 'Not evidence of micro investment, design, tender award, signature or earlier execution.'})
    request['agents'] = list(agents.values())
    # The original generated-project counter starts at zero independently of
    # initial project names. Keep two PGEN opportunities, one per native tick.
    request.update(target_project_count=len(request['initial_projects']) + 2,
        max_active_projects=len(request['initial_projects']) + 2)
    routes.update(micro_government_intake_scope=True, micro_government_approval_scope=True,
        micro_government_monthly_feedback_scope=with_government_monthly_feedback,
        query_saved_approval_on_error=query_saved_approval_on_error,
        query_saved_intake_on_error=query_saved_intake_on_error,
        query_saved_monthly_on_error=query_saved_monthly_on_error,
        native_government_approval_transport=False, micro_supplier_order_scope=True,
        micro_contractor_supply_scope=True)
    if with_government_monthly_feedback:
        routes['native_proposals']=[r for r in routes['native_proposals']
            if (r['role'],r['operation'])!=('Government','decide_monthly_operation')]
        routes['native_decisions']=[r for r in routes['native_decisions']
            if (r['role'],r['decision_type'])!=('Government','monthly_enterprise_operation')]
    # Later preparation in an initial approval case retains its explicitly
    # declared original native invitation behavior; this is not OWN-A09 coverage.
    routes['native_proposals'].append({'role': 'Owner', 'operation': 'select_tender_invitees'})
    routes['native_decisions'].append({'role': 'Owner', 'decision_type': 'owner_tender_shortlist'})
    document={'schema_version': 'shared-role-initial-cases.v1', 'run_id': run_id,
        'initial_projects': provenance,
        'planned_generated_project_ids': ['PGEN0001', 'PGEN0002'],
        'limits': 'Initial cases exercise independent existing native windows in one runtime. They do not '
            'prove that the generated PGEN projects completed design, procurement, finance execution or closeout.'}
    if with_contract_supply_handoff:
        document['contract_supply_handoff']={'project_id':'terms-first','source_tick':4,
            'required_origin':'actual strictly earlier native contract_awarded, not initial contract declarations',
            'commercial_source':str(supplier_dir/'initial-supply-windows.json'),
            'independent_initial_buyer_terms':'Private initial commercial consent, not a future Contractor selection or a formal SupplyOrder.',
            'amounts':'Two panels, unit factory cost 8 HKD, 25% assumed markup, independent offer price 20 HKD, working-capital plan 10 HKD and procurement ceiling 30 HKD. Initial Supplier cash remains 1000 HKD.',
            'boundary':'No actual delivery, stock reservation, cash debit or detailed effective supply agreement is inferred.'}
    if write_provenance:_write(directory,'input-provenance.json',document)
    return document
