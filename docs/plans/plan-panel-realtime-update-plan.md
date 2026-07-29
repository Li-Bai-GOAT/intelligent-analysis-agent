# Plan: Make the right-side Plan panel update in realtime

## Context

The project already creates and executes analysis plans, but the right-side Plan panel can remain stuck at “暂无分析计划”. The backend emits live SSE `plan` events from `AgentService`, and `/api/plans/{session_id}` can read persisted `PlanNotebook` state after the agent state is saved. The frontend gap is that `session.ts` currently ignores `type: "plan"` SSE events, while `PlanPanel.tsx` only fetches `/plans/{sessionId}` on mount/session change/manual refresh. As a result, a plan can exist and complete during execution without ever being reflected in the panel in realtime.

The intended outcome is: when DataPM creates or updates a plan, the right-side Plan panel immediately shows the plan and subtask progress, then reconciles with persisted backend state after completion or reload.

## Recommended approach

### 1. Add shared plan types

Modify `dataagent/frontend/src/types/index.ts`:

- Add frontend/backend-compatible plan interfaces, e.g. `PlanData` and `PlanSubtaskData`.
- Include both persisted API fields and live SSE fields:
  - plan `name`, `description`, `expected_outcome`, `state`
  - subtask `name`, `description`, `expected_outcome`, `state`
- Keep the existing lightweight `Plan`/`PlanSubtask` if other components rely on them, but make the new runtime plan type explicit.

### 2. Store live plan state in the session store

Modify `dataagent/frontend/src/stores/session.ts`:

- Add plan-related state to `SessionState`:
  - `currentPlan`
  - `planLoading`
  - `planError`
- Add actions:
  - `loadPlan(sessionId?: string)` — fetches `Api.getPlan` for the active session and updates `currentPlan`.
  - `setCurrentPlanFromStream(data: StreamData)` or inline equivalent normalization logic.
- Clear `currentPlan`, `planError`, and pending preview state on session switch before loading a different session.
- After loading session details in `selectSession`, call `loadPlan(sessionId)` so persisted plans restore after page refresh or session reopen.
- Add a `case 'plan'` in `handleStreamData` to convert the SSE payload `{ name, state, subtasks }` into `currentPlan` immediately.
- On stream `end`, call `loadPlan()` once to reconcile the live plan with persisted `StateRepository` state.

Reuse existing stream handling patterns in `handleStreamData`, especially the existing cases around `plan_preview`, `end`, and `interrupted`.

### 3. Make PlanPanel read from the store

Modify `dataagent/frontend/src/components/panels/PlanPanel.tsx`:

- Replace local one-shot `plan` ownership with `useSessionStore` selectors:
  - `currentPlan`
  - `planLoading`
  - `loadPlan`
- Keep local UI-only state such as `editing` and `newTaskTitle`.
- Keep existing display conversion helpers like `normalizeStatus` and `toViewPlan`, but feed them from store plan data.
- Manual refresh should call the store `loadPlan()` action.
- After `addSubtask` and `deleteSubtask`, call `loadPlan()` to refresh the shared store.
- Preserve current empty/loading UI copy, but optionally distinguish fetch errors from true empty state.

### 4. Refresh after plan preview confirmation

Modify `dataagent/frontend/src/components/chat/PreviewConfirm.tsx`:

- Read `loadPlan` from `useSessionStore`.
- After `Api.confirmPlanPreview(...)` or `Api.cancelPlanPreview(...)`, call `loadPlan(currentSession)`.
- Keep `clearPendingPreview()` and existing loading behavior.

This closes the stale UI gap after the user confirms/cancels a plan preview.

### 5. Backend check only if needed

Likely no backend change is required for the first fix. The existing hook already emits:

- `dataagent/app/services/agent_service.py` `plan_callback(...)` with `type: "plan"`
- subtask `name` and `state`

Only modify `dataagent/app/services/agent_service.py` if runtime testing shows the SSE `plan` event lacks a full enough snapshot for the UI. If changed, keep it minimal: include full current plan fields and all subtasks in the existing `plan_callback` event.

## Critical files

- `dataagent/frontend/src/types/index.ts`
- `dataagent/frontend/src/stores/session.ts`
- `dataagent/frontend/src/components/panels/PlanPanel.tsx`
- `dataagent/frontend/src/components/chat/PreviewConfirm.tsx`
- Optional only if needed: `dataagent/app/services/agent_service.py`

## Verification

1. Frontend static checks:
   - `cd dataagent/frontend`
   - `npm.cmd run lint`
   - `npm.cmd run build`
2. Runtime verification:
   - Start the app with the existing Windows workflow.
   - Log in and create/select a session.
   - Send a task that causes DataPM to create a plan.
   - Confirm that the right-side Plan panel changes from “暂无分析计划” to the live plan before the task ends.
   - Confirm subtask progress updates as `state` changes arrive over SSE.
   - Confirm/cancel a `plan_preview` and verify the panel refreshes without manual clicking.
   - Let the task finish, refresh the browser, reopen the same session, and verify the persisted plan is restored from `/api/plans/{session_id}`.
   - Switch to another session and verify the previous session’s plan does not remain visible.
3. Backend/API sanity check if needed:
   - Inspect browser network/SSE events for `type: "plan"` payloads.
   - Call `GET /api/plans/{session_id}` after completion to verify persisted state matches the final panel state.
