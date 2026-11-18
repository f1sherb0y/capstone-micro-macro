"""Plan or explicitly run independent synthetic V2 procurement decisions."""
import argparse
from copy import deepcopy
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from integration.role_contract_fixture_host import build_role_host
from integration.role_contract_host import run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.coordination.tasks import task_digest


_FACTORY = 'integration.role_contract_fixture_host:build_role_host'
_SCHEMAS = {
    'ARCHITECT-A02': 'src.actions.contracts.architect_objects:architect_intake_schemas',
    'OWN-A04': 'src.actions.contracts.owner_commission_objects:owner_commission_schemas',
}
_FORMATION_FACTORY = 'integration.contractor_role_contract_host:build_role_host'
_FORMATION_CASES = {
    'v2-contractor-formation-accept': 'accept',
    'v2-contractor-formation-revision': 'revise',
    'v2-contractor-formation-reject': 'reject',
    'v2-linked-formation-accept': 'accept',
}
_PUBLICATION_CASE = 'v2-owner-tender-publication'
_PUBLICATION_FACTORY = 'integration.owner_role_contract_host:build_role_host'
_BID_CASE = 'v2-contractor-bid-submit'
_EVALUATION_CASE = 'v2-owner-tender-evaluation'
_AWARD_CASE = 'v2-owner-award-accept'
_CONFIGURED_CASES = {
    'v2-received-tender-bid': {
        'action': 'CONTRACTOR-A02', 'role': 'Contractor', 'choices': {'submit_bid'},
        'factory': _FORMATION_FACTORY, 'source_module': 'owner_tender_contractor',
        'source_version': 'configured-contractor-owner-tender-fixture-sources.v1',
        'preparation_schema': 'owner-tender-reception-configuration-result.v1',
        'selection': 'received_tender_inputs', 'provenance': 'received_tender_input',
        'table': 'contractor_bid_results'},
    'v2-received-bids-evaluation': {
        'action': 'OWN-A09', 'role': 'Owner', 'choices': {'evaluate'},
        'factory': _PUBLICATION_FACTORY, 'source_module': 'contractor_bid_owner',
        'source_version': 'configured-owner-contractor-bid-fixture-sources.v1',
        'preparation_schema': 'contractor-bid-reception-configuration-result.v1',
        'selection': 'received_contractor_bid_inputs', 'provenance': 'received_contractor_bid_input',
        'table': 'owner_tender_results'},
    'v2-selected-evaluation-award': {
        'action': 'OWN-A10', 'role': 'Owner', 'choices': {'accept', 'revise', 'reject'},
        'factory': _PUBLICATION_FACTORY, 'source_module': 'owner_tender_award',
        'source_version': 'configured-owner-tender-award-fixture-sources.v1',
        'preparation_schema': 'owner-tender-award-configuration-result.v1',
        'selection': 'tender_evaluation_inputs', 'provenance': 'tender_evaluation_input',
        'table': 'owner_award_results'},
    'v2-received-award-formation': {
        'action': 'CONTRACTOR-A04', 'role': 'Contractor', 'choices': {'accept', 'revise', 'reject'},
        'factory': _FORMATION_FACTORY, 'source_module': 'owner_award_contractor',
        'source_version': 'configured-contractor-owner-award-fixture-sources.v1',
        'preparation_schema': 'owner-award-reception-configuration-result.v1',
        'selection': 'received_award_inputs', 'provenance': 'received_award_input',
        'table': 'contractor_formation_results'},
}


