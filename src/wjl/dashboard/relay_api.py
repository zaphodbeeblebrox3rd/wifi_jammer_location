"""Relay API: POST /api/measurements (with API key) and GET /api/config for nodes."""

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict

from flask import Response, request

from ..config import Config
from ..database import Database

logger = logging.getLogger(__name__)


def register_relay_api(server, config: Config, database: Database) -> None:
    """Register relay API routes on the Flask/Dash server when role is relay."""
    if not config.is_relay():
        return

    def get_api_key():
        return (request.headers.get("X-API-Key") or request.headers.get("Authorization") or "").replace("Bearer ", "").strip()

    def json_response(data: Dict[str, Any], status: int):
        return Response(json.dumps(data), status=status, mimetype="application/json")

    @server.route("/api/measurements", methods=["POST"])
    def api_measurements():
        api_key = get_api_key()
        if not api_key:
            return json_response({"error": "Missing X-API-Key"}, 401)
        allowed = config.relay_api_key()
        if allowed is not None and api_key != allowed:
            return json_response({"error": "Invalid API key"}, 401)

        try:
            body = json.loads(request.get_data(as_text=True) or "{}")
        except json.JSONDecodeError:
            return json_response({"error": "Invalid JSON"}, 400)

        node_row = database.get_node_by_api_key(api_key)
        if node_row is None:
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            node_id = key_hash[:12]
            name = body.get("node_name") or body.get("name") or f"Node-{node_id}"
            lat = body.get("latitude") or body.get("node_latitude")
            lon = body.get("longitude") or body.get("node_longitude")
            database.upsert_node(
                node_id=node_id,
                name=name,
                latitude=float(lat) if lat is not None else None,
                longitude=float(lon) if lon is not None else None,
                api_key_hash=key_hash,
            )
            node_row = database.get_node_by_api_key(api_key)
        if not node_row:
            return json_response({"error": "Node registration failed"}, 500)

        node_id = node_row["id"]
        if body.get("node_name") or body.get("name"):
            name = body.get("node_name") or body.get("name")
            lat = body.get("latitude") or body.get("node_latitude")
            lon = body.get("longitude") or body.get("node_longitude")
            database.upsert_node(
                node_id=node_id,
                name=name,
                latitude=float(lat) if lat is not None else node_row.get("latitude"),
                longitude=float(lon) if lon is not None else node_row.get("longitude"),
                api_key_hash=None,
            )

        measurement = {
            "timestamp": body.get("timestamp"),
            "node_id": node_id,
            "wifi_channel": body.get("wifi_channel"),
            "wifi_util_pct": body.get("wifi_util_pct"),
            "noise_dbm": body.get("noise_dbm"),
            "deauth_count": body.get("deauth_count"),
            "disassoc_count": body.get("disassoc_count"),
            "local_wifi_signal_dbm": body.get("local_wifi_signal_dbm"),
            "local_wifi_noise_dbm": body.get("local_wifi_noise_dbm"),
            "rf_jam_detected": body.get("rf_jam_detected"),
        }
        if not measurement["timestamp"]:
            measurement["timestamp"] = datetime.utcnow().isoformat()
        database.insert_measurement(measurement)
        database.touch_node_last_seen(node_id)
        return json_response({"ok": True, "node_id": node_id}, 201)

    @server.route("/api/channel_amplitude", methods=["POST"])
    def api_channel_amplitude():
        """Accept channel amplitude samples from nodes (per-channel scan)."""
        api_key = get_api_key()
        if not api_key:
            return json_response({"error": "Missing X-API-Key"}, 401)
        allowed = config.relay_api_key()
        if allowed is not None and api_key != allowed:
            return json_response({"error": "Invalid API key"}, 401)

        node_row = database.get_node_by_api_key(api_key)
        if node_row is None:
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            node_id = key_hash[:12]
            database.upsert_node(
                node_id=node_id,
                name=f"Node-{node_id}",
                latitude=None,
                longitude=None,
                api_key_hash=key_hash,
            )
            node_row = database.get_node_by_api_key(api_key)
        if not node_row:
            return json_response({"error": "Node registration failed"}, 500)

        node_id = node_row["id"]
        try:
            body = json.loads(request.get_data(as_text=True) or "{}")
        except json.JSONDecodeError:
            return json_response({"error": "Invalid JSON"}, 400)

        samples = body.get("samples") or body.get("channel_amplitude") or []
        if not isinstance(samples, list):
            return json_response({"error": "samples must be an array"}, 400)

        stored = 0
        for s in samples:
            if not isinstance(s, dict):
                continue
            ts = s.get("timestamp")
            ch = s.get("channel")
            if ts is None or ch is None:
                continue
            if isinstance(ts, str):
                try:
                    ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except ValueError:
                    continue
            else:
                ts_dt = ts
            database.insert_channel_amplitude(
                ts_dt,
                node_id,
                int(ch),
                s.get("signal_dbm"),
                s.get("noise_dbm"),
            )
            stored += 1
        database.touch_node_last_seen(node_id)
        return json_response({"ok": True, "node_id": node_id, "stored": stored}, 201)

    @server.route("/api/config", methods=["GET"])
    def api_config():
        api_key = get_api_key()
        if not api_key:
            return json_response({"error": "Missing X-API-Key"}, 401)
        allowed = config.relay_api_key()
        if allowed is not None and api_key != allowed:
            return json_response({"error": "Invalid API key"}, 401)

        out = {
            "devices": {"local_wifi": config.get("devices.local_wifi", {})},
            "event_detection": config.get("event_detection", {}),
        }
        return json_response(out, 200)

    logger.info("Relay API registered: POST /api/measurements, GET /api/config")
