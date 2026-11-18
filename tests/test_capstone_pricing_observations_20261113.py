"""Selected pricing evidence must not be confused with unselected alternatives."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from capstone_pricing_observations_20261113 import extract_pricing_worker
from src.coordination.tasks import task_digest


def sealed(record):
    record = deepcopy(record)
    record.pop('record_sha256', None)
    record['record_sha256'] = task_digest(record)
    return record


def fixture(prefix='one', unknown_quantity=False):
    ref = lambda kind, suffix: {'kind': kind, 'id': prefix + suffix, 'version': '1'}
    original, selected = ref('ContractorPricingProfile', '-original'), ref('ContractorPricingProfile', '-selected')
    cost_ref, quantity_ref = ref('CostBasis', '-cost'), ref('QuantityBasis', '-quantity')
    profiles = [{'ref': r, 'projection': {'choice': 'submit_bid', 'markup_fraction': markup,
        'commercial_allowance': {'value': '0', 'currency': 'HKD'}, 'currency': 'HKD'}}
        for r, markup in [(original, '0.1'), (selected, '0.2')]]
    quantity = {'state': 'unknown'} if unknown_quantity else {'state': 'known', 'value': {'value': '2', 'unit': 'item'}}
    sources = profiles + [
        {'ref': cost_ref, 'projection': {'quantity_basis_ref': quantity_ref, 'quantity_line_key': 'work',
            'quantity_unit': 'item', 'unit_rate': {'state': 'known', 'value': {'value': '50', 'currency': 'HKD'}}}},
        {'ref': quantity_ref, 'projection': {'lines': [{'local_key': 'work', 'quantity': quantity}]}}]
    identity = {'run_id': prefix, 'organization_id': 'contractor', 'action_id': 'CONTRACTOR-A02',
        'input_sha256': 'input-hash', 'context_sha256': 'context-hash'}
    action_input = {'pricing_profile_ref': selected, 'cost_refs': [cost_ref], 'quantity_refs': [quantity_ref]}
    snapshot = {'source_reading': sources, 'source_reading_sha256': task_digest(sources),
        'options': [{'option_id': prefix + '-option', 'action_input': action_input}]}
    option_record = sealed({'selection': identity, 'snapshot': snapshot})
    result = {'kind': 'completed', 'payload': {'choice': 'submit_bid',
        'bid': {'price': {'value': '120', 'currency': 'HKD'}, 'cost_basis_refs': [cost_ref]}}}
    methods = [{'method_ref': {'id': 'micro.contractor.declared_bid_price'}, 'input': {'source_refs': [profile]},
        'result': {'kind': 'ok', 'value': {'internal_cost_subtotal': {'value': '100'},
            'offered_price': {'value': price}}}} for profile, price in [(original, '110'), (selected, '120')]]
    worker = sealed({'identity': identity, 'result': result, 'result_sha256': task_digest(result),
        'audit': {'decision': {'execution': {'selected_option_id': prefix + '-option'}}, 'method_calls': methods}})
    return worker, option_record


class PricingSourceTests(unittest.TestCase):
    def test_selected_alternative_not_first_pricing_calculation(self):
        worker, snapshot = fixture()
        row = extract_pricing_worker(worker, snapshot, snapshot_locator='journal:actual')
        self.assertEqual(row['declared_cost_base'], '100')
        self.assertEqual(row['bid_price'], '120')
        self.assertEqual(row['markup_fraction'], .2)
        self.assertEqual(row['selected_pricing_method_indices'], [1])

    def test_canonical_choice_does_not_treat_run_specific_ids_as_behavior(self):
        first = extract_pricing_worker(*fixture('one'), snapshot_locator='journal:one')
        second = extract_pricing_worker(*fixture('another'), snapshot_locator='journal:another')
        self.assertNotEqual(first['selected_option_id'], second['selected_option_id'])
        self.assertEqual(first['canonical_commercial_choice'], second['canonical_commercial_choice'])

    def test_unknown_quantity_does_not_recover_cost_from_price_and_markup(self):
        worker, snapshot = fixture(unknown_quantity=True)
        row = extract_pricing_worker(worker, snapshot, snapshot_locator='journal:unknown')
        self.assertEqual(row['bid_price'], '120')
        self.assertIsNone(row['declared_cost_base'])
        self.assertIsNone(row['markup_fraction'])

    def test_modified_source_or_incompatible_actual_price_is_rejected(self):
        worker, snapshot = fixture()
        snapshot['snapshot']['source_reading'][0]['projection']['currency'] = 'MOP'
        with self.assertRaisesRegex(ValueError, 'digest'):
            extract_pricing_worker(worker, snapshot, snapshot_locator='journal:tampered')
        worker, snapshot = fixture()
        worker['result']['payload']['bid']['price']['value'] = '121'
        worker['result_sha256'] = task_digest(worker['result'])
        worker = sealed(worker)
        with self.assertRaisesRegex(ValueError, 'formula'):
            extract_pricing_worker(worker, snapshot, snapshot_locator='journal:price')


if __name__ == '__main__':
    unittest.main()
