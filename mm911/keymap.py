"""Keyboard map: one table that the UI renders as its shortcut sheet.

Keeping the keys here (instead of only in app.js) means the palette, the shortcut sheet and the
README cannot drift apart, and every entry can be tested."""
from __future__ import annotations

# (keys, what, group)
SHORTCUTS = [
    ("⌘K / Ctrl+K", "Search everything (the palette)", "Search"),
    ("Ctrl+Shift+P", "Search settings only", "Search"),
    ("?", "Show this shortcut sheet", "Search"),
    ("/", "Jump to the settings search box", "Search"),
    ("Ctrl+R", "Render one video", "Render"),
    ("Ctrl+Shift+R", "Render a batch", "Render"),
    ("Ctrl+P", "Upload the queue to YouTube", "Publish"),
    ("Ctrl+L", "My videos", "Library"),
    ("Ctrl+Z", "Undo", "Edit"),
    ("Ctrl+Shift+Z / Ctrl+Y", "Redo", "Edit"),
    ("Esc", "Close whatever is open", "App"),
]


def sheet(**extra: str) -> list[dict]:
    """The sheet the UI shows, optionally with platform labels switched (e.g. ``mod="Cmd"``)."""
    return [{"keys": k, "what": w, "group": g} for k, w, g in SHORTCUTS]


def groups() -> list[str]:
    seen: list[str] = []
    for _k, _w, g in SHORTCUTS:
        if g not in seen:
            seen.append(g)
    return seen
