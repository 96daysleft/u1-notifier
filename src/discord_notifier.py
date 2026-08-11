"""Discord webhook notifier for Snapmaker U1 alerts."""

import asyncio
import json
import aiohttp
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .config import config, logger
from .models.discord import DiscordEmbed, DiscordMessage, SEVERITY_COLORS, SEVERITY_EMOJIS
from .models.notice import Alert


class DiscordNotifier:
    """Discord webhook integration for sending alert notifications."""
    
    def __init__(self):
        self.session: aiohttp.ClientSession = None
    
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={'User-Agent': 'u1-notifier/1.0.0 (Python)'}
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
    async def fetch_snapshot(self) -> Optional[bytes]:
        """Grab a single JPEG frame from the printer's camera, if configured.

        Handles both a plain JPEG snapshot endpoint and an MJPEG
        (multipart/x-mixed-replace) stream by pulling out the first frame.
        """
        if not config.camera_snapshot_url or not self.session:
            return None
        try:
            async with self.session.get(
                config.camera_snapshot_url,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                if response.status != 200:
                    logger.warning("Camera snapshot request failed", status=response.status)
                    return None

                content_type = response.headers.get('Content-Type', '')
                if 'multipart' in content_type or 'x-mixed-replace' in content_type:
                    buf = b''
                    async for chunk in response.content.iter_chunked(4096):
                        buf += chunk
                        start = buf.find(b'\xff\xd8')
                        end = buf.find(b'\xff\xd9', start + 2) if start != -1 else -1
                        if start != -1 and end != -1:
                            return buf[start:end + 2]
                        if len(buf) > 2_000_000:
                            break
                    logger.warning("Could not find a JPEG frame in camera stream")
                    return None

                return await response.read()
        except Exception as e:
            logger.warning("Failed to fetch camera snapshot", error=str(e))
            return None

    @staticmethod
    def _to_iso(timestamp: str) -> str:
        """Convert a Unix timestamp string or ISO string to UTC ISO 8601."""
        try:
            return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat()
        except (ValueError, OSError):
            return timestamp  # already ISO, pass through

    def create_alert_embed(self, alert: Alert) -> DiscordEmbed:
        """Create a Discord embed for a single alert."""
        embed = DiscordEmbed(
            title=f"{SEVERITY_EMOJIS[alert.severity]} {alert.title}",
            description=alert.description,
            color=SEVERITY_COLORS[alert.severity],
            timestamp=self._to_iso(alert.timestamp),
            fields=[
                {
                    'name': 'Severity',
                    'value': alert.severity.upper(),
                    'inline': True
                },
                {
                    'name': 'Alert ID', 
                    'value': alert.id,
                    'inline': True
                }
            ],
            footer={
                'text': 'Snapmaker U1 Alert System',
            }
        )
        
        # Add source field if available
        if alert.source:
            embed.fields.append({
                'name': 'Source',
                'value': alert.source,
                'inline': True
            })
        
        # Add details field if available
        if alert.details and len(alert.details) > 0:
            details_string = '\n'.join([
                f"**{key}**: {value}" for key, value in alert.details.items()
            ])
            
            # Truncate if too long
            if len(details_string) > 1000:
                details_string = details_string[:997] + '...'
            
            embed.fields.append({
                'name': 'Details',
                'value': details_string,
                'inline': False
            })
        
        return embed
    
    def create_summary_embed(self, alerts: List[Alert]) -> DiscordEmbed:
        """Create a summary embed for multiple alerts."""
        severity_counts = {}
        for alert in alerts:
            severity_counts[alert.severity] = severity_counts.get(alert.severity, 0) + 1
        
        fields = []
        for severity, count in severity_counts.items():
            fields.append({
                'name': severity.upper(),
                'value': str(count),
                'inline': True
            })
        
        return DiscordEmbed(
            title='📊 Alert Summary',
            color=0x3498db,  # Blue
            fields=fields,
            timestamp=datetime.now(timezone.utc).isoformat(),
            footer={
                'text': f"Total: {len(alerts)} alert{'s' if len(alerts) != 1 else ''}"
            }
        )
    
    async def send_alert(self, alert: Alert) -> bool:
        """Send a single alert to Discord, with a camera snapshot attached if available."""
        embed = self.create_alert_embed(alert)

        snapshot = await self.fetch_snapshot() if config.notify_with_snapshot else None
        if snapshot:
            embed.image = {'url': 'attachment://snapshot.jpg'}

        message = DiscordMessage(
            username='Snapmaker U1 Alert System',
            embeds=[embed]
        )

        return await self.send_message(message, image_bytes=snapshot)
    
    async def send_alerts(self, alerts: List[Alert]) -> int:
        """Send multiple alerts to Discord individually."""
        success_count = 0
        
        for alert in alerts:
            try:
                success = await self.send_alert(alert)
                if success:
                    success_count += 1
                
                # Small delay to avoid rate limiting
                await asyncio.sleep(1.0)
                
            except Exception as e:
                logger.error("Failed to send alert", alert_id=alert.id, error=str(e))
        
        logger.info(
            "Sent alerts to Discord",
            sent=success_count,
            total=len(alerts)
        )
        return success_count
    
    async def send_alerts_batch(self, alerts: List[Alert]) -> int:
        """Send alerts in a batch format to avoid Discord rate limits."""
        if not alerts:
            return 0
        
        if len(alerts) == 1:
            success = await self.send_alert(alerts[0])
            return 1 if success else 0
        
        # Create summary + individual embeds for multiple alerts
        summary_embed = self.create_summary_embed(alerts)
        alert_embeds = [self.create_alert_embed(alert) for alert in alerts[:3]]  # Limit to 3 individual alerts

        snapshot = await self.fetch_snapshot() if config.notify_with_snapshot else None
        if snapshot:
            summary_embed.image = {'url': 'attachment://snapshot.jpg'}

        message = DiscordMessage(
            username='Snapmaker U1 Alert System',
            content=f"🚨 **{len(alerts)} New Alert{'s' if len(alerts) != 1 else ''}**",
            embeds=[summary_embed] + alert_embeds
        )

        success = await self.send_message(message, image_bytes=snapshot)
        return len(alerts) if success else 0
    
    async def send_message(self, message: DiscordMessage, image_bytes: Optional[bytes] = None) -> bool:
        """Send a message to Discord webhook, optionally with an attached image."""
        if not self.session:
            logger.error("Discord session not initialized")
            return False

        try:
            # Convert to dict for JSON serialization
            message_dict = message.model_dump(exclude_none=True)

            if image_bytes:
                form = aiohttp.FormData()
                form.add_field('payload_json', json.dumps(message_dict), content_type='application/json')
                form.add_field('files[0]', image_bytes, filename='snapshot.jpg', content_type='image/jpeg')
                post_kwargs = {'data': form}
            else:
                post_kwargs = {'json': message_dict}

            async with self.session.post(config.discord_webhook_url, **post_kwargs) as response:
                # Discord returns 204 for JSON-only posts, 200 (with the created
                # message body) for multipart/file-upload posts.
                if response.status in (200, 204):
                    logger.debug("Message sent to Discord successfully")
                    return True
                else:
                    logger.error(
                        "Discord webhook error",
                        status=response.status,
                        response=await response.text()
                    )
                    return False
                    
        except Exception as e:
            logger.error("Failed to send message to Discord", error=str(e))
            return False
    
    async def test_webhook(self) -> bool:
        """Test the Discord webhook connection."""
        try:
            logger.info("Testing Discord webhook...")
            
            test_message = DiscordMessage(
                username='Snapmaker U1 Alert System',
                content='✅ Test message - Discord webhook connection successful!',
                embeds=[DiscordEmbed(
                    title='Connection Test',
                    description='This is a test message to verify the Discord webhook is working properly.',
                    color=0x00ff00,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    footer={
                        'text': 'u1-notifier service'
                    }
                )]
            )
            
            success = await self.send_message(test_message)
            if success:
                logger.info("Discord webhook test successful")
            return success
            
        except Exception as e:
            logger.error("Discord webhook test failed", error=str(e))
            return False
