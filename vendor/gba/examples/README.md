# Integration Examples

The executable contract tests are the primary reference examples:

- `gba_construction_sim/backend/tests/test_agent_module_contracts.py`
- `gba_construction_sim/backend/tests/test_role_agent_decisions.py`

They demonstrate complete versioned decision packages, proposal validation, state-mutation rejection, observation delivery, capability discovery, health reporting, and `SimulationEngine` injection.

Production integrations should implement `ExternalAgentClientPort`, construct `ExternalAgentModuleAdapter`, and inject it through `SimulationEngine.from_request`. Network transport, authentication, retries, and model-session storage belong to the deployment composition layer and are intentionally not fixed by the simulation contract.
