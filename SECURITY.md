# Security and privacy

This repository is a generic distribution package. Do not commit credentials,
OAuth values, cookies, account handles, provider IDs, client or brand material,
policy instances, generated content, export receipts, signed export addresses,
runtime JSON, feedback, fingerprints, approvals, measurements, caches, or local
filesystem paths.

Use the provider's OAuth browser flow and secure credential store. Never paste a
token or secret into a prompt, issue, fixture, log, test output, or pull
request. Keep runtime data in the configured Hermes data root and apply the
owner's retention and access policy. Anti-slop feedback, provenance, route and
layout fingerprints, rejection reasons, approval evidence, and performance
observations are runtime data and must remain scoped to the active
tenant/client/product/brand/account.

Canva folder, design, and template IDs are opaque runtime identifiers. Resolve
or create only the explicitly authorized scope, never reorganize unrelated
assets, and keep the resulting registry outside this repository.

Before publishing a change:

1. Run all three skill test suites.
2. Run `python3 scripts/check_public_release.py`.
3. Inspect the staged file list and verify that it contains only the documented
   allowlist.
4. Remove temporary test output and Python caches.

The release checker accepts private leak markers only from its test-only
arguments or `HERMES_RELEASE_MARKERS`; marker values are never printed. If a
possible disclosure is found, stop distribution, preserve the affected commit
privately, rotate any exposed credential, and report the file and remediation
steps to the repository maintainers through the approved private channel.

Security reports should not include the suspected secret or client data. Share
only a redacted description, affected path, impact, and a safe reproduction.
