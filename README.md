# Snapmaker U1 Alert Notifier (u1-notifier) - Python

A Python-based service that connects to a Snapmaker U1's local Moonraker WebSocket API and sends real-time print alert notifications to Discord via webhooks. Built with modern async Python using WebSocket patterns inspired by the [OctoEverywhere WebSocket client](https://github.com/OctoEverywhere/octowebsocket-client).

## Background

The Snapmaker U1 runs Snapmaker-maintained forks of Klipper (motion/device control), Moonraker (API/orchestration layer) and Fluidd (browser UI) — stock firmware, not community-flashed. That means the printer exposes a genuine local Moonraker JSON-RPC 2.0 WebSocket at `ws://<printer-ip>/websocket`, with no cloud account or Snapmaker service required.

## Features

- 🔌 **WebSocket Connection**: Real-time connection to the U1's Moonraker JSON-RPC API
- 🎯 **Discord Integration**: Beautiful, formatted alert notifications sent to Discord channels
- 💓 **Native WebSocket Keepalive**: Standard ping/pong frames, no application-level heartbeat needed
- 🔄 **Auto-Reconnect**: Automatic reconnection with backoff on connection loss
- 🐳 **Docker Ready**: Fully containerized for easy deployment
- ⚙️ **Configurable**: Flexible polling intervals and alert filtering
- 📊 **Rich Notifications**: Color-coded alerts with severity indicators and detailed information
- 🐍 **Modern Python**: Built with Python 3.11+ using async/await patterns
- 📝 **Structured Logging**: Beautiful colored logs with structured data
- 🛡️ **Error Handling**: Robust error handling and graceful shutdown

## Prerequisites

- Python 3.11+
- Docker (optional, for containerized deployment)
- Discord webhook URL
- A Snapmaker U1 on the same network, reachable at its local IP

## Quick Start

### 1. Clone and Setup

```bash
git clone <repository-url>
cd u1-notifier
```

### 2. Configure Environment

Copy the example environment file and configure your settings:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```env
# Snapmaker U1 Moonraker Connection
PRINTER_IP=192.168.1.50
PRINTER_PORT=80

# Discord Configuration
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/your_webhook_url_here

# Polling Configuration
POLL_INTERVAL_MINUTES=5
MAX_ALERTS_PER_POLL=10

# Logging Configuration
LOG_LEVEL=INFO

# Connection Settings
SKIP_CONNECTION_TEST=true

# Notification Settings
NOTIFY_ON_PRINT_START=true
NOTIFY_ON_PRINT_FINISH=true
```

### 3. Run the Service

#### Development Mode (Auto-setup)
```bash
./run.sh
```

#### Manual Setup
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the service
python main.py
```

#### Docker Mode
```bash
# Using Docker Compose (recommended)
docker-compose up -d

# Or using Docker directly
docker build -t u1-notifier .
docker run --env-file .env u1-notifier
```

## Configuration

| Environment Variable | Description | Default | Required |
|---------------------|-------------|---------|----------|
| `PRINTER_IP` | Snapmaker U1 IP address or hostname | - | ✅ |
| `PRINTER_PORT` | Moonraker/nginx port on the printer | `80` | ❌ |
| `MOONRAKER_API_KEY` | Moonraker API key, only needed if trusted-client access isn't enabled | - | ❌ |
| `DISCORD_WEBHOOK_URL` | Discord webhook URL | - | ✅ |
| `POLL_INTERVAL_MINUTES` | Alert buffer check interval in minutes | `5` | ❌ |
| `MAX_ALERTS_PER_POLL` | Maximum alerts to process per check | `10` | ❌ |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` | ❌ |
| `SKIP_CONNECTION_TEST` | Skip initial WebSocket connection test | `true` | ❌ |
| `NOTIFY_ON_PRINT_START` | Send an alert when a print job starts | `true` | ❌ |
| `NOTIFY_ON_PRINT_FINISH` | Send an alert when a print job completes | `true` | ❌ |
| `NOTIFY_ON_ERROR` | Send an alert on print errors, cancellations, or Klipper disconnects | `true` | ❌ |
| `NOTIFY_ON_PROGRESS` | Send an alert at print progress milestones | `true` | ❌ |
| `PROGRESS_MILESTONES` | Comma-separated progress percentages to alert on | `25,50,75` | ❌ |
| `CAMERA_SNAPSHOT_URL` | HTTP snapshot URL for the printer camera | `http://<PRINTER_IP>/server/files/camera/monitor.jpg` | ❌ |
| `NOTIFY_WITH_SNAPSHOT` | Attach a camera snapshot to Discord alerts | `true` | ❌ |

## Discord Webhook Setup

1. Go to your Discord server settings
2. Navigate to **Integrations** → **Webhooks**
3. Click **Create Webhook**
4. Customize the webhook name and channel
5. Copy the webhook URL and add it to your `.env` file

## Moonraker WebSocket Protocol

The service connects to the printer's Moonraker API over WebSocket at `ws://<PRINTER_IP>:<PRINTER_PORT>/websocket` using JSON-RPC 2.0, and subscribes to the `print_stats`, `virtual_sdcard`, and `display_status` printer objects.

### Outgoing Requests
- `printer.objects.subscribe`: Subscribe to status updates for the tracked objects, sent immediately on connect

