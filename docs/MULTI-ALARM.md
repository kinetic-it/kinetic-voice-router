# Mehrwecker-System — Konzept und Implementierungsplan (R05+)

Status: **Owner-Entscheidungen bestätigt; technische Umsetzung ab P1 offen.** P0 ist eine isolierte Testbasis, keine Produktivänderung.
Ausgangsbasis: Router `0.5.0b8`, Writer `0.1.2`.
Projektinterne Nachweise und Aufgaben werden außerhalb dieses Repositories geführt.
Bezug: Owner-Entscheidung vom 17.11.2026 (zehn permanente interne Wecker-IDs).

---

## 1. Verbindliche Owner-Vorgaben (unverändert übernommen)

1. Exakt zehn permanente interne Wecker-IDs.
2. Frei wählbare, optionale Namen.
3. Automatische Vergabe freier Slots.
4. Keine automatische Überschreibung.
5. Abgelaufene einmalige Wecker geben ihren Slot wieder frei.
6. Wiederkehrende Wecker behalten ihren Slot.
7. Timer und Wecker bleiben getrennt.
8. **D-MA-1:** zehn autoritative Writer-Slots, Promotion des nächsten fälligen Weckers in den bestehenden einzelnen Klingelkanal.
9. **D-MA-2 = A:** gleichzeitig fällige Wecker nacheinander; keiner darf verloren gehen, ein nicht quittierter Wecker darf nachfolgende nicht dauerhaft blockieren. Die Absicherung ist später zu implementieren und nachzuweisen.
10. **D-MA-3 = A:** bei zehn belegten Slots `NO_FREE_SLOT`; keine automatische Überschreibung, Löschung oder Veränderung bestehender Wecker.
11. **D-MA-4 = A:** zehn gleichberechtigte, frei verwaltbare IDs ohne geschützte Systemwecker; Namen optional und unabhängig von der ID. Bei späterer Migration bleiben Slots 1 und 3 erhalten.

Unterstützte Spracheingaben:

```text
"Wecker in 10 Minuten."
"Wecker morgen um 15 Uhr."
"Wecker Sonntag um 9 Uhr."
"Wecker Sonntag Medikamente um 12 Uhr."
"Wecker jeden Montag um 7 Uhr."
"Welche Wecker habe ich gestellt?"
"Lösche den Medikamentenwecker."
```

---

## 2. Analyse des Ist-Stands (belegt)

### 2.1 Writer `nabu_alarm_writer` 0.1.2

- SQLite-Store `alarms(slot PK, version, active, ringing, alarm_time, next_due)`,
  `requests`, `alarm_events`, `mirror_state`, `notification_outbox`.
- **Slots sind fest auf 1..3 verdrahtet**: `Store.execute` (`slot not in (1, 2, 3)`),
  `ACTION_SCHEMA`, `get_slot`/`execute_dashboard` (`vol.In([1, 2, 3])`).
- Slot-Bedeutung heute hart kodiert: Slot 1 = Werktags-Wiederholung (Mo–Fr, HH:MM),
  Slot 3 = täglich (HH:MM, `next_due`), Slot 2 = einmalig, absoluter Zeitpunkt.
- Nur Slot 2 wird gespiegelt (`mirror_slot2`: `input_datetime` + `input_boolean` +
  Busy-Entity) und als `sensor.nabu_alarm_slot2_due` veröffentlicht.
- `recover_due` behandelt Neustart-/Nachholfälle je Slot, inklusive HH:MM-Altbestand.
- `execute_voice` kennt nur `set|delete|stop` und **immer Slot 2**; keine Namen,
  keine Abfrage, keine Wiederholungsarten.
- Fehler werden als `ServiceValidationError` gemeldet (`INVALID`, `CONFLICT`) — seit
  0.1.2 auch im Sprachpfad, damit der Router keinen falschen Erfolg ansagt.

### 2.2 Router `kinetic_voice_router` 0.5.0b8

- `voice_router/alarm.py`: Parser erzeugt `AlarmAction(operation, rule_id, response,
  alarm_time)`; Grenzen `MIN_DELAY_SECONDS=60`, `MAX_DELAY_SECONDS=86400`.
