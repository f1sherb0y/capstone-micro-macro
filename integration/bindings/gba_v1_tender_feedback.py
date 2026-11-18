"""Own-enterprise tender feedback linked to original saved proposal and choice."""
from copy import deepcopy
import json

from src.coordination.tasks import TaskConflict, TaskIdentity, canonical, task_digest


TENDER_FIELDS = {
    'contractor_tender_decision': ('final_submit_bid', 'advisor_adjusted_probability'),
    'bid_submitted': ('contractor_id', 'bid_price', 'expected_profit', 'risk_level', 'bid_probability'),
    'bid_declined': ('contractor_id', 'decline_reason', 'expected_profit', 'risk_level', 'bid_probability'),
}
ADVISOR_LINK_FIELDS = ('micro_action_id', 'micro_result_sha256', 'proposal_request_id',
                       'proposal_response_sha256', 'final_request_id')


def project_tender_event(observation, organization_roles):
    """Clip committed own facts; never expose a whole project or other bidders."""
    if (not observation.committed or observation.event_type not in TENDER_FIELDS
            or organization_roles.get(observation.agent_id) != 'Contractor'):
        return {}
    data = observation.data
    if observation.event_type != 'contractor_tender_decision' and data.get('contractor_id') != observation.agent_id:
        raise TaskConflict('Own tender feedback changes the original contractor identity')
    projected = {name:deepcopy(data[name]) for name in TENDER_FIELDS[observation.event_type] if name in data}
    advisor = data.get('decision_advisor')
    if isinstance(advisor, dict):
        clipped = {name:deepcopy(advisor[name]) for name in ('available', 'action_type', 'decision') if name in advisor}
        original_link = advisor.get('data')
        if isinstance(original_link, dict):
            clipped['data'] = {name:deepcopy(original_link[name]) for name in ADVISOR_LINK_FIELDS if name in original_link}
        projected['decision_advisor'] = clipped
    return {observation.agent_id:{'event_type':observation.event_type, 'tick':observation.tick,
        'project_id':observation.project_id, 'agent_id':observation.agent_id, 'committed':True, 'data':projected}}