def _read_pinned_bindings(step):
    """Capture each configured input file once, without opening its journal."""
    root = Path(__file__).resolve().parents[1]
    files, data = [], []
    for label in ('invocation', 'configuration', 'origin'):
        relative = Path(step[label + '_path'])
        path = (root / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(root / 'integration/examples'):
            raise ValueError('V2 bindings must stay in the repository example directory')
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if label != 'origin' and sha != step[label + '_file_sha256']:
            raise ValueError('V2 binding changes its declared original file SHA')
        _, value = parse_input_json(raw)
        files.append((path, sha))
        data.append(value)
    return *data, files


def _prepare_formation(case):
    """Read pinned input/configuration data; instantiate no host or schema."""
    choice = _FORMATION_CASES[case['case_id']]
    steps = case.get('steps', [])
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V2'
            or case.get('origin') != 'synthetic' or len(steps) != 1 or not isinstance(steps[0], dict)
            or (steps[0].get('action_id'), steps[0].get('expected_kind'), steps[0].get('expected_choice'))
                != ('CONTRACTOR-A04', 'completed', choice)
            or steps[0].get('host_factory') != _FORMATION_FACTORY):
        raise ValueError('V2 formation requires its independently declared synthetic A04 branch')
    step = steps[0]
    request, config, origin, files = _read_pinned_bindings(step)
    context, action_input = request['context'], request['action_input']
    settings = config['settings']
    source = settings['source_settings']
    projection = source['source_projection']
    objects = projection['objects']
    def original(ref):
        matches = [row['value'] for row in objects if row['ref'] == ref]
        if len(matches) != 1:
            raise ValueError('V2 formation requires one exact original source projection')
        return matches[0]
    profile = original(action_input['formation_profile_ref'])
    terms = original(action_input['terms_ref'])
    offer = original(action_input['offer_ref'])
    bid = original(offer['bid_ref'])
    if (request.get('schema_version') != 'role-contract-invocation.v1'
            or config.get('schema_version') != 'role-contract-host-config.v1'
            or context['run_id'] != case['run_id'] or context['operation_id'] != step['operation_id']
            or context['contract_ref']['id'] != 'CONTRACTOR-A04'
            or context['execution_mode'] != 'offline_fixture' or request.get('execution_path') != 'deterministic'
            or settings['action_id'] != 'CONTRACTOR-A04' or source['action_id'] != 'CONTRACTOR-A04'
            or settings['source_factory'] != 'integration.contractor_formation_fixture_sources:build_sources'
            or settings['source_version'] != 'configured-contractor-formation-fixture-sources.v1'
            or source['organization_snapshot']['run_id'] != case['run_id']
            or settings['macro_version'] != projection['macro_version']
            or any(context[k] != projection[k] for k in ('run_id', 'business_time', 'read_token'))
            or profile['choice'] != choice or profile['offer_ref'] != offer['ref']
            or profile['terms_ref'] != terms['ref'] or profile['authority_ref'] != action_input['authority_ref']
            or origin.get('schema_version') != 'role-contract-fixture-origin.v1'
            or origin.get('origin') != 'synthetic' or origin.get('run_id') != case['run_id']
            or origin.get('case_id') != case['case_id'] or origin.get('action_id') != 'CONTRACTOR-A04'
            or origin.get('expected_result') != {'kind': 'completed', 'choice': choice}
            or origin.get('source_note') != source['source_note']
            or any(row['value'].get('source_kind') != 'synthetic' for row in objects if row['ref']['kind'] == 'Evidence')
            or any(origin['artifact_sha256'].get(path.name) != sha for path, sha in files[:2])):
        raise ValueError('V2 formation changes its original synthetic identity, sources or branch configuration')
    agreement = task_digest({k: v for k, v in terms.items()
        if k not in {'evidence_refs', 'available_at', 'effective_window'}})
    basis = task_digest({'action_input': action_input,
        'objects_without_evidence': [row for row in objects if row['ref']['kind'] != 'Evidence'],
        'source_note': source['source_note']})
    evidence = [row for row in objects if row['ref']['kind'] == 'Evidence']
    if case['case_id'] == 'v2-linked-formation-accept':
        # The same-run fixture preserves original A02 and Owner basis records.
        # Authenticate them against the pinned source artifacts instead of
        # assigning the new agreement basis to every historical Evidence.
        root = Path(__file__).resolve().parents[1]
        original_objects = []
        artifacts = origin.get('source_artifacts', {})
        if not artifacts or settings.get('received_award_inputs') is not None:
            raise ValueError('Independent linked formation requires declared original artifacts, without claimed reception')
        for name, expected_sha in artifacts.items():
            relative = Path(name)
            path = (root / relative).resolve()
            if relative.is_absolute() or not path.is_relative_to(root / 'integration/examples'):
                raise ValueError('Linked formation sources must stay in the repository example directory')
            raw = path.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            if sha != expected_sha:
                raise ValueError('Linked formation changes an original source artifact')
            _, value = parse_input_json(raw)
            original_objects.extend(value.get('settings', {}).get('source_settings', {}).get('source_projection', {}).get('objects', []))
            files.append((path, sha))
        if not terms['evidence_refs']:
            raise ValueError('Linked formation requires its declared agreement basis')
        for row in evidence:
            if row['ref'] in terms['evidence_refs']:
                if row['value']['content_hash'] != basis:
                    raise ValueError('Linked formation changes its current agreement basis')
            elif row not in original_objects:
                raise ValueError('Linked formation changes a retained original Evidence projection')
        if any(original(ref)['content_hash'] != basis for ref in terms['evidence_refs']):
            raise ValueError('Linked formation substitutes its declared agreement evidence')
    elif any(row['value']['content_hash'] != basis for row in evidence):
        raise ValueError('V2 formation changes its declared source evidence digest')
    if (agreement != origin['agreement_sha256'] or profile['reviewed_agreement_sha256'] != agreement
            or basis != origin['basis_sha256']
            or not evidence):
        raise ValueError('V2 formation changes the original agreement or declared source digest')
    expected = ({'offer_ref': offer['ref'], 'terms_ref': terms['ref'],
        'proposed_allocations': bid['draft']['proposed_resources']} if choice == 'accept'
        else {'requirement_changes': profile['requirement_changes']} if choice == 'revise' else {})
    if case['case_id'] == 'v2-linked-formation-accept' and expected != origin['expected_output_refs']:
        raise ValueError('Linked formation substitutes its original declared proposal output')
    return [{'request': deepcopy(request), 'configuration': deepcopy(config),
        'specification': _FORMATION_FACTORY, 'source_files': files, 'expected_refs': deepcopy(expected)}]