- Absolute Zeiten: `heute|morgen` + `um|auf`, `viertel vor/nach`, `halb`, `HH:MM` als
  `HH MM` (HA-Normalisierung) — Groß-/Kleinschreibung und Satzzeichen sind robust.
- **Nicht vorhanden**: Wochentage, Serien, Namen, Listenabfrage, Auswahl unter mehreren
  Weckern.
- Sicherheitsgrenzen (unverändert zu halten): `AUTHORIZED_TARGETS =
  frozenset({("nabu_alarm_writer", "execute_voice")})`; genau **ein** `services.async_call`
  in `conversation.py`, gesichert durch `ensure_authorized_target()` und den statischen
  Guard in `tests/router/test_static.py`; Hermes bleibt ausführungsfrei.
- Satz-Trigger-Automation `configs/packages/wi0181_wecker_sprachpfad.yaml` holt
  „Wecker"-Sätze vor den lokalen HA-Timer-Intents (`prefer_local_intents: true`) und
  reicht sie unverändert an den Router weiter.

### 2.3 Ausführungskanal in Home Assistant

- Klingelpfad: `automation.nabu_wecker_koordinator_ereignisse_r4` (Zeittrigger auf
  `input_datetime`) → `nabu_wecker_klingelstart` → `nabu_wecker_klingel_loop`
  (Zielraum `input_select.nabu_wecker_slot_2_zierraum`, Guard
  `input_boolean.nabu_wecker_koord_freigabe`, Busy `input_boolean.nabu_wecker_klingelt`).
- **Ein** physischer Kanal für Wecker (ein Echo 2 im Wohnzimmer), derzeit ein Wecker
  gleichzeitig; Kollisionen mehrerer gleichzeitig fälliger Slots sind als F3 offen.

### 2.4 Trageweite des Ist-Stands für 10 Slots

| Bedarf | Ist-Zustand | Konsequenz |
|---|---|---|
| 10 IDs | 3 harte Slots | Store, Schemas und Publish generalisieren |
| Namen | keine | Schema + Auflösung + Löschen nach Namen |
| Serien (täglich/wöchentlich) | Slot 1/3 implizit | explizites `kind` je Slot nötig |
| freie Slot-Vergabe | keine (immer Slot 2) | Zuweisungslogik + `NO_FREE_SLOT` |
| Listenabfrage | keine | neue Operation ohne neues Ziel |
| Ausführung | eine `input_datetime` | Kanalzahl ist eine Architekturentscheidung |

---

## 3. Architekturentscheidung (Vorschlag, Owner bestätigt)

**D-MA-1 Kanalmodell: ein Ausführungskanal, zehn Speicherplätze (Variante C).**

