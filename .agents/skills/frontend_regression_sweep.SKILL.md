# Frontend Regression Sweep

Use this skill when a change affects React views, route guards, API state, or operator workflows.

## Focus

- build stability
- type safety
- route-guard behavior
- dashboard and platform flows
- websocket and notification assumptions

## Workflow

1. Identify the page, hook, or shared state entrypoint.
2. Trace the backend fields the UI expects.
3. Check route access rules for customer versus platform users.
4. Run the cheap guard scripts before wider browser checks.
5. Record visible regressions in plain operator language.

## Minimum Verification

```powershell
npm.cmd run build
npm.cmd run typecheck
npm.cmd run check:ws-order
npm.cmd run check:ui-ux-guards
```