def _prepare_publication(case):
    """Bind the original publication preparation; create no package or round."""
    steps = case.get('steps', [])
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V2'
            or case.get('origin') != 'synthetic' or len(steps) != 1 or not isinstance(steps[0], dict)
            or (steps[0].get('action_id'), steps[0].get('expected_kind'), steps[0].get('expected_choice'))
                != ('OWN-A09', 'completed', 'publish_package')
            or steps[0].get('host_factory') != _PUBLICATION_FACTORY):
        raise ValueError('V2 publication requires the independently declared synthetic Owner A09 case')
    step = steps[0]
    request, config, origin, files = _read_pinned_bindings(step)
    context, action_input = request['context'], request['action_input']
    settings = config['settings']
    source = settings['source_settings']
    projection = source['source_projection']
    objects = projection['objects']
    def original(ref):
        matches = [row['value'] for row in objects if row['ref'] == ref]
        if len(matches) != 1:
            raise ValueError('V2 publication requires one exact original source projection')
        return matches[0]
    preparation = action_input['package_context']
    procedure = original(preparation['procedure_ref'])
    profile = original(action_input['evaluation_profile_ref'])
    if (request.get('schema_version') != 'role-contract-invocation.v1'
            or config.get('schema_version') != 'role-contract-host-config.v1'
            or context['run_id'] != case['run_id'] or context['operation_id'] != step['operation_id']
            or context['contract_ref']['id'] != 'OWN-A09'
            or context['execution_mode'] != 'offline_fixture' or request.get('execution_path') != 'deterministic'
            or settings['action_id'] != 'OWN-A09' or source['action_id'] != 'OWN-A09'
            or settings['source_factory'] != 'integration.owner_role_contract_fixture_sources:build_sources'
            or settings['source_version'] != 'configured-owner-fixture-sources.v1'
            or source['organization_snapshot']['run_id'] != case['run_id']
            or settings['macro_version'] != projection['macro_version']
            or any(context[k] != projection[k] for k in ('run_id', 'business_time', 'read_token'))
            or preparation['kind'] != 'preparation' or preparation['scope_ref'] != context['scope']
            or action_input['round_refs'] or action_input['bid_refs']
            or profile['package_ref'] is not None or profile['selected_round_ref'] is not None
            or profile['choice_order'] != ['publish_package'] or profile['procedure_ref'] != procedure['ref']
            or procedure['evaluation_profile_ref'] != profile['ref']
            or profile['owner_organization_id'] != projection['organization_id']
            or any(row['ref']['kind'] in {'ProcurementPackage', 'TenderRound', 'Bid'} for row in objects)
            or origin.get('schema_version') != 'role-contract-fixture-origin.v1'
            or origin.get('origin') != 'synthetic' or origin.get('case_id') != _PUBLICATION_CASE
            or origin.get('run_id') != case['run_id'] or origin.get('action_id') != 'OWN-A09'
            or origin.get('source_note') != source['source_note']
            or origin.get('expected_result') != {'kind': 'completed', 'choice': 'publish_package'}
            or any(origin['artifact_sha256'].get(path.name) != sha for path, sha in files[:2])):
        raise ValueError('V2 publication changes its original preparation, identity or offline source configuration')
    basis = task_digest({'action_input': action_input,
        'objects_without_evidence': [row for row in objects if row['ref']['kind'] != 'Evidence'],
        'source_note': source['source_note']})
    evidence = [row['value'] for row in objects if row['ref']['kind'] == 'Evidence']
    if basis != origin['basis_sha256'] or not evidence or any(
            row['source_kind'] != 'synthetic' or row['content_hash'] != basis for row in evidence):
        raise ValueError('V2 publication changes its declared original synthetic source digest')
    expected = {'package': {'scope_ref': context['scope'],
        'technical_submission_refs': preparation['technical_submission_refs'],
        'quantity_basis_ref': preparation['quantity_basis']['value'], 'procedure_ref': procedure['ref'],
        'requirement_refs': preparation['requirement_refs'],
        'submission_window_ref': procedure['submission_window_ref'], 'evaluation_profile_ref': profile['ref']},
        'bidder_ids': [original(ref)['organization_id'] for ref in profile['invitation_bidder_refs']]}
    if expected != origin['expected_output_refs'] or any(
            ref not in action_input['bidder_refs'] for ref in profile['invitation_bidder_refs']):
        raise ValueError('V2 publication substitutes declared preparation refs or invitation recipients')
    return [{'request': deepcopy(request), 'configuration': deepcopy(config),
        'specification': _PUBLICATION_FACTORY, 'source_files': files, 'expected_refs': deepcopy(expected)}]


def _prepare_bid(case):
    """Bind synthetic A02 inputs; expected price stays outside processor inputs."""
    steps = case.get('steps', [])
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V2'
            or case.get('origin') != 'synthetic' or len(steps) != 1 or not isinstance(steps[0], dict)
            or (steps[0].get('action_id'), steps[0].get('expected_kind'), steps[0].get('expected_choice'))
                != ('CONTRACTOR-A02', 'completed', 'submit_bid')
            or steps[0].get('host_factory') != _FORMATION_FACTORY):
        raise ValueError('V2 bid requires its independently declared synthetic A02 submit case')
    step = steps[0]
    request, config, origin, files = _read_pinned_bindings(step)
    context, action_input = request['context'], request['action_input']
    settings = config['settings']
    source = settings['source_settings']
    projection = source['source_projection']
    objects = projection['objects']
    def original(ref):
        matches = [row['value'] for row in objects if row['ref'] == ref]
        if len(matches) != 1:
            raise ValueError('V2 bid requires one exact original source projection')
        return matches[0]
    profile = original(action_input['pricing_profile_ref'])
    package = original(action_input['package_ref'])
    programme = original(profile['programme_ref'])
    basis = task_digest({'action_input': action_input,
        'objects_without_evidence': [row for row in objects if row['ref']['kind'] != 'Evidence'],
        'source_note': source['source_note']})
    if (request.get('schema_version') != 'role-contract-invocation.v1'
            or config.get('schema_version') != 'role-contract-host-config.v1'
            or context['run_id'] != case['run_id'] or context['operation_id'] != step['operation_id']
            or context['contract_ref']['id'] != 'CONTRACTOR-A02'
            or context['execution_mode'] != 'offline_fixture' or request.get('execution_path') != 'deterministic'
            or settings['action_id'] != 'CONTRACTOR-A02' or source['action_id'] != 'CONTRACTOR-A02'
            or settings['source_factory'] != 'integration.contractor_bid_fixture_sources:build_sources'
            or settings['source_version'] != 'configured-contractor-bid-fixture-sources.v1'
            or source.get('allow_saved_recovery') is not False or source.get('received_tender_inputs')
            or source['organization_snapshot']['run_id'] != case['run_id']
            or settings['macro_version'] != projection['macro_version']
            or any(context[k] != projection[k] for k in ('run_id', 'business_time', 'read_token'))
            or profile['choice'] != 'submit_bid' or profile['package_ref'] != package['ref']
            or package['scope'] != context['scope'] or programme['package_ref'] != package['ref']
            or origin.get('schema_version') != 'role-contract-fixture-origin.v1'
            or origin.get('origin') != 'synthetic' or origin.get('case_id') != _BID_CASE
            or origin.get('run_id') != case['run_id'] or origin.get('action_id') != 'CONTRACTOR-A02'
            or origin.get('expected_result') != {'kind': 'completed', 'choice': 'submit_bid'}
            or origin.get('source_note') != source['source_note'] or origin.get('basis_sha256') != basis
            or original(profile['markup_basis_ref'])['content_hash'] != basis
            or any(row['value'].get('source_kind') != 'synthetic' for row in objects if row['ref']['kind'] == 'Evidence')
            or any(origin['artifact_sha256'].get(path.name) != sha for path, sha in files[:2])):
        raise ValueError('V2 bid changes its declared synthetic identity, sources or native input digest')
    expected_bid = {'package_ref': package['ref'], 'scope_ref': package['scope'],
        'cost_basis_refs': action_input['cost_refs'], 'programme_ref': programme['ref'],
        'terms_ref': profile['terms_ref'], 'exclusion_refs': profile['exclusion_refs'],
        'validity_ref': profile['validity_ref'],
        'proposed_resources': [row for task in programme['tasks'] for row in task['allocations']]}
    price = Decimal(origin['expected_numeric_price'])
    if not price.is_finite() or price < 0:
        raise ValueError('V2 expected bid price must be finite and nonnegative')
    return [{'request': deepcopy(request), 'configuration': deepcopy(config),
        'specification': _FORMATION_FACTORY, 'source_files': files,
        'expected_refs': {'planned_tasks': [{k: v for k, v in task.items() if k != 'quantity_sources'}
            for task in programme['tasks']]}, 'expected_bid_refs': deepcopy(expected_bid),
        'expected_price': str(price), 'expected_currency': profile['currency']}]


