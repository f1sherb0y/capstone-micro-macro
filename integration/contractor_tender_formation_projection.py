"""Project actual native submission and current occupancy into A04 read views.

Only an actually submitted, actually preferred own original A02 can enter.
No submission command, formal registry, signature, cash or reservation is made.
Future calendars and commercial terms remain independent initial sources.
"""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

from pydantic import Field
from src.actions.contracts.common import StrictRecord,ref_type,Reference
from src.actions.contracts.contractor_formation_objects import contractor_formation_schemas
from src.coordination.tasks import TaskConflict,TaskIdentity,task_digest
from integration.contractor_selected_tender_sources import query_selected_tender_sources
from integration.contractor_tender_request_trigger import read_request_record


class OriginalTenderProjection(StrictRecord):
    bid_ref: ref_type('Bid')
    submission_ref: ref_type('SubmissionExecution')
    source_evidence_ref: ref_type('Evidence')
    resource_evidence_ref: ref_type('Evidence')
    current_occupancy_ref: ref_type('ResourceCommitment')
    future_commitment_refs: list[ref_type('ResourceCommitment')]=Field(default_factory=list)


def project_original_tender_formation(app,plan,request,objects):
    binding=plan.original_tender_projection
    recover=getattr(app.assembly.client.proposal_handlers.get(('Contractor','consider_tender')),'_recovery_host',None)
    if binding is None or plan.original_tender_request_id is None or not callable(recover):
        raise TaskConflict('Original tender projection requires its declared binding and original host')
    host=recover()
    if (host.pipeline.assembly is not app.assembly or host.pipeline.worker.store is not app.worker.store
            or host.pipeline.assembler.organizations is not app.organizations):
        raise TaskConflict('Original tender projection changes its shared assembly, journal or authority')
    origin=read_request_record(application=SimpleNamespace(host=host,store=app.worker.store,assembly=app.assembly),
        organization_id=plan.organization_id,request_id=plan.original_tender_request_id)
    if origin['state']!='selected':raise TaskConflict('Original tender projection remains unresolved')
    source=query_selected_tender_sources(host,origin['native_request'],TaskIdentity(**origin['bid_identity']),
        current_context=plan.context)
    result=deepcopy(objects);by_ref={task_digest(r['ref']):r for r in result}
    visible={r.key() for r in plan.context.visible_refs}
    def put(ref,value):
        ref=Reference.model_validate(ref)
        if ref.key() not in visible:raise TaskConflict('Original tender projection exceeds its declared source references')
        key=task_digest(ref.model_dump(mode='json'))
        old=by_ref.get(key)
        if old is not None and old['value']!=value:
            raise TaskConflict('Original tender projection cannot replace an independent supplied source')
        if old is None:
            row={'ref':ref.model_dump(mode='json'),'value':deepcopy(value)};result.append(row);by_ref[key]=row
    def row(ref):return by_ref[task_digest(ref.model_dump(mode='json') if isinstance(ref,Reference) else ref)]['value']
    if any(r['ref']['kind'] in {'Bid','SubmissionExecution'} for r in result):
        raise TaskConflict('Initial actual-tender input must not predeclare a bid or submission outcome')
    schemas=contractor_formation_schemas()
    keep={'Evidence','ProgrammeProposal','QuantityBasis','CostBasis','WorkMethod','Qualification','ResourcePool',
        'TimeWindow','Authorization','FunctionAssignment','ProcurementPackage','TenderRound','ReleasedDeliverable',
        'ClockProfile','Project','WorkScope','MeasurementRule','Deliverable'}
    witness=source['history']['witness']['source_reading']
    for item in witness:
        if item['ref']['kind'] in keep:
            schemas.validate_projection(Reference.model_validate(item['ref']),item['projection'])
            put(item['ref'],item['projection'])
    native=row(binding.source_evidence_ref)
    if native['content_hash'] is not None:raise TaskConflict('Native submission evidence must be unresolved initially')
    native['content_hash']=source['native_submission']['source_event_sha256']
    terms=row(plan.action_input['terms_ref']);offer=row(plan.action_input['offer_ref'])
    if terms['bid_ref']!=binding.bid_ref.model_dump(mode='json') or offer['bid_ref']!=terms['bid_ref']:
        raise TaskConflict('Actual original bid differs from the independently declared agreement binding')
    common={'scope':deepcopy(terms['scope']),'available_at':plan.context.business_time.model_dump(mode='json'),
        'effective_window':deepcopy(terms['effective_window']),'evidence_refs':[binding.source_evidence_ref.model_dump(mode='json')]}
    put(binding.bid_ref,{'ref':binding.bid_ref.model_dump(mode='json'),**common,'organization_id':plan.organization_id,
        'round_ref':deepcopy(terms['round_ref']),'submission_ref':binding.submission_ref.model_dump(mode='json'),
        'reservation_refs':[],'draft':source['original_bid']})
    # This is the observed native command's accepted bid view, not a second
    # host's document-receipt assertion or a newly issued submission command.
    put(binding.submission_ref,{'ref':binding.submission_ref.model_dump(mode='json'),**common,
        'organization_id':plan.organization_id,'bid_ref':binding.bid_ref.model_dump(mode='json'),
        'package_ref':deepcopy(terms['package_ref']),'round_ref':deepcopy(terms['round_ref']),
        'command_id':origin['native_request']['request_id'],'status':'accepted',
        'result_basis_ref':binding.source_evidence_ref.model_dump(mode='json')})
    current=app.assembly.read_enterprise_resources(organization_id=plan.organization_id,read_guard=app.read_guard)
    original,=[r['projection'] for r in witness if r['ref']['kind']=='ContractorCapacity']
    if (len(original['resources'])!=1 or current['observed_tick']!=plan.tick
            or current['resource_unit']!='normalized_enterprise_capacity'
            or original['resources'][0]['total']['unit']!='normalized_enterprise_capacity'
            or Decimal(str(current['facts']['total_resource_capacity']))!=Decimal(original['resources'][0]['total']['value'])):
        raise TaskConflict('Current original resource total or declared normalized unit changed; revise sources explicitly')
    evidence=row(binding.resource_evidence_ref)
    if evidence['content_hash'] is not None:raise TaskConflict('Current resource evidence must be unresolved initially')
    evidence['content_hash']=current['record_sha256']
    capacity=row(plan.action_input['capacity_ref'])
    if (capacity['resources'] or capacity['qualification_refs']
            or [c['commitment_ref'] for c in capacity['commitments']]!=[r.model_dump(mode='json') for r in binding.future_commitment_refs]):
        raise TaskConflict('Current capacity may bind observed resources only; future occupancy stays explicitly supplied')
    capacity['resources']=deepcopy(original['resources']);capacity['qualification_refs']=deepcopy(original['qualification_refs'])
    amount=Decimal(str(current['facts']['occupied_resource']))
    if not amount.is_finite() or amount<0:raise TaskConflict('Current occupancy is not a finite original nonnegative quantity')
    now=plan.context.business_time.model_dump(mode='json')
    use={'commitment_ref':binding.current_occupancy_ref.model_dump(mode='json'),
        'resource_ref':deepcopy(capacity['resources'][0]['resource_ref']),
        'quantity':{'value':str(amount),'unit':'normalized_enterprise_capacity',
            'basis_ref':binding.resource_evidence_ref.model_dump(mode='json')},
        'window':{'start':now,'end':{**now,'offset':plan.tick+1},'bounds':'closed_open'}}
    capacity['commitments'].append(use)
    put(binding.current_occupancy_ref,{'ref':binding.current_occupancy_ref.model_dump(mode='json'),**common,
        'organization_id':plan.organization_id,**{k:v for k,v in use.items() if k!='commitment_ref'}})
    for item in result:
        # The caller binds the current negotiation witness after collecting
        # this original-bid/current-capacity provenance. It is not a receipt.
        if item['ref']==plan.native_evidence_ref.model_dump(mode='json'):
            continue
        schemas.validate_projection(Reference.model_validate(item['ref']),item['value'])
    return result,{'original_selected_source_sha256':source['record_sha256'],
        'actual_native_submission':source['native_submission'],'actual_own_selection':source['own_selection'],
        'current_resource_record_sha256':current['record_sha256'],'current_only_window':[plan.tick,plan.tick+1],
        'future_calendar_mutated':False,'formal_state_mutated':False}
