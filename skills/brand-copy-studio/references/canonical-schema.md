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

### Anti-slop creative contract

The profile may add the following top-level fields. They are deliberately
provider-neutral and additive, so schema `1.0` readers can ignore them and
legacy drafts remain readable:

- `audience_situations`: concrete audience circumstances or questions;
- `strategic_tension`: the meaningful problem, trade-off, or change behind the
  brief;
- `human_proof_points`: supplied observations, examples, artifacts, quotes, or
  other reasons to believe;
- `voice_examples.positive` and `voice_examples.negative`: examples of the
  desired voice and patterns to avoid;
- `distinctive_assets`: recognizable assets with a semantic role and rights
  record; palette alone is not a distinctive asset;
- `visual_principles`, `composition_rules`, and `avoid_patterns`: visual
  invariants, intentional composition choices, and anti-patterns;
- `model_usage_policy`: `allowed`, `restricted`, and `prohibited` model uses,
  plus `human_approval_required` and `approval_required_for`;
- `approval_roles`: non-empty `copy`, `claims`, `design`, and `publish` role
  lists for privileged bundles; values are `lead`, `admin`, `reviewer`, or
  `publisher`;
- `feedback_reason_codes`: an object containing the exact bundle scope and a
  `codes` array of stable uppercase reason codes, dimensions, and descriptions.
- `situation_patterns`, `audience_moments`, and `observable_behaviors`: the
  moments and actions that make an audience situation concrete;
- `concrete_proof_details`: details that may be used only when their source
  and rights are available;
- `brand_stance`, `right_to_speak`, and `what_we_refuse_to_say`: the position,
  authority boundary, and deliberate exclusions behind the voice;
- `voice_as_behavior`: observable writing behavior, not adjectives such as
  “warm” or “bold”;
- `approved_verbal_assets` and `owned_vocabulary`: supplied, approved terms
  and verbal assets rather than invented slogans;
- `locale_policy`: default Indonesian locale, evidence-backed code-switching or
  slang rules, and any EYD/KBBI handling;
- `fake_intimacy_policy` and `unsupported_first_person_policy`: explicit
  constraints against invented diary voice, testimonials, or ungrounded “we/I”
  experience.
- `id_style_profile`: an additive Indonesian register contract. It records the
  target `channel`, `register`, `audience_relation`, and `region_or_community`,
  plus `pronoun_policy`, `particle_policy`, `code_switch_policy`,
  `contraction_spelling_policy`, and `approved_human_examples`. The validator
  also accepts `indonesian_style_profile` as a compatibility alias, but emits
  and documents `id_style_profile` as the canonical key.

The `id_style_profile` shape is intentionally explicit and evidence-oriented:

```json
{
  "id_style_profile": {
    "channel": [],
    "register": "",
    "audience_relation": "",
    "region_or_community": "",
    "pronoun_policy": {
      "approved": [],
      "avoid": [],
      "evidence_status": "unverified",
      "source_ids": []
    },
    "particle_policy": {
      "approved": [],
      "no_forced_slang": true,
      "evidence_status": "unverified",
      "source_ids": []
    },
    "code_switch_policy": {
      "allowed_terms": [],
      "do_not_translate": [],
      "translate_surrounding_syntax": true,
      "evidence_status": "unverified",
      "source_ids": []
    },
    "contraction_spelling_policy": {
      "approved_forms": [],
      "standard_forms": [],
      "prohibited_forms": [],
      "default_spelling": "",
      "rules": [],
      "evidence_status": "unverified",
      "source_ids": []
    },
    "approved_human_examples": [],
    "evidence_status": "unverified",
    "source_ids": []
  }
}
```

Every approved particle entry must identify the particle, its `speech_act`
(`speech_acts` is also accepted), its pragmatic `function`, and one or more
`approved_examples`, with evidence metadata. An empty approved-particle list
is valid when the profile deliberately uses no particles; `no_forced_slang`
must remain `true` for privileged output. `code_switch_policy.allowed_terms`
and `do_not_translate` are lists of evidence-backed objects with a `term` and
`reason` in privileged profiles. `contraction_spelling_policy` separates
approved colloquial forms from standard and prohibited forms; it does not
require a contraction or typo. Approved human examples carry their own
channel/register/audience/region metadata and evidence status.

The profile is optional for legacy bundles. Draft profiles may be empty or
incomplete while evidence is collected. If an active bundle or an approved
claim/template declares a colloquial or community-specific register, the
validator fails closed unless the full profile, policy evidence, approved human
examples, and source references are present and exact/observed. It never
converts slang density, particles, spelling variation, or any other property
into an AI detector or universal naturalness score. If the profile is absent,
generation should use neutral Indonesian rather than inventing a community
voice.

Use register values such as `formal_public`, `neutral_editorial`,
`friendly_conversational`, or `community_specific`; `fandom` and
`local_activation` are available when the supplied audience evidence supports
them. Channel values identify where the line will appear (for example,
`caption`, `carousel`, `website`, `comment`, `chat`, or `spoken_script`). The
region/community field may be `national` or a specifically evidenced place or
community; it is not a license to treat Jakarta usage as a national default.

Each creative-contract record carries `id`, a non-empty text/value field,
`evidence_status`, and `source_ids`. A distinctive asset additionally requires
`role` and `rights`. Drafts may leave these arrays empty while collecting
evidence. An `active` bundle, or any bundle containing an `approved` claim or
template, must provide every field, at least one item in every required list,
evidenced proof and voice examples, rights-cleared distinctive assets, a
scope-matching feedback taxonomy, and a model policy that makes human approval
mandatory. Missing or unknown values fail closed. This contract reports
explainable editorial evidence; it is not an AI-authorship detector or score.

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