def _prepare_evaluation(case):
    """Bind declared evaluation inputs; calculate no ranking during planning."""
    steps = case.get('steps', [])
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V2'
            or case.get('origin') != 'synthetic' or len(steps) != 1 or not isinstance(steps[0], dict)
            or (steps[0].get('action_id'), steps[0].get('expected_kind'), steps[0].get('expected_choice'))
                != ('OWN-A09', 'completed', 'evaluate')
            or steps[0].get('host_factory') != _PUBLICATION_FACTORY):
        raise ValueError('V2 evaluation requires its declared independent synthetic A09 case')
    step = steps[0]
    request, config, origin, files = _read_pinned_bindings(step)
    context, action_input, settings = request['context'], request['action_input'], config['settings']
    source = settings['source_settings']
    projection = source['source_projection']
    objects = projection['objects']
    def original(ref):
        matches = [row['value'] for row in objects if row['ref'] == ref]
        if len(matches) != 1:
            raise ValueError('V2 evaluation requires one exact original projection')
        return matches[0]
    profile = original(action_input['evaluation_profile_ref'])
    package = original(action_input['package_context']['package_ref'])
    round_view = original(profile['selected_round_ref'])
    basis = task_digest({'action_input': action_input,
        'objects_without_evidence': [row for row in objects if row['ref']['kind'] != 'Evidence'],
        'source_note': source['source_note']})
    if (request.get('schema_version') != 'role-contract-invocation.v1'
            or config.get('schema_version') != 'role-contract-host-config.v1'
            or context['run_id'] != case['run_id'] or context['operation_id'] != step['operation_id']
            or context['contract_ref']['id'] != 'OWN-A09' or context['execution_mode'] != 'offline_fixture'
            or request.get('execution_path') != 'deterministic'
            or settings['action_id'] != 'OWN-A09' or source['action_id'] != 'OWN-A09'
            or settings['source_factory'] != 'integration.owner_role_contract_fixture_sources:build_sources'
            or settings['source_version'] != 'configured-owner-fixture-sources.v1'
            or settings.get('received_contractor_bid_inputs') is not None
            or source['organization_snapshot']['run_id'] != case['run_id']
            or settings['macro_version'] != projection['macro_version']
            or any(context[k] != projection[k] for k in ('run_id', 'business_time', 'read_token'))
            or action_input['package_context']['kind'] != 'published' or package['scope'] != context['scope']
            or profile['package_ref'] != package['ref'] or profile['choice_order'] != ['evaluate']
            or profile['tie_policy'] != 'retain_equal_groups_require_explicit_award_choice'
            or round_view['package_ref'] != package['ref'] or round_view['status'] != 'closed_for_bids'
            or round_view['accepts_new_bids'] is not False or round_view['accepts_awards'] is not True
            or action_input['round_refs'] != [round_view['ref']] or action_input['bid_refs'] != round_view['bid_refs']
            or origin.get('schema_version') != 'role-contract-fixture-origin.v1'
            or origin.get('origin') != 'synthetic' or origin.get('case_id') != _EVALUATION_CASE
            or origin.get('run_id') != case['run_id'] or origin.get('action_id') != 'OWN-A09'
            or origin.get('expected_result') != {'kind': 'completed', 'choice': 'evaluate'}
            or origin.get('source_note') != source['source_note'] or origin.get('basis_sha256') != basis
            or any(origin['artifact_sha256'].get(path.name) != sha for path, sha in files[:2])
            or any(row['value'].get('source_kind') != 'synthetic' for row in objects if row['ref']['kind'] == 'Evidence')
            or not any(row['ref']['kind'] == 'Evidence' and row['value']['content_hash'] == basis for row in objects)):
        raise ValueError('V2 evaluation changes its declared identity, comparison input or source digest')
    expected = origin['expected_output_refs']
    ranked, rejected = expected['ranked_bid_refs'], expected['rejected_bid_refs']
    combined = ranked + rejected
    if (len({task_digest(ref) for ref in combined}) != len(combined)
            or {task_digest(ref) for ref in combined} != {task_digest(ref) for ref in action_input['bid_refs']}):
        raise ValueError('V2 evaluation expectations must cover original bids without duplicates')
    return [{'request': deepcopy(request), 'configuration': deepcopy(config),
        'specification': _PUBLICATION_FACTORY, 'source_files': files, 'expected_refs': deepcopy(expected)}]


