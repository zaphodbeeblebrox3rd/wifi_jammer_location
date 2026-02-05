# RF / Jamming Metrics and Events

This document describes the metrics and event types used by the WiFi Jammer / Deauth Monitor.

## Metrics (RF / Jamming only)

### `deauth_count`

**What it measures:** Number of 802.11 deauth frames received in the last capture window (monitor mode).  
**Why it matters:** Bursts of deauth frames can indicate a deauth attack (kicking clients off the network) or a misconfigured device.  
**Good values:** 0  
**Poor values:** Above threshold (default 5) raises a deauth_burst event.

### `disassoc_count`

**What it measures:** Number of 802.11 disassociation frames in the last capture window.  
**Why it matters:** Used with deauth to assess management-frame activity.  
**Good values:** 0  
**Poor values:** Above threshold raises a disassoc_burst event.

### `local_wifi_signal_dbm`

**What it measures:** Signal (RSSI) in dBm from the local Wi-Fi interface (radiotap when in monitor mode).  
**Why it matters:** Used with noise to infer SNR and possible RF jamming.  
**Units:** dBm  

### `local_wifi_noise_dbm`

**What it measures:** Noise floor in dBm from the local Wi-Fi interface.  
**Why it matters:** High noise or low SNR (signal − noise) can indicate RF jamming or heavy interference.  
**Poor values:** Above threshold (e.g. −70 dBm) may trigger rf_jamming event.  
**Units:** dBm  

### `rf_jam_detected`

**What it measures:** Set to 1 when local_wifi_noise_dbm exceeds `jamming_noise_threshold_dbm` or when SNR is below `jamming_snr_threshold_db`; 0 otherwise.  
**Why it matters:** Indicates possible RF jamming or severe interference; triggers rf_jamming event.  
**Good values:** 0  
**Poor values:** 1  

### Optional: `wifi_channel`, `wifi_util_pct`, `noise_dbm`

These may be present if provided by the collector. `noise_dbm` is a generic noise field; the primary RF metrics are the local_wifi_* and rf_jam_detected fields above.

## Event types

- **deauth_burst**: Raised when `deauth_count` exceeds `deauth_count_threshold` (default 5) in a capture window. Suggests possible deauth attack or misconfigured device.
- **disassoc_burst**: Raised when `disassoc_count` exceeds threshold. Suggests management-frame activity or attack.
- **rf_jamming**: Raised when `rf_jam_detected >= 1`. Suggests high noise or low SNR; possible RF jamming or interference.

## Inferences

For each event type the inference engine can suggest causes (e.g. wifi_deauth, wifi_rf_jamming, wifi_disassoc) with high/medium/low confidence. No weather, modem, or correlation analysis is performed.
