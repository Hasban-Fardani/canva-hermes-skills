#!/usr/bin/env python3
"""Unit tests for the local brand bundle validator."""

from __future__ import annotations

import json
import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from validate_brand_bundle import REQUIRED_FILES, validate_brand_bundle  # noqa: E402


class BrandBundleValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.docs = self._valid_docs()
        self._write_docs()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _valid_docs(self) -> dict[str, dict]:
        envelope = {
            "schema_version": "1.0",
            "brand_id": "sample-brand",
            "revision": "2026-08-19T000000Z-r1",
            "status": "draft",
        }
        return {
            "brand-profile.json": {
                **envelope,
                "identity": {"name": "Sample Brand"},
                "audience": {},
                "voice": [
                    {
                        "id": "voice-1",
                        "value": "Plain and helpful",
                        "evidence_status": "exact",
                        "source_ids": ["source-1"],
                    }
                ],
                "terminology": [],
                "copy_constraints": [],
                "visual_copy_cues": [],
                "rights": {"status": "exact"},
                "gaps": [],
            },
            "claim-registry.json": {**envelope, "claims": []},
            "template-registry.json": {**envelope, "templates": []},
            "provenance.json": {
                **envelope,
                "sources": [
                    {
                        "source_id": "source-1",
                        "kind": "user-provided",
                        "locator": "local:brief.txt",
                        "authorization": {"status": "exact"},
                        "captured_at": "2026-08-19T000000Z",
                    }
                ],
                "evidence_ledger": [
                    {
                        "record_id": "voice-1",
                        "source_ids": ["source-1"],
                        "evidence_status": "exact",
                    }
                ],
                "authorization": {"status": "exact"},
                "update": {"operation": "capture"},
            },
        }

    def _write_docs(self) -> None:
        for filename, document in self.docs.items():
            (self.root / filename).write_text(json.dumps(document), encoding="utf-8")

    def _policy(self, actor_id: str = "admin-1", role: str = "admin", product_id=None) -> dict:
        role_mapping = {
            "lead": ["lead-1"],
            "admin": ["admin-1"],
            "member": ["member-1"],
            "reviewer": ["reviewer-1"],
            "publisher": ["publisher-1"],
        }
        role_mapping[role] = [actor_id]
        return {
            "schema_version": "1.0",
            "policy_id": "policy-example",
            "revision": "2026-08-19T000000Z-r1",
            "source": "local_authenticated_policy",
            "scope": {
                "tenant_id": "tenant-a",
                "client_id": "client-a",
                "brand_id": "sample-brand",
                "product_id": product_id,
            },
            "role_mapping": role_mapping,
        }

    def test_valid_bundle(self) -> None:
        self.assertEqual(validate_brand_bundle(self.root, "sample-brand"), [])

    def test_legacy_v1_bundle_rejects_partial_scope(self) -> None:
        self.docs["brand-profile.json"]["scope"] = {"tenant_id": "tenant-a", "client_id": "client-a"}
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("legacy schema 1.0 must omit scope" in error for error in errors))

    def _make_scoped(self, product_id=None, parent_brand_revision=None) -> None:
        scope = {
            "tenant_id": "tenant-a",
            "client_id": "client-a",
            "product_id": product_id,
            "parent_brand_revision": parent_brand_revision,
        }
        for document in self.docs.values():
            document["schema_version"] = "1.1"
            document["scope"] = copy.deepcopy(scope)
        self._write_docs()

    def test_accepts_scoped_bundle(self) -> None:
        self._make_scoped()
        self.assertEqual(validate_brand_bundle(self.root, "sample-brand"), [])

    def test_rejects_scope_mismatch_across_files(self) -> None:
        self._make_scoped()
        self.docs["claim-registry.json"]["scope"]["client_id"] = "other-client"
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("does not match bundle scope" in error for error in errors))

    def test_rejects_unsafe_scope_id(self) -> None:
        self._make_scoped()
        for document in self.docs.values():
            document["scope"]["tenant_id"] = "Tenant A"
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("scope.tenant_id: must match lowercase-kebab format" in error for error in errors))

    def test_rejects_unknown_scope_field(self) -> None:
        self._make_scoped()
        self.docs["brand-profile.json"]["scope"]["namespace"] = "tenant-a/client-a/sample-brand"
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("unknown field(s)" in error for error in errors))

    def test_observe_allows_bounded_unverified_public_draft(self) -> None:
        self._make_scoped()
        self.docs["provenance.json"]["update"]["operation"] = "observe"
        self.docs["provenance.json"]["authorization"]["status"] = "unverified"
        self.docs["provenance.json"]["sources"][0]["kind"] = "public-observation"
        self.docs["provenance.json"]["sources"][0]["authorization"] = {"status": "unverified"}
        self.docs["provenance.json"]["evidence_ledger"][0]["evidence_status"] = "observed"
        self.docs["brand-profile.json"]["rights"]["status"] = "unverified"
        self.docs["brand-profile.json"]["voice"][0]["evidence_status"] = "observed"
        self._write_docs()
        self.assertEqual(validate_brand_bundle(self.root), [])

    def test_observe_rejects_exact_or_active_rules(self) -> None:
        self._make_scoped()
        self.docs["provenance.json"]["update"]["operation"] = "observe"
        for document in self.docs.values():
            document["status"] = "active"
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("observe operation may only create a draft bundle" in error for error in errors))
        self.assertTrue(any("observe operation requires observed" in error for error in errors))

    def test_observe_rejects_approved_record(self) -> None:
        self._make_scoped()
        self.docs["provenance.json"]["update"]["operation"] = "observe"
        self.docs["brand-profile.json"]["rights"]["status"] = "unverified"
        self.docs["brand-profile.json"]["voice"][0]["evidence_status"] = "observed"
        self.docs["claim-registry.json"]["claims"] = [
            {
                "id": "claim-1",
                "claim": "Visible copy",
                "status": "approved",
                "evidence_status": "observed",
                "source_ids": ["source-1"],
                "rights": {"status": "unverified"},
            }
        ]
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("observe operation cannot create approved records" in error for error in errors))

    def test_product_overlay_requires_parent_revision(self) -> None:
        self._make_scoped(product_id="product-a", parent_brand_revision="2026-08-19T000000Z-r1")
        self.assertEqual(validate_brand_bundle(self.root), [])

    def test_rejects_product_overlay_without_parent_revision(self) -> None:
        self._make_scoped(product_id="product-a")
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("parent_brand_revision" in error for error in errors))

    def test_rejects_master_parent_reference(self) -> None:
        self._make_scoped(parent_brand_revision="2026-08-19T000000Z-r1")
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("requires scope.product_id" in error for error in errors))

    def test_active_scoped_bundle_requires_verified_lead(self) -> None:
        self._make_scoped()
        for document in self.docs.values():
            document["status"] = "active"
        self.docs["brand-profile.json"]["rights"]["status"] = "approved"
        self.docs["provenance.json"]["authorization"] = {
            "status": "approved",
            "actor_id": "member-1",
            "role": "member",
            "verified": False,
            "policy_source": "prompt",
            "policy_id": "",
            "policy_revision": "",
        }
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("local authenticated lead or admin role" in error for error in errors))
        self.assertTrue(any("verified true" in error for error in errors))
        self.assertTrue(any("local authenticated policy authorization" in error for error in errors))

    def test_scoped_approved_record_requires_verified_lead(self) -> None:
        self._make_scoped()
        self.docs["claim-registry.json"]["claims"] = [
            {
                "id": "claim-1",
                "claim": "A supported claim",
                "status": "approved",
                "evidence_status": "exact",
                "source_ids": ["source-1"],
                "rights": {"status": "approved"},
            }
        ]
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("privileged approval/activation requires external trusted local access policy" in error for error in errors))

    def test_active_scoped_bundle_accepts_local_admin(self) -> None:
        self._make_scoped()
        for document in self.docs.values():
            document["status"] = "active"
        self.docs["brand-profile.json"]["rights"]["status"] = "approved"
        self.docs["provenance.json"]["authorization"] = {
            "status": "approved",
            "actor_id": "admin-1",
            "role": "admin",
            "verified": True,
            "policy_source": "local_authenticated_policy",
            "policy_id": "policy-example",
            "policy_revision": "2026-08-19T000000Z-r1",
        }
        self._write_docs()
        self.assertEqual(validate_brand_bundle(self.root, policy=self._policy(), actor_id="admin-1"), [])

    def test_active_bundle_rejects_missing_external_policy(self) -> None:
        self._make_scoped()
        for document in self.docs.values():
            document["status"] = "active"
        self.docs["brand-profile.json"]["rights"]["status"] = "approved"
        self.docs["provenance.json"]["authorization"] = {
            "status": "approved",
            "actor_id": "admin-1",
            "role": "admin",
            "verified": True,
            "policy_source": "local_authenticated_policy",
            "policy_id": "policy-example",
            "policy_revision": "2026-08-19T000000Z-r1",
        }
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("external trusted local access policy" in error for error in errors))

    def test_active_bundle_rejects_wrong_policy_scope(self) -> None:
        self._make_scoped()
        for document in self.docs.values():
            document["status"] = "active"
        self.docs["brand-profile.json"]["rights"]["status"] = "approved"
        self.docs["provenance.json"]["authorization"] = {
            "status": "approved",
            "actor_id": "admin-1",
            "role": "admin",
            "verified": True,
            "policy_source": "local_authenticated_policy",
            "policy_id": "policy-example",
            "policy_revision": "2026-08-19T000000Z-r1",
        }
        policy = self._policy()
        policy["scope"]["tenant_id"] = "other-tenant"
        self._write_docs()
        errors = validate_brand_bundle(self.root, policy=policy, actor_id="admin-1")
        self.assertTrue(any("policy scope does not match bundle scope" in error for error in errors))

    def test_active_bundle_rejects_embedded_self_promotion(self) -> None:
        self._make_scoped()
        for document in self.docs.values():
            document["status"] = "active"
        self.docs["brand-profile.json"]["rights"]["status"] = "approved"
        self.docs["provenance.json"]["authorization"] = {
            "status": "approved",
            "actor_id": "member-1",
            "role": "admin",
            "verified": True,
            "policy_source": "local_authenticated_policy",
            "policy_id": "policy-example",
            "policy_revision": "2026-08-19T000000Z-r1",
        }
        self._write_docs()
        errors = validate_brand_bundle(self.root, policy=self._policy(), actor_id="member-1")
        self.assertTrue(any("not mapped by external access policy" in error for error in errors))

    def test_active_bundle_rejects_runtime_impersonation(self) -> None:
        self._make_scoped()
        for document in self.docs.values():
            document["status"] = "active"
        self.docs["brand-profile.json"]["rights"]["status"] = "approved"
        self.docs["provenance.json"]["authorization"] = {
            "status": "approved",
            "actor_id": "admin-1",
            "role": "admin",
            "verified": True,
            "policy_source": "local_authenticated_policy",
            "policy_id": "policy-example",
            "policy_revision": "2026-08-19T000000Z-r1",
        }
        self._write_docs()
        errors = validate_brand_bundle(self.root, policy=self._policy(), actor_id="member-1")
        self.assertTrue(any("runtime actor_id does not match" in error for error in errors))
        self.assertTrue(any("not mapped by external access policy" in error for error in errors))

    def test_policy_can_be_loaded_from_external_path(self) -> None:
        self._make_scoped()
        for document in self.docs.values():
            document["status"] = "active"
        self.docs["brand-profile.json"]["rights"]["status"] = "approved"
        self.docs["provenance.json"]["authorization"] = {
            "status": "approved",
            "actor_id": "admin-1",
            "role": "admin",
            "verified": True,
            "policy_source": "local_authenticated_policy",
            "policy_id": "policy-example",
            "policy_revision": "2026-08-19T000000Z-r1",
        }
        policy_path = self.root / "access-policy.json"
        policy_path.write_text(json.dumps(self._policy()), encoding="utf-8")
        self._write_docs()
        self.assertEqual(validate_brand_bundle(self.root, policy=policy_path, actor_id="admin-1"), [])

    def test_policy_receipt_must_match_external_version(self) -> None:
        self._make_scoped()
        for document in self.docs.values():
            document["status"] = "active"
        self.docs["brand-profile.json"]["rights"]["status"] = "approved"
        self.docs["provenance.json"]["authorization"] = {
            "status": "approved",
            "actor_id": "admin-1",
            "role": "admin",
            "verified": True,
            "policy_source": "local_authenticated_policy",
            "policy_id": "old-policy",
            "policy_revision": "2026-08-18T000000Z-r1",
        }
        self._write_docs()
        errors = validate_brand_bundle(self.root, policy=self._policy(), actor_id="admin-1")
        self.assertTrue(any("policy_id does not match" in error for error in errors))
        self.assertTrue(any("policy_revision does not match" in error for error in errors))

    def test_policy_rejects_wildcard_identity(self) -> None:
        policy = self._policy()
        policy["role_mapping"]["member"] = ["*"]
        errors = validate_brand_bundle(self.root, policy=policy)
        self.assertTrue(any("wildcard identities are not allowed" in error for error in errors))

    def test_policy_allows_sparse_roles_and_multiple_roles(self) -> None:
        self._make_scoped()
        for document in self.docs.values():
            document["status"] = "active"
        self.docs["brand-profile.json"]["rights"]["status"] = "approved"
        self.docs["provenance.json"]["authorization"] = {
            "status": "approved",
            "actor_id": "admin-1",
            "role": "admin",
            "verified": True,
            "policy_source": "local_authenticated_policy",
            "policy_id": "policy-example",
            "policy_revision": "2026-08-19T000000Z-r1",
        }
        policy = self._policy()
        policy["role_mapping"] = {
            "lead": ["admin-1"],
            "admin": ["admin-1"],
            "member": [],
        }
        self._write_docs()
        self.assertEqual(validate_brand_bundle(self.root, policy=policy, actor_id="admin-1"), [])

    def test_requires_all_four_outputs(self) -> None:
        (self.root / "provenance.json").unlink()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("missing required file: provenance.json" in error for error in errors))

    def test_rejects_mixed_revision(self) -> None:
        self.docs["claim-registry.json"]["revision"] = "2026-08-19T000100Z-r2"
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("claim-registry.json.revision" in error for error in errors))

    def test_rejects_unlabelled_evidence(self) -> None:
        self.docs["brand-profile.json"]["voice"][0]["evidence_status"] = "maybe"
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("invalid value 'maybe'" in error for error in errors))

    def test_rejects_probable_secret(self) -> None:
        self.docs["brand-profile.json"]["identity"]["notes"] = "sk-" + ("a" * 16)
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("probable secret" in error for error in errors))

    def test_rejects_unapproved_claim_status_value(self) -> None:
        self.docs["claim-registry.json"]["claims"] = [
            {
                "id": "claim-1",
                "claim": "A claim",
                "status": "published",
                "evidence_status": "unverified",
                "source_ids": [],
            }
        ]
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("claim-registry.json.claims[0].status" in error for error in errors))

    def test_rejects_unsafe_brand_id(self) -> None:
        for document in self.docs.values():
            document["brand_id"] = "../unsafe-brand"
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("brand_id: must match lowercase-kebab format" in error for error in errors))

    def test_rejects_invalid_revision_format(self) -> None:
        for document in self.docs.values():
            document["revision"] = "2026-08-19T000000Z-r0"
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("revision: must match UTC timestamp-rN format" in error for error in errors))

    def test_rejects_duplicate_record_id(self) -> None:
        self.docs["brand-profile.json"]["terminology"] = [
            {
                "id": "voice-1",
                "value": "same ID",
                "evidence_status": "exact",
                "source_ids": ["source-1"],
            }
        ]
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("duplicate record ID 'voice-1'" in error for error in errors))

    def test_rejects_duplicate_source_id(self) -> None:
        duplicate = dict(self.docs["provenance.json"]["sources"][0])
        self.docs["provenance.json"]["sources"].append(duplicate)
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("duplicate source ID 'source-1'" in error for error in errors))

    def test_rejects_unknown_source_reference(self) -> None:
        self.docs["brand-profile.json"]["voice"][0]["source_ids"] = ["missing-source"]
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("unknown source ID 'missing-source'" in error for error in errors))

    def test_rejects_unknown_claim_reference(self) -> None:
        self.docs["template-registry.json"]["templates"] = [
            {
                "id": "template-1",
                "name": "A template",
                "purpose": "Test",
                "channel": "generic",
                "slots": [],
                "claim_ids": ["missing-claim"],
                "status": "needs_review",
                "evidence_status": "unverified",
                "source_ids": ["source-1"],
            }
        ]
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("unknown claim ID 'missing-claim'" in error for error in errors))

    def test_rejects_approved_claim_without_evidence_and_rights(self) -> None:
        self.docs["claim-registry.json"]["claims"] = [
            {
                "id": "claim-1",
                "claim": "A claim",
                "status": "approved",
                "evidence_status": "inferred",
                "source_ids": [],
                "rights": {"status": "blocked"},
            }
        ]
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("approved record requires exact or observed evidence" in error for error in errors))
        self.assertTrue(any("approved record requires non-empty source_ids" in error for error in errors))
        self.assertTrue(any("approved record requires rights.status approved or exact" in error for error in errors))

    def test_rejects_approved_template_without_rights(self) -> None:
        self.docs["template-registry.json"]["templates"] = [
            {
                "id": "template-1",
                "name": "A template",
                "purpose": "Test",
                "channel": "generic",
                "slots": [],
                "claim_ids": [],
                "status": "approved",
                "evidence_status": "observed",
                "source_ids": ["source-1"],
            }
        ]
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("template-registry.json.templates[0].rights: required object" in error for error in errors))

    def test_accepts_approved_claim_and_template(self) -> None:
        self._make_scoped()
        self.docs["claim-registry.json"]["claims"] = [
            {
                "id": "claim-1",
                "claim": "A supported claim",
                "status": "approved",
                "evidence_status": "exact",
                "source_ids": ["source-1"],
                "rights": {"status": "exact"},
            }
        ]
        self.docs["template-registry.json"]["templates"] = [
            {
                "id": "template-1",
                "name": "A template",
                "purpose": "Test",
                "channel": "generic",
                "slots": [],
                "claim_ids": ["claim-1"],
                "status": "approved",
                "evidence_status": "observed",
                "source_ids": ["source-1"],
                "rights": {"status": "approved"},
            }
        ]
        self.docs["provenance.json"]["authorization"] = {
            "status": "approved",
            "actor_id": "admin-1",
            "role": "admin",
            "verified": True,
            "policy_source": "local_authenticated_policy",
            "policy_id": "policy-example",
            "policy_revision": "2026-08-19T000000Z-r1",
        }
        self._write_docs()
        self.assertEqual(validate_brand_bundle(self.root, policy=self._policy(), actor_id="admin-1"), [])

    def test_active_bundle_requires_authorization_and_profile_rights(self) -> None:
        for document in self.docs.values():
            document["status"] = "active"
        self.docs["brand-profile.json"]["rights"]["status"] = "unverified"
        self.docs["provenance.json"]["authorization"]["status"] = "unverified"
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("active bundle requires brand-profile.json.rights" in error for error in errors))
        self.assertTrue(any("active bundle requires provenance.json.authorization" in error for error in errors))

    def test_rejects_wrong_required_field_type(self) -> None:
        self.docs["brand-profile.json"]["voice"] = ["not-an-object"]
        self._write_docs()
        errors = validate_brand_bundle(self.root)
        self.assertTrue(any("brand-profile.json.voice[0]: must be an object" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
