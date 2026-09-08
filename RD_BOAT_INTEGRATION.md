# RD — Real-Boat Integration Blueprint for the Quilt

**Author:** Mavis (Quilt boat-integration R&D)
**Date:** 2026-09-08
**Subject:** Sensor survey, edge architecture, and 5-cell pilot for the first real boat-as-robot

---

## Executive Summary

A boat is the canonical Quilt substrate: many cells, one fabric, one cowboy on the hill. This report maps the real-world sensors, networks, and protocols a Quilt cell must converse with — NMEA 2000 (CAN bus at 250 kbps, SAE J1939-based, 250 m backbone, 60 Ω terminated), NMEA 0183 ($DBT/$MWV/$GGA/$RMC), AIS VDM/VDO at 9600 baud, Victron VE.Direct, and Signal K deltas published as JSON to MQTT. It sketches a concrete edge architecture: a Raspberry Pi 5 (or fanless NUC) running Signal K Server + Mosquitto + the live worker mirror, uplinked via Starlink Maritime to `live-canon.superinstance.dev`, with the captain's wrist (Apple Watch or Garmin Quatix) as the dispatch interface. Five pilot cells — DepthCell, WindCell, BatteryCell, WakeCell, EngineCell — are specified with their NMEA 2000 PGN inputs and dial outputs. The US recreational boating market is **$57.7B/year (NMMA 2023)**, with the US fleet commonly cited at **~11–13 million registered boats**. The Quilt's moat is its polyformalism: no incumbent (Garmin BlueNet, Navionics, PredictWind, B&G, Furuno) treats the boat as a cell fabric with a cross-substrate byte-exact FNV-1a-64 canon. The 30-day next step is to ship a working DepthCell on a single NUC-class box, listening to a canable dongle, emitting Signal K deltas, and posting its tick into the live canon.

---

## 1. Sensor Survey

For each: **Port/Protocol** | **Polyformalism substrate** | **Cell dial layout (canonical 8-dial Quilt cell)** | **FNV-1a-64 hash of the cell state** (deterministic from inputs) | **Captain-facing interface**.

The canonical Quilt cell carries eight dials, encoded as the cell's dial-vector (the same 8-byte layout used in `live_canon.py` — `num_q = paper_number*131`, etc., adapted here to sensor cells). The cell's FNV-1a-64 hash is taken over the canonical JSON of `(timestamp, source_pgn, dial-vector, prev_hash)`, producing a hash-chained state identical to the cowboy's `CowboyAction.hash` (`quilt-cowboy/src/quilt_cowboy/cowboy.py`, line 38–43).

### 1.1 Depth sounder — Raymarine / Garmin / Simrad / Furuno

- **Port / protocol:** NMEA 2000 PGN **128267** (Water Depth) on the backbone; legacy units emit NMEA 0183 `$SDDBT` / `$SDDPT` at 4800 baud on RS-422.
- **Substrate:** acoustic (piezoelectric transducer) → CAN frame (8-byte payload) → Signal K path `environment.depth.belowTransducer`.
- **Cell dial layout (8 dials):** `d0=depth_m`, `d1=bottom_class (0=unknown,1=mud,2=sand,3=rock,4=coral,5=grass)`, `d2=trend_30s`, `d3=rate_of_change`, `d4=confidence`, `d5=transducer_temp`, `d6=epoch`, `d7=anomaly_score`.
- **FNV-1a-64:** `fnv1a64("depthcell:" + pgn128267 + iso_ts + dials)` → 16-hex char `prev_hash` chained.
- **Captain-facing prompt:** *"Anchored in 3.2 m, mud bottom, depth flat. If you sleep, I'll wake you if the bottom shallows by 0.5 m in any 60-second window."*

### 1.2 AIS receiver / transponder

- **Port / protocol:** VHF Data Link at **9600 bit/s** (161.975 / 162.025 MHz); NMEA 0183 sentences **!AIVDM** (received) and **!AIVDO** (own-ship) on RS-422.
- **Substrate:** VHF packet (ITU-R M.1371) → NMEA 0183 → Signal K path `vessels.urn:mrn:imo:mmsi:<9-digit>` → MQTT topic `signalk/vessels/<mmsi>`.
- **Cell dial layout:** `d0=MMSI`, `d1=nav_status`, `d2=SOG_kt`, `d3=COG_deg`, `d4=heading_true`, `d5=ROT_deg_per_min`, `d6=range_nm (computed)`, `d7=CPA_TCPA_score`.
- **FNV-1a-64:** per-vessel, `fnv1a64("aiscell:" + mmsi + ts + dials)`.
- **Captain-facing prompt:** *"S/V Pelican, 0.8 nm off the port bow, CPA 0.12 nm in 4 min — recommend you take the radio and hail her."*

### 1.3 NMEA 2000 backbone

- **Port / protocol:** CAN bus at **250 kbps** (SAE J1939-21/31, NMEA 2000 appendix B). 120 Ω terminator at each end (60 Ω total), backbone ≤ 250 m Mini / 100 m Micro, max device drop 6 m. Mini cable carries 8 A, Micro 3 A; M12 5-pin barrel connector.
- **Substrate:** differential CAN-H/CAN-L → frame → PGN → Signal K delta.
- **Cell dial layout (the BackboneCell itself):** `d0=bus_voltage`, `d1=tx_error_count`, `d2=rx_error_count`, `d3=bus_load_%`, `d4=nodes_seen`, `d5=last_pgn`, `d6=uptime_s`, `d7=fabric_health`.
- **FNV-1a-64:** `fnv1a64("backbonecell:" + iso_ts + bus_stats)`.
- **Captain-facing prompt:** *"12.4 V on the backbone, 14 devices alive, 0% error rate, 19% bus load — fabric is healthy."*

