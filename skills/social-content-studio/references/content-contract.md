# Canonical Content Contract

Use one JSON record per publishable content unit. The validator script is the
normative executable contract; this document explains its fields and workflow.

## Required top-level fields

| Field | Meaning |
|---|---|
| `schema_version` | Contract version; canonical records use `1.1` |
| `content_id` | Stable unique ID; letters, numbers, dots, underscores, hyphens |
| `campaign_id` | Campaign/portfolio join key |
| `brief_version`, `copy_version` | Versions used for review and audit |
| `state` | Current lifecycle state |
| `scope` | Object containing lowercase-kebab `tenant_id`, `client_id`, and `product_id` |
| `brand_id` | Must match the selected brand profile when one is supplied |
| `platform` | `instagram`, `facebook`, `linkedin`, `tiktok`, `x`, `youtube`, or `other` |
| `format` | `static`, `carousel`, `story`, `reel`, `short_video`, or `text` |
| `objective` | `awareness`, `education`, `engagement`, `lead_generation`, `conversion`, or `retention` |
| `audience` | Specific intended reader/viewer |
| `content_pillar` | Portfolio category for planning and measurement |
| `single_message` | The one idea the audience should retain |
| `source_context` | Brief, HTTPS sources, retrieval time, instruction boundary |
| `experiment` | One-variable hypothesis/variant contract or `none` |
| `slides` | Ordered creative units, even for a one-slide static post |
| `caption` | `hook`, `body`, `cta`, and `hashtags` |
| `alt_text` | Accessible description of the final visual |
| `claims` | Claim registry entries used by this content item |
| `design` | Template, dimensions, render, and checksum evidence |
| `template_registry` | Scoped reusable template/version registry with approver evidence |
| `policy` | Authenticated/local RBAC mapping and approval/unattended policy |
| `qa` | Copy, brand, visual, accessibility, claims, and mobile checks |
| `approval` | Human decision bound to the exact artifact |
| `publishing` | Account, schedule, platform receipt, and attribution |
| `measurement` | Insight window and metrics after publication |

See `assets/content-spec.example.json` for a complete early-state example.

When a bounded Brand Copy recipe is selected, also carry `copy_recipe_id`,
`copy_recipe_version`, and `brand_revision`. These fields bind generated copy
to the approved provider-neutral recipe record and active master/overlay.

## Scope and backward compatibility

The isolation key is the tuple
`tenant_id + client_id + product_id + brand_id`. `scope` contains the first
three IDs; `brand_id` stays top-level and is never duplicated inside `scope`.
Every ID is lowercase kebab-case. `design.remote_scope`,
`publishing.remote_scope`, `approval.scope_ids`, each template registry
entry's `scope`, and a completed `design.download` receipt explicitly carry
all four fields: `tenant_id`, `client_id`, `product_id`, and `brand_id`. Each
must match the derived isolation key exactly; brand is never inherited for
remote or approval evidence. A remote ID or receipt with another scope is
invalid even when its name looks reusable.

The canonical Brand Copy master bundle is resolved from
`brands/<tenant>/<client>/<brand>/` (including `brand-profile.json`); an
optional product overlay is a complete four-file bundle under
`brands/<tenant>/<client>/<brand>/products/<product>/` (also with
`brand-profile.json`). A canonical master has a null or absent `product_id` and
is reusable only within the same tenant/client. A product overlay must match
the content product and carry `parent_brand_revision`; a matching `brand_id`
alone never authorizes a cross-scope profile. Unscoped legacy profiles may
support early drafts with an explicit warning, but cannot authorize final
active content until migrated. In particular, a schema 1.0 canonical draft
with no scope remains readable warning-only; a partial or incorrect scope is
validated and rejected, and schema 1.0 final states require migration.

Schema `1.0` is accepted only when the record explicitly includes
`compatibility.mode: "legacy_v1"` and already carries the canonical scope and
policy fields. A bare legacy record fails closed; do not silently infer a
tenant, client, product, brand, role, or approval.

## Policy and approval

