# Operating guide

This guide is intentionally provider-neutral. Read the individual `SKILL.md`
files for the full contracts and validation rules.

Install both skills for the complete workflow, with `brand-copy-studio` first.
The social skill can prepare drafts on its own, but final privileged validation
is deliberately blocked when the sibling brand validator is unavailable.

## 1. Build a copy system

Use `brand-copy-studio` with `capture` or `refresh` only when the user supplies
authorization and source evidence. `observe` may create a non-active,
unverified draft from one user-designated public source. Every fact keeps an
evidence status (`exact`, `observed`, `inferred`, or `unverified`), a locator,
capture time, and rights state.

Validate the four-file bundle together. A draft is not an active brand rule;
activation requires a trusted external policy and the current authenticated
actor.

## 2. Create social content

Use `social-content-studio` with a validated scope and approved copy bundle.
Keep tenant, client, product, brand, account, and content identifiers isolated.
The normal path is brief → copy review → design draft → brand/accessibility QA →
human approval → export or manual handoff.

The default policy is attended approval. If a bounded unattended policy is
explicitly enabled, validate its scope, role, preapproved template/version, and
field slots separately. Never infer authority from mutable content JSON.

## 3. Connect Canva only when needed

Use the Hermes connector's OAuth browser flow. Ask for the minimum capability,
complete consent in the provider UI, and verify the connection with a read-only
check. Keep OAuth values in the connector's secure store. If the connector is
not available, return the provider-neutral content spec and a field-by-field
manual handoff.

## 4. Export safely

Request export only after the required native and human/policy gates. Download
the result immediately with the bundled helper, check the media type and size,
and bind its SHA-256 to the approved package. Keep signed addresses out of
receipts and logs. A local path is runtime data, never a repository artifact.

## 5. Keep the package clean

The repository may contain only the two allowlisted skill trees and generic
documentation, license, CI, and release-checking files. Do not add runtime
state, caches, generated content, client/brand examples, policy instances,
runtime JSON, credentials, provider receipts, or research exports.