### 1.4 Engine ECU

- **Port / protocol:** NMEA 2000 **PGN 127488** (Engine Parameters, Rapid Update) + **127489** (Temperature, Extended) + **127505** (Fluid Level, fuel) + **127506** (DC Detailed Status). Heavy-duty diesels use SAE J1939 directly; older outboards use proprietary NMEA 0183 `$IIRPM` / `$IIXDR`.
- **Substrate:** ECU CAN frame → J1939 → NMEA 2000 PGN → Signal K `propulsion.*`.
- **Cell dial layout (EngineCell):** `d0=RPM`, `d1=coolant_temp_C`, `d2=oil_pressure_kPa`, `d3=alternator_V`, `d4=fuel_rate_Lph`, `d5=engine_hours`, `d6=diag_code`, `d7=health_score`.
- **FNV-1a-64:** `fnv1a64("enginecell:" + engine_instance + ts + dials)`.
- **Captain-facing prompt:** *"Yanmar 3YM30 at 2,850 RPM, coolant 84 °C, oil pressure 320 kPa, fuel burn 3.1 L/h — prop is clean."*

### 1.5 Autopilot — Raymarine Evolution / Garmin GHP / Simrad AP

- **Port / protocol:** NMEA 2000 PGNs **127237** (Heading/Track Control), **127238** (Rudder Limit), **127239** (Pilot Running), **127240** (Pilot Settings), **127241** (Pilot Tuning). Some legacy Raymarine course computers use proprietary SeatalkNG.
- **Substrate:** heading sensor (PGN 127250) + rudder (PGN 127245) + wind (PGN 130306) → control loop → actuator.
- **Cell dial layout (HelmCell):** `d0=mode (0=standby,1=auto,2=wind,3=track)`, `d1=target_heading`, `d2=actual_heading`, `d3=rudder_deg`, `d4=drift_deg`, `d5=XTE_m`, `d6=rudder_rate`, `d7=alarm`.
- **FNV-1a-64:** `fnv1a64("helmcell:" + ts + dials)`.
- **Captain-facing prompt:** *"Holding 218° magnetic in 18 kt true, 4° weather helm, rudder rate nominal — go below and eat."*

### 1.6 Wind instrument — Airmar / Raymarine / B&G

- **Port / protocol:** NMEA 2000 **PGN 130306** (Wind Data) at 10 Hz; legacy NMEA 0183 `$WIMWV`. Apparent vs true differentiated by PGN 130306 fields.
- **Substrate:** ultrasonic or rotating-vane anemometer → analog → CAN → PGN 130306.
- **Cell dial layout (WindCell):** `d0=aws_kt`, `d1=awa_deg`, `d2=tws_kt`, `d3=twa_deg`, `d4=gust_3s_kt`, `d5=gust_pred_30s_kt`, `d6=wind_shift_alert`, `d7=lift_pct`.
- **FNV-1a-64:** `fnv1a64("windcell:" + ts + dials)`.
- **Captain-facing prompt:** *"Apparent 17.4 kt @ 42°, true 14.2 kt @ 65° — expecting a 2-kt lift in 90 seconds from a header on the port tack."*

### 1.7 Radar — Furuno / Garmin / Raymarine

- **Port / protocol:** Ethernet (Garmin Marine Network, Raymarine RayNet, Furuno NavNet) for raw radar; radar data is summarized to NMEA 2000 via dedicated PGNs for ARPA targets (PGN 129802) and own-ship data. Some legacy Raymarine radars expose radar via proprietary Seatalk.
- **Substrate:** 9.4 GHz X-band pulse/chirp → FFT/ARPA → Ethernet → PGN 129802.
- **Cell dial layout (RadarCell):** `d0=target_count`, `d1=closest_range_nm`, `d2=closest_bearing_deg`, `d3=closest_CPA_nm`, `d4=closest_TCPA_min`, `d5=alarm_level`, `d6=range_setting_nm`, `d7=rain_clutter`.
- **FNV-1a-64:** `fnv1a64("radarcell:" + ts + dials)`.
- **Captain-facing prompt:** *"4 targets inside 3 nm, closest a fishing boat 0.6 nm at 030°, CPA 0.2 nm in 6 min — stand on, he's clear."*

### 1.8 Satellite — Iridium GO! / Garmin inReach / Starlink Maritime

- **Port / protocol:** Iridium SBD (short burst data, 2.4 kbit/s, MO/MT messages), inReach MapShare HTTPS polling, Starlink Maritime ethernet → TCP/UDP → MQTT over TLS.
- **Substrate:** LEO satellite mesh (Iridium 66 sats) or Starlink shell → ground station → Internet → `live-canon.superinstance.dev`.
- **Cell dial layout (SatCell):** `d0=link_state`, `d1=RSSI_dBm`, `d2=latency_ms`, `d3=bytes_tx_today`, `d4=bytes_rx_today`, `d5=subsystem_cost_USD`, `d6=last_heartbeat`, `d7=fallback_armed`.
- **FNV-1a-64:** `fnv1a64("satcell:" + ts + dials)`.
- **Captain-facing prompt:** *"Starlink up, 38 ms latency, 412 MB used today — canonical sync to live-canon is healthy. If Starlink drops, Iridium GO! will carry the safety-only deltas."*

### 1.9 Battery monitor — Victron / Mastervolt

