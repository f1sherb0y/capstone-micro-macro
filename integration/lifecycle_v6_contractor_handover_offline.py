"""Plan or explicitly evaluate one synthetic V6 pending-verification handover."""
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path

from integration.contractor_closeout_fixture_sources import ContractorCloseoutFixtureSettings
from integration.contractor_role_contract_host import ContractorRoleContractSettings, build_role_host
from integration.role_contract_host import RoleContractHostConfiguration, RoleContractInvocation, run_role_contract
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.actions.contracts.common import Reference
from src.actions.contracts.contractor_closeout_objects import (
    ContractorCloseoutContractView, ContractorHandoverProfileView, ContractorHandoverProcedureView,
    ContractorCloseoutIssueView, ContractorCloseoutRequirementView,
    ContractorContinuingResponsibilityView, contractor_closeout_schemas,
)
from src.coordination.tasks import task_digest


_FACTORY = 'integration.contractor_role_contract_host:build_role_host'
_SOURCES = 'integration.contractor_closeout_fixture_sources:build_sources'


def _prepare(case_path):
    path = Path(case_path).resolve()
    raw = path.read_bytes()
    _, case = parse_input_json(raw)
    if (case.get('schema_version') != 'lifecycle-input-case.v1' or case.get('scenario_id') != 'V6'
            or case.get('origin') != 'synthetic' or not isinstance(case.get('steps'), list) or len(case['steps']) != 1):
        raise ValueError('V6 Contractor handover requires one explicitly synthetic original input')
    step = case['steps'][0]
    request = RoleContractInvocation.model_validate(step['request'])
    configuration = RoleContractHostConfiguration.model_validate(step['configuration'])
    settings = ContractorRoleContractSettings.model_validate(configuration.settings)
    source = ContractorCloseoutFixtureSettings.model_validate(settings.source_settings)
    context, projection = request.context, source.source_projection
    if (step.get('action_id') != 'CONTRACTOR-A11' or step.get('host') != _FACTORY
            or step.get('expected_kind') != 'completed' or step.get('expected_choice') != 'submit_handover'
            or context.contract_ref.id != 'CONTRACTOR-A11' or context.operation_id != step['operation_id']
            or context.run_id != case['run_id'] or context.execution_mode != 'offline_fixture'
            or request.execution_path != 'deterministic' or settings.action_id != 'CONTRACTOR-A11'
            or settings.source_factory != _SOURCES
            or settings.source_version != 'configured-contractor-closeout-fixture-sources.v1'
            or source.action_id != 'CONTRACTOR-A11' or source.allow_saved_recovery
            or any(getattr(settings, name) is not None for name in (
                'feedback_inputs', 'received_material_inputs', 'received_payment_inputs',
                'received_award_inputs', 'received_tender_inputs', 'received_permit_inputs'))
            or source.organization_snapshot.run_id != case['run_id']
            or any(projection.get(key) != context.model_dump(mode='json')[key]
                for key in ('run_id', 'read_token', 'business_time'))
            or projection.get('macro_version') != settings.macro_version):
        raise ValueError('V6 handover changes original offline action, source factory, run or snapshot')
    rows = projection['objects']
    originals = {Reference.model_validate(row['ref']).key(): row['value'] for row in rows}
    if len(originals) != len(rows) or context.visible_refs != [Reference.model_validate(row['ref']) for row in rows]:
        raise ValueError('V6 handover changes complete original visible projection identities')
    schemas = contractor_closeout_schemas()
    for row in rows:
        schemas.validate_projection(Reference.model_validate(row['ref']), row['value'])
        if row['ref']['kind'] == 'Evidence' and row['value']['source_kind'] != 'synthetic':
            raise ValueError('V6 offline handover evidence must declare its synthetic origin')

    def original(reference, schema):
        return schema.model_validate(originals[reference.key()])

    def declared(values):
        references = [Reference.model_validate(value) for value in values]
        if len(set(references)) != len(references):
            raise ValueError('V6 handover repeats original source identities')
        return references

    inputs = request.action_input
    contract = original(Reference.model_validate(inputs['contract_ref']), ContractorCloseoutContractView)
    profile = original(Reference.model_validate(inputs['handover_profile_ref']), ContractorHandoverProfileView)
    procedure = original(profile.procedure_ref, ContractorHandoverProcedureView)
    if (inputs['scope_ref'] != context.scope.model_dump(mode='json')
            or profile.choice != 'submit_handover' or profile.contract_ref != contract.ref
            or contract.contractor_id != projection['organization_id']
            or profile.organization_id != contract.contractor_id or profile.scope != context.scope
            or profile.actor_id != context.actor_id or profile.function_ref != context.function_ref
            or profile.authority_ref not in context.authorization_refs
            or contract.coverage != 'complete' or contract.as_of != context.business_time
            or procedure.contract_ref != contract.ref or not procedure.allow_pending_handover
            or not procedure.require_independent_verification
            or 'submit_handover' not in procedure.permitted_choices
            or procedure.permitted.model_dump() != {'state': 'known', 'value': True}
            or contract.verification_refs or inputs['verification_refs']):
        raise ValueError('V6 handover requires its original explicitly permitted pending-independent-check input')
    for supplied, field in (('as_built_refs', 'as_built_refs'), ('verification_refs', 'verification_refs'),
            ('defect_refs', 'defect_refs'), ('settlement_components', 'settlement_component_refs')):
        if set(declared(inputs[supplied])) != set(getattr(contract, field)):
            raise ValueError('V6 handover omits original contract history: ' + field)
    if (not contract.as_built_refs or contract.as_built_refs != declared(step['expected_as_built_refs'])
            or not profile.remaining_issue_refs
            or profile.remaining_issue_refs != declared(step['expected_remaining_issue_refs'])):
        raise ValueError('V6 handover changes original actual configurations or remaining issues')
    unresolved, covered = set(), set()
    for reference in contract.issue_refs:
        issue = original(reference, ContractorCloseoutIssueView)
        if issue.contract_ref != contract.ref:
            raise ValueError('V6 handover issue belongs to another original contract')
        if issue.status != 'resolved':
            unresolved.add(reference)
            covered.update((a, r) for a in issue.as_built_refs for r in issue.requirement_refs)
    if unresolved != set(profile.remaining_issue_refs):
        raise ValueError('V6 handover must preserve every original unresolved issue')
    pending = set()
    for reference in procedure.required_requirement_refs:
        requirement = original(reference, ContractorCloseoutRequirementView)
        if (requirement.contract_ref != contract.ref or not requirement.as_built_refs
                or not set(requirement.as_built_refs) <= set(contract.as_built_refs)):
            raise ValueError('V6 handover requirement substitutes original configurations')
        pending.update((a, reference) for a in requirement.as_built_refs)
    expected_pairs = [(Reference.model_validate(value['as_built_ref']),
        Reference.model_validate(value['requirement_ref'])) for value in step['expected_pending_verification_pairs']]
    if not pending or len(set(expected_pairs)) != len(expected_pairs) or pending != set(expected_pairs) or not pending <= covered:
        raise ValueError('V6 pending handover must retain the exact uncovered independent checks as remaining issues')
    if (not contract.continuing_responsibility_refs
            or contract.continuing_responsibility_refs != declared(step['expected_continuing_responsibility_refs'])):
        raise ValueError('V6 handover changes original continuing responsibilities')
    for reference in contract.continuing_responsibility_refs:
        duty = original(reference, ContractorContinuingResponsibilityView)
        if (duty.contract_ref != contract.ref or duty.organization_id != contract.contractor_id
                or duty.remaining.model_dump() != {'state': 'known', 'value': True}):
            raise ValueError('V6 handover substitutes or discharges its declared continuing duty')
    return path, hashlib.sha256(raw).hexdigest(), deepcopy(case), request.model_dump(mode='json'), configuration.model_dump(mode='json')


