#!/usr/bin/env python3
"""Deterministic tests for validate_content_spec.py."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from validate_content_spec import calculate_package_checksum, validate_content_spec  # noqa: E402


TEST_EXPORT_DIR = tempfile.TemporaryDirectory(prefix="social-content-validator-")
TEST_BRAND_BUNDLE_DIR = tempfile.TemporaryDirectory(prefix="social-content-brand-bundle-")


def load_json(name: str) -> dict:
    with (SKILL_DIR / "assets" / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def trusted_policy(spec: dict) -> dict:
    policy = spec["policy"]
    unattended = policy.get("unattended") if isinstance(policy.get("unattended"), dict) else {}
    preapproved = unattended.get("preapproved") if isinstance(unattended.get("preapproved"), dict) else {}
    return {
        "schema_version": policy["schema_version"],
        "policy_id": policy["policy_id"],
        "revision": policy["revision"],
        "source": policy["source"],
        "scope": dict(policy["scope"]),
        "role_mapping": json.loads(json.dumps(policy["role_mapping"])),
        "actor_id": policy["actor_id"],
        "actor_role": policy["actor_role"],
        "unattended": {
            "preapproved": {
                "template_provider_ids": json.loads(json.dumps(preapproved.get("template_provider_ids", {})))
            }
        },
    }


def trusted_brand_policy(spec: dict, *, product_id: str | None = None) -> dict:
    policy = spec["policy"]
    return {
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


def full_scope(spec: dict) -> dict:
    return {**spec["scope"], "brand_id": spec["brand_id"]}


def neutral_brand_bundle(*, include_claim: bool = False) -> str:
    """Write a scoped, provider-neutral Brand Copy bundle fixture."""
    root = Path(TEST_BRAND_BUNDLE_DIR.name)
    envelope = {
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
    }
    documents = {
        "brand-profile.json": {
            **envelope,
            "identity": {},
            "audience": {},
            "voice": [],
            "terminology": [],
            "copy_constraints": [],
            "visual_copy_cues": [],
            "rights": {"status": "approved"},
            "gaps": [],
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
        spec["qa"][key] = "pass"
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
    spec["approval"]["package_checksum"] = calculate_package_checksum(spec)
    return spec


class ValidatorTests(unittest.TestCase):
    TODAY = date(2026, 8, 19)

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
        context = trusted_policy(spec)
        context["revision"] = "2026-08-19T000001Z-r2"
        report = validate_content_spec(spec, approved_brand(), self.TODAY, context, actor_id="lead-fixture")
        self.assertIn("trusted_policy_revision", {issue.code for issue in report.errors})

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
            brand_policy_context=trusted_policy(spec),
            brand_actor_id="lead-fixture",
        )
        self.assertIn("brand_bundle_invalid", {issue.code for issue in report.errors})

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

        trusted = trusted_policy(spec)
        trusted["unattended"]["preapproved"]["template_provider_ids"]["brand-template-001"] = "CanvaOpaqueTemplate-TRUSTED-DIFFERENT-001"
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

        context["scope"]["product_id"] = "other-product"
        report = validate_content_spec(spec, approved_brand(), self.TODAY, context)
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