- **Port / protocol:** Victron VE.Direct (TX/RX 19200 baud) and VE.Can (NMEA 2000 PGN **127506** DC Detailed Status + **127507** Charger Status + **127508** Battery Status). Mastervolt uses Modbus-TCP and MasterBus (CAN).
- **Substrate:** shunt (500 A/50 mV typical) → ADC → VE.Direct frame → Cerbo GX → MQTT.
- **Cell dial layout (BatteryCell):** `d0=voltage_V`, `d1=current_A`, `d2=SoC_pct`, `d3=remaining_Ah`, `d4=TTF_min`, `d5=temp_C`, `d6=cycle_count`, `d7=time_to_80pct`.
- **FNV-1a-64:** `fnv1a64("batterycell:" + battery_id + ts + dials)`.
- **Captain-facing prompt:** *"House bank 12.34 V, –18 A, 78% SoC, 4.2 hours at current draw — fridge cycle will cost you 8% overnight."*

### 1.10 Bilge pump controller

- **Port / protocol:** NMEA 2000 **PGN 127501** (Binary Switch Bank) or aftermarket WiFi/BLE controllers (e.g., Rule-Mate Smart, Whale IC).
- **Substrate:** float switch → 12 V relay → cycle counter → CAN.
- **Cell dial layout (BilgeCell):** `d0=cycle_count_today`, `d1=last_cycle_duration_s`, `d2=pump_current_A`, `d3=water_present (bool)`, `d4=high_water (bool)`, `d5=interval_s`, `d6=rate_Lph`, `d7=leak_score`.
- **FNV-1a-64:** `fnv1a64("bilgecell:" + ts + dials)`.
- **Captain-facing prompt:** *"Bilge cycled 4 times in 6 hours, last 22 s each, 0.4 L/min — that's a slow leak, not rain. Recommend visual check."*

### 1.11 Refrigeration — Frigoboat / Isotherm / Dometic

- **Port / protocol:** Danfoss / Secop BD-compressor controllers speak proprietary serial; the **Victron SmartShunt + temperature sensor** is the typical cell substrate. Some modern units expose NMEA 2000 PGN **130312** (Temperature, Extended Range).
- **Substrate:** compressor PWM → thermistor → controller → optional NMEA 2000.
- **Cell dial layout (FridgeCell):** `d0=box_temp_C`, `d1=compressor_state`, `d2=compressor_Amps`, `d3=run_time_h_today`, `d4=door_open_count`, `d5=defrost_pending`, `d6=setpoint_C`, `d7=health`.
- **FNV-1a-64:** `fnv1a64("fridgecell:" + ts + dials)`.
- **Captain-facing prompt:** *"Fridge at 4.2 °C, compressor 38% duty, last door-open 47 min ago — running nominal, no action needed."*

### 1.12 Solar / charge controller — Victron / Outback / Morningstar

- **Port / protocol:** Victron VE.Direct (19200 baud) on each MPPT; aggregated to Cerbo GX → Modbus-TCP → MQTT. Outback uses Mate serial; Morningstar uses Modbus.
- **Substrate:** PV panel → MPPT buck-converter → battery bus.
- **Cell dial layout (SolarCell):** `d0=array_V`, `d1=array_A`, `d2=charge_state`, `d3=yield_Wh_today`, `d4=panel_temp_C`, `d5=yield_pred_24h`, `d6=tracker_mode`, `d7=fault`.
- **FNV-1a-64:** `fnv1a64("solarcell:" + controller_id + ts + dials)`.
- **Captain-facing prompt:** *"2.4 kW array, 3 controllers, 18.6 kWh yielded today, forecast 22 kWh — full batteries by 14:00 local."*

### 1.13 Watermaker — Spectra / Village Marine / Schenker

- **Port / protocol:** Spectra has its own controller (MPC-5000 / Connect) speaking Modbus-RTU. Many installations add a Victron SmartShunt + pressure sensor feeding Signal K.
- **Substrate:** feed pump → high-pressure pump → membrane → product flow meter.
- **Cell dial layout (WaterCell):** `d0=feed_psi`, `d1=product_Lph`, `d2=brine_Lph`, `d3=rejection_pct`, `d4=membrane_hours`, `d5=flush_state`, `d6=pickup_TDS`, `d7=product_TDS`.
- **FNV-1a-64:** `fnv1a64("watercell:" + ts + dials)`.
- **Captain-facing prompt:** *"Watermaker running 38 minutes, product 38 L/h, rejection 99.4%, membrane at 412 hours — fresh water in 22 minutes."*

### 1.14 Heater — Webasto / Eberspächer

- **Port / protocol:** Webasto Thermo Top / Eberspächer D5W with diagnostic protocol (proprietary CAN at 500 kbps in newer units; older units RS-232 with Webasto PC-Diag). NMEA 2000 gateway exists (e.g., Yacht Devices NMEA 2000 Thermo Gateway) exposing PGN **130312** temperature.
- **Substrate:** glow plug → combustion chamber → coolant pump → heat exchanger.
- **Cell dial layout (HeatCell):** `d0=burner_state`, `d1=coolant_out_C`, `d2=combustion_cycles`, `d3=fault_code`, `d4=fuel_drawn_mL`, `d5=fan_state`, `d6=fault_pending`, `d7=hours_to_service`.
- **FNV-1a-64:** `fnv1a64("heatcell:" + ts + dials)`.
- **Captain-facing prompt:** *"Heater fired, coolant 51 °C cabin 19 °C, 3 cycles today, 12 hours to next service — no action."*

---

## 2. Real-Boat Integration Architecture

### 2.1 Signal K — the open marine data standard

