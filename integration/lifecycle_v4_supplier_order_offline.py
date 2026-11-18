"""Plan or explicitly evaluate one synthetic V4 Supplier order acceptance draft."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from integration.supplier_order_fixture_sources import SupplierOrderFixtureSettings
from integration.supplier_quote_handoff import supplier_quote_handoff_schemas
from integration.supplier_role_contract_host import SupplierRoleContractSettings, build_role_host
from src.actions.contracts.common import Reference
from src.actions.contracts.supplier_order_objects import (
    FormationOfferView, OrderProposalView, FormationProfileView, FormationPlanView,
    FormationAcceptanceView, order_agreement_digest,
)
from src.coordination.tasks import task_digest


_FACTORY = 'integration.supplier_role_contract_host:build_role_host'
_SOURCES = 'integration.supplier_order_fixture_sources:build_sources'


def _prepare(case_path):
    path = Path(case_path).resolve()
    raw = path.read_bytes()
    _, case = parse_input_json(raw)
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V4'
            or case.get('origin') != 'synthetic' or not isinstance(case.get('steps'), list) or len(case['steps']) != 1):
        raise ValueError('V4 order acceptance requires one explicitly synthetic original input')
    step = case['steps'][0]
    request = RoleContractInvocation.model_validate(step['request'])
    configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    settings = SupplierRoleContractSettings.model_validate(configuration.settings)
    source = SupplierOrderFixtureSettings.model_validate(settings.source_settings)
    context, projection = request.context, source.source_projection
    if (step.get('action_id') != 'SUPPLIER-A04' or step.get('host') != _FACTORY
            or step.get('expected_kind') != 'completed' or step.get('expected_choice') != 'accept'
            or context.contract_ref.id != 'SUPPLIER-A04' or context.operation_id != step['operation_id']
            or context.run_id != case['run_id'] or context.execution_mode != 'offline_fixture'
            or request.execution_path != 'deterministic' or settings.action_id != 'SUPPLIER-A04'
            or settings.source_factory != _SOURCES or settings.source_version != 'configured-supplier-order-fixture-sources.v1'
            or source.action_id != 'SUPPLIER-A04' or source.allow_saved_recovery
            or any(getattr(settings, name) is not None for name in (
                'feedback_inputs', 'planning_inputs', 'execution_inputs', 'quality_inputs', 'logistics_inputs'))
            or source.organization_snapshot.run_id != case['run_id']
            or any(projection.get(key) != context.model_dump(mode='json')[key]
                for key in ('run_id', 'read_token', 'business_time'))
            or projection.get('macro_version') != settings.macro_version):
        raise ValueError('V4 order acceptance alters original offline action, source factory, run or snapshot')
    identities = [value for organization in source.organization_snapshot.organizations for value in organization.source_ids]
    if len(set(identities)) != len(identities):
        raise ValueError('V4 order acceptance aliases independent organization source identities')
    rows = projection['objects']
    originals = {Reference.model_validate(row['ref']).key(): row['value'] for row in rows}
    if len(originals) != len(rows) or context.visible_refs != [Reference.model_validate(row['ref']) for row in rows]:
        raise ValueError('V4 order acceptance alters complete original visible projection identities')
    schemas = supplier_quote_handoff_schemas()
    for row in rows:
        schemas.validate_projection(Reference.model_validate(row['ref']), row['value'])
        if row['ref']['kind'] == 'Evidence' and row['value']['source_kind'] != 'synthetic':
            raise ValueError('V4 offline order evidence must declare its synthetic origin')
    inputs = request.action_input
    offer = FormationOfferView.model_validate(originals[Reference.model_validate(inputs['offer_ref']).key()])
    proposal = OrderProposalView.model_validate(originals[Reference.model_validate(inputs['order_proposal_ref']).key()])
    profile = FormationProfileView.model_validate(originals[Reference.model_validate(inputs['formation_profile_ref']).key()])
    if (offer.status != 'active' or proposal.status != 'active' or proposal.offer_ref != offer.ref
            or offer.ref.model_dump(mode='json') != step['expected_offer_ref']
            or proposal.terms_ref != offer.terms_ref or offer.terms_ref.model_dump(mode='json') != step['expected_terms_ref']
            or offer.supplier_organization_id != projection['organization_id']
            or proposal.supplier_organization_id != offer.supplier_organization_id
            or proposal.buyer_id != offer.buyer_id or proposal.payer_id != offer.payer_id
            or offer.scope != context.scope or proposal.scope != context.scope
            or proposal.recipient_actor_id != context.actor_id
            or profile.organization_id != offer.supplier_organization_id or profile.offer_ref != offer.ref
            or profile.order_proposal_ref != proposal.ref or profile.policy != 'evaluate' or profile.full_plan_ref is None):
        raise ValueError('V4 order acceptance requires its original active offer, proposal and full-order policy')
    plan = FormationPlanView.model_validate(originals[profile.full_plan_ref.key()])
    deliveries = [line.delivery.model_dump(mode='json') for line in plan.lines]
    if (plan.organization_id != offer.supplier_organization_id or plan.offer_ref != offer.ref
            or plan.order_proposal_ref != proposal.ref or plan.purpose != 'full_order'
            or [line.order_line_key for line in plan.lines] != [line.local_key for line in proposal.lines]
            or deliveries != [line.delivery.model_dump(mode='json') for line in proposal.lines]
            or deliveries != step['expected_accepted_lines']):
        raise ValueError('V4 order acceptance changes its original complete accepted delivery lines')
    refs = [Reference.model_validate(value) for value in inputs['counterpart_acceptance_refs']]
    if len(set(refs)) != len(refs) or inputs['counterpart_acceptance_refs'] != step['expected_counterpart_acceptance_refs']:
        raise ValueError('V4 order acceptance changes its independently supplied acceptance identities')
    parties = []
    agreement_sha256 = order_agreement_digest(proposal)
    for ref in refs:
        acceptance = FormationAcceptanceView.model_validate(originals[ref.key()])
        if (acceptance.run_id != case['run_id'] or acceptance.proposal_ref != proposal.ref
                or acceptance.offer_ref != offer.ref or acceptance.terms_ref != offer.terms_ref
                or acceptance.scope != context.scope or acceptance.choice != 'accept' or acceptance.status != 'active'
                or acceptance.agreement_sha256 != agreement_sha256
                or acceptance.action_id not in profile.counterpart_action_ids
                or acceptance.party_id == offer.supplier_organization_id):
            raise ValueError('V4 order acceptance lacks an independent acceptance of this exact agreement')
        parties.append(acceptance.party_id)
    if len(set(parties)) != len(parties) or set(parties) != {offer.buyer_id, offer.payer_id}:
        raise ValueError('V4 order acceptance requires distinct buyer and payer confirmations')
    return path, hashlib.sha256(raw).hexdigest(), deepcopy(case), request.model_dump(mode='json'), configuration.model_dump(mode='json')


def run_v4_supplier_order_offline(*, case_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V4 order acceptance execution selection must be an explicit boolean')
    path, digest, case, request, configuration = _prepare(case_path)
    step = case['steps'][0]
    directory = Path(output_directory).resolve()
    journal = Path(configuration['settings']['source_settings']['journal_path']).resolve()
    if execute and (directory != Path(step['output_directory']).resolve() or journal != directory / 'journal.sqlite'):
        raise ValueError('V4 execution requires the declared new output directory and its exact synthetic journal')
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v4-supplier-order-plan.v1', 'scenario_id': 'V4', 'origin': 'synthetic',
        'run_id': case['run_id'], 'action_id': 'SUPPLIER-A04', 'factory': _FACTORY,
        'mode': 'execute_offline' if execute else 'plan_only', 'input': {'path': str(path), 'sha256': digest},
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(configuration),
        'expected_offer_ref': deepcopy(step['expected_offer_ref']),
        'expected_terms_ref': deepcopy(step['expected_terms_ref']),
        'expected_accepted_lines': deepcopy(step['expected_accepted_lines']),
        'source_counterpart_acceptance_refs': deepcopy(step['expected_counterpart_acceptance_refs']),
        'limitations': ['Isolated synthetic order draft with explicitly sourced independent buyer and payer acceptances.',
            'No formal order formation, stock/capacity/cash reservation, native execution or connected V4 delivery chain proven.']}
    for label, value in (('input', case), ('request', request), ('configuration', configuration), ('plan', plan)):
        atomic_json(directory / (label + '.json'), value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v4-supplier-order-attempt.v1', 'status': 'started',
        'input_sha256': digest, 'automatic_retry': False}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest or journal.exists():
            raise ValueError('V4 input changed or original synthetic journal already exists; no replay')
        output = run_role_contract(request=request, configuration=configuration, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'supplier', offline=True)
        result, evidence = output['result'], output['execution_evidence']
        identity, task, audit = evidence['identity'], evidence['task'], evidence['saved_audit']
        expected_identity = {'run_id': case['run_id'],
            'organization_id': configuration['settings']['source_settings']['source_projection']['organization_id'],
            'role': 'Supplier', 'action_id': 'SUPPLIER-A04', 'request_id': request['context']['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        if (output['source_mode'] != 'fixture' or output['action_id'] != 'SUPPLIER-A04'
                or output['macro_execution'] != 'not_performed' or evidence['model_host'] is not None
                or evidence['result_table'] != 'supplier_order_results' or task['identity'] != identity
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or output['audit'] != [audit] or audit['result_sha256'] != task_digest(result)
                or result['kind'] != 'completed' or result['payload']['choice'] != 'accept'
                or result['payload']['offer_ref'] != step['expected_offer_ref']
                or result['payload']['terms_ref'] != step['expected_terms_ref']
                or result['payload']['accepted_lines'] != step['expected_accepted_lines']
                or task['state'] != 'output_formed' or task['output'] != result
                or task['output_sha256'] != task_digest(result) or task['submission'] is not None or task['receipt'] is not None):
            raise ValueError('V4 order acceptance did not preserve its exact accepted order draft and original result without transport')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('V4 original Supplier order input changed during evaluation')
        summary = {**plan, 'mode': 'executed_offline', 'identity': deepcopy(identity),
            'record_sha256': evidence['record_sha256'], 'result': deepcopy(result), 'real_model_calls': 0}
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'finished'})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    print(run_v4_supplier_order_offline(case_path=args.input, output_directory=args.output, execute=args.execute)['mode'])


if __name__ == '__main__':
    main()
