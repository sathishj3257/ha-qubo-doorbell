# Qubo Doorbell for Home Assistant (unofficial)

A custom Home Assistant integration for **Qubo video doorbells** (Hero Electronix), built on the
[qubopy](https://github.com/selvakk2k/qubopy) library. It gives you a real-time **doorbell ring**
sensor, **motion** events, and the **visitor snapshot** that Qubo uploads when someone rings.

> **Unofficial.** Not affiliated with or endorsed by Qubo / Hero Electronix. It uses Qubo's cloud
> (REST + MQTT) via qubopy, so it can break if Qubo changes their service.

## Tested on

| Device | Model | Status |
|---|---|---|
| Qubo Video Doorbell Pro | HCD04C | ✅ ring, snapshot, events |

Other Qubo cameras/doorbells (HCD01, HCP, HCO series) may work for events; reports welcome.

## Requirements

- A Qubo account that signs in with **email + password**. Phone-number/OTP accounts only get a
  1-hour session from Qubo's cloud, which is not usable for 24/7. Workaround: create an email-based
  Qubo account and share the doorbell to it from the Qubo app.
- Home Assistant 2025.1 or newer.

## Installation

### HACS (custom repository)
1. HACS → ⋮ → **Custom repositories** → add `https://github.com/sathishj3257/ha-qubo-doorbell`, type **Integration**.
2. Install **Qubo Doorbell**, then restart Home Assistant.

### Manual
Copy `custom_components/qubo_doorbell` into your Home Assistant `config/custom_components/` folder and restart.

## Setup
Settings → Devices & services → **Add integration** → **Qubo Doorbell** → enter your Qubo email and password.
The session appears in the Qubo app under *Account → Logged-in devices* as **Home Assistant**; logging it out
there revokes access (Home Assistant will then ask you to sign in again).

## What you get (per doorbell)

| Entity | Description |
|---|---|
| `binary_sensor.<name>_ring` | Turns **on for 15 s** when the button is pressed |
| `binary_sensor.<name>_motion` | Pulses on motion / person events (if enabled in the Qubo app) |
| `image.<name>_last_visitor` | Photo of the most recent visitor — downloaded and stored locally (`config/qubo_doorbell/`), so it survives link expiry and restarts until the next ring replaces it |
| `sensor.<name>_last_event` | The latest raw event (`service / event`) with parameters as attributes — handy for debugging |
| `sensor.<name>_snapshot_history` | Number of photos kept in the snapshot history; size, limit, folder, oldest/newest as attributes |

## Snapshot history (optional, off by default)

Settings → Devices & services → **Qubo Doorbell** → **Configure**:

| Option | Default | Meaning |
|---|---|---|
| Save snapshot history | off | Keep a copy of every visitor photo (ring and motion) |
| Folder name (inside Media) | `qubo_doorbell` | A single folder name under Home Assistant's media folder |
| Size limit (MB) | 100 | When the folder grows past this, the **oldest photos are deleted automatically** |

Photos are saved as `media/<folder>/<YYYY-MM-DD>/<HH-MM-SS> ring.jpg` (or `motion.jpg`) and can be browsed
in **Media → My media**. A photo that arrives within 90 s of a button press is labelled `ring`; any other
photo is labelled `motion`.

Every real-time event is also fired on the Home Assistant bus as **`qubo_event`**, so you can trigger
automations on anything the doorbell sends.

### Event sequence for one button press (HCD04C)

| Order | `service` | `event_name` | Notes |
|---|---|---|---|
| 1 | `call` | `incomingCall`, then `stateChanged` (`state: ringing`) | Call to the app starts |
| 2 | `doorbell` | `visitorAtDoor` | |
| 3 | `doorbell` | **`doorbellPressed`** | **The ring** — used by the Ring sensor |
| 4 | `recordingControl` | `stateChanged` (`cause: DOORBELL_PRESSED`) | Recording starts |
| 5 | `call` | `snapshotAvailable` | `parameters.snapshotUrl` = time-limited photo link |
| 6 | `call` | `missedCall`, then `stateChanged` (`state: idle`) | Nobody answered |

See [`examples/doorbell_ring_automation.yaml`](examples/doorbell_ring_automation.yaml) for a phone alert that
adds the visitor photo a few seconds later.

## Privacy & security
- Your Qubo email/password are stored in Home Assistant's config entry (like other cloud integrations) and are
  sent only to Qubo's servers by qubopy.
- The last visitor photo is saved in `config/qubo_doorbell/` (not in `www`, so it is not publicly served).
- Snapshot history (if enabled) goes into the media folder, which only signed-in Home Assistant users can open.
- Snapshot links are pre-signed, expiring URLs from Qubo's storage. Anyone holding a link can open it until it
  expires — don't post them publicly.
- The integration only subscribes to Qubo's `monitor` MQTT topics (no control channel).

## Not (yet) supported
- Live video stream (Qubo's cloud stream allows one viewer at a time).
- Answering / two-way talk.

## Credits
- [qubopy](https://github.com/selvakk2k/qubopy) by Selva Kumaran K (MIT) — does all the Qubo cloud work.

## License
MIT
