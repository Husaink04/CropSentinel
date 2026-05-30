# CropSentinel Agent Operating Guide

## Project Vision

CropSentinel is an employee monitoring and context-based data loss prevention platform. Its purpose is to give organizations real-time visibility into endpoint activity, risky data movement, insider-threat indicators, and operational productivity signals without hiding system behavior from administrators. The product combines a React frontend, a FastAPI backend, and a Python endpoint agent, so every agent working in this repository must protect product integrity across those layers.

## General Agent Responsibilities

- Work from repository evidence first. Prefer existing code, docs, and tests over assumptions.
- Keep changes scoped. Solve the assigned problem without creating unrelated architectural drift.
- Respect tenant isolation, security boundaries, auditability, and privacy requirements in every change.
- Leave clear outputs. Summaries, diffs, and implementation notes must state what changed, what was verified, and what remains unverified.
- Reuse current contracts where possible. Avoid inventing duplicate APIs, schemas, or event flows when the repo already has a working pattern.
- Treat endpoint, backend, and frontend work as one product surface. Changes in one layer often require validation in the others.

## Communication Protocols

### Task Assignment

- Read the request, identify the affected subsystem, and choose the most relevant specialized agent.
- If a task spans multiple subsystems, split it into explicit responsibilities before implementation.
- Escalate security-sensitive or schema-affecting changes early instead of making silent assumptions.

### Inter-Agent Handoff

- A frontend agent should document required backend contracts, payload fields, and user-state assumptions.
- A backend agent should document route changes, schema implications, background jobs, and migration requirements.
- An endpoint agent developer should document transport behavior, collection impact, OS-specific assumptions, and enforcement limits.
- A codebase explorer should document concrete reproduction steps, test commands, missing coverage, and severity.
- A project manager agent should document scope, owner, dependencies, release risk, and verification status across all tracks.

### Reporting Format

- State the goal.
- State the files or modules touched.
- State the verification performed.
- State risks, follow-ups, or unanswered questions.

## File Structure And Naming Conventions

Top-level product structure in this repository:

- `frontend/`: React and Vite customer and platform portals.
- `backend/`: FastAPI APIs, services, repositories, tests, and operational entrypoints.
- `agent/`: Python endpoint agent, collectors, transports, DLP logic, and runtime modules.
- `gateway/`: edge routing and deployment-facing gateway configuration.
- `docs/`: product documentation, diagrams, guides, and operational references.
- `installer/`: Windows agent packaging, manifests, and distribution helpers.
- `ops/` and `tools/`: operational utilities, scripts, and support tooling.

Naming rules:

- Use descriptive, subsystem-aligned filenames.
- Prefer consistency with existing module naming before introducing new patterns.
- Keep agent configs in `.codex/agents/`.
- Keep reusable workflow skills in `.agents/skills/`.

## Security And Privacy Guidelines

- Never weaken tenant isolation, authorization checks, or audit trails for convenience.
- Treat endpoint telemetry, screenshots, browser history, keystroke-derived signals, and DLP evidence as sensitive data.
- Follow detection-first transparency: unsupported enforcement must fail visibly rather than pretending coverage exists.
- Minimize exposure of raw evidence. Preserve masking and redaction patterns already present in the product.
- Do not hardcode secrets, tokens, credentials, or environment-specific endpoints.
- Flag any vulnerability, privilege-escalation path, insecure default, or data-retention risk as a first-class issue.

## Development Workflow

### Feature Work

1. Identify the target user workflow or product requirement.
2. Inspect the relevant frontend, backend, and agent modules before editing.
3. Reuse existing contracts, models, and telemetry flows where possible.
4. Implement the change with minimal surface-area drift.
5. Verify the affected layer and any cross-layer dependencies.
6. Report completed work, verification, and residual risks.

### Bug Fixing

1. Reproduce or trace the failure from concrete evidence.
2. Find the true source module rather than patching symptoms only.
3. Apply the smallest reliable fix that preserves current product behavior.
4. Verify the regression path and note any missing automated coverage.

