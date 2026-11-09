# Video Mangler Workbench: UI rules

The look and behaviour every screen follows. Approved by the operator on 2026-10-23 from the design mockups (16 screens, built from the real v0.10.0 app). The mockups are kept outside the repo.

The goal: a finished, commercial-feeling app. Simple like CapCut, polished like Resolve. Every screen uses the same parts, so learning one screen teaches them all.

## 1. Words

- Every button, tab and setting keeps its current name unless a rule here renames it. Never show or mention a control that does not exist.
- Buttons are verbs: "Copy prompt for Claude Code", "Play the preview". Never "OK", "Submit" or "Go".
- Plain English, no internal terms (no "stage id", "payload", "worker").
- Each page starts with a title and one short line saying what the page is for.
- Empty states say what to do next, for example "No recording chosen." followed by the button that fixes it.

## 2. Colours (dark theme, the default)

| Token | Hex | Used for |
|---|---|---|
| ground | `#0E1014` | window background |
| nav | `#12151B` | left menu background |
| card | `#161A21` | cards and panels |
| card border | `#232833` | 1 px around cards |
| inner row | `#12151B` | rows and list items inside cards |
| input | `#0E1014` | text boxes, drop-downs; border `#2B313C` |
| text | `#E8EAED` | normal text |
| text soft | `#C9CED6` | secondary text in rows |
| muted | `#A3ACBA` | descriptions under titles |
| label | `#8C95A5` | small labels, column headers, hints |
| accent | `#2BB5C9` | primary buttons, selection bar, progress bars, focus ring |
| link | `#5FD3E3` | link-style buttons and links |
| selection | `#1D2A33` | selected row or item, with a 3 px accent bar on its left |
| running panel | `#11262C`, border `#1F5561`, bar track `#1F3A42` | job banners |
| done | `#6EE7A0` on `#1E3B2E` | status pills |
| needs a look | `#F5B94A` on `#2A2113`, border `#5C4518` | status pills and warning panels |
| failed | `#F08A7E` on `#3A1E1C`, strong `#B4413C` | status pills and error panels |
| waiting | `#A3ACBA` on `#232833` | status pills |
| proposal / new | text `#E3D5FF` on `#3B2A63` | mockups only; never in the app |

Light theme: same structure, with ground `#F5F7FA`, card `#FFFFFF`, border `#D9DEE5`, text `#14181F`, muted `#5A6472`, accent `#127C8C` (darker so it passes contrast on white), selection `#E3F3F5`. Pills keep their meaning with darker text on lighter tints.

The existing status meaning (`theme.py` STATUS_COLORS and status_kind) stays: green = working or done, amber = needs a look, red = failed, grey = waiting. Only the hex values move to these tokens. Running uses accent teal.

Contrast: body text at least 4.5:1 against its background, in both themes.

## 3. Text

- Font: Segoe UI (built into Windows; the mockups use Inter only because they render in a browser).
- At 100% text size: body 11 pt, small labels 9.5 pt, section headings 12.5 pt semibold, page titles 18 pt bold.
- Text size setting: 100%, 110%, 125%, 150%. It scales every font in the app and is remembered between runs. It lives in Settings > General / Startup, with keyboard shortcuts Ctrl+Plus, Ctrl+Minus and Ctrl+0 (back to 100%).
- Nothing may be cut off or overlap at 150% in a 1280×800 window.

## 4. Spacing and shape

- Spacing steps: 4, 8, 12, 16, 24 px. Page padding 24 px. Card padding 16 px. Gap between cards 14–16 px.
- Corner radius: cards 12 px, buttons and inputs 8–10 px, pills fully round.
- Cards group related controls under a short heading. A page is a few cards, not one long form.

## 5. Buttons

| Kind | Look | Rule |
|---|---|---|
| Primary | accent background, dark text `#0B1418`, bold, 40–48 px tall | One per card or area: the thing you most likely want next |
| Secondary | transparent, 1 px `#2B313C` border, normal text | Everything else |
| Danger | transparent, red border and red text | Cancel review, delete-type actions |
| Link | no border, link colour | Help, "See the prompt first", "Open in Queue / Progress" |

- Minimum height 36 px (32 px in dense toolbars such as the player). Hover and pressed states are visible.
- A disabled button looks clearly disabled, and the reason is shown next to it or on hover.
- Keyboard focus shows a 2 px accent ring on every control.

## 6. Inputs

- Every drop-down shows a visible down arrow (chevron). A drop-down must never look like a plain text box.
- Checkboxes are 16 px with a checked state in accent.
- Two to four exclusive choices (Workload, Decision, Text size) use a segmented control: one rounded box, the chosen part filled `#26303C` with white text.

## 7. Status and feedback

- **Status pill:** one shared widget for every status word in the app (History, Home Recent runs, Session Review, Queue / Progress items, Find my bug reports rows, AI Video Editor versions). The colour comes from status_kind.
- **Feedback where you click:** every action button gives visible feedback within a quarter of a second, next to the button that was clicked:
  - while it works: the button says what it is doing ("Copying…", "Rendering…") and cannot be clicked twice; the line beside it does not say it again, so the working word shows once (224, Decision 7);
  - when done: a short green confirmation beside it ("Copied", "Saved a moment ago"), which fades after a few seconds;
  - when it fails: a red line beside it saying what went wrong and what to do next. It stays until dismissed.
- **Job banner:** any job that runs longer than about 2 seconds (Prepare for the AI editor, Render a preview, Approve and export, Find bug reports, Process new media, a New Review run) shows a banner on the page where it was started: what is running, a progress bar, percent and time left when known, and a link "Open in Queue / Progress" that opens that exact job. While nothing is measured yet, it shows the step's words and a moving bar, never "0%" (224, Decision 6). A sentence telling the user to go and look elsewhere is not enough.
- **Step bar:** pages with a sequence (AI Video Editor, Find my bug reports; New Review keeps its own step list) show numbered steps. Done steps are green ticks, the current step is filled accent, later steps are grey outlines.

## 8. Selection, lists and tables

- A selected row or item has the selection background plus a 3 px accent bar on its left.
- Table headers use the label colour, 9.5 pt semibold. Rows are at least 32 px tall, with a 1 px divider `#1C2029`.
- Double-click plays a recording wherever recordings are listed (existing behaviour, keep it).

## 9. Left menu

- Order and groups: **Make**: Home, Find Bug Reports, AI Video Editor, New Review. **Library**: Raw Bin, Review Media Inbox. **Results**: Evidence, Session Review, Prompt Drafts, History. **Running**: Queue / Progress. Settings and Help sit at the bottom.
- Group labels are small, uppercase, in the label colour.
- Queue / Progress shows a badge with the number of jobs running or queued, and no badge when nothing is running.
- The selected page uses the selection style with the accent bar.
- The footer keeps "Evidence stays local until you approve sharing." and the build label.

## 10. Checking a screen

A screen follows these rules when:
1. it uses only the tokens above, with no one-off colours or sizes;
2. there is exactly one primary button per area;
3. every drop-down shows an arrow;
4. every action gives feedback next to the button;
5. long jobs show a job banner;
6. it reads correctly at 100% and 150% text size, in the dark and light themes;
7. nothing private shows in screenshots used for docs or tests.
