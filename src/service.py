"""Main service orchestrator for the U1 Alert Notifier."""

import asyncio
import signal
import sys
from datetime import datetime, timezone
from typing import List, Optional

from .config import config, logger, validate_config
from .discord_notifier import DiscordNotifier
from .models.notice import Alert
from .websocket_client import MoonrakerWebSocketClient


class AlertNotificationService:
    """Main service class that orchestrates alert monitoring and notification."""

    def __init__(self):
        self.printer_client = MoonrakerWebSocketClient()
        self.discord_notifier: Optional[DiscordNotifier] = None
        self.is_running = False
        self._stopping = False
        self.poll_task: Optional[asyncio.Task] = None
        self.websocket_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the alert notification service."""
        logger.info("🚀 Starting U1 Alert Notification Service...")

        # Validate configuration
        validate_config(config)
        logger.info("✅ Configuration validation passed")

        # Test connections
        await self._test_connections()

        # Start service components
        self.is_running = True

        # Initialize Discord notifier
        self.discord_notifier = DiscordNotifier()
        await self.discord_notifier.__aenter__()

        # Setup WebSocket connection handlers
        self.printer_client.on_connect = self._on_websocket_connect
        self.printer_client.on_disconnect = self._on_websocket_disconnect
        self.printer_client.on_error = self._on_websocket_error

        # Start WebSocket connection in background
        self.websocket_task = asyncio.create_task(
            self.printer_client.start_with_reconnect()
        )

        # Start polling task
        self.poll_task = asyncio.create_task(self._poll_loop())

        logger.info(
            "🔄 Alert polling started",
            interval_minutes=config.poll_interval_minutes
        )

        # Setup graceful shutdown
        self._setup_signal_handlers()

        # Wait for all tasks
        try:
            await asyncio.gather(
                self.websocket_task,
                self.poll_task,
                return_exceptions=True
            )
        except Exception as e:
            logger.error("Service error", error=str(e))
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop the alert notification service."""
        if self._stopping:
            return
        self._stopping = True
        logger.info("🛑 Stopping Alert Notification Service...")

        self.is_running = False

        # Cancel tasks
        if self.poll_task and not self.poll_task.done():
            self.poll_task.cancel()

        if self.websocket_task and not self.websocket_task.done():
            self.websocket_task.cancel()

        # Disconnect WebSocket
        await self.printer_client.disconnect()

        # Send shutdown notification before closing the Discord session
        if self.discord_notifier:
            from .models.discord import DiscordEmbed, DiscordMessage
            try:
                await self.discord_notifier.send_message(DiscordMessage(
                    username="Snapmaker U1 Alert System",
                    embeds=[DiscordEmbed(
                        title="Service Stopped",
                        description="U1 Alert Notifier has shut down.",
                        color=0x808080,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )]
                ))
            except Exception as e:
                logger.warning("Could not send shutdown notification", error=str(e))
            await self.discord_notifier.__aexit__(None, None, None)

        logger.info("✅ Service stopped successfully")

    async def _test_connections(self) -> None:
        """Validate config; optionally probe the WebSocket before the main loop starts."""
        if config.skip_initial_connection_test:
            logger.info("Skipping initial WebSocket connection test — will connect in background")
        else:
            logger.info("Testing Moonraker WebSocket connection...")
            websocket_connected = await self.printer_client.test_connection()
            if not websocket_connected:
                logger.warning("Initial WebSocket connection failed, retrying in background")

    def _on_websocket_connect(self) -> None:
        """Handle WebSocket connection event."""
        logger.info("WebSocket connected to Snapmaker U1")
        asyncio.create_task(self._notify_printer_connected())
        asyncio.create_task(self._initial_status_poll())

    async def _initial_status_poll(self) -> None:
        """Poll for alerts shortly after connect to send the initial status without waiting for the poll interval."""
        await asyncio.sleep(3)
        await self._poll_for_alerts()

    async def _notify_printer_connected(self) -> None:
        if self.discord_notifier:
            from .models.discord import DiscordEmbed, DiscordMessage
            message = DiscordMessage(
                username="Snapmaker U1 Alert System",
                embeds=[DiscordEmbed(
                    title="Printer Connected",
                    description=f"Successfully connected to the Snapmaker U1 at `{config.printer_ip}`",
                    color=0x00ff00,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )]
            )
            await self.discord_notifier.send_message(message)

    def _on_websocket_disconnect(self, exception: Optional[Exception]) -> None:
        """Handle WebSocket disconnection event."""
        if exception:
            logger.warning("WebSocket disconnected due to error", error=str(exception))
        else:
            logger.info("WebSocket disconnected")

    def _on_websocket_error(self, exception: Exception) -> None:
        """Handle WebSocket error event."""
        logger.error("WebSocket error", error=str(exception))

    async def _poll_loop(self) -> None:
        """Main polling loop for checking alerts."""
        while self.is_running:
            try:
                await self._poll_for_alerts()
            except Exception as e:
                logger.error("Error in polling loop", error=str(e))

            # Wait for next poll interval
            await asyncio.sleep(config.poll_interval_minutes * 60)

    async def _poll_for_alerts(self) -> None:
        """Poll for new alerts and send notifications."""
        try:
            logger.debug("🔍 Polling for new alerts...")

            # Check WebSocket connection
            if not self.printer_client.is_connected:
                logger.debug("WebSocket not connected, skipping poll")
                return

            # Get new alerts from buffer
            new_alerts = await self.printer_client.get_new_alerts()

            if not new_alerts:
                logger.debug("No new alerts found")
                return

            logger.info("📢 Found new alerts", count=len(new_alerts))

            # Filter alerts if needed
            filtered_alerts = self._filter_alerts(new_alerts)

            if not filtered_alerts:
                logger.info("All alerts filtered out by severity settings")
                return

            # Send alerts to Discord
            if self.discord_notifier:
                sent_count = await self.discord_notifier.send_alerts_batch(filtered_alerts)

                if sent_count > 0:
                    logger.info("✅ Successfully sent alerts to Discord", count=sent_count)
                else:
                    logger.error("❌ Failed to send alerts to Discord")

        except Exception as e:
            logger.error("Error during alert polling", error=str(e))

    def _filter_alerts(self, alerts: List[Alert]) -> List[Alert]:
        """Filter alerts based on configuration settings."""
        # For now, return all alerts
        # You can add filtering logic here based on severity, source, etc.
        return alerts

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        if sys.platform != 'win32':
            # Unix-like systems
            for sig in [signal.SIGTERM, signal.SIGINT]:
                asyncio.get_event_loop().add_signal_handler(
                    sig,
                    lambda s=sig: asyncio.create_task(self._handle_shutdown(s))
                )

    async def _handle_shutdown(self, sig: signal.Signals) -> None:
        """Handle shutdown signals."""
        logger.info(f"📡 Received {sig.name}, shutting down gracefully...")
        await self.stop()


async def main() -> None:
    """Main entry point for the service."""
    service = AlertNotificationService()

    try:
        await service.start()
    except KeyboardInterrupt:
        logger.info("👋 Service interrupted by user")
        await service.stop()
    except Exception as e:
        logger.error("❌ Failed to start service", error=str(e))
        sys.exit(1)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
