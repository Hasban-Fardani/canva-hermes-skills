#!/usr/bin/env python3
"""Deterministic tests for validate_content_spec.py."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from validate_content_spec import _anti_slop_package_checksum, _load_brand_bundle_validator, calculate_package_checksum, load_trusted_policy, main, validate_content_spec  # noqa: E402


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
    spec["policy"]["role_mapping"]["lead"] = ["lead-fixture"]
    spec["design"]["template_id"] = "brand-template-001"
    spec["design"]["template_version"] = "1"
    spec["design"]["provider"] = "canva"
    spec["design"]["provider_template_id"] = "CanvaOpaqueTemplate-EXAMPLE-001"
    spec["design"]["draft_ref"] = "canva:design:example"
    spec["design"]["render_ref"] = "<render-directory>/example-render.png"
    spec["design"]["render_evidence"] = {"render_ref": "<render-directory>/example-render.png", "render_digest": "sha256:" + ("1" * 64), "receipt_digest": "sha256:" + ("1" * 64), "receipt_id": "render-receipt-001", "provider": "local_renderer", "verification_status": "verified", "captured_at": "2026-08-19T11:00:00+07:00", "page_refs": ["page-1"], "scope": full_scope(spec)}
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
    spec["human_copy_brief"] = {
        "situation": {"moment": "After the second meeting, tabs remain open.", "observable_behavior": "The reader switches tabs before opening one document."},
        "tension": {"audience_assumption": "More tabs means more progress.", "friction": "No task is selected."},
        "point_of_view": {"brand_stance": "Choose the next document plainly.", "what_we_refuse_to_say": "We do not promise productivity gains.", "right_to_speak": "The brief supplies the observed work moment."},
        "proof": {"concrete_details": ["second meeting", "seven tabs"], "source_refs": ["proof-organise"]},
        "creative_route": {"visual_dependency": "A tab strip shows the choice.", "distinctive_move": "Annotate one selected tab."},
        "message_jobs": {"headline": "Name the document.", "body": "Close the unrelated tabs.", "caption": "Use this after a task switch.", "cta_behavior": "Save for the next task switch."},
    }
    spec["copy_quality_audit"] = {"status": "pass", "reason_codes": [], "findings": []}
    audit["status"] = "pass"
    audit["evidence"] = {
        "ocr": {"status": "pass", "checked_at": "2026-08-19T11:00:00+07:00", "page_refs": ["page-1"], "exact_match": True},
        "layout": {"status": "pass", "checked_at": "2026-08-19T11:00:00+07:00", "page_refs": ["page-1"], "overflow": False, "overlap": False},
        "semantic": {"status": "pass", "checked_at": "2026-08-19T11:00:00+07:00", "page_refs": ["page-1"], "contract_tests": ["object", "count", "relation", "cta"]},
        "wcag": {"status": "pass", "checked_at": "2026-08-19T11:00:00+07:00", "page_refs": ["page-1"], "contrast_pass": True},
        "rights": {"status": "pass", "checked_at": "2026-08-19T11:00:00+07:00", "page_refs": ["page-1"], "assets": []},
        "recent_similarity": {"status": "pass", "checked_at": "2026-08-19T11:00:00+07:00", "page_refs": ["page-1"], "threshold": 0.80},
    }
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
        "independent_from_generation": True,
        "findings": [],
    }
    audit["approval_package"] = {
        "scope": full_scope(spec),
        "content_id": spec["content_id"],
        "render_digest": "sha256:" + ("1" * 64),
        "export_checksum": spec["design"]["export_checksum"],
    }
    audit["approval_package"]["checksum"] = _anti_slop_package_checksum(spec, audit)
    spec["approval"]["package_checksum"] = calculate_package_checksum(spec)
    return spec


class ValidatorTests(unittest.TestCase):
    TODAY = date(2026, 8, 19)

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
        self.assertEqual("sha256:fdaca8c011cf5f168a17e90d6994546683d3a8480381f554805c555a0c3d17cb", calculate_package_checksum(spec))

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