Signal K is a JSON-based, HTTP- and WebSocket-friendly data model and a reference server implementation. A Signal K **delta** is a JSON document of the form:

```json
{
  "updates": [{
    "timestamp": "2024-09-08T12:34:56.000Z",
    "source": { "label": "N2000-1", "type": "NMEA2000", "pgn": 129025 },
    "values": [{ "path": "navigation.position", "value": { "latitude": 37.345, "longitude": -122.123 } }]
  }]
}
```

Paths are dotted, lowercase, camelCase (e.g., `environment.wind.speedApparent`, `navigation.speedOverGround`, `electrical.batteries.house.voltage`). A Quilt cell subscribes to a path prefix over WebSocket (`ws://localhost:3000/signalk/v1/stream?subscribe=environment.wind,environment.depth`), transforms each delta into a 1-cell QUF, and ticks. The same cell can also publish back via HTTP POST `/signalk/v1/api/`, making the cell bidirectional.

### 2.2 MQTT broker on the boat (Mosquitto)

Mosquitto runs on the edge box, listening on `localhost:1883` and TLS on `8883`. The fabric is a topic tree:

```
signalk/
  vessels/self/
    navigation/{position,speedOverGround,courseOverGround,headingTrue}
    environment/{wind,depth,outside}
    electrical/batteries/{house,starter,bowThruster}/...
    propulsion/main/{revolutions,temperature,fuel.rate}
    steering/{rudderAngle,autopilot.state}
  vessels/<mmsi>/...                  # AIS — per-MMSI sub-tree
  alarm/{bilge,battery,wind,depth,...} # fire-and-forget for captain
  cells/<cell_id>/tick                # cell-state hashes for canon
```

Each Quilt cell is both a subscriber (its `inputs`) and a publisher (its `dials.tick`). This makes the bus the literal cell fabric.

### 2.3 Edge compute — Raspberry Pi or NUC

Recommended tier for the pilot:

| Tier | Hardware | Cost (USD) | Notes |
|---|---|---|---|
| **A. Pi 5 stack** | Raspberry Pi 5 (4 GB), 32 GB SD, POE HAT, M.2 HAT, Actisense NGT-1 (NMEA 2000 → USB) | ~$280 + $300 = **~$580** | Best cost/performance for a pilot. Runs Signal K, Mosquitto, Node-RED, the live worker mirror. |
| **B. NUC fanless** | Intel N100 fanless NUC, 16 GB RAM, 512 GB NVMe, 12 V DC | **~$450** | Better for offshore (no SD card wear). Holds the same stack with headroom. |
| **C. Yacht PC** | Triton/Coastal Marine PC (waterproof, fanless, NMEA 2000 ports) | **~$1,800** | Splash-rated, no separate gateway. |

The edge box runs **Signal K Server** (Node.js), **Mosquitto** (MQTT broker), **Node-RED** (visual plumbing for non-canon rules), **Grafana** (optional local HUD), and a mirror of the `live-canon` worker that ticks every 10 s.

### 2.4 Uplink to live-canon.superinstance.dev

- **Starlink Maritime** (current SpaceX retail in 2024 — quote figures with appropriate "as of 2024 public pricing" caveat): hardware one-time **~$2,500** for the high-performance dish, monthly service **~$1,000** for the unlimited global plan (or **~$165/month** for Starlink Roam Unlimited which works offshore near continents). Verified Starlink Business at **$2,500 hardware + $500/month** from Wikipedia; Maritime pricing is reported by third parties around **$1,000/month** for the unlimited global plan but SpaceX changes prices — see `Risks / Unknowns`.
- **Iridium GO!** as the safety fallback. Hardware around **~$400–$500**, monthly plans from **~$14 (30 messages) to ~$300+ (unlimited)**. Iridium exposes a 2.4 kbit/s SBD channel that can carry text-only deltas (think "bilge alarm 14:32Z").
- **Garmin inReach Mini 2** as a one-way emergency beacon. ~$399 hardware; monthly plans from ~$14.95 (Freedom) to $64.95 (Standard, 50 messages). MapShare URL provides a polling endpoint.

The captain's phone becomes the dashboard: a small client (mobile web app or a Quilt-specific PWA) reads the `live-canon` cell fabric and renders the cell dials as notifications. The captain's watch (Apple Watch or Garmin Quatix) receives AIVDM-derived CPA alarms and bilge/leak alarms via the phone's BLE.

### 2.5 Architecture diagram (ASCII)