def _prepare_award(case):
    """Bind the independent Owner acceptance; retain pending party conditions."""
    steps = case.get('steps', [])
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V2'
            or case.get('origin') != 'synthetic' or len(steps) != 1 or not isinstance(steps[0], dict)
            or (steps[0].get('action_id'), steps[0].get('expected_kind'), steps[0].get('expected_choice'))
                != ('OWN-A10', 'completed', 'accept')
            or steps[0].get('host_factory') != _PUBLICATION_FACTORY):
        raise ValueError('V2 award requires its declared independent synthetic A10 acceptance')
    step = steps[0]
    request, config, origin, files = _read_pinned_bindings(step)
    context, action_input, settings = request['context'], request['action_input'], config['settings']
    source = settings['source_settings']
    projection = source['source_projection']
    objects = projection['objects']
    def original(ref):
        matches = [row['value'] for row in objects if row['ref'] == ref]
        if len(matches) != 1:
            raise ValueError('V2 award requires one exact original agreement or commitment projection')
        return matches[0]
    offer, terms = original(action_input['selected_offer_ref']), original(action_input['final_terms_ref'])
    snapshot = original(action_input['commitment_snapshot_ref'])
    profile = original(snapshot['formation_profile_ref'])
    basis = task_digest({'action_input': action_input,
        'objects_without_evidence': [row for row in objects if row['ref']['kind'] != 'Evidence'],
        'source_note': source['source_note']})
    if (request.get('schema_version') != 'role-contract-invocation.v1'
            or config.get('schema_version') != 'role-contract-host-config.v1'
            or context['run_id'] != case['run_id'] or context['operation_id'] != step['operation_id']
            or context['contract_ref']['id'] != 'OWN-A10' or context['execution_mode'] != 'offline_fixture'
            or request.get('execution_path') != 'deterministic'
            or settings['action_id'] != 'OWN-A10' or source['action_id'] != 'OWN-A10'
            or settings['source_factory'] != 'integration.owner_role_contract_fixture_sources:build_sources'
            or settings['source_version'] != 'configured-owner-fixture-sources.v1'
            or settings.get('tender_evaluation_inputs') is not None
            or source['organization_snapshot']['run_id'] != case['run_id']
            or settings['macro_version'] != projection['macro_version']
            or any(context[k] != projection[k] for k in ('run_id', 'business_time', 'read_token'))
            or offer['final_terms_ref'] != terms['ref'] or terms['offer_ref'] != offer['ref']
            or offer['round_ref'] != action_input['round_ref'] or terms['round_ref'] != action_input['round_ref']
            or terms['scope'] != context['scope'] or snapshot['as_of'] != context['business_time']
            or profile['choice_order'] != ['accept'] or profile['offer_ref'] != offer['ref']
            or profile['terms_ref'] != terms['ref'] or profile['allow_owner_acceptance_pending_other_parties'] is not True
            or action_input['party_acceptance_refs'] or not profile['pending_party_condition_refs']
            or any(original(ref)['kind'] != 'counterparty_acceptance' for ref in profile['pending_party_condition_refs'])
            or origin.get('schema_version') != 'role-contract-fixture-origin.v1'
            or origin.get('origin') != 'synthetic' or origin.get('case_id') != _AWARD_CASE
            or origin.get('run_id') != case['run_id'] or origin.get('action_id') != 'OWN-A10'
            or origin.get('expected_result') != {'kind': 'completed', 'choice': 'accept'}
            or origin.get('source_note') != source['source_note'] or origin.get('basis_sha256') != basis
            or any(origin['artifact_sha256'].get(path.name) != sha for path, sha in files[:2])
            or any(row['value'].get('source_kind') != 'synthetic' for row in objects if row['ref']['kind'] == 'Evidence')
            or not any(row['ref']['kind'] == 'Evidence' and row['value']['content_hash'] == basis for row in objects)):
        raise ValueError('V2 award changes original identity, agreement, pending acceptance or source digest')
    conditions = [*terms['condition_refs']]
    if snapshot['counterparty_capacity_condition_ref'] is not None:
        conditions.append(snapshot['counterparty_capacity_condition_ref'])
    conditions.extend(profile['pending_party_condition_refs'])
    expected = {'offer_ref': offer['ref'], 'terms_ref': terms['ref'],
        'condition_refs': list({task_digest(ref): ref for ref in conditions}.values())}
    if expected != origin['expected_output_refs']:
        raise ValueError('V2 award substitutes original expected agreement or retained conditions')
    return [{'request': deepcopy(request), 'configuration': deepcopy(config),
        'specification': _PUBLICATION_FACTORY, 'source_files': files, 'expected_refs': deepcopy(expected)}]


