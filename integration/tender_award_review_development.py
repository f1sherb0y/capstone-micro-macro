"""Fixed 3A sources over the existing actual tender and bilateral award chain."""
from copy import deepcopy
import argparse
import json
from pathlib import Path

from integration.contractor_tender_development import _write, _write_launch_files, ref, known
from integration.contractor_tender_formation_development import build_bundle as build_formation
from integration.owner_invitation_native import OwnerInvitationPlan
from src.coordination.tasks import task_digest


def build_bundle(directory, *, run_id, authorized_budget='1000', ticks=8,
        selection_mode='review_native',selection_tie_break='wait'):
    from decimal import Decimal
    if not Decimal(authorized_budget).is_finite() or Decimal(authorized_budget) < 0 or ticks not in (4,8):
        raise ValueError('Review uses a finite nonnegative declared HKD budget and 4/8 tick window')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True,exist_ok=False)
    foundation = directory/'foundation'
    build_formation(foundation,run_id=run_id,with_owner_award=True)
    read = lambda name: json.loads((foundation/name).read_bytes())
    assembly = read('assembly-host.json')
    tender = assembly['settings']['tender']
    composition = tender['settings']['source_settings']['application_settings']['owner_contractor']
    snapshot = deepcopy(assembly['settings']['formation']['authority']['organization_snapshot'])
    invitation = json.loads(Path(composition['owner_invitation']['file_path']).read_bytes())['plans'][0]
    plan = deepcopy(invitation)
    context = plan['context']
    context.update(operation_id='owner-native-selection-budget-review',
        task_ref=ref('DecisionTask','owner-native-selection-budget-review'),
        read_token='owner-native-selection-budget-review',
        business_time={**context['business_time'],'offset':4})
    plan['tick'] = 4
    objects = plan['objects']
    native = next(r for r in objects if r['ref'] == plan['native_evidence_ref'])
    native['ref'] = ref('Evidence','owner-selection-review-current-native-request')
    native['value'].update(ref=native['ref'],locator='actual-native-owner-selection-review')
    plan['native_evidence_ref'] = native['ref']
    value = lambda kind: next(r['value'] for r in objects if r['ref']['kind'] == kind)
    original_grant = next(g for g in snapshot['authorizations'] if g['ref'] == context['authorization_refs'][0])
    grant = deepcopy(original_grant)
    grant['ref'] = ref('Authorization','owner-selection-review-authorization')
    grant['action_ids'] = ['OWN-A09']
    context['authorization_refs'] = [grant['ref']]
    context['candidate_set_ref'] = ref('CandidateSet','owner-selection-review-candidates')
    old_candidate = next(r for r in objects if r['ref']['kind'] == 'CandidateSet')
    old_candidate['ref'] = context['candidate_set_ref']
    old_candidate['value'].update(operation_id=context['operation_id'],as_of=context['business_time'])
    old_candidate['value']['candidates'][0]['permitted_choices'] = ['evaluate']
    for row in objects:
        if 'available_at' in row['value']:
            row['value']['available_at'] = deepcopy(context['business_time'])
        if row['ref']['kind'] in {'ProcurementPackage','ProcurementProcedure','FundingPosition'}:
            row['value']['authority_ref'] = grant['ref']
    profile = value('TenderEvaluationProfile')
    profile.update(author_authority_ref=grant['ref'],choice_order=['evaluate'],invitation_bidder_refs=[],
        selected_round_ref=value('TenderRound')['ref'],
        criteria=[{'metric':'price','weight':'1','scale':'1','unit':'HKD','basis_ref':plan['utility']['basis_ref']}])
    value('TenderRound').update(status='closed_for_bids',accepts_new_bids=False,accepts_awards=True)
    value('FundingPosition').update(as_of=context['business_time'],
        authorized_limit=known({'value':authorized_budget,'currency':'HKD','basis_ref':plan['utility']['basis_ref']}))
    pricing = ref('PricingBasis','owner-selection-review-common-HKD-basis')
    objects.append({'ref':pricing,'value':{k:deepcopy(value('ProcurementProcedure')[k])
        for k in ('scope','available_at','effective_window','evidence_refs')}})
    objects[-1]['value'].update(ref=pricing,procedure_ref=value('ProcurementProcedure')['ref'],
        permission=known(True),allowed_recipient_ids=[],required_public_recipient_ids=[])
    # Reuse original declared bidder functions, authority and their basis. No
    # actual Bid, SubmissionExecution or selected candidate is prefilled.
    organizations = {o['organization_id']:o for o in snapshot['organizations']}
    contractors = [r['value']['organization_id'] for r in objects if r['ref']['kind'] == 'EligibleBidder']
    needed = []
    for org in contractors:
        organization = organizations[org]
        declared = next(g for g in snapshot['authorizations'] if g['organization_id'] == org
            and 'CONTRACTOR-A02' in g['action_ids'])
        needed.extend([declared['ref'],declared['function_ref'],*declared['basis_refs']])
        needed.extend(organization['assignments'][0]['basis_refs'])
    supplied = {task_digest(r['ref']):r for r in objects}
    for source in foundation.rglob('sources.json'):
        document = json.loads(source.read_bytes())
        for snapshot_row in document.get('snapshots',[]):
            for row in snapshot_row['projection']['objects']:
                if row['ref'] in needed:
                    supplied.setdefault(task_digest(row['ref']),deepcopy(row))
    objects = list(supplied.values())
    if any(task_digest(r) not in supplied for r in needed):
        raise ValueError('Original declared bidder authority or basis source is missing')
    bid_refs = [ref('Bid','owner-review-bid:'+org) for org in contractors]
    plan['action_input']['bid_refs'] = bid_refs
    candidate = next(r['value'] for r in objects if r['ref']['kind'] == 'CandidateSet')
    candidate['candidates'].extend({'ref':r,'permitted_choices':['evaluate']} for r in bid_refs)
    context['visible_refs'] = list({task_digest(r):r for r in
        [*[r['ref'] for r in objects],*bid_refs,grant['ref']]}.values())
    grant['readable_refs'] = deepcopy(context['visible_refs'])
    objects.append({'ref':grant['ref'],'value':deepcopy(grant)})
    plan['objects'] = objects
    plan = OwnerInvitationPlan.model_validate(plan).model_dump(mode='json')
    snapshot['authorizations'].append(grant)
    composition['contractor']['authority']['organization_snapshot'] = deepcopy(snapshot)
    assembly['settings']['formation']['authority']['organization_snapshot'] = deepcopy(snapshot)
    sources = _write(directory,'owner-selection-review-input.json',{
        # Original plan schema is deliberately reused for OWN-A09 source input.
        'schema_version':'owner-invitation-input.v1','run_id':run_id,'plans':[plan]})
    composition['owner_selection_review'] = {'version':'2',**sources,
        'selection_mode':selection_mode,'selection_tie_break':selection_tie_break}
    native = read('native-host.json')
    native['settings']['native_decisions'] = [r for r in native['settings']['native_decisions']
        if (r['role'],r['decision_type']) != ('Owner','owner_preferred_bidder_selection')]
    request = read('macro-request.json')
    request['ticks'] = ticks
    _write(directory,'macro-request.json',request)
    _write(directory,'native-host.json',native)
    _write(directory,'assembly-host.json',assembly)
    _write_launch_files(directory,assembly_hook='integration.contractor_tender_formation_development:configure_assembly',
        readme_override=('GOAL 3A: original OWN-A09 reviews actual submitted bids and the declared HKD budget. '
            + ('The declared lowest eligible price policy selects a current candidate, with an explicit organization-ID tie rule or a wait. '
               if selection_mode=='lowest_eligible_price' else
               'Its final Boolean accepts/rejects the original native candidate; it cannot override the winner. ')
            + 'Original Contractor A04 and Owner A10 remain responsible for independent consent; native signs. '
            + 'All initial commercial and eligibility sources are explicit synthetic assumptions.'))
    return {'run_id':run_id,'authorized_budget':authorized_budget,'ticks':ticks,
            'prefilled_actual_bids':False,'prefilled_selection':False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--config',type=Path,default=Path('config/tender_award_review.json'))
    parser.add_argument('--scenario',choices=['normal','budget_refusal'],default='normal')
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_bytes())
    if config['schema_version'] != 'tender-award-review.v1':
        raise ValueError('Unknown 3A scenario configuration')
    scenario = config['scenarios'][args.scenario]
    print(json.dumps(build_bundle(args.output,run_id=config['run_id']+'-'+args.scenario,**scenario)))


if __name__ == '__main__':
    main()