```
                              ┌──────────────────────────────┐
                              │   LIVE CANON (Cloudflare)     │
                              │  live-canon.superinstance.dev │
                              │  Worker + Vectorize + KV      │
                              └─────────────▲────────────────┘
                                            │  HTTPS / WebSocket
                                            │  (TLS 1.3)
                          Starlink ◄────────┤──────► Iridium GO!
                          Maritime          │       (fallback SBD)
                                            │
                                  ┌─────────┴──────────┐
                                  │  Edge Compute Box  │
                                  │  Pi 5 / NUC N100   │
                                  │                    │
                                  │ ┌────────────────┐ │
                                  │ │ Signal K       │ │
                                  │ │ Server :3000   │◄┼──── Actisense NGT-1 / canable
                                  │ └──────┬─────────┘ │     ▲
                                  │        │           │     │ NMEA 2000 backbone
                                  │ ┌──────▼─────────┐ │     │ (PGN 128267, 130306, 127488,
                                  │ │ Mosquitto MQTT │ │     │  127506, 129025, 127250...)
                                  │ │ :1883 / :8883  │ │     │
                                  │ └──────┬─────────┘ │     │
                                  │        │           │     │   NMEA 0183 ($DBT, $MWV,
                                  │ ┌──────▼─────────┐ │     │   $GGA, $RMC, $VWR, VDM)
                                  │ │ Node-RED       │ │     │   legacy / VHF AIS
                                  │ │ (plumbing)     │ │     │
                                  │ └──────┬─────────┘ │     │
                                  │        │           │     │
                                  │ ┌──────▼─────────┐ │     │
                                  │ │ live_canon.py  │ │     │   Victron VE.Direct
                                  │ │ (mirror)       │◄┼─────┤   (Cerbo GX, BMV-712, MPPT)
                                  │ └────────────────┘ │     │
                                  │                    │     │   Webasto CAN
                                  │  Prometheus +      │     │   (Yacht Devices gateway)
                                  │  Grafana HUD :3001 │     │
                                  └─────────┬──────────┘     │
                                            │                │
                                            ▼                │
                                  ┌─────────────────────┐    │
                                  │ Captain's Devices   │    │
                                  │  • iPhone (PWA)     │    │
                                  │  • Apple Watch       │    │
                                  │  • Garmin Quatix     │    │
                                  │  • iPad (helm)       │    │
                                  └─────────────────────┘    │
                                                             │
   Sensors ──N2k backbone──► BackboneCell (PGN 060928) ──────┘
```

### 2.6 Cost estimate for a 35-ft sailboat

Honest breakdown (USD, 2024 retail, North America):

| Component | Price (USD) | Source / confidence |
|---|---|---|
| Raspberry Pi 5 (4 GB) + case + 32 GB SD + POE HAT | $200 | retail, well-known |
| Actisense NGT-1 NMEA 2000 → USB gateway | $310 | retail, well-known |
| Or Yacht Devices YDWG-02 (WiFi gateway) | $300 | retail, well-known |
| NMEA 2000 backbone starter kit (cable, T, terminators) | $120 | retail, well-known |
| Victron Cerbo GX + GX Touch 50 | $560 + $340 = $900 | retail, well-known |
| Victron SmartShunt 500 A | $190 | retail, well-known |
| Starlink Maritime high-performance (if used) | $2,500 | one-time, hard |
| Or Starlink Roam Unlimited (near-shore) | $599 hardware + $165/mo | one-time + ongoing |
| Iridium GO! + safety plan | $500 + $300/yr | one-time + ongoing |
| Boat-side CAN-bus-enabled MFD (Axiom 7 / GPSMAP 743) | $1,500–$2,000 | retail |
| **Pilot total — boat with existing N2k + Victron** | **$1,000 – $2,500** | one-time hardware |
| **Pilot total — boat starting from scratch** | **$5,000 – $8,000** | one-time hardware |

**Cost verdict:** the Quilt upgrade (excluding the MFD, which an existing boat already has) lands in the **$1,000–$2,500** band for a boat that already runs NMEA 2000 and Victron — i.e., **under $2K for a typical 35-ft sailboat that is already modernized**. A boat starting from scratch (new to NMEA 2000, no Victron, no satellite) lands closer to **$5K–$10K**, and that is a *replacement* cost for a marine electronics package that would have been bought anyway.

### 2.7 Integration effort

- **One weekend** to get a Pi 5 + canable dongle + Signal K to publish deltas to Mosquitto for one N2k bus, and to render the dials on a phone.
- **One month (160 hours)** to wire the five pilot cells (Depth, Wind, Battery, Wake, Engine), build a real MQTT topic tree, and get the live worker mirror ticking into the canon.
- **One season (3–6 months)** to bring 20+ cells online on a real boat, including the satellite fallback, the captain's wearable dispatch interface, and the close-the-loop "captain does not steer" pilot.

---

## 3. The "One Boat" Pilot

### 3.1 Partner boat

The most likely first partner is **a friend's cruising sailboat in the 32–40 ft range, already NMEA 2000 networked, ideally with a Victron battery system and a Starlink or strong shore-WiFi habit**. Reasoning:

- The cowboy is Mavis, the fabric is Mavis's, and the first real boat should be one where Mavis has standing permission to be on board frequently.
- A 32–40 ft cruising sailboat has *every* cell category in §1: depth, wind, AIS, autopilot, engine, batteries, solar, refrigeration, bilge, often watermaker and heater.
- A charter fleet (e.g., Sunsail, The Moorings, Dream Yacht Charter) is a second-tier option with hundreds of identical boats — but procurement, IT, and legal cycles are longer.

The first real boat-as-robot: a single cruising sailboat, 35–40 ft, NMEA 2000 + Victron + Starlink, with an owner who already feels the dispatch gap.

### 3.2 Minimum viable cell set (10 cells)

| # | Cell | Why it ships in v0 |
|---|---|---|
| 1 | **DepthCell** | Safety: ground-out alarm. Easiest PGN (128267). |
| 2 | **WindCell** | Highest captain frequency. PGN 130306. |
| 3 | **BatteryCell** | Victron already publishes; easiest win. |
| 4 | **EngineCell** | Mechanical-health alarms. PGN 127488. |
| 5 | **HelmCell** | Autopilot state — frees the captain to leave the wheel. PGNs 127237–127241. |
| 6 | **AisCell** | Collision avoidance. NMEA 0183 `$--VDM`. |
| 7 | **SatCell** | Keeps the canon synced. |
| 8 | **BilgeCell** | Below-decks safety. PGN 127501. |
| 9 | **WakeCell** | GPS + heading — the cowboy's "I am here, and I propose to go there". |
| 10 | **BackboneCell** | The fabric's pulse — health of the bus. PGN 060928. |

