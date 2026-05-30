# Machine Productivity Planning

Use this skill when the user wants to evaluate, redesign, or extend machine-wise productivity in CropSentinel.

## Goal

Create a plan from current repo evidence, not from generic employee-monitoring ideas.

## Workflow

1. Start with `productivity_explorer.toml` or equivalent read-first tracing.
2. Inventory the current UX and routes:
   - `/productivity`
   - `/machines/:machineId/productivity`
   - `/teams/:teamId/productivity`
3. Separate each metric by source:
   - app activity
   - browser activity
   - input activity
   - settings-driven productive and unproductive lists
4. Check for split formulas or conflicting semantics between:
   - today-only score
   - date-range machine score
   - team aggregates
   - dashboard previews
5. Produce a planning output with:
   - current capability
   - trusted signals
   - weak or inferred signals
   - feature gaps
   - implementation order
6. Keep privacy and transparency explicit whenever activity evidence gets richer.

## Minimum Verification

```powershell
py -m pytest backend\tests\test_permissions.py -q
npm.cmd run build
```
