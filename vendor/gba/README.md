# GBA Construction Multi-Agent Simulation Integration Kit

**Public development handoff · Contract version 1.0 · 2026-08-21**

This package provides a runnable simulation core, a versioned external-agent boundary, a visual workflow client, synthetic demonstration data, and the normative specifications required to continue multi-agent integration work.

## 1. Integration boundary

Each Owner, Bank, Architect, Engineer, QS, Government, Contractor, and Supplier is an independent agent. An agent implementation may own identity, background, memory, beliefs, strategy, reasoning, and model sessions. The simulation core remains the sole owner of project state, event ordering, resource accounting, formal calculations, validation, and committed state transitions.

```text
Simulation core
  -> versioned read-only request + bounded action set
External agent module
  -> proposal or decision + reason + structured data
Simulation core
  -> validate -> apply -> emit committed observation
External agent module
  -> update agent-owned memory
```

The external module can be in-process or remote. The transport-neutral contracts are defined in `gba_construction_sim/backend/agents/contracts.py`; adapter validation is implemented in `gba_construction_sim/backend/agents/external_adapter.py`.

## 2. Package contents

| Path | Purpose |
|---|---|
| `gba_construction_sim/` | Backend simulation core, agent contracts, adapters, API, and tests |
| `frontend/` | Vue workflow and analytics client |
| `docs/` | One master specification and three normative specification volumes |
| `examples/` | External-agent integration examples |
| `outputs/gba_construction_agents_batch001.csv` | Fully synthetic demonstration agent profiles |
| `scripts/` | Repeatable demo-data generation and package validation |

The package contains no credentials, private enterprise records, local databases, presentation files, screenshots, research drafts, repository history, or generated frontend dependencies.

## 3. Normative documentation

Read the documents in this order:

1. [Technical specification master book](docs/gba_multi_agent_simulation_specification.md)
2. [SPEC-01 Model and runtime environment](docs/simulation_model_specification.md)
3. [SPEC-02 Agent module integration](docs/agent_module_integration_guide.md)
4. [SPEC-03 Operation function contracts](docs/agent_operation_contracts.md)

The master book defines system boundaries and ownership. SPEC-01 defines the simulation environment and lifecycle. SPEC-02 defines transport DTOs and integration procedures. SPEC-03 is the authoritative input/output contract for every role-specific operation.

## 4. Quick start

### Backend

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
python -m uvicorn gba_construction_sim.backend.main:app --host 127.0.0.1 --port 8000
```

The default public configuration uses the deterministic rule-based fallback and does not require a model credential. A local SQLite database is generated from the synthetic CSV only when a database-backed endpoint is first used.

### Frontend

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173/`. The frontend expects the backend at `http://127.0.0.1:8000` unless its API configuration is changed.

### Tests

```bash
python -m pytest -q
python scripts/validate_public_package.py
cd frontend && npm run build
```

## 5. External-agent integration

The minimum implementation is `ExternalAgentClientPort`:

```python
class ExternalAgentClient:
    def propose(self, request: AgentProposalRequestV1) -> AgentProposalResponseV1:
        ...

    def decide(self, request: AgentDecisionRequestV1) -> AgentDecisionResponseV1:
        ...

    def observe(self, observation: AgentObservationV1) -> None:
        ...
```

Inject the client through the validated adapter:

```python
client = ExternalAgentClient()
module = ExternalAgentModuleAdapter(client, random_seed=42)
engine = SimulationEngine.from_request(request, agent_module=module)
```

Use [the integration quick start](docs/integration_quickstart.md) for the implementation sequence and acceptance checklist. Do not mutate project state in an agent response; return only one action from the provided bounded action set and the fields required by the attached operation contract.

## 6. Release status

This is a development integration package, not a production deployment. Interface compatibility is governed by `AGENT_MODULE_CONTRACT_VERSION`. Changes to DTO fields, operation contracts, ownership rules, or validation semantics require an explicit version update and coordinated migration.

See [release scope](docs/release_scope.md) and [NOTICE](NOTICE.md) before redistribution or deployment.
