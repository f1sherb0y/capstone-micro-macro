"""Private A02/A03/A04 handoff from actual saved micro decisions.

These projections are internal review records, never native intake receipts,
registered credit facilities or separate formal financing accounts.
"""
from copy import deepcopy
from decimal import Decimal

from src.actions.contracts.common import Reference
from src.actions.contracts.bank_quote_objects import QuoteCreditAssessmentView, QuoteRecordedReviewView
from src.coordination.tasks import TaskConflict, task_digest


def checked_result(worker, identity):
    record = worker.get_record(identity)
    task = worker.store.get(identity)
    if (record is None or task['state'] != 'output_formed' or task['output'] != record['result']
            or task['output_sha256'] != record['result_sha256'] or record['result']['kind'] != 'completed'):
        raise TaskConflict('Private bank handoff requires its original formed completed micro result')
    return record


def evidence_binding(objects, reference, value):
    rows = [r for r in objects if r['ref'] == reference]
    if (len(rows) != 1 or rows[0]['value'].get('content_hash') is not None
            or rows[0]['value'].get('source_kind') != 'synthetic'
            or rows[0]['value'].get('basis_kind') != 'observed'):
        raise TaskConflict('Bank runtime binding requires its one explicit unbound observed evidence')
    rows[0]['value']['content_hash'] = task_digest(value)


def intake_for_review(record, *, context, action_input, objects, evidence_ref):
    result = record['result']['payload']
    if (record['identity']['action_id'] != 'BANK-A02' or result['choice'] != 'accept_for_review'
            or result['product_ref'] != action_input['product_ref']
            or context.run_id != record['identity']['run_id']
            or context.business_time.model_dump(mode='json') != next(r['projection'] for r in record['source_reading']
                if r['ref']['kind'] == 'CandidateSet')['as_of']):
        raise TaskConflict('A03 private handoff changes its original accepted A02 product or business clock')
    original = {task_digest(r['ref']): r['projection'] for r in record['source_reading']}
    for ref in (action_input['application_ref'], action_input['product_ref']):
        row, = [r for r in objects if r['ref'] == ref]
        value = deepcopy(row['value'])
        if ref['kind'] == 'FinanceProductProfile':
            value.pop('quote_policy_ref', None)
        if task_digest(value) != task_digest(original.get(task_digest(ref))):
            raise TaskConflict('A03 private handoff substitutes original submitted application or intake product')
    if result['required_condition_refs'] != next(r['value'] for r in objects
            if r['ref'] == action_input['product_ref'])['required_condition_refs']:
        raise TaskConflict('A03 private handoff drops original intake conditions')
    evidence_binding(objects, evidence_ref, {'source': 'private_micro_intake_result',
        'identity': record['identity'], 'record_sha256': record['record_sha256'],
        'result_sha256': record['result_sha256'], 'source_reading_sha256': record['source_reading_sha256']})


