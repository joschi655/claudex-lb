# Security Policy

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues,
discussions, or pull requests.**

Instead, report them privately using GitHub's
[Private Vulnerability Reporting](https://github.com/joschi655/claudex-lb/security/advisories/new):

1. Open <https://github.com/joschi655/claudex-lb/security/advisories/new>
2. Fill in a clear title and a detailed description of the issue.
3. Include reproduction steps, affected versions, and any proof-of-concept you
   have.
4. Submit. The report is visible only to repository maintainers.

If for some reason you cannot use the private advisory flow, you may instead
contact the fork owner through the private contact details on their
[GitHub profile](https://github.com/joschi655), with a subject line starting
with `[claudex-lb security]`.

## What to include

A good report makes triage much faster:

- **Affected revision**: the exact claudex-lb commit SHA.
- **Deployment**: source checkout, locally built Docker image, or local Helm chart.
- **Impact**: what can an attacker do? (data disclosure, account takeover,
  RCE, DoS, auth bypass, log injection, etc.)
- **Reproduction**: minimal steps — config snippet, request payload, log
  excerpt. Redact your own secrets before sending.
- **Suggested fix** (optional): if you already have a patch in mind.

## Scope

In scope:

- The claudex-lb proxy (`app/`) — auth, routing, account management, the
  dashboard backend, the `/v1/*` and `/backend-api/*` surfaces.
- The dashboard frontend (`frontend/`).
- The source-build Dockerfile and Helm chart in this repository.
- The SwiftBar and credential-transfer scripts in this repository.

Out of scope (please don't file these as security advisories):

- Issues in upstream services (ChatGPT, OpenAI Codex, model providers).
- Vulnerabilities in third-party dependencies that don't reach codex-lb's
  attack surface — file those upstream.
- Self-inflicted misconfiguration (exposing the dashboard publicly without
  auth, leaking your own API keys via committed `.env`, etc.).
- Findings that do not reproduce on the current default-branch source.

## Disclosure process

1. **Acknowledge** — maintainer confirms receipt within **3 business days**.
2. **Triage & validate** — within **7 business days** the maintainer either
   confirms the issue, asks for more information, or declines with reasoning.
3. **Fix & coordinate** — for confirmed issues, the maintainer drafts a fix
   privately. We aim to ship a patched release within **30 days** of
   confirmation; severe issues are prioritized.
4. **Release & advisory** — once the patched release is published, the
   maintainer publishes a GitHub Security Advisory (with a CVE if applicable)
   crediting you, unless you request anonymity.
5. **Embargo** — please do not publicly disclose the issue until the advisory
   is published. We will not sit on a confirmed vulnerability indefinitely; if
   30 days pass without a fix, we'll agree on a coordinated disclosure date
   with you.

## Supported versions

The fork has not published a release, image, PyPI package, or Helm artifact yet.
Security fixes apply to the current default-branch source on a best-effort basis.
The similarly named upstream artifacts are maintained by Soju06 and do not
contain claudex-lb's native Claude support.

## Hall of fame

We're happy to credit reporters in the published advisory and (with permission)
in this section. Researchers who responsibly disclose a confirmed vulnerability
will be acknowledged here.

_(none yet — be the first.)_
