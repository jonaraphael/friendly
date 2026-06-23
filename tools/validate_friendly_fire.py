#!/usr/bin/env python3
"""Validate Friendly Fire level cards against the current primary ruleset.

This is a static authoring validator. It checks card syntax, HTML/card sync,
object placement, spawn safety, shield/color rules implied by routes, and each
declared route by simulating the engine's tile-level beam behavior.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


COLS = 19
ROWS = 13

DIRS: dict[str, tuple[int, int]] = {
    "E": (1, 0),
    "ENE": (2, -1),
    "NE": (1, -1),
    "NNE": (1, -2),
    "N": (0, -1),
    "NNW": (-1, -2),
    "NW": (-1, -1),
    "WNW": (-2, -1),
    "W": (-1, 0),
    "WSW": (-2, 1),
    "SW": (-1, 1),
    "SSW": (-1, 2),
    "S": (0, 1),
    "SSE": (1, 2),
    "SE": (1, 1),
    "ESE": (2, 1),
}

COORD_FIELDS = {
    "walls",
    "occlusions",
    "glass",
    "slitsV",
    "slitsH",
    "rails",
    "tracks",
    "markers",
}

BLOCKING_TILES = {"wall", "occlusion"}
PUSH_BLOCKED_TILES = {
    "wall",
    "occlusion",
    "glass",
    "mirror",
    "prism",
    "splitter",
    "slitV",
    "slitH",
}


@dataclass
class Issue:
    severity: str
    message: str
    level: str | None = None

    def render(self) -> str:
        prefix = self.severity.upper()
        if self.level:
            return f"{prefix}: {self.level}: {self.message}"
        return f"{prefix}: {self.message}"


@dataclass
class Beam:
    x: float
    y: float
    dx: int
    dy: int
    owner: str
    color: str
    last_tile: tuple[int, int]
    bounces: int = 0


@dataclass
class RouteResult:
    destroyed: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    visited: list[tuple[int, int]] = field(default_factory=list)


def number(value: str) -> int | float:
    try:
        n = float(value)
    except ValueError as exc:
        raise ValueError(f"expected number, got {value!r}") from exc
    if not math.isfinite(n):
        raise ValueError(f"expected finite number, got {value!r}")
    return int(n) if n.is_integer() else n


def value(raw: str) -> Any:
    if raw == "true":
        return True
    if raw == "false":
        return False
    if raw == "null":
        return None
    if re.fullmatch(r"-?\d+(?:\.\d+)?", raw):
        return number(raw)
    return raw


def orient(raw: str | None) -> str:
    if not raw:
        return "slash"
    return {"/": "slash", "\\": "back", "|": "vertical", "-": "horizontal"}.get(raw, raw)


def attrs(tokens: list[str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for token in tokens:
        if not token:
            continue
        if "=" not in token:
            raise ValueError(f"bad attr {token!r}")
        key, raw = token.split("=", 1)
        parsed[key] = orient(raw) if key == "o" else value(raw)
    return parsed


def coords(tokens: list[str]) -> list[dict[str, int]]:
    parsed = []
    for token in tokens:
        if not token:
            continue
        x_raw, y_raw = token.split(",", 1)
        parsed.append({"x": int(number(x_raw)), "y": int(number(y_raw))})
    return parsed


def base_level(name: str) -> dict[str, Any]:
    level: dict[str, Any] = {
        "name": name,
        "tutorial": False,
        "p": {"x": 1, "y": 10},
        "door": {"x": 9, "y": 12},
        "hint": "",
        "banner": "",
        "mirrors": [],
        "prisms": [],
        "splitters": [],
        "pushables": [],
        "turrets": [],
        "generators": [],
        "buttons": [],
        "doors": [],
        "routes": [],
    }
    for field_name in COORD_FIELDS:
        level[field_name] = []
    return level


def parse_level_cards(raw: str) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    level: dict[str, Any] | None = None

    def need_level(line: str) -> dict[str, Any]:
        if level is None:
            raise ValueError(f"line outside @level block: {line}")
        return level

    for idx, raw_line in enumerate(raw.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        if line.startswith("@level "):
            if level is not None:
                levels.append(level)
            level = base_level(line[7:].strip())
            continue
        if line == "@end":
            current = need_level(line)
            levels.append(current)
            level = None
            continue

        current = need_level(line)
        if line.startswith("hint "):
            current["hint"] = line[5:]
            continue
        if line.startswith("banner "):
            current["banner"] = line[7:]
            continue
        if line.startswith("route "):
            parts = [part.strip() for part in line[6:].split("|")]
            if len(parts) < 4:
                raise ValueError(f"bad route on line {idx}: {line}")
            name, source, direction, expect_raw = parts[:4]
            state_raw = "|".join(parts[4:]).strip()
            expect = [part.strip() for part in expect_raw.split(",") if part.strip()]
            current["routes"].append(
                {
                    "name": name,
                    "source": source,
                    "dir": direction,
                    "expect": expect,
                    "state": json.loads(state_raw) if state_raw else {},
                    "line": idx,
                }
            )
            continue

        tokens = line.split()
        cmd, args = tokens[0], tokens[1:]
        try:
            if cmd == "tutorial":
                current["tutorial"] = bool(value(args[0]))
            elif cmd in {"start", "p"}:
                current["p"] = {"x": int(number(args[0])), "y": int(number(args[1]))}
            elif cmd in {"exit", "door"}:
                current["door"] = {"x": int(number(args[0])), "y": int(number(args[1]))}
            elif cmd in COORD_FIELDS:
                current[cmd].extend(coords(args))
            elif cmd in {"mirror", "prism"}:
                obj = {"x": int(number(args[0])), "y": int(number(args[1])), "o": orient(args[2])}
                if len(args) > 3:
                    obj["id"] = args[3]
                current["mirrors" if cmd == "mirror" else "prisms"].append(obj)
            elif cmd == "splitter":
                obj = {"x": int(number(args[0])), "y": int(number(args[1]))}
                if len(args) > 2:
                    obj["id"] = args[2]
                current["splitters"].append(obj)
            elif cmd == "push":
                item = {
                    "id": args[0],
                    "kind": args[1],
                    "x": int(number(args[2])),
                    "y": int(number(args[3])),
                }
                i = 4
                if i < len(args) and "=" not in args[i]:
                    item["o"] = orient(args[i])
                    i += 1
                item.update(attrs(args[i:]))
                current["pushables"].append(item)
            elif cmd == "turret":
                turret = {"id": args[0], "x": int(number(args[1])), "y": int(number(args[2]))}
                turret.update(attrs(args[3:]))
                current["turrets"].append(turret)
            elif cmd == "generator":
                generator = {"id": args[0], "x": int(number(args[1])), "y": int(number(args[2]))}
                generator.update(attrs(args[3:]))
                generator.setdefault("req", None)
                current["generators"].append(generator)
            elif cmd == "button":
                button = {"id": args[0], "x": int(number(args[1])), "y": int(number(args[2]))}
                button.update(attrs(args[3:]))
                current["buttons"].append(button)
            elif cmd == "doorTile":
                door = {"x": int(number(args[0])), "y": int(number(args[1]))}
                door.update(attrs(args[2:]))
                current["doors"].append(door)
            else:
                raise ValueError(f"unknown card command {cmd!r}")
        except (IndexError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"line {idx}: {line}: {exc}") from exc

    if level is not None:
        levels.append(level)
    if not levels:
        raise ValueError("no level cards parsed")
    return levels


def extract_html_cards(html: str) -> str:
    match = re.search(
        r'<script id="level-cards" type="text/plain">\n([\s\S]*?)\n</script>',
        html,
    )
    if not match:
        raise ValueError("friendly_fire.html is missing the level-cards script block")
    return match.group(1).rstrip() + "\n"


def gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a


def norm_dir(dx: int, dy: int) -> tuple[int, int]:
    if dx == 0 and dy == 0:
        return (0, 0)
    divisor = gcd(abs(dx), abs(dy)) or 1
    dx //= divisor
    dy //= divisor
    if (dx, dy) in DIRS.values():
        return (dx, dy)

    angle = math.atan2(dy, dx)
    best = (1, 0)
    best_delta = 99.0
    for candidate in DIRS.values():
        candidate_angle = math.atan2(candidate[1], candidate[0])
        delta = abs(math.atan2(math.sin(candidate_angle - angle), math.cos(candidate_angle - angle)))
        if delta < best_delta:
            best_delta = delta
            best = candidate
    return best


def reflect(dx: int, dy: int, orientation: str) -> tuple[int, int]:
    if orientation == "slash":
        return norm_dir(-dy, -dx)
    if orientation == "back":
        return norm_dir(dy, dx)
    if orientation == "vertical":
        return norm_dir(-dx, dy)
    return norm_dir(dx, -dy)


def rot90(dx: int, dy: int, sign: int) -> tuple[int, int]:
    return norm_dir(-dy, dx) if sign > 0 else norm_dir(dy, -dx)


def color_next(color: str) -> str:
    return {"R": "G", "G": "B"}.get(color, "R")


def tile_key(x: int, y: int) -> tuple[int, int]:
    return (x, y)


class World:
    def __init__(self, level: dict[str, Any], state: dict[str, Any] | None = None):
        self.level = level
        self.state = state or {}
        self.grid = [["floor" for _ in range(COLS)] for _ in range(ROWS)]
        for y in range(ROWS):
            for x in range(COLS):
                if x == 0 or y == 0 or x == COLS - 1 or y == ROWS - 1:
                    self.grid[y][x] = "wall"

        def put(items: list[dict[str, int]], tile: str) -> None:
            for item in items:
                if self.in_bounds(item["x"], item["y"]):
                    self.grid[item["y"]][item["x"]] = tile

        put(level.get("walls", []), "wall")
        put(level.get("occlusions", []), "occlusion")
        put(level.get("glass", []), "glass")
        put(level.get("slitsV", []), "slitV")
        put(level.get("slitsH", []), "slitH")
        put(level.get("rails", []), "rail")
        put(level.get("tracks", []), "track")

        self.static_mirrors: dict[tuple[int, int], str] = {}
        for mirror in level.get("mirrors", []):
            key = tile_key(mirror["x"], mirror["y"])
            self.static_mirrors[key] = mirror["o"]
            if self.in_bounds(*key):
                self.grid[key[1]][key[0]] = "mirror"

        self.static_prisms: dict[tuple[int, int], str] = {}
        for prism in level.get("prisms", []):
            key = tile_key(prism["x"], prism["y"])
            self.static_prisms[key] = prism["o"]
            if self.in_bounds(*key):
                self.grid[key[1]][key[0]] = "prism"

        self.static_splitters: set[tuple[int, int]] = set()
        for splitter in level.get("splitters", []):
            key = tile_key(splitter["x"], splitter["y"])
            self.static_splitters.add(key)
            if self.in_bounds(*key):
                self.grid[key[1]][key[0]] = "splitter"

        for button in level.get("buttons", []):
            if self.in_bounds(button["x"], button["y"]):
                self.grid[button["y"]][button["x"]] = "button"
        for door in level.get("doors", []):
            if self.in_bounds(door["x"], door["y"]):
                self.grid[door["y"]][door["x"]] = "door"
        door = level["door"]
        if self.in_bounds(door["x"], door["y"]):
            self.grid[door["y"]][door["x"]] = "exit"

        self.pushables = {item["id"]: dict(item) for item in level.get("pushables", [])}
        for item_id, patch in self.state.get("pushables", {}).items():
            if item_id in self.pushables:
                if "x" in patch:
                    self.pushables[item_id]["x"] = int(patch["x"])
                if "y" in patch:
                    self.pushables[item_id]["y"] = int(patch["y"])
                if "o" in patch:
                    self.pushables[item_id]["o"] = orient(str(patch["o"]))

        self.turrets = {item["id"]: dict(item) for item in level.get("turrets", [])}
        self.generators = {item["id"]: dict(item) for item in level.get("generators", [])}
        self.dead_turrets = set(self.state.get("deadTurrets", []))
        self.dead_generators = set(self.state.get("deadGenerators", []))
        self.doors_open = set(self.state.get("doorsOpen", []))

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < COLS and 0 <= y < ROWS

    def tile_at(self, x: int, y: int) -> str:
        if not self.in_bounds(x, y):
            return "wall"
        return self.grid[y][x]

    def pushable_at(self, x: int, y: int) -> dict[str, Any] | None:
        for pushable in self.pushables.values():
            if int(pushable["x"]) == x and int(pushable["y"]) == y:
                return pushable
        return None

    def living_turret_at(self, x: int, y: int) -> dict[str, Any] | None:
        for turret_id, turret in self.turrets.items():
            if turret_id in self.dead_turrets:
                continue
            if int(turret["x"]) == x and int(turret["y"]) == y:
                return turret
        return None

    def living_generator_at(self, x: int, y: int) -> dict[str, Any] | None:
        for generator_id, generator in self.generators.items():
            if generator_id in self.dead_generators:
                continue
            if int(generator["x"]) == x and int(generator["y"]) == y:
                return generator
        return None

    def any_generators_alive(self) -> bool:
        return any(generator_id not in self.dead_generators for generator_id in self.generators)

    def door_open_at(self, x: int, y: int) -> bool:
        for door in self.level.get("doors", []):
            if int(door["x"]) == x and int(door["y"]) == y:
                return door.get("group", 0) in self.doors_open
        return True

    def line_blocker(self, x: int, y: int) -> bool:
        tile = self.tile_at(x, y)
        if tile in BLOCKING_TILES:
            return True
        if tile == "door" and not self.door_open_at(x, y):
            return True
        pushable = self.pushable_at(x, y)
        return bool(pushable and pushable.get("kind") == "block")

    def ray_reaches_player(self, turret: dict[str, Any], player: dict[str, int]) -> bool:
        tx, ty = int(turret["x"]), int(turret["y"])
        px, py = int(player["x"]), int(player["y"])
        direction = quantize16(px + 0.5 - (tx + 0.5), py + 0.5 - (ty + 0.5))
        x, y = tx + 0.5, ty + 0.5
        mag = math.hypot(direction[0], direction[1])
        vx, vy = direction[0] / mag, direction[1] / mag
        last: tuple[int, int] | None = None
        for _ in range(900):
            x += vx * 0.05
            y += vy * 0.05
            gx, gy = math.floor(x), math.floor(y)
            key = tile_key(gx, gy)
            if key == last:
                continue
            last = key
            if not self.in_bounds(gx, gy) or gx == 0 or gy == 0 or gx == COLS - 1 or gy == ROWS - 1:
                return False
            if gx == px and gy == py:
                return True
            if self.line_blocker(gx, gy):
                return False
        return False

    def simulate_route(self, route: dict[str, Any]) -> RouteResult:
        source_id = route["source"]
        source = self.turrets[source_id]
        dx, dy = DIRS[route["dir"]]
        mag = math.hypot(dx, dy)
        queue = deque(
            [
                Beam(
                    x=int(source["x"]) + 0.5 + (dx / mag) * 0.57,
                    y=int(source["y"]) + 0.5 + (dy / mag) * 0.57,
                    dx=dx,
                    dy=dy,
                    owner=source_id,
                    color=str(source.get("color", "R")),
                    last_tile=tile_key(int(source["x"]), int(source["y"])),
                )
            ]
        )
        result = RouteResult()
        processed = 0

        while queue and processed < 200:
            beam = queue.popleft()
            processed += 1
            self._run_beam(beam, queue, result)

        if queue:
            result.events.append("stopped after too many split branches")
        return result

    def trace_projectile_from_tile(
        self,
        start: tuple[int, int],
        direction: str,
        *,
        color: str = "R",
        owner: str = "__probe__",
    ) -> RouteResult:
        """Trace a projectile leaving a tile center in a named 16-way direction."""
        if direction not in DIRS:
            raise ValueError(f"unknown direction {direction!r}")
        dx, dy = DIRS[direction]
        mag = math.hypot(dx, dy)
        beam = Beam(
            x=start[0] + 0.5 + (dx / mag) * 0.57,
            y=start[1] + 0.5 + (dy / mag) * 0.57,
            dx=dx,
            dy=dy,
            owner=owner,
            color=color,
            last_tile=tile_key(start[0], start[1]),
        )
        result = RouteResult()
        queue = deque([beam])
        processed = 0
        while queue and processed < 200:
            processed += 1
            self._run_beam(queue.popleft(), queue, result)
        if queue:
            result.events.append("stopped after too many split branches")
        return result

    def _run_beam(self, beam: Beam, queue: deque[Beam], result: RouteResult) -> None:
        for _ in range(5000):
            if beam.bounces > 24:
                result.events.append("beam died after bounce limit")
                return

            beam.x += (beam.dx / math.hypot(beam.dx, beam.dy)) * 0.05
            beam.y += (beam.dy / math.hypot(beam.dx, beam.dy)) * 0.05
            gx, gy = math.floor(beam.x), math.floor(beam.y)
            key = tile_key(gx, gy)

            if key != beam.last_tile:
                action = self._handle_tile(beam, key, queue, result)
                if action == "dead":
                    return
                if action == "split":
                    return

            if self._handle_hit(beam, key, result) == "dead":
                return

        result.events.append("beam exceeded step limit")

    def _handle_tile(
        self, beam: Beam, key: tuple[int, int], queue: deque[Beam], result: RouteResult
    ) -> str:
        gx, gy = key
        result.visited.append(key)
        if not self.in_bounds(gx, gy):
            result.events.append("beam left bounds")
            return "dead"

        tile = self.tile_at(gx, gy)
        if tile in {"wall", "occlusion"}:
            result.events.append(f"beam blocked by {tile} at {gx},{gy}")
            return "dead"
        if tile == "exit":
            result.events.append(f"beam blocked by closed exit at {gx},{gy}")
            return "dead"
        if tile == "door" and not self.door_open_at(gx, gy):
            result.events.append(f"beam blocked by closed door at {gx},{gy}")
            return "dead"

        pushable = self.pushable_at(gx, gy)
        if pushable:
            kind = pushable.get("kind")
            if kind == "block":
                result.events.append(f"beam blocked by push block {pushable['id']} at {gx},{gy}")
                return "dead"
            if kind == "mirror":
                self._reflect(beam, orient(pushable.get("o")), prism=False)
                return "live"
            if kind == "prism":
                self._reflect(beam, orient(pushable.get("o")), prism=True)
                return "live"
            if kind == "splitter":
                self._split(beam, queue)
                return "split"

        if tile in {"glass", "rail", "track", "button"}:
            beam.last_tile = key
            return "live"
        if tile == "slitV" and abs(beam.dx) > abs(beam.dy):
            result.events.append(f"beam blocked by vertical slit at {gx},{gy}")
            return "dead"
        if tile == "slitH" and abs(beam.dy) > abs(beam.dx):
            result.events.append(f"beam blocked by horizontal slit at {gx},{gy}")
            return "dead"
        if tile == "mirror":
            self._reflect(beam, self.static_mirrors[key], prism=False)
            return "live"
        if tile == "prism":
            self._reflect(beam, self.static_prisms[key], prism=True)
            return "live"
        if tile == "splitter":
            self._split(beam, queue)
            return "split"

        beam.last_tile = key
        return "live"

    def _handle_hit(self, beam: Beam, key: tuple[int, int], result: RouteResult) -> str:
        gx, gy = key
        generator = self.living_generator_at(gx, gy)
        if generator:
            generator_id = generator["id"]
            required = generator.get("req")
            if required and required != beam.color:
                result.events.append(
                    f"{generator_id} absorbed wrong color {beam.color}, requires {required}"
                )
                return "dead"
            self.dead_generators.add(generator_id)
            result.destroyed.append(generator_id)
            result.events.append(f"destroyed {generator_id} with {beam.color}")
            return "dead"

        turret = self.living_turret_at(gx, gy)
        if turret:
            turret_id = turret["id"]
            if turret_id == beam.owner and beam.bounces == 0:
                return "live"
            if turret.get("shielded") and self.any_generators_alive():
                result.events.append(f"{turret_id} shield absorbed hit while generator alive")
                return "dead"
            required = turret.get("req")
            if required and required != beam.color:
                result.events.append(
                    f"{turret_id} absorbed wrong color {beam.color}, requires {required}"
                )
                return "dead"
            self.dead_turrets.add(turret_id)
            result.destroyed.append(turret_id)
            result.events.append(f"destroyed {turret_id} with {beam.color}")
            return "dead"
        return "live"

    def _reflect(self, beam: Beam, orientation: str, prism: bool) -> None:
        beam.dx, beam.dy = reflect(beam.dx, beam.dy, orientation)
        if prism:
            beam.color = color_next(beam.color)
        beam.bounces += 1
        gx, gy = math.floor(beam.x), math.floor(beam.y)
        mag = math.hypot(beam.dx, beam.dy)
        beam.x = gx + 0.5 + (beam.dx / mag) * 0.62
        beam.y = gy + 0.5 + (beam.dy / mag) * 0.62
        beam.last_tile = tile_key(gx, gy)

    def _split(self, beam: Beam, queue: deque[Beam]) -> None:
        gx, gy = math.floor(beam.x), math.floor(beam.y)
        for dx, dy in [rot90(beam.dx, beam.dy, 1), rot90(beam.dx, beam.dy, -1)]:
            dx, dy = norm_dir(dx, dy)
            mag = math.hypot(dx, dy)
            queue.append(
                Beam(
                    x=gx + 0.5 + (dx / mag) * 0.62,
                    y=gy + 0.5 + (dy / mag) * 0.62,
                    dx=dx,
                    dy=dy,
                    owner=beam.owner,
                    color=beam.color,
                    last_tile=tile_key(gx, gy),
                    bounces=beam.bounces + 1,
                )
            )


def quantize16(dx: float, dy: float) -> tuple[int, int]:
    angle = math.atan2(dy, dx)
    best = DIRS["E"]
    best_delta = 99.0
    for candidate in DIRS.values():
        candidate_angle = math.atan2(candidate[1], candidate[0])
        delta = abs(math.atan2(math.sin(candidate_angle - angle), math.cos(candidate_angle - angle)))
        if delta < best_delta:
            best_delta = delta
            best = candidate
    return best


def load_cards(cards_path: str | Path = "friendly_fire_cards.txt") -> list[dict[str, Any]]:
    """Load and parse a level-card file."""
    return parse_level_cards(Path(cards_path).read_text())


def load_html_cards(html_path: str | Path = "friendly_fire.html") -> list[dict[str, Any]]:
    """Load and parse the embedded level-card block from the HTML game file."""
    return parse_level_cards(extract_html_cards(Path(html_path).read_text()))


def find_level(levels: list[dict[str, Any]], name: str) -> dict[str, Any]:
    """Return a level by exact name."""
    for level in levels:
        if level["name"] == name:
            return level
    raise KeyError(f"unknown level {name!r}")


def projectile_reaches_tile(
    level: dict[str, Any],
    start: tuple[int, int],
    direction: str,
    target: tuple[int, int],
    *,
    state: dict[str, Any] | None = None,
    color: str = "R",
) -> tuple[bool, RouteResult]:
    """Return whether a projectile path visits a target tile under a board state."""
    world = World(level, state)
    owner_turret = world.living_turret_at(start[0], start[1])
    owner = owner_turret["id"] if owner_turret else "__probe__"
    result = world.trace_projectile_from_tile(start, direction, color=color, owner=owner)
    return target in result.visited, result


def projectile_destroys_target(
    level: dict[str, Any],
    start: tuple[int, int],
    direction: str,
    target_id: str,
    *,
    state: dict[str, Any] | None = None,
    color: str = "R",
) -> tuple[bool, RouteResult]:
    """Return whether a projectile destroys a named turret or generator."""
    world = World(level, state)
    owner_turret = world.living_turret_at(start[0], start[1])
    owner = owner_turret["id"] if owner_turret else "__probe__"
    result = world.trace_projectile_from_tile(start, direction, color=color, owner=owner)
    return target_id in result.destroyed, result


def route_destroys_expected(
    level: dict[str, Any],
    route_name: str,
) -> tuple[bool, RouteResult]:
    """Return whether a named route destroys exactly its declared expected targets."""
    route = next((item for item in level.get("routes", []) if item["name"] == route_name), None)
    if route is None:
        raise KeyError(f"unknown route {route_name!r}")
    result = World(level, route["state"]).simulate_route(route)
    return set(result.destroyed) == set(route["expect"]), result


def orientation_for_push(dx: int, dy: int, current: str | None = None, kind: str = "mirror") -> str | None:
    """Match the engine's push-to-orientation rule for mirrors and prisms."""
    if kind not in {"mirror", "prism"}:
        return current
    if dx > 0:
        return "slash"
    if dx < 0:
        return "back"
    if dy > 0:
        return "vertical"
    return "horizontal"


