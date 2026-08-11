"""Pydantic model for application configuration."""

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class Config(BaseModel):
    printer_ip: str = Field(default="")
    printer_port: int = Field(default=80)         # Moonraker/nginx port on the Snapmaker U1
    api_key: Optional[str] = Field(default=None)  # optional Moonraker API key (X-Api-Key header)
    discord_webhook_url: str = ""
    poll_interval_minutes: int = Field(default=5, ge=1)
    max_alerts_per_poll: int = Field(default=10, ge=1)
    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR'] = 'INFO'
    skip_initial_connection_test: bool = True
    notify_on_print_start: bool = True    # alert when print_stats.state transitions to printing
    notify_on_print_finish: bool = True   # alert when print_stats.state transitions to complete/standby
    notify_on_error: bool = True          # alert on Klipper errors / shutdown / cancelled prints
    notify_on_progress: bool = True           # alert when print hits a progress milestone
    progress_milestones: List[int] = Field(default=[25, 50, 75])  # progress % thresholds to alert on
    camera_snapshot_url: str = Field(default="")  # e.g. http://<ip>/server/files/camera/monitor.jpg
    notify_with_snapshot: bool = True         # attach a camera snapshot to Discord alerts
