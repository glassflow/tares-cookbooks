"""The in-process NavFlow data plane — the "dummy".

Register sources (each an async fn that returns Records), define a view over a set of sources, and
on `query` the plane gathers them concurrently and consolidates them into ONE time-ordered payload.
Everything runs in the cookbook process — no external service. The agent's read path is identical to
what a real NavFlow deployment would serve; only the internals here are simulated, so you can swap
this for a hosted NavFlow later without touching the agent.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass
class Record:
    source: str
    text: str
    ago: float = 0.0  # seconds before "now"; larger = older


class DataPlane:
    def __init__(self):
        self._sources = {}   # name -> async fn(key, window) -> list[Record]
        self._views = {}     # name -> {"key_field": str, "sources": [str]}

    def source(self, name):
        """Decorator: register an async source fn under `name`."""
        def deco(fn):
            self._sources[name] = fn
            return fn
        return deco

    def add_source(self, name, fn):
        self._sources[name] = fn

    def define_view(self, name, key_field, sources):
        self._views[name] = {"key_field": key_field, "sources": list(sources)}

    async def query(self, view: str, key: str, window: str) -> str:
        """Gather the view's sources concurrently, merge, time-order, and render one payload."""
        spec = self._views[view]
        fns = [self._sources[s] for s in spec["sources"] if s in self._sources]
        gathered = await asyncio.gather(*(fn(key, window) for fn in fns), return_exceptions=True)

        records: list[Record] = []
        for r in gathered:
            if isinstance(r, Exception):
                continue
            records.extend(r)
        records.sort(key=lambda rec: -rec.ago)  # oldest first

        lines = [f"=== {view} · key={key} · window={window} · ONE NavFlow read ===", ""]
        for rec in records:
            ago = int(max(rec.ago, 0))
            for ln in (rec.text or "").splitlines() or [""]:
                lines.append(f"[T-{ago}s] [{rec.source}] {ln}")
        if not records:
            lines.append("(no events for this key in the window)")
        return "\n".join(lines)
