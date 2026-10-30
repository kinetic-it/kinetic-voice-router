# Kinetic Voice Router

> **EXPERIMENTAL SOFTWARE / EXPERIMENTELLE SOFTWARE — NO WARRANTY / OHNE GEWÄHR**
>
> Not for safety-critical device control, emergency response, access control or unattended
> operation. A router decision proves neither a device state nor an executed action.
> Use at your own risk. **Only experimental beta pre-releases are available.**
>
> Nicht für sicherheitskritische Gerätesteuerung, Notfälle, Zutrittskontrolle oder
> unbeaufsichtigten Betrieb. Eine Router-Entscheidung beweist weder einen Gerätezustand
> noch eine ausgeführte Aktion. Nutzung auf eigenes Risiko. **Derzeit gibt es nur experimentelle Beta-Vorabversionen.**

Kinetic Voice Router is a **Home Assistant conversation agent** that sits in front of a
[Hermes Agent](https://github.com/Codename-11/hermes-homeassistant) **Companion**. It lets
Home Assistant handle everything it understands locally, and takes care of the rest:

- device and status requests that Home Assistant did **not** handle get a short, honest answer
  (the router never switches anything and never invents a device state);
- ordinary conversation and knowledge questions go to your Hermes Companion;
- answers from Hermes are checked in mode *Active* so that unverified claims
  ("I switched it on", "Home Assistant is down") are not spoken as fact.

## Status

| | |
|---|---|
| Version in this repository | `0.5.0b2` (under review, **not published**); `v0.5.0b1` is a published experimental beta |
| Tested against | Home Assistant 2026.9.x **contract stubs** and a local fake companion. No live Home Assistant, HACS or hardware run has been done for this version. |
| Hermes Companion API | v1 (`/health`, `/v1/capabilities`, `/v1/inference`), bearer token |
| Licence | MIT, personal **and commercial** use permitted, **without warranty** |

## Installation

**Experimental beta only.** The published pre-release `v0.5.0b1` may be installed by
adding `https://github.com/kinetic-it/kinetic-voice-router` as a custom *Integration*
repository in HACS, then explicitly selecting the beta release. The proposed
`v0.5.0b2` compatibility fix is not released yet; do not install its development branch.
There is no stable or production-supported release. HACS offers updates when a new release
is published, and installation requires confirmation. Before upgrading an existing 0.4.x
instance, back up Home Assistant and read [docs/MIGRATION.md](docs/MIGRATION.md).

### Setup (planned flow)

1. *Settings → Devices & services → Add integration → Kinetic Voice Router*.
2. Enter the **URL** of your Hermes Companion and its **bearer token**. The connection is
   tested first (`/health`, API version 1, conversation offered). Nothing is saved if it fails.
3. In *Settings → Voice assistants*, pick **Kinetic Voice Router** as the conversation agent of
   the pipeline you want, with *Prefer handling commands locally* switched on.
   The integration never changes your pipeline, exposures or permissions by itself.
4. Choose the mode under *Configure*: **Off** (default: plain pass-through to Hermes),
   **Observe** (count decisions in memory, answers unchanged) or **Active**.

*Reconfigure* (three-dots menu) changes URL and TLS check; *Configure → Hermes connection*
shows a live status. Re-authentication starts automatically when the token is rejected.

## Safety and privacy

- No Home Assistant service is ever called, no entity is exposed or changed, no pipeline is
  switched. Home Assistant's own local intents always run first.
- The bearer token lives in the Home Assistant configuration. It is never logged, never shown
  in the UI, never part of diagnostics. Neither are the URL, spoken text, or conversation IDs.
- Requests go only to the URL you configured; redirects are refused so the token cannot be
  forwarded elsewhere. Keep the companion on a trusted network (LAN/VPN) and use HTTPS where
  you can. **Do not expose the companion API to the internet.**
- Statistics are anonymous counters in memory (lost on restart). The "test request" in the
  options only simulates the router decision: no Hermes call, no device action, nothing stored.
- See [SECURITY.md](SECURITY.md) for reporting problems.

## Limits you should know

- The classification is a deterministic, German word-pattern engine without a language model.
  It will misjudge unusual sentences; a misjudgement never causes a device action.
- In *Active* mode only German is handled by the router; other languages get a short notice.
- The answer filter is conservative: a harmless Hermes sentence can occasionally be replaced
  by a neutral reply.
- A companion that is down or slow produces a clean error response in the Assist dialog.

## Updating from the private 0.4.x line

See [docs/MIGRATION.md](docs/MIGRATION.md).

## Development

```text
python -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements-test.txt
python -I -m unittest discover -s tests/router      # router core, static guards
python -m pytest tests/ha                           # integration, flows, client (local fake companion)
ruff check . && ruff format --check .
python scripts/audit_public.py                      # secrets / internal references / licence files
```

## Licence and credits

[MIT](LICENSE) — personal and commercial use permitted; software provided **AS IS, WITHOUT
WARRANTY**. Commercial permission is not a statement of production readiness, support or
safety certification. The Hermes Companion API contract follows the MIT-licensed
[hermes-homeassistant](https://github.com/Codename-11/hermes-homeassistant); see
[NOTICE](NOTICE). This project is independent of Home Assistant, Nabu Casa and the Hermes Agent
maintainers; trademarks belong to their owners.

---

## Deutsch

**Kinetic Voice Router** ist ein Home-Assistant-Gesprächsagent vor einem Hermes-Agent-Companion.
Home Assistant erledigt zuerst alles, was es lokal versteht. Was übrig bleibt:

- Geräte- und Statusanfragen bekommen eine kurze, ehrliche Antwort (der Router schaltet nie etwas
  und erfindet keinen Gerätezustand);
- Gespräche und Wissensfragen gehen an deinen Hermes-Companion;
- im Modus *Aktiv* werden Hermes-Antworten geprüft, damit unbelegte Behauptungen
  („habe eingeschaltet“, „Home Assistant ist ausgefallen“) nicht als Tatsache gesprochen werden.

**Status:** Version `0.5.0b1`, nicht veröffentlicht, experimentell, ohne Gewähr. Nur gegen
Vertrags-Stubs und einen lokalen Fake-Companion getestet, nicht gegen ein echtes Home Assistant.
**Installation:** noch nicht verfügbar (siehe oben). **Einrichtung:** Integration hinzufügen,
Hermes-URL und Token eingeben, Verbindungstest abwarten, Agent in der Assist-Pipeline wählen,
Betriebsart unter *Konfigurieren* festlegen (Standard: Aus). Migration von 0.4.x:
[docs/MIGRATION.md](docs/MIGRATION.md).
