# Adaptive Speech Memory (ASM) — WI-0181 / Issue #4

Status: **experimental core only**, no HA option, storage, automatic learning or
live routing yet. Release **v0.5.0b2** is unaffected. This design is public and
contains only synthetic utterances.

## Why this is separate from PR #3

The HA pipeline produces text first. The Kinetic Voice Router cannot correct the
original audio or recover a one-letter transcription such as `T.`. PR #3 addresses
short *conversational follow-ups* and is still under review. ASM addresses
**confirmed word-level corrections** and must not bypass PR #3's session gate
or the router's safety filters.

## Implemented in this draft

- Pure `voice_router/speech_memory.py` core, **not imported by the production
  conversation entity**, no runtime behavior changes.
- `SpeechMemory.propose(cid, heard, intended)` creates only a time-limited
  candidate per conversation, with a 60-second TTL; no learning on its own.
- `confirm(cid, answer)` needs an explicit affirmative answer in the **same**
  session; a rejected, repeated, other-session or late answer does not teach.
- `apply(text, enabled=True)` substitutes complete 3–40-letter words only,
  only for already-classified `CHAT` / `KNOWLEDGE`, and excludes obvious
  command/status vocabulary. Default `enabled=False`; no callsite yet.
- `export_confirmed`/`import_confirmed` versioned data contract; only the
  approved word pairs, never audio, transcript, conversation ID or candidates.
  **Not yet connected to HA Store**: exporting in memory is not persistence.
- Bounded 128 confirmed rules and 64 pending sessions, explicit deletion/clear.
- Independent regression tests with synthetic data. All safety filtering here
  is a *second layer*, never a substitute for Home Assistant local intents or
  the original router.

## Non-goals of this first patch

- No online adjustment of STT, no audio feedback or re-transcription.
- No automatic inference of an incorrect word from a transcript. A phrase like
  “Nein, ich meinte Mulan” does not identify the incorrectly recognized word
  without a trustworthy prior user message; do not guess.
- No learned home device names, security-sensitive words or automatic device
  commands. No HA service call, exposure change or direct Hermes invocation.
- No voice-biometric recognition, shared cross-household assumptions or
  unlimited conversation listening.

## Planned integration gates (separate changes before any beta)

1. Independent Werkstatt test at exact SHA against the **real**
   `voice_router.classify`, existing router tests and CI; review ambiguous
   classification and blocklists against representative device names.
2. HA **opt-in** setting and read/delete/reset UI; default disabled, all
   existing saved options preserved. Local HA `Store` persistence with size
   limits, corruption/migration tests, and exclusion from diagnostics/logs.
3. Explicit interactive correction dialogue: safely identify a correction
   request and a single candidate from bounded HA ChatLog context, ask one
   short confirmation, persist **only after consent**, then continue the
   harmless original request without asking the user to repeat it.
4. Integrate **after HA local-intent handling**, **before safe Hermes
   conversation routing**; never use ASM to rewrite device operations,
   statuses, confirmations of actions or UI command paths.
5. Integrate with PR #3 only after both individual branches are validated;
   test separate conversation IDs, timeout, STT `T.`, local intent priority,
   unknown device names, "ja mach das", free conversational questions,
   options lifecycle, stop/restart and full output-safety regression.
6. Explicit Owner gate for merge/release/HAOS snapshot-backed Echo live pilot.
   Never silently deploy a beta into VM200.

## Verification

```bash
python -I -m unittest discover -s tests/router -p 'test_speech_memory.py'
python -I -m unittest discover -s tests/router
python -m pytest tests/ha
ruff check . && ruff format --check .
python scripts/audit_public.py
```

**Current local preliminary result:** 11 synthetic tests PASS against a small
classifier stand-in. Full real-repo tests, CI, native HA tests and VM205
Werkstatt verification still required. Do not interpret the preliminary result
as a working or installable ASM feature.

Owner preference: *understand → inspect → isolate → change → validate*; avoid
interleaving unrelated live HA / Echo troubleshooting.
