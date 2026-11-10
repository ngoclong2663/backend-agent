# IoT: vision ops (camera detections and review)

Cameras run a model at the edge and send detections: a label, a confidence, a bounding box and a snapshot. No live
video. Operators review detections (confirm or dismiss), watch counts per label and handle the alerts that
detections raise. Admins add cameras, tune which labels and confidences matter, and send commands. A simulator posts
detections from the first minute.

## Studied

- Verkada Command: cloud camera fleet with people and vehicle detections and alerts.
- Rhombus Console: cloud cameras with detection events, thumbnails and alert policies.
- UniFi Protect: on-site camera system with smart detections and an event timeline.
- Frigate: open-source video recorder with object detection, events and review.
- Eagle Eye Networks: cloud video management with analytics events across sites.
- Roboflow (deploy and monitor): vision model deployment with prediction review.
- Ring (event history): consumer cameras with a motion and person event list with snapshots.

## People and areas

| Role | Area | First device |
|---|---|---|
| Operator | Monitoring (overview, detections, cameras, alerts) | Desktop, checked on a phone |
| Admin | Admin (cameras, labels, rules, sites, users) | Desktop |
| Camera | The ingestion API, with an API key each (no screens) | None |

## Pages

### Monitoring (operators)

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| Overview (home) | Menu "Overview" | `kpi-row`: cameras online, cameras offline (links to Cameras filtered offline), detections today, to review (links to Detections filtered), open alerts · `alert-list`: open alerts newest first (rule in words, label, confidence, camera, zone, time, Acknowledge) · `chart`: detections per label per hour for the last 24 h (stacked bars) · `card-row` "To review": the newest `snapshot-card`s with Confirm and Dismiss | Acknowledge, review, open a detection, open offline cameras |
| Detections | Menu "Detections" (to-review badge) | `tab-strip`: To review, Confirmed, Dismissed · `filter-bar`: label, confidence above, camera, zone, time range · `card-grid` of `snapshot-card`: snapshot with the box drawn, label, confidence as a percentage, camera, zone, time, Confirm, Dismiss | Confirm, dismiss, open, filter |
| Detection | A card | `snapshot-card`: the large snapshot with every box and its label · `record-header`: label, confidence, camera, zone, time, `status-pill` (to review, confirmed, dismissed) · `action-bar`: Confirm, Dismiss as false positive, Previous and Next in the review order · `timeline`: received, reviewed (who, when), alert raised · `card-row`: other detections from this camera in the same hour | Confirm, dismiss, next, open the camera |
| Cameras | Menu "Cameras" | `filter-bar`: status (online, stale, offline), site, zone · `data-table`: cameras (name, zone, `status-pill`, last seen, latest snapshot thumbnail, detections today) | Filter, open a camera |
| Camera | A row, a detection's camera | `record-header`: name, zone, `status-pill`, last seen, firmware · `snapshot-card`: the latest snapshot · `chart`: detections per label for the last 24 h, window picker (24 h, 7 d) · `card-grid` of `snapshot-card`: its recent detections · `timeline`: status changes and commands | Change window, open a detection |
| Alerts | Menu "Alerts" (open count badge) | `tab-strip`: Open, Acknowledged, Resolved · `alert-list`: each with its snapshot thumbnail | Acknowledge, resolve, open |
| Alert | A row | `record-header`: rule in words, `status-pill` · `snapshot-card`: the detection that raised it · `timeline`: opened, acknowledged, resolved · `form`: a note | Acknowledge, resolve, note |
| Reports | Menu "Reports" | `filter-bar`: site, label, range · `chart`: confirmed detections per label per day · `data-table`: counts per label per day, with the share dismissed | Change range, export |

### Admin

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| Cameras (admin home) | Menu "Cameras" | `data-table`: cameras (name, zone, `status-pill`, last seen, firmware, snapshot interval, pending commands) | Add camera, open |
| Add camera | Button "Add camera" | `form`: name, site and zone, labels it detects · then `secret-reveal`: the API key once, with Copy and an example request | Create, copy the key |
| Camera settings | A row | `command-panel`: Reboot, Set snapshot interval; pending and past commands with results · `form`: name, zone, labels, minimum confidence to store · Rotate key (`secret-reveal`) | Reboot, set interval, cancel pending, rotate key, retire |
| Rules | Menu "Rules" | `data-table`: rules in words (label, confidence above, zone, severity, enabled) | New rule, enable, disable |
| Rule editor | "New rule" or a row | `rule-builder`: kind (detection or offline), label, confidence above, zone scope, quiet time between alerts, severity; read back as a sentence · `card-row`: recent detections the rule would have matched | Save |
| Labels | Menu "Labels" | `data-table`: labels (name, shown to operators, default minimum confidence) | Add, edit |