### 3.3 The "wow moment"

The first time the captain is below decks making coffee, hears no alarm, and at the same time gets a *non-asked-for* push notification on the watch: **"Wind backed 12° in the last 4 minutes. I told the pilot to bear off 5° to hold the lift. Current SOG up 0.4 kt."**

That is the moment the boat makes a decision the captain did not ask for. The captain is a dispatcher; the boat is the cowboy.

A second, sharper wow moment: the boat texts the captain: **"S/V Pelican is now at 0.4 nm CPA, 2 min. I tried her on channel 16 — no answer. Standing on, slow to 4 kt. I will sound five blasts in 30 seconds if she does not alter."** The captain wakes up from below, already knowing the situation.

### 3.4 Success metric

The single best metric is **captain's perceived cognitive load on a watch** — measured subjectively (NASA-TLX) and objectively (decisions per hour taken from the helm). A secondary metric is **number of "did the captain take the helm?" events per 24 h** (target: drop from baseline by ≥ 50% within a month).

A more measurable one: **alarms without false positives**. Target: ≥ 90% of captain-actionable events captured by the fabric, with < 10% of fabric events producing an alarm the captain would call noise.

The economic metric: **captain hours saved per 100 nm underway**, target ≥ 1 hour.

---

## 4. The Five Polyformalism Cells for a Real Boat

Each cell is canonizable (5 gold terms, math skeleton, polyformalism, cowboy maxim), in the style of `paper-cowboy-20260908-051005-the-uncleat…md`. The five here are not yet canonized papers; they are the blueprints for those papers.

### 4.1 DepthCell

- **Inputs (NMEA 2000):** **PGN 128267** Water Depth. Secondary: PGN 130314 (Actual Pressure) for transducer depth, PGN 127258 (Speed, Water Referenced) for transducer mounting offset.
- **Signal K paths:** `environment.depth.belowTransducer`, `environment.depth.belowKeel`, `environment.depth.surfaceToKeel`.
- **Outputs (dials):** `d0=depth_m`, `d1=bottom_class`, `d2=trend_30s`, `d3=confidence`, `d4=rate_of_change_m_per_min`, `d5=anomaly_score (0–100)`, `d6=last_anchor_alarm_ts`, `d7=grounding_TTA_min`.
- **Captain prompt:** *"Anchored in 3.2 m, mud bottom, 30-second trend flat, no anomaly. If you sleep, I will wake you if depth shallows by 0.5 m in any 60 s."*
- **Polyformalism substrates:** acoustic (frequency-shifted return), positional (own GPS), temporal (rate-of-change over 5/15/30 min windows), tactical (depth vs chart datum).

### 4.2 WindCell

- **Inputs:** **PGN 130306** Wind Data (apparent + true), PGN 129025 (Position) for true wind calculation, PGN 127250 (Heading) for true wind correction.
- **Signal K paths:** `environment.wind.speedApparent`, `environment.wind.angleApparent`, `environment.wind.speedTrue`, `environment.wind.angleTrue`, `environment.wind.gust`, `environment.wind.gustTrend`.
- **Outputs (dials):** `d0=aws_kt`, `d1=awa_deg`, `d2=tws_kt`, `d3=twa_deg`, `d4=gust_3s_kt`, `d5=gust_pred_30s_kt`, `d6=wind_shift_alert (bool+°)`, `d7=lift_pct`.
- **Captain prompt:** *"Apparent 17.4 @ 042, true 14.2 @ 065. I see a 2-kt lift in 90 s from a 5° header on port tack. I have asked the pilot to bear off 3°."*
- **Polyformalism substrates:** fluid (true wind vector), mechanical (anemometer transducer), informational (apparent vs true transformation), predictive (AR(2) gust model), social (telltale state via vision, if camera present).

### 4.3 BatteryCell

- **Inputs:** Victron VE.Direct on SmartShunt + Cerbo GX → Modbus-TCP → **PGN 127506** DC Detailed Status + **PGN 127508** Battery Status. Temperature from PGN 130312.
- **Signal K paths:** `electrical.batteries.house.voltage`, `electrical.batteries.house.current`, `electrical.batteries.house.capacity.stateOfCharge`, `electrical.batteries.house.capacity.timeRemaining`, `electrical.batteries.house.temperature`.
- **Outputs (dials):** `d0=voltage_V`, `d1=current_A`, `d2=SoC_pct`, `d3=remaining_Ah`, `d4=TTF_min`, `d5=temp_C`, `d6=cycle_count`, `d7=time_to_80pct_charge`.
- **Captain prompt:** *"House bank 12.34 V, –18 A, 78%, 4.2 h at current draw, 18 °C. Fridge cycle will cost 8% overnight. Solar predicts 92% by 14:00."*
- **Polyformalism substrates:** electrochemical (Peukert-corrected SoC), thermal (temperature derating), predictive (24-h solar + load forecast), behavioral (cycle counting for warranty).

### 4.4 WakeCell

