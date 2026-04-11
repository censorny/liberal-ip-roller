import argparse
import asyncio
import sys
from dataclasses import dataclass

from storage import ConfigProvider


HEADLESS_FLAGS = {"--headless", "-h"}
VALID_SERVICES = ("yandex", "regru", "selectel")


@dataclass(slots=True)
class CliOptions:
    headless: bool = False
    service: str | None = None
    dry_run: bool = False
    config_path: str | None = None
    target_count: int | None = None


def is_headless_mode(argv: list[str] | None = None) -> bool:
    args = argv if argv is not None else sys.argv[1:]
    return any(flag in args for flag in HEADLESS_FLAGS)


def parse_cli_options(argv: list[str] | None = None) -> CliOptions:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-h", "--headless", action="store_true")
    parser.add_argument("--help", action="help", help="Show this help message and exit.")
    parser.add_argument("--service", choices=VALID_SERVICES)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--config", dest="config_path")
    parser.add_argument("--target-count", type=int)

    namespace, _unknown = parser.parse_known_args(argv)
    return CliOptions(
        headless=namespace.headless,
        service=namespace.service,
        dry_run=namespace.dry_run,
        config_path=namespace.config_path,
        target_count=namespace.target_count,
    )


def build_config_provider(options: CliOptions) -> ConfigProvider:
    provider = ConfigProvider(options.config_path) if options.config_path else ConfigProvider()
    config = provider.config

    if options.service:
        config.active_service = options.service

    service_config = config.get_service_config()
    if options.dry_run:
        service_config.process.dry_run = True

    if options.target_count is not None and options.target_count > 0:
        service_config.api.target_match_count = options.target_count

    return provider

async def run_headless(options: CliOptions | None = None) -> int:
    from app.controller import AppController
    from app.ui.headless import HeadlessRunner

    resolved_options = options or parse_cli_options(sys.argv[1:])
    provider = build_config_provider(resolved_options)
    controller = AppController(provider)
    runner = HeadlessRunner(controller, cli_options=resolved_options)
    return await runner.run()


def run_tui() -> None:
    from app.ui.app import LiberallyApp

    LiberallyApp().run()


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    options = parse_cli_options(args)

    try:
        if options.headless:
            return asyncio.run(run_headless(options))
        else:
            run_tui()
    except KeyboardInterrupt:
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
