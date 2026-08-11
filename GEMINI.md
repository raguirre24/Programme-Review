# Gemini / Antigravity Context

Follow `AGENTS.md` in this workspace root in full — it defines the mandatory skills index (in `.agents/skills/`), the hard rules for P6/Power BI work, and workspace conventions. Nothing in this file overrides it.

Antigravity-specific notes:
- Skills in `.agents/skills/` should be auto-discovered; if a skill doesn't appear after adding or editing one, restart the agent session so they're re-detected.
- When planning multi-step tasks (implementation plans / task lists), name which skills each step will apply — it makes plan review faster and catches missed skills early.
- Artifacts and generated docs go in `docs/` or the location the task specifies, in NZ/UK English.