Der Writer hält zehn autoritative Slots im Store. In den bestehenden HA-Helferkanal
(`input_datetime.nabu_wecker_2_einmalig` + `_aktiv` + Busy) wird immer nur **der nächste
fällige Wecker** gespiegelt („Promotion"). Nach Klingeln, Stopp, Löschen oder Ablauf wird
der nächste fällige Slot nachgezogen. Damit bleiben Klingelautomationen, Guards, Zielraum
und Busy-Semantik unverändert; es entsteht keine zweite Weckerarchitektur.

Verworfene Alternativen:

- **A — Helfer je Slot** (10 × `input_datetime` + `input_boolean` + 10 Automationen):
  größter Konfigurations- und Wartungsaufwand, ~30 neue Entitäten, F3-Kollisionen
  bleiben, Rollback aufwändig.
- **B — Writer als alleiniger Triggergeber** (HA-Zeittrigger entfällt, Writer ruft
  Klingelstart): ändert den produktiv abgenommenen Klingelpfad und die Eigentümerschaft
  der Auslösung — unnötiges Risiko.

**Owner-Entscheidung D-MA-2 = A: sequentielles Klingeln.**
Ein Kanal bedeutet: mehrere gleichzeitig fällige Wecker klingeln nacheinander. Das löst
das Kollisionsproblem allein noch nicht nachweislich, verzögert aber den zweiten Wecker. Kein fälliger Wecker darf verloren gehen oder dauerhaft blockiert werden; hierzu sind Implementierung und Tests noch offen. Alternative wäre ein Kanal je Raum
(Zukunft), nicht Teil dieses Pakets.

---

## 4. Datenmodell und Persistenz

### 4.1 Schema v2 (Migration `PRAGMA user_version` 1 → 2)

```sql
CREATE TABLE alarms (
  slot        INTEGER PRIMARY KEY CHECK (slot BETWEEN 1 AND 10),
  version     INTEGER NOT NULL,
  active      INTEGER NOT NULL,
  ringing     INTEGER NOT NULL,
  kind        TEXT NOT NULL CHECK (kind IN ('once','daily','weekdays','weekly')),
  time_hhmm   TEXT,            -- lokale Uhrzeit für daily/weekdays/weekly
  weekdays    TEXT,            -- ISO-Wochentage "1,3,5" für weekdays/weekly
  date_local  TEXT,            -- YYYY-MM-DD für once
  next_due    TEXT NOT NULL,   -- UTC ISO, einzige Fälligkeitsquelle
  name        TEXT,            -- Anzeigename, optional
  name_key    TEXT,            -- normalisiert, optional, UNIQUE WHERE NOT NULL
  source      TEXT NOT NULL,   -- voice|dashboard|legacy|migration
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX ux_alarms_name_key ON alarms(name_key) WHERE name_key IS NOT NULL;
```

`mirror_state` erhält `promoted_slot INTEGER`, damit die Promotion idempotent prüfbar ist:

```sql
ALTER TABLE mirror_state ADD COLUMN promoted_slot INTEGER;
```

### 4.2 Migration des Bestands (verlustfrei, idempotent)

| Alt | Neu |
|---|---|
| Slot 1, HH:MM | `kind='weekdays'`, `weekdays='1,2,3,4,5'`, `time_hhmm` unverändert |
| Slot 3, HH:MM | `kind='daily'`, `time_hhmm` unverändert |
| Slot 2, ISO-Datetime | `kind='once'`, `date_local` + `time_hhmm` aus lokalem Zeitpunkt |
| Slots 4..10 | `active=0`, `next_due` = Sentinel `9999-12-31T23:59:59+00:00` |

Regeln: Migration läuft in **einer** Transaktion, schreibt vorher eine Kopie der DB
(`nabu_alarm_writer.db.pre-v2`), ist wiederholbar (nur wenn `user_version < 2`), und
behält `version` je Slot bei (keine künstlichen Versionssprünge).

### 4.3 Fälligkeitsberechnung

`next_due` wird **nur** vom Writer berechnet (Europe/Berlin, DST-sicher über
`fold`-Prüfung wie im Bestand) und in UTC gespeichert. Nach jeder Mutation und beim
Starten wird `next_due` neu bestimmt, bei `once` nach dem Klingeln auf Sentinel gesetzt
und `active=0` (Slot frei).

---

## 5. Slotverwaltung

| Regel | Umsetzung |
|---|---|
| 10 permanente IDs | `slot` 1..10, niemals umnummeriert |
| freie Vergabe | kleinste ID mit `active=0 AND ringing=0` |
| keine Überschreibung | ein belegter Slot wird nur durch ausdrückliches Löschen/Ersetzen dieses Slots geändert; kein „nimm den nächsten freien" bei vollem Bestand |
| einmalig abgelaufen | nach Klingeln/Stopp/Delete: `active=0`, `next_due` Sentinel → Slot wieder frei |
| wiederkehrend | nach Klingeln `active=1` + nächstes `next_due` (Slot bleibt) |
| alle belegt | `NO_FREE_SLOT` mit Liste der 10 Slots, keine stille Verdrängung |
| Klingeln aktiv | Setzen auf einen **anderen** Slot blockiert während `busy` (`REFUSED_BUSY`), Verschieben/Löschen bleibt erlaubt |

---

## 6. Namensauflösung

- `name` = Anzeigename („Medikamente"), `name_key` = normalisiert:
  Kleinschreibung, `ß→ss`, Umlaut-Faltung (`ä→a`), alles außer `[a-z0-9]` entfernt,
  abschließendes `wecker` entfernt („Medikamentenwecker" → `medikamenten`).
- Auflösungsreihenfolge bei Löschen/Abfrage: exakt → eindeutiger Präfix → eindeutige
  Teilzeichenkette. Mehr als ein Treffer: `AMBIGUOUS` mit Kandidatenliste, der Router
  fragt nach („Meinst du Medikamente oder Montagswecker?"), **keine** Ausführung.
- Kein Treffer: `NOT_FOUND`, ehrliche Antwort, unverändert kein Löschen.
- Namen sind optional; ohne Namen bleibt der Wecker über Slotnummer und Liste
  adressierbar. Doppelte Namen sind unzulässig (`DUPLICATE_NAME`).

---

## 7. Neustart-, Ausfall- und Nachholverhalten

1. **Start:** `recover_due` (Bestand) → `next_due` für alle aktiven Slots neu berechnen →
   `promote_next()`.
2. **Promotion:** kleinster `next_due` unter `active=1 AND ringing=0` wird in den
   Helferkanal gespiegelt (`set_datetime` + `turn_on`), `mirror_state.promoted_slot`
   gesetzt. Idempotent: gleicher Slot und gleiche Zeit → `NOOP`.
3. **HA-Restore-Drift:** stellt `input_datetime` einen alten Wert wieder her, ist der
   Helfer inaktiv → gilt als frei und wird übernommen (seit Writer 0.1.2 so umgesetzt).
   Ein **aktiver** fremder Helferwert bleibt geschützt (`REFUSED_DRIFT`).
4. **Nachholen:** Die bisher vorgeschlagene 15-Minuten-Grenze mit anschließendem
   `missed` ohne Klingeln ist nicht als Lösung für D-MA-2 freigegeben: Sie darf
   fällige Wecker nicht verlieren. Verlustfreie, nicht dauerhaft blockierende
   Behandlung und ihre Tests sind vor einer Umsetzung fachlich zu klären.
5. **Klingeln/Stopp:** danach immer Promotion des nächsten fälligen Slots; bei
   mehreren gleichzeitigen Fälligkeiten streng nach `next_due`, dann Slotnummer.
6. **Kein Doppelklingeln:** `ringing` bleibt die Sperre; ein Slot kann nicht zweimal
   gleichzeitig klingeln.

---

## 8. Fehlerbehandlung

Der Writer liefert ausschließlich strukturierte Ergebnisse
(`{status, code, slot, slots[]}`), **keine** Sprachtexte:

| Code | Bedeutung | Router-Reaktion |
|---|---|---|
| `OK` | gesetzt/gelöscht/gestoppt | Bestätigung mit Slotnummer, Name, Zeit |
| `NOOP` | identischer Zustand | Bestätigung ohne Änderung |
| `NO_FREE_SLOT` | alle 10 belegt | „Alle zehn Weckerplätze sind belegt." |
| `AMBIGUOUS` | mehrere Namenstreffer | Rückfrage mit Kandidaten |
| `NOT_FOUND` | kein Treffer | ehrliche Ablehnung |
| `DUPLICATE_NAME` | Name existiert | Ablehnung mit Hinweis |
| `INVALID` | Zeit/Regel unplausibel | Ablehnung |
| `CONFLICT` / `REFUSED_BUSY` / `REFUSED_DRIFT` | Zustandskonflikt | Ablehnung, keine Erfolgsansage |
| `LIST` | Abfrage | gesprochene Liste (max. 5, danach „und N weitere") |

Grundsätze: fail-closed, keine Erfolgsansage ohne `OK`/`NOOP`, keine Ausnahme als
Normalfall, jede Ablehnung mit Grund.

---

## 9. Router-Erweiterung ohne Aufweichung der Sicherheitsgrenzen

- **Allowlist bleibt exakt ein Ziel**: `{("nabu_alarm_writer", "execute_voice")}`.
  Liste und Löschen nach Namen laufen als zusätzliche `operation`-Werte (`list`, `delete`)
  über **denselben** Dienst. Damit bleibt „genau ein `services.async_call`" wahr.
- Neue Regeln im Parser (jeweils mit eigener `rule_id`):
  `R-ALARM-SET-MORGEN`, `R-ALARM-SET-WOCHENTAG`, `R-ALARM-SET-NAMED`,
  `R-ALARM-SET-WEEKLY`, `R-ALARM-LIST`, `R-ALARM-DELETE-NAME`.
- `MAX_DELAY_SECONDS` wird für einmalige absolute Angaben auf **8 Tage** erhöht
  (Wochentag nächste Woche), für `weekly`/`daily` entfällt die Obergrenze, weil
  `next_due` zyklisch berechnet wird. Timer bleiben unberührt (`_NOUNS = {"wecker"}`).
- „Welche Wecker habe ich gestellt?" ist eine **Frage**: eigene Regel vor dem
  ACTION-Fallback, damit sie nicht als unausführbare Aktion endet.
- Antworten bleiben im Router formuliert; der Writer liefert nur Daten.

---

## 10. Implementierungsschritte (jeweils labor- und testbar, keine Produktivänderung)

| # | Paket | Inhalt | Nachweis |
|---|---|---|---|
| P0 | Testbasis | `tests_lab`-Gerüst für 10 Slots, Fixtures für Uhr/DST | Tests grün, ohne HA |
| P1 | Schema v2 + Migration | Tabelle, `user_version`, DB-Kopie, Slot 1/2/3 → neu | Migrationstest mit echter Alt-DB |
| P2 | Slotlogik | freie Vergabe, kein Überschreiben, Ablauf/Freigabe, Serien | Store-Tests je Regel |
| P3 | Promotion | `promote_next()` idempotent, nach Ring/Stopp/Delete, Start | Promotionstests + Restart-Simulation |
| P4 | Namen | `name_key`, Auflösung, `AMBIGUOUS`/`NOT_FOUND`/`DUPLICATE_NAME` | Namens-Tests |
| P5 | Service-API | `execute_voice` mit `operation=list`, Namen, `slot` optional; Schemas 1..10 | Service-/Schema-Tests |
| P6 | Parser | Wochentag, morgen, benannt, weekly, Liste, Löschen nach Name | Parser-Tests für alle 7 Sätze |
| P7 | Router-Anbindung | Ergebnisabbildung auf Sprache, Rückfragen, `MAX_DELAY` | Router-Tests + Guard-Mutationen |
| P8 | Integrationstest | echte HA-Core-Objekte, echter Store, 10 Slots, Kanal | ≥ 30 Prüfungen, 0 Fehler |
| P9 | Doku/Rollback | Dokupaket, Rollback-Anleitung, Bundle-Inventar | Hash-Readback |

Reihenfolge ist bindend: P1 vor P2 vor P3; P5 vor P6; P7 zuletzt.

---

## 11. Abnahmekriterien

**Sprache (alle sieben Sätze, je ein Test plus Negativfall)**

- [ ] „Wecker in 10 Minuten." → einmalig, Zeit = jetzt+10 min, freier Slot.
- [ ] „Wecker morgen um 15 Uhr." → einmalig, morgen 15:00.
- [ ] „Wecker Sonntag um 9 Uhr." → einmalig, nächster Sonntag 09:00.
- [ ] „Wecker Sonntag Medikamente um 12 Uhr." → einmalig, Name „Medikamente".
- [ ] „Wecker jeden Montag um 7 Uhr." → `weekly`, Wochentag 1, 07:00.
- [ ] „Welche Wecker habe ich gestellt?" → Liste mit Name/Slot/Zeit, keine Aktion.
- [ ] „Lösche den Medikamentenwecker." → löscht genau den benannten Wecker.
- [ ] „Stelle einen Timer auf 5 Minuten." → unverändert HA-Timer, kein Wecker.
- [ ] Nicht unterstützte Formulierung → fail-closed, keine Erfolgsansage.

**Slotverwaltung**

- [ ] Zehn Wecker belegen 1..10 in Vergabereihenfolge; der elfte Versuch liefert
  `NO_FREE_SLOT` und verändert nichts.
- [ ] Ein abgelaufener einmaliger Wecker gibt seinen Slot frei (nach Klingeln und Stopp).
- [ ] Ein wiederkehrender Wecker behält seinen Slot und plant das nächste Vorkommen.
- [ ] Ein belegter Slot wird nie stillschweigend überschrieben.

**Persistenz und Neustart**

- [ ] Migration einer 3-Slot-Datenbank erhält alle Wecker, Versionen und Serien.
- [ ] Nach HA-Neustart mit drei aktiven Weckern klingelt der früheste; danach der nächste.
- [ ] Promotion ist idempotent (zweimaliger Aufruf ändert nichts).
- [ ] Restore-Drift des `input_datetime` blockiert keinen Sprachwecker.

**Sicherheit (unverändert)**

- [ ] `AUTHORIZED_TARGETS` enthält genau ein Ziel.
- [ ] Genau ein `services.async_call`, nur in `conversation.py`, nur nach
  `ensure_authorized_target()`.
- [ ] Statischer Guard und seine Mutationstests bleiben grün.
- [ ] Kein Hermes-Zugriff im Weckerpfad.

**Gesamt**

- [ ] Router-Suite und HA-Suite grün, `ruff` clean, `scripts/audit_public.py` PASS.
- [ ] Produktivpfad unverändert funktionsfähig (Slot 2, Klingelautomatik, Guards).
- [ ] Rollback beschrieben und geprobt (DB-Kopie + Bundle-Rücknahme).

---

## 12. Risiken

| Risiko | Auswirkung | Gegenmaßnahme |
|---|---|---|
| Ein Kanal, mehrere Fälligkeiten | zweiter Wecker klingelt später oder wird blockiert | D-MA-2=A: verlustfreie Sequenz, begrenzte Blockade; Nachweis durch spätere Tests |
| Promotion-Lücke (Absturz zwischen Klingeln und Promotion) | Wecker bleibt unbeobachtet | Promotion bei jedem Start + `recover_due`, idempotent |
| Store/Helfer-Divergenz nach Neustart | Drift, blockierte Sprache | inaktiver Helfer wird übernommen; aktiver Fremdwert bleibt geschützt |
| Falsche Namenstreffer | falscher Wecker gelöscht | exakt → Präfix → Teilstring, bei Mehrdeutigkeit Rückfrage, nie raten |
| Migration beschädigt Bestand | Wecker verloren | DB-Kopie vor Migration, Transaktion, Realtest mit Alt-DB, Rollback |
| `MAX_DELAY` 8 Tage trifft „Sonntag" knapp | Ablehnung statt Wecker | Test an Wochengrenzen und um Mitternacht |
| Sommerzeit-Umstellung | Wecker zur falschen Zeit | `fold`-Prüfung wie im Bestand, DST-Tests |
| Semantikänderung von `execute_voice` | bestehende Aufrufer brechen | `slot` optional, Default = freie Vergabe; alte Aufrufe ohne Namen bleiben gültig |
| Ein-Kanal-Architektur | mehrere Wecker werden nicht parallel ausgegeben | D-MA-2=A vom Owner bestätigt; technische Absicherung offen |
| Testumfang wächst unkontrolliert | lange Läufe | Pakete P0–P9 einzeln abnehmen, kein Sammellauf |

---

## 13. Entscheidungsstand und offene Nachweise

D-MA-1 und D-MA-2/3/4=A sind durch den Owner am 17.11.2026 entschieden; die
verbindlichen Inhalte stehen in Abschnitt 1. Nicht entschieden bzw. nicht nachgewiesen
ist die konkrete technische Absicherung gegen Verlust und dauerhafte Blockade bei
gleichzeitiger Fälligkeit. Die hierfür erforderlichen Implementierungs- und Testschritte
gehören zu späteren Paketen; aus P0 folgt keine Freigabe für P1 oder Produktivbetrieb.
