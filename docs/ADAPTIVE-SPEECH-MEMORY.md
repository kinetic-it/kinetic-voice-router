# Adaptive Speech Memory (ASM)

Status: **included in experimental beta v0.5.0b3**. Off by default. Tested
with Home Assistant contract stubs and a local fake Hermes Companion; **not yet tested on a
real Home Assistant with real speech recognition.** All examples are synthetic.

## What it does

Speech recognition (for example Home Assistant Cloud STT) sometimes writes a word wrongly.
The router cannot fix the audio, but it can learn **confirmed** word pairs and use them in
later harmless conversation.

| Step | What happens |
|---|---|
| 1 | You: „Erzähl mir etwas über Mulan“ – STT hears „Mulahn“. Hermes answers about „Mulahn“. |
| 2 | You: „Nein, ich meinte Mulan.“ The router finds the misheard word („Mulahn“) in your previous sentence, sends your **original request with the corrected word** to Hermes and adds one question: „Soll ich mir merken, dass mit „Mulahn“ „Mulan“ gemeint ist?“ |
| 3 | You: „Ja“ → stored, „Gemerkt: Mit „Mulahn“ meinst du „Mulan“.“ You: „Nein“ → nothing stored. Anything else, another conversation or more than 60 seconds → the question lapses, nothing stored. |
| 4 | Later: „Erzähl mir etwas über Mulahn“ reaches Hermes as „… Mulan“, without asking. |

Recognised correction forms: „(Nein,) ich meinte X“, „ich meine X“, „gemeint war/ist X“,
„ich sagte X“, „ich habe X gesagt“, „nicht Y, sondern X“, „X, nicht Y“ (X and Y: 1–3 words).

**The misheard word must be reliably known.** It must appear in your previous sentence; if
you did not name it, exactly one word (or short span) there must be clearly similar to X.
No candidate or several candidates → nothing is proposed, nothing guessed. Hermes still
receives your words and the conversation history as before.

### Short replies and „T.“

After a real Hermes question (for example „Möchtest du Kaffee oder Tee?“) a short answer
such as „Tee“ goes to Hermes with the conversation history (single-use, 60-second window,
no text stored). A single letter such as „T.“ is never resolved; Nabu asks again with the
question taken from Home Assistant's chat log: „Ich habe dich nicht richtig verstanden.
Möchtest du Kaffee oder Tee?“. Single letters are never learned.

## Categories

| Category | Automatically applied? | Typical use |
|---|---|---|
| Proper name | yes | „Mulahn“ → „Mulan“ |
| Technical term | yes | rare terms the STT does not know |
| STT misspelling | yes | default for pairs learned in a conversation |
| Ambiguous | **no** – stored for reference only | pairs whose misheard word is an everyday word („Bild“ → „Bill“) |
| Device / room / control / status / confirmation | **never stored** | „Licht“, „Wohnzimmer“, „an“, „aus“, „stopp“, „Ja, mach das“, „Status“ … |

Everyday words are automatically downgraded to *ambiguous*, also for manual entries.

## Safety rules (enforced in code and tests)

1. Home Assistant handles local intents first; the router only sees what HA did not handle.
2. ASM never calls a Home Assistant service, never switches anything, never changes device
   names, entity IDs, rooms, exposures, permissions or the Assist pipeline.
3. Pairs are applied **only** to sentences the router classifies as conversation or
   knowledge, contain no control/device/room vocabulary before **and** after the
   replacement, and only as whole words in one pass (no chains).
4. Commands and status requests are never rewritten; the existing RouterBridge filters
   (no invented device actions, no unverified Home Assistant claims) stay in place.
5. Learning only after an explicit „Ja“ in the same conversation, within 60 seconds.
   Unconfirmed proposals live only in memory and expire.
6. A conflicting pair (same misheard word, other meaning) is never overwritten silently:
   Nabu asks „Bisher verstehe ich „X“ als „Y“. Soll ich mir stattdessen „Z“ merken?“; the
   options refuse it with an explanation. Chains and loops (A→B→C, A↔B) are refused.
7. ASM works only in mode **Active** and only when the switch is on. Off and Observe are unchanged.

## Home Assistant interface

*Settings → Devices & services → Kinetic Voice Router → Configure → Speech memory*

- Overview: learning on/off, number of entries (limit 200), storage state, every pair with
  category and „confirmed in conversation on …“ / „added manually on …“.
- Switch learning on/off (option, default off).
- Add, edit (meaning and category), delete a term.
- Reset all terms – only after a confirmation page with „Cancel“.

German and English texts; native Home Assistant forms and menus only.

## Storage

- Home Assistant `Store`, key `kinetic_voice_router.speech_memory` in `.storage`, version 1,
  written **atomically** and marked **private**; survives restarts and updates.
- Content: `heard`, `intended`, `category`, `source` (dialogue/manual), `confirmed_on`
  (date only). No sentences, audio, conversation IDs, tokens or person profiles.
- Limits: 200 entries, 1–3 words and 40 characters per side, letters only, at least 3
  letters for the misheard side.
- Damaged data: syntactically broken JSON is moved aside by Home Assistant (`*.corrupt.<time>`)
  with a repair issue. Readable but invalid content, or a newer format version, is **left
  untouched**: the lexicon is locked (no learning, no edits) and the options show a warning
  until you reset it explicitly. Nothing is reset silently.
- Removing the integration deletes the stored lexicon.
- Diagnostics contain only the switch state, storage state and the number of entries.

## Not (yet) possible

- Repairing the audio or the STT result itself; vocabulary hints for a specific STT engine.
- Learning from a correction when the misheard word was not in your previous sentence.
- Separate lexicons per person. This needs reliable speaker identification first; until
  then the lexicon is shared by everyone using the voice assistant.
- English correction phrases: the router's language engine is German.
- Strengthening a pair by repetition: one explicit confirmation is the only way to store.

## Testing on a real Home Assistant later

1. Snapshot / backup first, keep the published release at hand for rollback.
2. Install the development build only after the maintainer's approval; mode **Observe** first.
3. Mode **Active**, switch learning **on**, run the Mulan example by voice and by Assist text.
4. Check *Speech memory* in the options, restart Home Assistant, repeat step 4 of the table.
5. Negative checks: „T.“ after a question, „Ja, mach das“, „Licht an“, a status question,
   a „Ja“ after 60 seconds, a second conversation.
6. Switch learning off and confirm that the same sentences behave as before.

## Verification commands

```bash
python -I -m unittest discover -s tests/router
python -m pytest tests/ha
ruff check . && ruff format --check .
python scripts/audit_public.py
```
