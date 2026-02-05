# Relay and Node Setup

The WiFi Jammer / Deauth Monitor runs as either a **relay** (central server) or a **node** (client that pushes to the relay).

## Relay

- One relay per team. It holds the SQLite database, serves the dashboard, and (optionally) runs local WiFi collection.
- Set `role: relay` in config. Set `relay.api_key` to a shared secret; nodes must use this key in `X-API-Key` when POSTing measurements and GETting config.
- Bind dashboard where nodes can reach it (e.g. `dashboard.host: 0.0.0.0` and `dashboard.port: 8050`). Nodes will use `relay.url` (e.g. `http://<relay-ip>:8050`).

## Node

- Each node runs only the local WiFi collector and pushes measurements to the relay. It does not run a dashboard.
- Set `role: node`, `relay.url` (e.g. `http://192.168.1.100:8050`), and `relay.api_key` (same as relay). Set `node.name` and `node.location.latitude` / `longitude` so the relay map shows this node.
- Enable `devices.local_wifi` and (on Linux) put the WiFi interface in monitor mode (e.g. `sudo ./scripts/setup-monitoring.sh wlo1`).

## API Key

- Relay validates `X-API-Key` on POST /api/measurements and GET /api/config. If `relay.api_key` is set, only that key is accepted. If unset, any key is accepted and the relay creates one node per key (node_id = hash of key).
- Use a strong shared secret in production and keep it out of version control (e.g. env var `WIFI_JAMMER_API_KEY`).

## Config from relay

- Nodes can pull config from the relay: GET /api/config with `X-API-Key`. Response includes `devices.local_wifi` and `event_detection`. You can implement a startup step on the node to overwrite local config from this response.

## Node registration

- The first time a node POSTs with a given API key, the relay creates a node row (id from hash of key, name/lat/lon from request body if provided). Subsequent POSTs can include `node_name`, `latitude`, `longitude` to update the node’s display info and map position.
