# Chat input visual QA

## Comparison target

- Source visual truth: `C:\Users\ASUS\AppData\Local\Temp\codex-clipboard-ef8650b1-810f-462a-9042-a485e3276497.png`
- Implementation route: `http://127.0.0.1:5173`
- Intended state: authenticated empty conversation, dark theme, desktop input area.
- Source dimensions: 1420 x 173 px.
- Implementation screenshot: not available. The local application redirects to its login screen and no authenticated test session was supplied.
- Viewport and density normalization: not applicable because the target component could not be reached in-browser.

## Implemented fidelity checks

The source's defining input-bar characteristics were applied in `frontend/src/components/chat/InputArea.tsx`:

- Typography: the editable text and placeholder scale from 18 px to 22 px on desktop, with a relaxed 32 px line-height.
- Layout rhythm: the bar is constrained by a centered 72 rem content width, while filling the available chat pane within that boundary. It has a 64 px minimum height, 28 px radius, and 8 px internal spacing.
- Colors and tokens: the dark project palette is retained; the empty-state placeholder uses the existing muted text token and focus uses the existing accent token.
- Assets and icons: existing Lucide upload, send, and stop icons are preserved; no image assets are required for this control.
- Copy: the new empty-state prompt is `问问 Data agent`.

## Findings

- [P2] Browser-rendered comparison is blocked by authentication.
  - Location: authenticated chat workspace.
  - Evidence: the local preview renders the DataAgent login screen before the chat route.
  - Impact: the actual post-login input bar cannot be visually compared with the supplied reference at the same state.
  - Fix: sign in to the local app, open an empty conversation, then capture the input bar at desktop width for final comparison.

## Implementation checklist

1. Confirm lint passes.
2. Confirm the production build passes.
3. After an authenticated chat session is available, verify the empty prompt, input focus state, mode controls, upload trigger, and send/stop action visually.

## Comparison history

1. 2026-08-08: source screenshot was opened; implementation code was updated and static checks passed. Browser verification was blocked at authentication before the chat workspace could be captured.

## Final result

final result: blocked
