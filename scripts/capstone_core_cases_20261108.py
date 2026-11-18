"""Task adapters for the zero-provider Capstone validation batch.

Reuses fixed synthetic business facts and actual authorized runners. Expected
business properties are declared separately in the batch manifest, not learnt
from the result. No macro state or paid model client is instantiated here.
"""
from __future__ import annotations
from copy import deepcopy
from importlib import import_module
import json
import hashlib
from pathlib import Path
import tempfile


ADAPTERS = {
    'Owner': ('tests.test_owner_investment', 'facts', 'build_run'),
    'Bank': ('tests.test_bank_credit', 'facts', 'build_credit_run'),
    'Architect': ('tests.test_architect_intake', 'runtime_data', 'build_intake_run'),
    'Engineer': ('tests.test_engineer_appointment', 'facts', None),
    'QS': ('tests.test_qs_cost', 'facts', None),
    'Supplier': ('tests.test_supplier_quote', 'facts', 'build_run'),
}


def view(data, kind, identity=None):
    return next(r['value'] for r in data['objects'] if r['ref']['kind'] == kind
                and (identity is None or r['ref']['id'] == identity))


def unknown():
    return {'state': 'unknown', 'reason_code': 'capstone_fixture_missing', 'missing_refs': []}


def prepare_task(role, condition):
    if role in {'Contractor', 'Government'}:
        return prepare_assembled(role, condition)
    if role not in ADAPTERS:
        return None
    module_name, factory, builder = ADAPTERS[role]
    module = import_module(module_name)
    data = getattr(module, factory)()
    if condition == 'missing_evidence':
        if role == 'Owner':
            view(data, 'ProjectRegistrationProfile')['policy'] = unknown()
        elif role == 'Bank':
            view(data, 'RiskObservation')['interval'] = unknown()
        elif role == 'Architect':
            view(data, 'Capability')['service_codes'] = unknown()
        elif role == 'Engineer':
            view(data, 'OrganizationRelations')['related_organization_ids'] = unknown()
        elif role == 'QS':
            view(data, 'Task')['delivery_mode'] = 'request_inputs'
            view(data, 'Price')['unit_rate'] = unknown()
            module.record_calculation(data)
        elif role == 'Supplier':
            view(data, 'CostBasis')['unit_cost'] = unknown()
    original = deepcopy(data)
    if role in {'Engineer', 'QS'}:
        base = import_module('tests.test_architect_appointment')
        schema_module = import_module('src.actions.contracts.' + ('engineer_appointment_objects' if role == 'Engineer' else 'qs_cost_objects'))
        schemas = getattr(schema_module, 'engineer_appointment_schemas' if role == 'Engineer' else 'qs_cost_schemas')()
        runner, context, action_input = base.build_run(data, action_id='ENGINEER-A03' if role == 'Engineer' else 'QS-A04',
                                                       role=role, schemas=schemas)
        objects = data['objects']
    else:
        instance = getattr(module, builder)(data)
        runner, context, action_input, objects = instance.runner, instance.context, instance.input, instance.objects
    if condition == 'out_of_authority':
        context = context.model_copy(update={'actor_id': 'capstone-ungranted-actor'})
    return {'runner': runner, 'context': context, 'input': action_input, 'objects': objects,
            'source_fixture': original, 'adapter': module_name + ':' + (builder or 'existing appointment builder'),
            'factory_source_unchanged': data == original}


EXPECTATIONS = {
    'Owner': {'normal': ('completed', 'invest'), 'missing': ('needs_information', None)},
    'Bank': {'normal': ('completed', 'recommend'), 'missing': ('needs_information', None)},
    'Architect': {'normal': ('completed', 'accept'), 'missing': ('needs_information', None)},
    'Engineer': {'normal': ('completed', 'confirm'), 'missing': ('needs_information', None)},
    'QS': {'normal': ('completed', 'estimate'), 'missing': ('completed', 'request_price')},
    'Supplier': {'normal': ('completed', 'quote'), 'missing': ('needs_information', None)},
    'Contractor': {'normal': ('completed', 'submit_bid'), 'missing': ('needs_information', None)},
    'Government': {'normal': ('completed', 'assess'), 'missing': ('needs_information', None)},
}


