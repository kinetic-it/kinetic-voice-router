# Kinetic Voice Router

> **EXPERIMENTAL SOFTWARE / EXPERIMENTELLE SOFTWARE — NO WARRANTY / OHNE GEWÄHR**
>
> **There is no released version and nothing to install yet. / Es gibt noch keine
> veröffentlichte Version und nichts zu installieren.**

This repository is the home of **Kinetic Voice Router**: an experimental Home Assistant
conversation agent that sits in front of a Hermes Agent Companion. Home Assistant handles
what it understands locally first; device and status requests it did not handle get a short,
honest answer (the router never switches anything), and conversation goes to your Hermes
Companion.

Dieses Repository ist die Heimat des **Kinetic Voice Router**: ein experimenteller
Home-Assistant-Gesprächsagent vor einem Hermes-Agent-Companion.

## Status

- `main` intentionally contains **only the licence, notices and security policy** — no
  integration code, no `hacs.json`, no `custom_components/`. It cannot be installed through HACS.
- The first implementation (pre-release `0.5.0b1`) is under review in an open **draft pull
  request**. It will only reach `main` and a release after a maintainer has tested it on a real
  Home Assistant system and explicitly approved publication.
- Please **do not** add this repository or any branch to HACS yet.

## Licence

[MIT](LICENSE) — personal and commercial use permitted; provided **AS IS, WITHOUT WARRANTY**.
Commercial permission is not a statement of production readiness, support or safety
certification. Third-party notices: [NOTICE](NOTICE). Security reports: [SECURITY.md](SECURITY.md).

This project is independent of Home Assistant, Nabu Casa and the Hermes Agent maintainers;
trademarks belong to their owners.
