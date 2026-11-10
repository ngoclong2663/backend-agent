# IoT: sensor monitoring (fleet dashboard)

Sensors in sites and zones post readings through an HTTPS API. Operators watch the latest values and the last
24 hours as charts, find offline or low-battery devices and acknowledge alerts. Admins add devices, set alert rules
and send commands. A simulator posts readings from the first minute, so no page starts empty.

## Studied

- ThingsBoard: open IoT platform with dashboards, device profiles, rule chains and alarms.
- Azure IoT Central: hosted IoT apps with device templates, dashboards, rules and commands.
- AWS IoT SiteWise Monitor: industrial asset portals with time-series charts and alarms.
- Grafana: time-series dashboards with panels, time ranges and alert rules.
- Ubidots: IoT dashboards for sensors with events and device groups.
- Losant: IoT application platform with dashboards, workflows and device commands.
- Particle Console: device fleet console with status, vitals and remote functions.
- Monnit (iMonnit): wireless sensor monitoring with thresholds, battery and signal.

## People and areas

| Role | Area | First device |
|---|---|---|
| Operator | Monitoring (overview, sites, devices, alerts) | Desktop wall or laptop, checked on a phone |
| Admin | Admin (devices, rules, sites, metrics, users) | Desktop |
| Device | The ingestion API, with an API key each (no screens) | None |

## Pages

### Monitoring (operators)

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| Overview (home) | Menu "Overview" | `kpi-row`: devices online, offline (links to Devices filtered offline), low battery (links filtered), open alerts, readings in the last hour, each with a trend · `alert-list`: open alerts, newest first (severity, rule in words, device, zone, value with unit, opened time, Acknowledge) · `filter-bar`: site, window (1 h, 24 h, 7 d) · `chart` per key metric: the last 24 h per zone, the normal range shaded, unit on the axis, last updated time · `card-grid`: zones (name, `reading-grid` of latest values with unit and in-range state, devices offline count) | Acknowledge, open an alert, open a zone, change window, open offline devices |
| Zone | A zone card, a site's list | `record-header`: site and zone name, devices count · `reading-grid`: latest value per metric (value, unit, normal range, status, last updated) · `chart`: one per metric, window picker · `data-table`: the zone's devices (name, `status-pill`, battery, last seen) | Change window, open a device |
| Device | A row in Devices or a zone, an alert | `record-header`: name, kind, site and zone, `status-pill` (online, stale, offline), last seen, battery, firmware · `reading-grid`: latest per metric · `chart` per metric with the window picker and the normal range · `alert-list`: this device's recent alerts · `timeline`: status changes and commands | Change window, acknowledge, open an alert |
| Devices | Menu "Devices" | `filter-bar`: status (online, stale, offline), battery low, kind, site, zone · `data-table`: devices (name, zone, `status-pill`, last seen, battery, firmware, latest reading) | Filter, open a device |
| Alerts | Menu "Alerts" (open count badge) | `tab-strip`: Open, Acknowledged, Resolved · `filter-bar`: severity, site, rule · `alert-list` | Acknowledge, resolve, open |
| Alert | A row in any alert list | `record-header`: rule in words, severity, `status-pill` (open, acknowledged, resolved) · `chart`: the metric around the alert time with the threshold drawn · `timeline`: opened, acknowledged (who, when), resolved · `form`: a note | Acknowledge, resolve, add a note |
| Detections | Menu "Detections", when the site has cameras | `filter-bar`: label, camera, review state · `card-grid` of `snapshot-card` (image with box, label, confidence, camera, time, Confirm, Dismiss) | Confirm, dismiss, open |

### Admin

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| Devices (admin home) | Menu "Devices" | `filter-bar`: status, kind, zone · `data-table`: devices (name, kind, zone, `status-pill`, last seen, firmware, pending commands) | Add device, open a device |
| Add device | Button "Add device" | `form`: name, kind (sensor or camera), site and zone, metrics it reports, reporting interval · then `secret-reveal`: the API key shown once with Copy and an example request | Create, copy the key |
| Device settings | A row | `record-header`: name, `status-pill`, last seen · `command-panel`: Reboot, Set interval; pending and past commands (sent, delivered at next heartbeat, result) · `form`: name, zone, interval · Rotate key (`secret-reveal`) | Reboot, set interval, cancel a pending command, rotate key, retire |
| Rules | Menu "Rules" | `data-table`: rules (the rule in words, severity, enabled, last fired) | New rule, enable, disable |
| Rule editor | "New rule" or a row | `rule-builder`: kind (threshold, detection, offline), metric, comparison, value with unit, duration, zone scope, severity; the rule read back as a sentence · `chart`: the metric's last 24 h with the threshold drawn as a preview | Save, test against the last 24 h |
| Sites and zones | Menu "Sites" | `data-table`: sites with zones (name, device count) | Add, rename |
| Metrics | Menu "Metrics" | `data-table`: metrics (name, unit, normal range, decimals) | Add, edit range |