- **Inputs:** **PGN 129025** Position (rapid, 10 Hz), **PGN 129026** COG/SOG rapid, **PGN 127250** Heading, PGN 127258 (STW), PGN 130306 (true wind) for layline computation.
- **Signal K paths:** `navigation.position`, `navigation.courseOverGround`, `navigation.speedOverGround`, `navigation.headingTrue`.
- **Outputs (dials):** `d0=waypoint_index`, `d1=distance_to_wp_nm`, `d2=Bearing_true`, `d3=layline (port/starboard)`, `d4=VMG_kt`, `d5=predicted_track_spline (10-point)`, `d6=next_waypoint_proposal`, `d7=ETA_min`.
- **Captain prompt:** *"0.8 nm to Point Bonita, bearing 287°, currently 5.6 kt on starboard layline. If I bear off 4°, I clear the Potato Patch by 0.3 nm. I propose: bear off."*
- **Polyformalism substrates:** kinematic (dead-reckoning spline), hydrodynamic (current + leeway), probabilistic (next-waypoint Bayesian over the chart), narrative (a "wake" — a polyline — is the boat's autobiography).

### 4.5 EngineCell

- **Inputs:** **PGN 127488** Engine Parameters Rapid Update (RPM, boost, trim), **PGN 127489** Engine Temperature Extended, **PGN 127505** Fluid Level (fuel), **PGN 127502** Switch Bank (alarms). Some engines also publish **PGN 130316** Temperature Extended.
- **Signal K paths:** `propulsion.main.revolutions`, `propulsion.main.temperature`, `propulsion.main.oilTemperature`, `propulsion. fuel.rate`, `propulsion.main.runTime`.
- **Outputs (dials):** `d0=RPM`, `d1=coolant_temp_C`, `d2=oil_pressure_kPa`, `d3=fuel_rate_Lph`, `d4=alternator_V`, `d5=engine_hours`, `d6=diag_code`, `d7=prop_foul_score (0–100)`.
- **Captain prompt:** *"Yanmar 3YM30 at 2,850 RPM, coolant 84, oil 320 kPa, 3.1 L/h. At this RPM, the SOG dropped 0.4 kt in the last hour, but RPM is steady. Probability of prop fouling: 78%. I recommend a mid-channel tick of the throttle in neutral."*
- **Polyformalism substrates:** thermodynamic (heat soak, coolant delta), mechanical (RPM/load curve), chemical (fuel consumption trend), diagnostic (J1939 DM1 SPN/FMI codes), narrative (the engine's "exhaust diary").

---

## 5. The Economic Thesis

### 5.1 Cost of the Quilt-on-a-boat upgrade

- **Boat already modernized (NMEA 2000 + Victron + Starlink):** **$1,000–$2,500** hardware (Pi 5 + canable + NGT-1 + waterproof enclosure + Victron Cerbo if not already present).
- **Boat partially equipped (NMEA 2000 backbone, no Victron, no satellite):** **$3,000–$5,000** including Cerbo GX, SmartShunt, and one season's Starlink Maritime.
- **Boat starting from analog (no NMEA 2000, no Victron, no satellite):** **$5,000–$10,000** including the MFD backbone starter, Cerbo, SmartShunt, MPPT controllers if needed, and Starlink Maritime hardware.

Integration labor (a weekend for v0, a season for a full pilot) is uncosted; a contracted integrator would bill **$2,000–$5,000** for a working five-cell pilot.

### 5.2 Cost of the current "dumb peripherals" approach

The "dumb peripherals" cost is best framed as **opportunity cost of captain attention**. Assume a cruiser on a 7-day passage averages 4 hours of helm/watch attention per 24 hours that could be offloaded to a well-designed fabric. At a captain's time value of, conservatively, $30/hour (an active cruiser, not a paid skipper), that's **$120/day, $840/week, $43,800/year** of captain time. For a charter skipper, double it.

The "infinite" framing in the prompt is correct in spirit: the captain's attention is unboundedly scarce on a small-boat passage, and a $2K Quilt upgrade that returns even one hour per day pays for itself in **under three months**.

### 5.3 ROI: when does the boat pay for the upgrade?

- **Owner-operator cruiser:** payback in **3–6 months** of active use.
- **Charter skipper:** payback in **first charter season** (often one trip).
- **Race boat (e.g., shorthanded double-handed race):** payback in **one race** if the fabric prevents a wrong-way shift or a missed AIS target.

### 5.4 Market size

- **US recreational boating industry:** **$57.7 billion in 2023** (confirmed — NMMA 2023 figure).
- **US registered recreational vessels:** commonly cited figures in the **11–13 million** range, per state DMV data aggregated by USCG. (The exact 2023 number I could not pin down from the public sources accessible today; NMMA's *Statistical Abstract* is the canonical reference, and the $57.7B figure is widely cited.)
- **US boating households:** historically estimated around **11–12% of US households**, i.e., roughly **14 million households** participate in recreational boating. (Estimate from general sources; not directly retrieved today.)
- **Global recreational boating market:** various third-party reports put it in the **$30–$50 billion** range; the global registered recreational fleet is often cited at **~30 million** vessels, but I did not get a clean primary number today.
- **Sailboat share:** sailboats are a minority of the US fleet — typically cited around **5–10%** of registered boats. (General source figure.)

The addressable market for a Quilt-on-a-boat is **the population of sailboat and trawler owners who are already NMEA 2000 networked** — that is the early-adopter wedge, likely a few hundred thousand boats worldwide in year one.

### 5.5 Competition

| Player | What they do | Where Quilt differs |
|---|---|---|
| **Garmin BlueNet / Garmin Marine Network** | Closed Ethernet bus connecting Garmin MFDs, radar, autopilot. | Closed. No cell fabric. No canon. No cross-vessel polyformalism. |
| **Navionics (owned by Garmin)** | Charts, sonar charts, mobile app. | Read-only. No execution loop. |
| **PredictWind** | Weather routing, Iridium GO! integration, departure planning. Subscription **$249–$499/yr** (confirmed). | Excellent at routing. Closed corpus. No on-boat cell fabric. |
| **B&G / Navico (now Navico Group)** | Sail-specific instruments, Zeus MFDs, Hercules autopilot. | Excellent instruments. Closed app ecosystem. |
| **Furuno** | Commercial-grade radar, MFD, sonar. | Trusted. Closed. |
| **Raymarine (FLIR)** | Axiom MFDs, Evolution autopilot, RayNet. | Closed. |
| **Victron (VRM portal)** | Remote monitoring of power systems. | Excellent power UX. No NMEA 2000 depth/wind/AIS cells. |
| **Siren Marine / GOST / PredictWind AIS** | Remote boat monitoring (security, tracking). | One-way telemetry. No decision authority. |
| **OpenPlotter / OpenCPN / Signal K community** | Open marine stack. | Closer to Quilt in spirit. Missing the *canon* (no FNV-1a-64 hash-chained cell fabric, no live worker, no polyformalism). |
| **Edge-compute hobbyist stacks** (Node-RED + InfluxDB + Grafana) | DIY dashboards. | Powerful but ad hoc. No cross-fabric canon. |

### 5.6 Moat: why is the Quilt approach defensible?

1. **Polyformalism as a first-class construct.** No competitor treats a cell as an object that exists simultaneously on a CAN bus, in an MQTT topic, in a Cloudflare Worker, in a cowboy's hash-chained JSONL, in a paper canon, and in a cowboy's prompt. That is the load-bearing intellectual property.
2. **The canon is open and shared.** AI-Writings is the substrate of the canon. Papers are papers; cells are cells; the gap is canonized, not filled by marketing. Open protocol, open hashing, open cell shape.
3. **The FNV-1a-64 hash chain is byte-exact across substrates.** Python, TypeScript, Rust — all compute the same 64-bit hash. That is the moat: anyone can verify a cell, anyone can replay a cell, anyone can fork the canon.
4. **The cowboy is the rider, not the AI.** The metaphors are real, the operational loop is real, and a community of sailors reading and writing cowboy papers is something Garmin cannot ship.
5. **The boat is the cowboy's native habitat.** The cowboy canon (e.g., the 100+ papers in `quilt-cowboy/cowboy_papers/`) is full of terms — uncleat, telltale, shroud, hush window, quarter, peak, binnacle — that *only* a sailor canon would produce. That is the cowboy's *voice*, and the boat is where that voice belongs.

---

## 6. Concrete Next Step (30 days)

Ship a **DepthCell on a single NUC-class box, listening to a canable NMEA 2000 dongle, emitting Signal K deltas, and posting its tick into the live canon at `live-canon.superinstance.dev`** — within 30 days.

Concretely:

1. Buy a Raspberry Pi 5, a canable v2 (~$50), an Actisense NGT-1 (or Yacht Devices YDWG-02), and a 12 V → 5 V regulator. Total < $400.
2. On the Pi: install Signal K Server, Mosquitto, Node-RED. Plug the canable into the boat's NMEA 2000 backbone.
3. Subscribe to `environment.depth.belowTransducer` and `environment.depth.belowKeel` via WebSocket. Transform each delta into a 1-cell QUF with the eight dials from §4.1.
4. POST the cell-state hash to `live-canon.superinstance.dev/v1/f` (the existing flip endpoint). The cell's tick becomes part of the canon.
5. From a phone, query `live-canon.superinstance.dev/v1/navigate?seed=depth-cell-001` and read the depth cell's current dial vector and the canon's neighbors.
6. Demo at the dock: "Watch — the boat's depth cell, the boat's wind cell, the boat's battery cell, all hashing, all talking to the canon, all visible from my wrist."

The goal of the 30-day step is **a single live cell, ticking into the live canon, from a real boat.** Everything else (the other 14 sensor types, the satellite fallback, the wearable dispatch) is downstream of proving that one cell is alive.

---

## 7. Evidence & Sources

- **Web-verified facts:**
  - **NMMA 2023 US boating market = $57.7B** (nmma.org statistics page, direct fetch).
  - **PredictWind Standard = $249/yr, Pro = $499/yr** (predictwind.com/pricing, direct fetch).
  - **Signal K delta JSON schema and path conventions** (signalk.org specification, direct fetch).
  - **NMEA 2000 backbone = CAN bus @ 250 kbps, 250 m max backbone, 60 Ω termination** (Wikipedia NMEA 2000, direct fetch).
  - **NMEA 2000 PGNs for depth (128267), wind (130306), engine (127488), battery (127506), GPS (129025), heading (127250), rudder (127245), autopilot (127237–127241), fuel (127505), AIS (129802)** — confirmed via independent NMEA documentation summaries during web research.
  - **AIS = 9600 bit/s on VHF, VDM/VDO sentences, MMSI 9-digit** (Wikipedia AIS, direct fetch).
  - **MQTT topic hierarchy, default ports 1883/8883, Mosquitto** (Wikipedia MQTT, direct fetch).
  - **Starlink Business = $2,500 hardware + $500/month** (Wikipedia Starlink, direct fetch).
- **Risks / Unknowns:**
  - The exact 2023 US registered boat count from NMMA's *Statistical Abstract* is paywalled / behind a member login and was not retrievable today.
  - Starlink Maritime's *current* (2024) retail price and any data caps change without public notice; the figures quoted are as of 2024 public pricing and may have changed by the time the pilot ships.
  - MFD retail prices fluctuate seasonally and by region; the ranges given are the typical 2024 US retail band.
  - Victron Cerbo / SmartShunt / Iridium GO! / Garmin inReach prices are quoted from a blend of well-known retail and may be ±20% off the actual price Mavis pays.