class GbaTenderFeedbackStore:
    """Persist correlation evidence in the same run journal, without core writes.

    A tender decision event records a choice, not bid creation. Only the actual
    bid_submitted event proves the native submission observation. It does not
    prove contract award, signed resources or the correctness of capacity. No
    technical task is marked as a receipt of a newer action submit endpoint.
    """
    SCHEMA = 'gba-v1-tender-feedback.v1'

    def __init__(self, client):
        self.client, self.store = client, client.tasks
        with self.store._transaction():
            self.store._db.execute('CREATE TABLE IF NOT EXISTS gba_tender_feedback (event_key TEXT PRIMARY KEY, record TEXT NOT NULL)')

    def record(self, observation):
        projected = project_tender_event(observation, self.client.organization_roles)
        if not projected:
            return False
        payload = projected[observation.agent_id]
        advisor = payload['data'].get('decision_advisor', {})
        link = advisor.get('data', {})
        # Native/unrelated tender observations can enter the own inbox, but do
        # not invent a correlation to this new bridge's original A02 task.
        if link.get('micro_action_id') != 'CONTRACTOR-A02':
            return False
        if self.client.simulation_id is None or not observation.project_id:
            raise TaskConflict('Tender feedback lacks the actual bound simulation/project')
        rows = self.store.for_organization(run_id=self.client.run_id, organization_id=observation.agent_id)

        def original(purpose, request_id, action_id):
            matches = [row for row in rows if row['identity']['purpose'] == purpose
                       and row['identity']['request_id'] == request_id]
            if len(matches) != 1:
                raise TaskConflict('Tender feedback lacks one exact original proposal/final task')
            identity = TaskIdentity(**matches[0]['identity'])
            task = self.store.get(identity)
            if (identity.action_id != action_id or identity.role != 'Contractor'
                    or task['state'] != 'output_formed' or task['output'] is None):
                raise TaskConflict('Tender feedback original task has no matching formed response')
            return identity, task

        expected_proposal_id = f'proposal-tick{observation.tick}-{observation.project_id}-{observation.agent_id}-consider_tender'
        if link.get('proposal_request_id') != expected_proposal_id:
            raise TaskConflict('Tender feedback substitutes original project, enterprise or tick')
        proposal_identity, proposal = original('propose', expected_proposal_id, 'consider_tender')
        final_identity, final = original('decide', link.get('final_request_id'), 'tender_decision')
        response = final['output']
        if (proposal_identity.versions != final_identity.versions
                or link != {name:response['data'].get(name) for name in ADVISOR_LINK_FIELDS}
                or link.get('proposal_response_sha256') != task_digest(proposal['output'])
                or link.get('micro_result_sha256') != proposal['output'].get('factors', {}).get('micro_result_sha256')
                or advisor.get('available') is not True or advisor.get('action_type') != response.get('action_type')
                or advisor.get('decision') is not response.get('decision')):
            raise TaskConflict('Tender feedback changes the actually returned proposal or final decision')
        submitted = response['action_type'] == 'submit_bid' and response['decision'] is True
        event_type = observation.event_type
        if (event_type == 'bid_submitted' and not submitted or event_type == 'bid_declined' and submitted
                or event_type == 'contractor_tender_decision' and payload['data'].get('final_submit_bid') is not submitted):
            raise TaskConflict('Tender core observation contradicts the saved final choice')
        # Core probability is adjusted by its advisor formula and is retained
        # as observed. Price/profit/risk must still be the actual proposal values.
        fields = ('bid_price', 'expected_profit', 'risk_level') if event_type == 'bid_submitted' else (
            ('expected_profit', 'risk_level', 'decline_reason') if event_type == 'bid_declined' else ())
        if any(payload['data'].get(name) != proposal['output']['data'].get(name) for name in fields):
            raise TaskConflict('Tender observation changes original offered price or professional indicators')
        record = {'schema_version':self.SCHEMA, 'run_id':self.client.run_id,
            'simulation_id':self.client.simulation_id, 'event_id':observation.event_id,
            'organization_id':observation.agent_id, 'projection':payload,
            'proposal_identity':proposal_identity.as_dict(), 'final_identity':final_identity.as_dict(),
            'micro_result_sha256':link['micro_result_sha256'],
            'effect': 'native_bid_submitted' if event_type == 'bid_submitted' else
                      'native_bid_declined' if event_type == 'bid_declined' else 'final_choice_observed'}
        record['record_sha256'] = task_digest(record)
        key = task_digest([self.client.run_id, observation.agent_id, observation.event_id])
        with self.store._transaction():
            # Recheck exact persisted responses before recording a correlation.
            if self.store._read(proposal_identity) != proposal or self.store._read(final_identity) != final:
                raise TaskConflict('Tender original tasks changed during feedback correlation')
            prior = self.store._db.execute('SELECT record FROM gba_tender_feedback WHERE event_key=?', (key,)).fetchone()
            if prior is not None:
                if json.loads(prior[0]) != record:
                    raise TaskConflict('Immutable tender feedback changed for the same event/enterprise')
                return False
            self.store._db.execute('INSERT INTO gba_tender_feedback VALUES (?,?)', (key, canonical(record)))
        return True

    def for_organization(self, *, organization_id):
        if organization_id not in self.store.organization_ids:
            raise TaskConflict('Tender feedback reader changes the original recipient')
        with self.store._lock:
            result = []
            for row in self.store._db.execute('SELECT record FROM gba_tender_feedback ORDER BY event_key'):
                record = json.loads(row[0])
                if (record.get('schema_version') != self.SCHEMA or record.get('run_id') != self.client.run_id
                        or record.get('simulation_id') != self.client.simulation_id
                        or task_digest({k:v for k,v in record.items() if k != 'record_sha256'}) != record.get('record_sha256')):
                    raise TaskConflict('Stored tender feedback changes its run, simulation or digest')
                if record['organization_id'] == organization_id:
                    result.append(deepcopy(record))
            return result

    def context_for_request(self, request, *, project_only=True):
        """Own prior terminal outcomes, suitable for a later micro request.

        A final-choice event is not an outcome. Repeated notifications of the
        same original proposal count once. Same-tick events are excluded so
        caller ordering cannot turn a contemporaneous choice into prior fact.
        """
        from gba_construction_sim.backend.agents.contracts import AgentProposalRequestV1
        from gba_construction_sim.backend.agents.operation_specs import get_operation_contract, validate_operation_inputs

        request = AgentProposalRequestV1.model_validate(request).model_copy(deep=True)
        tick = request.metadata.get('tick')
        project_id = request.inputs.get('project', {}).get('project_id')
        if (request.agent.role != 'Contractor' or request.operation != 'consider_tender'
                or self.client.organization_roles.get(request.agent.agent_id) != 'Contractor'
                or type(tick) is not int or tick < 0 or not project_id
                or type(project_only) is not bool
                or request.metadata.get('simulation_id') not in {None, self.client.simulation_id}):
            raise TaskConflict('Tender memory requires the actual scoped Contractor request and tick')
        contract = get_operation_contract('consider_tender', 'Contractor')
        if request.operation_contract != contract:
            raise TaskConflict('Tender memory changes the original native operation contract')
        validate_operation_inputs(contract, request.inputs)
        outcomes = {}
        records = self.for_organization(organization_id=request.agent.agent_id)
        for record in records:
            projection = record['projection']
            if (record['effect'] not in {'native_bid_submitted', 'native_bid_declined'}
                    or projection['tick'] >= tick
                    or project_only and projection['project_id'] != project_id):
                continue
            proposal = TaskIdentity(**record['proposal_identity'])
            final = TaskIdentity(**record['final_identity'])
            proposal_task, final_task = self.store.get(proposal), self.store.get(final)
            if (proposal.organization_id != request.agent.agent_id or final.organization_id != request.agent.agent_id
                    or proposal_task['state'] != 'output_formed' or final_task['state'] != 'output_formed'
                    or proposal_task['output']['factors'].get('micro_result_sha256') != record['micro_result_sha256']):
                raise TaskConflict('Tender memory lost its original completed request/result relationship')
            value = {'project_id': projection['project_id'], 'tick': projection['tick'],
                'effect': record['effect'], 'proposal_identity': proposal.as_dict(),
                'final_identity': final.as_dict(), 'micro_result_sha256': record['micro_result_sha256'],
                'data': deepcopy(projection['data'])}
            prior = outcomes.get(proposal.key)
            if prior is not None and prior != value:
                raise TaskConflict('Tender memory has inconsistent terminal outcomes for one original proposal')
            outcomes[proposal.key] = value
        source_events = [{'event_id': record['event_id'], 'record_sha256': record['record_sha256']}
            for record in records
            if record['effect'] in {'native_bid_submitted', 'native_bid_declined'}
            and record['projection']['tick'] < tick
            and (not project_only or record['projection']['project_id'] == project_id)]
        values = sorted(outcomes.values(), key=lambda value: (value['tick'], value['proposal_identity']['request_id']))
        context = {'schema_version': 'gba-v1-own-tender-context.v1', 'run_id': self.client.run_id,
            'simulation_id': self.client.simulation_id, 'organization_id': request.agent.agent_id,
            'request_sha256': task_digest(request.model_dump(mode='json')), 'as_of_tick': tick,
            'project_id': project_id, 'project_only': project_only, 'outcomes': values,
            'source_events': sorted(source_events, key=lambda value: value['event_id']),
            'submitted_count': sum(value['effect'] == 'native_bid_submitted' for value in values),
            'declined_count': sum(value['effect'] == 'native_bid_declined' for value in values)}
        context['context_sha256'] = task_digest(context)
        return context

    def record_screening_consumption(self, *, request, identity, worker, source, read_guard=None):
        """Acknowledge only a completed original A01 that read the private policy."""
        from integration.contractor_screening_results import ContractorScreeningResultWorker
        from src.actions.contracts.common import Reference

        identity = TaskIdentity(**identity.as_dict())
        if (not isinstance(worker, ContractorScreeningResultWorker) or worker.store is not self.store
                or identity.action_id != 'CONTRACTOR-A01' or identity.role != 'Contractor'
                or identity.run_id != self.client.run_id or identity.organization_id != request.agent.agent_id
                or identity.context_sha256 != source.get('context_sha256')
                or source.get('run_id') != identity.run_id or source.get('organization_id') != identity.organization_id
                or source.get('record_sha256') != task_digest(
                    {name: value for name, value in source.items() if name != 'record_sha256'})
                or source.get('schema_version') != 'contractor-screening-feedback-source.v1'
                or source.get('request_sha256') != task_digest(request.model_dump(mode='json'))):
            raise TaskConflict('Feedback consumption requires the original A01 task, request and source evidence')
        snapshot = worker.snapshots.get(identity)
        if snapshot['context']['execution_mode'] == 'offline_fixture':
            raise TaskConflict('Fixture-only screening cannot prove native feedback consumption')
        source_key = 'contractor_screening_feedback_source:' + task_digest([
            source['source_file_sha256'], snapshot['context']])
        with self.store._lock:
            saved_source = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (source_key,)).fetchone()
        if saved_source is None or json.loads(saved_source[0]) != source:
            raise TaskConflict('Feedback consumption lacks its original published private policy source')
        memory = self.context_for_request(request, project_only=source['feedback_context']['project_only'])
        if source.get('decline_after_prior_evaluations') is not None:
            from integration.bindings.gba_v1_bid_evaluation import with_own_evaluation_history
            memory=with_own_evaluation_history(self.client.native_routes.assembly,
                request=request,memory=memory,read_guard=read_guard)
        if source.get('decline_after_prior_final_accounts') is not None:
            from integration.bindings.gba_v1_final_accounts import with_own_final_account_history
            memory = with_own_final_account_history(self.client.native_routes.assembly,
                request=request, memory=memory, read_guard=read_guard)
        if source.get('decline_after_prior_payment_delays') is not None:
            from integration.bindings.gba_v1_progress_payments import with_own_progress_payment_history
            memory = with_own_progress_payment_history(self.client.native_routes.assembly,
                request=request, memory=memory, read_guard=read_guard)
        if memory != source['feedback_context']:
            raise TaskConflict('Prior own tender context changed before screening consumption was recorded')
        record = worker.get_record(identity)
        if (record is None or record['result']['kind'] != 'completed'
                or self.store.get(identity)['state'] != 'output_formed'
                or record['audit'].get('stages') != {
                    'input_validation': 'accepted', 'authorization': 'accepted', 'processor': 'bound'}
                or record['audit'].get('reading', {}).get('status') != 'accepted'):
            raise TaskConflict('Feedback consumption requires an actual completed authorized screening')
        if record['audit']['reading'].get('source_mode') != 'formal':
            raise TaskConflict('Feedback consumption requires the actual formal source projection path')
        reading = {Reference.model_validate(item['ref']).key(): item['projection'] for item in record['source_reading']}
        if (snapshot['action_input']['screening_profile_ref'] != source['profile_ref']
                or any(reading.get(Reference.model_validate(item['ref']).key()) != item['value'] for item in source['objects'])):
            raise TaskConflict('Completed screening did not read the exact derived profile and feedback evidence')
        body = {'schema_version': 'gba-v1-tender-feedback-consumption.v1',
            'run_id': identity.run_id, 'organization_id': identity.organization_id,
            'identity': identity.as_dict(), 'result_record_sha256': record['record_sha256'],
            'feedback_context_sha256': memory['context_sha256'],
            'feedback_source_sha256': source['record_sha256'], 'request_sha256': source['request_sha256'],
            'source_events': deepcopy(memory['source_events']), 'screening_choice': record['result']['payload']['choice'],
            'effect': 'private_policy_read_by_completed_screening'}
        if 'own_evaluated_bids' in memory:
            body['own_evaluated_bids']=deepcopy(memory['own_evaluated_bids'])
        if 'own_final_accounts' in memory:
            body['own_final_accounts'] = deepcopy(memory['own_final_accounts'])
        if 'own_progress_payments' in memory:
            body['own_progress_payments'] = deepcopy(memory['own_progress_payments'])
        body['record_sha256'] = task_digest(body)
        with self.store._transaction():
            # get_record validates the invocation through a transaction of its
            # own. Re-read already validated bytes inside this commit instead
            # of nesting SQLite BEGIN statements.
            current = self.store._db.execute('SELECT record FROM contractor_screening_results WHERE task_key=?',
                (identity.key,)).fetchone()
            current_snapshot = self.store._db.execute('SELECT record FROM invocation_snapshots WHERE task_key=?',
                (identity.key,)).fetchone()
            if (current is None or json.loads(current[0]) != record or current_snapshot is None
                    or json.loads(current_snapshot[0]) != snapshot
                    or self.store.get(identity)['state'] != 'output_formed'):
                raise TaskConflict('Original screening changed before feedback consumption was committed')
            key = 'gba_tender_feedback_consumption:' + identity.key
            prior = self.store._db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if prior is not None:
                if json.loads(prior[0]) != body:
                    raise TaskConflict('Original feedback consumption cannot be replaced')
            else:
                self.store._db.execute('INSERT INTO metadata VALUES (?,?)', (key, canonical(body)))
        return deepcopy(body)