def prepare_assembled(role, condition):
    """Existing source assemblers; fixture preparation never runs a macro engine."""
    from src.actions.contracts.common import ActionContext
    from src.actions.registry import ActionRegistry
    from src.actions.processors import register_representative_processors
    from src.organization.registry import OrganizationRegistry, OrganizationSnapshot
    root = Path(__file__).resolve().parents[1]
    registry = register_representative_processors(ActionRegistry())
    if role == 'Contractor':
        from integration.contractor_bid_actions import ContractorBidActionAssembler
        source = json.loads((root/'integration/examples/role_contract_contractor_bid_host.json').read_bytes())['settings']['source_settings']
        invocation = json.loads((root/'integration/examples/role_contract_contractor_bid_invocation.json').read_bytes())
        snapshot = source['organization_snapshot']
        projection = deepcopy(source['source_projection'])
        context = ActionContext.model_validate(invocation['context'])
        action_input = invocation['action_input']
        if condition == 'missing_evidence':
            next(r['value'] for r in projection['objects'] if r['ref']['kind']=='CostBasis')['unit_rate'] = unknown()
        assembler_type = ContractorBidActionAssembler
        arguments = {k: action_input[k] for k in ('pricing_profile_ref','capacity_ref','cost_refs','allowed_method_refs')}
        adapter = 'integration.contractor_bid_actions:ContractorBidActionAssembler'
    else:
        from integration.government_intake_development import build_bundle
        from integration.government_review_actions import GovernmentReviewActionAssembler
        with tempfile.TemporaryDirectory(prefix='capstone-gov-fixture-') as temp:
            directory=Path(temp)/'input'
            bundle=build_bundle(directory,run_id='capstone-gov-offline',sources_only=True,with_approval=True)
            plan=json.loads((directory/'government-approval-input.json').read_bytes())['plans'][0]
            snapshot=bundle['settings']['authority']['organization_snapshot']
        context=ActionContext.model_validate(plan['review_context'])
        # The generator describes native inputs; this task is an explicitly
        # derived offline fixture and must use the assembler's matching mode.
        context=context.model_copy(update={'execution_mode':'offline_fixture'})
        action_input=deepcopy(plan['review_input'])
        objects=deepcopy(plan['review_objects'])
        # Native request evidence is intentionally absent in a sources-only
        # bundle. For this derived test, label those placeholders as ASSUMED
        # synthetic context with a digest of the fixture, never as observed
        # native events. No receipt, approval or macro state is manufactured.
        fixture_digest=hashlib.sha256(json.dumps(plan['review_input'],sort_keys=True).encode()).hexdigest()
        for row in objects:
            if row['ref']['kind']=='Evidence' and row['value'].get('content_hash') is None:
                row['value'].update(source_kind='synthetic',basis_kind='assumed',
                    locator='capstone-offline-fixture:unexecuted-native-context-placeholder',content_hash=fixture_digest)
        if condition == 'missing_evidence':
            action_input['verified_evidence_refs']=[]
            next(r['value'] for r in objects if r['ref']['kind']=='Task')['verified_evidence_refs']=[]
        projection={'run_id':context.run_id,'macro_version':'synthetic-government-review.v1','state_version':'fixture-1',
                    'read_token':context.read_token,'business_time':context.business_time.model_dump(mode='json'),
                    'organization_id':plan['organization_id'],'objects':objects}
        assembler_type=GovernmentReviewActionAssembler
        arguments=action_input
        adapter='integration.government_review_actions:GovernmentReviewActionAssembler; existing sources-only scenario generator'
    snapshot=OrganizationSnapshot.model_validate(snapshot)
    organizations=OrganizationRegistry(snapshot.run_id)
    for organization in snapshot.organizations:
        organizations.register(organization)
    for grant in snapshot.authorizations:
        organizations.authorize(grant)
    for ref in snapshot.inactive_authorization_refs:
        organizations.revoke(ref)
    class Source:
        def project(self, **kwargs):
            return deepcopy(projection)
    assembler=assembler_type(registry=registry,organizations=organizations,provider=Source(),
                             macro_version=projection['macro_version'],source_mode='fixture',
                             policy_version='capstone-declared-fixture-policy',model_version='offline-rule')
    prepared=assembler.build(context,**arguments)
    if condition=='out_of_authority':
        context=context.model_copy(update={'actor_id':'capstone-ungranted-actor'})
    return {'runner':prepared.runner,'context':context,'input':prepared.action_input.model_dump(mode='json'),
            'objects':projection['objects'],'source_fixture':{'organization_snapshot':snapshot.model_dump(mode='json'),
             'projection':projection,'action_input':action_input,'origin':'synthetic existing development scenario'},
            'adapter':adapter,'factory_source_unchanged':True}


def expected(role, condition):
    if role not in EXPECTATIONS:
        return {'outcome': 'not_assembled', 'allowed': [],
                'gap': 'Exact action fixture/authorized adapter still requires assembly; processor existence is not a task result'}
    if condition == 'out_of_authority':
        return {'outcome': 'authorization_blocked', 'allowed': [], 'processor_must_not_run': True,
                'property': 'An actor with no matching grant cannot execute this institution action'}
    kind, choice = EXPECTATIONS[role]['normal' if condition == 'in_scope' else 'missing']
    out = {'outcome': 'business_result', 'allowed': [{'kind': kind, 'choice': choice}],
           'property': 'Use only supplied authorized facts; unknown facts never become zero or a completed external action'}
    if role == 'QS' and condition == 'in_scope':
        out['independent_arithmetic'] = {'expression': '260 m2 * 2 CNY/m2', 'expected_total': '520', 'currency': 'CNY'}
    if role == 'Supplier' and condition == 'in_scope':
        out['price_reference'] = {'expected_batch_price': '1215.5', 'currency': 'HKD',
                                  'expression': '(10 panels * (100+10) HKD/panel + 5 HKD/batch) * 1.10',
                                  'source': 'declared fixture quantities/costs; arithmetic oracle fixed before runner execution'}
    if role == 'Government' and condition == 'in_scope':
        out['independent_rule'] = {'expression': 'document_type == declared_rule.expected_code',
                                   'expected_finding': 'conforms', 'scope': 'synthetic document code, no statutory permission or engineering safety claim'}
    return out
