"""Database operations for storing WiFi jamming / deauth monitoring data."""

import hashlib
import sqlite3
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Columns allowed in monitoring_data (slim schema)
MONITORING_DATA_COLUMNS = frozenset({
    "id", "timestamp", "node_id",
    "wifi_channel", "wifi_util_pct", "noise_dbm",
    "deauth_count", "disassoc_count",
    "local_wifi_signal_dbm", "local_wifi_noise_dbm", "rf_jam_detected",
})


class Database:
    """SQLite database manager for WiFi jamming monitoring data."""

    def __init__(self, db_path: str):
        """
        Initialize database connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: Optional[sqlite3.Connection] = None
        self._initialize()

    def _initialize(self) -> None:
        """Initialize database schema."""
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        cursor = self.conn.cursor()

        # Slim monitoring data table (RF / jamming only)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS monitoring_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                node_id TEXT,
                wifi_channel INTEGER,
                wifi_util_pct REAL,
                noise_dbm REAL,
                deauth_count INTEGER,
                disassoc_count INTEGER,
                local_wifi_signal_dbm REAL,
                local_wifi_noise_dbm REAL,
                rf_jam_detected INTEGER
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_timestamp ON monitoring_data(timestamp)"
        )

        # Migrate first (add node_id to existing tables) before creating node_id index
        self._migrate_schema(cursor)

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_node_id ON monitoring_data(node_id)"
        )

        # Nodes table (for relay: map display and API key mapping)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                latitude REAL,
                longitude REAL,
                api_key_hash TEXT,
                last_seen DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Per-channel amplitude at 5-min intervals (signal/noise per channel)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS channel_amplitude (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                node_id TEXT,
                channel INTEGER NOT NULL,
                signal_dbm REAL,
                noise_dbm REAL
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_channel_amplitude_timestamp ON channel_amplitude(timestamp)"
        )
        self.conn.commit()
        logger.info(f"Database initialized at {self.db_path}")

    def _migrate_schema(self, cursor: sqlite3.Cursor) -> None:
        """Add node_id to existing monitoring_data if missing."""
        cursor.execute("PRAGMA table_info(monitoring_data)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        if "node_id" not in existing_columns:
            try:
                cursor.execute("ALTER TABLE monitoring_data ADD COLUMN node_id TEXT")
                logger.info("Added node_id column to monitoring_data")
            except sqlite3.OperationalError as e:
                logger.warning(f"Migration node_id: {e}")

    def insert_measurement(self, data: Dict[str, Any]) -> None:
        """
        Insert a measurement into the database.

        Args:
            data: Dictionary containing measurement data. Only slim columns are stored.
        """
        if self.conn is None:
            raise RuntimeError("Database connection not initialized")

        with self._lock:
            if "timestamp" not in data:
                data["timestamp"] = datetime.utcnow()
            if isinstance(data["timestamp"], datetime):
                data["timestamp"] = data["timestamp"].isoformat()

            # Restrict to slim columns
            columns = [k for k in data.keys() if k in MONITORING_DATA_COLUMNS and k != "id"]
            if not columns:
                logger.warning("No valid columns to insert")
                return

            placeholders = ", ".join(["?" for _ in columns])
            values = [data.get(c) for c in columns]
            columns_str = ", ".join(columns)
            query = f"INSERT INTO monitoring_data ({columns_str}) VALUES ({placeholders})"
            try:
                cursor = self.conn.cursor()
                cursor.execute(query, values)
                self.conn.commit()
                logger.debug(f"Inserted measurement at {data.get('timestamp')}")
            except sqlite3.Error as e:
                logger.error(f"Error inserting measurement: {e}")
                self.conn.rollback()
                raise

    def upsert_node(
        self,
        node_id: str,
        name: str,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        api_key_hash: Optional[str] = None,
    ) -> None:
        """Insert or update a node (for relay)."""
        if self.conn is None:
            raise RuntimeError("Database connection not initialized")
        now = datetime.utcnow().isoformat()
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO nodes (id, name, latitude, longitude, api_key_hash, last_seen)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    latitude = COALESCE(excluded.latitude, latitude),
                    longitude = COALESCE(excluded.longitude, longitude),
                    api_key_hash = COALESCE(excluded.api_key_hash, api_key_hash),
                    last_seen = excluded.last_seen
                """,
                (node_id, name, latitude, longitude, api_key_hash, now),
            )
            self.conn.commit()

    def touch_node_last_seen(self, node_id: str) -> None:
        """Update last_seen for a node."""
        if self.conn is None:
            return
        now = datetime.utcnow().isoformat()
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE nodes SET last_seen = ? WHERE id = ?",
                (now, node_id),
            )
            self.conn.commit()

    def get_node_by_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """Return node row if api_key_hash matches. Relay uses this to resolve API key to node."""
        if self.conn is None:
            return None
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT id, name, latitude, longitude, last_seen FROM nodes WHERE api_key_hash = ?",
                (key_hash,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def insert_channel_amplitude(
        self,
        timestamp: datetime,
        node_id: Optional[str],
        channel: int,
        signal_dbm: Optional[float],
        noise_dbm: Optional[float],
    ) -> None:
        """Insert one channel-amplitude sample (5-min scan)."""
        if self.conn is None:
            raise RuntimeError("Database connection not initialized")
        ts = timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp
        with self._lock:
            self.conn.execute(
                """INSERT INTO channel_amplitude (timestamp, node_id, channel, signal_dbm, noise_dbm)
                   VALUES (?, ?, ?, ?, ?)""",
                (ts, node_id, channel, signal_dbm, noise_dbm),
            )
            self.conn.commit()

    def get_channel_amplitude(
        self, start_time: str, end_time: str
    ) -> List[Dict[str, Any]]:
        """Return channel_amplitude rows in time range for dashboard graph."""
        if self.conn is None:
            return []
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                """SELECT timestamp, channel, signal_dbm, noise_dbm
                   FROM channel_amplitude
                   WHERE timestamp >= ? AND timestamp <= ?
                   ORDER BY timestamp ASC""",
                (start_time, end_time),
            )
            rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def get_nodes_for_map(self) -> List[Dict[str, Any]]:
        """Return all nodes with id, name, latitude, longitude for dashboard map."""
        if self.conn is None:
            return []
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT id, name, latitude, longitude, last_seen FROM nodes ORDER BY name"
            )
            rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
            logger.info("Database connection closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
