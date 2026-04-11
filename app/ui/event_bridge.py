from textual.message import Message
from ..core.events import bus, LogEvent, StatsUpdateEvent, IpMatchEvent, WorkerErrorEvent

class UILogMessage(Message):
    def __init__(self, message: str, level: str = "info"):
        super().__init__()
        self.message = message
        self.level = level

class UIStatsUpdate(Message):
    def __init__(self, stats):
        super().__init__()
        self.stats = stats

def bridge_events(app) -> None:
    """Subscribe UI messages and notifications to the shared event bus."""
    
    @bus.subscribe(LogEvent)
    def on_log(event: LogEvent):
        app.post_message(UILogMessage(event.message, event.level))

    @bus.subscribe(StatsUpdateEvent)
    def on_stats(event: StatsUpdateEvent):
        app.post_message(UIStatsUpdate(event.stats))

    @bus.subscribe(IpMatchEvent)
    def on_match(event: IpMatchEvent):
        app.notify(f"🌟 IP FOUND: {event.ip}", severity="information", timeout=10)

    @bus.subscribe(WorkerErrorEvent)
    def on_error(event: WorkerErrorEvent):
        app.post_message(UILogMessage(f"❌ {event.error}", "error"))
        app.notify(event.error, severity="error")