CARDINAL_DIRS: tuple[tuple[str, int, int], ...] = (
    ("E", 1, 0),
    ("W", -1, 0),
    ("S", 0, 1),
    ("N", 0, -1),
)


def plan_pushable_to(
    level: dict[str, Any],
    pushable_id: str,
    goal: tuple[int, int],
    *,
    orientation: str | None = None,
    state: dict[str, Any] | None = None,
    start: tuple[int, int] | None = None,
    max_states: int = 50000,
) -> list[str] | None:
    """Find a bounded player push plan for one pushable.

    Other pushables are treated as fixed blockers. The returned plan is a list
    of cardinal movement and push steps, or None if the target state is not
    found within max_states.
    """
    world = World(level, state)
    if pushable_id not in world.pushables:
        raise KeyError(f"unknown pushable {pushable_id!r}")
    target = dict(world.pushables[pushable_id])
    start_player = start or (int(level["p"]["x"]), int(level["p"]["y"]))
    initial_orientation = orient(target.get("o"))
    initial = (
        start_player[0],
        start_player[1],
        int(target["x"]),
        int(target["y"]),
        initial_orientation,
    )

    static_pushables = {
        item_id: dict(item) for item_id, item in world.pushables.items() if item_id != pushable_id
    }

    def pushable_at(x: int, y: int, state_key: tuple[int, int, int, int, str]) -> dict[str, Any] | None:
        _px, _py, tx, ty, target_orientation = state_key
        if tx == x and ty == y:
            item = dict(target)
            item["x"] = tx
            item["y"] = ty
            item["o"] = target_orientation
            return item
        for item in static_pushables.values():
            if int(item["x"]) == x and int(item["y"]) == y:
                return item
        return None

    def player_can_stand(x: int, y: int, state_key: tuple[int, int, int, int, str]) -> bool:
        tile = world.tile_at(x, y)
        if tile in {"wall", "occlusion", "glass", "mirror", "prism", "splitter", "slitV", "slitH"}:
            return False
        if tile == "door" and not world.door_open_at(x, y):
            return False
        if tile == "exit":
            return False
        if pushable_at(x, y, state_key):
            return False
        if world.living_turret_at(x, y) or world.living_generator_at(x, y):
            return False
        return True

    def target_can_move_to(x: int, y: int, state_key: tuple[int, int, int, int, str]) -> bool:
        tile = world.tile_at(x, y)
        if tile in PUSH_BLOCKED_TILES:
            return False
        if tile == "door" and not world.door_open_at(x, y):
            return False
        if tile == "exit":
            return False
        if tile == "rail" and target.get("kind") in {"mirror", "prism", "splitter"}:
            return False
        if pushable_at(x, y, state_key):
            return False
        if world.living_turret_at(x, y) or world.living_generator_at(x, y):
            return False
        return True

    queue: deque[tuple[int, int, int, int, str]] = deque([initial])
    parent: dict[tuple[int, int, int, int, str], tuple[tuple[int, int, int, int, str] | None, str]] = {
        initial: (None, "start")
    }

    while queue and len(parent) < max_states:
        current = queue.popleft()
        px, py, tx, ty, target_orientation = current
        if (tx, ty) == goal and (orientation is None or target_orientation == orient(orientation)):
            return reconstruct_plan(parent, current)

        for dir_name, dx, dy in CARDINAL_DIRS:
            nx, ny = px + dx, py + dy
            if nx == tx and ny == ty:
                bx, by = tx + dx, ty + dy
                if target_can_move_to(bx, by, current):
                    next_orientation = orientation_for_push(dx, dy, target_orientation, str(target.get("kind")))
                    next_state = (tx, ty, bx, by, next_orientation or target_orientation)
                    if next_state not in parent:
                        parent[next_state] = (
                            current,
                            f"push {dir_name} {pushable_id} -> {bx},{by}"
                            + (f" {next_state[4]}" if next_state[4] else ""),
                        )
                        queue.append(next_state)
            elif player_can_stand(nx, ny, current):
                next_state = (nx, ny, tx, ty, target_orientation)
                if next_state not in parent:
                    parent[next_state] = (current, f"move {dir_name} -> {nx},{ny}")
                    queue.append(next_state)

    return None