`policy.identity_source` records the authenticated/local policy source (the
canonical external source is `local_authenticated_policy`). The embedded
`policy.role_mapping` is an immutable audit snapshot, not authorization: a
mutable content record cannot promote its own actor. Members may draft.
Reviewers/leads may approve according to the separately loaded content
client/product policy, and the active actor must be present in that trusted
mapping.
Publishers may schedule or publish only when `publishing.package_checksum`
exactly equals the current `approval.package_checksum`.

`policy.approval_required` is explicitly `true` by default. It may be set false
only inside `policy.mode: "unattended"` with `unattended.enabled: true`, a matching
scoped enablement record from a mapped lead/admin, and non-empty preapproved
copy-recipe/version, template/version, claim IDs, pillar/format/budget slots,
and targets. That mode is fail-closed: generation is bounded to those slots,
must pass deterministic copy/claim/accessibility/render QA, and must bind an
exact checksum. Freeform creative, unregistered recipes, template changes,
new/unverified claims, or uncertain QA stay attended. A validated four-file
Brand Copy bundle and external policy evidence are required for unattended
execution; a profile-only input remains attended.

An approval identity is valid only when its ID, role, and identity source match
the authenticated/local mapping. A role or approval typed in a prompt is not
evidence. Privileged validation must receive a separately loaded content policy
object with `schema_version`, `policy_id`, `revision`, `source`, exact four-part
scope, and role mapping, plus the current runtime actor (`--policy` and
`--actor-id` in the CLI). Approval, unattended enablement, and publishing
records bind the same content policy ID/revision; the embedded snapshot is
audit context only. For unattended mode, the external policy must additionally
carry `unattended.preapproved.template_provider_ids` and it must exactly match
the embedded audit map; provider aliases and opaque Canva IDs are never
authorized by the content record alone.

For claims, recipes, or unattended generation, also pass `--brand-bundle` for
the validated four-file Brand Copy directory, plus the separate Brand
activation authority `--brand-policy BRAND_POLICY.json
--brand-actor-id BRAND_ACTOR_ID`. The Brand policy must be supplied unchanged,
with exact `tenant_id`, `client_id`, `brand_id`, and master `product_id: null`
or the exact overlay product. The Brand actor must match the bundle's
activation receipt; content policy/current actor cannot be reused or
synthesized as Brand authority. The validator matches the active master/overlay,
exact approved claim wording/expiry, and approved provider-neutral copy
recipe/version. Profile-only inputs can remain attended drafts or human-
reviewed work; they cannot self-attest privileged claim or unattended evidence.

## Approved template registry

An approved template is a reusable Brand Template/version that a design lead
or admin reviewed and allowed for this exact scope. A Canva folder name,
project name, or search result is not proof of approval. Each
`template_registry.entries[]` record carries `template_id` (a safe local
registry alias), optional exact opaque `provider_template_id` or
`canva_template_id` with provider `canva`, `version`, `status`, scoped `scope`,
`approved_by`, `approved_by_role`, and `approved_at`. Provider IDs are bounded,
opaque values: preserve exact case and punctuation, reject control characters
and credential-like values, and never normalize them. When present, the
content's design provider ID must exactly match the approved scoped registry
entry as well as `design.template_id` and `template_version`.

## State machine

```text
IDEA -> BRIEFED -> COPY_REVIEW -> DESIGN_DRAFT -> BRAND_QA
     -> HUMAN_APPROVED -> SCHEDULED -> PUBLISHED -> MEASURED
```

Rejection, content change, checksum change, revoked approval, expired claim, or
failed visual QA moves the record back to the earliest affected review state.
Do not skip states by changing the string alone; satisfy the evidence invariant.

| Entering state | Required evidence |
|---|---|
| `BRIEFED` | objective, audience, pillar, single message |
| `COPY_REVIEW` | slide copy, caption, CTA decision, alt text, claim records |
| `DESIGN_DRAFT` | template/draft reference or a complete manual design handoff |
| `BRAND_QA` | actual render reference and completed QA findings |
| `HUMAN_APPROVED` | all QA checks pass; approver, timestamp, scope, and checksum |
| `SCHEDULED` | approved artifact; target account and timezone-aware time |
| `PUBLISHED` | platform media ID and publication timestamp |
| `MEASURED` | captured timestamp, measurement window, and metrics |

