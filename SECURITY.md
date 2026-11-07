# Security

## Reporting

Report vulnerabilities privately through GitHub Security Advisories on
`Meshterm/meshterm`. Do not open a public issue for an unfixed vulnerability.

## Dependency and supply-chain policy

- Runtime and development dependencies are locked in `requirements/dev.lock`
  with SHA-256 hashes. CI installs with `--require-hashes`.
- The lock is resolved from PyPI only. CI passes an explicit
  `--index-url https://pypi.org/simple` and installs the project itself with
  `--no-index --no-deps`.
- Build isolation is disabled so build-time dependencies come from the lock,
  not an unpinned network fetch.
- `uv` resolves with a three-day dependency cooldown (`exclude-newer = "P3D"`)
  so a freshly published malicious release is not adopted immediately.
- GitHub Actions are pinned to commit SHAs. CI has read-only permissions.
- CI runs `pip-audit`, `bandit -ll`, `detect-secrets-hook`, and optionally
  `gitleaks` when `GITLEAKS_LICENSE` is configured.
- New dependencies require review: check the package owner, release history,
  source repository, and PyPI provenance before adding them.
- Do not test write paths against a live mesh. Use fake interfaces for failure
  and rollback tests. Live writes require an isolated radio and a verified
  full-device backup.

## Known ecosystem incidents

Recent PyPI compromises have targeted release workflows and install-time
startup hooks, not only package contents. Relevant public incidents include:

- LiteLLM (March 2026 and October 2026): stolen publishing credentials and
  malicious startup files.
- Ultralytics (December 2024): GitHub Actions cache injection and a leaked
  PyPI token.
- GhostAction (September 2025): workflow token exfiltration across many
  repositories.
- Shai-Hulud PyPI wave (2026): executable `.pth` startup hooks in science
  packages.
- Meshtastic firmware workflow CVEs CVE-2025-53637 and CVE-2026-44359:
  GitHub Actions `pull_request_target` and fork-checkout weaknesses. These
  affect the firmware repository, not the `meshtastic` PyPI package directly,
  but they show why dependency releases must be pinned and monitored.

No compromise of `meshtastic`, `textual`, `pgeocode`, or `reverse_geocoder`
was found in the sources reviewed for this project. Pinning and auditing are
still required because a clean history does not prevent a future compromise.
