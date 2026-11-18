"""Return the original checked A02 choice at GBA's bounded tender decision port."""
from integration.agent_client import AgentClientError, GbaV1AgentClient
from src.coordination.tasks import TaskIdentity, task_digest


class GbaTenderDecisionAdapter:
    """Read the client's same-tick persisted proposal; never rerun its strategy.

    validate_current(request, proposal, task_identity) must explicitly approve
    the original bid against actual current host facts and authorization. This
    component exposes the already evaluated A02 choice; it makes no independent
    model call and declares no new model discussion. Other decisions retain the
    explicitly configured handler. Missing proposals stop without a rule choice.
    """
    VERSION = 'gba-v1-contractor-a02-final-choice.v1'

    def __init__(self, *, client, validate_current, other_handler):
        if (not isinstance(client, GbaV1AgentClient) or not callable(validate_current)
                or not callable(other_handler)):
            raise ValueError('Actual bound client, fresh bid validator and configured other handler required')
        self.client, self.validate_current, self.other_handler = client, validate_current, other_handler

    def __call__(self, raw_request):
        from gba_construction_sim.backend.agents.contracts import (
            AGENT_MODULE_CONTRACT_VERSION, AgentDecisionRequestV1, AgentDecisionResponseV1,
            AgentProposalResponseV1,
        )
        from gba_construction_sim.backend.agents.external_adapter import ExternalAgentDecisionProvider

        request = AgentDecisionRequestV1.model_validate(raw_request).model_copy(deep=True)
        if (request.agent.role, request.decision_type) != ('Contractor', 'tender_decision'):
            return self.other_handler(request)
        if (request.contract_version != AGENT_MODULE_CONTRACT_VERSION
                or self.client.simulation_id is None
                or request.metadata.get('simulation_id') not in {None, self.client.simulation_id}
                or self.client.organization_roles.get(request.agent.agent_id) != 'Contractor'
                or not request.project_id or request.project.get('project_id') != request.project_id
                or request.tick < 0):
            raise AgentClientError('Final tender request changes original contract, simulation or recipient')
        proposal_id = f'proposal-tick{request.tick}-{request.project_id}-{request.agent.agent_id}-consider_tender'
        rows = self.client.tasks.for_organization(run_id=self.client.run_id,
            organization_id=request.agent.agent_id)
        matches = [row for row in rows if row['identity']['purpose'] == 'propose'
                   and row['identity']['request_id'] == proposal_id]
        if len(matches) != 1:
            raise AgentClientError('Final tender requires exactly one original same-tick saved proposal')
        identity = TaskIdentity(**matches[0]['identity'])
        if (identity.action_id != 'consider_tender' or identity.role != 'Contractor'
                or identity.versions != self.client.versions):
            raise AgentClientError('Final tender proposal differs from the original operation or execution versions')
        task = self.client.tasks.get(identity)
        if task['state'] != 'output_formed':
            raise AgentClientError('Final tender proposal is not a completed saved response')
        proposal = AgentProposalResponseV1.model_validate(task['output'])
        factors = proposal.factors
        if (proposal.request_id != proposal_id or proposal.action_type not in {'submit_bid', 'decline_bid'}
                or proposal.accepted != (proposal.action_type == 'submit_bid')
                or factors.get('micro_action_id') != 'CONTRACTOR-A02'
                or factors.get('project_id') != request.project_id
                or type(factors.get('proposal_tick')) is not int or factors['proposal_tick'] != request.tick):
            raise AgentClientError('Final tender saved proposal changes original micro choice, project or tick')
        for name in ('micro_result_sha256', 'micro_input_sha256', 'indicator_mapping_sha256',
                     'original_audit_sha256', 'proposal_request_sha256'):
            value = factors.get(name)
            if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
                raise AgentClientError('Final tender lacks its original micro decision provenance')
        if proposal.action_type not in request.constraints.allowed_actions:
            raise AgentClientError('Original tender choice is outside the current bounded action set')
        # Collector-based requests expose the actual assessment. Some old
        # synchronous DTOs omit it; fresh host validation is mandatory in both.
        risk_inputs = request.current_state.get('risk_inputs', {})
        assessment = risk_inputs.get('bid_assessment') if isinstance(risk_inputs, dict) else None
        if assessment is not None:
            if (not isinstance(assessment, dict)
                    or any(assessment.get(name) != proposal.data.get(name) for name in
                           ('bid_price', 'expected_profit', 'risk_level', 'bid_probability', 'decline_reason'))
                    or assessment.get('decision_factors') != factors):
                raise AgentClientError('Core tender assessment differs from the original saved proposal')
        if self.validate_current(request=request.model_copy(deep=True),
                proposal=proposal.model_copy(deep=True), task_identity=TaskIdentity(**identity.as_dict())) is not None:
            raise AgentClientError('Current original bid facts and permission must be explicitly validated')
        # The core consumes only the final bounded choice; its original
        # assessment retains price and professional indicators. Do not send
        # resource mutations, altered amounts or another probability adjustment.
        response = AgentDecisionResponseV1(request_id=request.request_id, agent_id=request.agent.agent_id,
            action_type=proposal.action_type, decision=proposal.accepted, reason=proposal.reason,
            data={'micro_action_id':'CONTRACTOR-A02', 'micro_result_sha256':factors['micro_result_sha256'],
                  'final_request_id':request.request_id,
                  'proposal_request_id':proposal_id, 'proposal_response_sha256':task_digest(task['output'])})
        ExternalAgentDecisionProvider._validated_action(request, response)
        # A concurrently changed task/version cannot be substituted after host
        # validation. The actual client also serializes this whole invocation.
        if self.client.tasks.get(identity) != task or identity.versions != self.client.versions:
            raise AgentClientError('Original tender proposal changed before final choice exposure')
        return response

    def evidence(self):
        return {'component':'integration.bindings.gba_v1_tender_decision.GbaTenderDecisionAdapter',
                'version':self.VERSION, 'run_id':self.client.run_id,
                'simulation_id':self.client.simulation_id, 'decision_type':'tender_decision',
                'action_id':'CONTRACTOR-A02', 'status':'implemented_unverified',
                'model_calls':0, 'selection_source':'original_audited_A02_choice',
                'limitations':['Current host bid/authorization validation remains mandatory.',
                               'No new model selection is performed at the legacy final transport boundary.',
                               'Native core submission, engagement/resource effects and feedback remain unverified.']}
