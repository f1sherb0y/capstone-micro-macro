"""Selection invariants only; never execute a feedback intervention or provider."""
import unittest

from prepare_capstone_feedback_sources_20261113 import select_events


def settlement(tick=45,owner='owner',case='case'):
    return {'tick':tick,'event_type':'final_account_settled','project_id':case,
        'data':{'owner_id':owner}}


def decision(key,tick,owner='owner',kind='project_opportunity_declined'):
    return {'tick':tick,'agent_id':owner,'event_type':kind,
        'data':{'decision_factors':{'micro_action_id':'OWN-A03','micro_task_key':key}}}


class SelectionTests(unittest.TestCase):
    def test_outcome_and_region_are_not_selection_criteria(self):
        earlier=decision('first',46,kind='project_initiated')
        later=decision('second',47)
        events=[settlement(),later,earlier,decision('third',48)]
        _,chosen=select_events(events,'owner','case')
        self.assertEqual(chosen,[earlier,later])

    def test_settlement_must_belong_to_same_owner_and_source_project(self):
        for wrong in [settlement(owner='other'),settlement(case='other')]:
            self.assertEqual(select_events([wrong,decision('one',46)],'owner','case'),([],[]))

    def test_later_round_is_strict_and_owner_is_exact(self):
        valid=decision('valid',46)
        events=[settlement(),decision('same-round',45),decision('other-owner',46,'other'),valid]
        _,chosen=select_events(events,'owner','case')
        self.assertEqual(chosen,[valid])  # no invented second opportunity

    def test_same_tick_ties_use_original_event_sequence(self):
        first=decision('a',46);second=decision('b',46,kind='project_initiated')
        _,chosen=select_events([settlement(),first,second,decision('c',46)],'owner','case')
        self.assertEqual(chosen,[first,second])


if __name__=='__main__':
    unittest.main()