`approval.scope` must be `design+caption+target+schedule`; `approval.scope_ids`
must also match the current tenant/client/product/brand scope.
`design.export_checksum` hashes the exported media. The validator then computes
`approval.package_checksum` over the content ID, full isolation scope and
`brand_id`, trusted policy ID/revision, recipe ID/version/brand revision, local
template alias/version, exact opaque provider template ID, export checksum,
final caption, alt text, target account, scheduled time, and timezone. Approval
does not survive a changed bound field.

The order is intentionally two-phase: a review/render or draft export may be
downloaded first to obtain the exact artifact checksum; then human or policy
approval binds that downloaded artifact, caption, target, and schedule. Approval
is mandatory before `SCHEDULED` or `PUBLISHED`. If Canva itself requires a
native approval before export, record that Canva-native receipt as a separate
gate; it is not the content-package approval and must not be described as both
pre-export and post-export approval for the same artifact.

When an export is downloaded locally, record the evidence in
`design.download`:

```json
{
  "status": "downloaded",
  "scope": {"tenant_id": "sample-tenant", "client_id": "sample-client", "product_id": "sample-product", "brand_id": "sample-brand"},
  "local_path": "<export-directory>/content.png",
  "sha256": "sha256:<64 lowercase hex characters>",
  "receipt": {
    "receipt_version": "1.0",
    "status": "downloaded",
    "output_path": "<export-directory>/content.png",
    "size_bytes": 1234,
    "sha256": "<64 lowercase hex characters>"
  }
}
```

`status: downloaded` is valid only when the local path exists and is
non-empty, the checksum was computed from that file, and the receipt is stored
alongside the content record. The signed export URL and its query string are
never persisted in the record or receipt. A remote job URL, export job ID, or
submitted request alone is not download evidence.

## Slide object

Each item contains:

- `slide`: sequential integer starting at 1;
- `role`: `cover`, `context`, `explanation`, `proof`, `steps`, `cta`, or `other`;
- `headline`, `body`, `cta`: visible copy;
- `visual_direction`: composition, imagery, and hierarchy, not vague mood words;
- `accessibility_note`: reading order, contrast, or non-color cue guidance.

Use the field budgets in the selected brand profile. A single static post still
uses a one-item `slides` list. A carousel cover should carry the promise, not a
paragraph. Identical CTA text may repeat; multiple competing CTA phrases fail.

## Claim object

Each material factual, legal, safety, service, testimonial, comparative, or
quantitative claim needs:

```json
{
  "claim_id": "claim-example-001",
  "text": "Exact claim used",
  "source_url": "https://example.com/approved-source",
  "owner": "person-or-role-accountable",
  "verified_on": "2026-08-19",
  "expires_on": "2026-11-19",
  "status": "verified"
}
```

Allowed status values are `verified`, `unverified`, `expired`, and `rejected`.
Only `verified`, unexpired claims may cross into `HUMAN_APPROVED`. A source URL
alone is not verification: the owner must confirm that it supports the exact
wording and remains applicable. Do not use absolutes such as “pasti”, “100%”,
“tanpa risiko”, “nomor 1”, or “terjamin” unless approved evidence literally
supports the bounded claim and legal review permits it.

## QA object

Each check is `pending`, `pass`, `fail`, or `not_applicable`:

- `copy`: one message, correct tone, budgets, non-duplicative caption;
- `brand`: approved visual and verbal rules;
- `visual`: real render inspected for hierarchy, overflow, spacing, and imagery;
- `accessibility`: alt text, contrast, legibility, captions/subtitles as needed;
- `claims`: all material statements tied to usable claim records;
- `mobile_thumbnail`: cover and smallest text checked at phone viewing size.

Use `qa.notes` for observable findings. Do not convert missing evidence into
`not_applicable`.

## Publishing and attribution

