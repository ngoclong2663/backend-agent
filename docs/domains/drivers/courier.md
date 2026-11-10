# Drivers: courier (driver, customer tracking, dispatch)

A shop or an operator creates a delivery with a pickup and a drop-off. Online drivers see it as an offer with the
fee; the first to accept takes it. The driver follows the steps to Delivered with a photo. The customer follows a
timeline. Dispatch sees every delivery by state and who is online. No maps or live GPS: addresses are text and the
route is a link out. Offers and the board refresh by polling.

## Studied

- DoorDash (Dasher app): food and retail courier app with offers, steps and earnings.
- Uber Driver (deliveries): ride and delivery driver app with an online switch and trip steps.
- Deliveroo Rider: restaurant delivery rider app with offers and fees.
- Glovo (couriers): multi-category courier app with order steps and proof.
- Stuart: on-demand courier platform for shops, with a driver app and a dispatch dashboard.
- Onfleet: last-mile delivery software with a dispatcher board, driver app and customer tracking.
- Lalamove: same-day van and bike delivery with order tracking.

## People and areas

| Role | Area | First device |
|---|---|---|
| Driver | Drivers (online switch, offers, active job, earnings, history) | Mobile-first, one hand, outdoors |
| Customer | Tracking (my deliveries, one delivery's timeline) | Mobile-first, often from a link |
| Dispatcher (shop or operator) | Dispatch (create, board, drivers) | Desktop |

## Pages

### Drivers

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| Home, no active job | Menu tab "Home" | `availability-toggle`: online or offline, time online today · `earnings`: today's total and job count · `offer-list` (online only): newest first; each offer: fee, pickup area and drop-off area as text, parcel size, distance text, time left to accept, Accept | Go online or offline, accept an offer, decline |
| Home, active job | Menu tab "Home" (replaces the offers while a job is active) | `status-pill`: the current step · `job-steps`: the next action as one big button (Arrived at pickup, Picked up, Arrived at drop-off, Delivered) with the done steps ticked above · `stop-card`: the current stop (name, address text, notes, "Open in maps" link out) · `contact-card`: the contact at this stop (name, Call, Message) · `proof-capture` at the drop-off step: Add photo, or the customer's code · `card-list`: delivery details (parcel size, fee, reference) | Next step, open in maps, call, add photo, report a problem |
| Report a problem | Button on the active job | `form`: reason (customer not there, wrong address, damaged, other), note, photo | Send (the delivery becomes failed or returns to dispatch) |
| Earnings | Menu tab "Earnings" | `tab-strip`: Today, This week · `earnings`: total, job count, fees and tips, online time · `card-list`: ledger lines (time, drop-off area, fee, tip) | Switch period, open a job |
| History | Menu tab "History" | `card-list`: past jobs (date, pickup and drop-off areas, `status-pill`: delivered, failed, cancelled, fee) | Open a job |
| Job (past) | Row in History or Earnings | `record-header`: reference, date, fee · `timeline`: each step with its time · `media`: the proof photo | None |
| Account | Menu tab "Account" | `profile-header`: name, photo, vehicle · `form`: phone, vehicle kind | Edit, sign out |

### Tracking (customer)

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| My deliveries | Menu tab "Deliveries" (home) | `tab-strip`: Active, Past · `card-list`: deliveries (shop name, `status-pill`, last update time) | Open a delivery |
| Tracking | A row, or the tracking link the shop sends | `status-pill`: the current state in words · `timeline`: created, driver assigned (the driver's first name), at pickup, picked up, on the way, delivered or failed, each with its time · `contact-card`: the driver's first name and photo, Call while active · `stop-card`: the drop-off address and notes · `media`: the proof photo once delivered | Call the driver, add drop-off notes before pickup |

### Dispatch

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| Board (home) | Menu "Board" | `kpi-row`: open offers, in progress, delivered today, failed today, drivers online · `filter-bar`: shop, date · `status-board`: columns by state (offered, accepted, picked up, delivered, failed); each card: reference, drop-off area, driver first name, age in this state | Open a delivery, new delivery |
| New delivery | Button "New delivery" on the board | `form`: pickup (name, address, phone), drop-off (customer name, address, phone, notes), parcel size, fee, assign: offer to online drivers or pick a driver | Create, create another |
| Delivery | A board card or a row | `record-header`: reference, `status-pill`, fee · `timeline`: every state change with its time and who · `stop-card`: pickup and drop-off · `contact-card`: driver and customer · `media`: the proof photo | Assign or reassign, cancel, copy the tracking link |
| Deliveries | Menu "Deliveries" | `filter-bar`: state, driver, date · `data-table`: deliveries (reference, created, state, driver, fee) | Open, export |
| Drivers | Menu "Drivers" | `filter-bar`: online, offline · `data-table`: drivers (name, `status-pill` online or offline, current delivery, jobs today, earned today) | Open a driver, assign a delivery |
| Driver | A row | `profile-header`: name, phone, vehicle · `earnings`: today, this week · `card-list`: recent jobs | Assign |

## Main tasks

| Task | Role | Path (click by click) | Clicks | Budget |
|---|---|---|---|---|
| accept-offer: accept the newest offer | Driver | Home (online): Accept on the first offer | 1 | 1 |
| deliver-with-photo: mark a delivery delivered with a photo | Driver | Home (active job at drop-off): Add photo (1), take or pick it (2), Delivered (3) | 3 | 3 |
| go-online: go online | Driver | Home: the availability toggle | 1 | 1 |
| see-earnings: see today's earnings | Driver | Home shows today's total; Earnings tab (1) for the lines | 0 (1) | 1 |
| track-delivery: follow a delivery's steps | Customer | The tracking link opens the timeline (0); or Deliveries: the delivery (1) | 1 | 1 |
| Create a delivery | Dispatcher | Board: New delivery (1), fill the form, Create (2) | 2 | 2 |
| See which drivers are online | Dispatcher | Board: the "drivers online" KPI (1) opens Drivers filtered online | 1 | 1 |
| Report a failed delivery | Driver | Home (active job): Report a problem (1), pick a reason, Send (2) | 2 | 2 |
| Call the customer | Driver | Home (active job, drop-off step): Call on the contact card | 1 | 1 |

## Data the pages need

- Offer: `fee`, `pickupArea`, `dropoffArea` (text), `parcelSize`, `distanceText`, `expiresAt`, `createdAt`;
  only to online drivers with no active job*.
- Active job: `state`, `nextAction`* (from the state), `currentStop`* (pickup before pick-up, drop-off after),
  `stops` (name, address, phone, notes), `parcelSize`, `fee`, `proofRequired`, `reference`.
- Availability: `online`, `onlineSince`, `onlineTimeToday`*.
- Earnings: `todayTotal`*, `weekTotal`*, `jobCountToday`*, ledger lines (`deliveryId`, `fee`, `tip`,
  `deliveredAt`).
- Tracking: `state`, `history`* (each state with `at` and `by`), `driverFirstName`*, `driverPhoto`, `dropoff`,
  `proofPhoto`, `customerNotes`.
- Board: deliveries grouped by `state`*, `ageInState`*, `driverFirstName`; KPIs `openOffers`*, `inProgress`*,
  `deliveredToday`*, `failedToday`*, `driversOnline`*.
- Driver row: `online`, `currentDelivery`*, `jobsToday`*, `earnedToday`*.

\* computed by the server. Accept is first come, first served: the server takes one driver per offer and refuses a
second accept, and refuses an accept from a driver with an active job.

## States

- Offline: the offer list is replaced by "Go online to see offers" with the toggle.
- Online, no offers: "Waiting for offers", refreshed by polling, with the time of the last check.
- Accept lost to another driver: the offer leaves the list with a short "taken" notice, no error page.
- Step buttons: one action at a time; the button shows progress and stays disabled until the server confirms.
- Delivered without proof: the button stays disabled until the photo (or code) is added.
- No signal: the step is queued on the phone and sent when back online, marked "sending".
- Customer, failed delivery: the timeline ends with the reason and what happens next.
- Board empty for today: "No deliveries yet" with New delivery.

## Never shown to

- Drivers: other drivers' offers and earnings, the customer's full name and phone after the job ends, dispatch's
  board and fee settings, offers while offline or on a job.
- Customers: the driver's surname, phone number (calls go through the app), earnings and fees paid to the driver,
  other customers' deliveries.
- Dispatchers (shop): other shops' deliveries; drivers' earnings beyond their own shop's jobs.

## Options

- Proof by photo (default), by the customer's four-digit code, or both.
- Offers to all online drivers (default) or direct assignment by dispatch.
- Earnings with tips (default) or fee only.
- Arrived steps shown (at pickup, at drop-off) or folded into the next step.
- Customer tracking signed in (Deliveries tab) or by a link only.

## Slots used

- `availability-toggle`
- `card-list`
- `contact-card`
- `data-table`
- `earnings`
- `filter-bar`
- `form`
- `job-steps`
- `kpi-row`
- `media`
- `offer-list`
- `profile-header`
- `proof-capture`
- `record-header`
- `status-board`
- `status-pill`
- `stop-card`
- `tab-strip`
- `timeline`
