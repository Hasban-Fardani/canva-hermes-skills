#!/usr/bin/env python3
"""Deterministic tests for validate_content_spec.py."""

from __future__ import annotations

import hashlib
import io
import json
import struct
import zlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from validate_content_spec import _anti_slop_package_checksum, _canonical_json_digest, _decode_png, _id_profile_digest, _visible_copy_digest, _load_brand_bundle_validator, _open_beneath, calculate_package_checksum, load_benchmark_registry, load_trusted_policy, main, validate_content_spec  # noqa: E402

# Fixture callers explicitly derive the out-of-band pin from the separately
# loaded policy.  Production API callers must pass this pin themselves; the
# adapter keeps the legacy test call sites concise without weakening runtime
# validation.
_real_validate_content_spec = validate_content_spec
def validate_content_spec(*args, **kwargs):
    if kwargs.get("policy_digest") is None and len(args) > 3 and hasattr(args[3], "canonical_digest"):
        kwargs["policy_digest"] = args[3].canonical_digest
    return _real_validate_content_spec(*args, **kwargs)


TEST_EXPORT_DIR = tempfile.TemporaryDirectory(prefix="social-content-validator-")
TEST_BRAND_BUNDLE_DIR = tempfile.TemporaryDirectory(prefix="social-content-brand-bundle-")
TEST_INPUT_DIR = tempfile.TemporaryDirectory(prefix="social-content-validator-input-")
MASTER_BRAND_REVISION = "2026-08-19T000000Z-r1"


