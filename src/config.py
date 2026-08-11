"""Configuration management for the U1 Alert Notifier."""

import logging
import os
import sys

from dotenv import load_dotenv
from pydantic import ValidationError

from .models.config import Config as ConfigModel

# Load environment variables
load_dotenv()

def get_config() -> ConfigModel:
    """Load and validate configuration from environment variables."""
    try:
        printer_ip = os.getenv('PRINTER_IP', '')
        host = printer_ip.replace('ws://', '').replace('wss://', '').split(':')[0]
        config = ConfigModel(
            printer_ip=printer_ip,
            printer_port=int(os.getenv('PRINTER_PORT', '80')),
            api_key=os.getenv('MOONRAKER_API_KEY') or None,
            discord_webhook_url=os.getenv('DISCORD_WEBHOOK_URL', ''),
            poll_interval_minutes=int(os.getenv('POLL_INTERVAL_MINUTES', '5')),
            max_alerts_per_poll=int(os.getenv('MAX_ALERTS_PER_POLL', '10')),
            log_level=os.getenv('LOG_LEVEL', 'INFO').upper(),
            skip_initial_connection_test=os.getenv('SKIP_CONNECTION_TEST', 'true').lower() == 'true',
            notify_on_print_start=os.getenv('NOTIFY_ON_PRINT_START', 'true').lower() == 'true',
            notify_on_print_finish=os.getenv('NOTIFY_ON_PRINT_FINISH', 'true').lower() == 'true',
            notify_on_error=os.getenv('NOTIFY_ON_ERROR', 'true').lower() == 'true',
            notify_on_progress=os.getenv('NOTIFY_ON_PROGRESS', 'true').lower() == 'true',
            progress_milestones=[
                int(x.strip()) for x in os.getenv('PROGRESS_MILESTONES', '25,50,75').split(',')
                if x.strip().isdigit()
            ],
            camera_snapshot_url=os.getenv('CAMERA_SNAPSHOT_URL', f'http://{host}/server/files/camera/monitor.jpg'),
            notify_with_snapshot=os.getenv('NOTIFY_WITH_SNAPSHOT', 'true').lower() == 'true',
        )
        return config
    except (ValueError, ValidationError) as e:
        print(f"Configuration error: {e}")
        sys.exit(1)


def validate_config(config: ConfigModel) -> None:
    """Validate required configuration settings."""
    errors = []

    if not config.printer_ip:
        errors.append('PRINTER_IP is required')

    if not config.printer_port:
        errors.append('PRINTER_PORT is required')

    if not config.discord_webhook_url:
        errors.append('DISCORD_WEBHOOK_URL is required')

    if config.poll_interval_minutes < 1:
        errors.append('POLL_INTERVAL_MINUTES must be at least 1')

    if config.max_alerts_per_poll < 1:
        errors.append('MAX_ALERTS_PER_POLL must be at least 1')

    if errors:
        print('Configuration validation failed:')
        for error in errors:
            print(f'  - {error}')
        sys.exit(1)


def setup_logging(log_level: str) -> logging.Logger:
    """Set up structured logging with the specified level."""
    import structlog
    from colorama import init, Fore, Style

    # Initialize colorama for colored output
    init(autoreset=True)

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="ISO"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer(colors=True)
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level, logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        context_class=dict,
        cache_logger_on_first_use=True,
    )

    # Set up Python logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level, logging.INFO),
    )

    return structlog.get_logger("u1-notifier")


# Global configuration instance
config = get_config()
logger = setup_logging(config.log_level)
