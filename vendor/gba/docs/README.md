# Documentation Index

## Normative set

| Order | Document | Authority |
|---|---|---|
| 1 | [Technical specification master book](gba_multi_agent_simulation_specification.md) | System architecture, lifecycle, core data objects, state ownership, and change control |
| 2 | [SPEC-01 Model and runtime environment](simulation_model_specification.md) | Agent categories, environment parameters, project lifecycle, events, metrics, and runtime behavior |
| 3 | [SPEC-02 Agent module integration](agent_module_integration_guide.md) | Integration boundary, versioned DTOs, adapter behavior, registration, observations, health, and acceptance |
| 4 | [SPEC-03 Operation function contracts](agent_operation_contracts.md) | Role-by-role operation purpose, required inputs, allowed outputs, field semantics, and validation rules |

These four documents form one coordinated specification set. They are not independent descriptions and should not be selectively implemented.

## Supplemental documents

- [Integration quick start](integration_quickstart.md): implementation order and executable integration pattern.
- [Release scope](release_scope.md): public-package contents, exclusions, and verification boundary.

Where supplemental guidance conflicts with a normative document, the normative document takes precedence.
