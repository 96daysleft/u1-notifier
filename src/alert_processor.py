"""Determines when to generate alerts based on incoming Moonraker messages.

This module owns all stateful alert logic:
- tracking last known print state / progress so changes can be detected
- deciding which events are worth alerting on
- building Alert objects and buffering them for the poll loop to drain

MoonrakerWebSocketClient calls process_status_update() / process_klippy_state()
/ process_gcode_response() after parsing raw WebSocket messages; it does not
make any alerting decisions itself.
"""

import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

from .config import config, logger
from .models.moonraker import PrinterObjectsStatus, PrintState
from .models.notice import Alert

# print_stats.state values that mean "no job actively running"
_TERMINAL_STATES = {"complete", "cancelled", "error", "standby"}


class AlertProcessor:
    """Stateful processor that decides when to fire alerts.

    Receives raw Moonraker status dicts from the WebSocket client,
    parses them, logs relevant fields, and buffers Alert objects
    whenever something noteworthy happens.
    """

    def __init__(self):
        self._alert_buffer: List[Alert] = []
        self._buffer_lock = asyncio.Lock()

        # Retained between messages to detect changes
        self._last_state: Optional[str] = None
        self._last_progress: Optional[int] = None
        self._last_filename: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API (called by service poll loop)
    # ------------------------------------------------------------------

    async def get_new_alerts(self) -> List[Alert]:
        """Drain and return all buffered alerts (thread-safe)."""
        async with self._buffer_lock:
            alerts = self._alert_buffer.copy()
            self._alert_buffer.clear()
            return alerts

    # ------------------------------------------------------------------
    # Message processors (called by MoonrakerWebSocketClient)
    # ------------------------------------------------------------------

    async def process_status_update(self, status: Dict[str, Any]) -> None:
        """Process a printer.objects status payload (subscribe result or
        notify_status_update push).

        Logs printer state and buffers alerts for:
        - Initial state on first message after connect
        - print_stats.state transitions (e.g. standby -> printing)
        - Print progress milestones (25 %, 50 %, 75 %)
        """
        try:
            parsed = PrinterObjectsStatus.model_validate(status)
        except Exception as e:
            logger.error("Failed to parse status update", error=str(e), raw=status)
            return

        ps = parsed.print_stats
        vsd = parsed.virtual_sdcard

        logger.info(
            "Printer status",
            state=ps.state if ps else None,
            file=ps.filename if ps else None,
            layer=f"{ps.info.current_layer}/{ps.info.total_layer}" if ps and ps.info else None,
            progress_pct=vsd.progress_pct if vsd else None,
            print_duration=ps.print_duration if ps else None,
            message=ps.message if ps else None,
        )

        timestamp = str(int(time.time()))

        if ps is not None and ps.state is not None:
            await self._check_state_change(ps, timestamp)

        # Moonraker often pushes partial updates — a progress-only push won't
        # include print_stats, so milestone checks must rely on the state/
        # filename tracked from the last push that did include it, not `ps`.
        if vsd is not None and vsd.progress is not None:
            await self._check_progress_milestones(vsd, timestamp)

    async def process_klippy_state(self, state: str) -> None:
        """Handle notify_klippy_ready / notify_klippy_disconnected / notify_klippy_shutdown."""
        logger.info("Klippy state changed", state=state)

        if state == "ready":
            return

        if not config.notify_on_error:
            return

        await self._buffer(Alert(
            id=str(uuid.uuid4()),
            title="Klipper Disconnected" if state == "disconnected" else "Klipper Shutdown",
            description=(
                "The printer's Klipper firmware connection was lost."
                if state == "disconnected"
                else "Klipper has entered an emergency shutdown state."
            ),
            severity="high",
            timestamp=str(int(time.time())),
            source="moonraker/klippy",
        ))
        logger.warning("Klippy state alert buffered", state=state)

    async def process_gcode_response(self, line: str) -> None:
        """Handle notify_gcode_response — buffer an alert on firmware-reported errors."""
        if not config.notify_on_error:
            return
        if not (line.startswith("!!") or line.lower().startswith("error")):
            return

        await self._buffer(Alert(
            id=str(uuid.uuid4()),
            title="Printer Error",
            description=line.lstrip("!").strip(),
            severity="high",
            timestamp=str(int(time.time())),
            source="moonraker/gcode_response",
        ))
        logger.warning("Gcode error alert buffered", line=line)

    async def process_error(self, error: Dict[str, Any]) -> None:
        """Process a top-level JSON-RPC error — buffer as a high-severity alert."""
        if not config.notify_on_error:
            return
        alert = Alert(
            id=str(uuid.uuid4()),
            title="Moonraker Error",
            description=error.get("message", "A Moonraker error was reported."),
            severity="high",
            timestamp=str(int(time.time())),
            source="moonraker/error",
            details=error or None,
        )
        await self._buffer(alert)
        logger.info("Error alert buffered", id=alert.id, error=error)

    # ------------------------------------------------------------------
    # Internal alert rules
    # ------------------------------------------------------------------

    async def _check_state_change(self, ps, timestamp: str) -> None:
        """Buffer an alert if print_stats.state has changed since last message."""
        state = ps.state
        filename = ps.filename

        if self._last_state is None:
            # First status received after connect — report current state
            parts = [f"State: {PrintState.label(state)}"]
            if filename:
                parts.append(f"File: {filename}")
            await self._buffer(Alert(
                id=str(uuid.uuid4()),
                title="Current Printer Status",
                description="\n".join(parts),
                severity="low",
                timestamp=timestamp,
                source="moonraker/print_stats",
            ))
            logger.info("Initial status alert buffered", state=state)

        elif state != self._last_state:
            prev_label = PrintState.label(self._last_state)
            curr_label = PrintState.label(state)

            is_start = state == "printing" and self._last_state != "paused"
            is_finish = state in ("complete", "standby") and self._last_state == "printing"
            is_error = state in ("error", "cancelled")

            if is_start and config.notify_on_print_start:
                desc_parts = ["Printer has started a new job."]
                if filename:
                    desc_parts.append(f"File: {filename}")
                await self._buffer(Alert(
                    id=str(uuid.uuid4()),
                    title="Print Started",
                    description="\n".join(desc_parts),
                    severity="low",
                    timestamp=timestamp,
                    source="moonraker/print_stats",
                ))
                logger.info("Print start alert buffered")
            elif is_error and config.notify_on_error:
                desc_parts = [f"Print job {curr_label.lower()}."]
                if filename:
                    desc_parts.append(f"File: {filename}")
                if ps.message:
                    desc_parts.append(f"Message: {ps.message}")
                await self._buffer(Alert(
                    id=str(uuid.uuid4()),
                    title=f"Print {curr_label}",
                    description="\n".join(desc_parts),
                    severity="high",
                    timestamp=timestamp,
                    source="moonraker/print_stats",
                ))
                logger.warning("Print error/cancel alert buffered", state=state)
            elif is_finish and config.notify_on_print_finish:
                desc_parts = [f"Print job finished ({curr_label.lower()})."]
                if filename:
                    desc_parts.append(f"File: {filename}")
                await self._buffer(Alert(
                    id=str(uuid.uuid4()),
                    title="Print Finished",
                    description="\n".join(desc_parts),
                    severity="low",
                    timestamp=timestamp,
                    source="moonraker/print_stats",
                ))
                logger.info("Print finish alert buffered", prev=prev_label, curr=curr_label)
            else:
                await self._buffer(Alert(
                    id=str(uuid.uuid4()),
                    title="Printer State Changed",
                    description=f"State changed from {prev_label} to {curr_label}",
                    severity="low",
                    timestamp=timestamp,
                    source="moonraker/print_stats",
                ))
                logger.info("State change alert buffered", prev=prev_label, curr=curr_label)

        # Progress milestones reset whenever a new print job starts. Moonraker
        # omits unchanged fields from partial pushes, so a push that reports a
        # state change but not filename must NOT be read as "filename -> None".
        if filename is not None and filename != self._last_filename:
            self._last_progress = None
            self._last_filename = filename

        self._last_state = state

    async def _check_progress_milestones(self, vsd, timestamp: str) -> None:
        """Buffer an alert when file progress crosses 25 %, 50 %, or 75 %.

        Uses state/filename tracked from the last push that included
        print_stats, since a progress-only push from Moonraker won't."""
        if not config.notify_on_progress:
            return
        if self._last_state != "printing":
            return

        progress = vsd.progress_pct
        if progress is None:
            return

        filename = self._last_filename or "Print"
        for milestone in config.progress_milestones:
            if self._last_progress is not None and self._last_progress < milestone <= progress:
                await self._buffer(Alert(
                    id=str(uuid.uuid4()),
                    title=f"Print {milestone}% Complete",
                    description=f"{filename} is {milestone}% complete.",
                    severity="low",
                    timestamp=timestamp,
                    source="moonraker/virtual_sdcard",
                ))
                logger.info("Progress milestone alert buffered", milestone=milestone, progress=progress)

        self._last_progress = progress

    async def _buffer(self, alert: Alert) -> None:
        async with self._buffer_lock:
            self._alert_buffer.append(alert)