def review_for_quote(record, *, invocation, context, action_input, objects, recorded_ref, audit_ref):
    """Project original A03 author, input, audit and payload, without a receipt."""
    identity = record['identity']
    if identity['action_id'] != 'BANK-A03' or identity['run_id'] != context.run_id:
        raise TaskConflict('A04 private handoff changes its original A03 action or run')
    # The actual invocation snapshot, rather than a copied input supplied by a
    # new caller, is passed by the application after checked_result().
    original_context = invocation['context']
    original_input = invocation['action_input']
    if (original_context['scope'] != context.scope.model_dump(mode='json')
            or original_context['business_time'] != context.business_time.model_dump(mode='json')
            or original_input['application_ref'] != action_input['application_ref']
            or original_input['product_ref'] != action_input['product_ref']):
        raise TaskConflict('A04 private handoff changes its original project, time or application')
    projected = {task_digest(r['ref']): r for r in objects}
    # These are explicit action-specific views of the same source. Preserve
    # every original field; only the two declared quote extensions are allowed.
    for source in record['source_reading']:
        ref = source['ref']
        if ref['kind'] == 'CandidateSet':
            continue
        target = projected.get(task_digest(ref))
        if target is None:
            raise TaskConflict('A04 private handoff omits an original A03 dependency')
        value = deepcopy(target['value'])
        if ref['kind'] == 'FinanceProductProfile':
            value.pop('quote_policy_ref', None)
        if ref['kind'] == 'Requirement':
            value.pop('stage', None)
        if task_digest(value) != task_digest(source['projection']):
            raise TaskConflict('A04 private handoff changes an original A03 dependency')
    evidence_binding(objects, audit_ref, {'source': 'private_micro_credit_review', 'identity': identity,
        'record_sha256': record['record_sha256'], 'result_sha256': record['result_sha256'], 'audit': record['audit']})
    recorded = QuoteRecordedReviewView.model_validate({'ref': recorded_ref, 'action_id': 'BANK-A03',
        'source_run_id': context.run_id, 'actor_id': original_context['actor_id'],
        'organization_id': identity['organization_id'], 'function_ref': original_context['function_ref'],
        'authority_refs': original_context['authorization_refs'], 'scope_ref': original_context['scope'],
        'business_time': original_context['business_time'], 'input': original_input,
        'payload': record['result']['payload'], 'evidence_refs': [audit_ref]})
    target, = [r for r in objects if r['ref'] == recorded_ref]
    if target['value'] is not None:
        raise TaskConflict('Private recorded review must be an unbound source, not an existing formal record')
    target['value'] = recorded.model_dump(mode='json')
    # Digest the original dependencies through A04's declared schemas, exactly
    # as its processor will read them. Never rewrite the saved A03 reading.
    from integration.bank_quote_actions import BankQuoteActionAssembler
    schemas = BankQuoteActionAssembler.SOURCE_SCHEMAS()
    required = {task_digest(r) for r in [*original_context['authorization_refs'], original_context['function_ref'],
        recorded_ref, audit_ref, *[r['ref'] for r in record['source_reading'] if r['ref']['kind'] != 'CandidateSet']]}
    dependencies = [{'ref': r['ref'], 'projection_sha256': task_digest(schemas.validate_projection(
        Reference.model_validate(r['ref']), r['value']).model_dump(mode='json'))}
        for r in objects if task_digest(r['ref']) in required]
    assessment = QuoteCreditAssessmentView.model_validate({'ref': action_input['assessment_ref'],
        'application_ref': original_input['application_ref'], 'product_ref': original_input['product_ref'],
        'borrower_id': next(r['value'] for r in objects if r['ref'] == original_input['application_ref'])['borrower_id'],
        'lender_id': identity['organization_id'], 'scope_ref': original_context['scope'],
        'recorded_decision_ref': recorded_ref, 'source_run_id': context.run_id,
        'author_actor_id': original_context['actor_id'], 'author_function_ref': original_context['function_ref'],
        'authority_refs': original_context['authorization_refs'], 'originating_action_id': 'BANK-A03',
        'review_input': original_input, 'review_payload': record['result']['payload'], 'source_dependencies': dependencies,
        'dependency_coverage': 'complete', 'method_audit_refs': [audit_ref],
        'reviewed_at': original_context['business_time'], 'available_at': context.business_time.model_dump(mode='json'),
        'effective_window': next(r['value'] for r in objects if r['ref'] == original_input['product_ref'])['effective_window'],
        'status': 'recorded', 'evidence_refs': [audit_ref]})
    target, = [r for r in objects if r['ref'] == action_input['assessment_ref']]
    if target['value'] is not None:
        raise TaskConflict('Private assessment must be derived from the actual worker result once')
    target['value'] = assessment.model_dump(mode='json')


def native_quote_summary(record, objects, *, periods_per_year):
    """Supported native summary: zero-fee simple interest with one end payment."""
    payload = record['result']['payload']
    if payload['choice'] == 'decline':
        return False, {'approved_amount': 0.0, 'interest_rate': 0.0, 'conditions': []}
    if payload['choice'] not in {'offer', 'conditional_offer'}:
        raise TaskConflict('Unresolved bank quotation cannot become native approval or rejection')
    terms = payload['terms']
    def get(ref):
        return next(r['value'] for r in objects if r['ref'] == ref)
    price = get(terms['pricing_ref'])
    tenor = get(terms['tenor_ref'])
    payments = price['interest_payments']
    if (type(periods_per_year) is not int or periods_per_year <= 0 or payments['state'] != 'known'
            or len(payments['value']) != 1 or payments['value'][0]['time'] != tenor['end']):
        raise TaskConflict('Native interest conversion needs one explicit simple-interest end payment and clock conversion')
    for fee_ref in terms['fee_rule_refs']:
        fee = get(fee_ref)
        if any(fee[k]['state'] != 'known' or Decimal(str(fee[k]['value'].get('value') if isinstance(fee[k]['value'], dict)
                else fee[k]['value'])) != 0 for k in ('fixed_amount', 'principal_factor')):
            raise TaskConflict('Native rate summary cannot silently discard nonzero or unknown fees')
    duration = tenor['end']['offset'] - tenor['start']['offset']
    if duration <= 0 or tenor['start']['clock_ref'] != tenor['end']['clock_ref']:
        raise TaskConflict('Native rate conversion changes its actual positive quote tenor')
    rate = Decimal(payments['value'][0]['principal_factor']) * periods_per_year / duration
    conditions = [get(ref).get('description', 'Requirement ' + ref['id']) for ref in terms['condition_refs']]
    return True, {'approved_amount': float(Decimal(terms['principal_limit']['value'])),
                  'interest_rate': float(rate), 'conditions': conditions}
