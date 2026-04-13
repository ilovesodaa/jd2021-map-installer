---
description: "Rewrite one mode section in MODES_GUIDE.md for clarity, with inline screenshot placeholders"
name: "Rewrite Mode Section"
argument-hint: "Mode name + optional notes (example: HTML mode, keep concise, add inline screenshot templates)"
agent: "agent"
---
Rewrite exactly one mode section in [MODES_GUIDE](../../docs/01_getting_started/MODES_GUIDE.md) using the provided arguments.

Goals:
1. Keep the section beginner-friendly and concise.
2. Avoid over-detail and avoid long technical deep-dives.
3. Place screenshot placeholders inline under the relevant step (not in a separate screenshot section).
4. Keep facts aligned with current project docs/settings.

Required workflow:
1. Read the current [MODES_GUIDE](../../docs/01_getting_started/MODES_GUIDE.md) before editing.
2. Identify the target mode from the user arguments.
3. Rewrite only that mode's section and its related table-of-contents sub-bullets as needed.
4. Keep other mode sections unchanged unless a small cross-reference fix is required.
5. Keep this prompt workspace-scoped only (`.github/prompts/`).

Use this section shape unless user explicitly asks otherwise:
- When to use it
- What you need
- Quick steps
- Quick troubleshooting

Inline screenshot template rules:
1. Add one screenshot placeholder directly below each key step.
2. Use paths under `../../assets/images/<mode-slug>/`.
3. Use numbered filenames in reading order, such as `01-...png`, `02-...png`.
4. Alt text should clearly describe the step.
5. Valid mode slugs in this workspace: `fetch`, `html`, `ipk`, `batch`, `manual`.

Output constraints:
1. Preserve Markdown heading levels and style used in the file.
2. Keep language practical and direct.
3. Do not invent features, settings, or tools that are not documented.
4. End with a short summary of what was changed.