def reconstruct_plan(
    parent: dict[tuple[int, int, int, int, str], tuple[tuple[int, int, int, int, str] | None, str]],
    terminal: tuple[int, int, int, int, str],
) -> list[str]:
    steps: list[str] = []
    cursor: tuple[int, int, int, int, str] | None = terminal
    while cursor is not None:
        previous, action = parent[cursor]
        if previous is not None:
            steps.append(action)
        cursor = previous
    return list(reversed(steps))


def validate_levels(levels: list[dict[str, Any]]) -> list[Issue]:
    issues: list[Issue] = []
    seen_names: set[str] = set()
    for level in levels:
        name = level["name"]
        if name in seen_names:
            issues.append(Issue("error", "duplicate level name", name))
        seen_names.add(name)

        issues.extend(validate_structure(level))
        if any(issue.severity == "error" and issue.level == name for issue in issues):
            continue

        world = World(level)
        unsafe = []
        player_tile = (int(level["p"]["x"]), int(level["p"]["y"]))
        for turret in level.get("turrets", []):
            if not world.ray_reaches_player(turret, level["p"]):
                continue
            direction = quantize16(
                level["p"]["x"] + 0.5 - (int(turret["x"]) + 0.5),
                level["p"]["y"] + 0.5 - (int(turret["y"]) + 0.5),
            )
            direction_name = next(name for name, value in DIRS.items() if value == direction)
            result = World(level).simulate_route(
                {"source": turret["id"], "dir": direction_name, "state": {}}
            )
            if player_tile in result.visited:
                unsafe.append(turret["id"])
        if unsafe:
            issues.append(
                Issue(
                    "warning",
                    f"spawn is hit by turrets after first player action: {', '.join(unsafe)}",
                    name,
                )
            )

        if level.get("turrets") and not level.get("routes"):
            issues.append(Issue("warning", "level has turrets but no route oracles", name))

        target_ids = {item["id"] for item in level.get("turrets", []) + level.get("generators", [])}
        generator_ids = {item["id"] for item in level.get("generators", [])}
        shielded_ids = {item["id"] for item in level.get("turrets", []) if item.get("shielded")}

        for route in level.get("routes", []):
            for expected in route["expect"]:
                if expected not in target_ids:
                    issues.append(Issue("error", f"route {route['name']!r} expects unknown target {expected!r}", name))
            if route["source"] not in {item["id"] for item in level.get("turrets", [])}:
                issues.append(Issue("error", f"route {route['name']!r} has unknown source {route['source']!r}", name))
            if route["dir"] not in DIRS:
                issues.append(Issue("error", f"route {route['name']!r} has unknown direction {route['dir']!r}", name))

            unknown_pushables = set(route["state"].get("pushables", {})) - {
                item["id"] for item in level.get("pushables", [])
            }
            if unknown_pushables:
                issues.append(
                    Issue(
                        "error",
                        f"route {route['name']!r} references unknown pushables: {', '.join(sorted(unknown_pushables))}",
                        name,
                    )
                )

            if set(route["expect"]) & shielded_ids:
                declared_dead = set(route["state"].get("deadGenerators", []))
                missing = generator_ids - declared_dead
                if missing:
                    issues.append(
                        Issue(
                            "error",
                            f"route {route['name']!r} kills shielded target before all generators are dead: {', '.join(sorted(missing))}",
                            name,
                        )
                    )

            route_world = World(level, route["state"])
            if route["source"] in route_world.dead_turrets:
                issues.append(Issue("error", f"route {route['name']!r} uses a dead source turret", name))
                continue
            if route["source"] not in route_world.turrets or route["dir"] not in DIRS:
                continue

            result = route_world.simulate_route(route)
            expected = set(route["expect"])
            destroyed = set(result.destroyed)
            missing = expected - destroyed
            extra = destroyed - expected
            if missing:
                detail = "; ".join(result.events[:5]) or "no beam events"
                issues.append(
                    Issue(
                        "error",
                        f"route {route['name']!r} missed {', '.join(sorted(missing))}; events: {detail}",
                        name,
                    )
                )
            if extra:
                issues.append(
                    Issue(
                        "error",
                        f"route {route['name']!r} destroyed unexpected targets: {', '.join(sorted(extra))}",
                        name,
                    )
                )

    return issues


