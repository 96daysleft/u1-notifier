"""WebSocket client for the Snapmaker U1's Moonraker JSON-RPC API."""

import asyncio
import itertools
import json
import ssl
from typing import Any, Callable, Dict, List, Optional

import websockets

from .alert_processor import AlertProcessor
from .config import config, logger
from .models.notice import Alert

# Printer objects we track via printer.objects.subscribe
SUBSCRIBE_OBJECTS = {
    "print_stats": None,
    "virtual_sdcard": None,
    "display_status": None,
}


class MoonrakerWebSocketClient:
    """
    JSON-RPC 2.0 WebSocket client for Moonraker, as run on the Snapmaker U1.

    Protocol details:
    - URL:      ws://{ip}:{port}/websocket
    - Requests: {"jsonrpc": "2.0", "method": ..., "params": {...}, "id": N}
    - Pushes:   {"jsonrpc": "2.0", "method": "notify_status_update", "params": [status, eventtime]}
    - Standard WebSocket ping/pong frames keep the connection alive — no
      application-level heartbeat is required by Moonraker.

    Alert logic is handled entirely by AlertProcessor — this class only manages
    the connection lifecycle, JSON-RPC request/response bookkeeping, and
    dispatches parsed notifications.
    """

    RECONNECT_DELAY_SECS = 10

    def __init__(self):
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected: bool = False
        self.is_running: bool = False
        self.reconnect_attempts: int = 0

        self._id_counter = itertools.count(1)

        # All alert decisions and buffering live here
        self.alert_processor = AlertProcessor()

        # Callbacks (OctoEverywhere on_open / on_close / on_error style)
        self.on_connect: Optional[Callable[[], None]] = None
        self.on_disconnect: Optional[Callable[[Optional[Exception]], None]] = None
        self.on_error: Optional[Callable[[Exception], None]] = None
        self.on_message: Optional[Callable[[Dict[str, Any]], None]] = None

    # ------------------------------------------------------------------
    # URL
    # ------------------------------------------------------------------

    @property
    def url(self) -> str:
        """Build the Moonraker WebSocket URL: ws://{ip}:{port}/websocket"""
        ip = config.printer_ip.replace("ws://", "").replace("wss://", "")
        url = f"ws://{ip}:{config.printer_port}/websocket"
        if config.api_key:
            url += f"?token={config.api_key}"
        return url

    def _make_ssl_context(self) -> Optional[ssl.SSLContext]:
        if not self.url.startswith("wss://"):
            return None
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def test_connection(self) -> bool:
        """Quick connectivity check — connect then immediately close."""
        try:
            logger.info("Testing WebSocket connection", url=self.url)
            async with websockets.connect(self.url, ssl=self._make_ssl_context(), open_timeout=5):
                logger.info("WebSocket test connection successful")
                return True
        except Exception as e:
            logger.warning("WebSocket test connection failed", error=str(e))
            return False

    async def get_new_alerts(self) -> List[Alert]:
        """Drain and return all buffered alerts. Delegates to AlertProcessor."""
        return await self.alert_processor.get_new_alerts()

    def stop(self) -> None:
        self.is_running = False

    async def disconnect(self, reason: str = "Manual disconnect") -> None:
        self.is_running = False
        self.is_connected = False
        if self.ws:
            logger.info("Disconnecting from Moonraker WebSocket", reason=reason)
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None

    # ------------------------------------------------------------------
    # Reconnect loop
    # ------------------------------------------------------------------

    async def start_with_reconnect(self) -> None:
        """Connect and auto-reconnect on any failure."""
        self.is_running = True

        while self.is_running:
            try:
                logger.info(
                    "Connecting to Moonraker WebSocket",
                    url=self.url,
                    attempt=self.reconnect_attempts + 1,
                )

                async with websockets.connect(
                    self.url,
                    ssl=self._make_ssl_context(),
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:
                    self.ws = ws
                    self.is_connected = True
                    self.reconnect_attempts = 0

                    logger.info("Connected to Moonraker WebSocket")
                    await self._subscribe_to_objects()

                    if self.on_connect:
                        self.on_connect()

                    async for raw in ws:
                        await self._handle_message(raw)

                logger.info("WebSocket connection closed by server")
                if self.on_disconnect:
                    self.on_disconnect(None)

            except websockets.exceptions.ConnectionClosed as e:
                logger.info("WebSocket connection closed", code=e.code, reason=e.reason)
                if self.on_disconnect:
                    self.on_disconnect(e)
            except Exception as e:
                logger.error("WebSocket error", error=str(e))
                if self.on_error:
                    self.on_error(e)
            finally:
                self.is_connected = False
                self.ws = None

            if not self.is_running:
                break

            self.reconnect_attempts += 1
            logger.info("Reconnecting", delay_secs=self.RECONNECT_DELAY_SECS, attempt=self.reconnect_attempts)
            await asyncio.sleep(self.RECONNECT_DELAY_SECS)

    # ------------------------------------------------------------------
    # Moonraker JSON-RPC helpers
    # ------------------------------------------------------------------

    def _build_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> str:
        """Build a JSON-RPC 2.0 request envelope."""
        return json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": next(self._id_counter),
        })

    async def _subscribe_to_objects(self) -> None:
        """Subscribe to print_stats / virtual_sdcard / display_status on connect."""
        if self.ws:
            await self.ws.send(self._build_request(
                "printer.objects.subscribe",
                {"objects": SUBSCRIBE_OBJECTS},
            ))
            logger.info("Object subscription request sent", objects=list(SUBSCRIBE_OBJECTS))

    # ------------------------------------------------------------------
    # Message dispatch
    # ------------------------------------------------------------------

    async def _handle_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse WebSocket message", error=str(e), raw=raw[:200])
            return

        method = msg.get("method")
        logger.debug("WebSocket message received", method=method, has_result="result" in msg)

        if method == "notify_status_update":
            await self._handle_status_update(msg.get("params") or [])
        elif method == "notify_klippy_ready":
            await self.alert_processor.process_klippy_state("ready")
        elif method == "notify_klippy_disconnected":
            await self.alert_processor.process_klippy_state("disconnected")
        elif method == "notify_klippy_shutdown":
            await self.alert_processor.process_klippy_state("shutdown")
        elif method == "notify_gcode_response":
            params = msg.get("params") or []
            if params:
                await self.alert_processor.process_gcode_response(str(params[0]))
        elif "result" in msg:
            await self._handle_response(msg)
        elif "error" in msg:
            logger.error("Moonraker JSON-RPC error", error=msg.get("error"))
            await self.alert_processor.process_error(msg.get("error") or {})
        else:
            logger.debug("Unhandled message", method=method)

        if self.on_message:
            self.on_message(msg)

    async def _handle_response(self, msg: Dict[str, Any]) -> None:
        """Handle a JSON-RPC response — currently only the subscribe result matters,
        which carries the printer's current status snapshot."""
        result = msg.get("result")
        if isinstance(result, dict) and "status" in result:
            await self.alert_processor.process_status_update(result["status"])

    async def _handle_status_update(self, params: List[Any]) -> None:
        if not params:
            return
        status = params[0]
        if isinstance(status, dict):
            await self.alert_processor.process_status_update(status)
