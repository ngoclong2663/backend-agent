# Story 33.12 — Edge AI / IoT

**Epic:** [33 — Domain plugins](epic33_domain_plugins.md) · **Requirements:** FR-47 · **Depends on:** 33.7

## User story

As an operator I want a dashboard of my sensors' readings and my cameras' detections, to see at a glance what's
offline or out of range, and to acknowledge alerts; as an admin I want to add devices, set alert rules and send
commands, so that the app works like a real monitoring product.

## Context

- Devices talk HTTPS only (D10): each device has an API key and posts readings, detections and heartbeats; no MQTT
  broker, no firmware, no live video (cameras send snapshots).
- The app is never empty (D11): a simulator posts data through the same API.
- Reuses the storage plugin (snapshots) and the jobs plugin (rules, the simulator, retention).

## Steps

1. **Domain** `templates/domains/iot/`: roles `device` (name, kind: sensor or camera, site and zone, status, last
   seen, battery, firmware), `site` (with zones), `metric` (name, unit, normal range); areas Operators (a new
   `monitoring` pattern), Admins (`back-office`), and the devices' API (no screens); required features telemetry,
   device registry, alert rules; optional detections, commands.
2. **Features**:
   - `telemetry` (`attachesTo: device`): an ingestion endpoint (`POST /ingest/readings`, a batch per device, the API key
     in a header, idempotent by device and timestamp); readings stored as a time series; aggregates per metric over
     a window (min, max, average per 5 min, hour or day); retention (raw 30 days, hourly aggregates kept), a job;
     the latest value per device and metric on the device's response;
   - `device-registry`: create a device and show its API key once (rotate later); heartbeats; status computed from
     last seen (online, stale, offline); battery and firmware; a device's page with its metrics;
   - `detections` (`attachesTo: device`, cameras): `POST /ingest/detections` with a label, confidence, bounding box and
     a snapshot upload (storage plugin); review (confirm or false positive); counts per label per day;
   - `alert-rules`: a rule is a metric threshold for a duration ("CO₂ > 1200 ppm for 10 min"), a detection label above
     a confidence ("pest ≥ 0.8"), or a device offline for a time; evaluated by a job; alerts move open →
     acknowledged → resolved, with who and when; notifications to the operators;
   - `commands` (`attachesTo: device`): reboot, set the reporting interval; queued until the device's next
     heartbeat, which returns pending commands; the result reported back;
   - `simulator`: the seed's devices post plausible readings (daily cycles, noise, a slow drift) and occasional
     detections and threshold crossings, in sandboxes and previews, so charts and alerts have data immediately.
3. **Types**:
   - **sensor monitoring**: overview (KPIs: devices online, open alerts, readings today; a chart per key metric for the
     last 24 h with the normal range shaded; sites and zones), a device page (each metric's chart with a window
     picker: 1 h, 24 h, 7 d), Alerts (open first, Acknowledge in one click), Devices (status, battery, last seen; filter
     offline);
   - **vision ops**: detections feed (snapshot, label, confidence, camera, time; Confirm or False positive), counts per
     label per day, a camera's page (latest snapshot, detections), Alerts.
4. **Kit sections**: `AppChart` and `AppKpis` (33.7) with units, the normal range and a "last updated" time; a status
   pill (online, stale, offline); `SnapshotCard` with the bounding box drawn over the image.
5. **The reference requirement** (the greenhouse) generated end to end and its tasks passing.

## Acceptance criteria

- [ ] On the preview, without any hardware: the overview's charts show the simulator's last 24 h in their units, an
      alert opens when a threshold is crossed and is acknowledged in one click, offline devices are found in one click,
      and a pest detection shows its snapshot with the box.
- [ ] A real device (a `curl` with its API key) posts a reading that appears on its chart.

## Verify

`make domain-check NAME=iot`, `make test` (ingestion idempotency, rule evaluation, command queue), `make kit-test`,
the real run in the UI.

## Status

Proposed 2026-11-10.