## Main tasks

| Task | Role | Path (click by click) | Clicks | Budget |
|---|---|---|---|---|
| ack-alert: acknowledge the newest alert | Operator | Overview: Acknowledge on the first open alert | 1 | 1 |
| chart-24h: see a sensor's last 24 h as a chart | Operator | Overview shows each key metric for 24 h (0); for one sensor: Devices (1), the device (2) | 2 | 2 |
| find-offline: find offline devices | Operator | Overview: the "offline" KPI (1) opens Devices filtered offline | 1 | 1 |
| review-detection: confirm or dismiss a detection | Operator | Detections (1), Confirm or Dismiss on the first card (2) | 2 | 2 |
| reboot-device: send a reboot command | Admin | Devices: the device (1), Reboot (2); the command shows as pending with Cancel | 2 | 2 |
| Add a device and get its API key | Admin | Devices: Add device (1), fill the form, Create (2), Copy key (3) | 3 | 3 |
| Set an alert rule | Admin | Rules (1), New rule (2), fill "CO2 above 1200 ppm for 10 min", Save (3) | 3 | 3 |
| See the last 7 days of a zone | Operator | Overview: a zone card (1), 7 d (2) | 2 | 2 |
| Resolve an acknowledged alert | Operator | Alerts (1), Acknowledged tab (2), Resolve (3) | 3 | 3 |

## Data the pages need

- Device: `name`, `kind`, `site`, `zone`, `lastSeenAt`, `status`* (online, stale, offline from last seen and the
  interval), `battery`, `firmware`, `interval`, `latest`* (latest value per metric with its time).
- Metric: `name`, `unit`, `normalMin`, `normalMax`, `decimals`.
- Reading grid: per metric `value`, `unit`, `at`, `inRange`* (from the normal range).
- Chart: `series`* per device or zone and metric, aggregated by window (raw for 1 h, 5 min averages for 24 h,
  hourly for 7 d, each with min, max, average), `normalMin`, `normalMax`, `lastUpdatedAt`*.
- KPIs: `devicesOnline`*, `devicesOffline`*, `lowBattery`*, `openAlerts`*, `readingsLastHour`*, each `trend`*.
- Alert: `rule` (in words*), `severity`, `device`, `zone`, `value`, `unit`, `openedAt`, `state` (open,
  acknowledged, resolved), `acknowledgedBy`, `acknowledgedAt`, `resolvedAt`, `notes`.
- Rule: `kind`, `metric`, `comparison`, `threshold`, `durationMinutes`, `scope`, `severity`, `enabled`,
  `lastFiredAt`*.
- Command: `kind` (reboot, set interval), `args`, `state` (pending, delivered, done, failed), `sentAt`,
  `deliveredAt`, `result`.
- API key: shown once on create or rotate; stored hashed*.

\* computed by the server. Alerts open from a job that evaluates rules, never from the browser.

## States

- Never empty: the simulator's readings fill charts and the reading grid from the first minute.
- Stale data: a value older than twice the interval is greyed with "last seen 14 min ago", never shown as current.
- A gap in the series breaks the chart line instead of joining across the gap.
- Out of range: the value and its point turn to the alert colour, with the range beside it.
- No open alerts: the alert list says "No open alerts" with the time of the last check.
- Polling: "updated 20 s ago" on each chart; a failed poll keeps the last data and shows "reconnecting".
- Command pending: shown until the device's next heartbeat, then delivered and its result.

## Never shown to

- Operators: API keys, rule editing, commands, device retirement, user management.
- Admins: an API key after it has been shown once.
- Devices: nothing but their own pending commands in the heartbeat reply.

## Options

- Units per user (°C or °F) or fixed per metric (default fixed).
- Charts per metric across zones (default) or per zone across metrics.
- Alerts acknowledged then resolved (default) or resolved automatically when back in range.
- Detections page on when any camera exists (default), or off.
- Overview as a wall display: no menu, larger figures, cycling sites.

## Slots used

- `alert-list`
- `card-grid`
- `chart`
- `command-panel`
- `data-table`
- `filter-bar`
- `form`
- `kpi-row`
- `reading-grid`
- `record-header`
- `rule-builder`
- `secret-reveal`
- `snapshot-card`
- `status-pill`
- `tab-strip`
- `timeline`
