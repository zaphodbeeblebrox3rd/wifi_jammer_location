#!/bin/bash
# One-shot setup for WiFi Jammer / Deauth Monitor: systemd service, optional Wi-Fi monitor mode,
# and dashboard autostart at user login.
#
# Usage: sudo ./scripts/setup-monitoring.sh [wifi_interface]
# Example: sudo ./scripts/setup-monitoring.sh
# Example: sudo ./scripts/setup-monitoring.sh wlo1
#
# With no argument: installs systemd service and dashboard autostart for the user who ran sudo.
# With wifi_interface: also configures persistent Wi-Fi monitor mode for that interface (udev + systemd + NM unmanaged).

set -e

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this script as root (e.g. sudo $0 [wifi_interface])" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_PATH="$PROJECT_ROOT/config/config.yaml"
WIFI_IFACE="${1:-}"

# ---- Python autodetect ----
REAL_USER="${SUDO_USER:-}"
if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
  WJL_PYTHON="$PROJECT_ROOT/.venv/bin/python"
elif [ -x "$PROJECT_ROOT/venv/bin/python" ]; then
  WJL_PYTHON="$PROJECT_ROOT/venv/bin/python"
elif [ -n "$REAL_USER" ]; then
  WJL_PYTHON="$(su - "$REAL_USER" -c 'command -v python3' 2>/dev/null)" || true
fi
if [ -z "${WJL_PYTHON:-}" ] || [ ! -x "$WJL_PYTHON" ]; then
  WJL_PYTHON="/usr/bin/python3"
fi
if [ ! -x "$WJL_PYTHON" ]; then
  echo "Could not find python3. Install Python 3.8+ and run this script again." >&2
  exit 1
fi
echo "Using Python: $WJL_PYTHON"

# ---- Optional: Wi-Fi monitor mode ----
if [ -n "$WIFI_IFACE" ]; then
  echo "Configuring Wi-Fi monitor mode for $WIFI_IFACE ..."

  # 1. Helper script (interface-agnostic; udev passes interface name as first arg)
  echo "Creating /usr/local/bin/wifi-monitor-mode.sh ..."
  cat > /usr/local/bin/wifi-monitor-mode.sh << 'HELPER'
#!/bin/sh
[ -n "$1" ] || exit 0
/usr/sbin/iw dev "$1" set type monitor 2>/dev/null || true
/usr/sbin/ip link set "$1" up 2>/dev/null || true
HELPER
  chmod +x /usr/local/bin/wifi-monitor-mode.sh

  # 2. Udev rule
  echo "Creating udev rule for $WIFI_IFACE ..."
  echo "ACTION==\"add\", SUBSYSTEM==\"net\", KERNEL==\"$WIFI_IFACE\", RUN+=\"/usr/local/bin/wifi-monitor-mode.sh %k\"" > /etc/udev/rules.d/99-wifi-monitor.rules

  # 3. Systemd oneshot
  echo "Creating systemd service wifi-monitor.service ..."
  cat > /etc/systemd/system/wifi-monitor.service << SYSEOF
[Unit]
Description=Set Wi-Fi interface $WIFI_IFACE to monitor mode
After=network-pre.target
Before=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/wifi-monitor-mode.sh $WIFI_IFACE
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
SYSEOF
  systemctl daemon-reload
  systemctl enable wifi-monitor.service

  # 4. NetworkManager unmanaged
  echo "Telling NetworkManager to leave $WIFI_IFACE unmanaged ..."
  mkdir -p /etc/NetworkManager/conf.d
  cat > /etc/NetworkManager/conf.d/99-unmanage-wifi-monitor.conf << UNMANAGED
[keyfile]
unmanaged-devices=interface-name:$WIFI_IFACE
UNMANAGED

  # 5. Reload udev
  udevadm control --reload-rules

  # 6. Reload NetworkManager if present
  if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet NetworkManager 2>/dev/null; then
    systemctl reload NetworkManager 2>/dev/null || true
  fi

  # 7. Put interface in monitor mode now
  echo "Setting $WIFI_IFACE to monitor mode now ..."
  /usr/sbin/iw dev "$WIFI_IFACE" set type monitor 2>/dev/null && /usr/sbin/ip link set "$WIFI_IFACE" up 2>/dev/null || {
    echo "Warning: could not set $WIFI_IFACE to monitor mode right now (interface may be in use). It will be set at next boot." >&2
  }
  echo "Wi-Fi monitor mode configured for $WIFI_IFACE."
fi

# ---- WiFi Jammer Monitor systemd service ----
echo "Creating systemd service wjl.service ..."
cat > /etc/systemd/system/wjl.service << WJLEOF
[Unit]
Description=WiFi Jammer / Deauth Monitor - relay and dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$PROJECT_ROOT
ExecStart=$WJL_PYTHON main.py -c $CONFIG_PATH --no-browser
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
WJLEOF
systemctl daemon-reload
systemctl enable wjl.service
systemctl start wjl.service
echo "Started wjl.service."

# ---- Dashboard autostart at user login ----
if [ -n "$REAL_USER" ]; then
  USER_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"
  if [ -n "$USER_HOME" ] && [ -d "$USER_HOME" ]; then
    AUTOSTART_DIR="$USER_HOME/.config/autostart"
    mkdir -p "$AUTOSTART_DIR"
    DESKTOP_FILE="$AUTOSTART_DIR/wjl-dashboard.desktop"
    cat > "$DESKTOP_FILE" << DESKTOP
[Desktop Entry]
Type=Application
Name=WiFi Jammer Monitor Dashboard
Comment=Open the WiFi Jammer / Deauth Monitor dashboard at login
Exec=xdg-open http://localhost:8051
X-GNOME-Autostart-enabled=true
DESKTOP
    chown "$REAL_USER:$REAL_USER" "$DESKTOP_FILE"
    echo "Dashboard autostart installed for $REAL_USER (opens at next login)."
  fi
else
  echo "SUDO_USER not set; skipping dashboard autostart. Create ~/.config/autostart/wjl-dashboard.desktop manually if desired."
fi

# ---- Marker so main.py knows setup was run ----
touch "$PROJECT_ROOT/.wjl-setup-done"
echo "Created $PROJECT_ROOT/.wjl-setup-done (WiFi Jammer Monitor)"

# ---- Summary ----
echo ""
echo "Setup complete."
echo "  Service:  sudo systemctl start wjl   (already started)"
echo "            sudo systemctl stop wjl"
echo "            sudo systemctl status wjl"
echo "  Dashboard: http://localhost:8051 (opens at next login for $REAL_USER, or open manually)"
if [ -n "$WIFI_IFACE" ]; then
  echo "  Wi-Fi monitor: $WIFI_IFACE (wifi-monitor.service enabled)"
fi
