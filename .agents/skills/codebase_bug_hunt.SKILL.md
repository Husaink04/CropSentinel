# Codebase Bug Hunt

Use this skill when the problem is unclear, when the user asks for a review, or when you need to find missing things before implementation.

## Focus

- broken contracts between frontend, backend, and agent
- missing tests for risky flows
- docs that no longer match runtime behavior
- silent tenant leakage or auth assumptions
- build, type, or smoke failures

## Workflow

1. Start with repo evidence, not guesswork.
2. Identify the subsystem owner for each finding.
3. Rank findings by product risk:
   - tenant isolation or auth
   - data loss prevention or phishing correctness
   - runtime or build breakage
   - user-facing workflow regressions
   - lower-priority cleanup
4. For each finding, include:
   - what is wrong
   - where it lives
   - why it matters
   - who should fix it
5. Only propose code changes after the failure path is concrete.

## Minimum Verification

```powershell
py -m pytest backend\tests\test_smoke.py -q
py -m pytest backend\tests\test_tenant_isolation.py -q
npm.cmd run build
```
