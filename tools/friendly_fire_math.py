"""Reusable Friendly Fire level-math API.

Import this module from level checkers or level generators instead of shelling
out to the validator CLI.
"""

from .validate_friendly_fire import (
    DIRS,
    Issue,
    RouteResult,
    World,
    extract_html_cards,
    find_level,
    load_cards,
    load_html_cards,
    parse_level_cards,
    plan_pushable_to,
    projectile_destroys_target,
    projectile_reaches_tile,
    route_destroys_expected,
)

__all__ = [
    "DIRS",
    "Issue",
    "RouteResult",
    "World",
    "extract_html_cards",
    "find_level",
    "load_cards",
    "load_html_cards",
    "parse_level_cards",
    "plan_pushable_to",
    "projectile_destroys_target",
    "projectile_reaches_tile",
    "route_destroys_expected",
]
