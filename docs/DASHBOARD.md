# Dashboard User Guide

## Overview

The WiFi Jammer / Deauth Monitor Dashboard is a web-based view for RF/jamming metrics, jamming events, and node locations. It runs on the relay only.

## Starting the Dashboard

```bash
python dashboard.py
```

Or run the full app (relay with collection): `python main.py`. Dashboard defaults to http://localhost:8050 (configurable in `config.yaml`).

### Command line options (dashboard.py)

- `-c, --config PATH` – Config file  
- `-v, --verbose` – Verbose logging  
- `--host HOST` – Bind host  
- `--port PORT` – Bind port  
- `--debug` – Debug mode  

## Dashboard layout

### Header

- **Time range**: Last hour, 6h, 24h, 7d, 30d, or custom date range. All data is stored in UTC.

### Jamming Events (left pane)

- Timeline of jamming-related events: **deauth_burst**, **rf_jamming**, **disassoc_burst**.
- Each event shows type, severity, timestamp, and description.
- **Show Inferences**: Click to see suggested causes (e.g. wifi_deauth, wifi_rf_jamming).

### Line graph (center)

- Single graph of **RF/jamming metrics only**: deauth count, disassoc count, signal (dBm), noise (dBm), RF jam detected.
- Counts and RF jam on the left Y-axis; signal/noise (dBm) on the right Y-axis.
- No metric checkboxes; all RF metrics are shown.
- Buttons: **Auto-Range Axes**, **Refresh**.

### Node Map (bottom)

- OpenStreetMap embed zoomed to the bounding box of **nodes** that have latitude and longitude.
- Nodes appear after they POST measurements with `node_name` and `latitude`/`longitude` (or after relay has stored node locations). If no nodes have coordinates, a short message is shown instead.

## Relay API (for nodes)

- **POST /api/measurements** – Submit a measurement. Header: `X-API-Key: <api_key>`. Body: JSON with timestamp and RF fields (deauth_count, disassoc_count, local_wifi_signal_dbm, local_wifi_noise_dbm, rf_jam_detected, etc.). Optional: node_name, latitude, longitude.
- **GET /api/config** – Fetch config for nodes. Header: `X-API-Key: <api_key>`. Returns devices.local_wifi, event_detection.

See [RELAY_NODE_SETUP.md](RELAY_NODE_SETUP.md) for relay and node setup.
