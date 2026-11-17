# Mehrwecker-P0: archivierte Testbasis

Diese beiden Textdateien sind **bytegleiche Sicherungen** der im isolierten Labor geprüften Python-Fixtures und ihrer Selbsttests. Die Endung `.txt` kennzeichnet ein Beweisarchiv; sie sind keine durch die reguläre CI automatisch ausgeführten Tests.

| Archivdatei | SHA-256 |
|---|---|
| `conftest.py.txt` | `9a709cbcb4bcedd5cc368b7207e21c452cafd20172920425b52d04ee5a043187` |
| `test_p0_harness.py.txt` | `97765447bea1aeb113982ee092d53b906b448e399bb2c6a6980974625cff43e5` |

Am 17.11.2026 wurden im isolierten Labor 90 bestehende und neue Tests erfolgreich ausgeführt, darunter zehn Selbsttests dieser Testbasis. Bei deaktivierter Plugin-Autoladung gab es zwei Konfigurationswarnungen. Dies ist kein Nachweis einer implementierten Zehn-Wecker-Verwaltung, einer verlustfreien Fälligkeitsbehandlung oder einer Geräteabnahme.

**Reproduzierbarkeit:** Die Vorlagen setzen eine separate Laborverzeichnisstruktur und einen nicht in diesem Repository versionierten Writer-Core voraus. Der damals verwendete Core hatte SHA-256 `c5349331c862e4749761dfd625c8ca13e5671a9d377ac8dd67904dd434dba742`. Dieses Archiv enthält weder den Core noch dessen übrige Labortests und ist daher **nicht eigenständig ausführbar**. Es belegt nicht dessen Herkunft oder Gleichheit mit einem produktiven Stand. Für spätere reproduzierbare Tests müssen Writer-Herkunft und Testumgebung separat geklärt werden; keine Produktivinstallation daraus ableiten.