## Main tasks

| Task | Role | Path (click by click) | Clicks | Budget |
|---|---|---|---|---|
| ack-alert: acknowledge the newest alert | Operator | Overview: Acknowledge on the first open alert | 1 | 1 |
| chart-24h: see a device's last 24 h as a chart | Operator | Overview shows all cameras for 24 h (0); for one camera: Cameras (1), the camera (2) | 2 | 2 |
| find-offline: find offline cameras | Operator | Overview: the "offline" KPI (1) opens Cameras filtered offline | 1 | 1 |
| review-detection: confirm or dismiss a detection | Operator | Overview: Confirm on the first "To review" card (1); or Detections (1), Confirm (2) | 1 (2) | 2 |
| reboot-device: send a reboot command | Admin | Cameras: the camera (1), Reboot (2); shown as pending with Cancel | 2 | 2 |
| Review a batch in order | Operator | Detections (1), the first card (2), Confirm or Dismiss moves to the next (3, 4...) | 2 + 1 each | 2 + 1 each |
| See counts per label per day | Operator | Reports (1) | 1 | 1 |
| Show only one label | Operator | Detections (1), the label in the filter bar (2) | 2 | 2 |
| Set a detection rule | Admin | Rules (1), New rule (2), fill "pest above 80% confidence", Save (3) | 3 | 3 |

## Data the pages need

- Camera: `name`, `site`, `zone`, `lastSeenAt`, `status`* (from last seen and the interval), `firmware`,
  `snapshotInterval`, `latestSnapshot`*, `detectionsToday`*.
- Detection: `label`, `confidence` (0 to 1, shown as a percentage), `boxes` (x, y, width, height relative to the
  image, with a label each), `snapshotUrl`, `camera`, `zone`, `detectedAt`, `reviewState` (to review, confirmed,
  dismissed), `reviewedBy`, `reviewedAt`, `alertId`.
- Review order: `nextToReview`* and `previousToReview`* by time within the current filter.
- Counts: per label per hour or day*, confirmed and dismissed shares*.
- KPIs: `camerasOnline`*, `camerasOffline`*, `detectionsToday`*, `toReview`*, `openAlerts`*.
- Alert: as in sensor monitoring, plus `detection` (thumbnail, label, confidence).
- Rule: `label`, `minConfidence`, `scope`, `quietMinutes`, `severity`, `enabled`, `lastFiredAt`*.
- Command: `kind`, `args`, `state`, `sentAt`, `deliveredAt`, `result`.

\* computed by the server. Detections below a label's minimum confidence are not stored.

## States

- Never empty: the simulator posts detections with snapshots from the first minute.
- Snapshot loading: the card keeps the image's shape; the box is drawn only once the image has loaded.
- Snapshot missing: a placeholder with the label and time, review still possible.
- Review: the card leaves the To review tab at once, with Undo for a few seconds.
- Nothing to review: "All caught up" with the time of the newest detection.
- Camera offline: its latest snapshot is shown with its age, never as current.
- Polling: "updated 20 s ago"; a failed poll keeps the cards and shows "reconnecting".

## Never shown to

- Operators: API keys, rules editing, commands, label thresholds, users.
- Admins: an API key after it has been shown once.
- Cameras: nothing but their own pending commands in the heartbeat reply.
- Anyone: live video (out of scope); dismissed detections are kept for reports but hidden from the default view.

## Options

- Review on the overview (default "To review" row) or only on the Detections page.
- Grid of cards (default) or one detection per screen for fast review.
- Confidence as a percentage (default) or as high, medium, low.
- Alerts from confirmed detections only, or from every detection above the rule's confidence (default).
- Boxes always drawn (default) or on hover.

## Slots used

- `action-bar`
- `alert-list`
- `card-grid`
- `card-row`
- `chart`
- `command-panel`
- `data-table`
- `filter-bar`
- `form`
- `kpi-row`
- `record-header`
- `rule-builder`
- `secret-reveal`
- `snapshot-card`
- `status-pill`
- `tab-strip`
- `timeline`
