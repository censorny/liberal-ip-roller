import asyncio
from typing import Dict, List, Callable, Any, Type, TypeVar, Optional

T = TypeVar("T")

class Event:
    """Base class for all application events."""
    pass

class LogEvent(Event):
    def __init__(self, message: str, level: str = "info"):
        self.message = message
        self.level = level

class StatsUpdateEvent(Event):
    def __init__(self, stats: Any):
        self.stats = stats

class IpMatchEvent(Event):
    def __init__(self, ip: str):
        self.ip = ip

class WorkerErrorEvent(Event):
    def __init__(self, error: str):
        self.error = error

class EventBus:
    """Simple asynchronous event bus to decouple logic from UI/IO."""
    
    def __init__(self):
        self._listeners: Dict[Type[Event], List[Callable]] = {}

    def subscribe(self, event_type: Type[Event], callback: Optional[Callable] = None):
        def decorator(func: Callable):
            if event_type not in self._listeners:
                self._listeners[event_type] = []
            self._listeners[event_type].append(func)
            return func
        
        if callback is None:
            return decorator
        return decorator(callback)

    async def emit(self, event: Event):
        event_type = type(event)
        if event_type in self._listeners:
            tasks = []
            for callback in self._listeners[event_type]:
                if asyncio.iscoroutinefunction(callback):
                    tasks.append(callback(event))
                else:
                    callback(event)
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

# Global instance for easy access
bus = EventBus()
