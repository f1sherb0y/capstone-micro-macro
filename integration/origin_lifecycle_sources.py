"""Compose initial front/late sources for one native-generated project.

This module transforms only independent initial declarations, before either
engine is constructed. It never imports, edits or relabels a runtime result.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

from integration.bootstrap import enable_gba_imports
enable_gba_imports()
from integration.contractor_tender_development import _write
from integration.financing_professional_development import _merge_snapshot
from integration.tender_closeout_development import build_bundle as build_late
from src.actions.contracts.contractor_formation_objects import ContractorFormationTermsView, contractor_agreement_digest
from src.coordination.tasks import task_digest


def read(path):
    return json.loads(Path(path).read_bytes())


class InitialLateSources:
    def __init__(self, directory, *, config):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True)
        self.config = config
        self.shift = config['tender_open_tick'] - 1
        self.scale = Decimal(config['late_money_scale'])
        self.names = {'dev-tender-project':'PGEN0001', 'dev-work':'PGEN0001-work',
            'dev-contractor-a':'finance-contractor', 'dev-contractor-b':'origin-contractor-b',
            'dev-owner':'finance-owner-a', 'dev-qs':'finance-qs',
            'actual-supplier-a':'finance-supplier', 'actual-supplier-b':'origin-supplier-b',
            'actual-closeout-government':'finance-government',
            'dev-clock':config['run_id']+'-monthly-clock'}
        self.pattern = re.compile('|'.join(re.escape(k) for k in sorted(self.names,key=len,reverse=True)))
        self.declaration = task_digest({'type':'initial-origin-lifecycle-declarations.v1','config':config})
        self.written = {}
        self.documents = {}

    def string(self, value):
        value = self.pattern.sub(lambda m:self.names[m.group()],value)
        return re.sub(r'proposal-tick(\d+)-',lambda m:'proposal-tick'+str(int(m[1])+self.shift)+'-',value)

    def transform(self, value):
        if isinstance(value,str):
            return self.string(value)
        if isinstance(value,list):
            return [self.transform(v) for v in value]
        if not isinstance(value,dict):
            return value
        # Publication validators select native source declarations by the
        # operation id used as a mapping key. Rename keys together with the
        # context values, otherwise the unchanged validator correctly refuses
        # to publish an unbound project/terms source.
        result = {self.string(k):self.transform(v) for k,v in value.items()}
        if set(value)=={'kind','id','version'}:
            if value['kind'] not in {'Project','WorkScope','ClockProfile','Organization','ActionContract','Method'}:
                result['id'] = 'origin-late-' + result['id']
            return result
        if set(value)=={'clock_ref','offset'}:
            result['offset'] = value['offset'] + self.shift if value['offset'] else 0
        for key,v in value.items():
            if (key=='tick' or key.endswith('_tick')) and type(v) is int and v>0:
                result[key] = v + self.shift
        if isinstance(value.get('value'),str) and (value.get('currency')=='HKD' or value.get('unit')=='HKD'):
            result['value'] = format(Decimal(value['value'])*self.scale,'f')
        if result.get('basis_kind')=='assumed' and result.get('content_hash'):
            result['content_hash'] = task_digest({'original':value['content_hash'],'initial_declaration':self.declaration})
        # Evidence export rechecks permission at the actual final clock. The
        # initial mandate must explicitly permit that later historical read;
        # neither the current guard nor any executed record is weakened.
        if result.get('ref',{}).get('kind')=='Authorization' and 'validity' in result:
            result['validity']['end']['offset']=max(
                result['validity']['end']['offset'],self.config['ticks']+1)
        if result.get('ref',{}).get('kind')=='ContractTerms' and 'work_window' in result:
            result['work_window']['end']['offset'] = result['work_window']['start']['offset'] + self.config['contract_duration']
        # Owner resource demands must use the same independently declared work
        # window, not a ten-month source template copied into a 24-month job.
        if result.get('ref',{}).get('kind')=='ContractTerms' and 'owner_resource_demands' in result:
            for demand in result['owner_resource_demands']:
                demand['window'] = deepcopy(result['work_window'])
        return result

    def finalize_document(self, document):
        """Recompute initial agreement review digests after explicit transforms."""
        def visit(value):
            if isinstance(value,list):
                for v in value:visit(v)
            elif isinstance(value,dict):
                rows=value.get('objects',[])
                terms={task_digest(r['ref']):r['value'] for r in rows
                    if r['ref']['kind']=='ContractTerms' and 'price' in r['value']}
                for row in rows:
                    if row['ref']['kind']=='ContractFormationProfile' and 'reviewed_agreement_sha256' in row['value']:
                        profile=row['value']
                        profile['reviewed_agreement_sha256']=contractor_agreement_digest(
                            ContractorFormationTermsView.model_validate(terms[task_digest(profile['terms_ref'])]))
                for v in value.values():visit(v)
        visit(document)
        return document

    def settings(self, value):
        """Copy every referenced independent input to a fresh pinned file."""
        result=self.transform(value)
        def pin_files(original,target):
            if isinstance(original,list):
                for a,b in zip(original,target):pin_files(a,b)
            elif isinstance(original,dict):
                for k,v in original.items():pin_files(v,target[self.string(k)])
                for path_key,hash_key in [('file_path','file_sha256'),('snapshot_path','snapshot_sha256')]:
                    if path_key not in original:continue
                    path=Path(original[path_key])
                    if hashlib.sha256(path.read_bytes()).hexdigest()!=original[hash_key]:
                        raise ValueError('Initial late source template bytes changed')
                    key=str(path.resolve())
                    if key not in self.written:
                        body=self.finalize_document(self.transform(read(path)))
                        name=f'{len(self.written):02}-'+path.name
                        self.written[key]=_write(self.directory,name,body)
                        self.documents[key]=(read(path),body)
                    pin=self.written[key]
                    target[path_key]=pin['file_path'];target[hash_key]=pin['file_sha256']
        pin_files(value,result)
        return result

    def bind_initial_digests(self, settings):
        """Bind the authored initial documents to their transformed projections.

        These are pre-run private quantity/cost relations, not audit hashes of
        executed actions. Original native publication validators remain active.
        """
        from src.actions.contracts.contractor_bid_objects import ContractorBidQuantityView
        from src.actions.contracts.supplier_order_objects import order_agreement_digest
        pairs={}
        supply_agreements={}
        def collect(old,new):
            if isinstance(old,list):
                for a,b in zip(old,new):collect(a,b)
            elif isinstance(old,dict):
                if set(old)=={'ref','value'}:
                    digest=task_digest(old['value'])
                    previous=pairs.get(digest)
                    if previous is not None and previous!=new['value']:
                        raise ValueError('One initial source projection transformed inconsistently')
                    pairs[digest]=new['value']
                    if old['ref']['kind']=='OrderProposal':
                        supply_agreements[order_agreement_digest(old['value'])]=new['value']
                for k,v in old.items():collect(v,new[self.string(k)])
        for old,new in self.documents.values():collect(old,new)

        # The original builder declares this quantity as a source expectation
        # for later adoption, rather than storing it as an executed result.
        # Reconstruct that exact original expectation before transforming it.
        old_objects=[]
        def rows(value):
            if isinstance(value,list):
                for item in value:yield from rows(item)
            elif isinstance(value,dict):
                if set(value)=={'ref','value'}:yield value
                for item in value.values():yield from rows(item)
        for old,_ in self.documents.values():old_objects.extend(rows(old))
        unique={task_digest(r['value']):r for r in old_objects}
        old_objects=list(unique.values())
        def original(reference,field):
            candidates=[r['value'] for r in old_objects if r['ref']==reference and field in r['value']]
            if len(candidates)!=1:
                raise ValueError('Initial quantity relation does not identify one original '+field)
            return candidates[0]
        mappings=[r['value'] for r in old_objects if r['ref']['kind']=='ContractorQuantityMapping']
        for mapping in mappings:
            schedule=original(mapping['schedule_ref'],'lines')
            package=original(mapping['package_ref'],'allowed_method_refs')
            designs=[original(link['design_ref'],'limitations') for link in mapping['design_links']]
            evidence=[*mapping['evidence_refs'],*schedule['evidence_refs'],*package['evidence_refs'],
                *mapping['relation_evidence_refs'],*[ref for d in designs for ref in d['evidence_refs']]]
            evidence=list({task_digest(v):v for v in evidence}.values())
            now=mapping['available_at']
            expected=ContractorBidQuantityView.model_validate({'ref':mapping['quantity_ref'],
                'package_ref':mapping['package_ref'],
                'deliverable_refs':[link['released_ref'] for link in mapping['design_links']],
                'measurement_rule_ref':mapping['measurement_rule_ref'],
                'lines':[{'local_key':line['line_key'],'coverage_keys':line['coverage_keys'],
                    'quantity':line['quantity']} for line in schedule['lines']],
                'status':'ok','scope':mapping['scope'],'available_at':now,
                'effective_window':{'start':now,'end':now,'bounds':'closed_closed'},
                'evidence_refs':evidence}).model_dump(mode='json')
            digest=task_digest(expected)
            adoptions=[r['value'] for r in old_objects if r['ref']['kind']=='ContractorCostAdoption'
                and r['value']['quantity_basis_ref']==mapping['quantity_ref']]
            if not adoptions or any(a['quantity_sha256']!=digest for a in adoptions):
                raise ValueError('Original declared quantity expectation could not be reconstructed exactly')
            pairs[digest]=self.transform(expected)

        def data_bytes(value):
            return (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
        def bind(old,new,digests):
            changed=0
            if isinstance(old,list):
                return sum(bind(a,b,digests) for a,b in zip(old,new))
            if isinstance(old,dict):
                for key,value in old.items():
                    k=self.string(key)
                    if isinstance(value,str) and value in digests and (
                            key.endswith('_sha256') or key=='content_hash'):
                        replacement=digests[value]
                        if new[k]!=replacement:new[k]=replacement;changed+=1
                    else:changed+=bind(value,new[k],digests)
            return changed
        for _ in range(12):
            digests={old:task_digest(new) for old,new in pairs.items()}
            digests.update({old:order_agreement_digest(new) for old,new in supply_agreements.items()})
            digests.update({hashlib.sha256(Path(path).read_bytes()).hexdigest():
                hashlib.sha256(data_bytes(new)).hexdigest() for path,(_,new) in self.documents.items()})
            changed=sum(bind(old,new,digests) for old,new in self.documents.values())
            if not changed:break
        else:raise ValueError('Initial quantity/cost source digest dependencies did not converge')
        final=self.directory.parent/'bound-declarations';final.mkdir()
        pins={}
        for path,(_,new) in self.documents.items():
            previous=self.written[path]
            pins[previous['file_path']]=_write(final,Path(previous['file_path']).name,new)
        def replace_pins(value):
            if isinstance(value,list):
                for v in value:replace_pins(v)
            elif isinstance(value,dict):
                for v in value.values():replace_pins(v)
                for key,sha in [('file_path','file_sha256'),('snapshot_path','snapshot_sha256')]:
                    if value.get(key) in pins:
                        pin=pins[value[key]];value[key]=pin['file_path'];value[sha]=pin['file_sha256']
        replace_pins(settings)
        return settings


def regulatory_sources(directory, *, config, snapshot):
    """Predeclare phase-specific sources with the original regulatory builders."""
    from integration.government_intake_development import build_bundle
    from integration.government_approval_native_development import approval_plans
    directory=Path(directory);directory.mkdir()
    combined_intakes=[];combined_approvals=[];settings=None
    for phase,ticks in [('design',[config['design_approval_tick']]),
                        ('completion',list(range(config['completion_earliest_tick'],config['completion_latest_tick']+1)))]:
        built=build_bundle(directory/phase,run_id=config['run_id'],with_approval=True,
            completion=phase=='completion',with_feedback=True,sources_only=True,
            owner_id='finance-owner-a',agency_ids=('finance-government',),
            owner_function_id='origin-'+phase+'-applicant-function',
            clock_id=config['run_id']+'-monthly-clock',project_ids=('PGEN0001',),
            intake_ticks=ticks,approval_ticks=(ticks[0]+2,) if phase=='completion' else tuple(ticks),
            organization_locations={'finance-owner-a':next(o['public_location'] for o in snapshot['organizations']
                if o['organization_id']=='finance-owner-a')})
        body=built['settings'];own_snapshot=deepcopy(body['authority']['organization_snapshot'])
        intakes=read(body['file_path'])['plans']
        if phase=='completion':
            grants=[g for g in own_snapshot['authorizations'] if g['action_ids']==['GOV-A02']]
            own_snapshot['authorizations']=grants
            approvals=[]
            for tick in ticks:
                approvals.extend(approval_plans(intakes,grants,approval_ticks=(tick+2,),
                    initial_assignment_tick=tick,with_feedback=True,approval_organization_ids=('finance-government',)))
        else:
            approvals=read(body['approval']['file_path'])['plans']
        snapshot=_merge_snapshot(snapshot,own_snapshot)
        combined_intakes.extend(intakes);combined_approvals.extend(approvals)
        settings=deepcopy(body) if settings is None else settings
    settings.update(_write(directory,'intakes.json',{'schema_version':'government-intake-input.v1',
        'run_id':config['run_id'],'plans':combined_intakes}))
    settings['approval'].update(_write(directory,'approvals.json',{'schema_version':'government-approval-input.v1',
        'run_id':config['run_id'],'plans':combined_approvals}))
    return settings,snapshot


def compose_late(directory, *, config, front_host, request, native, initial_source_editor=None):
    directory=Path(directory);directory.mkdir()
    shift=config['tender_open_tick']-1
    seed=directory/'tender-seed'
    build_late(seed,run_id=config['run_id'],with_owner_award=True,
        review_ticks=tuple(t-shift for t in config['review_ticks']),authorization_read_until_tick=config['ticks'],
        contractor_ids=tuple(config.get('initial_contractor_ids',('dev-contractor-a','dev-contractor-b'))))
    original=read(seed/'assembly-host.json')['settings']
    if initial_source_editor is not None:
        original=initial_source_editor(directory/'model-pricing-declarations', original, config)
    transformer=InitialLateSources(directory/'declarations',config=config)
    late={name:transformer.settings(original[name]) for name in ['formation','tender','supplier','lifecycle']}
    late=transformer.bind_initial_digests(late)
    contractor=late['tender']['settings']['source_settings']['application_settings']['owner_contractor']['contractor']
    publications=contractor['professional']['publication']['settings']['native_sources']
    for plan in contractor['request_work_settings']['requests']:
        declaration=publications[plan['screening_publication']['source_context']['operation_id']]
        if (declaration['project_id']!=plan['project_id']
                or declaration['terms_ref']!=plan['screening_publication']['terms_ref']
                or declaration['screening_facts_ref']!=plan['screening_publication']['facts_ref']):
            raise ValueError('Initial tender publication lost its original project/terms/facts binding')
    front=front_host['settings']
    authority=deepcopy(front['bank']['authority']);snapshot=authority['organization_snapshot']
    late_snapshot=late['formation']['authority']['organization_snapshot']
    by_org={o['organization_id']:o for o in snapshot['organizations']}
    for org in late_snapshot['organizations']:
        if org['organization_id'] in by_org:
            org['public_location']=deepcopy(by_org[org['organization_id']]['public_location'])
    snapshot=_merge_snapshot(snapshot,late_snapshot)
    government,snapshot=regulatory_sources(directory/'regulatory',config=config,snapshot=snapshot)
    authority['organization_snapshot']=snapshot
    front.update(late,government=government)
    for name in ['bank','professional','opportunity','formation','supplier','government']:
        front[name]['authority']=deepcopy(authority)
    front['tender']['settings']['source_settings']['application_settings']['owner_contractor']['contractor']['authority']=deepcopy(authority)
    # Add only independent native agent profiles. Child projects, stages,
    # winners, design values, contracts and results are never adopted.
    agents=transformer.transform(read(seed/'macro-request.json')['agents'])
    by_id={a['agent_id']:a for a in request['agents']}
    for agent in agents:
        org=agent['agent_id']
        if org not in by_id:
            request['agents'].append(agent);by_id[org]=agent
        if agent['role'] in {'Contractor','Supplier'}:
            by_id[org]['total_resource_capacity']=1
    routes=native['settings'];late_routes=read(seed/'native-host.json')['settings']
    for key in ['micro_contractor_formation_scope','micro_owner_award_scope','micro_supplier_order_scope',
                'micro_contractor_supply_scope','micro_qs_evaluation_scope']:
        routes[key]=late_routes[key]
    routes.update(micro_government_intake_scope=True,micro_government_approval_scope=True,
        native_government_approval_transport=False)
    owned_proposals={('Government','consider_review_assignment'),('Government','decide_approval'),
        ('Contractor','consider_tender'),('Contractor','decide_contract_terms'),('Contractor','select_supplier'),
        ('Owner','select_tender_invitees'),('Owner','decide_contract_award'),('QS','evaluate_bid'),('Supplier','consider_supply_order')}
    owned_decisions={('Government','government_review_assignment'),('Government','government_design_approval'),
        ('Government','government_completion_approval'),('Contractor','tender_decision'),('Contractor','contract_negotiation'),
        ('Contractor','contractor_supplier_selection'),('Owner','owner_tender_shortlist'),('Owner','owner_contract_award'),
        ('QS','qs_bid_evaluation'),('Supplier','supplier_order_acceptance')}
    routes['native_proposals']=[r for r in routes['native_proposals'] if (r['role'],r['operation']) not in owned_proposals]
    routes['native_decisions']=[r for r in routes['native_decisions'] if (r['role'],r['decision_type']) not in owned_decisions]
    # Fail during input compilation rather than after an expensive business
    # run if a retained lifecycle action cannot be read at the final clock.
    from src.actions.contracts.common import ActionContext
    from src.organization.registry import OrganizationRegistry,OrganizationSnapshot
    checked=OrganizationSnapshot.model_validate(snapshot)
    registry=OrganizationRegistry(config['run_id'])
    for org in checked.organizations:registry.register(org)
    for grant in checked.authorizations:registry.authorize(grant)
    roles={a['agent_id']:a['role'] for a in request['agents']}
    for plan in read(front['lifecycle']['file_path'])['plans']:
        if plan['tick']>config['ticks']:continue
        context=ActionContext.model_validate(plan['context'])
        current=context.model_copy(update={'business_time':context.business_time.model_copy(
            update={'offset':config['ticks']})},deep=True)
        registry.grants(current,context.contract_ref.id,roles[plan['organization_id']])
    return front_host,request,native
