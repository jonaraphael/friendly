AGENTS.md is the canonical shared instruction file for this repository. CLAUDE.md is a thin Claude Code shim that imports this file.

## Scope

These instructions apply to the whole repository.

## Repo-Local Skills

Before substantial work, inspect the frontmatter in `.claude/skills/*/SKILL.md` and load any skill whose description matches the task. The canonical repo-local skill catalog is `.claude/skills`; `.agents/skills` should be a symlink mirror to that same catalog for Codex-native discovery.

Current repo-local skills:

- `.claude/skills/friendly-fire-level-design/SKILL.md`

High-priority triggers:

- Use `friendly-fire-level-design` before adding, fixing, auditing, or refactoring Friendly Fire levels.
- Use `friendly-fire-level-design` before changing level-card syntax or engine behavior that affects beams, mirrors, prisms, splitters, shields, doors, rails, slits, or turret line of sight.

## Project Notes

- `friendly_fire.html` contains the playable game, current engine implementation, and embedded `<script id="level-cards">` data.
- `friendly_fire_cards.txt` is the external level-card copy. Until there is a build step, keep it synchronized with the embedded level cards in `friendly_fire.html`.
- Treat `friendly_fire.html` as the source of truth for current engine mechanics. Old pasted ASCII layouts or prose audits are historical context only unless they match the current parser and runtime.

## Portability And Git

- Keep repo-local skill files portable: no user-specific absolute paths, shell profile assumptions, local machine names, or one-tool-only extensions unless explicitly documented.
- Preserve the user's Git index. Do not stage, unstage, reset, restore, or revert user changes unless the user asks for that exact operation.
- Prefer narrow, task-scoped edits. If engine behavior changes, update the level-design skill and level-card comments in the same change.
