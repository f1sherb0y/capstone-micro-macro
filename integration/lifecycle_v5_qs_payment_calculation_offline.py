"""Plan or explicitly calculate and publish V5 original QS payment measurement."""
import argparse
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from integration.qs_payment_calculation_fixture_session import build_session
from integration.scenario_v2 import parse_input_json
from integration.sessions import atomic_json
from src.coordination.tasks import task_digest


def _read(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    _, value = parse_input_json(raw)
    return path, hashlib.sha256(raw).hexdigest(), value


def _prepare(case_path, reception_path):
    """Inspect supplied plain JSON; create neither session nor database."""
    case_file, reception_file = _read(case_path), _read(reception_path)
    case, reception = case_file[2], reception_file[2]
    if (case.get('schema_version') not in {'lifecycle-v5-qs-payment-calculation-input-case.v1',
            'lifecycle-v5-qs-payment-calculation-input-case.v2'}
            or case.get('scenario_id') != 'V5' or case.get('origin') != 'synthetic' or len(case.get('steps', [])) != 1
            or set(reception) != {'schema_version', 'input_case_sha256', 'owner_reconcile_result_path', 'request', 'settings'}
            or reception['schema_version'] != 'lifecycle-v5-qs-payment-calculation-reception.v1'
            or reception['input_case_sha256'] != case_file[1]):
        raise ValueError('V5 QS calculation requires explicit production input and independent original work reception')
    step, declaration = case['steps'][0], case['source_declaration']
    fixture, binding = step['input_fixture'], step['offline_binding']
    future_signing = declaration.get('future_signing_refs', {})
    if (future_signing and (case['schema_version'] != 'lifecycle-v5-qs-payment-calculation-input-case.v2'
            or set(future_signing) != {'certification_basis_ref', 'certification_authority_ref'}
            or future_signing['certification_basis_ref']['kind'] != 'CertificationBasis'
            or future_signing['certification_authority_ref']['kind'] != 'Authority')):
        raise ValueError('V5 signing calculation requires explicit future independent basis and authority references')
    request, settings = deepcopy(reception['request']), deepcopy(reception['settings'])
    publication_request = settings['publication_request']
    before, after = settings['production_sources'], settings['publication_sources']
    for supplied, expected, sources in ((request, binding['invocation'], before),
            (publication_request, binding['publication_invocation'], after)):
        context, projection = supplied['context'], sources['source_projection']
        rows = {task_digest(row['ref']): row for row in projection['objects']}
        if (set(supplied) != set(expected) or set(context) != set(expected['context'])
                or any(supplied[k] != v for k, v in expected.items() if k != 'context')
                or any(context[k] != v for k, v in expected['context'].items()
                    if k not in {'visible_refs', 'authorization_refs'})
                or not all(ref in context['authorization_refs'] for ref in expected['context']['authorization_refs'])
                or sources['action_id'] != 'QS-A08' or sources['allow_saved_recovery'] is not False
                or len(rows) != len(projection['objects'])
                or any(rows.get(task_digest(row['ref'])) != row for row in fixture['objects'])
                or any(projection[k] != context[k] for k in ('run_id', 'read_token', 'business_time'))
                or projection['organization_id'] != fixture['organization_id']
                or projection['macro_version'] != binding['source_projection_envelope']['macro_version']
                or set(map(task_digest, context['visible_refs'])) != {task_digest(row['ref']) for row in projection['objects']}
                    | {task_digest(ref) for ref in declaration['result_targets'].values()}
                    | {task_digest(ref) for ref in future_signing.values()}
                or any(task_digest(ref) in rows for ref in [*declaration['result_targets'].values(), *future_signing.values()])):
            raise ValueError('V5 calculation changes original inputs/authority or substitutes a generated future result')
        snapshot, baseline = sources['organization_snapshot'], binding['organization_snapshot']
        grants = {task_digest(row['ref']): row for row in snapshot['authorizations']}
        if (snapshot['run_id'] != case['run_id'] or snapshot['organizations'] != baseline['organizations']
                or snapshot['inactive_authorization_refs'] != baseline['inactive_authorization_refs']
                or len(grants) != len(snapshot['authorizations'])
                or any(grants.get(task_digest(row['ref'])) != row for row in baseline['authorizations'])):
            raise ValueError('V5 calculation replaces original scoped QS organization or author grants')
    if (before['organization_snapshot'] != after['organization_snapshot']
            or before['source_projection']['objects'] != after['source_projection']['objects']
            or Path(before['journal_path']).resolve() != Path(after['journal_path']).resolve()
            or settings['author_authority_ref'] != declaration['author_authority_ref']
            or settings['policy_version'] != declaration['policy_version']):
        raise ValueError('V5 fresh publication changes the original physical journal, source versions or calculation author')
    rows = {task_digest(row['ref']): row['value'] for row in before['source_projection']['objects']}
    action_input = request['action_input']
    application, contract = rows[task_digest(action_input['application_ref'])], rows[task_digest(action_input['contract_ref'])]
    requirements = declaration['assumptions']['required_native_values']
    if (application['contract_ref'] != contract['ref'] or application['applicant_id'] != 'contractor'
            or application['basis'] != 'incremental' or application['work_refs'] != action_input['performed_work_refs']
            or application['valuation_result_ref'] != declaration['result_targets']['valuation']
            or application['retention_result_ref'] is not None or application['deduction_result_ref'] is not None
            or application['certification_basis_ref'] != future_signing.get('certification_basis_ref')
            or application['correction_basis_ref'] is not None
            or application['status'] != 'submitted' or contract['payer_id'] != 'owner' or contract['beneficiary_id'] != 'contractor'
            or contract['currency'] != requirements['currency']
            or Fraction(contract['retention_fraction']) != Fraction(requirements['retention_fraction'])
            or contract['deduction_refs'] or contract['advance_credit_refs'] or contract['active_certificate_refs']
            or contract['certificate_count'] != requirements['prior_certificates'] or contract['receipt_refs']
            or contract['certified_cash_visibility'] != requirements['certified_cash_visibility']):
        raise ValueError('V5 actual calculation sources differ from explicit first works valuation and original complete history')
    for ref in action_input['performed_work_refs']:
        work = rows[task_digest(ref)]
        rate, condition = rows[task_digest(work['rate_ref'])], rows[task_digest(work['condition_ref'])]
        if (any(row['contract_ref'] != contract['ref'] for row in (work, rate, condition))
                or work['rate_ref'] not in contract['rate_refs'] or condition['work_ref'] != work['ref']
                or work['quantity']['unit'] != requirements['unit'] or rate['quantity_unit'] != requirements['unit']
                or Fraction(work['quantity']['value']) != Fraction(requirements['quantity'])
                or Fraction(rate['amount']['value']) != Fraction(requirements['rate'])
                or rate['amount']['currency'] != requirements['currency']
                or condition['fulfilled']['state'] != 'known' or condition['fulfilled']['value'] is not requirements['eligible']):
            raise ValueError('V5 actual observed work/rate/eligibility differs from declared original source requirement')
    owner_file = _read(reception['owner_reconcile_result_path'])
    owner, evidence = owner_file[2], owner_file[2]['execution_evidence']
    if (owner['run_id'] != case['run_id'] or owner['action_id'] != 'OWN-A06' or owner['source_mode'] != 'fixture'
            or owner['result']['kind'] != 'completed' or owner['result']['payload']['choice'] != 'reconcile'
            or evidence['identity']['organization_id'] != 'owner' or evidence['identity']['request_id'] != 'v5-owner-reconcile-24'
            or evidence['result_table'] != 'owner_payment_results' or evidence['task']['identity'] != evidence['identity']
            or evidence['task']['output'] != owner['result'] or evidence['task']['output_sha256'] != task_digest(owner['result'])
            or owner['audit'] != [evidence['saved_audit']] or evidence['saved_audit']['result_sha256'] != task_digest(owner['result'])
            or not isinstance(evidence['bank_execution_input'], dict)
            or Path(evidence['sources']['journal_path']).resolve() == Path(before['journal_path']).resolve()):
        raise ValueError('V5 QS calculation lacks original separate Owner reconciliation and Bank reception lineage')
    return (case_file, reception_file, owner_file), case, request, settings


def run_v5_qs_payment_calculation_offline(*, case_path, reception_path, output_directory, execute=False, saved_record_sha256=None):
    if type(execute) is not bool:
        raise ValueError('Calculation requires an explicit boolean offline execution choice')
    files, case, request, settings = _prepare(case_path, reception_path)
    directory = Path(output_directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema_version': 'lifecycle-v5-qs-payment-calculation-offline-plan.v1', 'origin': 'synthetic',
        'run_id': case['run_id'], 'action_id': 'QS-A08', 'mode': 'execute_offline' if execute else 'plan_only',
        'inputs': [{'path': str(path), 'sha256': sha} for path, sha, _ in files],
        'request_sha256': task_digest(request), 'configuration_sha256': task_digest(settings),
        'saved_record_sha256': saved_record_sha256, 'limitations': case['limitations'],
        'remaining_requirements': case['remaining_requirements']}
    for name, value in [('request', request), ('configuration', settings), ('reception-input', files[1][2]),
            ('owner-reconcile-result-input', files[2][2]), ('plan', plan)]:
        atomic_json(directory / f'{name}.json', value)
    if not execute:
        return plan
    attempt = {'schema_version': 'lifecycle-v5-qs-payment-calculation-attempt.v1', 'status': 'started'}
    atomic_json(directory / 'attempt.json', attempt)
    session = None
    try:
        for path, sha, _ in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('V5 original payment calculation sources changed before execution')
        session = build_session(request=request, settings=settings, output_directory=directory, offline=True)
        result = session.publish_saved(saved_record_sha256) if saved_record_sha256 is not None else session.calculate_and_publish()
        atomic_json(directory / 'calculation-result.json', result)
        if result['kind'] != 'prepared':
            summary = {**plan, 'status': 'calculation_not_prepared', 'result_kind': result['kind']}
        else:
            record, publication = result['record'], result['publication']
            projected = session.project_published()
            targets = case['source_declaration']['result_targets']
            actual = {row['result_kind']: row['ref'] for row in record['prepared']['projections']}
            expected = case['source_declaration']['expected_net_period_delta']
            if (actual != targets or publication['execution_sha256'] != record['record_sha256']
                    or publication['context'] != settings['publication_request']['context']
                    or any(row['report']['net_period_delta']['state'] != 'known'
                        or row['report']['net_period_delta']['value']['currency'] != expected['currency']
                        or Fraction(row['report']['net_period_delta']['value']['value']) != Fraction(expected['value'])
                        for row in record['prepared']['projections'])):
                raise ValueError('V5 saved valuation bundle or fresh publication differs from original declared targets/amount')
            atomic_json(directory / 'published-source-projection.json', projected)
            atomic_json(directory / 'persistent-evidence.json', session.evidence())
            summary = {**plan, 'status': 'original_qs_calculation_saved_and_published',
                'record_sha256': record['record_sha256'], 'publication_sha256': publication['record_sha256'],
                'result_targets': deepcopy(actual), 'source_projection_sha256': task_digest(projected)}
        for path, sha, _ in files:
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError('V5 original payment calculation sources changed during execution')
        atomic_json(directory / 'summary.json', summary)
        atomic_json(directory / 'attempt.json', {**attempt, 'status': summary['status']})
        return summary
    except Exception as exc:
        atomic_json(directory / 'attempt.json', {**attempt, 'status': 'failed', 'error_type': type(exc).__name__,
            'replay': 'requires_explicit_review_or_saved_record_selection'})
        raise
    finally:
        if session is not None:
            session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, default=Path('tests/fixtures/roles/lifecycle_v5_qs_payment_calculation_inputs.v1.json'))
    parser.add_argument('--reception', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute-offline', action='store_true')
    parser.add_argument('--saved-record-sha256')
    args = parser.parse_args()
    report = run_v5_qs_payment_calculation_offline(case_path=args.case, reception_path=args.reception,
        output_directory=args.output, execute=args.execute_offline, saved_record_sha256=args.saved_record_sha256)
    print(json.dumps({'mode': report['mode'], 'status': report.get('status', 'planned_not_executed'),
        'output': str(args.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