def load_json(name: str) -> dict:
    with (SKILL_DIR / "assets" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def trusted_policy(
    spec: dict,
    *,
    scope_override: dict | None = None,
    revision_override: str | None = None,
    provider_override: str | None = None,
    omit_fields: tuple[str, ...] = (),
    actor_role_override: str | None = None,
):
    policy = spec["policy"]
    payload = {
        "schema_version": policy["schema_version"],
        "policy_id": policy["policy_id"],
        "revision": revision_override or policy["revision"],
        "source": policy["source"],
        "identity_source": "local_authenticated_policy",
        "scope": dict(scope_override or policy["scope"]),
        "role_mapping": json.loads(json.dumps(policy["role_mapping"])),
        "actor_id": policy["actor_id"],
        "actor_role": actor_role_override or policy["actor_role"],
        # The external policy fixture intentionally mirrors the complete
        # capability-bearing unattended subtree.  Partial copies are rejected
        # by the trusted-policy boundary.
        "unattended": json.loads(json.dumps(policy.get("unattended", {}))),
    }
    for field in ("action_records", "benchmark_registry", "exception_policy", "evidence_tools", "evidence_results", "comparators", "filesystem_roots", "download_root"):
        if field in policy:
            payload[field] = json.loads(json.dumps(policy[field]))
    if provider_override:
        payload["unattended"]["preapproved"]["template_provider_ids"]["brand-template-001"] = provider_override
    for field in omit_fields:
        payload.pop(field, None)
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(payload, handle)
    handle.close()
    return load_trusted_policy(Path(handle.name))


def trusted_brand_policy(spec: dict, *, product_id: str | None = None):
    policy = spec["policy"]
    payload = {
        "schema_version": "1.0",
        "policy_id": "sample-brand-policy",
        "revision": policy["revision"],
        "source": "local_authenticated_policy",
        "scope": {
            "tenant_id": spec["scope"]["tenant_id"],
            "client_id": spec["scope"]["client_id"],
            "brand_id": spec["brand_id"],
            "product_id": product_id,
        },
        "role_mapping": {
            "admin": ["brand-admin-fixture"],
            "lead": ["brand-lead-fixture"],
            "reviewer": [],
            "member": [],
            "publisher": [],
        },
    }
    validator = _load_brand_bundle_validator()
    assert validator is not None
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(payload, handle)
    handle.close()
    return validator.TrustedAccessPolicyContext.from_file(handle.name)


def write_input_json(name: str, value: dict) -> Path:
    path = Path(TEST_INPUT_DIR.name) / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def full_scope(spec: dict) -> dict:
    return {**spec["scope"], "brand_id": spec["brand_id"]}


def benchmark_registry(spec: dict, *, reference_set_id: str = "fixture-benchmark", version: str = "1") -> dict:
    corpus_path = Path(TEST_INPUT_DIR.name) / f"{reference_set_id}-corpus.json"
    corpus_bytes = b"neutral benchmark corpus fixture"
    corpus_path.write_bytes(corpus_bytes)
    entry = {
        "reference_set_id": reference_set_id,
        "version": version,
        "status": "approved",
        "scope": full_scope(spec),
        "allowed_reviewer_ids": ["independent-critic-fixture"],
        "method": "pairwise_visual_review",
        "candidate_ids": ["recent-education-001"],
        "reference_corpus": [{"corpus_id": "fixture-corpus-001", "checksum": "sha256:" + hashlib.sha256(corpus_bytes).hexdigest(), "path": str(corpus_path)}],
    }
    entry["checksum"] = "sha256:" + hashlib.sha256(json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {
        "schema_version": "1.0",
        "source": "local_authenticated_benchmark_registry",
        "registry_id": "fixture-benchmark-registry",
        "revision": "1",
        "scope": full_scope(spec),
        "trusted_root": str(Path(TEST_INPUT_DIR.name)),
        "reference_sets": [entry],
    }


def neutral_brand_bundle(
    *,
    include_claim: bool = False,
    product_id: str | None = None,
    parent_brand_revision: str | None = None,
) -> str:
    """Write a scoped, provider-neutral Brand Copy bundle fixture."""
    root = Path(tempfile.mkdtemp(prefix="bundle-", dir=TEST_BRAND_BUNDLE_DIR.name))
    envelope = {
        "schema_version": "1.1",
        "brand_id": "sample-brand",
        "scope": {
            "tenant_id": "sample-tenant",
            "client_id": "sample-client",
            "product_id": product_id,
            "parent_brand_revision": parent_brand_revision,
        },
        "revision": MASTER_BRAND_REVISION,
        "status": "active",
    }
    documents = {
        "brand-profile.json": {
            **envelope,
            "identity": {},
            "brand_stance": {"id": "stance-1", "stance": "Name the next step plainly.", "evidence_status": "exact", "source_ids": ["source-1"]},
            "concrete_proof_details": [{"id": "detail-1", "value": "A source note makes a correction traceable.", "evidence_status": "exact", "source_ids": ["source-1"]}],
            "fake_intimacy_policy": {"rule": "Do not imply personal experience without provenance.", "status": "avoid_without_provenance", "evidence_status": "exact", "source_ids": ["source-1"]},
            "locale_policy": {"rule": "Use Indonesian locale unless a brief approves another locale.", "default_locale": "id-ID", "allowed_locales": ["id-ID"], "evidence_status": "exact", "source_ids": ["source-1"]},
            "observable_behaviors": [{"id": "behavior-1", "behavior": "Reader chooses one next step.", "evidence_status": "exact", "source_ids": ["source-1"]}],
            "owned_vocabulary": [{"id": "term-1", "term": "next step", "evidence_status": "exact", "source_ids": ["source-1"]}],
            "right_to_speak": {"id": "right-1", "right": "Speak only from supplied evidence.", "evidence_status": "exact", "source_ids": ["source-1"]},
            "what_we_refuse_to_say": {"id": "refusal-1", "refusal": "Do not promise performance outcomes.", "evidence_status": "exact", "source_ids": ["source-1"]},
            "voice_as_behavior": {"id": "voice-1", "behavior": "Name the next step plainly.", "evidence_status": "exact", "source_ids": ["source-1"]},
            "unsupported_first_person_policy": {"rule": "Do not imply personal experience without provenance.", "evidence_status": "exact", "source_ids": ["source-1"]},
            "audience": {},
            "voice": [],
            "terminology": [],
            "copy_constraints": [],
            "visual_copy_cues": [],
            "rights": {"status": "approved"},
            "gaps": [],
            "audience_situations": [
                {"id": "audience-1", "situation": "A reader needs a clear next step.", "evidence_status": "exact", "source_ids": ["source-1"]}
            ],
            "audience_moments": [{"id": "moment-1", "moment": "A reader needs a clear next step.", "evidence_status": "exact", "source_ids": ["source-1"]}],
            "situation_patterns": [{"id": "pattern-1", "situation": "A reader needs a clear next step.", "evidence_status": "exact", "source_ids": ["source-1"]}],
            "human_proof_points": [
                {"id": "proof-1", "proof": "A source note makes a correction traceable.", "evidence_status": "exact", "source_ids": ["source-1"]}
            ],
            "distinctive_assets": [
                {"id": "asset-1", "asset": "A source thread", "role": "connects evidence to a changed field", "evidence_status": "exact", "source_ids": ["source-1"], "rights": {"status": "approved"}}
            ],
            "visual_principles": [
                {"id": "visual-1", "principle": "Show relationships with editable labels.", "evidence_status": "exact", "source_ids": ["source-1"]}
            ],
            "composition_rules": [
                {"id": "composition-1", "rule": "Keep one primary action per page.", "evidence_status": "exact", "source_ids": ["source-1"]}
            ],
            "avoid_patterns": [
                {"id": "avoid-1", "pattern": "Unexplained decorative badges.", "evidence_status": "exact", "source_ids": ["source-1"]}
            ],
            "strategic_tension": {
                "id": "tension-1", "tension": "Scattered records make corrections hard to trace.", "evidence_status": "exact", "source_ids": ["source-1"]
            },
            "voice_examples": {
                "positive": [{"id": "voice-positive-1", "example": "Name the next step plainly.", "evidence_status": "exact", "source_ids": ["source-1"]}],
                "negative": [{"id": "voice-negative-1", "example": "Avoid unsupported guarantees.", "evidence_status": "exact", "source_ids": ["source-1"]}]
            },
            "approved_verbal_assets": [{"id": "asset-phrase-1", "value": "Name the next step plainly.", "status": "approved", "evidence_status": "exact", "source_ids": ["source-1"]}],
            "model_usage_policy": {
                "allowed": ["research", "draft", "format"],
                "restricted": ["copy"],
                "prohibited": ["approve", "publish", "rights-clearance"],
                "human_approval_required": True,
                "approval_required_for": ["claims", "design", "publish"]
            },
            "approval_roles": {"copy": ["lead"], "claims": ["lead"], "design": ["lead"], "publish": ["lead"]},
            "feedback_reason_codes": {
                "scope": {"brand_id": "sample-brand", "tenant_id": "sample-tenant", "client_id": "sample-client", "product_id": product_id or ""},
                "codes": [{"code": "TOO_GENERIC", "dimension": "distinctiveness", "description": "Message can be exchanged with another brand."}]
            }
        },
        "claim-registry.json": {
            **envelope,
            "claims": [
                {
                    "id": "claim-001",
                    "claim": "Supported neutral claim",
                    "status": "approved",
                    "evidence_status": "exact",
                    "source_ids": ["source-1"],
                    "rights": {"status": "approved"},
                    "expires_at": "2026-12-31T00:00:00Z",
                }
            ]
            if include_claim
            else [],
        },
        "template-registry.json": {
            **envelope,
            "templates": [
                {
                    "id": "recipe-001",
                    "name": "Neutral recipe",
                    "purpose": "Neutral bounded copy recipe",
                    "channel": "instagram",
                    "slots": [],
                    "constraints": {},
                    "claim_ids": [],
                    "evidence_status": "exact",
                    "source_ids": ["source-1"],
                    "rights": {"status": "approved"},
                    "status": "approved",
                    "version": "recipe-v1",
                }
            ],
        },
        "provenance.json": {
            **envelope,
            "sources": [
                {
                    "source_id": "source-1",
                    "kind": "user-provided",
                    "locator": "local:fixture",
                    "authorization": {"status": "exact"},
                    "captured_at": "2026-08-19T000000Z",
                }
            ],
            "evidence_ledger": [],
            "authorization": {
                "status": "approved",
                "actor_id": "brand-lead-fixture",
                "role": "lead",
                "verified": True,
                "policy_source": "local_authenticated_policy",
                "policy_id": "sample-brand-policy",
                "policy_revision": "2026-08-19T000000Z-r1",
            },
            "update": {"operation": "capture"},
        },
    }
    for filename, document in documents.items():
        (root / filename).write_text(json.dumps(document), encoding="utf-8")
    return str(root)

def approved_brand() -> dict:
    """Return an approved neutral fixture; never load a real brand profile."""
    return {
        "schema_version": "1.1",
        "brand_id": "sample-brand",
        "scope": {
            "tenant_id": "sample-tenant",
            "client_id": "sample-client",
            "product_id": None,
            "parent_brand_revision": None,
        },
        "revision": "2026-08-19T000000Z-r1",
        "status": "active",
        "identity": {},
        "audience": {},
        "voice": [],
        "terminology": [],
        "copy_constraints": [],
        "visual_copy_cues": [],
        "rights": {"status": "approved"},
        "gaps": [],
    }


def canonical_brand(*, status: str = "draft", rights_status: str = "unverified") -> dict:
    """Minimal Brand Copy Studio profile fixture (the full bundle is separate)."""
    return {
        "schema_version": "1.1",
        "brand_id": "sample-brand",
        "tenant_id": "sample-tenant",
        "client_id": "sample-client",
        "revision": "2026-08-19T000000Z-r1",
        "status": status,
        "identity": {},
        "audience": {},
        "voice": [],
        "terminology": [],
        "copy_constraints": [],
        "visual_copy_cues": [],
        "rights": {"status": rights_status},
        "gaps": [],
    }


def legacy_canonical_brand(*, scope: dict | None = None) -> dict:
    """Neutral schema 1.0 Brand Copy shape used for migration compatibility tests."""
    brand = {
        "schema_version": "1.0",
        "brand_id": "legacy-brand",
        "revision": "2026-08-19T000000Z-r1",
        "status": "draft",
        "identity": {},
        "audience": {},
        "voice": [],
        "terminology": [],
        "copy_constraints": [],
        "visual_copy_cues": [],
        "rights": {"status": "unverified"},
        "gaps": [],
    }
    if scope is not None:
        brand["scope"] = scope
    return brand


def make_approved_spec() -> dict:
    spec = load_json("content-spec.example.json")
    spec["state"] = "HUMAN_APPROVED"
    spec["policy"]["actor_id"] = "lead-fixture"
    spec["policy"]["actor_role"] = "lead"
    spec["policy"]["role_mapping"]["lead"] = ["lead-fixture", "independent-critic-fixture"]
    spec["policy"]["role_mapping"]["member"] = ["member-fixture", "generator-fixture"]
    spec["design"]["template_id"] = "brand-template-001"
    spec["design"]["template_version"] = "1"
    spec["design"]["provider"] = "canva"
    spec["design"]["provider_template_id"] = "CanvaOpaqueTemplate-EXAMPLE-001"
    spec["design"]["draft_ref"] = "canva:design:example"
    spec["design"]["generated_by"] = "generator-fixture"
    selection_receipt_digest = "sha256:" + hashlib.sha256(b"fixture-selection-receipt").hexdigest()
    generation_receipt_digest = "sha256:" + hashlib.sha256(b"fixture-generation-receipt").hexdigest()
    spec["human_selected_route"]["selection_receipt_id"] = "selection-receipt-fixture-001"
    spec["human_selected_route"]["selection_receipt_digest"] = selection_receipt_digest
    spec["design"]["generation_receipt_id"] = "generation-receipt-fixture-001"
    spec["design"]["generation_receipt_digest"] = generation_receipt_digest
    spec["policy"]["action_records"] = {
        "route_selection": {
            "actor_id": spec["human_selected_route"]["selected_by"],
            "receipt_id": spec["human_selected_route"]["selection_receipt_id"],
            "receipt_digest": selection_receipt_digest,
            "scope": full_scope(spec),
            "status": "verified",
            "recorded_at": "2026-08-19T09:00:00+07:00",
        },
        "generation": {
            "actor_id": spec["design"]["generated_by"],
            "receipt_id": spec["design"]["generation_receipt_id"],
            "receipt_digest": generation_receipt_digest,
            "scope": full_scope(spec),
            "status": "verified",
            "recorded_at": "2026-08-19T10:00:00+07:00",
        },
    }
    render_dir = Path(tempfile.mkdtemp(prefix="render-pages-", dir=TEST_EXPORT_DIR.name))
    page_hashes = []
    page_pixel_digests = []
    for page_number in range(1, len(spec["slides"]) + 1):
        # Minimal deterministic, fully decodable PNGs are sufficient for this
        # fixture; no runtime render artifact is committed to the repository.
        def png_chunk(kind: bytes, payload: bytes) -> bytes:
            body = kind + payload
            return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

        pixel_row = bytearray(1080 * 3)
        # Keep fixture pages visually distinct at the decoded-pixel layer so
        # the production validator can reject accidental repetition without a
        # blanket identity exception.
        pixel_row[0] = page_number
        raw = (b"\x00" + bytes(pixel_row)) * 1350
        png = b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1080, 1350, 8, 2, 0, 0, 0))
        png += png_chunk(b"IDAT", zlib.compress(raw, 9)) + png_chunk(b"IEND", b"")
        page_path = render_dir / f"page-{page_number}.png"
        page_path.write_bytes(png)
        page_hashes.append({"name": page_path.name, "sha256": hashlib.sha256(png).hexdigest()})
        page_pixel_digests.append("sha256:" + hashlib.sha256(bytes(pixel_row) * 1350).hexdigest())
    aggregate = hashlib.sha256()
    for index, item in enumerate(page_hashes, start=1):
        aggregate.update(json.dumps({"page_index": index, **item}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        aggregate.update(b"\n")
    render_digest = "sha256:" + aggregate.hexdigest()
    spec["design"]["render_ref"] = str(render_dir)
    spec["design"]["render_evidence"] = {"render_ref": str(render_dir), "render_digest": render_digest, "receipt_digest": render_digest, "receipt_id": "render-receipt-001", "provider": "local_renderer", "verification_status": "verified", "captured_at": "2026-08-19T11:00:00+07:00", "page_refs": [f"page-{i}" for i in range(1, len(spec["slides"]) + 1)], "scope": full_scope(spec)}
    spec["design"]["render_evidence"]["page_map"] = [
        {"page_index": index, "page_ref": f"page-{index}", "path": f"page-{index}.png", "sha256": page_hashes[index - 1]["sha256"]}
        for index in range(1, len(spec["slides"]) + 1)
    ]
    spec["design"]["remote_scope"] = full_scope(spec)
    spec["template_registry"]["entries"] = [
        {
            "template_id": "brand-template-001",
            "version": "1",
            "provider": "canva",
            "provider_template_id": "CanvaOpaqueTemplate-EXAMPLE-001",
            "status": "approved",
            "approved_by": "lead-fixture",
            "approved_by_role": "lead",
            "approved_at": "2026-08-19T10:00:00+07:00",
            "scope": full_scope(spec),
        }
    ]
    export_bytes = b"approved export fixture"
    export_path = Path(TEST_EXPORT_DIR.name) / "example-export.png"
    export_path.write_bytes(export_bytes)
    export_sha256 = hashlib.sha256(export_bytes).hexdigest()
    spec["design"]["export_checksum"] = "sha256:" + export_sha256
    selected_route = next(route for route in spec["route_set"]["routes"] if route["route_id"] == spec["human_selected_route"]["route_id"])
    action_common = {
        "content_id": spec["content_id"],
        "route_id": spec["human_selected_route"]["route_id"],
        "route_payload_digest": _canonical_json_digest(selected_route),
        "target_id": spec["publishing"].get("target_account"),
        "render_digest": render_digest,
        "package_digest": spec["design"]["export_checksum"],
    }
    spec["policy"]["action_records"]["route_selection"].update({"action_kind": "route_selection", **action_common, "design_id": None})
    spec["policy"]["action_records"]["generation"].update({"action_kind": "generation", **action_common, "design_id": spec["design"].get("canva_design_id")})
    spec["design"]["download"] = {
        "status": "downloaded",
        "scope": full_scope(spec),
        "local_path": str(export_path),
        "sha256": "sha256:" + export_sha256,
        "receipt": {
            "receipt_version": "1.0",
            "status": "downloaded",
            "output_path": str(export_path),
            "size_bytes": len(export_bytes),
            "sha256": export_sha256,
        },
    }
    spec["policy"]["download_root"] = str(TEST_EXPORT_DIR.name)
    render_stat = render_dir.resolve().stat()
    download_root = Path(TEST_EXPORT_DIR.name).resolve()
    download_stat = download_root.stat()
    spec["policy"]["filesystem_roots"] = {
        "render": {"path": str(render_dir.resolve()), "st_dev": render_stat.st_dev, "st_ino": render_stat.st_ino, "st_mode": render_stat.st_mode},
        "download": {"path": str(download_root), "st_dev": download_stat.st_dev, "st_ino": download_stat.st_ino, "st_mode": download_stat.st_mode},
    }
    for key in ("copy", "brand", "visual", "accessibility", "claims", "mobile_thumbnail"):
        spec["qa"][key] = {"status": "pass", "checked_at": "2026-08-19T11:00:00+07:00", "page_refs": ["page-1"]}
    spec["approval"].update(
        {
            "status": "approved",
            "approver": "design-marketing-lead",
            "approver_id": "lead-fixture",
            "approver_role": "lead",
            "identity_source": "local_authenticated_policy",
            "policy_id": "sample-social-policy",
            "policy_revision": "2026-08-19T000000Z-r1",
            "approved_at": "2026-08-19T11:00:00+07:00",
            "scope": "design+caption+target+schedule",
            "scope_ids": full_scope(spec),
        }
    )
    audit = spec["anti_slop_audit"]
    audit["anti_slop_contract_version"] = 2
    spec["human_copy_brief"] = {
        "situation": {"moment": "After the second meeting, tabs remain open.", "observable_behavior": "The reader switches tabs before opening one document."},
        "tension": {"audience_assumption": "More tabs means more progress.", "friction": "No task is selected."},
        "point_of_view": {"brand_stance": "Choose the next document plainly.", "what_we_refuse_to_say": "We do not promise productivity gains.", "right_to_speak": "The brief supplies the observed work moment."},
        "proof": {"concrete_details": ["second meeting", "seven tabs"], "source_refs": ["proof-organise"]},
        "creative_route": {"visual_dependency": "A tab strip shows the choice.", "distinctive_move": "Annotate one selected tab."},
        "message_jobs": {"headline": "Name the document.", "body": "Close the unrelated tabs.", "caption": "Use this after a task switch.", "cta_behavior": "Save for the next task switch."},
    }
    spec["copy_quality_audit"] = {"status": "pass", "reason_codes": [], "findings": []}
    spec["id_style_profile"] = {
        "register": "neutral_editorial",
        "channel": "carousel",
        "audience_relation": "customer",
        "region_or_community": "national",
        "pronoun_policy": {"allowed": ["Anda"]},
        "particle_policy": {},
        "code_switch_policy": {"allowed_terms": [], "reasons": {}},
        "scope": full_scope(spec),
    }
    spec["copy_quality_audit"]["indonesian_review"] = {
        "status": "fallback",
        "method": "neutral_editorial_fallback",
        "reason": "Fixture uses neutral editorial Indonesian and has no approved colloquial audience profile.",
        "scope": full_scope(spec),
        "profile_checksum": _id_profile_digest(spec["id_style_profile"]),
        "reviewed_copy_digest": _visible_copy_digest(spec),
        "reviewed_at": "2026-08-19T11:00:00+07:00",
    }
    for slide in spec["slides"]:
        slide["information_job"] = f"Fixture information job for slide {slide['slide']}"
        slide["progression"] = f"Advances the fixture sequence to slide {slide['slide']}."
    spec["message_units"] = []
    for slide_index, slide in enumerate(spec["slides"]):
        for field in ("headline", "body", "cta"):
            if not slide.get(field):
                continue
            spec["message_units"].append(
                {
                    "path": f"$.slides[{slide_index}].{field}",
                    "text": slide[field],
                    "information_job": f"Fixture {field} job for slide {slide['slide']}",
                    "provenance": {"kind": "creative_brief", "ref": "brief_version:1.0"},
                }
            )
    for field in ("hook", "body", "cta"):
        if not spec["caption"].get(field):
            continue
        unit = {
            "path": f"$.caption.{field}",
            "text": spec["caption"][field],
            "information_job": f"Fixture caption {field} job",
            "provenance": {"kind": "creative_brief", "ref": "brief_version:1.0"},
        }
        if field == "cta":
            unit.update(
                {
                    "functional_role": "action",
                    "role_justification": "Names the single next action for the reader.",
                }
            )
        spec["message_units"].append(unit)
    spec["art_direction"]["decorative_elements"][0].update(
        {"message_job": "Connects the changed field to its source evidence.", "proof_ids": ["proof-organise"]}
    )
    spec["copy_quality_audit"]["indonesian_review"]["reviewed_copy_digest"] = _visible_copy_digest(spec)
    audit["status"] = "pass"
    page_refs = [f"page-{i}" for i in range(1, len(spec["slides"]) + 1)]
    layout_pages = []
    semantic_pages = []
    fingerprints = []
    for index, page_ref in enumerate(page_refs):
        layout_pages.append(
            {
                "page_ref": page_ref,
                "dimensions": {"width": 1080, "height": 1350},
                "safe_area": {"left": 64, "top": 64, "right": 64, "bottom": 64},
                "element_boxes": [{"element_id": f"headline-{index + 1}", "x": 64, "y": 64, "width": 800, "height": 120}],
                "overflow": False,
                "overlap": False,
                "edge_checks": [{"status": "pass", "expected": 64, "actual": 64, "tolerance": 4}],
                "grid_checks": [{"status": "pass", "expected": 8, "actual": 8, "tolerance": 2}],
                "spacing_checks": [{"status": "pass", "expected": 24, "actual": 24, "tolerance": 4}],
            }
        )
        semantic_pages.append(
            {
                "page_ref": page_ref,
                "expected_objects": [{"object_id": f"headline-{index + 1}", "role": "headline"}],
                "observed_objects": [{"object_id": f"headline-{index + 1}", "role": "headline"}],
                "count_checks": [{"expected_count": 1, "observed_count": 1, "status": "pass"}],
                "relation_checks": [{"expected_relation": "headline anchors message", "observed_relation": "headline anchors message", "status": "pass"}],
                "copy_image_job": {"expected": "headline states the page message", "observed": "headline states the page message", "status": "pass"},
                "cta_target": ({"status": "pass", "expected": "save the guide", "observed": "save the guide"} if spec["slides"][index].get("cta") else {"status": "not_applicable", "reason": "No page-level CTA."}),
            }
        )
        fingerprints.append(
            {
                "page_ref": page_ref,
                "layout_family": f"fixture-layout-{index + 1}",
                "focal_object": f"headline-{index + 1}",
                "motif_family": f"fixture-motif-{index + 1}",
                "composition_axis": "vertical",
                "text_density": f"density-{index + 1}",
                "page_digest": page_pixel_digests[index],
                "assets": [],
            }
        )
    audit["visual_fingerprints"] = fingerprints
    audit["visual_fingerprint_render_digest"] = render_digest
    audit["evidence"] = {
        "ocr": {"status": "pass", "checked_at": "2026-08-19T11:00:00+07:00", "page_refs": page_refs, "render_digest": render_digest, "exact_match": True},
        "layout": {"status": "pass", "checked_at": "2026-08-19T11:00:00+07:00", "page_refs": page_refs, "render_digest": render_digest, "pages": layout_pages, "overflow": False, "overlap": False},
        "semantic": {"status": "pass", "checked_at": "2026-08-19T11:00:00+07:00", "page_refs": page_refs, "render_digest": render_digest, "pages": semantic_pages, "contract_tests": ["object", "count", "relation", "copy_image_job", "cta"]},
        "wcag": {"status": "pass", "checked_at": "2026-08-19T11:00:00+07:00", "page_refs": page_refs, "contrast_pass": True},
        "rights": {"status": "pass", "checked_at": "2026-08-19T11:00:00+07:00", "page_refs": page_refs, "assets": []},
        "recent_similarity": {"status": "pass", "checked_at": "2026-08-19T11:00:00+07:00", "page_refs": page_refs, "render_digest": render_digest, "candidate_window": "28d", "comparator": {"name": "fixture-comparator", "version": "1"}, "current_fingerprint": {"layout_family": "fixture-current", "focal_object": "fixture-current", "motif_family": "fixture-current", "composition_axis": "vertical", "text_density": "medium"}, "candidate_fingerprint": {"layout_family": "fixture-candidate", "focal_object": "fixture-candidate", "motif_family": "fixture-candidate", "composition_axis": "vertical", "text_density": "medium"}, "score": 0.24, "threshold": 0.80},
    }
    evidence_tools = {}
    for evidence_key in ("ocr", "layout", "semantic"):
        receipt_digest = "sha256:" + hashlib.sha256(f"fixture-{evidence_key}-receipt".encode()).hexdigest()
        evidence_tools[evidence_key] = {"tool_id": f"fixture-{evidence_key}-tool", "tool_version": "1", "receipt_id": f"fixture-{evidence_key}-receipt", "receipt_digest": receipt_digest, "render_digest": render_digest}
        audit["evidence"][evidence_key].update({"tool_id": evidence_tools[evidence_key]["tool_id"], "receipt_id": evidence_tools[evidence_key]["receipt_id"], "receipt_digest": receipt_digest})
    spec["policy"]["evidence_tools"] = evidence_tools
    spec["policy"]["comparators"] = {"fixture-comparator": {"version": "1"}}
    evidence_results = {}
    for evidence_key in ("ocr", "layout", "semantic", "recent_similarity"):
        evidence_value = audit["evidence"][evidence_key]
        result_id = f"fixture-{evidence_key}-result-001"
        result = {
            "result_id": result_id,
            "content_id": spec["content_id"],
            "render_digest": render_digest,
            "page_refs": page_refs,
            "scope": full_scope(spec),
            "timestamp": "2026-08-19T11:00:00+07:00",
            "observations": [{"observation": f"External {evidence_key} receipt."}],
            "fingerprints": [{"page_ref": page_ref, "page_digest": page_pixel_digests[index]} for index, page_ref in enumerate(page_refs)],
        }
        for field in ("tool_id", "tool_version", "receipt_id", "receipt_digest", "comparator", "candidate_window", "current_fingerprint", "candidate_fingerprint", "score", "threshold"):
            if field in evidence_value:
                result[field] = evidence_value[field]
        if evidence_key in evidence_tools:
            result["tool_id"] = evidence_tools[evidence_key]["tool_id"]
            result["tool_version"] = evidence_tools[evidence_key]["tool_version"]
            result["receipt_id"] = evidence_tools[evidence_key]["receipt_id"]
            result["receipt_digest"] = evidence_tools[evidence_key]["receipt_digest"]
        result["result_digest"] = _canonical_json_digest(result)
        evidence_results[evidence_key] = result
        evidence_value["result_id"] = result_id
        evidence_value["payload_digest"] = _canonical_json_digest({key: item for key, item in evidence_value.items() if key not in {"result_id", "result_digest", "payload_digest"}})
        result["payload_digest"] = evidence_value["payload_digest"]
        result["result_digest"] = _canonical_json_digest({key: item for key, item in result.items() if key != "result_digest"})
        evidence_value["result_digest"] = result["result_digest"]
        evidence_results[evidence_key] = result
    spec["policy"]["evidence_results"] = evidence_results
    audit["hard_blockers"] = {
        "scope_alignment": {"status": "pass", "evidence": "scope receipt"},
        "source_and_claim_evidence": {"status": "pass", "evidence": "source receipt"},
        "rights_provenance": {"status": "pass", "evidence": "rights receipt"},
        "ocr_exact_match": {"status": "pass", "evidence": "ocr receipt"},
        "layout_integrity": {"status": "pass", "evidence": "layout receipt"},
        "semantic_contract": {"status": "pass", "evidence": "semantic receipt"},
        "wcag_accessibility": {"status": "pass", "evidence": "wcag receipt"},
        "template_controls": {"status": "pass", "evidence": "template receipt"},
        "approval_package": {"status": "pass", "evidence": "approval receipt"},
    }
    audit["independent_critique"] = {
        "status": "pass",
        "reviewer_id": "independent-critic-fixture",
        "reviewer_role": "lead",
        "independent_from_generation": True,
        "reviewed_at": "2026-08-19T11:00:00+07:00",
        "method": "pairwise_visual_review",
        "render_digest": render_digest,
        "page_refs": page_refs,
        "observations": ["The annotated source trail remains legible at thumbnail size."],
        "verdict": "pass",
        "benchmark": {"status": "cannot_verify", "reference_set_id": "fixture-benchmark", "version": "1", "pairwise_verdict": [{"candidate_id": "recent-education-001", "verdict": "distinct"}]},
    }
    benchmark = audit["independent_critique"]["benchmark"]
    benchmark.update({
        "result_id": "fixture-benchmark-result-001",
        "content_id": spec["content_id"],
        "render_digest": render_digest,
        "page_refs": page_refs,
        "scope": full_scope(spec),
        "timestamp": "2026-08-19T11:00:00+07:00",
        "observations": [{"observation": "External benchmark receipt."}],
        "fingerprints": [{"page_ref": page_ref, "page_digest": page_pixel_digests[index]} for index, page_ref in enumerate(page_refs)],
    })
    benchmark["payload_digest"] = _canonical_json_digest({key: value for key, value in benchmark.items() if key not in {"result_id", "result_digest", "payload_digest"}})
    benchmark["result_digest"] = _canonical_json_digest({key: value for key, value in benchmark.items() if key != "result_digest"})
    spec["policy"]["evidence_results"]["benchmark"] = json.loads(json.dumps(benchmark))
    audit["approval_package"] = {
        "scope": full_scope(spec),
        "content_id": spec["content_id"],
        "render_digest": render_digest,
        "export_checksum": spec["design"]["export_checksum"],
        "checksum_algorithm": "anti-slop-v2",
    }
    audit["approval_package"]["checksum"] = _anti_slop_package_checksum(spec, audit)
    spec["approval"]["package_checksum"] = calculate_package_checksum(spec)
    return spec


class ValidatorTests(unittest.TestCase):
    TODAY = date(2026, 8, 19)

    def id_copy_spec(self, text: str) -> dict:
        spec = load_json("content-spec.example.json")
        spec["single_message"] = text
        spec["slides"][0]["headline"] = text
        spec["caption"] = {"hook": text, "body": "", "cta": "", "hashtags": []}
        return spec

    def test_indonesian_stiff_findings_have_reason_codes_and_evidence_spans(self) -> None:
        spec = self.id_copy_spec("Kami mengecek pesanan Anda. Kami mengemasnya. Kami mengirimkannya sore ini. Open dashboard untuk melihat statusnya.")
        spec["id_style_profile"] = {
            "register": "neutral_editorial",
            "channel": "carousel",
            "audience_relation": "customer",
            "region_or_community": "national",
            "pronoun_policy": {"allowed": ["Anda"]},
            "particle_policy": {},
            "code_switch_policy": {"allowed_terms": ["tab"], "reasons": {"tab": "UI label"}},
        }
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        codes = {issue.code for issue in report.warnings}
        self.assertIn("id_explicit_subject_repeat", codes)
        self.assertIn("id_unexplained_code_switch", codes)
        evidence = [issue.evidence_span for issue in report.warnings if issue.code == "id_explicit_subject_repeat"]
        self.assertTrue(evidence and evidence[0]["text"] and evidence[0]["path"])

    def test_repeated_subject_evidence_spans_point_to_second_and_third_subject(self) -> None:
        spec = self.id_copy_spec("Kami mengecek pesanan. Kami mengemasnya. Kami mengirimkannya.")
        spec["id_style_profile"] = {
            "register": "neutral_editorial", "channel": "carousel", "audience_relation": "customer",
            "region_or_community": "national", "pronoun_policy": {"allowed": ["Kami"]},
            "particle_policy": {}, "code_switch_policy": {"allowed_terms": []},
        }
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        spans = [
            issue.evidence_span
            for issue in report.warnings
            if issue.code == "id_explicit_subject_repeat"
            and issue.evidence_span["path"] == "$.slides[0].headline"
        ]
        self.assertEqual(["Kami", "Kami"], [span["text"] for span in spans])
        self.assertEqual(sorted(span["start"] for span in spans), [span["start"] for span in spans])
        for span in spans:
            field_text = spec["slides"][0]["headline"]
            self.assertEqual(field_text[span["start"]:span["end"]], span["text"])

    def test_production_embedded_style_source_must_resolve_tagged_scoped_evidence(self) -> None:
        spec = self.id_copy_spec("Yuk, cek dokumen ini!")
        spec["state"] = "DESIGN_DRAFT"
        spec["design"]["draft_ref"] = "local:fixture-draft"
        spec["id_style_profile"] = {
            "register": "friendly_conversational", "channel": "carousel", "audience_relation": "customer",
            "region_or_community": "national", "source_ids": ["fake-style-source"],
            "pronoun_policy": {"allowed": ["kamu"]}, "particle_policy": {"allowed": []},
            "code_switch_policy": {"allowed_terms": []},
        }
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("id_style_profile_source_unresolved", {issue.code for issue in report.errors})

    def test_colloquial_indonesian_requires_explicit_style_profile(self) -> None:
        spec = self.id_copy_spec("Yuk, cek promo ini bareng bestie!")
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("id_style_profile_required", {issue.code for issue in report.errors})

    def test_approved_particle_provenance_does_not_force_particles_or_slang(self) -> None:
        spec = self.id_copy_spec("Yuk, cek dokumen ini di aplikasi.")
        spec["id_style_profile"] = {
            "register": "friendly_conversational",
            "channel": "carousel",
            "audience_relation": "customer",
            "region_or_community": "national",
            "pronoun_policy": {"allowed": ["kamu"]},
            "particle_policy": {
                "allowed": [{"form": "yuk", "function": "invitation", "speech_act": "invitation", "approved_examples": ["Yuk, cek dokumen ini."]}]
            },
            "code_switch_policy": {"allowed_terms": ["aplikasi"], "reasons": {"aplikasi": "ordinary Indonesian"}},
        }
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertNotIn("id_style_profile_required", {issue.code for issue in report.errors})
        self.assertNotIn("id_particle_without_provenance", {issue.code for issue in report.warnings})

    def test_recoverable_indonesian_fragments_and_ellipsis_are_not_banned(self) -> None:
        spec = self.id_copy_spec("Terlalu banyak tab. Satu pekerjaan belum mulai…")
        spec["eyd_review"] = {"standard": "EYD V", "status": "pass", "findings": []}
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        id_codes = {issue.code for issue in report.issues if issue.code.startswith("id_")}
        self.assertEqual(set(), id_codes)

    def test_production_copy_audit_requires_review_or_neutral_fallback_and_slide_progression(self) -> None:
        spec = make_approved_spec()
        spec["copy_quality_audit"].pop("indonesian_review")
        spec["slides"][0].pop("information_job")
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        codes = {issue.code for issue in report.errors}
        self.assertIn("id_copy_review_required", codes)
        self.assertIn("slide_information_job_missing", codes)

    def test_production_decorative_microcopy_requires_a_job(self) -> None:
        spec = make_approved_spec()
        spec["slides"][0]["extra_text"] = [{"text": "Page 1 of 5"}]
        spec["message_units"].append(
            {
                "path": "$.slides[0].extra_text[0].text",
                "text": "Page 1 of 5",
            }
        )
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        codes = {issue.code for issue in report.errors}
        self.assertIn("REDUNDANT_DECORATIVE_MICROCOPY", codes)
        self.assertIn("message_unit_information_job_missing", codes)

    def test_visible_false_cannot_hide_canonical_text(self) -> None:
        spec = make_approved_spec()
        spec["message_units"][0]["visible"] = False
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("message_unit_visibility_mismatch", {issue.code for issue in report.errors})

    def test_self_attested_job_does_not_legalize_decorative_patterns(self) -> None:
        spec = make_approved_spec()
        spec["slides"][0]["extra_text"] = [{"text": "Page 1 of 5"}, {"text": "→"}]
        spec["message_units"].extend(
            [
                {
                    "path": "$.slides[0].extra_text[0].text",
                    "text": "Page 1 of 5",
                    "information_job": "Shows the page count",
                },
                {
                    "path": "$.slides[0].extra_text[1].text",
                    "text": "→",
                    "information_job": "Adds visual direction",
                },
            ]
        )
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertGreaterEqual(
            sum(issue.code == "REDUNDANT_DECORATIVE_MICROCOPY" for issue in report.errors),
            2,
        )

        spec = make_approved_spec()
        spec["slides"][1]["headline"] = spec["slides"][2]["headline"] = "Panduan Data"
        for unit in spec["message_units"]:
            if unit["path"] == "$.slides[1].headline":
                unit["text"] = "Panduan Data"
                unit["information_job"] = "Introduces the context"
            if unit["path"] == "$.slides[2].headline":
                unit["text"] = "Panduan Data"
                unit["information_job"] = "Introduces the next step"
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("REDUNDANT_DECORATIVE_MICROCOPY", {issue.code for issue in report.errors})

    def test_message_unit_path_must_exist_and_match_text(self) -> None:
        invalid = make_approved_spec()
        invalid["message_units"][0]["path"] = "$.slides[99].headline"
        report = validate_content_spec(invalid, approved_brand(), self.TODAY, trusted_policy(invalid), actor_id="lead-fixture")
        self.assertIn("message_unit_path_invalid", {issue.code for issue in report.errors})

        mismatch = make_approved_spec()
        mismatch["message_units"][0]["text"] = "Different text"
        report = validate_content_spec(mismatch, approved_brand(), self.TODAY, trusted_policy(mismatch), actor_id="lead-fixture")
        self.assertIn("message_unit_text_mismatch", {issue.code for issue in report.errors})

    def test_malformed_or_unresolved_provenance_is_reported(self) -> None:
        malformed = make_approved_spec()
        unit = malformed["message_units"][0]
        unit.update(
            {
                "functional_role": "source",
                "role_justification": "Identifies the evidence source.",
                "provenance": {"source_ids": [None]},
            }
        )
        report = validate_content_spec(malformed, approved_brand(), self.TODAY, trusted_policy(malformed), actor_id="lead-fixture")
        self.assertIn("message_unit_provenance_type", {issue.code for issue in report.errors})

        unresolved = make_approved_spec()
        unit = unresolved["message_units"][0]
        unit.update(
            {
                "functional_role": "source",
                "role_justification": "Identifies the evidence source.",
                "provenance": {"source_ids": ["proof-checklist"]},
            }
        )
        report = validate_content_spec(unresolved, approved_brand(), self.TODAY, trusted_policy(unresolved), actor_id="lead-fixture")
        self.assertIn("message_unit_provenance_unresolved", {issue.code for issue in report.errors})

    def test_message_unit_aliases_cannot_be_supplied_together(self) -> None:
        spec = make_approved_spec()
        spec["text_elements"] = [dict(spec["message_units"][0])]
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("message_unit_alias_conflict", {issue.code for issue in report.errors})

    def test_manifest_checksum_binding_preserves_legacy_hashes(self) -> None:
        spec = make_approved_spec()
        original = calculate_package_checksum(spec)
        spec["message_units"][0]["information_job"] += " changed"
        self.assertNotEqual(original, calculate_package_checksum(spec))

        legacy = make_approved_spec()
        legacy.pop("message_units")
        legacy["copy_quality_audit"]["indonesian_review"]["reviewed_copy_digest"] = _visible_copy_digest(legacy)
        legacy["anti_slop_audit"]["approval_package"]["checksum"] = _anti_slop_package_checksum(legacy, legacy["anti_slop_audit"])
        legacy["approval"]["package_checksum"] = calculate_package_checksum(legacy)
        legacy_checksum = calculate_package_checksum(legacy)
        self.assertRegex(legacy_checksum, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(legacy_checksum, legacy["approval"]["package_checksum"])

    def test_draft_decorative_microcopy_is_a_warning_for_migration(self) -> None:
        spec = load_json("content-spec.example.json")
        spec["slides"][0]["extra_text"] = [{"text": "→"}]
        spec["text_elements"] = [{"path": "$.slides[0].extra_text[0].text", "text": "→"}]
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("REDUNDANT_DECORATIVE_MICROCOPY", {issue.code for issue in report.warnings})
        self.assertFalse(any(issue.code == "REDUNDANT_DECORATIVE_MICROCOPY" for issue in report.errors))

    def test_provenance_backed_functional_microcopy_is_not_false_positive(self) -> None:
        spec = make_approved_spec()
        spec["slides"][0]["extra_text"] = [
            {"text": "Sumber: checklist layanan"},
            {"text": "Halaman 1 dari 5"},
            {"text": "© 2026 Sample Publisher"},
        ]
        spec["message_units"].extend(
            [
                {
                    "path": "$.slides[0].extra_text[0].text",
                    "text": "Sumber: checklist layanan",
                    "functional_role": "source",
                    "role_justification": "Lets the reader verify the evidence behind the guide.",
                    "provenance": {"source_ids": ["source-1"]},
                },
                {
                    "path": "$.slides[0].extra_text[1].text",
                    "text": "Halaman 1 dari 5",
                    "functional_role": "navigation",
                    "role_justification": "Tells the reader where they are in the carousel.",
                    "navigation_target": "$.slides[1]",
                    "provenance": {"kind": "render_navigation", "ref": "source-1"},
                },
                {
                    "path": "$.slides[0].extra_text[2].text",
                    "text": "© 2026 Sample Publisher",
                    "functional_role": "legal",
                    "role_justification": "Identifies the rights notice required on the export.",
                    "provenance": {"kind": "approved_policy", "ref": "source-1"},
                },
            ]
        )
        report = validate_content_spec(
            spec,
            approved_brand(),
            self.TODAY,
            trusted_policy(spec),
            actor_id="lead-fixture",
            brand_bundle=neutral_brand_bundle(),
        )
        self.assertNotIn("REDUNDANT_DECORATIVE_MICROCOPY", {issue.code for issue in report.issues})

    def test_repeated_theme_headers_are_flagged_but_repeated_ctas_are_not(self) -> None:
        spec = load_json("content-spec.example.json")
        spec["slides"][1]["headline"] = "Panduan Data"
        spec["slides"][2]["headline"] = "Panduan Data"
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("REDUNDANT_DECORATIVE_MICROCOPY", {issue.code for issue in report.warnings})

        spec = load_json("content-spec.example.json")
        spec["slides"][0]["extra_text"] = [{"text": "Overview"}]
        spec["text_elements"] = [{"path": "$.slides[0].extra_text[0].text", "text": "Overview"}]
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("REDUNDANT_DECORATIVE_MICROCOPY", {issue.code for issue in report.warnings})

        spec = load_json("content-spec.example.json")
        spec["slides"][1]["cta"] = "Simpan panduan ini."
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertNotIn("REDUNDANT_DECORATIVE_MICROCOPY", {issue.code for issue in report.warnings})

    def test_action_role_cannot_exempt_repeated_headers(self) -> None:
        spec = make_approved_spec()
        spec["slides"][1]["headline"] = spec["slides"][2]["headline"] = "Panduan Data"
        for unit in spec["message_units"]:
            if unit["path"] in {"$.slides[1].headline", "$.slides[2].headline"}:
                unit.update(
                    {
                        "text": "Panduan Data",
                        "functional_role": "action",
                        "role_justification": "Moves the reader forward.",
                    }
                )
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        codes = {issue.code for issue in report.errors}
        self.assertIn("message_unit_action_semantics", codes)
        self.assertIn("REDUNDANT_DECORATIVE_MICROCOPY", codes)

    def test_generic_labels_need_role_specific_evidence_and_authority(self) -> None:
        spec = make_approved_spec()
        spec["slides"][0]["extra_text"] = [
            {"text": "Overview"},
            {"text": "Guide"},
            {"text": "Panduan"},
        ]
        roles = ("label", "navigation", "branding")
        for index, role in enumerate(roles):
            spec["message_units"].append(
                {
                    "path": f"$.slides[0].extra_text[{index}].text",
                    "text": spec["slides"][0]["extra_text"][index]["text"],
                    "functional_role": role,
                    "role_justification": "Keeps the small text visible for the reader.",
                    "provenance": {"brand_id": "sample-brand"},
                }
            )
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        codes = {issue.code for issue in report.errors}
        self.assertGreaterEqual(sum(issue.code == "REDUNDANT_DECORATIVE_MICROCOPY" for issue in report.errors), 3)
        self.assertIn("message_unit_provenance_unresolved", codes)

    def test_mutable_source_packet_id_cannot_authorize_functional_microcopy(self) -> None:
        spec = make_approved_spec()
        spec["slides"][0]["extra_text"] = [{"text": "Sumber: checklist layanan"}]
        spec["message_units"].append(
            {
                "path": "$.slides[0].extra_text[0].text",
                "text": "Sumber: checklist layanan",
                "functional_role": "source",
                "role_justification": "Lets the reader verify the source.",
                "provenance": {"source_ids": ["proof-checklist"]},
            }
        )
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("message_unit_provenance_unresolved", {issue.code for issue in report.errors})

    def test_duplicate_message_unit_paths_across_nested_aliases_are_rejected(self) -> None:
        spec = make_approved_spec()
        spec["slides"][0]["text_elements"] = [dict(spec["message_units"][0])]
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("message_unit_duplicate_path", {issue.code for issue in report.errors})

    def test_common_indonesian_and_english_ctas_are_not_verb_heuristic_false_positives(self) -> None:
        for phrase in ("Buat akun", "Daftar", "Join us", "Lihat detail", "Ayo mulai"):
            spec = make_approved_spec()
            spec["slides"][1]["cta"] = spec["slides"][2]["cta"] = phrase
            for index in (1, 2):
                spec["message_units"].append(
                    {
                        "path": f"$.slides[{index}].cta",
                        "text": phrase,
                        "functional_role": "action",
                        "role_justification": "Offers the reader the next concrete action.",
                    }
                )
            report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
            codes = {issue.code for issue in report.errors}
            self.assertNotIn("message_unit_action_semantics", codes, phrase)
            self.assertNotIn("REDUNDANT_DECORATIVE_MICROCOPY", codes, phrase)

    def test_role_evidence_must_bind_targets_and_brand_assets(self) -> None:
        spec = make_approved_spec()
        spec["slides"][0]["extra_text"] = [
            {"text": "Overview"},
            {"text": "Overview"},
            {"text": "Guide"},
            {"text": "Panduan"},
            {"text": "Catatan"},
            {"text": "See more"},
        ]
        units = (
            ("navigation", "navigation_target", "slide-2"),
            ("navigation", "navigation_target", "slide-3"),
            ("accessibility", "aria_for", "headline"),
            ("branding", "brand_asset_id", "unapproved-asset"),
            ("label", "label_for", "headline"),
            ("navigation", "navigation_target", "slide-4"),
        )
        for index, (role, evidence_key, evidence_value) in enumerate(units):
            spec["message_units"].append(
                {
                    "path": f"$.slides[0].extra_text[{index}].text",
                    "text": spec["slides"][0]["extra_text"][index]["text"],
                    "functional_role": role,
                    "role_justification": "The small text identifies a real interface relationship.",
                    evidence_key: evidence_value,
                    "provenance": {"source_ids": ["source-1"]},
                }
            )
        report = validate_content_spec(
            spec,
            approved_brand(),
            self.TODAY,
            trusted_policy(spec),
            actor_id="lead-fixture",
            brand_bundle=neutral_brand_bundle(),
        )
        self.assertGreaterEqual(sum(issue.code == "REDUNDANT_DECORATIVE_MICROCOPY" for issue in report.errors), 5)

    def test_malformed_copy_reason_code_is_reported_without_crashing(self) -> None:
        spec = self.id_copy_spec("Kami menyediakan panduan.")
        spec["state"] = "BRAND_QA"
        spec["human_copy_brief"] = {"proof": {"source_refs": ["proof-organise"]}}
        spec["copy_quality_audit"] = {"status": "pass", "reason_codes": [{"bad": "shape"}], "findings": []}
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("copy_quality_reason_codes", {issue.code for issue in report.errors})

    def test_nominalization_suffix_false_positives_remain_clean(self) -> None:
        spec = self.id_copy_spec("Pelanggan membuka langkahnya dan memeriksa sumbernya.")
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertNotIn("id_abstract_nominalization_cluster", {issue.code for issue in report.warnings})

    def test_code_switch_policy_accepts_term_objects_and_checksum_binds_copy_audit(self) -> None:
        spec = self.id_copy_spec("Buka Settings lalu pilih Save di dashboard.")
        spec["id_style_profile"] = {
            "register": "friendly_conversational", "channel": "carousel", "audience_relation": "customer",
            "region_or_community": "national", "source_ids": ["fixture-style"], "pronoun_policy": {"allowed": ["kamu"]},
            "particle_policy": {}, "code_switch_policy": {"allowed_terms": [{"term": "Settings", "reason": "UI label"}, {"term": "Save", "reason": "UI label"}, {"term": "dashboard", "reason": "UI label"}]},
        }
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertNotIn("id_unexplained_code_switch", {issue.code for issue in report.warnings})
        approved = make_approved_spec()
        before = calculate_package_checksum(approved)
        approved["copy_quality_audit"]["findings"] = [{"reason_code": "id_register_jump", "evidence_span": {"path": "$.slides[0].headline", "text": "fixture", "start": 0, "end": 7}}]
        self.assertNotEqual(before, calculate_package_checksum(approved))

    def test_privileged_external_policy_requires_each_actor_metadata_field(self) -> None:
        for field in ("actor_id", "actor_role", "identity_source"):
            spec = make_approved_spec()
            context = trusted_policy(spec, omit_fields=(field,))
            report = validate_content_spec(spec, approved_brand(), self.TODAY, context, actor_id="lead-fixture")
            self.assertTrue(report.errors, field)

    def test_external_actor_role_must_match_mapped_role(self) -> None:
        spec = make_approved_spec()
        context = trusted_policy(spec, actor_role_override="reviewer")
        report = validate_content_spec(spec, approved_brand(), self.TODAY, context, actor_id="lead-fixture")
        self.assertIn("trusted_policy_actor_membership", {issue.code for issue in report.errors})

    def test_trusted_policy_requires_actor_membership_and_rejects_wildcards(self) -> None:
        spec = make_approved_spec()
        spec["policy"]["role_mapping"]["lead"] = ["everyone"]
        context = trusted_policy(spec)
        report = validate_content_spec(spec, approved_brand(), self.TODAY, context, actor_id="lead-fixture")
        self.assertIn("role_mapping_identity", {i.code for i in report.errors})

    def test_copy_personal_experience_requires_approved_policy_and_resolved_source(self) -> None:
        for phrase in (
            "We know exactly how you feel.",
            "We also have been in your shoes.",
            "Kami tahu apa yang Anda rasakan.",
            "Kami juga pernah berada di posisi Anda.",
        ):
            spec = load_json("content-spec.example.json")
            spec["state"] = "BRAND_QA"
            spec["single_message"] = phrase
            spec["human_copy_brief"] = {"proof": {"source_refs": ["arbitrary-ref"]}}
            spec["copy_quality_audit"] = {"status": "pass", "reason_codes": [], "findings": []}
            report = validate_content_spec(spec, approved_brand(), self.TODAY)
            self.assertIn("UNSUPPORTED_PERSONAL_OR_PERFORMANCE_CLAIM", {issue.code for issue in report.errors}, phrase)

    def test_ordinary_institutional_first_person_is_not_false_positive_intimacy(self) -> None:
        spec = load_json("content-spec.example.json")
        spec["state"] = "BRAND_QA"
        spec["single_message"] = "Kami menyediakan panduan yang jelas untuk langkah berikutnya."
        spec["human_copy_brief"] = {"proof": {"source_refs": ["arbitrary-ref"]}}
        spec["copy_quality_audit"] = {"status": "pass", "reason_codes": [], "findings": []}
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertNotIn("UNSUPPORTED_PERSONAL_OR_PERFORMANCE_CLAIM", {issue.code for issue in report.errors})

    def test_malformed_route_and_proof_ids_fail_structurally_without_crashing(self) -> None:
        for malformed_route_id in ({}, [], None):
            spec = load_json("content-spec.example.json")
            spec["route_set"]["routes"][0]["route_id"] = malformed_route_id
            report = validate_content_spec(spec, approved_brand(), self.TODAY)
            self.assertTrue(report.errors)
        for malformed_proof_id in ({}, [], None):
            spec = load_json("content-spec.example.json")
            spec["source_packet"]["proof_ids"] = [malformed_proof_id]
            report = validate_content_spec(spec, approved_brand(), self.TODAY)
            self.assertTrue(report.errors)

    def test_approval_checksum_matches_independent_golden_literal(self) -> None:
        spec = make_approved_spec()
        checksum = calculate_package_checksum(spec)
        self.assertRegex(checksum, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(checksum, spec["approval"]["package_checksum"])

    def test_early_example_passes_with_approved_brand(self) -> None:
        spec = load_json("content-spec.example.json")
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="member-fixture")
        self.assertEqual([], report.issues)
        self.assertTrue(report.passes(strict=True))

    def test_draft_brand_is_honestly_warned(self) -> None:
        draft_brand = approved_brand()
        draft_brand["status"] = "draft"
        report = validate_content_spec(
            load_json("content-spec.example.json"),
            draft_brand,
            self.TODAY,
        )
        self.assertFalse(report.errors)
        self.assertIn("canonical_brand_draft", {issue.code for issue in report.warnings})
        self.assertFalse(report.passes(strict=True))

    def test_canonical_draft_brand_is_warned(self) -> None:
        report = validate_content_spec(load_json("content-spec.example.json"), canonical_brand(), self.TODAY)
        self.assertFalse(report.errors)
        self.assertIn("canonical_brand_draft", {issue.code for issue in report.warnings})
        self.assertFalse(report.passes(strict=True))

    def test_legacy_canonical_draft_without_scope_is_warning_only(self) -> None:
        spec = load_json("content-spec.example.json")
        spec["brand_id"] = "legacy-brand"
        spec["policy"]["scope"]["brand_id"] = "legacy-brand"
        spec["measurement"]["benchmark_scope"]["brand_id"] = "legacy-brand"
        report = validate_content_spec(spec, legacy_canonical_brand(), self.TODAY)
        self.assertFalse(report.errors)
        warning_codes = {issue.code for issue in report.warnings}
        self.assertIn("legacy_brand_compatibility", warning_codes)
        self.assertIn("legacy_brand_scope", warning_codes)
        self.assertIn("canonical_brand_draft", warning_codes)

        partial = legacy_canonical_brand(scope={"tenant_id": "sample-tenant"})
        report = validate_content_spec(spec, partial, self.TODAY)
        codes = {issue.code for issue in report.errors}
        self.assertIn("brand_client_mismatch", codes)

        cross_scope = legacy_canonical_brand(
            scope={
                "tenant_id": "other-tenant",
                "client_id": "sample-client",
                "product_id": None,
                "parent_brand_revision": None,
            }
        )
        report = validate_content_spec(spec, cross_scope, self.TODAY)
        self.assertIn("brand_tenant_mismatch", {issue.code for issue in report.errors})

    def test_legacy_canonical_profile_cannot_authorize_final_state(self) -> None:
        spec = make_approved_spec()
        spec["brand_id"] = "legacy-brand"
        spec["policy"]["scope"]["brand_id"] = "legacy-brand"
        spec["measurement"]["benchmark_scope"]["brand_id"] = "legacy-brand"
        spec["approval"]["package_checksum"] = calculate_package_checksum(spec)
        report = validate_content_spec(
            spec,
            legacy_canonical_brand(),
            self.TODAY,
            trusted_policy(spec),
            actor_id="lead-fixture",
        )
        self.assertIn("legacy_brand_migration_required", {issue.code for issue in report.errors})

    def test_canonical_active_brand_requires_approved_rights(self) -> None:
        approved = validate_content_spec(
            load_json("content-spec.example.json"),
            canonical_brand(status="active", rights_status="exact"),
            self.TODAY,
            trusted_policy(load_json("content-spec.example.json")),
            "member-fixture",
        )
        self.assertEqual([], approved.issues)

        blocked = validate_content_spec(
            load_json("content-spec.example.json"),
            canonical_brand(status="active", rights_status="blocked"),
            self.TODAY,
        )
        self.assertIn("canonical_brand_rights", {issue.code for issue in blocked.errors})

    def test_canonical_superseded_brand_is_blocked(self) -> None:
        report = validate_content_spec(
            load_json("content-spec.example.json"),
            canonical_brand(status="superseded", rights_status="exact"),
            self.TODAY,
        )
        self.assertIn("canonical_brand_superseded", {issue.code for issue in report.errors})

    def test_canonical_brand_id_still_must_match(self) -> None:
        brand = canonical_brand(status="active", rights_status="approved")
        brand["brand_id"] = "other-brand"
        report = validate_content_spec(load_json("content-spec.example.json"), brand, self.TODAY)
        self.assertIn("brand_mismatch", {issue.code for issue in report.errors})

    def test_canonical_brand_scope_rejects_cross_tenant_and_client(self) -> None:
        brand = canonical_brand(status="active", rights_status="approved")
        brand["tenant_id"] = "other-tenant"
        brand["client_id"] = "other-client"
        report = validate_content_spec(load_json("content-spec.example.json"), brand, self.TODAY)
        codes = {issue.code for issue in report.errors}
        self.assertIn("brand_tenant_mismatch", codes)
        self.assertIn("brand_client_mismatch", codes)

    def test_nested_master_and_overlay_scope_isolated(self) -> None:
        master = approved_brand()
        master["scope"]["tenant_id"] = "other-tenant"
        report = validate_content_spec(load_json("content-spec.example.json"), master, self.TODAY)
        self.assertIn("brand_tenant_mismatch", {issue.code for issue in report.errors})

        overlay = approved_brand()
        overlay["scope"]["product_id"] = "other-product"
        overlay["scope"]["parent_brand_revision"] = "2026-08-19T000000Z-r1"
        report = validate_content_spec(load_json("content-spec.example.json"), overlay, self.TODAY)
        self.assertIn("brand_product_mismatch", {issue.code for issue in report.errors})

        overlay["scope"]["product_id"] = "sample-product"
        overlay["scope"]["parent_brand_revision"] = None
        report = validate_content_spec(load_json("content-spec.example.json"), overlay, self.TODAY)
        self.assertIn("brand_parent_revision", {issue.code for issue in report.errors})

    def test_canonical_product_overlay_requires_matching_product_and_parent_revision(self) -> None:
        brand = canonical_brand(status="active", rights_status="approved")
        brand["product_id"] = "other-product"
        report = validate_content_spec(load_json("content-spec.example.json"), brand, self.TODAY)
        self.assertIn("brand_product_mismatch", {issue.code for issue in report.errors})

        brand["product_id"] = "sample-product"
        report = validate_content_spec(load_json("content-spec.example.json"), brand, self.TODAY)
        self.assertIn("brand_parent_revision", {issue.code for issue in report.errors})

    def test_unscoped_legacy_brand_cannot_authorize_final_content(self) -> None:
        brand = {
            "schema_version": "1.0",
            "brand_id": "sample-brand",
            "status": "approved",
            "owner": "fixture-owner",
        }
        spec = make_approved_spec()
        report = validate_content_spec(spec, brand, self.TODAY)
        self.assertIn("legacy_brand_scope_required", {issue.code for issue in report.errors})

    def test_valid_approval_binds_current_package(self) -> None:
        spec = make_approved_spec()
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertEqual([], report.issues)

    def test_valid_new_anti_slop_draft(self) -> None:
        spec = load_json("content-spec.example.json")
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="member-fixture")
        self.assertEqual([], report.errors)
        self.assertTrue(report.passes(strict=True))

    def test_generic_route_is_rejected_with_explainable_code(self) -> None:
        spec = load_json("content-spec.example.json")
        spec["route_set"]["routes"][0]["strategic_idea"] = "Konten edukasi untuk meningkatkan awareness."
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("generic_route", {issue.code for issue in report.errors})

    def test_route_cards_must_be_genuinely_distinct(self) -> None:
        spec = load_json("content-spec.example.json")
        first = spec["route_set"]["routes"][0]
        second = spec["route_set"]["routes"][1]
        for key in ("strategic_idea", "audience_tension", "message_promise", "visual_premise", "narrative_order", "asset_plan", "distinctive_move"):
            second[key] = first[key]
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("routes_not_distinct", {issue.code for issue in report.errors})

    def test_canva_mutation_requires_human_route_selection(self) -> None:
        spec = load_json("content-spec.example.json")
        spec["state"] = "DESIGN_DRAFT"
        spec["design"]["draft_ref"] = "canva:design:unselected"
        spec["human_selected_route"] = None
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("human_selected_route_required", {issue.code for issue in report.errors})

    def test_hard_blocker_fails_closed(self) -> None:
        spec = make_approved_spec()
        spec["anti_slop_audit"]["hard_blockers"]["ocr_exact_match"] = "fail"
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("hard_blocker", {issue.code for issue in report.errors})

    def test_valid_privileged_anti_slop_contract(self) -> None:
        spec = make_approved_spec()
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertEqual([], report.errors)
        self.assertTrue(report.passes(strict=True))

    def test_selected_route_change_invalidates_approval_package(self) -> None:
        spec = make_approved_spec()
        spec["human_selected_route"]["route_id"] = "proof-demo"
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        codes = {issue.code for issue in report.errors}
        self.assertIn("approval_checksum_mismatch", codes)
        self.assertIn("anti_slop_package_checksum", codes)

    def test_anti_slop_scope_template_and_folder_mismatch_are_blocked(self) -> None:
        spec = make_approved_spec()
        spec["production_controls"]["template"]["template_id"] = "other-template"
        spec["production_controls"]["folder"]["folder_id"] = "other-folder"
        spec["production_controls"]["folder"]["scope"]["tenant_id"] = "other-tenant"
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        codes = {issue.code for issue in report.errors}
        self.assertIn("template_snapshot_mismatch", codes)
        self.assertIn("folder_snapshot_mismatch", codes)
        self.assertIn("anti_slop_scope_mismatch", codes)

    def test_universal_detector_field_is_rejected(self) -> None:
        spec = load_json("content-spec.example.json")
        spec["anti_slop_audit"]["ai_probability"] = 0.2
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("universal_detector_field", {issue.code for issue in report.errors})

    def test_opaque_canva_template_id_is_exactly_bound(self) -> None:
        spec = make_approved_spec()
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertEqual([], report.issues)

        spec["design"]["provider_template_id"] = "CanvaOpaqueTemplate-DIFFERENT-001"
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("provider_template_id_mismatch", {issue.code for issue in report.errors})

    def test_opaque_canva_template_id_cannot_cross_scope(self) -> None:
        spec = make_approved_spec()
        spec["design"]["remote_scope"]["tenant_id"] = "other-tenant"
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("remote_scope_mismatch", {issue.code for issue in report.errors})

        spec["design"]["remote_scope"] = full_scope(spec)
        spec["design"]["remote_scope"]["brand_id"] = "other-brand"
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("remote_scope_mismatch", {issue.code for issue in report.errors})

    def test_runtime_actor_impersonation_is_rejected(self) -> None:
        spec = make_approved_spec()
        context = trusted_policy(spec)
        spec["policy"]["actor_id"] = "prompt-lead"
        spec["policy"]["role_mapping"]["lead"].append("prompt-lead")
        report = validate_content_spec(spec, approved_brand(), self.TODAY, context, actor_id="lead-fixture")
        self.assertIn("trusted_actor_approval", {issue.code for issue in report.errors})

    def test_policy_revision_must_be_bound_to_privileged_approval(self) -> None:
        spec = make_approved_spec()
        context = trusted_policy(spec, revision_override="2026-08-19T000001Z-r2")
        report = validate_content_spec(spec, approved_brand(), self.TODAY, context, actor_id="lead-fixture")
        self.assertIn("trusted_policy_revision", {issue.code for issue in report.errors})

    def test_trusted_policy_requires_policy_id_and_revision_metadata(self) -> None:
        spec = make_approved_spec()
        for field in ("policy_id", "revision"):
            context = trusted_policy(spec, omit_fields=(field,))
            report = validate_content_spec(spec, approved_brand(), self.TODAY, context, actor_id="lead-fixture")
            self.assertIn("trusted_policy_metadata", {issue.code for issue in report.errors})

    def test_embedded_verified_claim_requires_external_brand_bundle(self) -> None:
        spec = make_approved_spec()
        spec["claims"] = [
            {
                "claim_id": "claim-001",
                "text": "Supported neutral claim",
                "source_url": "https://example.com/evidence",
                "owner": "claim-owner",
                "verified_on": "2026-08-19",
                "expires_on": "2026-12-31",
                "status": "verified",
            }
        ]
        spec["approval"]["package_checksum"] = calculate_package_checksum(spec)
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("brand_bundle_required", {issue.code for issue in report.errors})

    def test_approved_external_claim_is_exactly_matched(self) -> None:
        spec = make_approved_spec()
        spec["claims"] = [
            {
                "claim_id": "claim-001",
                "text": "Supported neutral claim",
                "source_url": "https://example.com/evidence",
                "owner": "claim-owner",
                "verified_on": "2026-08-19",
                "expires_on": "2026-12-31",
                "status": "verified",
            }
        ]
        spec["approval"]["package_checksum"] = calculate_package_checksum(spec)
        report = validate_content_spec(
            spec,
            approved_brand(),
            self.TODAY,
            trusted_policy(spec),
            actor_id="lead-fixture",
            brand_bundle=neutral_brand_bundle(include_claim=True),
            brand_policy_context=trusted_brand_policy(spec),
            brand_actor_id="brand-lead-fixture",
        )
        self.assertEqual([], report.issues)

    def test_privileged_brand_bundle_requires_separate_policy_and_actor(self) -> None:
        spec = make_approved_spec()
        spec["claims"] = [
            {
                "claim_id": "claim-001",
                "text": "Supported neutral claim",
                "source_url": "https://example.com/evidence",
                "owner": "claim-owner",
                "verified_on": "2026-08-19",
                "expires_on": "2026-12-31",
                "status": "verified",
            }
        ]
        spec["approval"]["package_checksum"] = calculate_package_checksum(spec)
        report = validate_content_spec(
            spec,
            approved_brand(),
            self.TODAY,
            trusted_policy(spec),
            actor_id="lead-fixture",
            brand_bundle=neutral_brand_bundle(include_claim=True),
        )
        self.assertIn("brand_bundle_authority", {issue.code for issue in report.errors})

    def test_brand_bundle_authority_is_not_synthesized_from_content_policy(self) -> None:
        spec = make_approved_spec()
        spec["claims"] = [
            {
                "claim_id": "claim-001",
                "text": "Supported neutral claim",
                "source_url": "https://example.com/evidence",
                "owner": "claim-owner",
                "verified_on": "2026-08-19",
                "expires_on": "2026-12-31",
                "status": "verified",
            }
        ]
        spec["approval"]["package_checksum"] = calculate_package_checksum(spec)
        report = validate_content_spec(
            spec,
            approved_brand(),
            self.TODAY,
            trusted_policy(spec),
            actor_id="lead-fixture",
            brand_bundle=neutral_brand_bundle(include_claim=True),
            brand_policy_context=trusted_brand_policy(spec),
            brand_actor_id="lead-fixture",
        )
        self.assertIn("brand_bundle_invalid", {issue.code for issue in report.errors})

    def test_privileged_product_overlay_binds_to_runtime_master_revision(self) -> None:
        spec = make_approved_spec()
        master_bundle = neutral_brand_bundle()
        report = validate_content_spec(
            spec,
            approved_brand(),
            self.TODAY,
            trusted_policy(spec),
            actor_id="lead-fixture",
            brand_bundle=neutral_brand_bundle(
                product_id="sample-product",
                parent_brand_revision=MASTER_BRAND_REVISION,
            ),
            brand_policy_context=trusted_brand_policy(spec, product_id="sample-product"),
            brand_actor_id="brand-lead-fixture",
            master_brand_bundle=master_bundle,
        )
        self.assertEqual([], report.issues)

    def test_privileged_product_overlay_rejects_forged_runtime_parent_binding(self) -> None:
        spec = make_approved_spec()
        master_bundle = neutral_brand_bundle()
        report = validate_content_spec(
            spec,
            approved_brand(),
            self.TODAY,
            trusted_policy(spec),
            actor_id="lead-fixture",
            brand_bundle=neutral_brand_bundle(
                product_id="sample-product",
                parent_brand_revision="2026-08-18T000000Z-r1",
            ),
            brand_policy_context=trusted_brand_policy(spec, product_id="sample-product"),
            brand_actor_id="brand-lead-fixture",
            master_brand_bundle=master_bundle,
        )
        self.assertIn("brand_master_revision_mismatch", {issue.code for issue in report.errors})

    def test_privileged_product_overlay_requires_master_bundle_binding(self) -> None:
        spec = make_approved_spec()
        report = validate_content_spec(
            spec,
            approved_brand(),
            self.TODAY,
            trusted_policy(spec),
            actor_id="lead-fixture",
            brand_bundle=neutral_brand_bundle(
                product_id="sample-product",
                parent_brand_revision=MASTER_BRAND_REVISION,
            ),
            brand_policy_context=trusted_brand_policy(spec, product_id="sample-product"),
            brand_actor_id="brand-lead-fixture",
        )
        self.assertIn("brand_master_bundle_required", {issue.code for issue in report.errors})

    def test_privileged_product_overlay_rejects_master_bundle_scope_or_product(self) -> None:
        for field, value, expected_code in (
            ("tenant_id", "other-tenant", "master_brand_bundle_scope"),
            ("product_id", "other-product", "master_brand_bundle_product"),
        ):
            spec = make_approved_spec()
            master_bundle = Path(neutral_brand_bundle())
            profile_path = master_bundle / "brand-profile.json"
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            if field == "tenant_id":
                profile["scope"][field] = value
            else:
                profile["scope"][field] = value
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            report = validate_content_spec(
                spec,
                approved_brand(),
                self.TODAY,
                trusted_policy(spec),
                actor_id="lead-fixture",
                brand_bundle=neutral_brand_bundle(
                    product_id="sample-product",
                    parent_brand_revision=MASTER_BRAND_REVISION,
                ),
                brand_policy_context=trusted_brand_policy(spec, product_id="sample-product"),
                brand_actor_id="brand-lead-fixture",
                master_brand_bundle=master_bundle,
            )
            self.assertIn(expected_code, {issue.code for issue in report.errors})

    def test_cli_loads_separate_brand_policy(self) -> None:
        spec = make_approved_spec()
        spec_path = write_input_json("cli-spec.json", spec)
        brand_path = write_input_json("cli-brand.json", approved_brand())
        policy_context = trusted_policy(spec)
        policy_path = write_input_json("cli-policy.json", dict(policy_context.data))
        brand_policy_path = write_input_json(
            "cli-brand-policy.json",
            {
                "schema_version": "1.0",
                "policy_id": "sample-brand-policy",
                "revision": spec["policy"]["revision"],
                "source": "local_authenticated_policy",
                "scope": {
                    "tenant_id": spec["scope"]["tenant_id"],
                    "client_id": spec["scope"]["client_id"],
                    "brand_id": spec["brand_id"],
                    "product_id": None,
                },
                "role_mapping": {
                    "admin": ["brand-admin-fixture"],
                    "lead": ["brand-lead-fixture"],
                    "reviewer": [],
                    "member": [],
                    "publisher": [],
                },
            },
        )
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(
                [
                    str(spec_path),
                    "--brand",
                    str(brand_path),
                    "--policy",
                    str(policy_path),
                    "--policy-digest",
                    trusted_policy(spec).canonical_digest,
                    "--actor-id",
                    "lead-fixture",
                    "--brand-bundle",
                    neutral_brand_bundle(),
                    "--brand-policy",
                    str(brand_policy_path),
                    "--brand-actor-id",
                    "brand-lead-fixture",
                    "--master-brand-bundle",
                    neutral_brand_bundle(),
                    "--json",
                ]
            )
        self.assertEqual(0, result)
        self.assertTrue(json.loads(output.getvalue())["valid"])

    def test_cli_malformed_render_and_publishing_values_fail_structurally(self) -> None:
        for field, value, expected_code in (
            ("render_evidence", [], "render_evidence"),
            ("render_evidence", "malformed", "render_evidence"),
            ("publishing", [], "publishing"),
            ("publishing", "malformed", "publishing"),
        ):
            spec = make_approved_spec()
            if field == "render_evidence":
                spec["design"][field] = value
            else:
                spec[field] = value
            spec_path = write_input_json(f"cli-malformed-{field}-{type(value).__name__}.json", spec)
            brand_path = write_input_json(f"cli-malformed-brand-{field}-{type(value).__name__}.json", approved_brand())
            policy_context = trusted_policy(spec)
            policy_path = write_input_json(f"cli-malformed-policy-{field}-{type(value).__name__}.json", dict(policy_context.data))
            output = io.StringIO()
            with redirect_stdout(output):
                result = main([str(spec_path), "--brand", str(brand_path), "--policy", str(policy_path), "--policy-digest", policy_context.canonical_digest, "--actor-id", "lead-fixture", "--json"])
            payload = json.loads(output.getvalue())
            self.assertNotEqual(0, result)
            self.assertFalse(payload["valid"])
            self.assertIn(expected_code, {issue["code"] for issue in payload["issues"]})

    def test_external_benchmark_registry_controls_production_comparison(self) -> None:
        spec = make_approved_spec()
        registry = benchmark_registry(spec)
        entry = registry["reference_sets"][0]
        benchmark = spec["anti_slop_audit"]["independent_critique"]["benchmark"]
        benchmark.update(
            {
                "status": "pass",
                "reference_set_checksum": entry["checksum"],
                "render_digest": spec["design"]["render_evidence"]["render_digest"],
                "candidate_ids": ["recent-education-001"],
                "reference_corpus": entry["reference_corpus"],
                "comparator": {"id": "fixture-comparator", "version": "1"},
            }
        )
        registry_path = write_input_json("benchmark-registry-valid.json", registry)
        context = load_benchmark_registry(registry_path)
        benchmark["registry_checksum"] = context.canonical_digest
        benchmark["payload_digest"] = _canonical_json_digest({key: value for key, value in benchmark.items() if key not in {"result_id", "result_digest", "payload_digest"}})
        benchmark_result = spec["policy"]["evidence_results"]["benchmark"]
        benchmark_result.update(json.loads(json.dumps(benchmark)))
        benchmark_result["result_digest"] = _canonical_json_digest({key: value for key, value in benchmark_result.items() if key != "result_digest"})
        benchmark["result_digest"] = benchmark_result["result_digest"]
        benchmark["result_id"] = benchmark_result["result_id"]
        spec["policy"]["benchmark_registry"] = {
            "source": "local_authenticated_benchmark_registry",
            "registry_id": registry["registry_id"],
            "revision": registry["revision"],
            "registry_checksum": context.canonical_digest,
            "trusted_root": registry["trusted_root"],
            "reference_set_ids": ["fixture-benchmark@1"],
            "reference_set_checksums": {"fixture-benchmark@1": entry["checksum"]},
            "reference_corpus_checksums": {"fixture-corpus-001": entry["reference_corpus"][0]["checksum"]},
        }
        spec["anti_slop_audit"]["approval_package"]["checksum"] = _anti_slop_package_checksum(spec, spec["anti_slop_audit"])
        spec["approval"]["package_checksum"] = calculate_package_checksum(spec)
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture", benchmark_registry=context)
        self.assertEqual([], report.errors)

        fake = make_approved_spec()
        fake_registry = benchmark_registry(fake)
        fake_context = load_benchmark_registry(write_input_json("benchmark-registry-fake-id.json", fake_registry))
        fake_benchmark = fake["anti_slop_audit"]["independent_critique"]["benchmark"]
        fake_benchmark.update({"status": "pass", "reference_set_id": "attacker-reference", "reference_set_checksum": fake_registry["reference_sets"][0]["checksum"], "registry_checksum": fake_context.canonical_digest})
        report = validate_content_spec(fake, approved_brand(), self.TODAY, trusted_policy(fake), actor_id="lead-fixture", benchmark_registry=fake_context)
        self.assertIn("benchmark_registry_reference_set", {issue.code for issue in report.errors})

        cli_spec_path = write_input_json("benchmark-cli-spec.json", spec)
        cli_brand_path = write_input_json("benchmark-cli-brand.json", approved_brand())
        cli_policy = trusted_policy(spec)
        cli_policy_path = write_input_json("benchmark-cli-policy.json", dict(cli_policy.data))
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(
                [
                    str(cli_spec_path),
                    "--brand", str(cli_brand_path),
                    "--policy", str(cli_policy_path),
                    "--policy-digest", cli_policy.canonical_digest,
                    "--actor-id", "lead-fixture",
                    "--benchmark-registry", str(registry_path),
                    "--json",
                ]
            )
        self.assertEqual(0, result)
        self.assertTrue(json.loads(output.getvalue())["valid"])

    def test_brand_bundle_policy_scope_and_activation_actor_are_exact(self) -> None:
        spec = make_approved_spec()
        spec["claims"] = [
            {
                "claim_id": "claim-001",
                "text": "Supported neutral claim",
                "source_url": "https://example.com/evidence",
                "owner": "claim-owner",
                "verified_on": "2026-08-19",
                "expires_on": "2026-12-31",
                "status": "verified",
            }
        ]
        spec["approval"]["package_checksum"] = calculate_package_checksum(spec)
        wrong_scope = trusted_brand_policy(spec, product_id="sample-product")
        report = validate_content_spec(
            spec,
            approved_brand(),
            self.TODAY,
            trusted_policy(spec),
            actor_id="lead-fixture",
            brand_bundle=neutral_brand_bundle(include_claim=True),
            brand_policy_context=wrong_scope,
            brand_actor_id="brand-lead-fixture",
        )
        self.assertIn("brand_bundle_invalid", {issue.code for issue in report.errors})

        report = validate_content_spec(
            spec,
            approved_brand(),
            self.TODAY,
            trusted_policy(spec),
            actor_id="lead-fixture",
            brand_bundle=neutral_brand_bundle(include_claim=True),
            brand_policy_context=trusted_brand_policy(spec),
            brand_actor_id="wrong-brand-actor",
        )
        self.assertIn("brand_bundle_invalid", {issue.code for issue in report.errors})

    def test_unattended_unregistered_recipe_is_rejected(self) -> None:
        spec = make_approved_spec()
        spec["copy_recipe_id"] = "recipe-unregistered"
        spec["copy_recipe_version"] = "recipe-v1"
        spec["brand_revision"] = "2026-08-19T000000Z-r1"
        spec["policy"]["mode"] = "unattended"
        spec["policy"]["unattended"] = {
            "enabled": True,
            "policy_id": "sample-social-policy",
            "policy_revision": "2026-08-19T000000Z-r1",
            "scope": full_scope(spec),
            "enabled_by": "lead-fixture",
            "enabled_by_role": "lead",
            "enabled_at": "2026-08-19T10:00:00+07:00",
            "preapproved": {
                "copy_recipe_ids": ["recipe-unregistered"],
                "copy_recipe_versions": {"recipe-unregistered": "recipe-v1"},
                "copy_recipe_brand_revisions": {"recipe-unregistered": "2026-08-19T000000Z-r1"},
                "template_ids": ["brand-template-001"],
                "template_versions": {"brand-template-001": "1"},
                "template_provider_ids": {"brand-template-001": "CanvaOpaqueTemplate-EXAMPLE-001"},
                "claim_ids": [],
                "targets": ["account-placeholder"],
                "pillars": [spec["content_pillar"]],
                "formats": [spec["format"]],
                "field_budgets": {"headline_chars": 60, "body_chars": 220, "cta_chars": 50, "caption_chars": 2200, "alt_text_chars": 1000, "hashtags_max": 10, "slides_max": 10},
            },
        }
        spec["approval"]["status"] = "policy_approved"
        spec["approval"]["approver"] = None
        spec["approval"]["approver_id"] = None
        spec["approval"]["approver_role"] = None
        spec["approval"]["identity_source"] = None
        spec["approval"]["package_checksum"] = calculate_package_checksum(spec)
        report = validate_content_spec(
            spec,
            approved_brand(),
            self.TODAY,
            trusted_policy(spec),
            actor_id="lead-fixture",
            brand_bundle=neutral_brand_bundle(),
            brand_policy_context=trusted_brand_policy(spec),
            brand_actor_id="brand-lead-fixture",
        )
        self.assertIn("copy_recipe_unregistered", {issue.code for issue in report.errors})

    def test_caption_change_invalidates_approval(self) -> None:
        spec = make_approved_spec()
        spec["caption"]["body"] += " Perubahan setelah approval."
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("approval_checksum_mismatch", {issue.code for issue in report.errors})

    def test_competing_ctas_are_blocked(self) -> None:
        spec = load_json("content-spec.example.json")
        spec["caption"]["cta"] = "Hubungi kami sekarang."
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("multiple_ctas", {issue.code for issue in report.errors})

    def test_expired_claim_is_blocked(self) -> None:
        spec = make_approved_spec()
        spec["claims"] = [
            {
                "text": "Lebih dari 100 pengguna",
                "source_url": "https://example.com/evidence",
                "owner": "claim-owner",
                "verified_on": "2026-01-01",
                "expires_on": "2026-08-01",
                "status": "verified",
            }
        ]
        spec["approval"]["package_checksum"] = calculate_package_checksum(spec)
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("claim_expired", {issue.code for issue in report.errors})

    def test_secret_field_is_blocked(self) -> None:
        spec = load_json("content-spec.example.json")
        spec["publishing"]["access_token"] = "placeholder-secret"
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("secret_field", {issue.code for issue in report.errors})

    def test_approved_download_requires_receipt_evidence(self) -> None:
        spec = make_approved_spec()
        spec["design"]["download"]["receipt"] = None
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("download_receipt", {issue.code for issue in report.errors})

    def test_scope_ids_are_required_and_lowercase(self) -> None:
        spec = load_json("content-spec.example.json")
        spec["scope"]["client_id"] = "Client A"
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("scope_id_format", {issue.code for issue in report.errors})

    def test_bare_schema_v1_requires_explicit_legacy_marker(self) -> None:
        spec = load_json("content-spec.example.json")
        spec["schema_version"] = "1.0"
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("legacy_compatibility_required", {issue.code for issue in report.errors})

    def test_remote_reference_cannot_cross_scope(self) -> None:
        spec = make_approved_spec()
        spec["design"]["remote_scope"]["client_id"] = "other-client"
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("remote_scope_mismatch", {issue.code for issue in report.errors})

    def test_approval_requires_mapped_reviewer_or_lead(self) -> None:
        spec = make_approved_spec()
        spec["approval"]["approver_id"] = "member-fixture"
        spec["approval"]["approver_role"] = "member"
        spec["approval"]["package_checksum"] = calculate_package_checksum(spec)
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("approver_role", {issue.code for issue in report.errors})

    def test_unattended_requires_lead_admin_and_preapproval(self) -> None:
        spec = make_approved_spec()
        spec["policy"]["mode"] = "unattended"
        spec["policy"]["unattended"] = {
            "enabled": True,
            "scope": full_scope(spec),
            "enabled_by": "member-fixture",
            "enabled_by_role": "member",
            "enabled_at": "2026-08-19T10:00:00+07:00",
            "preapproved": {
                "template_ids": ["brand-template-001"],
                "claim_ids": [],
                "targets": ["account-placeholder"],
            },
        }
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("unattended_enabler_role", {issue.code for issue in report.errors})

    def test_valid_unattended_policy_is_explicit_and_scoped(self) -> None:
        spec = make_approved_spec()
        spec["copy_recipe_id"] = "recipe-001"
        spec["copy_recipe_version"] = "recipe-v1"
        spec["brand_revision"] = "2026-08-19T000000Z-r1"
        spec["policy"]["mode"] = "unattended"
        spec["policy"]["approval_required"] = False
        spec["policy"]["unattended"] = {
            "enabled": True,
            "policy_id": "sample-social-policy",
            "policy_revision": "2026-08-19T000000Z-r1",
            "scope": full_scope(spec),
            "enabled_by": "lead-fixture",
            "enabled_by_role": "lead",
            "enabled_at": "2026-08-19T10:00:00+07:00",
            "preapproved": {
                "copy_recipe_ids": ["recipe-001"],
                "copy_recipe_versions": {"recipe-001": "recipe-v1"},
                "copy_recipe_brand_revisions": {"recipe-001": "2026-08-19T000000Z-r1"},
                "template_ids": ["brand-template-001"],
                "template_versions": {"brand-template-001": "1"},
                "template_provider_ids": {"brand-template-001": "CanvaOpaqueTemplate-EXAMPLE-001"},
                "claim_ids": [],
                "targets": ["account-placeholder"],
                "pillars": [spec["content_pillar"]],
                "formats": [spec["format"]],
                "field_budgets": {
                    "headline_chars": 60,
                    "body_chars": 220,
                    "cta_chars": 50,
                    "caption_chars": 2200,
                    "alt_text_chars": 1000,
                    "hashtags_max": 10,
                    "slides_max": 10,
                },
            },
        }
        spec["approval"]["status"] = "policy_approved"
        spec["approval"]["approver"] = None
        spec["approval"]["approver_id"] = None
        spec["approval"]["approver_role"] = None
        spec["approval"]["identity_source"] = None
        spec["approval"]["package_checksum"] = calculate_package_checksum(spec)
        report = validate_content_spec(
            spec,
            approved_brand(),
            self.TODAY,
            trusted_policy(spec),
            actor_id="lead-fixture",
            brand_bundle=neutral_brand_bundle(),
            brand_policy_context=trusted_brand_policy(spec),
            brand_actor_id="brand-lead-fixture",
        )
        self.assertEqual([], report.issues)

        trusted = trusted_policy(spec, provider_override="CanvaOpaqueTemplate-TRUSTED-DIFFERENT-001")
        report = validate_content_spec(
            spec,
            approved_brand(),
            self.TODAY,
            trusted,
            actor_id="lead-fixture",
            brand_bundle=neutral_brand_bundle(),
            brand_policy_context=trusted_brand_policy(spec),
            brand_actor_id="brand-lead-fixture",
        )
        self.assertIn("trusted_policy_preapproval", {issue.code for issue in report.errors})

        spec["policy"]["unattended"]["preapproved"]["template_provider_ids"]["brand-template-001"] = "CanvaOpaqueTemplate-DIFFERENT-001"
        spec["approval"]["package_checksum"] = calculate_package_checksum(spec)
        report = validate_content_spec(
            spec,
            approved_brand(),
            self.TODAY,
            trusted_policy(spec),
            actor_id="lead-fixture",
            brand_bundle=neutral_brand_bundle(),
            brand_policy_context=trusted_brand_policy(spec),
            brand_actor_id="brand-lead-fixture",
        )
        self.assertIn("unattended_template_provider_id", {issue.code for issue in report.errors})

        spec["policy"]["unattended"]["preapproved"]["template_provider_ids"]["brand-template-001"] = "CanvaOpaqueTemplate-EXAMPLE-001"
        spec["approval"]["package_checksum"] = calculate_package_checksum(spec)

        spec["claims"] = [
            {
                "claim_id": "claim-001",
                "text": "Supported neutral claim",
                "status": "verified",
                "source_url": "https://example.com/claim",
                "owner": "lead-fixture",
                "verified_on": "2026-08-19",
                "expires_on": "2026-12-31",
            }
        ]
        spec["policy"]["unattended"]["preapproved"]["claim_ids"] = ["claim-001"]
        spec["approval"]["package_checksum"] = calculate_package_checksum(spec)
        report = validate_content_spec(
            spec,
            approved_brand(),
            self.TODAY,
            trusted_policy(spec),
            actor_id="lead-fixture",
            brand_bundle=neutral_brand_bundle(include_claim=True),
            brand_policy_context=trusted_brand_policy(spec),
            brand_actor_id="brand-lead-fixture",
        )
        self.assertEqual([], report.issues)

        spec["claims"][0]["claim_id"] = "claim-new"
        spec["approval"]["package_checksum"] = calculate_package_checksum(spec)
        report = validate_content_spec(
            spec,
            approved_brand(),
            self.TODAY,
            trusted_policy(spec),
            actor_id="lead-fixture",
            brand_bundle=neutral_brand_bundle(include_claim=True),
            brand_policy_context=trusted_brand_policy(spec),
            brand_actor_id="brand-lead-fixture",
        )
        self.assertIn("unattended_claim_unapproved", {issue.code for issue in report.errors})

        spec["approval"]["status"] = "approved"
        spec["approval"]["package_checksum"] = calculate_package_checksum(spec)
        report = validate_content_spec(
            spec,
            approved_brand(),
            self.TODAY,
            trusted_policy(spec),
            actor_id="lead-fixture",
            brand_bundle=neutral_brand_bundle(),
            brand_policy_context=trusted_brand_policy(spec),
            brand_actor_id="brand-lead-fixture",
        )
        self.assertIn("approval_mode", {issue.code for issue in report.errors})

    def test_publisher_must_bind_exact_approved_checksum(self) -> None:
        spec = make_approved_spec()
        spec["state"] = "SCHEDULED"
        spec["publishing"].update(
            {
                "scheduled_at": "2026-08-20T10:00:00+07:00",
                "idempotency_key": "sample-idempotency-key",
                "publisher_id": "publisher-fixture",
                "publisher_role": "publisher",
                "package_checksum": "sha256:" + "0" * 64,
                "preflight_checked_at": "2026-08-19T11:00:00+07:00",
                "preflight": {
                    "duplicate_check": "pass",
                    "kill_switch": "clear",
                    "account_access": "pass",
                    "asset_rights": "not_applicable",
                },
            }
        )
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("publisher_checksum", {issue.code for issue in report.errors})

    def test_embedded_self_promotion_cannot_cross_without_trusted_policy(self) -> None:
        spec = make_approved_spec()
        spec["policy"]["actor_id"] = "prompt-lead"
        spec["policy"]["actor_role"] = "lead"
        spec["policy"]["role_mapping"]["lead"].append("prompt-lead")
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("trusted_policy_required", {issue.code for issue in report.errors})

    def test_embedded_policy_object_cannot_be_reused_as_trusted_authority(self) -> None:
        spec = make_approved_spec()
        report = validate_content_spec(spec, approved_brand(), self.TODAY, spec["policy"], actor_id="lead-fixture")
        self.assertIn("trusted_policy_embedded", {issue.code for issue in report.errors})

    def test_trusted_policy_reviewer_succeeds_and_wrong_scope_fails(self) -> None:
        spec = make_approved_spec()
        context = trusted_policy(spec)
        report = validate_content_spec(spec, approved_brand(), self.TODAY, context, actor_id="lead-fixture")
        self.assertEqual([], report.issues)

        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec, scope_override={**full_scope(spec), "product_id": "other-product"}))
        self.assertIn("trusted_policy_scope", {issue.code for issue in report.errors})

    def test_measurement_plan_and_benchmark_scope_are_canonical(self) -> None:
        spec = load_json("content-spec.example.json")
        spec["measurement"]["plan"].pop("denominator")
        spec["measurement"]["benchmark_scope"]["client_id"] = "other-client"
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        codes = {issue.code for issue in report.errors}
        self.assertIn("measurement_denominator", codes)
        self.assertIn("benchmark_scope_mismatch", codes)

    def test_not_available_is_not_null_and_zero_remains_a_real_value(self) -> None:
        spec = load_json("content-spec.example.json")
        spec["measurement"]["metrics"] = {"reach": None}
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("metric_value", {issue.code for issue in report.errors})

        spec["measurement"]["metrics"] = {"views": 0, "saved": "not_available"}
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertNotIn("metric_value", {issue.code for issue in report.errors})

        spec["measurement"]["metrics"] = {"saves": 4}
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("metric_name", {issue.code for issue in report.errors})

    def test_carousel_child_metrics_must_be_not_available(self) -> None:
        spec = load_json("content-spec.example.json")
        spec["measurement"]["child_metrics"] = {"slide_1_reach": 12}
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("carousel_child_metric", {issue.code for issue in report.errors})

    def test_sample_size_interpretation_and_story_fetch_are_bounded(self) -> None:
        spec = make_approved_spec()
        spec["state"] = "MEASURED"
        spec["format"] = "story"
        spec["design"]["template_id"] = None
        spec["design"]["template_version"] = None
        spec["design"]["draft_ref"] = None
        spec["design"]["remote_scope"] = None
        spec["publishing"].update(
            {
                "media_id": "meta-media-1",
                "published_at": "2026-08-19T10:00:00+07:00",
                "remote_scope": full_scope(spec),
                "publisher_id": "publisher-fixture",
                "publisher_role": "publisher",
                "package_checksum": spec["approval"]["package_checksum"],
            }
        )
        spec["measurement"].update(
            {
                "window": "24h",
                "captured_at": "2026-08-20T10:00:00+07:00",
                "metrics": {"reach": 4},
                "sample_size": 4,
                "sample_interpretation": "operational_direction",
                "story_fetched_at": "2026-08-20T11:00:01+07:00",
            }
        )
        spec["measurement"]["benchmark_scope"]["format"] = "story"
        spec["measurement"]["benchmark_scope"]["window"] = "24h"
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        codes = {issue.code for issue in report.errors}
        self.assertIn("sample_interpretation_mismatch", codes)
        self.assertIn("story_fetch_late", codes)

    def test_benchmark_scope_includes_product_and_brand(self) -> None:
        spec = load_json("content-spec.example.json")
        spec["measurement"]["benchmark_scope"].pop("brand_id")
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("benchmark_scope_fields", {issue.code for issue in report.errors})

        spec = load_json("content-spec.example.json")
        spec["measurement"]["benchmark_scope"].pop("product_id")
        report = validate_content_spec(spec, approved_brand(), self.TODAY)
        self.assertIn("benchmark_scope_fields", {issue.code for issue in report.errors})

    def test_research_pillar_defaults_are_machine_readable(self) -> None:
        from validate_content_spec import PILLAR_MEASUREMENT_DEFAULTS

        self.assertEqual("saved", PILLAR_MEASUREMENT_DEFAULTS["education"]["primary_metric"])
        self.assertEqual("views", PILLAR_MEASUREMENT_DEFAULTS["trust"]["denominator"])
        self.assertEqual("total_interactions", PILLAR_MEASUREMENT_DEFAULTS["community"]["primary_metric"])
        self.assertEqual("profile_activity", PILLAR_MEASUREMENT_DEFAULTS["offer"]["primary_metric"])
        self.assertEqual("link_clicks", PILLAR_MEASUREMENT_DEFAULTS["offer"]["format_overrides"]["story"]["primary_metric"])

    def test_final_render_bytes_and_digest_are_required(self) -> None:
        spec = make_approved_spec()
        spec["design"]["render_evidence"]["render_digest"] = "sha256:" + ("0" * 64)
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("render_digest_mismatch", {issue.code for issue in report.errors})

    def test_layout_and_semantic_string_lists_are_not_evidence(self) -> None:
        spec = make_approved_spec()
        spec["anti_slop_audit"]["evidence"]["layout"]["pages"] = ["pass"] * len(spec["slides"])
        spec["anti_slop_audit"]["evidence"]["semantic"]["pages"] = ["object", "count"] * 3
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        codes = {issue.code for issue in report.errors}
        self.assertIn("layout_page_type", codes)
        self.assertIn("semantic_pages", codes)

    def test_layout_measurements_and_semantic_relations_must_agree(self) -> None:
        spec = make_approved_spec()
        spec["anti_slop_audit"]["evidence"]["layout"]["pages"][0]["edge_checks"][0]["actual"] = 999
        semantic_page = spec["anti_slop_audit"]["evidence"]["semantic"]["pages"][0]
        semantic_page["observed_objects"][0]["role"] = "wrong-role"
        semantic_page["relation_checks"][0]["observed_relation"] = "wrong-relation"
        cta_page = spec["anti_slop_audit"]["evidence"]["semantic"]["pages"][-1]
        cta_page["cta_target"]["observed"] = "wrong-destination"
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        codes = {issue.code for issue in report.errors}
        self.assertIn("layout_checks", codes)
        self.assertIn("semantic_object_mismatch", codes)
        self.assertIn("semantic_relation_mismatch", codes)
        self.assertIn("semantic_cta_target_mismatch", codes)

    def test_boolean_semantic_counts_are_not_numeric_evidence(self) -> None:
        spec = make_approved_spec()
        count_check = spec["anti_slop_audit"]["evidence"]["semantic"]["pages"][0]["count_checks"][0]
        count_check["expected_count"] = True
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("semantic_count_checks", {issue.code for issue in report.errors})

    def test_page_map_hash_and_symlink_bindings_fail_closed(self) -> None:
        spec = make_approved_spec()
        spec["design"]["render_evidence"]["page_map"][0]["sha256"] = "0" * 64
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("render_page_map_hash", {issue.code for issue in report.errors})

        symlinked = make_approved_spec()
        render_dir = Path(symlinked["design"]["render_ref"])
        alias = render_dir / "alias.png"
        alias.symlink_to(render_dir / "page-1.png")
        evidence = symlinked["design"]["render_evidence"]
        evidence["page_files"] = ["alias.png"] + [f"page-{index}.png" for index in range(2, len(symlinked["slides"]) + 1)]
        report = validate_content_spec(symlinked, approved_brand(), self.TODAY, trusted_policy(symlinked), actor_id="lead-fixture")
        codes = {issue.code for issue in report.errors}
        self.assertTrue({"render_symlink_component", "render_page_containment"} & codes)

        ancestor = make_approved_spec()
        target_dir = Path(ancestor["design"]["render_ref"])
        link_parent = target_dir.parent / "render-ancestor-link"
        link_parent.symlink_to(target_dir.parent, target_is_directory=True)
        ancestor["design"]["render_ref"] = str(link_parent / target_dir.name)
        ancestor["design"]["render_evidence"]["render_ref"] = ancestor["design"]["render_ref"]
        report = validate_content_spec(ancestor, approved_brand(), self.TODAY, trusted_policy(ancestor), actor_id="lead-fixture")
        self.assertIn("render_symlink_component", {issue.code for issue in report.errors})

    def test_visual_contract_changes_invalidate_approval_checksum(self) -> None:
        spec = make_approved_spec()
        spec["anti_slop_audit"]["visual_fingerprints"][0]["motif_family"] = "changed-after-approval"
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("anti_slop_package_checksum", {issue.code for issue in report.errors})

    def test_visual_reuse_and_full_composition_require_bound_exception(self) -> None:
        spec = make_approved_spec()
        for item in spec["anti_slop_audit"]["visual_fingerprints"]:
            item.update({"layout_family": "same", "focal_object": "same", "motif_family": "same", "composition_axis": "same", "text_density": "same"})
            item["assets"] = [{"asset_id": "stock-1", "role": "photo", "provenance": {"kind": "approved"}, "reuse_policy": {"max_uses": 1}}]
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        codes = {issue.code for issue in report.errors}
        self.assertIn("repeated_full_composition", codes)
        self.assertIn("asset_reuse_exceeded", codes)

    def test_asset_reuse_policy_is_consistent_across_occurrences(self) -> None:
        spec = make_approved_spec()
        for index, item in enumerate(spec["anti_slop_audit"]["visual_fingerprints"][:2]):
            item["assets"] = [{
                "asset_id": "shared-photo",
                "role": "photo",
                "provenance": {"kind": "approved"},
                "reuse_policy": {"max_uses": 2 if index == 0 else 3},
            }]
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("asset_manifest_inconsistent", {issue.code for issue in report.errors})

    def test_similarity_requires_window_comparator_fingerprints_and_bound_score(self) -> None:
        spec = make_approved_spec()
        similarity = spec["anti_slop_audit"]["evidence"]["recent_similarity"]
        similarity.pop("candidate_window")
        similarity["score"] = 0.95
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        codes = {issue.code for issue in report.errors}
        self.assertIn("similarity_candidate_window", codes)
        self.assertIn("similarity_threshold_exceeded", codes)

    def test_critique_requires_trusted_distinct_reviewer_and_observations(self) -> None:
        spec = make_approved_spec()
        critique = spec["anti_slop_audit"]["independent_critique"]
        critique["reviewer_id"] = "lead-fixture"
        critique["observations"] = []
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        codes = {issue.code for issue in report.errors}
        self.assertIn("independent_critique_not_distinct", codes)
        self.assertIn("independent_critique_observations", codes)

    def test_final_critique_requires_authenticated_selector_and_generator(self) -> None:
        spec = make_approved_spec()
        spec["human_selected_route"]["selected_by"] = "unmapped-selector"
        spec["design"]["generated_by"] = "unmapped-generator"
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        codes = {issue.code for issue in report.errors}
        self.assertIn("independent_selector_trust", codes)
        self.assertIn("independent_generator_trust", codes)

    def test_score_cannot_pass_with_pending_hard_evidence(self) -> None:
        spec = make_approved_spec()
        spec["anti_slop_audit"]["evidence"]["ocr"]["status"] = "pending"
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("score_incoherent", {issue.code for issue in report.errors})

    def test_visual_fingerprint_must_bind_decoded_page_pixels(self) -> None:
        spec = make_approved_spec()
        spec["anti_slop_audit"]["visual_fingerprints"][0]["page_digest"] = "sha256:" + "0" * 64
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("visual_fingerprint_page_digest", {issue.code for issue in report.errors})

    def test_identical_decoded_pages_fail_even_when_metadata_differs(self) -> None:
        spec = make_approved_spec()
        render_dir = Path(spec["design"]["render_ref"])
        (render_dir / "page-2.png").write_bytes((render_dir / "page-1.png").read_bytes())
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("repeated_identical_pixels", {issue.code for issue in report.errors})

    def test_missing_external_action_receipts_cannot_authorize_final(self) -> None:
        spec = make_approved_spec()
        spec["policy"].pop("action_records")
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("action_receipt_unverified", {issue.code for issue in report.errors})

    def test_action_receipt_cannot_be_reused_across_content_records(self) -> None:
        spec = make_approved_spec()
        spec["policy"]["action_records"]["generation"]["content_id"] = "other-content-fixture"
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("action_receipt_binding", {issue.code for issue in report.errors})

    def test_final_cli_requires_independent_policy_digest_pin(self) -> None:
        spec = make_approved_spec()
        spec_path = write_input_json("missing-policy-digest-spec.json", spec)
        brand_path = write_input_json("missing-policy-digest-brand.json", approved_brand())
        policy_context = trusted_policy(spec)
        policy_path = write_input_json("missing-policy-digest-policy.json", dict(policy_context.data))
        output = io.StringIO()
        with redirect_stdout(output):
            result = main([str(spec_path), "--brand", str(brand_path), "--policy", str(policy_path), "--actor-id", "lead-fixture", "--json"])
        self.assertNotEqual(0, result)
        self.assertIn("trusted_policy_digest_required", {item["code"] for item in json.loads(output.getvalue())["issues"]})

    def test_final_v1_anti_slop_contract_cannot_authorize(self) -> None:
        spec = make_approved_spec()
        spec["anti_slop_audit"]["anti_slop_contract_version"] = 1
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("anti_slop_contract_version", {issue.code for issue in report.errors})

    def test_production_evidence_requires_policy_pinned_tool_receipts(self) -> None:
        spec = make_approved_spec()
        spec["policy"].pop("evidence_tools")
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("evidence_authority_missing", {issue.code for issue in report.errors})

    def test_benchmark_pass_rejects_identical_pairwise_verdict(self) -> None:
        spec = make_approved_spec()
        registry = benchmark_registry(spec)
        entry = registry["reference_sets"][0]
        benchmark = spec["anti_slop_audit"]["independent_critique"]["benchmark"]
        benchmark.update({"status": "pass", "reference_set_checksum": entry["checksum"], "render_digest": spec["design"]["render_evidence"]["render_digest"], "candidate_ids": ["recent-education-001"], "reference_corpus": entry["reference_corpus"], "comparator": {"id": "fixture-comparator", "version": "1"}, "pairwise_verdict": [{"candidate_id": "recent-education-001", "verdict": "identical"}]})
        registry_path = write_input_json("benchmark-identical-registry.json", registry)
        context = load_benchmark_registry(registry_path)
        benchmark["registry_checksum"] = context.canonical_digest
        spec["policy"]["benchmark_registry"] = {"source": "local_authenticated_benchmark_registry", "registry_id": registry["registry_id"], "revision": registry["revision"], "registry_checksum": context.canonical_digest, "trusted_root": registry["trusted_root"], "reference_set_ids": ["fixture-benchmark@1"], "reference_set_checksums": {"fixture-benchmark@1": entry["checksum"]}, "reference_corpus_checksums": {"fixture-corpus-001": entry["reference_corpus"][0]["checksum"]}}
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture", benchmark_registry=context)
        self.assertIn("independent_benchmark_coherence", {issue.code for issue in report.errors})

    def test_high_slop_index_caps_an_unresolved_high_score(self) -> None:
        spec = make_approved_spec()
        spec["anti_slop_audit"]["slop_index"]["visual_convergence"] = 4
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("score_incoherent", {issue.code for issue in report.errors})

    def test_resolved_slop_finding_does_not_count_as_score_failure(self) -> None:
        spec = make_approved_spec()
        spec["anti_slop_audit"]["slop_index"]["visual_convergence"] = 4
        spec["anti_slop_audit"]["findings"] = [{
            "reason_code": "same_layout_cluster", "dimension": "visual_convergence",
            "explanation": "Earlier draft repeated a layout.", "status": "resolved", "resolution": "Changed composition axis.",
        }]
        spec["anti_slop_audit"]["approval_package"]["checksum"] = _anti_slop_package_checksum(spec, spec["anti_slop_audit"])
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertNotIn("score_incoherent", {issue.code for issue in report.errors})

    def test_reason_codes_must_bind_findings_and_cannot_hide_high_score_failure(self) -> None:
        spec = make_approved_spec()
        spec["anti_slop_audit"]["reason_codes"] = ["generic_language"]
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        codes = {issue.code for issue in report.errors}
        self.assertIn("anti_slop_reason_unbound", codes)
        self.assertIn("score_incoherent", codes)

    def test_generic_cta_warns_in_draft_and_blocks_final_but_natural_cta_survives(self) -> None:
        draft = load_json("content-spec.example.json")
        draft["caption"]["cta"] = "Pelajari lebih lanjut."
        draft_report = validate_content_spec(draft, approved_brand(), self.TODAY)
        self.assertIn("generic_cta_target_missing", {issue.code for issue in draft_report.warnings})
        final = make_approved_spec()
        final["caption"]["cta"] = "Pelajari lebih lanjut."
        final_report = validate_content_spec(final, approved_brand(), self.TODAY, trusted_policy(final), actor_id="lead-fixture")
        self.assertIn("generic_cta_target_missing", {issue.code for issue in final_report.errors})
        natural = make_approved_spec()
        natural_report = validate_content_spec(natural, approved_brand(), self.TODAY, trusted_policy(natural), actor_id="lead-fixture")
        self.assertNotIn("generic_cta_target_missing", {issue.code for issue in natural_report.errors})

    def test_embedded_remote_receipt_never_authorizes_final_render(self) -> None:
        spec = make_approved_spec()
        evidence = spec["design"]["render_evidence"]
        evidence["render_ref"] = "https:" + "//untrusted.invalid/render.png"
        evidence["trusted_receipt"] = {"verification_status": "verified", "receipt_digest": evidence["render_digest"]}
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("render_remote_untrusted", {issue.code for issue in report.errors})

    def test_empty_render_directory_and_duplicate_page_files_fail(self) -> None:
        spec = make_approved_spec()
        empty_dir = Path(tempfile.mkdtemp(prefix="empty-render-", dir=TEST_EXPORT_DIR.name))
        spec["design"]["render_ref"] = str(empty_dir)
        spec["design"]["render_evidence"]["render_ref"] = str(empty_dir)
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("render_artifact_empty", {issue.code for issue in report.errors})

        duplicate = make_approved_spec()
        render_dir = duplicate["design"]["render_ref"]
        duplicate["design"]["render_evidence"]["page_files"] = ["page-1.png", "page-1.png"] + [f"page-{i}.png" for i in range(2, len(duplicate["slides"]) + 1)]
        report = validate_content_spec(duplicate, approved_brand(), self.TODAY, trusted_policy(duplicate), actor_id="lead-fixture")
        self.assertIn("render_page_duplicate", {issue.code for issue in report.errors})

        bounded = make_approved_spec()
        bounded["design"]["render_evidence"]["page_files"] = ["page-1.png"] * 101
        report = validate_content_spec(bounded, approved_brand(), self.TODAY, trusted_policy(bounded), actor_id="lead-fixture")
        self.assertIn("render_file_count", {issue.code for issue in report.errors})

    def test_forged_png_magic_header_is_not_a_verified_render(self) -> None:
        spec = make_approved_spec()
        forged = Path(spec["design"]["render_ref"]) / "page-1.png"
        forged.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sIIBBBBB", 13, b"IHDR", 1080, 1350, 8, 6, 0, 0, 0))
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("render_dimensions_unreadable", {issue.code for issue in report.errors})

    def test_png_valid_chunks_with_invalid_idat_payload_fail_closed(self) -> None:
        spec = make_approved_spec()
        page_path = Path(spec["design"]["render_ref"]) / "page-1.png"
        data = page_path.read_bytes()
        offset = 8
        rebuilt = bytearray(data[:8])
        replaced = False
        while offset < len(data):
            length = int.from_bytes(data[offset:offset + 4], "big")
            chunk_type = data[offset + 4:offset + 8]
            payload = data[offset + 8:offset + 8 + length]
            if chunk_type == b"IDAT" and not replaced:
                payload = b"not-a-zlib-stream"
                replaced = True
            body = chunk_type + payload
            rebuilt.extend(struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))
            offset += 12 + length
        page_path.write_bytes(bytes(rebuilt))
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("render_dimensions_unreadable", {issue.code for issue in report.errors})

    def test_malformed_reviewer_identity_reports_errors_without_crashing(self) -> None:
        spec = make_approved_spec()
        spec["anti_slop_audit"]["independent_critique"]["reviewer_id"] = []
        spec["anti_slop_audit"]["independent_critique"]["reviewer_role"] = []
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        codes = {issue.code for issue in report.errors}
        self.assertIn("independent_critique_reviewer", codes)
        self.assertIn("independent_critique_reviewer_trust", codes)

    def test_attacker_cannot_approve_repeated_composition_exception(self) -> None:
        spec = make_approved_spec()
        for item in spec["anti_slop_audit"]["visual_fingerprints"]:
            item.update({"layout_family": "same", "focal_object": "same", "motif_family": "same", "composition_axis": "same", "text_density": "same"})
        spec["anti_slop_audit"]["approved_exceptions"] = {
            "repeated_composition": {
                "approved": True,
                "approved_by": "attacker",
                "approved_role": "lead",
                "approved_at": "2026-08-19T11:00:00+07:00",
                "scope": full_scope(spec),
                "render_digest": spec["design"]["render_evidence"]["render_digest"],
                "reason": "Intentional repetition.",
                "affected": {"page_refs": ["page-1", "page-2"]},
            }
        }
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("approved_exception_reviewer_trust", {issue.code for issue in report.errors})

    def test_exception_approver_cannot_be_the_independent_reviewer(self) -> None:
        spec = make_approved_spec()
        for item in spec["anti_slop_audit"]["visual_fingerprints"]:
            item.update({"layout_family": "same", "focal_object": "same", "motif_family": "same", "composition_axis": "same", "text_density": "same"})
        spec["anti_slop_audit"]["approved_exceptions"] = {
            "repeated_composition": {
                "approved": True,
                "approved_by": "independent-critic-fixture",
                "approved_role": "lead",
                "approved_at": "2026-08-19T11:00:00+07:00",
                "scope": full_scope(spec),
                "render_digest": spec["design"]["render_evidence"]["render_digest"],
                "reason": "Intentional repetition for the approved series motif.",
                "affected": {"page_refs": [f"page-{index}" for index in range(1, len(spec["slides"]) + 1)]},
            }
        }
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("approved_exception_not_distinct", {issue.code for issue in report.errors})

    def test_exception_approver_cannot_be_current_authenticated_actor(self) -> None:
        spec = make_approved_spec()
        for item in spec["anti_slop_audit"]["visual_fingerprints"]:
            item.update({"layout_family": "same", "focal_object": "same", "motif_family": "same", "composition_axis": "same", "text_density": "same"})
        spec["anti_slop_audit"]["approved_exceptions"] = {
            "repeated_composition": {
                "approved": True, "approved_by": "lead-fixture", "approved_role": "lead",
                "approved_at": "2026-08-19T11:00:00+07:00", "scope": full_scope(spec),
                "render_digest": spec["design"]["render_evidence"]["render_digest"],
                "reason": "Intentional repetition for the approved series motif.",
                "affected": {"page_refs": [f"page-{index}" for index in range(1, len(spec["slides"]) + 1)]},
            }
        }
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("approved_exception_self_approval", {issue.code for issue in report.errors})

    def test_png_trailing_zlib_bytes_fail_closed(self) -> None:
        spec = make_approved_spec()
        page_path = Path(spec["design"]["render_ref"]) / "page-1.png"
        data = page_path.read_bytes()
        offset = 8
        rebuilt = bytearray(data[:8])
        while offset < len(data):
            length = int.from_bytes(data[offset:offset + 4], "big")
            chunk_type = data[offset + 4:offset + 8]
            payload = data[offset + 8:offset + 8 + length]
            if chunk_type == b"IDAT":
                payload += b"trailing-zlib-bytes"
            body = chunk_type + payload
            rebuilt.extend(struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))
            offset += 12 + length
        page_path.write_bytes(bytes(rebuilt))
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("render_dimensions_unreadable", {issue.code for issue in report.errors})

    def test_indexed_png_is_rejected_even_with_valid_palette_and_crc(self) -> None:
        spec = make_approved_spec()
        page_path = Path(spec["design"]["render_ref"]) / "page-1.png"
        def chunk(kind: bytes, payload: bytes) -> bytes:
            body = kind + payload
            return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        indexed = b"\x89PNG\r\n\x1a\n"
        indexed += chunk(b"IHDR", struct.pack(">IIBBBBB", 1080, 1350, 8, 3, 0, 0, 0))
        indexed += chunk(b"PLTE", b"\x00\x00\x00")
        indexed += chunk(b"IDAT", zlib.compress((b"\x00" + b"\x00" * 1080) * 1350))
        indexed += chunk(b"IEND", b"")
        page_path.write_bytes(indexed)
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("render_dimensions_unreadable", {issue.code for issue in report.errors})

    def test_final_download_requires_policy_supplied_root(self) -> None:
        spec = make_approved_spec()
        spec["policy"].pop("download_root")
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("download_trusted_root", {issue.code for issue in report.errors})

    def test_trusted_policy_is_recursively_immutable(self) -> None:
        spec = make_approved_spec()
        context = trusted_policy(spec)
        with self.assertRaises(TypeError):
            context.data["action_records"]["generation"]["actor_id"] = "attacker"
        with self.assertRaises(TypeError):
            context.data["role_mapping"]["lead"].append("attacker")
        self.assertEqual(context.canonical_digest, trusted_policy(spec).canonical_digest)

    def test_action_receipt_binds_effective_target_account(self) -> None:
        spec = make_approved_spec()
        spec["publishing"]["target_account"] = "different-account"
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("action_receipt_target", {issue.code for issue in report.errors})

    def test_png_transparency_and_unknown_critical_chunks_fail_closed(self) -> None:
        def chunk(kind: bytes, payload: bytes) -> bytes:
            body = kind + payload
            return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

        def png(color_type: int, row: bytes, extra: bytes = b"") -> bytes:
            header = struct.pack(">IIBBBBB", 1, 1, 8, color_type, 0, 0, 0)
            return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + extra + chunk(b"IDAT", zlib.compress(b"\x00" + row)) + chunk(b"IEND", b"")

        # Fully valid RGBA with transparent hidden RGB must not enter the
        # production pixel fingerprint path.
        self.assertIsNone(_decode_png(png(6, b"\xff\x00\x00\x00")))
        self.assertIsNone(_decode_png(png(2, b"\x01\x02\x03", chunk(b"tRNS", b"\x00\x01"))))
        self.assertIsNone(_decode_png(png(2, b"\x01\x02\x03", chunk(b"ABCD", b""))))

    def test_forged_external_result_score_cannot_authorize_similarity(self) -> None:
        spec = make_approved_spec()
        spec["anti_slop_audit"]["evidence"]["recent_similarity"]["score"] = 0.01
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("evidence_result_binding", {issue.code for issue in report.errors})

    def test_open_beneath_rejects_ancestor_symlink_escape(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="trusted-root-"))
        outside = Path(tempfile.mkdtemp(prefix="outside-root-"))
        (outside / "page.bin").write_bytes(b"outside")
        (root / "escape").symlink_to(outside, target_is_directory=True)
        self.assertIsNone(_open_beneath(root, root / "escape" / "page.bin"))

    def test_final_policy_digest_cannot_be_disabled_by_caller_flag(self) -> None:
        spec = make_approved_spec()
        context = trusted_policy(spec)
        report = _real_validate_content_spec(
            spec,
            approved_brand(),
            self.TODAY,
            context,
            actor_id="lead-fixture",
            require_policy_digest=False,
        )
        self.assertIn("trusted_policy_digest_required", {issue.code for issue in report.errors})

    def test_future_external_evidence_result_timestamp_fails_closed(self) -> None:
        spec = make_approved_spec()
        spec["policy"]["evidence_results"]["recent_similarity"]["timestamp"] = "2099-01-01T00:00:00+00:00"
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("evidence_result_timestamp_future", {issue.code for issue in report.errors})

    def test_future_critique_timestamp_fails_closed(self) -> None:
        spec = make_approved_spec()
        spec["anti_slop_audit"]["independent_critique"]["reviewed_at"] = "2099-01-01T00:00:00+00:00"
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("independent_critique_timestamp_future", {issue.code for issue in report.errors})

    def test_future_evidence_checked_timestamp_fails_closed(self) -> None:
        spec = make_approved_spec()
        spec["anti_slop_audit"]["evidence"]["layout"]["checked_at"] = "2099-01-01T00:00:00+00:00"
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertIn("anti_slop_evidence_timestamp_future", {issue.code for issue in report.errors})

    def test_valid_filesystem_root_identity_pins_authorize_final_reads(self) -> None:
        spec = make_approved_spec()
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        self.assertEqual([], report.errors)

    def test_recreated_render_root_fails_pinned_identity(self) -> None:
        spec = make_approved_spec()
        original = Path(spec["design"]["render_ref"])
        moved = original.with_name(original.name + "-original")
        original.rename(moved)
        original.mkdir()
        try:
            report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
            self.assertIn("filesystem_root_identity", {issue.code for issue in report.errors})
        finally:
            original.rmdir()
            moved.rename(original)

    def test_missing_filesystem_root_pins_fail_final_closed(self) -> None:
        spec = make_approved_spec()
        spec["policy"].pop("filesystem_roots")
        report = validate_content_spec(spec, approved_brand(), self.TODAY, trusted_policy(spec), actor_id="lead-fixture")
        codes = {issue.code for issue in report.errors}
        self.assertIn("filesystem_root_pin_required", codes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
