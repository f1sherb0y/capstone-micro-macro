"""Use the existing bounded tender model host in the project-origin case.

All pricing and matching agreement alternatives are independent initial sources.
The original processors calculate bids; the native engine owns actual outcomes.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3

from integration.contractor_tender_development import _write
from integration.dual_lifecycle_case import (
    add_agreement_variant, align_source_contexts, execution_contexts, read, snapshot_file,
)
from integration.tender_model_development import TenderModelDevelopmentSettings, add_initial_model_options
from src.coordination.tasks import task_digest


def model_options(config):
    model=TenderModelDevelopmentSettings.model_validate(config['model_options'])
    cap=config.get('api_total_attempt_cap',4)
    if model.strategy!='single_agent' or type(cap) is not int or not 1 <= cap <= 32 or model.max_calls>cap:
        raise ValueError('Origin model case requires single-agent pricing within an explicit case cap (1 to 32)')
    return model


def prior_attempts(config):
    """Charge retained failed batches against this case's total attempt cap."""
    batches=[]
    for previous in config.get('api_previous_batches',[]):
        path=Path(previous['journal_path']).resolve()
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest!=previous['journal_sha256']:
            raise ValueError('Retained prior API batch journal changed')
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
            records=[json.loads(v) for v, in db.execute('SELECT record FROM model_call_budgets')]
        count=sum(r['charged_calls'] for r in records)
        if count!=previous['attempted_calls']:
            raise ValueError('Prior API attempt count differs from its durable budget')
        batches.append({**previous,'verified_attempted_calls':count})
    if sum(b['verified_attempted_calls'] for b in batches)+model_options(config).max_calls>config.get('api_total_attempt_cap',4):
        raise ValueError('New API budget would exceed the total case attempt cap')
    return batches


def author_initial_options(directory, settings, config):
    """Extend the unscaled initial template before the existing origin composer.

    Reuse the dual-case option and agreement builders, then let the existing
    origin composer shift time, rename identities, scale money and bind hashes.
    No executed source, result or original child manifest is rewritten.
    """
    from integration.owner_award_native_development import build_owner_sources
    directory=Path(directory);directory.mkdir()
    settings=deepcopy(settings)
    model=model_options(config)
    prior_attempts(config)
    authority=settings['formation']['authority']
    snapshot=authority['organization_snapshot']
    sources=settings['tender']['settings']['source_settings']
    app=sources['application_settings']['owner_contractor']['contractor']
    source_doc=read(sources['snapshots']['snapshot_path'])
    quantity_doc=read(sources['quantity_snapshots']['snapshot_path'])
    plans=app['request_work_settings']['requests']
    auths={p['organization_id']:next(g for g in snapshot['authorizations']
        if g['ref'] in p['screening_context']['authorization_refs']) for p in plans}
    add_initial_model_options(config=model,snapshots=source_doc['snapshots'],
        quantity_snapshots=quantity_doc['snapshots'],plans=plans,authorizations=auths)
    contexts={s['context']['read_token']:s['context'] for s in source_doc['snapshots']}
    app['request_work_settings']['requests']=align_source_contexts(plans,contexts)
    for source in quantity_doc['snapshots']:
        source['context']=deepcopy(contexts[source['context']['read_token']])
    formations=read(settings['formation']['file_path'])
    original=list(formations['plans'])
    for plan in original:
        references=[r['ref'] for s in source_doc['snapshots']
            if s['projection']['organization_id']==plan['organization_id']
            for r in s['projection']['objects'] if r['ref']['kind']=='ContractorPricingProfile'
            and r['ref']['id'].endswith('-model-alternative')]
        for reference in references:
            if reference not in plan['context']['visible_refs']:
                plan['context']['visible_refs'].append(deepcopy(reference))
            for grant in snapshot['authorizations']:
                if grant['ref'] in plan['context']['authorization_refs'] and reference not in grant['readable_refs']:
                    grant['readable_refs'].append(deepcopy(reference))
            for row in plan['objects']:
                if row['ref']['kind']=='Authorization' and reference not in row['value']['readable_refs']:
                    row['value']['readable_refs'].append(deepcopy(reference))
    alternative_price=format(Decimal('100')*(1+Decimal(model.alternate_markup_fraction)),'f')
    for plan in original:
        formations['plans'].append(add_agreement_variant(plan,price=alternative_price,snapshot=snapshot))
    owner,snapshot=build_owner_sources(directory,run_id=config['run_id'],
        formation_plans=formations['plans'],snapshot=snapshot,max_prior_accepts=1)
    authority['organization_snapshot']=snapshot
    settings['formation'].update(_write(directory,'formation.json',formations),
        owner=owner.model_dump(mode='json'),authority=authority)
    settings['supplier']['authority']=deepcopy(authority)
    app['authority']=deepcopy(authority)
    sources['snapshots']=snapshot_file(directory,'sources.json',source_doc)
    sources['quantity_snapshots']=snapshot_file(directory,'quantity-sources.json',quantity_doc)
    _write(directory,'pricing-declaration.json',{
        'source_kind':'synthetic','status':'initial-alternatives-not-decisions',
        'base_cost_before_origin_scale':'100','markup_fractions':['0.1',model.alternate_markup_fraction],
        'alternative_price_before_origin_scale':alternative_price,
        'matching_initial_agreement_plans':len(formations['plans']),
        'formed_results_or_native_bids_prefilled':False})
    return settings


def configure_model_inputs(directory, host, native, config):
    directory=Path(directory);directory.mkdir()
    model=model_options(config)
    sources=host['settings']['tender']['settings']['source_settings']
    app=sources['application_settings']['owner_contractor']['contractor']
    for field,name in [('snapshots','sources.json'),('quantity_snapshots','quantity-sources.json')]:
        sources[field]=snapshot_file(directory,name,
            execution_contexts(read(sources[field]['snapshot_path']),'llm'))
    app['request_work_settings']['requests']=execution_contexts(app['request_work_settings']['requests'],'llm')
    app.update(model_host_factory='integration.contractor_tender_model_options:build_model_host',
        model_host_settings=model.host_settings(config['run_id']))
    native['settings']={'native':native['settings'],
        'expected_provider':model.provider,'expected_model':model.model}
    return host,native


def configure_assembly(*,assembly,request,output_directory,offline,configuration):
    from integration.financing_professional_native import FinancingProfessionalApplication
    from integration.model_tender_native import ModelTenderAgentClient
    from integration.module_host import GbaModuleHostConfiguration,GbaModuleHostExtension
    from integration.verify_goal3_minimal_native_fix import save_or_match
    if offline is not False or not isinstance(assembly.client,ModelTenderAgentClient):
        raise ValueError('Origin model assembly requires the explicit live model client')
    config=GbaModuleHostConfiguration.model_validate(configuration)
    assembly.client.native_routes.attach(assembly)
    app=FinancingProfessionalApplication(assembly=assembly,settings=config.settings,
        request=request,output_directory=output_directory,offline=offline)

    def evidence():
        events=[e.model_dump(mode='json') for e in assembly.engine.events.events]
        if assembly.engine.status=='completed':
            save_or_match(Path(output_directory),'native-run-state.json',{
                'schema_version':'origin-native-run-state.v1',
                'simulation':assembly.engine.response().model_dump(mode='json'),
                'original_global_events':events,
                'boundary':'Original state captured before component export; not a substitute success receipt.'})
        return {**app.evidence(),'original_global_events':events}

    return GbaModuleHostExtension(version='origin-model-lifecycle.v1',evidence=evidence,
        close=app.close,writer_guard=app.read_guard,checkpoint_validator=app.check)