def validate_structure(level: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    name = level["name"]

    def check_point(label: str, point: dict[str, Any]) -> None:
        x, y = int(point["x"]), int(point["y"])
        if not (0 <= x < COLS and 0 <= y < ROWS):
            issues.append(Issue("error", f"{label} out of bounds at {x},{y}", name))

    check_point("start", level["p"])
    check_point("exit", level["door"])
    if level["door"]["y"] != ROWS - 1:
        issues.append(Issue("warning", "exit is not on the lower border", name))

    for field_name in COORD_FIELDS:
        for point in level.get(field_name, []):
            check_point(field_name, point)

    for collection in ["mirrors", "prisms", "splitters", "pushables", "turrets", "generators", "buttons", "doors"]:
        ids: set[str] = set()
        for item in level.get(collection, []):
            check_point(collection, item)
            item_id = item.get("id")
            if item_id:
                if item_id in ids:
                    issues.append(Issue("error", f"duplicate {collection} id {item_id!r}", name))
                ids.add(item_id)

    static_seen: dict[tuple[int, int], str] = {}

    def add_seen(kind: str, item: dict[str, Any]) -> None:
        key = tile_key(int(item["x"]), int(item["y"]))
        tag = f"{kind}:{item.get('id', '')}".rstrip(":")
        if key in static_seen:
            issues.append(Issue("warning", f"object overlap at {key[0]},{key[1]}: {static_seen[key]} and {tag}", name))
        else:
            static_seen[key] = tag

    for kind in ["mirrors", "prisms", "splitters", "pushables", "turrets", "generators"]:
        for item in level.get(kind, []):
            add_seen(kind[:-1], item)

    world = World(level)
    px, py = int(level["p"]["x"]), int(level["p"]["y"])
    start_tile = world.tile_at(px, py)
    if start_tile in PUSH_BLOCKED_TILES or world.pushable_at(px, py) or world.living_turret_at(px, py) or world.living_generator_at(px, py):
        issues.append(Issue("error", f"start is blocked by {start_tile} or an object", name))

    for pushable in level.get("pushables", []):
        tile = world.tile_at(int(pushable["x"]), int(pushable["y"]))
        if pushable.get("kind") in {"mirror", "prism", "splitter"} and tile == "rail":
            issues.append(Issue("warning", f"{pushable['id']} starts on a rail", name))

    if level.get("splitters") or any(item.get("kind") == "splitter" for item in level.get("pushables", [])):
        has_multi_target_route = any(len(route["expect"]) > 1 for route in level.get("routes", []))
        if not has_multi_target_route:
            issues.append(Issue("warning", "splitter level has no multi-target route oracle", name))

    return issues


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", default="friendly_fire.html", help="path to friendly_fire.html")
    parser.add_argument("--cards", default="friendly_fire_cards.txt", help="path to friendly_fire_cards.txt")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    args = parser.parse_args(argv)

    html_path = Path(args.html)
    cards_path = Path(args.cards)
    issues: list[Issue] = []

    try:
        html_cards = extract_html_cards(html_path.read_text())
        file_cards = cards_path.read_text()
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if html_cards.strip() != file_cards.strip():
        issues.append(Issue("error", f"{cards_path} differs from embedded cards in {html_path}"))

    try:
        levels = parse_level_cards(file_cards)
    except ValueError as exc:
        print(f"ERROR: {cards_path}: {exc}", file=sys.stderr)
        return 1

    issues.extend(validate_levels(levels))

    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    for issue in issues:
        print(issue.render())

    print(f"Validated {len(levels)} levels: {len(errors)} errors, {len(warnings)} warnings")
    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