def _check_durable_result(result, step, *, action_id, role, result_table, require_source_reading=True):
    """Keep original worker task/output/audit provenance with the observed branch."""
    evidence = result.get('execution_evidence', {})
    task, audit, identity = evidence.get('task', {}), evidence.get('saved_audit', {}), evidence.get('identity', {})
    context = step['request']['context']
    observed = result['result']
    result_sha = task_digest(observed)
    if (result.get('action_id') != action_id or result.get('run_id') != context['run_id']
            or result.get('source_mode') != 'fixture' or evidence.get('result_table') != result_table
            or task.get('identity') != identity or task.get('state') != 'output_formed'
            or task.get('output') != observed or task.get('output_sha256') != result_sha
            or any(identity.get(k) != v for k, v in {'run_id': context['run_id'], 'role': role,
                'action_id': action_id, 'purpose': 'action', 'request_id': context['operation_id'],
                'context_sha256': task_digest(context), 'input_sha256': task_digest(step['request']['action_input'])}.items())
            or result.get('audit') != [audit] or audit.get('reading', {}).get('source_mode') != 'fixture'
            or (require_source_reading and audit.get('reading', {}).get('sha256') != evidence.get('source_reading_sha256'))
            or any(audit.get(k) != v for k, v in {'run_id': context['run_id'], 'action_id': action_id,
                'operation_id': context['operation_id'], 'input_sha256': identity.get('input_sha256'),
                'result_sha256': result_sha, 'result_kind': 'completed'}.items())
            or any(not isinstance(evidence.get(k), str) or len(evidence[k]) != 64
                or any(c not in '0123456789abcdef' for c in evidence[k])
                for k in (('record_sha256', 'source_reading_sha256') if require_source_reading else ('record_sha256',)))):
        raise ValueError('V2 decision lacks matching original durable task, result and audit evidence')
    reading_sha = audit.get('reading', {}).get('sha256')
    if (not isinstance(reading_sha, str) or len(reading_sha) != 64
            or any(c not in '0123456789abcdef' for c in reading_sha)):
        raise ValueError('V2 decision lacks its original reading audit digest')
    if action_id == 'CONTRACTOR-A04' and observed['payload']['choice'] == 'reject' and any(observed['payload'].get(k)
            for k in ('offer_ref', 'terms_ref', 'proposed_allocations', 'requirement_changes')):
        raise ValueError('V2 rejection must not retain acceptance, allocation or revision output')


