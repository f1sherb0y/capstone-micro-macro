# Distribution Notice

This archive is a public development handoff for controlled technical collaboration on the GBA construction multi-agent simulation.

## Included material

- Simulation source code and tests required for agent-module integration.
- Versioned request, response, observation, capability, health, and operation contracts.
- A frontend client for workflow configuration and result inspection.
- One master specification and three normative specification volumes.
- Fully synthetic demonstration profiles generated specifically for this archive.

## Excluded material

- Credentials, local environment files, private databases, and personal or enterprise records.
- Repository history, worktrees, internal task notes, intermediate design attempts, presentation files, screenshots, reports, research drafts, and temporary outputs.
- Downloaded third-party documentation mirrors and installed dependency directories.

## Use and change control

This package is provided for development and evaluation. It does not assert production readiness, regulatory approval, or fitness for operational decisions. No open-source license is granted by this notice; use and redistribution remain subject to the governing project or collaboration agreement.

The simulation core owns committed state and formal calculations. External agent implementations must comply with the versioned contracts and must not directly mutate simulation-owned state.
