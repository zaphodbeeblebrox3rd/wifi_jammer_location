"""Main Dash application for the WiFi Jammer / Deauth Monitor dashboard."""

import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import dash
from dash import dcc, html, Input, Output, State, callback_context
import plotly.graph_objs as go
import pandas as pd

from ..config import Config
from ..database import Database
from .api import DashboardAPI
from .data_service import DataService
from .relay_api import register_relay_api

logger = logging.getLogger(__name__)


def utcnow():
    """Get current UTC time."""
    return datetime.now(timezone.utc)


class DashboardApp:
    """Main dashboard application."""

    def __init__(self, config: Config, database: Database):
        """
        Initialize dashboard application.

        Args:
            config: Configuration instance
            database: Database instance
        """
        self.config = config
        self.database = database

        # Initialize services
        self.data_service = DataService(database, config)
        self.api = DashboardAPI(self.data_service, config)

        # Initialize Dash app
        self.app = dash.Dash(__name__)
        self.app.title = "WiFi Jammer / Deauth Monitor"
        register_relay_api(self.app.server, self.config, self.database)

        # Setup layout
        self._setup_layout()

        # Setup callbacks
        self._setup_callbacks()

    def _channel_amplitude_node_options(self):
        """Options for channel amplitude node dropdown: Relay plus all nodes."""
        try:
            nodes = self.api.get_nodes()
        except Exception:
            nodes = []
        options = [{"label": "Relay", "value": "relay"}]
        for n in nodes:
            nid = n.get("id")
            if nid and nid != "relay":
                label = (n.get("name") or nid or "Node").strip() or nid
                options.append({"label": label, "value": nid})
        return options

    def _setup_layout(self):
        """Setup the dashboard layout."""
        # Calculate UTC time for initial time range store
        now_utc = utcnow()
        
        self.app.layout = html.Div(
            [
                # Header
                html.Div(
                    [
                        html.H1("WiFi Jammer / Deauth Monitor Dashboard", className="header-title"),
                        html.Div(
                            [
                                html.Label("Time Range:", style={"marginRight": "10px"}),
                                dcc.Dropdown(
                                    id="time-range-selector",
                                    options=[
                                        {"label": "Last Hour", "value": "1h"},
                                        {"label": "Last 6 Hours", "value": "6h"},
                                        {"label": "Last 24 Hours", "value": "24h"},
                                        {"label": "Last 7 Days", "value": "7d"},
                                        {"label": "Last 30 Days", "value": "30d"},
                                        {"label": "Custom", "value": "custom"},
                                    ],
                                    value="24h",
                                    style={"width": "200px", "display": "inline-block"},
                                ),
                                dcc.DatePickerRange(
                                    id="custom-date-range",
                                    display_format="YYYY-MM-DD HH:mm",
                                    style={"display": "none", "marginLeft": "10px"},
                                ),
                            ],
                            style={"display": "flex", "alignItems": "center", "marginTop": "10px"},
                        ),
                    ],
                    className="header",
                    style={
                        "padding": "20px",
                        "backgroundColor": "#f0f0f0",
                        "borderBottom": "2px solid #ccc",
                    },
                ),
                # Main content area
                html.Div(
                    [
                        # Events pane (sidebar)
                        html.Div(
                            [
                                html.H3("Jamming Events", style={"marginTop": "0"}),
                                html.Div(id="events-list", style={"maxHeight": "75vh", "overflowY": "auto"}),
                            ],
                            style={
                                "width": "25%",
                                "padding": "20px",
                                "backgroundColor": "#fafafa",
                                "borderRight": "1px solid #ddd",
                                "float": "left",
                            },
                        ),
                        # Main graph pane
                        html.Div(
                            [
                                # Graph controls
                                html.Div(
                                    [
                                        html.Button(
                                            "Auto-Range Axes",
                                            id="auto-range-btn",
                                            n_clicks=0,
                                            style={
                                                "padding": "5px 15px",
                                                "fontSize": "12px",
                                                "cursor": "pointer",
                                                "backgroundColor": "#FF9800",
                                                "color": "white",
                                                "border": "none",
                                                "borderRadius": "3px",
                                                "marginRight": "10px",
                                                "marginBottom": "10px",
                                            },
                                        ),
                                        html.Button(
                                            "Refresh",
                                            id="refresh-btn",
                                            n_clicks=0,
                                            style={
                                                "padding": "5px 15px",
                                                "fontSize": "12px",
                                                "cursor": "pointer",
                                                "backgroundColor": "#2196F3",
                                                "color": "white",
                                                "border": "none",
                                                "borderRadius": "3px",
                                                "marginBottom": "10px",
                                            },
                                        ),
                                    ],
                                    style={"marginBottom": "10px"},
                                ),
                                # Graph
                                dcc.Graph(id="main-graph", style={"height": "75vh"}),
                                # Inference modal (hidden by default)
                                html.Div(
                                    id="inference-modal",
                                    children=None,
                                    style={"display": "none"},
                                ),
                            ],
                            style={
                                "width": "75%",
                                "padding": "20px",
                                "float": "right",
                            },
                        ),
                    ],
                    style={"clear": "both", "display": "flex"},
                ),
                # Channel amplitude graph (5-min scan, one line per channel)
                html.Div(
                    [
                        html.H3("Channel amplitude (5 min)", style={"marginTop": "20px", "marginBottom": "10px"}),
                        html.P(
                            "Combined signal+noise (dBm) per channel. Enable devices.local_wifi.channel_scan in config.",
                            style={"fontSize": "12px", "color": "#666", "marginBottom": "10px"},
                        ),
                        html.Div(
                            [
                                html.Label("Node:", style={"marginRight": "8px", "fontWeight": "500"}),
                                dcc.Dropdown(
                                    id="channel-amplitude-node",
                                    options=self._channel_amplitude_node_options(),
                                    value="relay",
                                    clearable=False,
                                    style={"width": "220px", "display": "inline-block", "marginRight": "24px"},
                                ),
                                dcc.Checklist(
                                    id="channel-amplitude-hide-overlap",
                                    options=[{"label": "Hide overlapping 2.4\u2009GHz channels (2, 3, 4, 5, 7, 8, 9, 10)", "value": "hide"}],
                                    value=[],
                                    style={"display": "inline-block", "verticalAlign": "middle"},
                                    inputStyle={"marginRight": "6px"},
                                ),
                            ],
                            style={"marginBottom": "12px", "display": "flex", "alignItems": "center", "flexWrap": "wrap"},
                        ),
                        dcc.Graph(id="channel-amplitude-graph", style={"height": "800px"}),
                    ],
                    style={
                        "padding": "20px",
                        "backgroundColor": "#fafafa",
                        "borderTop": "1px solid #ddd",
                        "clear": "both",
                    },
                ),
                # Map pane (nodes)
                html.Div(
                    [
                        html.H3("Node Map", style={"marginTop": "20px", "marginBottom": "10px"}),
                        html.Div(id="map-container", style={"height": "400px", "width": "100%"}),
                    ],
                    style={
                        "padding": "20px",
                        "backgroundColor": "#ffffff",
                        "borderTop": "2px solid #ddd",
                        "clear": "both",
                    },
                ),
                # Store for current time range (initialize with default 24h range)
                # Use UTC for all time calculations since data is stored in UTC
                dcc.Store(
                    id="time-range-store",
                    data={
                        "start": (now_utc - timedelta(hours=24)).isoformat(),
                        "end": now_utc.isoformat(),
                    },
                ),
                # Store for auto-range trigger
                dcc.Store(id="auto-range-trigger", data=0),
                # Store for refresh trigger
                dcc.Store(id="refresh-trigger", data=0),
            ],
            style={"fontFamily": "Arial, sans-serif"},
        )

    def _setup_callbacks(self):
        """Setup Dash callbacks."""

        @self.app.callback(
            [Output("custom-date-range", "style"), Output("time-range-store", "data")],
            [Input("time-range-selector", "value")],
        )
        def update_time_range_selector(selected_range):
            """Update time range selector and calculate time range."""
            if selected_range is None:
                # Default to 24h if not set
                selected_range = "24h"
            
            if selected_range == "custom":
                return {"display": "inline-block", "marginLeft": "10px"}, {"start": None, "end": None}
            else:
                # Use UTC for all time calculations since data is stored in UTC
                end_time = utcnow()
                if selected_range == "1h":
                    start_time = end_time - timedelta(hours=1)
                elif selected_range == "6h":
                    start_time = end_time - timedelta(hours=6)
                elif selected_range == "24h":
                    start_time = end_time - timedelta(hours=24)
                elif selected_range == "7d":
                    start_time = end_time - timedelta(days=7)
                elif selected_range == "30d":
                    start_time = end_time - timedelta(days=30)
                else:
                    start_time = end_time - timedelta(hours=24)

                return (
                    {"display": "none", "marginLeft": "10px"},
                    {"start": start_time.isoformat(), "end": end_time.isoformat()},
                )

        @self.app.callback(
            Output("time-range-store", "data", allow_duplicate=True),
            [Input("custom-date-range", "start_date"), Input("custom-date-range", "end_date")],
            prevent_initial_call=True,
        )
        def update_custom_time_range(start_date, end_date):
            """Update time range from custom date picker."""
            if start_date and end_date:
                return {
                    "start": datetime.fromisoformat(start_date.replace("Z", "+00:00")).isoformat(),
                    "end": datetime.fromisoformat(end_date.replace("Z", "+00:00")).isoformat(),
                }
            return {"start": None, "end": None}

        @self.app.callback(
            Output("auto-range-trigger", "data", allow_duplicate=True),
            [Input("auto-range-btn", "n_clicks")],
            prevent_initial_call=True,
        )
        def trigger_auto_range(n_clicks):
            """Trigger auto-range when button is clicked."""
            return n_clicks if n_clicks else 0

        @self.app.callback(
            Output("refresh-trigger", "data", allow_duplicate=True),
            [Input("refresh-btn", "n_clicks")],
            prevent_initial_call=True,
        )
        def trigger_refresh(n_clicks):
            """Trigger graph refresh when button is clicked."""
            return n_clicks if n_clicks else 0

        @self.app.callback(
            [Output("main-graph", "figure"), Output("events-list", "children")],
            [
                Input("time-range-store", "data"),
                Input("auto-range-trigger", "data"),
                Input("refresh-trigger", "data"),
            ],
        )
        def update_graph_and_events(time_range, auto_range_trigger, refresh_trigger):
            """Update main graph (RF/jamming metrics only) and jamming events list."""
            if not time_range or not time_range.get("start") or not time_range.get("end"):
                return go.Figure(), html.Div("Select a time range")

            selected_metrics = [m["name"] for m in self.api.get_available_metrics()]
            if not selected_metrics:
                fig = go.Figure()
                fig.add_annotation(
                    text="No RF metrics configured",
                    xref="paper",
                    yref="paper",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                    font=dict(size=16),
                )
                fig.update_layout(height=600)
                return fig, html.Div("No metrics to display")

            # Parse timestamps - ensure they're timezone-aware (UTC)
            start_time_str = time_range["start"]
            end_time_str = time_range["end"]
            
            if isinstance(start_time_str, str):
                start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=timezone.utc)
            else:
                start_time = start_time_str
                
            if isinstance(end_time_str, str):
                end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
                if end_time.tzinfo is None:
                    end_time = end_time.replace(tzinfo=timezone.utc)
            else:
                end_time = end_time_str

            # Get time series data
            data = self.api.get_time_series_data(start_time, end_time, selected_metrics)
            
            # Debug logging
            logger.debug(f"Time range: {start_time} to {end_time}")
            logger.debug(f"Selected metrics: {selected_metrics}")
            logger.debug(f"Data keys: {data.keys() if data else 'None'}")
            logger.debug(f"Timestamps count: {len(data.get('timestamps', [])) if data else 0}")
            raw = data.get("data") if data else None
            logger.debug(f"Data metrics: {list(raw.keys()) if isinstance(raw, dict) else []}")

            # Create graph
            fig = go.Figure()

            # Check if we have data
            has_timestamps = data.get("timestamps") and len(data.get("timestamps", [])) > 0
            raw_data = data.get("data") if data else None
            has_data = isinstance(raw_data, dict) and len(raw_data) > 0
            
            if has_timestamps and has_data:
                # Parse timestamps from UTC, convert to local time for display
                timestamps_utc = []
                for ts_str in data["timestamps"]:
                    if isinstance(ts_str, str):
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                    else:
                        ts = ts_str
                    timestamps_utc.append(ts)
                
                # Convert UTC timestamps to local time for display
                timestamps = [ts.astimezone() for ts in timestamps_utc]

                # RF metrics: counts on left, dBm on right
                dbm_metrics = ["local_wifi_signal_dbm", "local_wifi_noise_dbm", "noise_dbm"]
                yaxis = "y"
                yaxis2 = "y2"
                y1_values = []
                y2_values = []

                for metric_name, values in data["data"].items():
                    valid_indices = [i for i, v in enumerate(values) if v is not None and not (isinstance(v, float) and (pd.isna(v) or math.isinf(v)))]
                    if not valid_indices:
                        continue
                    numeric_values = []
                    numeric_timestamps = []
                    for idx in valid_indices:
                        v = values[idx]
                        try:
                            if isinstance(v, (int, float)) and not (pd.isna(v) or math.isinf(v)):
                                numeric_values.append(float(v))
                                numeric_timestamps.append(timestamps[idx])
                            elif isinstance(v, str):
                                try:
                                    fv = float(v)
                                    if not (pd.isna(fv) or math.isinf(fv)):
                                        numeric_values.append(fv)
                                        numeric_timestamps.append(timestamps[idx])
                                except (ValueError, TypeError):
                                    pass
                        except (TypeError, ValueError):
                            pass
                    if not numeric_values:
                        continue
                    metrics_list = self.api.get_available_metrics()
                    metric_info = next((m for m in metrics_list if m["name"] == metric_name), {})
                    display_name = metric_info.get("display_name", metric_name)
                    unit = metric_info.get("unit", "")
                    current_yaxis = yaxis2 if metric_name in dbm_metrics else yaxis
                    if metric_name in dbm_metrics:
                        y2_values.extend(numeric_values)
                    else:
                        y1_values.extend(numeric_values)
                    fig.add_trace(
                        go.Scatter(
                            x=numeric_timestamps,
                            y=numeric_values,
                            name=f"{display_name} ({unit})" if unit else display_name,
                            yaxis=current_yaxis,
                            mode="lines+markers",
                            hovertemplate=f"<b>{display_name}</b><br>Time: %{{x}}<br>Value: %{{y:.2f}} {unit}<br><extra></extra>",
                        )
                    )

                yaxis_config = {"title": "Counts / RF Jam", "side": "left"}
                yaxis2_config = {"title": "Signal / Noise (dBm)", "side": "right", "overlaying": "y"}
                if y1_values:
                    y1_numeric = [float(v) for v in y1_values if isinstance(v, (int, float)) and not (pd.isna(v) or math.isinf(v))]
                    if y1_numeric:
                        y1_min, y1_max = min(y1_numeric), max(y1_numeric)
                        if y1_min == y1_max:
                            y1_min = y1_min - 1 if y1_min != 0 else -1
                            y1_max = y1_max + 1 if y1_max != 0 else 1
                        else:
                            r = y1_max - y1_min
                            y1_min -= r * 0.1
                            y1_max += r * 0.1
                        yaxis_config["range"] = [y1_min, y1_max]
                if y2_values:
                    y2_numeric = [float(v) for v in y2_values if isinstance(v, (int, float)) and not (pd.isna(v) or math.isinf(v))]
                    if y2_numeric:
                        y2_min, y2_max = min(y2_numeric), max(y2_numeric)
                        if y2_min == y2_max:
                            y2_min = y2_min - 1 if y2_min != 0 else -1
                            y2_max = y2_max + 1 if y2_max != 0 else 1
                        else:
                            r = y2_max - y2_min
                            y2_min -= r * 0.1
                            y2_max += r * 0.1
                        yaxis2_config["range"] = [y2_min, y2_max]
                fig.update_layout(
                    xaxis=dict(title="Time", range=[min(timestamps), max(timestamps)] if timestamps else None),
                    yaxis=yaxis_config,
                    yaxis2=yaxis2_config,
                    hovermode="x unified",
                    height=600,
                    legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
                )
            else:
                # No data - show empty graph with helpful message
                # Try to get the actual data range from the database
                try:
                    data_range = self.api.get_data_range()
                    if data_range.get("min_timestamp") and data_range.get("max_timestamp"):
                        min_ts = datetime.fromisoformat(data_range["min_timestamp"])
                        max_ts = datetime.fromisoformat(data_range["max_timestamp"])
                        message = f"No data available for selected time range.\n\nData exists from {min_ts.strftime('%Y-%m-%d %H:%M')} to {max_ts.strftime('%Y-%m-%d %H:%M')}.\n\nTry selecting 'Last 7 Days' or use the Custom date range."
                    else:
                        message = "No data available for selected metrics and time range.\n\nMake sure data has been collected and try selecting a longer time range."
                except Exception as e:
                    logger.debug(f"Error getting data range: {e}")
                    message = "No data available for selected metrics and time range.\n\nMake sure data has been collected and try selecting a longer time range."
                
                fig.add_annotation(
                    text=message,
                    xref="paper",
                    yref="paper",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                    font=dict(size=14),
                )
                fig.update_layout(
                    xaxis=dict(title="Time"),
                    yaxis=dict(title="Metrics", side="left"),
                    height=600,
                )
                return fig, html.Div("No events in selected time range")

            # Get events
            events = self.api.get_events(start_time, end_time)

            # Create events list
            events_html = []
            if events:
                for event in events:
                    severity_colors = {
                        "critical": "#d32f2f",
                        "severe": "#f57c00",
                        "moderate": "#fbc02d",
                        "minor": "#388e3c",
                    }
                    color = severity_colors.get(event["severity"], "#757575")

                    event_div = html.Div(
                        [
                            html.Div(
                                [
                                    html.Strong(event["event_type"].replace("_", " ").title()),
                                    html.Span(
                                        f" - {event['severity'].title()}",
                                        style={"color": color, "marginLeft": "5px"},
                                    ),
                                ],
                                style={"marginBottom": "5px"},
                            ),
                            html.Div(
                                datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                                style={"fontSize": "12px", "color": "#666"},
                            ),
                            html.Div(
                                event["description"],
                                style={"fontSize": "14px", "marginTop": "5px"},
                            ),
                            html.Button(
                                "Show Inferences",
                                id={"type": "inference-button", "index": event["event_id"]},
                                n_clicks=0,
                                style={
                                    "marginTop": "5px",
                                    "padding": "5px 10px",
                                    "fontSize": "12px",
                                    "cursor": "pointer",
                                },
                            ),
                        ],
                        id={"type": "event-item", "index": event["event_id"]},
                        style={
                            "padding": "10px",
                            "marginBottom": "10px",
                            "border": f"2px solid {color}",
                            "borderRadius": "5px",
                            "backgroundColor": "#fff",
                        },
                    )
                    events_html.append(event_div)
            else:
                events_html.append(html.Div("No events detected in this time range"))

            return fig, html.Div(events_html)

        # Non-overlapping 2.4 GHz channels to show when "hide overlapping" is on
        CHANNELS_OVERLAPPING_24GHZ = {2, 3, 4, 5, 7, 8, 9, 10}

        @self.app.callback(
            Output("channel-amplitude-graph", "figure"),
            [
                Input("time-range-store", "data"),
                Input("refresh-trigger", "data"),
                Input("channel-amplitude-node", "value"),
                Input("channel-amplitude-hide-overlap", "value"),
            ],
        )
        def update_channel_amplitude_graph(time_range, refresh_trigger, selected_node, hide_overlap):
            """Update channel amplitude graph (5-min scan, one line per channel)."""
            fig = go.Figure()
            graph_height = 800
            if not time_range or not time_range.get("start") or not time_range.get("end"):
                fig.add_annotation(
                    text="Select a time range",
                    xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False, font=dict(size=14),
                )
                fig.update_layout(height=graph_height)
                return fig
            start_time_str = time_range["start"]
            end_time_str = time_range["end"]
            if isinstance(start_time_str, str):
                start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=timezone.utc)
            else:
                start_time = start_time_str
            if isinstance(end_time_str, str):
                end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
                if end_time.tzinfo is None:
                    end_time = end_time.replace(tzinfo=timezone.utc)
            else:
                end_time = end_time_str
            node_id = selected_node if selected_node else "relay"
            data = self.api.get_channel_amplitude_time_series(start_time, end_time, node_id=node_id)
            timestamps_raw = data.get("timestamps") or []
            ch_data = data.get("data") or {}
            if hide_overlap and "hide" in hide_overlap:
                ch_data = {
                    k: v for k, v in ch_data.items()
                    if k.startswith("ch") and k[2:].isdigit() and int(k[2:]) not in CHANNELS_OVERLAPPING_24GHZ
                }
            if not timestamps_raw or not ch_data:
                fig.add_annotation(
                    text="No channel scan data. Enable devices.local_wifi.channel_scan in config, run as root (sudo), and wait for 5-min scans."
                    + (" Try another node." if node_id != "relay" else ""),
                    xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False, font=dict(size=12),
                )
                fig.update_layout(height=graph_height)
                return fig
            timestamps = []
            for ts_str in timestamps_raw:
                if isinstance(ts_str, str):
                    # Normalize: SQLite may return "YYYY-MM-DD HH:MM:SS" or ISO with T
                    normalized = ts_str.replace(" ", "T", 1).replace("Z", "+00:00")
                    try:
                        ts = datetime.fromisoformat(normalized)
                    except ValueError:
                        continue
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                else:
                    ts = ts_str
                timestamps.append(ts.astimezone())
            traces_added = 0
            for ch_key in sorted(ch_data.keys(), key=lambda x: int(x[2:]) if x.startswith("ch") and x[2:].isdigit() else 0):
                values = ch_data[ch_key]
                valid_xy = []
                for i, v in enumerate(values):
                    if v is None:
                        continue
                    if isinstance(v, float) and (pd.isna(v) or math.isinf(v)):
                        continue
                    try:
                        y_val = float(v)
                        if i < len(timestamps):
                            valid_xy.append((timestamps[i], y_val))
                    except (TypeError, ValueError):
                        continue
                if not valid_xy:
                    continue
                xs, ys = [p[0] for p in valid_xy], [p[1] for p in valid_xy]
                fig.add_trace(
                    go.Scatter(
                        x=xs, y=ys,
                        name=ch_key,
                        mode="markers+lines",
                        hovertemplate=None,
                    )
                )
                traces_added += 1
            fig.update_layout(
                xaxis=dict(title="Time"),
                yaxis=dict(title="Combined amplitude (dBm)"),
                hovermode="x",
                height=graph_height,
                legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
            )
            if traces_added == 0:
                fig.add_annotation(
                    text="Channel scan ran but no signal/noise was captured. Run as root (sudo) with interface in monitor mode for amplitude data.",
                    xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False, font=dict(size=12),
                )
            return fig

        @self.app.callback(
            Output("inference-modal", "children"),
            [Input({"type": "inference-button", "index": dash.dependencies.ALL}, "n_clicks")],
            [State("time-range-store", "data")],
        )
        def show_inferences(n_clicks_list, time_range):
            """Show inferences for clicked event."""
            ctx = callback_context
            if not ctx.triggered:
                return None

            button_id = ctx.triggered[0]["prop_id"]
            if not button_id or "n_clicks" not in button_id:
                return None

            # Extract event ID from button ID
            # Format: {"type": "inference-button", "index": "event_123"}.n_clicks
            try:
                # Get the part before .n_clicks
                id_str = button_id.split(".n_clicks")[0]
                
                # Try multiple parsing strategies
                button_dict = None
                
                # Strategy 1: Try JSON parsing (Dash typically uses double quotes)
                try:
                    button_dict = json.loads(id_str)
                except (json.JSONDecodeError, ValueError):
                    pass
                
                # Strategy 2: If JSON failed, try replacing single quotes with double quotes
                if button_dict is None:
                    try:
                        id_str_json = id_str.replace("'", '"')
                        button_dict = json.loads(id_str_json)
                    except (json.JSONDecodeError, ValueError):
                        pass
                
                # Strategy 3: Use regex to extract the index value directly
                if button_dict is None:
                    match = re.search(r'"index"\s*:\s*"([^"]+)"', id_str)
                    if match:
                        event_id = match.group(1)
                    else:
                        # Try with single quotes
                        match = re.search(r"'index'\s*:\s*'([^']+)'", id_str)
                        if match:
                            event_id = match.group(1)
                        else:
                            raise ValueError("Could not extract index from button_id")
                else:
                    event_id = button_dict.get("index")
                
                if not event_id:
                    logger.error(f"Could not extract event_id from button_id: {button_id}")
                    return None
            except (ValueError, SyntaxError, KeyError, AttributeError, TypeError) as e:
                logger.error(f"Error parsing button_id '{button_id}': {e}")
                return None

            # Get events to find the clicked one
            if not time_range or not time_range.get("start") or not time_range.get("end"):
                return None

            # Parse timestamps - ensure they're timezone-aware (UTC)
            start_time_str = time_range["start"]
            end_time_str = time_range["end"]
            
            if isinstance(start_time_str, str):
                start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=timezone.utc)
            else:
                start_time = start_time_str
                
            if isinstance(end_time_str, str):
                end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
                if end_time.tzinfo is None:
                    end_time = end_time.replace(tzinfo=timezone.utc)
            else:
                end_time = end_time_str
            events = self.api.get_events(start_time, end_time)

            event = next((e for e in events if e["event_id"] == event_id), None)
            if not event:
                return None

            # Get inferences
            inferences = self.api.get_event_inferences(event)

            if not inferences:
                return html.Div(
                    [
                        html.H4("No inferences available"),
                        html.Button("Close", id="close-modal", n_clicks=0),
                    ],
                    style={
                        "position": "fixed",
                        "top": "50%",
                        "left": "50%",
                        "transform": "translate(-50%, -50%)",
                        "backgroundColor": "white",
                        "padding": "20px",
                        "border": "2px solid #333",
                        "zIndex": "1000",
                    },
                )

            # Create inference display
            inference_items = []
            for inf in inferences:
                confidence_colors = {"high": "#4caf50", "medium": "#ff9800", "low": "#9e9e9e"}
                color = confidence_colors.get(inf["confidence"], "#757575")

                inference_items.append(
                    html.Div(
                        [
                            html.Strong(inf["cause_type"].replace("_", " ").title()),
                            html.Span(
                                f" ({inf['confidence']})",
                                style={"color": color, "marginLeft": "5px"},
                            ),
                            html.P(inf["description"], style={"marginTop": "5px"}),
                        ],
                        style={
                            "padding": "10px",
                            "marginBottom": "10px",
                            "borderLeft": f"4px solid {color}",
                            "backgroundColor": "#f9f9f9",
                        },
                    )
                )

            return html.Div(
                [
                    html.H3("Event Inferences"),
                    html.Div(inference_items),
                    html.Button("Close", id="close-modal", n_clicks=0, style={"marginTop": "10px"}),
                ],
                style={
                    "position": "fixed",
                    "top": "50%",
                    "left": "50%",
                    "transform": "translate(-50%, -50%)",
                    "backgroundColor": "white",
                    "padding": "20px",
                    "border": "2px solid #333",
                    "borderRadius": "5px",
                    "zIndex": "1000",
                    "maxWidth": "600px",
                    "maxHeight": "80vh",
                    "overflowY": "auto",
                },
            )

        @self.app.callback(
            Output("map-container", "children"),
            [Input("refresh-trigger", "data")],
        )
        def update_map(refresh_trigger):
            """Show map zoomed to node locations, or default 0.05 mile radius when no nodes."""
            nodes = self.api.get_nodes()
            with_coords = [
                n for n in nodes
                if n.get("latitude") is not None and n.get("longitude") is not None
                and not callable(n.get("latitude")) and not callable(n.get("longitude"))
            ]
            if with_coords:
                lats = [float(n["latitude"]) for n in with_coords]
                lons = [float(n["longitude"]) for n in with_coords]
                min_lat, max_lat = min(lats), max(lats)
                min_lon, max_lon = min(lons), max(lons)
                pad = 0.01
                bbox = f"{min_lon - pad},{min_lat - pad},{max_lon + pad},{max_lat + pad}"
                center_lat, center_lon = sum(lats) / len(lats), sum(lons) / len(lons)
                caption = html.Div(
                    [html.Span(f"{n.get('name', n.get('id', ''))}: {n.get('latitude')}, {n.get('longitude')}", style={"marginRight": "15px"}) for n in with_coords],
                    style={"marginTop": "8px", "fontSize": "12px", "color": "#555"},
                )
            else:
                # Default: 0.05 mile radius around config node or fallback center (relay-only or no nodes yet)
                radius_miles = 0.05
                _lat, _lon = self.config.node_latitude(), self.config.node_longitude()
                center_lat = _lat if _lat is not None else 41.0
                center_lon = _lon if _lon is not None else -87.0
                radius_deg_lat = radius_miles / 69.0
                radius_deg_lon = radius_miles / (69.0 * math.cos(math.radians(center_lat)))
                min_lat = center_lat - radius_deg_lat
                max_lat = center_lat + radius_deg_lat
                min_lon = center_lon - radius_deg_lon
                max_lon = center_lon + radius_deg_lon
                bbox = f"{min_lon},{min_lat},{max_lon},{max_lat}"
                caption = html.Div(
                    "No nodes with location yet. Map shows default 0.05 mile radius. Set node.location in config or have nodes POST with name/lat/lon.",
                    style={"marginTop": "8px", "fontSize": "12px", "color": "#666"},
                )
            osm_url = f"https://www.openstreetmap.org/export/embed.html?bbox={bbox}&layer=mapnik&marker={center_lat}%2C{center_lon}"
            return html.Div(
                [
                    html.Iframe(
                        src=osm_url,
                        style={"width": "100%", "height": "380px", "border": "none"},
                        title="Node map",
                    ),
                    caption,
                ],
            )

        @self.app.callback(
            Output("inference-modal", "style", allow_duplicate=True),
            [Input("close-modal", "n_clicks")],
            prevent_initial_call=True,
        )
        def close_modal(n_clicks):
            """Close inference modal."""
            if n_clicks and n_clicks > 0:
                return {"display": "none"}
            return {"display": "block"}

    def run(self, host: str = "127.0.0.1", port: int = 8051, debug: bool = False):
        """Run the dashboard server."""
        logger.info(f"Starting dashboard server on {host}:{port}")
        # Disable reloader when running in threads (it doesn't work in threads)
        # In newer Dash versions, use_reloader parameter is available on run()
        self.app.run(host=host, port=port, debug=debug, use_reloader=False)