def _prepare_configured(case):
    """Read generated bindings only; the original source hosts prove linkage later."""
    route = _CONFIGURED_CASES[case['case_id']]
    declared = case.get('steps', [])
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V2'
            or case.get('origin') != 'synthetic' or not isinstance(case.get('run_id'), str) or not case['run_id'].strip()
            or not isinstance(case.get('remaining_requirements'), list)
            or len(declared) != 1 or not isinstance(declared[0], dict)):
        raise ValueError('Configured V2 continuation requires one explicitly declared synthetic step')
    step = declared[0]
    if (step.get('action_id') != route['action'] or step.get('expected_kind') != 'completed'
            or step.get('expected_choice') not in route['choices'] or step.get('host_factory') != route['factory']):
        raise ValueError('Configured V2 continuation changes its original action, host or branch')
    root = Path(__file__).resolve().parents[1]
    files, values = [], []
    for label in ('invocation', 'configuration', 'preparation'):
        relative = Path(step[label + '_path'])
        path = (root / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(root / 'output/integration'):
            raise ValueError('Configured V2 bindings must be generated repository integration artifacts')
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if sha != step[label + '_file_sha256']:
            raise ValueError('Configured V2 binding changes its declared file SHA')
        _, value = parse_input_json(raw)
        files.append((path, sha))
        values.append(value)
    request, config, preparation = values
    context, settings = request['context'], config['settings']
    selection = settings[route['selection']]['selections'][context['operation_id']]
    if (len({path.parent for path, _ in files}) != 1
            or request.get('schema_version') != 'role-contract-invocation.v1'
            or config.get('schema_version') != 'role-contract-host-config.v1'
            or context['run_id'] != case['run_id'] or context['contract_ref']['id'] != route['action']
            or context['operation_id'] != step['operation_id'] or context['execution_mode'] != 'offline_fixture'
            or request.get('execution_path') not in {None, 'deterministic'}
            or settings['action_id'] != route['action']
            or settings['source_factory'] != 'integration.' + route['source_module'] + '_fixture_sources:build_sources'
            or settings['source_version'] != route['source_version']
            or preparation.get('schema_version') != route['preparation_schema']
            or preparation.get('status') != 'configuration_prepared_history_read_pending'
            or preparation.get('origin') != 'synthetic' or preparation.get('factory') != route['factory']
            or preparation.get('invocation_sha256') != task_digest(request)
            or preparation.get('configuration_sha256') != task_digest(config)
            or not isinstance(step.get('expected_output', {}), dict)):
        raise ValueError('Configured V2 continuation changes original preparation, identity or reception binding')
    selections = selection['bids'] if route['selection'] == 'received_contractor_bid_inputs' else [selection]
    if not selections:
        raise ValueError('Configured V2 continuation lacks explicit original source selections')
    upstream_files = preparation.get('source_execution_files', [])
    if not isinstance(upstream_files, list):
        raise ValueError('Configured V2 upstream file bindings must be explicit records')
    for binding in upstream_files:
        if not isinstance(binding, dict) or set(binding) != {'path', 'file_sha256'}:
            raise ValueError('Configured V2 upstream file requires its original raw SHA')
        relative = Path(binding['path'])
        path = (root / relative).resolve()
        if (relative.is_absolute() or not any(path.is_relative_to(root / directory)
                for directory in ('integration/examples', 'output/integration'))
                or hashlib.sha256(path.read_bytes()).hexdigest() != binding['file_sha256']):
            raise ValueError('Configured V2 upstream execution file changed or escaped its source directories')
        files.append((path, binding['file_sha256']))
    return [{'request': deepcopy(request), 'configuration': deepcopy(config),
        'specification': route['factory'], 'source_files': files,
        'expected_refs': deepcopy(step.get('expected_output', {})), 'linked_selections': deepcopy(selections)}]


def _check_configured_result(result, step, route):
    _check_durable_result(result, step, action_id=route['action'], role=route['role'],
        result_table=route['table'], require_source_reading=route['action'] != 'CONTRACTOR-A02')
    provenance = result.get('execution_evidence', {}).get(route['provenance'])
    if not isinstance(provenance, dict):
        raise ValueError('Configured V2 result lacks original reception provenance')
    observed = provenance.get('bids', []) if route['selection'] == 'received_contractor_bid_inputs' else [provenance]
    if not isinstance(observed, list) or len(observed) != len(step['linked_selections']):
        raise ValueError('Configured V2 result changes the declared source selection coverage')
    for selected, relation in zip(step['linked_selections'], observed):
        identity = relation.get('source_identity', {})
        if (identity.get('run_id') != step['request']['context']['run_id']
                or task_digest([identity.get(k) for k in ('run_id', 'organization_id', 'purpose', 'request_id')])
                    != selected['source_task_sha256']
                or any(relation.get(key) != value for key, value in selected.items() if key != 'source_task_sha256')):
            raise ValueError('Configured V2 result substitutes original source task or native reception references')


def _prepare(path):
    """Copy declared bindings only; planning constructs no host or registry."""
    path = Path(path).resolve()
    raw = path.read_bytes()
    case = json.loads(raw)
    if case.get('case_id') in _CONFIGURED_CASES:
        return path, hashlib.sha256(raw).hexdigest(), case, _prepare_configured(case)
    if case.get('case_id') in _FORMATION_CASES:
        return path, hashlib.sha256(raw).hexdigest(), case, _prepare_formation(case)
    if case.get('case_id') == _PUBLICATION_CASE:
        return path, hashlib.sha256(raw).hexdigest(), case, _prepare_publication(case)
    if case.get('case_id') == _BID_CASE:
        return path, hashlib.sha256(raw).hexdigest(), case, _prepare_bid(case)
    if case.get('case_id') == _EVALUATION_CASE:
        return path, hashlib.sha256(raw).hexdigest(), case, _prepare_evaluation(case)
    if case.get('case_id') == _AWARD_CASE:
        return path, hashlib.sha256(raw).hexdigest(), case, _prepare_award(case)
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V2'
            or case.get('origin') != 'synthetic' or not isinstance(case.get('run_id'), str)
            or not case['run_id'].strip()
            or [(s.get('action_id'), s.get('expected_kind'), s.get('expected_choice'))
                for s in case.get('steps', [])] != [('ARCHITECT-A02', 'completed', 'accept'), ('OWN-A04', 'completed', 'accept')]):
        raise ValueError('V2 requires explicit independent architect intake then owner selection inputs')
    prepared = []
    for step in case['steps']:
        fixture, binding = step['input_fixture'], step['offline_binding']
        request = deepcopy(binding['invocation'])
        request['action_input'] = deepcopy(fixture['input'])
        context = request['context']
        scope = fixture['input']['scope' if step['action_id'] == 'ARCHITECT-A02' else 'scope_ref']
        projection = deepcopy(binding['source_projection_envelope'])
        projection['objects'] = deepcopy(fixture['objects'] + binding['supplemental_objects'])
        snapshot = binding['organization_snapshot']
        if (fixture['source_kind'] != 'synthetic' or context['run_id'] != case['run_id']
                or context['execution_mode'] != 'offline_fixture' or request['execution_path'] != 'deterministic'
                or context['contract_ref']['id'] != step['action_id']
                or context['operation_id'] != step['operation_id'] or context['scope'] != scope
                or context['business_time'] != fixture['business_time'] or context['actor_id'] != fixture['actor_id']
                or binding['schema_factory'] != _SCHEMAS[step['action_id']]
                or snapshot['run_id'] != case['run_id']
                or context['visible_refs'] != [o['ref'] for o in projection['objects']]
                or any(projection[k] != context[k] for k in ('run_id', 'read_token', 'business_time'))
                or projection['organization_id'] != fixture['organization_id']):
            raise ValueError('V2 binding changes its declared action, identity, scope or authorized source')
        prepared.append({'request': request, 'configuration': {
            'schema_version': 'role-contract-host-config.v1', 'host_id': step['step_id'], 'version': '1',
            'settings': {'action_id': step['action_id'], 'schema_factory': binding['schema_factory'],
                'source_note': binding['source_note'], 'organization_snapshot': deepcopy(snapshot),
                'source_projection': projection}}})
    first, second = [s['request']['context'] for s in prepared]
    if (first['scope'] != second['scope'] or first['business_time']['clock_ref'] != second['business_time']['clock_ref']
            or first['business_time']['offset'] >= second['business_time']['offset']
            or any(first[k] == second[k] for k in ('actor_id', 'operation_id', 'task_ref', 'read_token'))):
        raise ValueError('V2 requires separately identified actors and ordered same-scope decisions')
    mapping = case['terms_mapping']
    architect, owner = [s['input_fixture'] for s in case['steps']]
    def original(fixture, ref):
        rows = [o['value'] for o in fixture['objects'] if o['ref'] == ref]
        if len(rows) != 1:
            raise ValueError('V2 mapping requires one exact original projection')
        return rows[0]
    offered = original(owner, mapping['owner_offer_ref'])
    contract = original(owner, mapping['owner_contract_terms_ref'])
    service = original(architect, mapping['architect_service_terms_ref'])
    if (owner['input']['candidates'] != [offered['ref']] or offered['terms_ref'] != contract['ref']
            or architect['input']['terms_ref'] != service['ref'] or service['scope'] != first['scope']
            or mapping['scope'] != first['scope'] or contract['scope_ref'] != first['scope']
            or any(mapping[k] != contract[k] for k in ('fee', 'requested_uses', 'responsibility_codes',
                'deliverable_refs', 'condition_refs', 'authority_limits'))
            or any(service[k] != contract[k] for k in ('fee', 'requested_uses', 'responsibility_codes'))
            or contract['service_codes'] != {'state': 'known', 'value': [service['service_code']['value']]}
            or service['deliverable_requirement_refs'] != contract['deliverable_refs']
            or service['desired_window'] != {'state': 'known', 'value': original(owner, contract['window_ref'])}
            or mapping['desired_window'] != service['desired_window']['value']):
        raise ValueError('V2 declared mapping changes the original offer, scope or single-service terms')
    return path, hashlib.sha256(raw).hexdigest(), case, prepared