### Incoming Notifications
- `notify_status_update`: Pushed whenever a subscribed object's fields change
- `notify_klippy_ready` / `notify_klippy_disconnected` / `notify_klippy_shutdown`: Klipper firmware connection state
- `notify_gcode_response`: Raw G-code console lines, used to catch firmware-reported errors

### Example Messages

**Subscribe request:**
```json
{
  "jsonrpc": "2.0",
  "method": "printer.objects.subscribe",
  "params": {
    "objects": {
      "print_stats": null,
      "virtual_sdcard": null,
      "display_status": null
    }
  },
  "id": 1
}
```

**Status update push:**
```json
{
  "jsonrpc": "2.0",
  "method": "notify_status_update",
  "params": [
    {
      "print_stats": { "state": "printing", "filename": "benchy.gcode" },
      "virtual_sdcard": { "progress": 0.42, "is_active": true }
    },
    1234567.89
  ]
}
```

## Alert Format

Alerts are buffered internally in the following structure and rendered as Discord embeds:

```python
from pydantic import BaseModel
from typing import Literal, Optional, Dict, Any

class Alert(BaseModel):
    id: str
    title: str
    description: str
    severity: Literal['low', 'medium', 'high', 'critical']
    timestamp: str
    source: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
```

## Docker Deployment

### Using Docker Compose (Recommended)

```yaml
version: '3.8'
services:
  u1-notifier:
    build: .
    environment:
      - PRINTER_IP=192.168.1.50
      - DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/your_webhook
      - POLL_INTERVAL_MINUTES=5
    restart: unless-stopped
```

### Environment File

Create a `.env` file for Docker:

```bash
# .env
PRINTER_IP=192.168.1.50
PRINTER_PORT=80
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/your_webhook_url
POLL_INTERVAL_MINUTES=5
MAX_ALERTS_PER_POLL=10
LOG_LEVEL=INFO
SKIP_CONNECTION_TEST=true
NOTIFY_ON_PRINT_START=true
NOTIFY_ON_PRINT_FINISH=true
```

## Development

### Project Structure

```
u1-notifier/
├── src/
│   ├── __init__.py           # Package initialization
│   ├── models/                # Pydantic data models
│   ├── config.py             # Configuration and logging
│   ├── websocket_client.py   # Moonraker WebSocket client for the U1
│   ├── alert_processor.py    # Stateful alert decision logic
│   ├── discord_notifier.py   # Discord webhook integration
│   └── service.py            # Main service orchestrator
├── main.py                   # Entry point
├── requirements.txt          # Python dependencies
├── run.sh                    # Development script
├── Dockerfile               # Docker container config
├── docker-compose.yml       # Docker Compose config
└── README.md                # This file
```

### Dependencies

The project uses modern Python libraries:

- **websockets**: WebSocket client library
- **aiohttp**: Async HTTP client for Discord webhooks
- **pydantic**: Data validation and serialization
- **structlog**: Structured logging
- **python-dotenv**: Environment variable management
- **colorama**: Colored terminal output

### Scripts

- `python main.py` - Run the service directly
- `./run.sh` - Development script with auto-setup
- `docker-compose up -d` - Start with Docker Compose
- `docker-compose logs -f` - View Docker logs
- `docker-compose down` - Stop Docker Compose

## Monitoring and Logs

The service provides comprehensive structured logging with timestamps and colored output:

```bash
2026-08-11T21:47:10.761Z [INFO] Service: 🚀 Starting U1 Alert Notification Service...
2026-08-11T21:47:11.285Z [INFO] MoonrakerWS: Connecting to Moonraker WebSocket url=ws://192.168.1.50/websocket
2026-08-11T21:47:12.531Z [INFO] MoonrakerWS: ✅ Connected to Moonraker WebSocket
2026-08-11T21:47:13.142Z [INFO] Discord: ✅ Test message - Discord webhook connection successful!
2026-08-11T21:47:14.023Z [INFO] Service: 🔄 Alert polling started interval_minutes=5
```

## Troubleshooting

### Common Issues

1. **WebSocket Connection Failed**
   - Check that the U1 is powered on and reachable on the network
   - Verify `PRINTER_IP`/`PRINTER_PORT` point at the printer's Moonraker/nginx port (default `80`)
   - Check firewall and network connectivity

2. **Discord Webhook Errors**
   - Verify webhook URL is correct and active
   - Check Discord server permissions
   - Ensure webhook channel still exists

3. **No Alerts Received**
   - Check WebSocket connection status in logs
   - Verify the `printer.objects.subscribe` request was acknowledged
   - Confirm the printer isn't blocking untrusted clients (set `MOONRAKER_API_KEY` if so)

4. **Python Import Errors**
   - Ensure Python 3.11+ is installed
   - Activate virtual environment: `source venv/bin/activate`
   - Install dependencies: `pip install -r requirements.txt`

### Debug Mode

Enable debug logging by setting `LOG_LEVEL=DEBUG` in your environment:

```env
LOG_LEVEL=DEBUG
```

This will provide detailed WebSocket message logs and connection status information.

## License

ISC License

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## Support

For issues and questions:
- Check the troubleshooting section
- Review the logs for error messages
- Create an issue in the repository

---

*Built with ❤️ using Python and inspired by [OctoEverywhere's WebSocket patterns](https://github.com/OctoEverywhere/octowebsocket-client)*
