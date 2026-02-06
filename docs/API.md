# API Documentation

This document describes the HTTP relay API (for nodes) and the dashboard data API used by the WiFi Jammer / Deauth Monitor.

## Relay HTTP API (for nodes)

The relay exposes two endpoints when `role: relay`. All require header `X-API-Key: <api_key>` (or `Authorization: Bearer <api_key>`).

### POST /api/measurements

Submit a measurement from a node.

**Headers:** `Content-Type: application/json`, `X-API-Key: <api_key>`

**Body (JSON):**
- `timestamp` (optional; default: server now) – ISO format
- `deauth_count`, `disassoc_count` (optional)
- `local_wifi_signal_dbm`, `local_wifi_noise_dbm`, `rf_jam_detected` (optional)
- `wifi_channel`, `wifi_util_pct`, `noise_dbm` (optional)
- `node_name`, `name` (optional) – display name for this node
- `latitude`, `longitude` or `node_latitude`, `node_longitude` (optional) – for map

**Response:** `201 Created` with body `{"ok": true, "node_id": "<id>"}`.  
**Errors:** `401` missing/invalid API key, `400` invalid JSON, `500` registration failure.

On first POST with a given API key, the relay creates a node (id from hash of key). Subsequent POSTs update node name/lat/lon if provided and touch `last_seen`.

### GET /api/config

Return config for nodes (local_wifi, event_detection).

**Headers:** `X-API-Key: <api_key>`

**Response:** `200 OK` with JSON:
- `devices`: `{"local_wifi": {...}}`
- `event_detection`: `{...}`

**Errors:** `401` missing/invalid API key.

---

## Dashboard / Data API (internal)

The dashboard uses `DashboardAPI` and `DataService` for time series, events, inferences, and nodes. These are used by the Dash app, not exposed as HTTP except via the relay API above.

### DashboardAPI (src/wjl/dashboard/api.py)

- **get_time_series_data(start_time, end_time, metrics=None)** – Returns `{timestamps: [...], data: {metric: [values]}}` for RF metrics only.
- **get_events(start_time, end_time)** – Returns list of jamming events (deauth_burst, rf_jamming, disassoc_burst).
- **get_event_inferences(event, context_hours=24)** – Returns list of inferences for an event.
- **get_available_metrics()** – Returns list of RF/jamming metrics with display_name, unit, category.
- **get_data_range()** – Returns `{min_timestamp, max_timestamp}` from database.
- **get_nodes()** – Returns list of nodes for map: `{id, name, latitude, longitude, last_seen}`.

### DataService (src/wjl/dashboard/data_service.py)

- **get_time_series_data(start_time, end_time, metrics=None)** – DataFrame with timestamp and RF columns.
- **get_available_metrics()** – List of metric dicts (name, display_name, category, unit).
- **get_data_range()**, **get_summary_stats()**, **get_nodes_for_map()** – As used by DashboardAPI.

All metrics are RF/jamming only (deauth_count, disassoc_count, local_wifi_signal_dbm, local_wifi_noise_dbm, rf_jam_detected, etc.). No correlation or threshold-analysis endpoints.
