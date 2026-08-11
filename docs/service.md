# service.py — Service Orchestrator

`src/service.py` is the top-level coordinator for the notifier. It owns no protocol logic of its own — instead it wires together the WebSocket client and the Discord notifier, manages their lifecycles, and routes alerts between them.

---

## Class: `AlertNotificationService`

### Owned objects

| Attribute | Type | Purpose |
|---|---|---|
| `printer_client` | `MoonrakerWebSocketClient` | Moonraker JSON-RPC WebSocket connection to the printer |
| `discord_notifier` | `DiscordNotifier` | aiohttp session + Discord webhook sender |
| `websocket_task` | `asyncio.Task` | Runs the WS reconnect loop |
| `poll_task` | `asyncio.Task` | Periodically drains the alert buffer |

---

## Startup sequence (`start`)

```
1. validate_config()              — check all required env vars are set
2. _test_connections()            — optional: quick connect/close to verify reachability
3. DiscordNotifier.__aenter__()   — open aiohttp ClientSession
4. attach WS callbacks            — on_connect / on_disconnect / on_error
5. create_task(start_with_reconnect)   — WS loop starts in background
6. create_task(_poll_loop)             — alert drain starts in background
7. _setup_signal_handlers()       — SIGTERM / SIGINT → graceful shutdown
8. asyncio.gather(both tasks)     — block here until stopped
```

---

## Concurrent tasks

Two `asyncio.Task` objects run independently after startup:

### `_poll_loop`
- Runs `_poll_for_alerts()` immediately, then sleeps for `POLL_INTERVAL_MINUTES * 60` seconds.
- `_poll_for_alerts()` calls `printer_client.get_new_alerts()` to drain the buffer, filters by severity, then calls `discord_notifier.send_alerts_batch()`.
- Skips silently if the WebSocket is not yet connected.

### `websocket_task` (delegated to `MoonrakerWebSocketClient`)
- Connects to `ws://{PRINTER_IP}:{PRINTER_PORT}/websocket`, subscribes to `print_stats` / `virtual_sdcard` / `display_status`, receives messages indefinitely.
- Relies on standard WebSocket ping/pong frames (`ping_interval=20`) for keepalive — Moonraker doesn't need an application-level heartbeat like the Centauri's SDCP protocol did.
- Auto-reconnects after 10 seconds on any error or disconnect.
- Fires the callbacks registered in step 4 above.

---

## WebSocket callbacks

| Callback | When fired | What it does |
|---|---|---|
| `on_connect` | WS connection established | Fires `_notify_printer_connected()` as a new task |
| `on_disconnect` | WS closed (clean or error) | Logs the event |
| `on_error` | Unhandled WS exception | Logs the error |

### `_notify_printer_connected`
Sends a green "Printer Connected" embed directly to Discord (bypasses the alert buffer). This fires once per connection, including reconnections.

---

## Alert flow

```
Snapmaker U1 (Klipper/Moonraker)
    │  (JSON-RPC WebSocket messages)
    ▼
MoonrakerWebSocketClient._handle_status_update / _handle_response / klippy/gcode handlers
    │  (Alert objects appended to _alert_buffer via AlertProcessor)
    ▼
AlertNotificationService._poll_for_alerts   (runs every POLL_INTERVAL_MINUTES)
    │  get_new_alerts() drains the buffer
    │  _filter_alerts() applies severity rules
    ▼
DiscordNotifier.send_alerts_batch
    │  (one embed per alert, batched into one webhook POST)
    ▼
Discord channel
```

Alerts that come from the WebSocket client:
- **Initial status** — buffered on the very first `notify_status_update`/subscribe response after connect
- **State change** — buffered whenever `print_stats.state` differs from the previous message (standby → printing, printing → complete/cancelled/error, …)
- **Progress milestones** — buffered when `virtual_sdcard.progress` crosses 25 %, 50 %, or 75 % while printing
- **Klipper connection state** — buffered on `notify_klippy_disconnected` / `notify_klippy_shutdown`
- **G-code errors** — buffered when `notify_gcode_response` lines look like firmware errors (`!!` prefix or `Error`)

---

## Shutdown (`stop`)

Called on `SIGTERM`, `SIGINT`, or an unhandled exception from `gather`:

1. `is_running = False` — the poll loop exits on next iteration
2. `poll_task.cancel()` / `websocket_task.cancel()`
3. `printer_client.disconnect()` — closes the WS connection cleanly
4. `discord_notifier.__aexit__()` — closes the aiohttp session

---

## Entry points

```python
# Called by main.py
async def main():
    service = AlertNotificationService()
    await service.start()
```

`main.py` calls `asyncio.run(main())`. `start()` blocks until the service stops.
