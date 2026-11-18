"""Scientific missingness, event order, and exposure checks for read-only metrics."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from capstone_macro_observations_20261113 import extract_project_observations, pricing_observation


def event(eid, tick, kind, *, stage='construction', data=None, project='p'):
    return {'event_id': eid, 'tick': tick, 'project_id': project, 'event_type': kind,
            'stage': stage, 'data': data or {}}


def state_data(quality=.7, risk=.25):
    return {'actual_progress': .6, 'planned_progress': .5, 'actual_cost': 120,
        'overall_quality': quality, 'design_quality': quality, 'construction_quality': quality,
        'material_quality': quality, 'supply_delay_risk': risk, 'safety_risk': risk,
        'claim_risk': risk, 'dispute_risk': risk, 'delay_days': 7}


def project(log):
    return {'project_id': 'p', 'current_stage': 'closed', 'initial_budget': 200,
        'estimated_cost': 100, 'contract_sum': 150, 'event_log': log,
        'performance': state_data(.6, .1)}


def observed_log():
    failed = event('f', 4, 'inspection_failed')
    return [event('a', 2, 'contract_awarded', stage='contract_award', data={'contract_sum': 150}),
        event('before', 3, 'project_state_updated', data=state_data(.99, .9)),
        event('work', 3, 'construction_progress_updated'),
        event('after', 3, 'project_state_updated', data=state_data(.7, .25)),
        failed, deepcopy(failed), event('other-project', 4, 'inspection_failed', project='another'),
        event('passed', 5, 'inspection_passed'),
        event('complete', 6, 'project_completed', stage='completion'),
        event('settle', 8, 'final_account_settled', stage='final_account'),
        event('closed-state', 9, 'project_state_updated', stage='closed', data=state_data(.6, .1))]


class MacroObservationTests(unittest.TestCase):
    def test_preconstruction_defaults_are_not_quality_or_safety_outcomes(self):
        p = project([event('initial', 1, 'project_state_updated', stage='initiation', data=state_data(1, 0))])
        r = extract_project_observations(p, end_tick=10, complete_horizon=True)
        self.assertIsNone(r['T5']['fixed_horizon'])
        self.assertIsNone(r['T6']['safety_risk']['construction_peak'])
        self.assertIsNone(r['T8']['comparative_counts'])
        self.assertEqual(r['T8']['raw_observed_counts']['safety_issue'], 0)
        self.assertFalse(r['T7']['occurred_by_planned_endpoint']['project_completed'])
        self.assertIsNone(r['T2']['contract_to_budget'])

    def test_missing_log_is_not_zero_events_or_a_complete_endpoint(self):
        p = project(None)
        r = extract_project_observations(p, end_tick=10, complete_horizon=True)
        self.assertFalse(r['fixed_horizon_complete'])
        self.assertIsNone(r['T7']['occurred_by_planned_endpoint']['contract_awarded'])
        self.assertIsNone(r['T8']['raw_observed_counts'])

    def test_event_order_and_project_log_deduplication_define_exposure(self):
        r = extract_project_observations(project(observed_log()), end_tick=10, complete_horizon=True)
        self.assertEqual(r['valid_construction_state_count'], 1)
        self.assertEqual(r['T6']['safety_risk']['construction_peak'], .25)
        self.assertEqual(r['T6']['safety_risk']['first_peak_source']['event_id'], 'after')
        self.assertEqual(r['T8']['comparative_counts']['inspection_failed'], 1)
        self.assertEqual(r['T8']['inspection_count'], 2)
        self.assertEqual(r['T8']['inspection_failure_fraction'], .5)
        self.assertEqual(r['T5']['completion']['overall_quality'], .7)
        self.assertEqual(r['T5']['fixed_horizon']['overall_quality'], .6)
        self.assertEqual(r['T5']['completion_state_source']['event_id'], 'after')
        self.assertAlmostEqual(r['T4']['fixed_horizon_progress_gap_pp'], 10)
        self.assertEqual(r['T4']['reported_delay_days'], 7)
        self.assertEqual(r['T4']['milestone_ticks']['project_completed'], [6])

    def test_partial_run_preserves_observed_positive_events_without_false_absences(self):
        r = extract_project_observations(project(observed_log()[:5]), end_tick=4, complete_horizon=False)
        self.assertTrue(r['T7']['occurred_by_planned_endpoint']['contract_awarded'])
        self.assertIsNone(r['T7']['occurred_by_planned_endpoint']['project_completed'])
        self.assertIsNone(r['T3']['fixed_horizon'])
        self.assertIsNone(r['T5']['fixed_horizon'])
        self.assertIsNone(r['T8']['comparative_counts'])
        self.assertEqual(r['T8']['raw_observed_counts']['inspection_failed'], 1)

    def test_completion_without_real_progress_cannot_use_default_quality(self):
        log = [event('state', 1, 'project_state_updated', stage='completion', data=state_data(1, 0)),
               event('complete', 2, 'project_completed', stage='completion')]
        r = extract_project_observations(project(log), end_tick=10, complete_horizon=True)
        self.assertTrue(r['T7']['occurred_by_planned_endpoint']['project_completed'])
        self.assertIsNone(r['T5']['completion'])

    def test_conflicting_event_copies_and_contract_mismatches_are_not_silently_merged(self):
        log = observed_log()
        log[5]['data']['different'] = True
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            extract_project_observations(project(log), end_tick=10, complete_horizon=True)
        p = project(observed_log())
        p['contract_sum'] = 151
        with self.assertRaisesRegex(ValueError, 'contract'):
            extract_project_observations(p, end_tick=10, complete_horizon=True)

    def test_cost_references_remain_separate_and_zero_references_are_missing(self):
        p = project(observed_log())
        r = extract_project_observations(p, end_tick=10, complete_horizon=True)
        self.assertEqual(r['T2']['contract_to_budget'], .75)
        deviations = r['T3']['completion']['deviations']
        self.assertEqual(deviations['initial_budget'], -.4)
        self.assertEqual(deviations['reported_estimated_cost'], .2)
        self.assertEqual(deviations['signed_contract'], -.2)
        p['estimated_cost'] = 0
        r = extract_project_observations(p, end_tick=10, complete_horizon=True)
        self.assertIsNone(r['T3']['fixed_horizon']['deviations']['reported_estimated_cost'])

    def test_markup_requires_an_independent_cost_and_does_not_invent_a_strategy(self):
        self.assertIsNone(pricing_observation(121, None)['markup_fraction'])
        with self.assertRaisesRegex(ValueError, 'independently'):
            pricing_observation(121, 100)
        r = pricing_observation(121, 100, cost_source_ref='declared-input#/cost')
        self.assertAlmostEqual(r['markup_fraction'], .21)
        self.assertIsNone(r['semantic_strategy'])
        self.assertIsNone(pricing_observation(121, 0, cost_source_ref='declared-input#/cost')['markup_fraction'])


if __name__ == '__main__':
    unittest.main()