def run_v6_contractor_handover_offline(*, case_path, output_directory, execute=False):
    if type(execute) is not bool:
        raise ValueError('V6 handover execution selection must be an explicit boolean')
    path, digest, case, request, configuration = _prepare(case_path)
    step = case['steps'][0]
    directory = Path(output_directory).resolve()
    journal = Path(configuration['settings']['source_settings']['journal_path']).resolve()
    if execute and (directory != Path(step['output_directory']).resolve() or journal != directory / 'journal.sqlite'):
        raise ValueError('V6 execution requires the declared new output directory and its exact synthetic journal')
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v6-contractor-handover-plan.v1', 'scenario_id': 'V6', 'origin': 'synthetic',
        'run_id': case['run_id'], 'action_id': 'CONTRACTOR-A11', 'factory': _FACTORY,
        'mode': 'execute_offline' if execute else 'plan_only', 'input': {'path': str(path), 'sha256': digest},
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(configuration),
        'expected_remaining_issue_refs': deepcopy(step['expected_remaining_issue_refs']),
        'source_continuing_responsibility_refs': deepcopy(step['expected_continuing_responsibility_refs']),
        'expected_pending_verification_pairs': deepcopy(step['expected_pending_verification_pairs']),
        'limitations': ['Isolated synthetic pending-verification handover opinion; continuing duties are retained input sources.',
            'Owner reception/acceptance, native work observation and connected V6 behavior remain pending.']}
    for label, value in (('input', case), ('request', request), ('configuration', configuration), ('plan', plan)):
        atomic_json(directory / (label + '.json'), value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v6-contractor-handover-attempt.v1', 'status': 'started',
        'input_sha256': digest, 'automatic_retry': False}
    atomic_json(directory / 'attempt.json', attempt)
    try:
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest or journal.exists():
            raise ValueError('V6 input changed or original synthetic journal already exists; no replay')
        output = run_role_contract(request=request, configuration=configuration, factory=build_role_host,
            specification=_FACTORY, output_directory=directory / 'contractor', offline=True)
        result, evidence = output['result'], output['execution_evidence']
        identity, task, audit = evidence['identity'], evidence['task'], evidence['saved_audit']
        expected_identity = {'run_id': case['run_id'],
            'organization_id': configuration['settings']['source_settings']['source_projection']['organization_id'],
            'role': 'Contractor', 'action_id': 'CONTRACTOR-A11', 'request_id': request['context']['operation_id'], 'purpose': 'action',
            'input_sha256': task_digest(request['action_input']), 'context_sha256': task_digest(request['context'])}
        if (output['source_mode'] != 'fixture' or output['action_id'] != 'CONTRACTOR-A11'
                or output['macro_execution'] != 'not_performed' or evidence['model_host'] is not None
                or evidence['result_table'] != 'contractor_closeout_results' or task['identity'] != identity
                or any(identity.get(key) != value for key, value in expected_identity.items())
                or output['audit'] != [audit] or audit['result_sha256'] != task_digest(result)
                or result['kind'] != 'completed' or result['payload']['choice'] != 'submit_handover'
                or result['payload']['scope_ref'] != request['context']['scope']
                or result['payload']['remaining_issue_refs'] != step['expected_remaining_issue_refs']
                or task['state'] != 'output_formed' or task['output'] != result
                or task['output_sha256'] != task_digest(result) or task['submission'] is not None or task['receipt'] is not None):
            raise ValueError('V6 handover did not preserve its exact pending issues and original result without transport')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('V6 original Contractor handover input changed during evaluation')
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
    print(run_v6_contractor_handover_offline(case_path=args.input, output_directory=args.output, execute=args.execute)['mode'])


if __name__ == '__main__':
    main()