### Research And Analysis

1. Anchor findings in dated evidence.
2. Compare competitor claims to current CropSentinel capabilities honestly.
3. Separate implemented features, partial foundations, and missing capabilities.
4. Convert research into actionable product implications when asked.

## Collaboration Boundaries

- Do not overwrite unrelated user changes.
- Do not fabricate test results, deployment status, or security guarantees.
- Ask for clarification only when the missing detail would create real product risk.
- Prefer explicit assumptions over silent ones when work touches privacy, enforcement, billing, licensing, or live infrastructure.

## Repo-Local Worker Roster

Use the following workers from `.codex/agents/`:

- `super_project_manager.toml`: Orchestrates multi-step work, splits responsibilities, tracks blockers, and decides release-readiness.
- `backend_worker.toml`: Owns FastAPI routers, services, DB methods, tests, tenant isolation, DLP/phishing contracts, and migration-aware backend changes.
- `frontend_worker.toml`: Owns React/Vite UX, route guards, state assumptions, API wiring, smoke coverage, and regression checks.
- `endpoint_worker.toml`: Owns the Python endpoint agent, collectors, offline transport, file/DLP instrumentation, Windows service behavior, and runtime safety.
- `codebase_explorer.toml`: Performs read-first sweeps for bugs, missing coverage, risky assumptions, and broken contracts across the whole repo.
- `market_research_worker.toml`: Compares CropSentinel against current market claims, turns competitor patterns into dated product implications, and keeps capability claims honest.
- `productivity_explorer.toml`: Maps the machine-wise productivity feature end-to-end across frontend, backend, and agent telemetry before implementation begins.
- `productivity_feature_worker.toml`: Owns machine-wise productivity feature delivery across scoring logic, UX, telemetry assumptions, and regression checks.

## Default Task Routing

- Product planning, milestone slicing, cross-team dependencies, or release risk: `super_project_manager.toml`
- API breakage, ingestion bugs, auth issues, tenant leakage, schema drift, reporting bugs: `backend_worker.toml`
- UI defects, route guards, state bugs, dashboard regressions, build or e2e issues: `frontend_worker.toml`
- Agent runtime bugs, collector gaps, packaging/runtime drift, DLP destination handling, offline queue issues: `endpoint_worker.toml`
- Unknown failures, repo understanding, missing tests, bug hunting, quality sweeps, release gap analysis: `codebase_explorer.toml`
- Competitor analysis, feature-gap validation, positioning checks, and dated market scans: `market_research_worker.toml`
- Productivity feature discovery, score-trace audits, telemetry-flow mapping, and machine-wise workflow understanding: `productivity_explorer.toml`
- Machine-wise productivity implementation, productivity scoring changes, and productivity UX or contract delivery: `productivity_feature_worker.toml`

## Reusable Skills

Use the following workflows from `.agents/skills/` when they fit:

- `orchestrate_release_readiness.SKILL.md`
- `backend_tenant_safety.SKILL.md`
- `frontend_regression_sweep.SKILL.md`
- `endpoint_runtime_audit.SKILL.md`
- `codebase_bug_hunt.SKILL.md`
- `machine_productivity_planning.SKILL.md`
- `market_competitor_research.SKILL.md`

## Recommended Operating Pattern

1. Start with `codebase_explorer.toml` if the failure is unclear.
2. For machine-wise productivity work, use `productivity_explorer.toml` before changing score logic or UI behavior.
3. Use `market_research_worker.toml` when feature planning depends on current competitor claims or category norms.
4. Hand the confirmed subsystem issue to the matching specialized worker.
5. Use `productivity_feature_worker.toml` when the work crosses productivity scoring, productivity UX, and telemetry assumptions together.
6. Use `super_project_manager.toml` when work spans frontend, backend, and endpoint together.
7. For release-sensitive work, require the project manager to collect verification evidence from each worker before calling the task complete.
