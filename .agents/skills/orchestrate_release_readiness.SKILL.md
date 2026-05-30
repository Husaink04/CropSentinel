# Orchestrate Release Readiness

Use this skill when a task spans multiple CropSentinel layers or when the user asks for a production-ready result.

## Goal

Drive the work like a project manager instead of a single undifferentiated agent.

## Steps

1. Define the user-facing outcome.
2. Split the work by owner:
   - backend
   - frontend
   - endpoint
   - codebase explorer
3. Identify dependency order.
4. Mark release blockers explicitly:
   - tenant isolation
   - auth and enrollment
   - DLP/phishing correctness
   - evidence privacy
   - broken build or smoke coverage
5. Require verification evidence from each owner before closing.

## Expected Output

- Scope
- Owner map
- Dependencies
- Verification status
- Remaining risk
