"""Original OWN-A09 review with an explicitly declared bounded choice mode."""
from copy import deepcopy
import json

from integration.owner_invitation_native import OwnerInvitationBridge
from src.coordination.tasks import TaskConflict, TaskIdentity, task_digest


class OwnerSelectionReview(OwnerInvitationBridge):
    VERSION = 'gba-v1-owner-selection-review.v2'
    HANDLER_KEY = ('Owner', 'select_preferred_bid')

    def install(self):
        client = self.assembly.client
        with client._lock:
            if (client._tender_feedback is not None or client._calls or client._request_hashes
                    or client.binding_installation_blocked()
                    or client.decision_handler is not self._other_decision):
                raise TaskConflict('Owner review must be installed before tender binding and business')
            if self.HANDLER_KEY not in client.native_routes._proposals:
                raise TaskConflict('Owner review requires the explicitly declared original native proposal')
            client.decision_handler = self.decide

    def _key(self, request):
        return 'owner_selection_review:' + task_digest([
            self.assembly.client.simulation_id, request.agent.agent_id, request.request_id])

    def _current(self, request):
        from gba_construction_sim.backend.simulation.decision_request_collector import DecisionRequestCollector
        self._check()
        engine = self.assembly.engine
        project = engine.projects.get(request.project_id)
        if (request.agent.role != 'Owner' or request.decision_type != 'owner_preferred_bidder_selection'
                or request.tick != engine.current_tick or project is None
                or project.owner_id != request.agent.agent_id or project.selected_contractor_id is not None
                or project.current_stage.value != 'bid_evaluation'
                or DecisionRequestCollector._project_snapshot(project) != request.project
                or request.choice_contract.output_field != 'selected_contractor_id'
                or request.choice_contract.multiple
                or 'select_preferred_bidder' not in request.constraints.allowed_actions):
            raise TaskConflict('Owner review requires its exact current pre-selection native decision')
        bids = request.decision_support.get('ranked_bids', [])
        selected = request.decision_support.get('selected_contractor_id')
        ids = [b['contractor_id'] for b in bids]
        if (not ids or len(ids) != len(set(ids)) or selected not in ids
                or set(ids) != {str(o['id']) for o in request.candidate_options}
                or set(ids) != {b['contractor_id'] for b in project.bids}):
            raise TaskConflict('Owner review cannot alter the complete native candidate set')
        return project

    def _plan(self, request):
        self._current(request)
        plans = [p for p in self.plans if (p.organization_id, p.project_id, p.tick) ==
                 (request.agent.agent_id, request.project_id, request.tick)]
        if len(plans) != 1 or plans[0].context.run_id != self.assembly.client.run_id:
            raise TaskConflict('Owner review lacks one exact independently declared source plan')
        return plans[0]

    def _qs_proof(self, request, bid):
        """Verify the publicly transported QS verdict against its saved action.

        No private QS source reading is copied into the Owner projection.
        The initial owner eligibility dossier remains an independent source.
        """
        verdict = bid.get('qs_decision', {})
        factors = verdict.get('decision_factors', {})
        scope = {'tick': request.tick, 'project_id': request.project_id,
                 'contractor_id': bid['contractor_id']}
        if (verdict.get('accepted') is not True or factors.get('micro_action_id') != 'QS-A06'
                or factors.get('native_evaluation_scope') != scope):
            raise TaskConflict('Owner review needs the actual successful original per-bid QS verdict')
        tasks = self.assembly.client.tasks.for_organization(run_id=self.assembly.client.run_id,
            organization_id=self.assembly.engine.projects[request.project_id].selected_qs_id)
        matching = [t for t in tasks if t['identity']['purpose'] == 'action'
            and TaskIdentity(**t['identity']).key == factors.get('micro_task_key')]
        if (len(matching) != 1 or matching[0]['state'] != 'output_formed'
                or matching[0]['output_sha256'] != factors.get('micro_result_sha256')
                or task_digest(matching[0]['output']) != matching[0]['output_sha256']
                or matching[0]['output']['kind'] != 'completed'
                or matching[0]['output']['payload']['choice'] != 'evaluate'):
            raise TaskConflict('Owner review QS verdict lost its original completed micro result')
        # The native QS bridge only emits accepted=True for a comparable,
        # resolved evaluation. Check the original round origin as well.
        with self.worker.store._lock:
            raw = self.worker.store._db.execute(
                "SELECT value FROM metadata WHERE key LIKE 'qs_bid_native_round:%'").fetchall()
        origins = [r for value, in raw for r in [json.loads(value)]
            if r.get('identity') == matching[0]['identity']]
        if len(origins) != 1:
            raise TaskConflict('Owner review lacks the original QS round provenance')
        record = origins[0]
        if (record['state'] != 'formed' or record['result_sha256'] != matching[0]['output_sha256']
                or record['record_sha256'] != task_digest({k:v for k,v in record.items() if k != 'record_sha256'})
                or len([o for o in record['origins'] if o['contractor_id'] == bid['contractor_id']]) != 1):
            raise TaskConflict('Owner review QS origin changed after evaluation')
        return {'task_key': factors['micro_task_key'], 'result_sha256': factors['micro_result_sha256'],
                'round_record_sha256': record['record_sha256']}

    def project(self, *, context, organization_id, grants):
        bound = self._bound.get(task_digest(context.model_dump(mode='json')))
        if bound is None or bound[0].organization_id != organization_id:
            raise TaskConflict('Owner review projection is not bound to its current request')
        plan, request = bound
        project = self._current(request)
        objects = deepcopy(plan.objects)
        get = lambda kind: next(r['value'] for r in objects if r['ref']['kind'] == kind)
        evidence = next(r['value'] for r in objects if r['ref'] == plan.native_evidence_ref.model_dump(mode='json'))
        evidence['content_hash'] = task_digest(request.model_dump(mode='json'))
        package, round_view = get('ProcurementPackage'), get('TenderRound')
        bidders = {r['value']['organization_id']:r['value'] for r in objects if r['ref']['kind'] == 'EligibleBidder'}
        qs_proofs = {}
        actual = {b['contractor_id']:b for b in project.bids}
        bids = request.decision_support['ranked_bids']
        if len(plan.action_input['bid_refs']) != len(bids):
            raise TaskConflict('Owner review source plan changes the original bid set')
        references = {r['id'].removeprefix('owner-review-bid:'):r for r in plan.action_input['bid_refs']}
        if set(references) != set(actual) or set(bidders) != set(actual):
            raise TaskConflict('Owner review must cover every original bidder')
        for bid in bids:
            org = bid['contractor_id']
            if (bid['bid_price'] != actual[org]['bid_price']
                    or bid['submitted_tick'] != actual[org]['submitted_tick']
                    or bid['decision_factors'] != actual[org]['decision_factors']):
                raise TaskConflict('Owner review changes an actual original submission')
            events = [e for e in self.assembly.engine.events.events if e.event_type == 'bid_submitted'
                and e.project_id == request.project_id and e.agent_id == org
                and e.tick == bid['submitted_tick']]
            if len(events) != 1 or bid['submitted_tick'] >= request.tick:
                raise TaskConflict('Owner review lacks the actual earlier native submission event')
            qs_proofs[org] = self._qs_proof(request, bid)
            bidder = bidders[org]
            grant = next(r['value'] for r in objects if r['ref']['kind'] == 'Authorization'
                and r['value']['organization_id'] == org and 'CONTRACTOR-A02' in r['value']['action_ids'])
            common = {k:deepcopy(round_view[k]) for k in ('scope','available_at','effective_window')}
            reference = references[org]
            value = {**common, 'ref':reference, 'evidence_refs':[plan.native_evidence_ref.model_dump(mode='json')],
                'package_ref':package['ref'], 'round_ref':round_view['ref'], 'bidder_ref':bidder['ref'],
                'bidder_organization_id':org, 'author_actor_id':bidder['actor_id'],
                'author_function_ref':bidder['function_ref'], 'author_authority_ref':grant['ref'],
                'author_action_id':'CONTRACTOR-A02', 'status':'submitted',
                'submitted_at':{**context.business_time.model_dump(mode='json'),'offset':bid['submitted_tick']},
                'compliance':{'state':'known','value':True}, 'compliance_rule_refs':[],
                'total_price':{'state':'known','value':{'value':str(bid['bid_price']),'currency':'HKD',
                    'basis_ref':plan.native_evidence_ref.model_dump(mode='json')}},
                'risk':{'state':'known','value':{'value':str(bid['risk_level']),'unit':'risk',
                    'basis_ref':plan.native_evidence_ref.model_dump(mode='json')}},
                'pricing_basis_ref':get('PricingBasis')['ref']}
            objects.append({'ref':reference, 'value':value})
        round_view['bid_refs'] = deepcopy(plan.action_input['bid_refs'])
        return {'run_id':context.run_id, 'macro_version':'gba-public-2026-08-21',
            'state_version':'owner-review-current:' + task_digest([request.model_dump(mode='json'),qs_proofs]),
            'read_token':context.read_token, 'business_time':context.business_time.model_dump(mode='json'),
            'organization_id':organization_id, 'objects':objects}

    def decide(self, request):
        from gba_construction_sim.backend.agents.contracts import AgentDecisionResponseV1
        if (request.agent.role,request.decision_type) != ('Owner','owner_preferred_bidder_selection'):
            return self._other_decision(request)
        with self.bindings.read_guard():
            plan = self._plan(request)
            if self._record(request) is not None:
                raise TaskConflict('Owner review already claimed; read the original saved final response')
            self._bound[task_digest(plan.context.model_dump(mode='json'))] = (plan,request.model_copy(deep=True))
            record = {'schema_version':self.VERSION,'state':'preparing',
                'organization_id':plan.organization_id,'project_id':plan.project_id,
                'native_request':request.model_dump(mode='json'),
                'request_sha256':task_digest(request.model_dump(mode='json')),
                'source_file_sha256':self.settings.file_sha256}
            self._save(request,record)
            prepared = self.assembler.build(plan.context, **deepcopy(plan.action_input))
            identity = self.worker.register(prepared, request_id='owner-selection-review:' + request.request_id)
            outcome = self.worker.execute(identity,prepared)
            result = outcome['result']
            if result['kind'] != 'completed' or result['payload']['choice'] != 'evaluate':
                raise TaskConflict('Owner review awaits original information; no final approval formed')
            candidate = request.decision_support['selected_contractor_id']
            selected_ref = next(r for r in plan.action_input['bid_refs'] if r['id'] == 'owner-review-bid:' + candidate)
            accepted = selected_ref in result['payload']['ranked_bid_refs']
            policy='Accept native candidate iff original OWN-A09 finds it eligible, compliant and within authorized budget; no winner override.'
            choice_data={}
            if self.settings.selection_mode=='lowest_eligible_price':
                eligible=[r['id'].removeprefix('owner-review-bid:') for r in result['payload']['ranked_bid_refs']]
                current={b['contractor_id']:b for b in request.decision_support['ranked_bids']}
                if any(org not in current for org in eligible):
                    raise TaskConflict('Owner choice references a bid outside the current evaluated set')
                accepted=bool(eligible)
                if accepted:
                    minimum=min(current[org]['bid_price'] for org in eligible)
                    tied=sorted(org for org in eligible if current[org]['bid_price']==minimum)
                    if len(tied)>1 and self.settings.selection_tie_break=='wait':
                        raise TaskConflict('Owner choice awaits an authorized tie-break policy')
                    candidate=tied[0]
                    choice_data={'selected_contractor_id':candidate}
                policy='Lowest actual submitted price among original OWN-A09 admissible bids; tie policy: '+self.settings.selection_tie_break
            record.update(state='formed', identity=identity.as_dict(), result_sha256=task_digest(result),
                accepted=accepted, native_candidate=candidate,
                proposal_candidate=request.decision_support['selected_contractor_id'],
                selection_mode=self.settings.selection_mode,policy=policy)
            self._save(request,record)
            return AgentDecisionResponseV1(request_id=request.request_id,agent_id=request.agent.agent_id,
                action_type='select_preferred_bidder',decision=accepted,
                reason='Original OWN-A09 budget/admissibility review and declared Owner selection policy: '+policy,
                data={'micro_action_id':'OWN-A09','micro_task_key':identity.key,
                    'micro_result_sha256':record['result_sha256'],
                    'selection_review_only':self.settings.selection_mode=='review_native',**choice_data})

    def evidence(self):
        self._check()
        with self.worker.store._lock:
            records = [json.loads(v) for v, in self.worker.store._db.execute(
                "SELECT value FROM metadata WHERE key LIKE 'owner_selection_review:%'")]
        return {'version':self.VERSION,'requests':records,'source_file_sha256':self.settings.file_sha256,
            'winner_override_supported':self.settings.selection_mode=='lowest_eligible_price',
            'native_ranking_is_micro_coverage':False}