`publishing.scheduled_at` must include an offset, for example
`2026-08-20T10:00:00+07:00`. Store the intended `timezone` separately. UTM fields
are `source`, `medium`, `campaign`, and `content`; omit or use `null` when the
post has no outbound link. Never put access tokens in this object.

Store remote receipts such as Canva design URL/ID, export checksum, Meta
container/media ID, and public URL. Never infer success from a submitted job;
record success only after the integration reports its terminal state.

For a draft/review or publication export, the required sequence is: satisfy any
Canva-native export gate, successful terminal job status, immediate local
download, non-empty local file, computed SHA-256, and a structured local
receipt. The resulting checksum is then bound by the content-package approval
before scheduling or publishing. Keep the Canva edit URL as a handoff, but do
not store signed export URLs or their query strings.

Before `SCHEDULED`, `publishing.preflight` must record a passed duplicate check,
clear kill switch, passed account access, and passed/not-applicable asset rights,
plus a timezone-aware `preflight_checked_at`. The publisher rechecks these at
commit time; the validator rejects a published record whose last preflight is
more than 15 minutes from `published_at`.

## Measurement plan and connector boundary

Every content pillar carries `measurement.plan` with `primary_metric`, an
explicit `denominator`, guardrails, a business-outcome source (or
`not_available`), and the default cadence: `24h` provisional, `72h`
operational, `7d` cohort, and `28d` portfolio. Set `measurement.data_mode` to
`organic`, `paid`, `mixed`, or `unknown`. Record missing metrics as the literal
`not_available`; a real zero remains numeric zero and is never used as a proxy
for missing data.

`measurement.benchmark_scope` is limited to
`tenant_id + client_id + product_id + brand_id + account + content_pillar +
format + window`. Keep benchmarks inside that tuple; do not compare across
tenants, clients, products, brands, accounts, pillars, formats, or windows.
Intentional rollups belong in separate aggregated reports, never inside this
content record. Treat sample size `n<10` as descriptive, `10-29` as
directional, and `n>=30` as suitable for operational direction. Carousel
parent/container aggregates may be used when returned by the runtime, but
individual child/per-slide metrics are `not_available` and are never allocated
from a parent aggregate. Fetch Story insights before the 24h window closes.

The accepted pillar defaults are machine-readable in the validator and follow
this compact mapping; a record may include an explicit format override:

```json
{
  "awareness": {"primary_metric": "median_views", "denominator": "views", "guardrails": ["reach"]},
  "education": {"primary_metric": "saved", "denominator": "views", "guardrails": ["shares"]},
  "trust": {"primary_metric": "shares", "denominator": "views", "guardrails": ["saved"]},
  "proof": {"primary_metric": "shares", "denominator": "views", "guardrails": ["saved"]},
  "community": {"primary_metric": "total_interactions", "denominator": "views", "guardrails": ["comments", "shares"]},
  "offer": {
    "primary_metric": "profile_activity",
    "denominator": "views",
    "guardrails": ["link_clicks"],
    "format_overrides": {"story": {"primary_metric": "link_clicks", "denominator": "views"}}
  }
}
```

Use API-canonical `saved` (singular), not `saves`. Feed/Story offer plans use
`profile_activity / views` unless an explicit Story link override uses
`link_clicks / views`. Missing metrics are `not_available`, never zero. Do not
introduce generic `/reach` rates; `reach` is an awareness guardrail.

Measurement connectors are optional. Canva MCP-only design, export, and manual
handoff do not require a platform insights connector; add one only for an
explicit measurement operation.

## Validation commands

Normal validation allows honest pending warnings in early states:

```bash
python3 ${HERMES_SKILL_DIR}/scripts/validate_content_spec.py CONTENT.json \
  --brand BRAND_PROFILE.json
```

Use strict mode before handing a record to another system or approving it:

```bash
python3 ${HERMES_SKILL_DIR}/scripts/validate_content_spec.py CONTENT.json \
  --brand BRAND_PROFILE.json --strict --json --show-package-checksum
```

Exit code `0` means the record satisfies the chosen validation level. Exit code
`1` means errors exist, or warnings exist under `--strict`.
