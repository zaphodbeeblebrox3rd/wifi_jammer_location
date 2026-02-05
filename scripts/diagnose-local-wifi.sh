#!/bin/bash
# Diagnose why local Wi-Fi metrics (signal, noise, SNR) might not be collected.
# Run with: sudo ./scripts/diagnose-local-wifi.sh [interface]
# Example: sudo ./scripts/diagnose-local-wifi.sh wlo1
#
# Prints: interface state, iwconfig output, iw output, and a short tshark capture
# to see if signal/noise are available from iwconfig or from radiotap headers.

set -e

IFACE="${1:-wlo1}"
echo "=== Local Wi-Fi diagnostics for interface: $IFACE ==="
echo ""

if [ "$(id -u)" -ne 0 ]; then
  echo "Warning: not running as root. Some checks may fail (run with sudo)."
  echo ""
fi

echo "--- 1. Interface state (ip link) ---"
ip link show "$IFACE" 2>&1 || true
echo ""

echo "--- 2. iw dev $IFACE info ---"
iw dev "$IFACE" info 2>&1 || true
echo ""

echo "--- 3. iw dev $IFACE link (signal when associated; often empty in monitor mode) ---"
iw dev "$IFACE" link 2>&1 || true
echo ""

echo "--- 4. iwconfig $IFACE (Signal/Noise level in dBm; many drivers omit in monitor mode) ---"
if command -v iwconfig >/dev/null 2>&1; then
  iwconfig "$IFACE" 2>&1 || true
  if iwconfig "$IFACE" 2>&1 | grep -qi "signal level"; then
    echo "[OK] iwconfig reports Signal level"
  else
    echo "[--] iwconfig did not report Signal level (common in monitor mode)"
  fi
  if iwconfig "$IFACE" 2>&1 | grep -qi "noise level"; then
    echo "[OK] iwconfig reports Noise level"
  else
    echo "[--] iwconfig did not report Noise level (common in monitor mode)"
  fi
else
  echo "iwconfig not installed (wireless-tools package). Install with: apt install wireless-tools"
fi
echo ""

echo "--- 5. Short tshark capture (radiotap signal/noise from received frames) ---"
if command -v tshark >/dev/null 2>&1; then
  echo "Capturing for 3 seconds to see if radiotap.dbm_antsignal / dbm_antnoise are present..."
  timeout 3 tshark -i "$IFACE" -Y "radiotap" -T fields -e radiotap.dbm_antsignal -e radiotap.dbm_antnoise -c 20 2>&1 | head -25 || true
  if timeout 2 tshark -i "$IFACE" -Y "radiotap" -T fields -e radiotap.dbm_antsignal -c 5 2>&1 | grep -qE '^-?[0-9]'; then
    echo "[OK] Radiotap signal (dBm) is available; collector uses tshark radiotap as primary source for signal/noise."
  else
    echo "[--] No radiotap.dbm_antsignal in capture (driver may not report it, or no traffic)."
  fi
else
  echo "tshark not installed. Install with: apt install tshark"
fi
echo ""

echo "=== Summary ==="
echo "Signal/noise (SNR) in monitor mode come from tshark radiotap (primary). iw/iwconfig are used only when associated."
echo "Ensure: (1) interface in monitor mode (iw dev $IFACE set type monitor), (2) running as root, (3) tshark installed."
