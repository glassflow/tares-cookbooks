"""The push half: a simple condition watcher. Poll a predicate; when it fires, hand back the
correlated view so the agent can be woken with the timeline already attached (zero reads to begin).
"""
import asyncio
import time


class Trigger:
    def __init__(self, name, dp, view, key, condition, window: str = "15m"):
        self.name = name
        self.dp = dp
        self.view = view
        self.key = key
        self.condition = condition  # async fn() -> falsy | detail
        self.window = window

    async def wait(self, poll: float = 3, timeout: float = 120):
        start = time.time()
        while time.time() - start < timeout:
            detail = await self.condition()
            if detail:
                payload = await self.dp.query(self.view, self.key, self.window)
                return {
                    "fired_after": round(time.time() - start, 1),
                    "detail": detail,
                    "payload": payload,
                }
            await asyncio.sleep(poll)
        return None
