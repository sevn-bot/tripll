# Security Policy

## Supported versions

tripll is pre-1.0 and under active development. Security fixes are applied to the
`main` branch and the most recent release. There is no long-term support for older
tags.

| Version | Supported |
|---------|-----------|
| `main` (latest) | ✅ |
| Latest `0.0.x` release | ✅ |
| Older tags | ❌ |

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately through GitHub's coordinated disclosure flow:

1. Go to the [**Security** tab](https://github.com/sevn-bot/tripll/security/advisories)
   of this repository.
2. Click **Report a vulnerability** to open a private advisory (private vulnerability
   reporting).

If you cannot use GitHub Security Advisories, contact the maintainer
[@alexhawat](https://github.com/alexhawat) directly and ask for a private channel.

Please include:

- A description of the issue and its impact.
- Steps to reproduce (proof-of-concept, affected commands, or wave-plan input).
- Affected version / commit and your environment (OS, Python version, backend CLI).

## What to expect

- **Acknowledgement:** within 5 business days.
- **Assessment & fix:** we will confirm the report, agree on severity, and work on a
  fix. We aim to ship a patch or mitigation within 90 days of confirmation, sooner for
  high-severity issues.
- **Disclosure:** we practice coordinated disclosure and will credit reporters who wish
  to be named once a fix is available.

## Scope notes

tripll **never stores model-provider credentials** (design rule **R24**) — authentication
lives in the backend CLI toolchain (`claude`, `cursor-agent`) and its own credential
store/environment (see the *Authentication* section of the [README](README.md)). Reports
about credential handling should focus on how tripll spawns and forwards environment to
those subprocesses rather than on tripll storing secrets.

The optional control-plane API (`api` extra) is gated by `TRIPLL_API_TOKEN`; running it
bound beyond `localhost` without that token is a misconfiguration, not a vulnerability.