def run_v2_offline(*, case_path, output_directory, execute=False):
    """Save local decisions only; original formal reception and effectiveness remain separate."""
    if type(execute) is not bool:
        raise ValueError('V2 execution requires an explicit boolean selection')
    path, source_sha, case, steps = _prepare(case_path)
    def recheck_inputs():
        for file, sha in [(path, source_sha)] + [item for step in steps for item in step.get('source_files', [])]:
            if hashlib.sha256(file.read_bytes()).hexdigest() != sha:
                raise ValueError('V2 case or original source binding changed during execution')
    recheck_inputs()
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v2-offline-plan.v1', 'origin': 'synthetic',
        'run_id': case['run_id'], 'case_path': str(path), 'case_sha256': source_sha,
        'factory': steps[0].get('specification', _FACTORY), 'mode': 'execute_offline' if execute else 'plan_only',
        'steps': [{'action_id': s['request']['context']['contract_ref']['id'],
            'request_sha256': task_digest(s['request']), 'configuration_sha256': task_digest(s['configuration']),
            'expected_kind': case['steps'][index]['expected_kind'],
            'expected_choice': case['steps'][index]['expected_choice']} for index, s in enumerate(steps)],
        'terms_mapping': deepcopy(case.get('terms_mapping', {})), 'dependent_steps': deepcopy(case.get('dependent_steps', [])),
        'limitations': 'Independent synthetic local decisions; no actual reception, formal appointment, signature, resource effect or complete V2 acceptance.'}
    if (case.get('case_id') in _FORMATION_CASES
            or case.get('case_id') in (_PUBLICATION_CASE, _BID_CASE, _EVALUATION_CASE, _AWARD_CASE)
            or case.get('case_id') in _CONFIGURED_CASES):
        plan['case_id'] = case['case_id']
        plan['source_files'] = [{'path': str(file), 'sha256': sha} for file, sha in steps[0]['source_files']]
    if case.get('case_id') in {_BID_CASE, 'v2-received-tender-bid'}:
        plan['reading_evidence'] = 'audit_digest_only'
    atomic_json(directory / 'plan.json', plan)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v2-offline-attempt.v1', 'case_sha256': source_sha,
        'status': 'started', 'completed_steps': []}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        formation = case.get('case_id') in _FORMATION_CASES
        publication = case.get('case_id') == _PUBLICATION_CASE
        evaluation = case.get('case_id') == _EVALUATION_CASE
        award = case.get('case_id') == _AWARD_CASE
        bid = case.get('case_id') == _BID_CASE
        configured = _CONFIGURED_CASES.get(case.get('case_id'))
        if configured:
            if configured['factory'] == _FORMATION_FACTORY:
                from integration.contractor_role_contract_host import build_role_host as executor
            else:
                from integration.owner_role_contract_host import build_role_host as executor
            expected_refs = [steps[0]['expected_refs']]
        elif formation or bid:
            from integration.contractor_role_contract_host import build_role_host as executor
            expected_refs = [steps[0]['expected_refs']]
        elif publication or evaluation or award:
            from integration.owner_role_contract_host import build_role_host as executor
            expected_refs = [steps[0]['expected_refs']]
        else:
            executor = build_role_host
            mapping = case['terms_mapping']
            expected_refs = [{'accepted_terms_ref': mapping['architect_service_terms_ref']},
                {'offer_ref': mapping['owner_offer_ref'], 'terms_ref': mapping['owner_contract_terms_ref']}]
        for index, step in enumerate(steps):
            recheck_inputs()
            result = run_role_contract(request=step['request'], configuration=step['configuration'],
                factory=executor, specification=step.get('specification', _FACTORY),
                output_directory=directory / ('step-' + str(index + 1)), offline=True)
            observed = result['result']
            payload = observed.get('payload', {})
            if (observed['kind'] != plan['steps'][index]['expected_kind']
                    or payload.get('choice') != plan['steps'][index]['expected_choice']
                    or any(payload.get(k) != v for k, v in expected_refs[index].items())):
                raise ValueError('V2 original action differs from the declared branch or original output references')
            if configured:
                _check_configured_result(result, step, configured)
            elif formation:
                _check_durable_result(result, step, action_id='CONTRACTOR-A04',
                    role='Contractor', result_table='contractor_formation_results')
            elif publication or evaluation:
                _check_durable_result(result, step, action_id='OWN-A09',
                    role='Owner', result_table='owner_tender_results')
            elif award:
                _check_durable_result(result, step, action_id='OWN-A10',
                    role='Owner', result_table='owner_award_results')
            elif bid:
                offered = payload.get('bid', {})
                price = offered.get('price', {})
                if (any(offered.get(k) != v for k, v in step['expected_bid_refs'].items())
                        or price.get('currency') != step['expected_currency']
                        or Decimal(price.get('value', 'NaN')) != Decimal(step['expected_price'])):
                    raise ValueError('V2 bid changes original proposal refs or calculated price')
                _check_durable_result(result, step, action_id='CONTRACTOR-A02',
                    role='Contractor', result_table='contractor_bid_results', require_source_reading=False)
            attempt['completed_steps'].append({'action_id': plan['steps'][index]['action_id'],
                'result_path': 'step-' + str(index + 1) + '/result.json', 'result_sha256': task_digest(result)})
            atomic_json(directory / 'attempt.json', attempt)
        recheck_inputs()
        summary = {**plan, 'status': 'independent_local_decisions_completed',
            'results': deepcopy(attempt['completed_steps']), 'remaining_requirements': deepcopy(case['remaining_requirements'])}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'completed'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed',
            'error_type': type(exc).__name__, 'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path,
        default=Path('tests/fixtures/roles/lifecycle_v2_commission_inputs.v1.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute-offline', action='store_true')
    args = parser.parse_args()
    report = run_v2_offline(case_path=args.case, output_directory=args.output, execute=args.execute_offline)
    print(json.dumps({'mode': report['mode'], 'output': str(args.output),
        'status': report.get('status', 'planned_not_executed')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
