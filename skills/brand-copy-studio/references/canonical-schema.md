# Canonical schema

The four files below form one local revision. They intentionally use a small,
provider-neutral JSON contract so other skills can consume the snapshot without
depending on Canva, a particular model, or a remote database.

## Shared envelope

Every file is a JSON object containing the same envelope. New production bundles
use schema `1.1` and keep `brand_id` top-level so existing consumers can still
read it. The `scope` object is the isolation namespace; it deliberately does not
duplicate `brand_id`:

```json
{
  "schema_version": "1.1",
  "brand_id": "example-brand",
  "scope": {
    "tenant_id": "tenant-example",
    "client_id": "client-example",
    "product_id": null,
    "parent_brand_revision": null
  },
  "revision": "2026-01-01T000000Z-r1",
  "status": "draft"
}
```

`brand_id`, `scope.tenant_id`, `scope.client_id`, and non-empty
`scope.product_id` are stable lowercase-kebab identifiers chosen by the user
(for example, `example-brand`; no slash, backslash, dot traversal, whitespace,
or uppercase). The isolation key is
`tenant_id/client_id/brand_id[/product_id]`; never reuse an ID across tenants or
clients when it would resolve to a different owner. A master bundle omits or
sets `scope.product_id` to `null` and must not set `parent_brand_revision`. A
product overlay sets `scope.product_id` and must set `scope.parent_brand_revision`
to the parent master revision; `brand_id` identifies that parent master. The
overlay contains only product-specific deltas and does not duplicate master
voice, claims, or templates.

`revision` is a new UTC identifier matching `YYYY-MM-DDTHHMMSSZ-rN` for every
material update. `status` is one of `draft`, `active`, or `superseded`; an
unverified or rights-blocked fact must not silently become an approved active
rule. Schema `1.0` remains readable for legacy bundles that have no `scope`;
the validator rejects a legacy `1.0` bundle as active production until it is
migrated to scoped `1.1`.

## Local namespace and product overlays

Use these local paths (with IDs already validated as lowercase-kebab):

```text
<hermes-data-root>/social-content/brands/<tenant-id>/<client-id>/<brand-id>/
<hermes-data-root>/social-content/brands/<tenant-id>/<client-id>/<brand-id>/products/<product-id>/
```

The first path is the master brand. The second is an overlay that references the
master by top-level `brand_id` and `scope.parent_brand_revision`; it is not a
second copy of the master. Consumers load the master first, then apply the
overlay's changed records and retain the master's unchanged rules.

## Evidence records

Any material value is accompanied by an evidence record or a field-level status:

```json
{
  "evidence_status": "exact",
  "source_id": "source-001",
  "source_locator": "user-upload:brief.pdf#page=2",
  "captured_at": "2026-01-01T000000Z",
  "confidence": 1.0,
  "notes": "Quoted from the supplied approved brief."
}
```

The allowed statuses are:

- `exact`: directly supplied, quoted, or explicitly approved;
- `observed`: visible/measurable in supplied material;
- `inferred`: a hypothesis derived from evidence, not a rule;
- `unverified`: claimed or expected but not yet supported.

## `brand-profile.json`

The profile contains `identity`, `audience`, `voice`, `terminology`,
`copy_constraints`, `visual_copy_cues`, `rights`, and `gaps`. Keep reusable
values small and structured. Each rule should include `id`, `value`,
`evidence_status`, and `source_ids`; examples in the template are empty arrays,
not defaults.

## `claim-registry.json`

`claims` is an array of records with `id`, `claim`, `claim_type`, `status`,
`evidence_status`, `source_ids`, `owner`, `verified_at`, `expires_at`,
`permitted_channels`, `rights`, and `notes`. `status` is one of `approved`,
`needs_review`, `blocked`, or `expired`. IDs are unique across all profile,
claim, and template records. Every `source_ids` entry must name a source in
`provenance.json`. An approved claim requires non-empty `source_ids`,
`evidence_status` `exact` or `observed`, and `rights.status` `approved` or
`exact`. Claims without evidence or permission must not be used as approved
copy.

## `template-registry.json`

`templates` is an array of provider-neutral copy patterns. Each record has `id`,
`name`, `purpose`, `channel`, `slots`, `constraints`, `claim_ids`,
`evidence_status`, `source_ids`, `rights`, and `status`. A slot is a named
variable with a type and required flag. `claim_ids` must reference existing
claims. An approved template follows the same evidence, source, and rights gate
as an approved claim. Provider references belong in a confirmed `integrations`
note and are never guessed.

## `provenance.json`

`sources` inventories only user-supplied or explicitly authorized sources and
stores unique `source_id`, `kind`, `locator`, `authorization`, `captured_at`,
and `content_fingerprint` when available. `evidence_ledger` maps reusable record
IDs to evidence statuses and source IDs; both record and source references must
resolve. `authorization` records the local consent status. `update` records the
local staging, validation, and activation receipt. Do not put source contents or
secrets in provenance; store stable local references and redacted fingerprints
only. For a `kind: "public-observation"` source, visible patterns may support
`observed` or `inferred` drafts without a Canva/Meta login, browser automation,
or prior ownership proof. If authorization is unknown, record it as
`unverified`; exact official colors, fonts, claims, and rights remain
`unverified` until an official source or owner approval is recorded. Do not copy
or download protected assets.

When the shared envelope is `active`, both `provenance.authorization.status` and
`brand-profile.json.rights.status` must be `approved` or `exact`. In addition,
the validator must receive an external trusted policy and trusted current actor
described in [references/access-policy.md](access-policy.md). The policy must
match the bundle's tenant/client/brand/product scope and map the runtime actor
and authorization receipt's actor to its declared `lead` or `admin` role. The
receipt must include the exact external `policy_id` and `policy_revision`.
The receipt's `role`, `verified`, and `policy_source` remain an audit record; they
are not authority by themselves. The same external policy gate applies to
approved claims and templates.

## Activation contract

The canonical consumer path is the four JSON files at the brand directory root.
An update first validates a complete staged bundle, atomically stores that bundle
under immutable `versions/<revision>/`, and only then publishes root files from
that validated version using per-file temporary-file renames. There is no
four-file atomic transaction or implicit pointer in this contract. Consumers
must load all four, compare their shared envelope, and retry/re-read on any
mixed-revision mismatch; they must never use a partial publication.
