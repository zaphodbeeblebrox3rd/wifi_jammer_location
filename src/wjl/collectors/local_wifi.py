"""Local Wi-Fi monitor collector: deauth frame counting and RF jamming inference."""

import logging
import re
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple

from .base import BaseCollector

logger = logging.getLogger(__name__)


class LocalWiFiCollector(BaseCollector):
    """Collector for local Wi-Fi interface in monitor mode: deauth/disassoc counts and RF metrics."""

    def __init__(self, config: Dict = None):
        """
        Initialize local Wi-Fi collector.

        Args:
            config: Configuration dictionary with:
                - interface: Wi-Fi interface name (e.g. wlan0)
                - ssid: SSID name to monitor; the interface is set to that network's channel before capture.
                  Preferred over channel when both are set. Scan may not work in monitor mode on some drivers.
                - channel: Channel number to monitor (1-14 for 2.4 GHz, 36+ for 5 GHz). Used when ssid is
                  unset or SSID lookup fails. If both unset, interface stays on current channel.
                - monitor_capture_seconds: Duration of capture per cycle for deauth (e.g. 30)
                - deauth_threshold: Count above which we consider a deauth event (e.g. 5)
                - jamming_noise_threshold_dbm: Noise (dBm) above which we flag jamming (e.g. -70)
                - jamming_snr_threshold_db: Min SNR (signal - noise dB) below which we flag jamming (e.g. 10)
        """
        super().__init__(config)
        self.interface = self.config.get("interface", "wlan0")
        self.ssid = self.config.get("ssid")  # If set, look up channel by scanning for this SSID
        self.channel = self.config.get("channel")  # Fallback when ssid unset or lookup fails
        self.monitor_capture_seconds = self.config.get("monitor_capture_seconds", 30)
        self.deauth_threshold = self.config.get("deauth_threshold", 5)
        self.jamming_noise_threshold_dbm = self.config.get("jamming_noise_threshold_dbm", -70)
        self.jamming_snr_threshold_db = self.config.get("jamming_snr_threshold_db", 10)

    def collect(self) -> Dict:
        """
        Collect deauth/disassoc counts and local Wi-Fi signal/noise; set rf_jam_detected when applicable.

        Returns:
            Dictionary with: deauth_count, disassoc_count, local_wifi_signal_dbm,
            local_wifi_noise_dbm, rf_jam_detected (0/1). Keys only present when data is available.
        """
        if not self.is_enabled():
            return {}

        result: Dict = {}

        try:
            # Ensure we're on the right channel: SSID (preferred) or channel, or leave as-is
            freq = None
            if self.ssid:
                freq = self._get_frequency_for_ssid(self.ssid)
                if freq is None:
                    logger.debug(
                        "Could not find channel for SSID %r (scan may not work in monitor mode); using channel=%s",
                        self.ssid,
                        self.channel,
                    )
            if freq is not None:
                self._set_frequency(freq)
            elif self.channel is not None:
                self._set_channel(self.channel)

            # Deauth/disassoc counts and optionally radiotap signal/noise from tshark
            deauth_count, disassoc_count, radiotap_signal, radiotap_noise = self._count_deauth_frames()
            if deauth_count is not None:
                result["deauth_count"] = deauth_count
            if disassoc_count is not None:
                result["disassoc_count"] = disassoc_count

            # Signal/noise: tshark radiotap is primary (monitor mode); iw/iwconfig used when associated
            signal_dbm = radiotap_signal
            noise_dbm = radiotap_noise
            if signal_dbm is None or noise_dbm is None:
                iw_signal, iw_noise = self._read_signal_noise()
                if signal_dbm is None and iw_signal is not None:
                    signal_dbm = iw_signal
                if noise_dbm is None and iw_noise is not None:
                    noise_dbm = iw_noise
            if signal_dbm is not None:
                result["local_wifi_signal_dbm"] = round(signal_dbm, 2)
            if noise_dbm is not None:
                result["local_wifi_noise_dbm"] = round(noise_dbm, 2)

            # RF jamming inference
            rf_jam = self._infer_rf_jamming(signal_dbm, noise_dbm)
            if rf_jam is not None:
                result["rf_jam_detected"] = rf_jam

        except (PermissionError, OSError) as e:
            logger.warning(
                "Local Wi-Fi collector requires root or CAP_NET_RAW/CAP_NET_ADMIN. %s",
                e,
            )
            return {}
        except Exception as e:
            return self._handle_error(e, "collecting local Wi-Fi metrics")

        return result

    def _get_frequency_for_ssid(self, ssid: str) -> Optional[int]:
        """Find the frequency (MHz) of the first BSS advertising the given SSID. Returns None if scan fails or SSID not found."""
        try:
            out = subprocess.run(
                ["iw", "dev", self.interface, "scan"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if out.returncode != 0:
                return None
            # Parse BSS blocks: "BSS aa:bb:cc(on wlo1)\n\tfrequency: 2437\n...\n\tSSID: MyNet\n"
            text = out.stdout or ""
            freq_re = re.compile(r"frequency:\s*(\d+)")
            ssid_re = re.compile(r"SSID:\s*(.+)$")
            current_freq: Optional[int] = None
            for line in text.splitlines():
                line = line.rstrip()
                if line.startswith("BSS "):
                    current_freq = None
                    continue
                m = freq_re.match(line.strip())
                if m:
                    current_freq = int(m.group(1))
                    continue
                m = ssid_re.match(line.strip())
                if m and current_freq is not None:
                    found_ssid = m.group(1).strip()
                    if found_ssid == ssid:
                        return current_freq
                    # SSID can be hex-encoded in some output; try raw match first
            return None
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None

    def _set_frequency(self, freq_mhz: int) -> None:
        """Set the interface to the given frequency in MHz. No-op if iw fails."""
        try:
            out = subprocess.run(
                ["iw", "dev", self.interface, "set", "freq", str(freq_mhz)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if out.returncode != 0:
                logger.debug(
                    "Could not set %s to freq %s: %s",
                    self.interface,
                    freq_mhz,
                    (out.stderr or out.stdout or "").strip(),
                )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    def _set_channel(self, channel: int) -> None:
        """Set the interface to the given channel (1-14 for 2.4 GHz, 36+ for 5 GHz). No-op if iw fails."""
        try:
            out = subprocess.run(
                ["iw", "dev", self.interface, "set", "channel", str(channel)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if out.returncode != 0:
                logger.debug(
                    "Could not set %s to channel %s: %s",
                    self.interface,
                    channel,
                    (out.stderr or out.stdout or "").strip(),
                )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    def _count_deauth_frames(self) -> Tuple[Optional[int], Optional[int], Optional[float], Optional[float]]:
        """Count deauth/disassoc and optionally get signal/noise from radiotap. Returns (deauth, disassoc, signal_dbm, noise_dbm)."""
        if shutil.which("tshark"):
            return self._count_deauth_tshark()
        try:
            deauth, disassoc = self._count_deauth_scapy()
            return deauth, disassoc, None, None
        except ImportError:
            logger.debug("Neither tshark nor scapy available for deauth counting")
            return None, None, None, None

    def _capture_signal_noise_duration(
        self, duration_sec: int
    ) -> Tuple[Optional[float], Optional[float]]:
        """Capture on current channel for duration_sec and return (signal_dbm, noise_dbm) from radiotap. Requires tshark."""
        if not shutil.which("tshark"):
            return None, None
        duration = max(1, min(duration_sec, 60))
        try:
            cmd = [
                "tshark",
                "-i", self.interface,
                "-Y", "wlan",
                "-a", f"duration:{duration}",
                "-q",
                "-T", "fields",
                "-e", "radiotap.dbm_antsignal",
                "-e", "radiotap.dbm_antnoise",
            ]
            out = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=duration + 10,
            )
            signal_values: List[float] = []
            noise_values: List[float] = []
            if out.returncode == 0 and out.stdout:
                for line in out.stdout.strip().splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 1 and parts[0].strip():
                        try:
                            sig_str = parts[0].strip()
                            if "," in sig_str:
                                sigs = [float(x.strip()) for x in sig_str.split(",") if x.strip()]
                                if sigs:
                                    signal_values.append(sum(sigs) / len(sigs))
                            else:
                                signal_values.append(float(sig_str))
                        except ValueError:
                            pass
                    if len(parts) >= 2 and parts[1].strip():
                        try:
                            noise_str = parts[1].strip()
                            if "," in noise_str:
                                noises = [float(x.strip()) for x in noise_str.split(",") if x.strip()]
                                if noises:
                                    noise_values.append(sum(noises) / len(noises))
                            else:
                                noise_values.append(float(noise_str))
                        except ValueError:
                            pass
            sig = round(sum(signal_values) / len(signal_values), 2) if signal_values else None
            noise = round(sum(noise_values) / len(noise_values), 2) if noise_values else None
            return sig, noise
        except subprocess.TimeoutExpired:
            return None, None
        except (OSError, PermissionError):
            raise

    def collect_per_channel(
        self, channels: List[int], duration_sec_per_channel: int
    ) -> List[Dict]:
        """
        Hop through channels, capture signal/noise on each. Returns list of
        {channel, signal_dbm, noise_dbm}. Caller sets interface to monitor mode.
        """
        result: List[Dict] = []
        for ch in channels:
            self._set_channel(ch)
            sig, noise = self._capture_signal_noise_duration(duration_sec_per_channel)
            result.append({
                "channel": ch,
                "signal_dbm": sig,
                "noise_dbm": noise,
            })
        return result

    def _count_deauth_tshark(self) -> Tuple[Optional[int], Optional[int], Optional[float], Optional[float]]:
        """Use tshark to count deauth/disassoc and extract radiotap signal/noise (dBm) from captured frames."""
        duration = max(1, min(self.monitor_capture_seconds, 120))
        try:
            # Capture management frames; output subtype and radiotap signal/noise when present
            cmd = [
                "tshark",
                "-i", self.interface,
                "-Y", "wlan.fc.type == 0",
                "-a", f"duration:{duration}",
                "-q",
                "-T", "fields",
                "-e", "wlan.fc.type_subtype",
                "-e", "radiotap.dbm_antsignal",
                "-e", "radiotap.dbm_antnoise",
            ]
            out = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=duration + 10,
            )
            deauth_count = 0
            disassoc_count = 0
            signal_values: List[float] = []
            noise_values: List[float] = []
            if out.returncode == 0 and out.stdout:
                for line in out.stdout.strip().splitlines():
                    parts = line.split("\t")
                    if not parts:
                        continue
                    try:
                        st = int(parts[0])
                    except (ValueError, IndexError):
                        continue
                    if st == 12:
                        deauth_count += 1
                    elif st == 10:
                        disassoc_count += 1
                    # Radiotap signal (dBm); driver may report multiple antennas as "-70,-70,-72"
                    if len(parts) >= 2 and parts[1].strip():
                        try:
                            sig_str = parts[1].strip()
                            if "," in sig_str:
                                sigs = [float(x.strip()) for x in sig_str.split(",") if x.strip()]
                                if sigs:
                                    signal_values.append(sum(sigs) / len(sigs))
                            else:
                                signal_values.append(float(sig_str))
                        except ValueError:
                            pass
                    if len(parts) >= 3 and parts[2].strip():
                        try:
                            noise_str = parts[2].strip()
                            if "," in noise_str:
                                noises = [float(x.strip()) for x in noise_str.split(",") if x.strip()]
                                if noises:
                                    noise_values.append(sum(noises) / len(noises))
                            else:
                                noise_values.append(float(noise_str))
                        except ValueError:
                            pass
            signal_dbm = round(sum(signal_values) / len(signal_values), 2) if signal_values else None
            noise_dbm = round(sum(noise_values) / len(noise_values), 2) if noise_values else None
            return deauth_count, disassoc_count, signal_dbm, noise_dbm
        except subprocess.TimeoutExpired:
            logger.warning("tshark capture timed out")
            return None, None, None, None
        except (OSError, PermissionError):
            raise

    def _count_deauth_scapy(self) -> Tuple[Optional[int], Optional[int]]:
        """Use scapy to count deauth and disassoc frames."""
        try:
            from scapy.all import Dot11, Dot11Deauth, Dot11Disas, sniff
        except ImportError:
            return None, None

        deauth_count = [0]
        disassoc_count = [0]

        def _count(pkt):
            if pkt.haslayer(Dot11Deauth):
                deauth_count[0] += 1
            elif pkt.haslayer(Dot11Disas):
                disassoc_count[0] += 1

        duration = max(1, min(self.monitor_capture_seconds, 120))
        try:
            sniff(
                iface=self.interface,
                prn=_count,
                store=False,
                timeout=duration,
                lfilter=lambda p: p.haslayer(Dot11) and (p.haslayer(Dot11Deauth) or p.haslayer(Dot11Disas)),
            )
        except (PermissionError, OSError) as e:
            logger.debug("Scapy sniff failed: %s", e)
            return None, None

        return deauth_count[0], disassoc_count[0]

    def _read_signal_noise(self) -> Tuple[Optional[float], Optional[float]]:
        """Read signal and noise (dBm) from iw (link) or iwconfig. Returns (signal_dbm, noise_dbm)."""
        # Try iw first (e.g. "signal: -67 dBm" when associated; often empty in monitor mode)
        try:
            out = subprocess.run(
                ["iw", "dev", self.interface, "link"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if out.returncode == 0 and out.stdout:
                m = re.search(r"signal:\s*(-?\d+(?:\.\d+)?)\s*dBm", out.stdout, re.IGNORECASE)
                if m:
                    signal_dbm = float(m.group(1))
                    # iw link rarely reports noise; try iwconfig for noise
                    _, noise_dbm = self._read_signal_noise_iwconfig()
                    return signal_dbm, noise_dbm
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # iwconfig: some drivers report Signal/Noise in managed or monitor mode
        signal_dbm, noise_dbm = self._read_signal_noise_iwconfig()
        if signal_dbm is not None or noise_dbm is not None:
            return signal_dbm, noise_dbm

        logger.debug(
            "Local Wi-Fi: no signal/noise from iw/iwconfig for %s (common in monitor mode). "
            "Signal/noise come from tshark radiotap in the same capture.",
            self.interface,
        )
        return None, None

    def _read_signal_noise_iwconfig(self) -> Tuple[Optional[float], Optional[float]]:
        """Read signal and noise (dBm) from iwconfig. Returns (signal_dbm, noise_dbm)."""
        try:
            out = subprocess.run(
                ["iwconfig", self.interface],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if out.returncode != 0:
                return None, None
            signal_dbm = None
            noise_dbm = None
            m = re.search(r"Signal\s+level[=:](-?\d+(?:\.\d+)?)\s*dBm", out.stdout, re.IGNORECASE)
            if m:
                signal_dbm = float(m.group(1))
            m = re.search(r"Noise\s+level[=:](-?\d+(?:\.\d+)?)\s*dBm", out.stdout, re.IGNORECASE)
            if m:
                noise_dbm = float(m.group(1))
            return signal_dbm, noise_dbm
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None, None

    def _infer_rf_jamming(self, signal_dbm: Optional[float], noise_dbm: Optional[float]) -> Optional[int]:
        """
        Set rf_jam_detected to 1 when noise is above threshold or SNR is below threshold; 0 otherwise.
        Returns None if no signal/noise data (do not set column).
        """
        if noise_dbm is not None and noise_dbm > self.jamming_noise_threshold_dbm:
            return 1
        if signal_dbm is not None and noise_dbm is not None:
            snr = signal_dbm - noise_dbm
            if snr < self.jamming_snr_threshold_db:
                return 1
        if noise_dbm is not None or signal_dbm is not None:
            return 0
        return None
