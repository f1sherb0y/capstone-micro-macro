"""Declare independent Owner resources and exact agreement views before runtime."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from integration.contractor_tender_development import _write, ref
from integration.owner_award_native import OwnerAwardNativePlan, OwnerAwardNativeSettings
from src.actions.contracts.common import Reference
from src.actions.contracts.owner_award_objects import owner_award_schemas
from src.coordination.tasks import task_digest


def build_owner_sources(directory, *, run_id, formation_plans, snapshot, max_prior_accepts=1):
    root = Path(__file__).resolve().parent / 'examples'
    host_path = root / 'role_contract_owner_award_host.json'
    raw = json.loads(host_path.read_bytes())['settings']['source_settings']
    invocation = json.loads((root / 'role_contract_owner_award_invocation.json').read_bytes())
    result = []
    snapshot = deepcopy(snapshot)
    counterparties = {}
    prices = {}
    for source in formation_plans:
        terms, = [r['value'] for r in source['objects'] if r['ref'] == source['action_input']['terms_ref']]
        counterparties.setdefault(source['project_id'], set()).add(terms['contractor_id'])
        prices.setdefault((source['project_id'], terms['contractor_id']), set()).add(terms['price']['value'])
    seen = set()
    for source in formation_plans:
        # Repeated Contractor revisions do not automatically produce a new
        # Owner request. The first actual negotiation of each project is used.
        tick = source['tick'] + 1
        project = source['project_id']
        original = {task_digest(r['ref']): r['value'] for r in source['objects']}
        full = deepcopy(original[task_digest(source['action_input']['terms_ref'])])
        owner, contractor = full['client_id'], full['contractor_id']
        price = full['price']['value']
        if (project, contractor, price) in seen:
            continue
        seen.add((project, contractor, price))
        # Candidate-specific sources are initial independent views. Only the
        # actual native winner may select one; no future winner is prefilled.
        suffix = '-' + contractor if len(counterparties[project]) > 1 else ''
        if len(prices[(project, contractor)]) > 1:
            suffix += '-price-' + price
        tag = project + '-owner' + suffix + '-t' + str(tick)
        clock = source['context']['business_time']['clock_ref']
        own_function = ref('FunctionAssignment', owner + '-award' + suffix + '-function')
        grant_ref = source['action_input']['authority_ref']
        contractor_function = source['context']['function_ref']
        native = ref('Evidence', tag + '-actual-received-acceptance')
        acceptance = ref('PartyAcceptance', tag + '-received-contractor-decision')
        def transform(value):
            if isinstance(value, str):
                return {'v2-publication-owner': owner, 'v2-publication-owner-actor': owner,
                        'v2-publication-contractor': contractor, 'v2-publication-contractor-actor': contractor,
                        'synthetic-HK': 'Hong Kong'}.get(value, value)
            if isinstance(value, list):
                return [transform(v) for v in value]
            if not isinstance(value, dict):
                return value
            if set(value) == {'kind', 'id', 'version'}:
                kind, name = value['kind'], value['id']
                if kind == 'ActionContract': return deepcopy(value)
                if kind == 'ClockProfile': return deepcopy(clock)
                if kind == 'Project': return deepcopy(full['scope']['ref'])
                if kind == 'WorkScope': return deepcopy(full['scope']['coverage_refs'][0])
                if kind == 'FunctionAssignment' and 'owner-function' in name: return deepcopy(own_function)
                if kind == 'FunctionAssignment' and 'contractor-function' in name: return deepcopy(contractor_function)
                if kind == 'Authorization' and 'contractor-grant' in name: return deepcopy(grant_ref)
                if kind == 'ContractTerms': return deepcopy(full['ref'])
                if kind == 'TenderRound': return deepcopy(full['round_ref'])
                if kind == 'ProcurementPackage': return deepcopy(full['package_ref'])
                if kind == 'ContractClause': return deepcopy(full['clause_refs'][0])
                if kind == 'ContractTemplate': return deepcopy(full['contract_template_ref'])
                return ref(kind, tag + '-' + name, value['version'])
            if set(value) == {'clock_ref', 'offset'}:
                return {'clock_ref': deepcopy(clock), 'offset': max(0, value['offset'] - 18)}
            return {k: transform(v) for k, v in value.items()}
        objects = []
        for row in raw['source_projection']['objects']:
            kind, name, version = row['ref']['kind'], row['ref']['id'], row['ref']['version']
            if kind == 'Authorization' and not ('owner-grant' in name and version == '3'):
                continue
            if kind == 'FunctionAssignment' and 'owner-function' not in name:
                continue
            if kind == 'Requirement' and 'pending-contractor-acceptance' in name:
                continue
            objects.append(transform(row))
        by_kind = lambda kind: next(r['value'] for r in objects if r['ref']['kind'] == kind)
        by_kind('FunctionAssignment')['basis_refs'] = [deepcopy(full['price']['basis_ref'])]
        by_kind('ClockProfile')['tick_unit'] = 'month'
        by_kind('ClockProfile')['evidence_refs'] = [deepcopy(full['price']['basis_ref'])]
        context = transform(invocation['context'])
        action_input = transform(invocation['action_input'])
        action_input['party_acceptance_refs'] = [acceptance]
        owner_terms = by_kind('ContractTerms')
        owner_terms.update(available_at={'clock_ref': clock, 'offset': 0}, total_price=deepcopy(full['price']),
            work_window=deepcopy(full['work_window']), scope_keys=deepcopy(full['scope_keys']),
            required_party_ids=deepcopy(full['required_party_ids']), clause_refs=deepcopy(full['clause_refs']),
            condition_refs=deepcopy(full['condition_refs']))
        for demand in owner_terms['owner_resource_demands']:
            demand['window'] = deepcopy(full['work_window'])
        owner_terms['evidence_refs'].append(native)
        offer = by_kind('Offer')
        offer.update(author_actor_id=source['context']['actor_id'], author_function_ref=deepcopy(contractor_function),
            author_authority_ref=deepcopy(grant_ref), author_action_id='CONTRACTOR-A04',
            available_at=deepcopy(source['context']['business_time']), condition_refs=deepcopy(full['condition_refs']))
        template = by_kind('ContractTemplate')
        template['required_condition_refs'] = deepcopy(full['condition_refs'])
        profile = by_kind('ContractFormationProfile')
        profile.update(choice_order=['accept'], requested_change_refs=[], pending_party_condition_refs=[],
                       allow_owner_acceptance_pending_other_parties=False)
        current = by_kind('CommitmentSnapshot')
        current['as_of'] = {'clock_ref': clock, 'offset': tick}
        for commitment in current['resource_commitments']:
            commitment['window'] = deepcopy(full['work_window'])
        by_kind('ResourceCommitment')['window'] = deepcopy(full['work_window'])
        # Capacity is independently checked by the real A04 processor. Bind its
        # actual acceptance below, rather than predeclaring a successful check.
        capacity = by_kind('Requirement')
        capacity['verification'] = {'state': 'known', 'value': False}
        capacity['evidence_refs'].append(native)
        change = ref('ContractChangeRequest', tag + '-authorized-price-review')
        clause = deepcopy(by_kind('ContractClause'))
        clause['ref'] = change
        objects.append({'ref': change, 'value': clause})
        for reference in (grant_ref, contractor_function):
            objects.append({'ref': deepcopy(reference), 'value': deepcopy(original[task_digest(reference)])})
        # Preserve original public authority/price evidence identities; no
        # Contractor cash, crew calendars or private planning views are shared.
        for row in source['objects']:
            if row['ref']['kind'] == 'Evidence' and row['value'].get('basis_kind') != 'observed':
                objects.append(deepcopy(row))
        objects.append({'ref': native, 'value': {'ref': native, 'source_kind': 'synthetic', 'basis_kind': 'observed',
            'locator': 'actual-native-negotiation-and-independent-exact-agreement-correspondence',
            'content_hash': None, 'effective_window': None}})
        declaration = task_digest({'template_sha256': hashlib.sha256(host_path.read_bytes()).hexdigest(),
            'reviewed_complete_contractor_terms': full, 'owner_terms': owner_terms,
            'owner_initial_authorized_budget': current['authorized_budget'], 'owner_old_funding': current['funding_uses'],
            'owner_initial_resources': current['resources'], 'owner_old_resources': current['resource_commitments'],
            'max_prior_accepts': max_prior_accepts})
        for row in objects:
            if row['ref']['kind'] == 'Evidence' and row['ref'] not in [r['ref'] for r in source['objects']]:
                if row['ref'] != native:
                    row['value'].update(locator='independent-owner-award-budget-resources-and-complete-agreement-review',
                                        content_hash=declaration)
        context.update(run_id=run_id, actor_id=owner, operation_id=tag + '-OWN-A10', task_ref=ref('DecisionTask', tag),
            business_time={'clock_ref': clock, 'offset': tick}, read_token=tag + '-read', execution_mode='rule',
            visible_refs=[r['ref'] for r in objects] + [acceptance])
        candidates = by_kind('CandidateSet')
        candidates.update(operation_id=context['operation_id'], as_of=deepcopy(context['business_time']))
        candidates['candidates'].append({'ref': change, 'permitted_choices': ['revise']})
        grant = by_kind('Authorization')
        grant['readable_refs'] = deepcopy(context['visible_refs'])
        schemas = owner_award_schemas()
        for row in objects:
            value = deepcopy(row['value'])
            if row['ref'] == native: value['content_hash'] = '0' * 64
            schemas.validate_projection(Reference.model_validate(row['ref']), value)
        snapshot['authorizations'].append(deepcopy(grant))
        owner_org = next(o for o in snapshot['organizations'] if o['organization_id'] == owner)
        function = by_kind('FunctionAssignment')
        if function not in owner_org['assignments']: owner_org['assignments'].append(deepcopy(function))
        result.append(OwnerAwardNativePlan.model_validate({'organization_id': owner, 'project_id': project,
            'tick': tick, 'context': context, 'action_input': action_input, 'objects': objects,
            'reviewed_contractor_terms': full, 'received_acceptance_ref': acceptance,
            'native_evidence_ref': native, 'history_revision_refs': [change], 'max_prior_accepts': max_prior_accepts,
            'utility': {'value': '0.7', 'unit': 'score', 'basis_ref': native},
            'probability': {'value': '1', 'unit': 'probability', 'basis_ref': native}}).model_dump(mode='json'))
    settings = OwnerAwardNativeSettings.model_validate({'version': '1', 'policy_version': 'independent-owner-award-v1',
        **_write(directory, 'owner-award-input.json', {'schema_version': 'owner-award-native-input.v1',
                                                      'run_id': run_id, 'plans': result})})
    return settings, snapshot
