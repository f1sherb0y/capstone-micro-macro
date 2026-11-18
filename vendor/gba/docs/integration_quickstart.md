# External Agent Module Integration Quick Start

## 1. Objective

Connect an independent agent implementation without transferring simulation-state ownership to the agent layer. The external module receives bounded, read-only decision packages and returns structured proposals or choices. The simulation validates and commits all resulting state changes.

## 2. Required interface

Implement `ExternalAgentClientPort` from `gba_construction_sim.backend.agents.contracts`:

- `propose(request)`: role-specific professional reasoning for an operation listed in SPEC-03.
- `decide(request)`: final bounded selection from `request.constraints.allowed_actions`.
- `observe(observation)`: ingestion of committed facts after simulation validation.

Optional methods are `decide_batch`, `capabilities`, and `health`.

## 3. Proposal processing

For every `AgentProposalRequestV1`:

1. Verify `contract_version`.
2. Use `request.agent.agent_id` to load only that agent's memory and model session.
3. Read `request.operation_contract` as the machine-readable output schema.
4. Select one declared `action_type`.
5. Return all required `data_fields` for that action.
6. Return `utility` and `probability` in `[0, 1]`, an auditable `reason`, and optional `factors`.

The adapter validates the action and fields against the attached contract before the result enters the simulation.

## 4. Final decision processing

For every `AgentDecisionRequestV1`:

1. Read identity, memory, beliefs, strategy, resources, project, environment, policy, engagement, messages, and candidate options as read-only context.
2. Select exactly one action in `constraints.allowed_actions`.
3. Respect `choice_contract.output_field`, `multiple`, and `limit` when candidate selection is required.
4. Return a concise reason, optional confidence, and only decision-owned structured data.

Fields such as project stage, budget, resources, metrics, event logs, and other simulation-owned state must not be written by an external agent response.

## 5. Adapter construction

```python
from gba_construction_sim.backend.agents.external_adapter import ExternalAgentModuleAdapter
from gba_construction_sim.backend.simulation.simulation_engine import SimulationEngine

client = ExternalAgentClient()
agent_module = ExternalAgentModuleAdapter(
    client,
    random_seed=42,
    scheduler_options={"max_concurrency": 8},
)
engine = SimulationEngine.from_request(
    simulation_request,
    agent_module=agent_module,
)
```

`SimulationEngine.from_request` is the stable programmatic composition point. A deployment that creates simulations through an HTTP service should construct the same adapter in its application composition layer and pass it to this factory; transport and credential management remain deployment concerns.

## 6. Identity and memory isolation

- Maintain a separate memory namespace for every `agent_id`.
- Do not reuse hidden conversation history across agents.
- Treat semantic background and episodic observations as distinct stores.
- Update memory only from committed `AgentObservationV1` events.
- Preserve `request_id`, `event_id`, and `contract_version` for audit and idempotency.

## 7. Acceptance checklist

- Capability and health checks return the current contract version.
- Every role-operation pair required by SPEC-03 has a valid proposal implementation.
- Every decision returns an allowed action and satisfies the choice contract.
- Invalid versions, mismatched IDs, missing fields, and state-mutation attempts are rejected.
- Concurrent decisions remain isolated by `agent_id`.
- Observation replay is idempotent.
- Fixed-seed contract tests are deterministic when model calls are replaced with fixtures.
- Integrated smoke tests complete at least one project lifecycle without bypassing simulation validation.

Run the focused contract suite:

```bash
python -m pytest \
  gba_construction_sim/backend/tests/test_agent_module_contracts.py \
  gba_construction_sim/backend/tests/test_role_agent_decisions.py \
  gba_construction_sim/backend/tests/test_workflow_runtime.py -q
```
