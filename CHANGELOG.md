# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions with `b`/`rc` are
pre-releases and **not** a recommendation for production use.

## [0.5.0b2] - unreleased

Experimental beta maintenance fix, awaiting workshop and real Home Assistant acceptance.

### Fixed
- Normalize the Hermes Companion's wildcard language list `["*"]` into Home Assistant's
  required literal `"*"` for conversation agents. Without this normalization, the agent
  appears disabled in the voice pipeline language selector despite being connected.
- Add regressions for wildcard, mixed wildcard, explicit language lists and empty lists.

## [0.5.0b1] - 2026-10-30

First standalone version, published as an experimental pre-release with no warranty.

### Added
- Own Home Assistant conversation agent (`conversation.kinetic_voice_router`); no patch or
  coupling to the `hermes_agent` integration is needed any more.
- Setup, re-authentication and reconfiguration of the Hermes Agent Companion in the UI:
  URL, bearer token, optional TLS-check switch, real connection test (`/health`,
  `/v1/capabilities` API major 1, conversation offered) before anything is saved.
- "Hermes connection" page in the options with a live probe and honest status
  (reachable / token rejected / incompatible API / no conversation / unreachable).
- Minimal Hermes client with redirect refusal, URL safety checks, size and time limits,
  and redacted errors.
- Operating modes Off / Observe / Active (default Off) with the router policy of 0.4.x.
- Public package structure for HACS (`hacs.json`, one integration), `NOTICE`, `SECURITY.md`,
  CI (tests on Python 3.11 and 3.13, lint, `hassfest`, HACS validation, public-tree audit).

### Changed
- The router no longer publishes itself in `hass.data`; the old "bridge API 2" is gone.
- Entry version is now 1.3. Entries from 0.4.x keep their chosen mode; because they hold no
  Hermes connection, Home Assistant asks for URL and token (re-authentication) after the update.
- Diagnostics no longer contain anything about the Hermes URL or token, only whether they exist.

### Carried over from the 0.4.x line (router behaviour)
- Statements about unknown own devices ("Is my ... switched on?") get the honest status answer.
- Explanations are no longer blocked by the answer filter when Hermes honestly states a
  channel limit; the remainder of such a sentence is still checked strictly.
- Fail-closed behaviour on internal router errors in Active mode; reset of counters only
  after explicit confirmation; abbreviations and list numbers no longer end a spoken sentence.

### Not included / open before a first release
- No brand icon: origin and licence of the icon used in the private line must be confirmed.
- No real Home Assistant, HACS or hardware test has been run for this version.
- Release workflow exists but no tag or release has been created.
