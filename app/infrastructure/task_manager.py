import asyncio
import logging
from typing import Any

class LifecycleManager:
    """
    Ensures that all background tasks are properly tracked and terminated.
    Prevents resource leaks during app shutdown or rotation stops.
    """
    
    def __init__(self):
        self._tasks: set[asyncio.Task[Any]] = set()

    def run_task(self, coro) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def shutdown(self):
        """Cancels all running tasks and waits for them to finalize."""
        if not self._tasks:
            return
            
        logging.info(f"Shutting down {len(self._tasks)} tasks...")
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
            
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        logging.info("Shutdown complete.")

app_lifecycle = LifecycleManager()
