# Security policy

This is **experimental software without warranty**. There is no supported release yet.

## Scope

- The router classifies German sentences and talks to **one** configured Hermes Agent
  Companion. It does not call Home Assistant services, change exposures or switch pipelines.
- The companion connection is authenticated with a bearer token. Keep the companion on a
  trusted network (LAN/VPN); never expose its API to the internet.

## What to report

Please report, privately, anything that could cause: a device action, a leak of the token,
the URL, spoken text or conversation IDs, a request sent to another host than the configured
one, an unsafe claim spoken as fact, or a bypass of the router modes.

## How to report

Use GitHub's **private vulnerability reporting** for this repository (*Security → Report a
vulnerability*), once enabled by the maintainers. If it is not available, open a public issue
that says only *"security report, please contact me"* — **without** any technical detail,
secret, hostname, address, transcript or screenshot. No e-mail address is published.

## Public issues

Never paste bearer tokens, hostnames, IP addresses, raw transcripts, recordings, private
Home Assistant configuration or device identifiers into public issues. Use a synthetic,
reproducible example with versions, the sanitised error class, and expected vs. observed
behaviour.

## No warranties

Distributed as-is under the MIT licence. Do not use it for emergency, safety-critical or
unattended device automation. A model-generated statement never verifies an action or a device state.
