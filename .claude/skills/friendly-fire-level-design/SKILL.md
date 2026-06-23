---
name: friendly-fire-level-design
description: Use when adding, fixing, auditing, or refactoring Friendly Fire levels, level-card syntax, or engine mechanics that affect beam routing, turrets, mirrors, prisms, splitters, shields, doors, rails, slits, or safe starts.
---

# Friendly Fire Level Design

Use this skill before changing `friendly_fire_cards.txt` or the embedded `<script id="level-cards">` block in `friendly_fire.html`.

## Where Information Lives

- Concrete level definitions live in the compact `@level` cards in `friendly_fire_cards.txt` and in the embedded level-card block inside `friendly_fire.html`.
- Reusable level-design constraints live in this skill.
- Current engine truth lives in `friendly_fire.html`; if prose or old notes disagree with the parser or runtime, follow the code and update this skill if the rule is durable.
- Historical 18x12 ASCII maps and `X`-based occlusion notes are not authoritative. Keep only their puzzle intent after translating it to current compact cards.

For a specific level such as `Borrowed Shot`, keep the exact start, exit, occlusions, marker, mirror, turret, and route lines in the level cards. Do not duplicate full room data here unless it is a short example.

## Card Format

The game uses a 19x13 tile grid. Coordinates are tile coordinates; `x=0`, `y=0`, `x=18`, and `y=12` are the outer border walls. The normal downward exit is on the lower border.

Use compact coordinate cards:

```text
@level Name
tutorial true|false
start x y
exit x y
hint free text
banner optional overlay text
walls x,y ...
occlusions x,y ...
glass x,y ...
slitsV x,y ...
slitsH x,y ...
rails x,y ...
tracks x,y ...
markers x,y ...
mirror x y slash|back|vertical|horizontal [id]
prism x y slash|back|vertical|horizontal [id]
splitter x y [id]
push id block|mirror|prism|splitter x y [orientation] [k=v ...]
turret id x y cooldown=2.6 timer=1.8 color=R req=G shielded=true mobile=true axis=x min=10 max=14 speed=.9 dir=1
generator id x y req=R|G|B|null
button id x y group=0
doorTile x y group=0
route name | source | DIR | expected[,expected2] | {json state}
@end
```

Supported route directions are the engine's 16 quantized directions:

```text
E ENE NE NNE N NNW NW WNW W WSW SW SSW S SSE SE ESE
```

`route` lines are design and validation oracles. Add one for every intended generator kill, turret kill, splitter branch, color conversion, and cleanup shot. Common state keys are `pushables`, `deadGenerators`, `deadTurrets`, and `doorsOpen`.

## Engine Mechanics To Preserve

- True occlusion is the `occlusions` command. Do not use `X`; old `X` notation is not parsed as an occluding tile.
- Turrets aim only along exact 16-direction lanes toward the player. A route that is merely "near" a target is not valid.
- Turrets do not start firing until the player has acted. Any movement input marks the player as having acted, including blocked movement; the touch-control wait action also starts turret firing.
- Line of sight is blocked by walls, occlusions, closed door tiles, and pushed blocks. Glass, rails, tracks, buttons, and open doors do not block turret sight.
- Lasers are blocked by walls, occlusions, closed doors, the closed exit, and pushed blocks. Glass, rails, tracks, buttons, and open doors pass lasers.
- Vertical slits pass mostly vertical beams and block mostly horizontal beams. Horizontal slits pass mostly horizontal beams and block mostly vertical beams.
- Slits are symmetric direction filters, not one-way gates. If a slit corridor connects two turrets, the return shot may be valid too; use shields/generators, color requirements, blockers, or source/target placement to make the intended order mandatory.
- Rails stop movable mirrors, movable prisms, and movable splitters. Rails do not stop the player, lasers, or pushed blocks.
- Pushing a movable mirror or prism sets its orientation: east push = `slash`, west push = `back`, south push = `vertical`, north push = `horizontal`.
- Mirrors reflect without changing color. Prisms reflect and advance color in this cycle: `R -> G -> B -> R`.
- A target with `req=R|G|B` is only destroyed by that color. Wrong-color hits are harmless absorptions.
- Shielded turrets can still aim and fire. They cannot be destroyed while any generator in the level is alive, so all generators must die before any shielded turret kill route.
- Splitters consume the incoming beam and emit only the two perpendicular branches. They do not emit forward, and they do not return a beam back toward the source.
- Runtime splitter children are processed on the next animation frame and active projectiles are capped for performance. Do not design levels that rely on unbounded splitter feedback or very high branch counts.
- Buttons are active when occupied by the player or a pushed block. Closed door tiles block movement, line of sight, and lasers.
- The exit opens only when every turret is dead. Generators alone do not open the exit.

## Validation Checklist

Before treating a level change as correct:

- Run `python3 tools/validate_friendly_fire.py` from the repo root.
- Keep `friendly_fire_cards.txt` and the embedded `friendly_fire.html` level-card block synchronized.
- Ensure the player start is safe from every living turret. The runtime `validateSpawn()` warning is useful but not a full solve proof.
- Check runtime console warnings from `validateSpawn()` and `validateNoOverlaps()` after loading changed rooms.
- Verify every route by exact beam geometry against the current engine. Check the beam enters each optical tile and exits into the intended target tile.
- Block unintended direct turret-to-turret shots, early generator kills, early shielded-turret hits, and bypasses that skip the level's main mechanic.
- For blue requirements from red sources, provide two prism reflections unless the route intentionally starts from a non-red source or revisits a prism in a verified way.
- For splitter puzzles, account for both perpendicular branches and explicitly prevent unwanted branch kills.
- Treat validator "too many split branches" events as a performance smell even when the route expectations pass.
- For slit puzzles, match slit orientation to the beam direction: shallow ENE/WNW style paths need horizontal slits, while steep NNE/SSE style paths need vertical slits. Also test the reverse direction if the route connects two firing objects.
- Preserve the needed source turret until cleanup. If the source can die early, the level may become impossible.
- If changing engine semantics, update this skill, the card quick reference comments, and any affected levels in the same patch.

## Helper API

Use `tools.friendly_fire_math` for level-checker and level-creator code that needs mechanical queries:

```python
from tools.friendly_fire_math import (
    find_level,
    load_cards,
    plan_pushable_to,
    projectile_destroys_target,
    projectile_reaches_tile,
    route_destroys_expected,
)

levels = load_cards()
level = find_level(levels, "First Color")

ok, trace = projectile_reaches_tile(level, (3, 8), "E", (12, 8))
plan = plan_pushable_to(level, "Q1", (8, 8), orientation="horizontal")
route_ok, result = route_destroys_expected(level, "green generator")
```

The helper API is intentionally mathematical and bounded. It can verify exact beam propagation, object destruction, route expectations, and whether a named pushable can be moved to a tile/orientation with other pushables treated as fixed blockers. It does not yet search full multi-object Sokoban solutions or time mobile turrets across their tracks.
