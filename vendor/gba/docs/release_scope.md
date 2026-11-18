# Public Integration Package Scope

## Release identifier

`gba_multi_agent_integration_public_v1.0_2026-08-21`

## Purpose

Provide a self-contained development baseline for implementing and validating independent role-based agents against the GBA construction simulation core.

## Included

- Current backend source required by the simulation runtime.
- Agent contracts, operation specifications, external adapter, and focused integration tests.
- Current frontend source and deterministic package lock.
- Canonical one-master-plus-three-volume specification set.
- Supplemental integration and release guidance.
- 1,320 reproducible, synthetic-only demonstration profiles, sufficient for the public runtime and cluster-balance tests without exposing source records.

## Excluded

- Git metadata and local worktrees.
- `.env.local`, API keys, tokens, credentials, and developer-machine configuration.
- Real or user-provided enterprise data and generated local databases.
- Internal planning notes, temporary QA routes, screenshots, presentations, intermediate reports, research drafts, and experimental artifacts not required by the public contract.
- Installed dependencies, build output, caches, logs, and third-party documentation mirrors.

## Compatibility baseline

- Agent module contract: `1.0`
- Python: `>=3.9`
- Frontend: package versions locked by `frontend/package-lock.json`
- Public demo behavior: rule-based fallback enabled, external model calls disabled

## Verification requirement

Before distribution, run `python scripts/validate_public_package.py`, the focused agent integration tests, the full backend suite, and `npm run build`. Two tests that assert the omitted private Batch001 source mix or collaboration prior are explicitly skipped in this public package. A generated SQLite database, frontend build directory, or dependency directory must not be included in the final archive.
