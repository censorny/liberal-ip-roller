import asyncio
import signal
from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel

from ..core.events import bus, LogEvent, StatsUpdateEvent, IpMatchEvent, WorkerErrorEvent
from ..core.stats_formatter import format_rate_summary, format_top_subnets, format_uptime
from ..core.models import RollerStats
from ..controller import AppController

console = Console()


@dataclass(slots=True)
class HeadlessCliOptions:
    headless: bool = True
    service: str | None = None
    dry_run: bool = False
    config_path: str | None = None
    target_count: int | None = None

class HeadlessRunner:
    """
    Runner for headless (CLI) mode.
    Subscribes to events and prints them to the terminal.
    """
    
    def __init__(self, controller: AppController, cli_options: object | None = None):
        self.controller = controller
        self.stats: RollerStats | None = None
        self._stop_event = asyncio.Event()
        self._last_snapshot: tuple | None = None
        self.cli_options = self._normalize_cli_options(cli_options)

    @staticmethod
    def _normalize_cli_options(cli_options: object | None) -> HeadlessCliOptions:
        if cli_options is None:
            return HeadlessCliOptions()

        data = {
            "headless": getattr(cli_options, "headless", True),
            "service": getattr(cli_options, "service", None),
            "dry_run": getattr(cli_options, "dry_run", False),
            "config_path": getattr(cli_options, "config_path", None),
            "target_count": getattr(cli_options, "target_count", None),
        }
        return HeadlessCliOptions(**data)

    def _apply_cli_overrides(self) -> None:
        service_config = self.controller.config_provider.config.get_service_config()

        if self.cli_options.dry_run:
            service_config.process.dry_run = True

        if self.cli_options.target_count is not None and self.cli_options.target_count > 0:
            service_config.api.target_match_count = self.cli_options.target_count

    def _bridge_events(self):
        @bus.subscribe(LogEvent)
        def on_log(event: LogEvent):
            level_colors = {"info": "cyan", "success": "green", "warning": "yellow", "error": "red"}
            level_icons = {"info": "i", "success": "+", "warning": "!", "error": "x"}
            
            color = level_colors.get(event.level, "white")
            icon = level_icons.get(event.level, "i")
            console.print(f"[{color}]{icon} {event.message}[/{color}]")

        @bus.subscribe(StatsUpdateEvent)
        def on_stats(event: StatsUpdateEvent):
            self.stats = event.stats

        @bus.subscribe(IpMatchEvent)
        def on_match(event: IpMatchEvent):
            console.print(Panel(f"[bold green]*** MATCH DISCOVERED: {event.ip}[/bold green]", expand=False))

        @bus.subscribe(WorkerErrorEvent)
        def on_error(event: WorkerErrorEvent):
            console.print(f"[bold red]FATAL: {event.error}[/bold red]")

    def _stats_snapshot(self, stats: RollerStats) -> tuple:
        return (
            stats.attempts,
            stats.matches,
            stats.non_matches,
            stats.errors,
            stats.deleted_resources,
            stats.active_workers,
            stats.uptime_seconds,
            tuple((subnet.network, subnet.count) for subnet in stats.top_subnets),
        )

    def _render_stats_panel(self, stats: RollerStats) -> Panel:
        body = "\n".join(
            [
                (
                    f"Attempts: {stats.attempts} | Matches: {stats.matches} | Non-matches: {stats.non_matches} | "
                    f"Errors: {stats.errors}"
                ),
                (
                    f"Workers: {stats.active_workers} | Uptime: {format_uptime(stats.uptime_seconds)} | "
                    f"Unique IPs: {stats.unique_ip_count} | Unique subnets: {stats.unique_subnet_count}"
                ),
                format_rate_summary(stats),
                f"Top subnets: {format_top_subnets(stats.top_subnets).replace(chr(10), ' | ')}",
            ]
        )
        return Panel(body, title="Headless Stats", expand=False)

    def _render_final_summary(self, stats: RollerStats) -> Panel:
        lines = [
            f"Attempts: {stats.attempts}",
            f"Matches: {stats.matches}",
            f"Non-matches: {stats.non_matches}",
            f"Errors: {stats.errors}",
            f"Deleted resources: {stats.deleted_resources}",
            f"Uptime: {format_uptime(stats.uptime_seconds)}",
            format_rate_summary(stats),
            f"Top subnets:\n{format_top_subnets(stats.top_subnets)}",
        ]
        if stats.last_match_ip:
            lines.insert(1, f"Last match: {stats.last_match_ip}")
        if stats.last_error:
            lines.append(f"Last error: {stats.last_error}")
        return Panel("\n".join(lines), title="Session Summary", expand=False)

    def _apply_automatic_fallback(self) -> list[str]:
        config = self.controller.config_provider.config
        issues = self.controller.validate_active_service_config()
        if not issues:
            return issues

        if self.cli_options.service or self.cli_options.dry_run:
            return issues

        fallback_service = self.controller.find_first_ready_service()
        if fallback_service and fallback_service != config.active_service:
            console.print(
                f"[yellow]Active service {config.active_service} is not ready. "
                f"Switching to configured service {fallback_service} for this headless session.[/yellow]"
            )
            config.active_service = fallback_service
            self.cli_options.service = fallback_service
            self._apply_cli_overrides()
            return self.controller.validate_active_service_config()

        active_config = config.get_service_config()
        if active_config.process.allowed_ranges:
            console.print(
                f"[yellow]No fully configured provider found. Running {config.active_service} in dry-run mode for this headless session.[/yellow]"
            )
            active_config.process.dry_run = True
            self.cli_options.dry_run = True
            self._apply_cli_overrides()
            return self.controller.validate_active_service_config()

        return issues

    async def run(self) -> int:
        self._bridge_events()
        self._apply_cli_overrides()

        issues = self._apply_automatic_fallback()

        config = self.controller.config_provider.config
        service_name = config.active_service
        console.print(f"Active service: [bold]{service_name}[/bold]")
        if self.cli_options.config_path:
            console.print(f"Config path: [bold]{self.cli_options.config_path}[/bold]")
        if self.cli_options.dry_run:
            console.print("Mode: [bold]dry-run[/bold]")

        if issues:
            console.print("[bold red]Headless preflight failed.[/bold red]")
            for issue in issues:
                console.print(f"[red]- {issue}[/red]")
            if not self.cli_options.dry_run:
                console.print("[yellow]Tip:[/yellow] run with [bold]python main.py -h --dry-run[/bold] to test the pipeline without cloud credentials.")
            if not self.cli_options.service:
                console.print(
                    "[yellow]Tip:[/yellow] choose a provider explicitly with "
                    "[bold]--service yandex[/bold], [bold]--service regru[/bold], or [bold]--service selectel[/bold]."
                )
            return 1
        
        console.print("[bold cyan]Starting IP Roller in HEADLESS MODE...[/bold cyan]")
        console.print("Press [bold red]Ctrl+C[/bold red] to stop at any time.\n")

        try:
            started = await self.controller.start_rotation()
        except Exception as exc:
            console.print(f"[bold red]Startup failed: {exc}[/bold red]")
            return 1

        if not started:
            console.print("[yellow]Rotation is already running.[/yellow]")
            return 0
        
        # Setup signal handlers for graceful exit
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._stop_event.set)
            except NotImplementedError:
                # Signal handlers not implemented on some Windows environments
                pass

        try:
            # Main monitoring loop
            while not self._stop_event.is_set():
                if self.stats:
                    snapshot = self._stats_snapshot(self.stats)
                    if snapshot != self._last_snapshot:
                        console.print(self._render_stats_panel(self.stats))
                        self._last_snapshot = snapshot
                if self.controller.rotation_task and self.controller.rotation_task.done():
                    break
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            console.print("\n[bold yellow]Stopping and cleaning up cloud resources...[/bold yellow]")
            await self.controller.stop_rotation()
            if self.stats:
                console.print(self._render_final_summary(self.stats))
            console.print("[bold green]Shutdown complete.[/bold green]")
        return 0
