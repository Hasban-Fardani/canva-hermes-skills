#!/usr/bin/env python3
"""Validate a Social Content Studio JSON record with optional Brand Copy evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit


STATE_ORDER = [
    "IDEA",
    "BRIEFED",
    "COPY_REVIEW",
    "DESIGN_DRAFT",
    "BRAND_QA",
    "HUMAN_APPROVED",
    "SCHEDULED",
    "PUBLISHED",
    "MEASURED",
]

PLATFORMS = {"instagram", "facebook", "linkedin", "tiktok", "x", "youtube", "other"}
FORMATS = {"static", "carousel", "story", "reel", "short_video", "text"}
OBJECTIVES = {"awareness", "education", "engagement", "lead_generation", "conversion", "retention"}
SLIDE_ROLES = {"cover", "context", "explanation", "proof", "steps", "cta", "other"}
QA_STATUSES = {"pending", "pass", "fail", "not_applicable"}
APPROVAL_STATUSES = {"not_requested", "pending", "approved", "policy_approved", "rejected", "revoked"}
CLAIM_STATUSES = {"verified", "unverified", "expired", "rejected"}
EXPERIMENT_VARIABLES = {"none", "hook", "cta", "format", "visual", "caption", "offer"}
PREFLIGHT_STATUSES = {
    "duplicate_check": {"pending", "pass", "fail"},
    "kill_switch": {"pending", "clear", "blocked"},
    "account_access": {"pending", "pass", "fail"},
    "asset_rights": {"pending", "pass", "fail", "not_applicable"},
}

DEFAULT_BUDGETS = {
    "headline_chars": 60,
    "body_chars": 220,
    "cta_chars": 50,
    "caption_chars": 2200,
    "alt_text_chars": 1000,
    "hashtags_max": 10,
    "slides_max": 10,
}

CANONICAL_BRAND_STATUSES = {"draft", "active", "superseded"}
CANONICAL_APPROVED_RIGHTS = {"approved", "exact"}
CANONICAL_RIGHTS_STATUSES = {
    "approved",
    "blocked",
    "exact",
    "expired",
    "inferred",
    "needs_review",
    "observed",
    "unverified",
}

# Scope IDs are intentionally narrower than general content IDs.  They are
# stable, lowercase policy keys, never display names or user-entered labels.
SAFE_SCOPE_ID_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+){0,15}")
SAFE_REGISTRY_ID_RE = SAFE_SCOPE_ID_RE
POLICY_ROLES = {"admin", "lead", "reviewer", "member", "publisher"}
IDENTITY_SOURCES = {"authenticated", "local_policy", "local_authenticated_policy"}
TRUSTED_POLICY_SOURCE = "local_authenticated_policy"
POLICY_MODES = {"attended", "unattended"}
MEASUREMENT_WINDOWS = {"24h", "72h", "7d", "28d"}
MEASUREMENT_DATA_MODES = {"organic", "paid", "mixed", "unknown"}
MEASUREMENT_INTERPRETATIONS = {"descriptive", "directional", "operational_direction", "not_available"}
FORBIDDEN_METRIC_NAMES = {"saves", "reached_accounts"}
DEFAULT_MEASUREMENT_CADENCE = (
    {"window": "24h", "label": "provisional"},
    {"window": "72h", "label": "operational"},
    {"window": "7d", "label": "cohort"},
    {"window": "28d", "label": "portfolio"},
)
# Machine-readable defaults from the accepted content-metrics research. A
# Format-specific overrides may be recorded in measurement.plan.format_override
# or the provider-neutral measurement.plan.format_overrides map.
PILLAR_MEASUREMENT_DEFAULTS = {
    "awareness": {
        "primary_metric": "median_views",
        "denominator": "views",
        "guardrails": ["reach"],
    },
    "education": {
        "primary_metric": "saved",
        "denominator": "views",
        "guardrails": ["shares"],
    },
    "trust": {
        "primary_metric": "shares",
        "denominator": "views",
        "guardrails": ["saved"],
    },
    "proof": {
        "primary_metric": "shares",
        "denominator": "views",
        "guardrails": ["saved"],
    },
    "community": {
        "primary_metric": "total_interactions",
        "denominator": "views",
        "guardrails": ["comments", "shares"],
    },
    "offer": {
        "primary_metric": "profile_activity",
        "denominator": "views",
        "guardrails": ["link_clicks"],
        "format_overrides": {
            "story": {"primary_metric": "link_clicks", "denominator": "views"},
        },
    },
}

REQUIRED_TOP_LEVEL = {
    "schema_version",
    "content_id",
    "campaign_id",
    "brief_version",
    "copy_version",
    "state",
    "scope",
    "brand_id",
    "platform",
    "format",
    "objective",
    "audience",
    "content_pillar",
    "single_message",
    "source_context",
    "experiment",
    "slides",
    "caption",
    "alt_text",
    "claims",
    "design",
    "template_registry",
    "policy",
    "qa",
    "approval",
    "publishing",
    "measurement",
}

SECRET_KEYS = {
    "access_token",
    "refresh_token",
    "client_secret",
    "api_key",
    "password",
    "bearer_token",
    "private_key",
}

ABSOLUTE_CLAIM_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b100\s*%\b",
        r"\bpasti\b",
        r"\bterjamin\b",
        r"\btanpa\s+risiko\b",
        r"\bnomor\s*(?:1|satu)\b",
        r"\bterbaik\b",
        r"\btercepat\b",
        r"\bguaranteed\b",
        r"\brisk[- ]free\b",
        r"\bbest\b",
    )
]


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    path: str
    message: str


class Report:
    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def error(self, code: str, path: str, message: str) -> None:
        self.issues.append(Issue("error", code, path, message))

    def warning(self, code: str, path: str, message: str) -> None:
        self.issues.append(Issue("warning", code, path, message))

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    def passes(self, strict: bool = False) -> bool:
        return not self.errors and (not strict or not self.warnings)

    def to_dict(self, strict: bool = False, checksum: str | None = None) -> dict[str, Any]:
        return {
            "valid": self.passes(strict),
            "strict": strict,
            "summary": {"errors": len(self.errors), "warnings": len(self.warnings)},
            "computed_package_checksum": checksum,
            "issues": [asdict(issue) for issue in self.issues],
        }


def _state_at_least(state: Any, minimum: str) -> bool:
    return isinstance(state, str) and state in STATE_ORDER and STATE_ORDER.index(state) >= STATE_ORDER.index(minimum)


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _safe_scope_id(value: Any) -> bool:
    return isinstance(value, str) and bool(SAFE_SCOPE_ID_RE.fullmatch(value))


def _safe_registry_id(value: Any) -> bool:
    return isinstance(value, str) and bool(SAFE_REGISTRY_ID_RE.fullmatch(value))


def _opaque_provider_id(value: Any) -> bool:
    """Accept an exact provider identifier without treating it as a local key."""

    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    if re.search(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", value, re.IGNORECASE):
        return False
    if re.search(r"(?:^|\b)(?:sk-[A-Za-z0-9_-]{16,}|xox[baprs]-[A-Za-z0-9-]{16,}|gh[pousr]_[A-Za-z0-9]{20,})(?:$|\b)", value):
        return False
    return bool(value.strip())


def _provider_template_id_value(value: dict[str, Any]) -> str | None:
    for key in ("provider_template_id", "canva_template_id"):
        candidate = value.get(key)
        if candidate is not None:
            return candidate if isinstance(candidate, str) else None
    return None


def _validate_provider_template_id(value: Any, path: str, report: Report) -> str | None:
    """Validate optional exact Canva IDs and return the preserved value."""

    if not isinstance(value, dict):
        return None
    present = [
        (key, value.get(key))
        for key in ("provider_template_id", "canva_template_id")
        if key in value and value.get(key) is not None
    ]
    if len(present) > 1 and present[0][1] != present[1][1]:
        report.error(
            "provider_template_id_mismatch",
            path,
            "provider_template_id and canva_template_id must carry the same exact opaque ID when both are present.",
        )
    provider_id = present[0][1] if present else None
    if provider_id is not None and not _opaque_provider_id(provider_id):
        report.error(
            "provider_template_id_format",
            path,
            "Provider template IDs must be bounded opaque data without control characters or secrets; preserve them exactly.",
        )
        provider_id = None
    if provider_id is not None:
        provider = value.get("provider")
        if "provider_template_id" in value and provider != "canva":
            report.error("provider_template_provider", f"{path}.provider", "provider_template_id requires provider canva.")
        elif provider not in {"canva", None}:
            report.error("provider_template_provider", f"{path}.provider", "Provider template IDs must use provider canva.")
    return provider_id


def _scope_with_brand(scope: dict[str, str] | None) -> dict[str, str] | None:
    if scope is None:
        return None
    return {key: scope[key] for key in ("tenant_id", "client_id", "product_id", "brand_id")}


def _validate_scope(spec: dict[str, Any], report: Report) -> dict[str, str] | None:
    """Validate the canonical tenant/client/product/brand isolation tuple."""

    scope = spec.get("scope")
    if not isinstance(scope, dict):
        report.error("scope", "$.scope", "scope must be an object with tenant_id, client_id, and product_id.")
        return None
    expected_keys = {"tenant_id", "client_id", "product_id"}
    missing = sorted(expected_keys - scope.keys())
    for key in missing:
        report.error("scope_field", f"$.scope.{key}", "Canonical scope field is required.")
    unknown = sorted(set(scope) - expected_keys)
    if unknown:
        report.error("scope_field", "$.scope", "scope may contain only tenant_id, client_id, and product_id.")
    for key in expected_keys:
        value = scope.get(key)
        if not _safe_scope_id(value):
            report.error(
                "scope_id_format",
                f"$.scope.{key}",
                "Scope IDs must be lowercase kebab-case (letters and numbers separated by single hyphens).",
            )
    brand_id = spec.get("brand_id")
    if not _safe_scope_id(brand_id):
        report.error("brand_id_format", "$.brand_id", "brand_id must be a lowercase kebab-case ID.")
    if missing or unknown or not all(_safe_scope_id(scope.get(key)) for key in expected_keys) or not _safe_scope_id(brand_id):
        return None
    return {
        "tenant_id": scope["tenant_id"],
        "client_id": scope["client_id"],
        "product_id": scope["product_id"],
        "brand_id": brand_id,
    }


def _validate_remote_scope(
    value: Any,
    path: str,
    expected_scope: dict[str, str] | None,
    report: Report,
    *,
    required: bool,
) -> None:
    if value is None:
        if required:
            report.error("remote_scope_missing", path, "Every remote reference must carry the canonical scope.")
        return
    if not isinstance(value, dict):
        report.error("remote_scope_type", path, "remote_scope must be an object.")
        return
    expected_remote_scope = _scope_with_brand(expected_scope)
    if expected_remote_scope is None or value != expected_remote_scope:
        report.error("remote_scope_mismatch", path, "Remote reference scope must exactly match tenant, client, product, and brand.")


def _mapped_identity(policy: dict[str, Any], identity: Any, role: Any) -> bool:
    mapping = policy.get("role_mapping")
    return isinstance(mapping, dict) and role in POLICY_ROLES and isinstance(mapping.get(role), list) and identity in mapping[role]


def _validate_policy(spec: dict[str, Any], expected_scope: dict[str, str] | None, report: Report) -> dict[str, Any]:
    """Validate local RBAC and the fail-closed unattended policy."""

    raw = spec.get("policy")
    if not isinstance(raw, dict):
        report.error("policy", "$.policy", "policy must be an authenticated/local policy object.")
        return {"mode": "attended", "approval_required": True}
    for key in ("schema_version", "policy_id", "revision", "source"):
        if not _nonempty_string(raw.get(key)):
            report.error("policy_metadata", f"$.policy.{key}", "Policy snapshot requires schema_version, policy_id, revision, and source.")
    if raw.get("source") != TRUSTED_POLICY_SOURCE:
        report.error("policy_source", "$.policy.source", "Policy source must be local_authenticated_policy; embedded snapshots are not authority by themselves.")
    policy_scope = raw.get("scope")
    expected_policy_scope = {
        "tenant_id": expected_scope.get("tenant_id") if expected_scope else None,
        "client_id": expected_scope.get("client_id") if expected_scope else None,
        "product_id": expected_scope.get("product_id") if expected_scope else None,
        "brand_id": expected_scope.get("brand_id") if expected_scope else None,
    }
    if not isinstance(policy_scope, dict) or policy_scope != expected_policy_scope:
        report.error("policy_scope_mismatch", "$.policy.scope", "Policy snapshot scope must exactly match tenant, client, product, and brand.")
    source = raw.get("identity_source")
    if source not in IDENTITY_SOURCES:
        report.error("identity_source", "$.policy.identity_source", "Identity must come from authenticated or local_policy context.")
    actor_id = raw.get("actor_id")
    actor_role = raw.get("actor_role")
    if not _nonempty_string(actor_id):
        report.error("actor_id", "$.policy.actor_id", "The active actor must be identified by authenticated/local policy.")
    if actor_role not in POLICY_ROLES:
        report.error("actor_role", "$.policy.actor_role", "Unsupported active actor role.")
    mapping = raw.get("role_mapping")
    if not isinstance(mapping, dict):
        report.error("role_mapping", "$.policy.role_mapping", "role_mapping must be an object managed by lead/admin policy.")
        mapping = {}
    for role, identities in mapping.items():
        if role not in POLICY_ROLES:
            report.error("role_mapping_role", f"$.policy.role_mapping.{role}", "Unsupported role in role_mapping.")
        if not isinstance(identities, list) or any(
            not _nonempty_string(identity) or identity in {"*", "any", "prompt"} for identity in identities
        ):
            report.error("role_mapping_identity", f"$.policy.role_mapping.{role}", "Each mapped role must contain explicit identity IDs; an empty role list is allowed until that role is needed.")
    if _nonempty_string(actor_id) and actor_role in POLICY_ROLES and not _mapped_identity(raw, actor_id, actor_role):
        report.error("actor_not_mapped", "$.policy.actor_id", "The active identity must be present in its mapped role.")

    approval_required = raw.get("approval_required")
    if approval_required not in {True, False}:
        report.error("approval_required", "$.policy.approval_required", "approval_required must be an explicit boolean and defaults to true.")
        approval_required = True
    mode = raw.get("mode", "attended")
    if mode not in POLICY_MODES:
        report.error("policy_mode", "$.policy.mode", "Policy mode must be attended or unattended.")
        mode = "attended"

    unattended = raw.get("unattended")
    if not isinstance(unattended, dict):
        report.error("unattended", "$.policy.unattended", "unattended must be an explicit object; absent policy fails closed.")
        unattended = {"enabled": False}
    enabled = unattended.get("enabled")
    if not isinstance(enabled, bool):
        report.error("unattended_enabled", "$.policy.unattended.enabled", "unattended.enabled must be boolean.")
        enabled = False
    if enabled and mode != "unattended":
        report.error("unattended_mode", "$.policy.mode", "Unattended execution requires policy.mode unattended.")
    if mode == "unattended" and not enabled:
        report.error("unattended_disabled", "$.policy.unattended.enabled", "Unattended mode is disabled unless a lead/admin enables it.")
    if approval_required is False and not (mode == "unattended" and enabled is True):
        report.error("approval_required", "$.policy.approval_required", "Only an explicitly enabled unattended policy may set approval_required false; attended content fails closed with approval required.")
    if enabled:
        _validate_remote_scope(unattended.get("scope"), "$.policy.unattended.scope", expected_scope, report, required=True)
        enabled_by = unattended.get("enabled_by")
        enabled_by_role = unattended.get("enabled_by_role")
        if enabled_by_role not in {"lead", "admin"}:
            report.error("unattended_enabler_role", "$.policy.unattended.enabled_by_role", "Only lead or admin may enable unattended execution.")
        if not _nonempty_string(enabled_by) or not _mapped_identity(raw, enabled_by, enabled_by_role):
            report.error("unattended_enabler", "$.policy.unattended.enabled_by", "Unattended execution must be enabled by a mapped lead/admin identity.")
        if _parse_datetime(unattended.get("enabled_at")) is None:
            report.error("unattended_enabled_at", "$.policy.unattended.enabled_at", "Unattended enablement requires a timezone-aware timestamp.")
        preapproved = unattended.get("preapproved")
        if not isinstance(preapproved, dict):
            report.error("unattended_preapproved", "$.policy.unattended.preapproved", "Preapproved template, claim, and target lists are required.")
        else:
            for key in ("copy_recipe_ids", "template_ids", "claim_ids", "targets", "pillars", "formats"):
                values = preapproved.get(key)
                if not isinstance(values, list):
                    report.error("unattended_preapproved", f"$.policy.unattended.preapproved.{key}", "Preapproval lists must be arrays.")
                elif (key != "claim_ids" or spec.get("claims")) and not values:
                    report.error("unattended_preapproved", f"$.policy.unattended.preapproved.{key}", "Unattended policy requires explicit preapproval entries.")
                elif any(not _nonempty_string(item) for item in values):
                    report.error("unattended_preapproved", f"$.policy.unattended.preapproved.{key}", "Preapproval entries must be non-empty strings.")
            for key in ("template_versions", "copy_recipe_versions", "copy_recipe_brand_revisions"):
                values = preapproved.get(key)
                if not isinstance(values, dict):
                    report.error("unattended_preapproved", f"$.policy.unattended.preapproved.{key}", "Preapproved version maps must be objects.")
                elif any(not _nonempty_string(item) or not _nonempty_string(version) for item, version in values.items()):
                    report.error("unattended_preapproved", f"$.policy.unattended.preapproved.{key}", "Preapproved version maps require non-empty IDs and versions.")
            provider_ids = preapproved.get("template_provider_ids")
            template_ids = preapproved.get("template_ids", [])
            if not isinstance(provider_ids, dict):
                report.error("unattended_preapproved", "$.policy.unattended.preapproved.template_provider_ids", "Unattended template_provider_ids must be an alias-to-opaque-Canva-ID object.")
            else:
                for alias, provider_id in provider_ids.items():
                    if not _safe_registry_id(alias) or alias not in template_ids:
                        report.error("unattended_preapproved_provider_id", "$.policy.unattended.preapproved.template_provider_ids", "Provider-ID map keys must be safe IDs present in template_ids.")
                    if not _opaque_provider_id(provider_id):
                        report.error("unattended_preapproved_provider_id", f"$.policy.unattended.preapproved.template_provider_ids.{alias}", "Preapproved Canva provider IDs must be bounded opaque values preserved exactly.")
            field_budgets = preapproved.get("field_budgets")
            if not isinstance(field_budgets, dict) or not field_budgets:
                report.error("unattended_preapproved", "$.policy.unattended.preapproved.field_budgets", "Unattended generation requires explicit field budgets.")
            elif any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in field_budgets.values()):
                report.error("unattended_preapproved", "$.policy.unattended.preapproved.field_budgets", "Preapproved field budgets must be positive integers.")
        for key in ("policy_id", "policy_revision"):
            if not _nonempty_string(unattended.get(key)) or unattended.get(key) != raw.get("policy_id" if key == "policy_id" else "revision"):
                report.error("unattended_policy_revision", f"$.policy.unattended.{key}", "Unattended enablement must bind the exact policy ID and revision.")
    return {"mode": mode, "approval_required": approval_required, "unattended": unattended, "raw": raw}


def _validate_trusted_policy(
    spec: dict[str, Any],
    policy: dict[str, Any],
    expected_scope: dict[str, str] | None,
    state: Any,
    policy_context: Any,
    runtime_actor_id: str | None,
    report: Report,
) -> None:
    """Require a separately loaded policy authority for privileged states."""

    privileged = _state_at_least(state, "HUMAN_APPROVED") or policy.get("mode") == "unattended"
    embedded = policy.get("raw") if isinstance(policy.get("raw"), dict) else {}
    if policy_context is None:
        if privileged:
            report.error(
                "trusted_policy_required",
                "$.policy",
                "Privileged states require a separately loaded local_authenticated_policy; the embedded snapshot is audit-only.",
            )
        else:
            report.warning(
                "policy_untrusted",
                "$.policy",
                "Draft is usable with a pending policy snapshot, but cannot cross approval, unattended, schedule, or publish gates without trusted policy.",
            )
        return
    if not isinstance(policy_context, dict):
        report.error("trusted_policy_type", "$policy", "Trusted policy context must be an object loaded outside the content record.")
        return
    if policy_context is spec.get("policy") or policy_context is embedded:
        report.error(
            "trusted_policy_embedded",
            "$policy",
            "The trusted policy must be loaded separately; passing the mutable embedded policy object cannot authorize privileged content.",
        )
        return
    if policy_context.get("source") != TRUSTED_POLICY_SOURCE:
        report.error("trusted_policy_source", "$policy.source", "Trusted policy source must be local_authenticated_policy.")
    if policy_context.get("schema_version") != "1.0":
        report.error("trusted_policy_schema", "$policy.schema_version", "Trusted policy schema_version must be 1.0.")
    for key in ("policy_id", "revision"):
        if not _nonempty_string(policy_context.get(key)):
            report.error("trusted_policy_metadata", f"$policy.{key}", "Trusted policy requires policy_id and revision.")
    expected_policy_scope = {
        "tenant_id": expected_scope.get("tenant_id") if expected_scope else None,
        "client_id": expected_scope.get("client_id") if expected_scope else None,
        "product_id": expected_scope.get("product_id") if expected_scope else None,
        "brand_id": expected_scope.get("brand_id") if expected_scope else None,
    }
    if policy_context.get("scope") != expected_policy_scope:
        report.error("trusted_policy_scope", "$policy.scope", "Trusted policy scope must exactly match the content isolation key.")
    if policy_context.get("policy_id") != embedded.get("policy_id") or policy_context.get("revision") != embedded.get("revision"):
        report.error("trusted_policy_revision", "$policy", "Trusted policy ID/revision must match the content policy snapshot.")
    if policy_context.get("role_mapping") != embedded.get("role_mapping"):
        report.error("trusted_policy_roles", "$policy.role_mapping", "Trusted role mapping must match the content snapshot exactly.")
    embedded_unattended = embedded.get("unattended")
    if isinstance(embedded_unattended, dict) and embedded_unattended.get("enabled") is True:
        embedded_preapproved = embedded_unattended.get("preapproved")
        embedded_provider_ids = embedded_preapproved.get("template_provider_ids") if isinstance(embedded_preapproved, dict) else None
        trusted_unattended = policy_context.get("unattended")
        trusted_preapproved = trusted_unattended.get("preapproved") if isinstance(trusted_unattended, dict) else None
        trusted_provider_ids = trusted_preapproved.get("template_provider_ids") if isinstance(trusted_preapproved, dict) else None
        if not isinstance(trusted_provider_ids, dict):
            report.error(
                "trusted_policy_preapproval",
                "$policy.unattended.preapproved.template_provider_ids",
                "Trusted unattended policy must carry the exact template_provider_ids preapproval map; the embedded map is audit-only.",
            )
        elif trusted_provider_ids != embedded_provider_ids:
            report.error(
                "trusted_policy_preapproval",
                "$policy.unattended.preapproved.template_provider_ids",
                "Trusted template provider-ID preapproval must exactly match the content audit snapshot.",
            )
        else:
            trusted_template_ids = embedded_preapproved.get("template_ids", []) if isinstance(embedded_preapproved, dict) else []
            for alias, provider_id in trusted_provider_ids.items():
                if not _safe_registry_id(alias) or alias not in trusted_template_ids or not _opaque_provider_id(provider_id):
                    report.error(
                        "trusted_policy_preapproval",
                        "$policy.unattended.preapproved.template_provider_ids",
                        "Trusted template provider-ID preapproval must use safe approved aliases and exact bounded opaque IDs.",
                    )
    if runtime_actor_id is None or not _nonempty_string(runtime_actor_id):
        if privileged:
            report.error("trusted_actor_required", "$policy", "Privileged validation requires the current authenticated actor from runtime, not the content record.")
    elif isinstance(policy_context.get("actor_id"), str) and policy_context.get("actor_id") != runtime_actor_id:
        report.error("trusted_policy_actor", "$policy.actor_id", "The runtime actor must exactly match the actor in the trusted policy receipt.")
    if privileged and isinstance(embedded.get("actor_id"), str):
        approval = spec.get("approval")
        publishing = spec.get("publishing")
        if _state_at_least(state, "SCHEDULED") and isinstance(publishing, dict):
            expected_actor = publishing.get("publisher_id")
            if _nonempty_string(expected_actor) and runtime_actor_id != expected_actor:
                report.error("trusted_actor_publisher", "$.publishing.publisher_id", "Runtime actor must exactly match the authenticated publisher for scheduling or publishing.")
        elif isinstance(approval, dict) and approval.get("status") == "approved":
            expected_actor = approval.get("approver_id")
            if runtime_actor_id != expected_actor or embedded.get("actor_id") != expected_actor:
                report.error("trusted_actor_approval", "$.approval.approver_id", "Runtime actor, policy actor, and approved package approver must match exactly.")
        elif runtime_actor_id != embedded.get("actor_id"):
            report.error("trusted_policy_actor", "$.policy.actor_id", "The runtime actor must exactly match the content policy actor; content alone cannot impersonate an identity.")
        unattended = embedded.get("unattended")
        if isinstance(unattended, dict) and unattended.get("enabled") is True:
            enabled_by = unattended.get("enabled_by")
            if state == "HUMAN_APPROVED" and enabled_by != runtime_actor_id:
                report.error("trusted_actor_unattended", "$.policy.unattended.enabled_by", "Runtime actor must exactly match the trusted unattended enabler for policy-approved content.")
    mapping = policy_context.get("role_mapping")
    if isinstance(mapping, dict):
        for role, identities in mapping.items():
            if role not in POLICY_ROLES or not isinstance(identities, list) or any(identity in {"*", "any", "prompt"} for identity in identities):
                report.error("trusted_policy_roles", "$policy.role_mapping", "Trusted role mapping may not contain wildcard or prompt identities.")


BRAND_BUNDLE_FILES = ("brand-profile.json", "claim-registry.json", "template-registry.json", "provenance.json")


def _load_brand_bundle_validator() -> Any:
    """Load the sibling Brand Copy validator without copying its contract here."""

    validator_path = Path(__file__).resolve().parents[2] / "brand-copy-studio" / "scripts" / "validate_brand_bundle.py"
    if not validator_path.is_file():
        return None
    module_spec = importlib.util.spec_from_file_location("social_content_brand_bundle_validator", validator_path)
    if module_spec is None or module_spec.loader is None:
        return None
    module = importlib.util.module_from_spec(module_spec)
    try:
        module_spec.loader.exec_module(module)
    except (ImportError, OSError, SyntaxError, TypeError, ValueError):
        return None
    return module


def _read_brand_bundle_documents(root: Path, report: Report) -> dict[str, dict[str, Any]] | None:
    documents: dict[str, dict[str, Any]] = {}
    for filename in BRAND_BUNDLE_FILES:
        path = root / filename
        try:
            with path.open("r", encoding="utf-8") as handle:
                document = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            report.error("brand_bundle_read", f"$brand_bundle/{filename}", f"Cannot read validated Brand Copy bundle file: {exc}.")
            continue
        if not isinstance(document, dict):
            report.error("brand_bundle_type", f"$brand_bundle/{filename}", "Brand Copy bundle files must contain JSON objects.")
            continue
        documents[filename] = document
    return documents if len(documents) == len(BRAND_BUNDLE_FILES) else None


def _validate_brand_bundle(
    brand_bundle: str | Path | None,
    expected_scope: dict[str, str] | None,
    state: Any,
    spec: dict[str, Any],
    report: Report,
    *,
    brand_policy_context: Any = None,
    brand_actor_id: str | None = None,
) -> dict[str, Any] | None:
    """Validate an external four-file Brand Copy bundle for privileged use."""

    policy = spec.get("policy") if isinstance(spec.get("policy"), dict) else {}
    claims = spec.get("claims")
    has_claims = isinstance(claims, list) and bool(claims)
    has_recipe = any(spec.get(key) is not None for key in ("copy_recipe_id", "copy_recipe_version", "brand_revision"))
    privileged = _state_at_least(state, "HUMAN_APPROVED") or policy.get("mode") == "unattended"
    if brand_bundle is None:
        if privileged and (has_claims or has_recipe or policy.get("mode") == "unattended"):
            report.error(
                "brand_bundle_required",
                "$brand_bundle",
                "Privileged claims, copy recipes, and unattended generation require a validated scoped four-file Brand Copy bundle; profile-only input remains attended.",
            )
        return None
    if not isinstance(brand_bundle, (str, Path)):
        report.error("brand_bundle_type", "$brand_bundle", "brand_bundle must be a validated Brand Copy bundle directory path.")
        return None
    root = Path(brand_bundle).expanduser()
    if not root.is_dir():
        report.error("brand_bundle_path", "$brand_bundle", "Brand Copy bundle directory does not exist.")
        return None
    documents = _read_brand_bundle_documents(root, report)
    if documents is None:
        return None

    profile = documents["brand-profile.json"]
    if "scope" in profile and not isinstance(profile.get("scope"), dict):
        report.error("brand_bundle_scope", "$brand_bundle/brand-profile.json.scope", "Brand Copy profile scope must be an object.")
    profile_scope = profile.get("scope") if isinstance(profile.get("scope"), dict) else {}
    unknown_profile_scope = sorted(set(profile_scope) - {"tenant_id", "client_id", "product_id", "parent_brand_revision"})
    if unknown_profile_scope:
        report.error("brand_bundle_scope", "$brand_bundle/brand-profile.json.scope", "Brand Copy profile scope contains unsupported fields.")
    for field in ("tenant_id", "client_id", "product_id", "parent_brand_revision"):
        if field in profile and field in profile_scope and profile.get(field) != profile_scope.get(field):
            report.error(
                "brand_bundle_scope_conflict",
                f"$brand_bundle/brand-profile.json.scope.{field}",
                "Brand Copy top-level and nested scope fields must agree exactly.",
            )
    bundle_product = profile_scope.get("product_id")
    if bundle_product is None and "product_id" in profile and not isinstance(profile.get("scope"), dict):
        bundle_product = profile.get("product_id")
    expected_product = expected_scope.get("product_id") if expected_scope else None
    if bundle_product not in (None, expected_product):
        report.error("brand_bundle_scope", "$brand_bundle/brand-profile.json.scope.product_id", "Brand Copy master/overlay product scope must be null for a master or exactly match the content product.")
    bundle_scope = {
        "tenant_id": profile_scope.get("tenant_id", profile.get("tenant_id")),
        "client_id": profile_scope.get("client_id", profile.get("client_id")),
        "product_id": bundle_product,
        "parent_brand_revision": profile_scope.get("parent_brand_revision", profile.get("parent_brand_revision")),
    }
    if expected_scope and (
        bundle_scope["tenant_id"] != expected_scope.get("tenant_id")
        or bundle_scope["client_id"] != expected_scope.get("client_id")
        or profile.get("brand_id") != expected_scope.get("brand_id")
    ):
        report.error("brand_bundle_scope", "$brand_bundle", "Brand Copy bundle tenant, client, and brand must match the content isolation scope.")

    requires_brand_authority = privileged and (has_claims or has_recipe or policy.get("mode") == "unattended")
    brand_authority_missing = requires_brand_authority and (
        brand_policy_context is None or not _nonempty_string(brand_actor_id)
    )
    if brand_authority_missing:
        report.error(
            "brand_bundle_authority",
            "$brand_bundle",
            "Privileged Brand Copy evidence requires a separately loaded brand policy and runtime brand activation actor; content policy/current actor cannot authorize it.",
        )

    validator = _load_brand_bundle_validator()
    if validator is None:
        report.error("brand_bundle_validator", "$brand_bundle", "The sibling Brand Copy bundle validator is unavailable; fail closed for privileged use.")
    elif not brand_authority_missing:
        bundle_expected_scope = {
            "tenant_id": bundle_scope["tenant_id"],
            "client_id": bundle_scope["client_id"],
            "product_id": bundle_product,
            "parent_brand_revision": bundle_scope["parent_brand_revision"],
        }
        try:
            errors = validator.validate_brand_bundle(
                root,
                expected_brand_id=expected_scope.get("brand_id") if expected_scope else None,
                expected_scope=bundle_expected_scope,
                policy=brand_policy_context,
                actor_id=brand_actor_id,
            )
        except (AttributeError, TypeError, OSError, ValueError) as exc:
            errors = [f"validator invocation failed: {exc}"]
        for error in errors:
            report.error("brand_bundle_invalid", "$brand_bundle", str(error))
    return {
        "root": root,
        "documents": documents,
        "profile": profile,
        "product_id": bundle_product,
        "revision": profile.get("revision"),
        "claims": documents.get("claim-registry.json", {}).get("claims", []),
        "templates": documents.get("template-registry.json", {}).get("templates", []),
    }


def _validate_copy_recipe(
    spec: dict[str, Any],
    policy: dict[str, Any],
    state: Any,
    brand_bundle: dict[str, Any] | None,
    report: Report,
) -> None:
    """Bind bounded unattended generation to an approved Brand Copy recipe."""

    recipe_id = spec.get("copy_recipe_id")
    recipe_version = spec.get("copy_recipe_version")
    brand_revision = spec.get("brand_revision")
    provided = [recipe_id, recipe_version, brand_revision]
    if recipe_id is None and recipe_version is None and brand_revision is None:
        if policy.get("mode") == "unattended" and policy.get("unattended", {}).get("enabled") is True:
            report.error("copy_recipe_required", "$", "Unattended generation requires copy_recipe_id, copy_recipe_version, and brand_revision.")
        return
    if not _safe_registry_id(recipe_id):
        report.error("copy_recipe_id", "$.copy_recipe_id", "copy_recipe_id must be a lowercase-kebab Brand Copy template-registry ID.")
    if not _nonempty_string(recipe_version):
        report.error("copy_recipe_version", "$.copy_recipe_version", "copy_recipe_version is required when a recipe is selected.")
    if not _nonempty_string(brand_revision):
        report.error("brand_revision", "$.brand_revision", "brand_revision is required to bind a copy recipe to the active Brand Copy revision.")
    if recipe_id is None and any(value is not None for value in provided[1:]):
        report.error("copy_recipe_incomplete", "$", "Recipe version and brand revision cannot be supplied without copy_recipe_id.")

    if policy.get("mode") != "unattended" or policy.get("unattended", {}).get("enabled") is not True:
        return
    preapproved = policy.get("unattended", {}).get("preapproved", {})
    if not isinstance(preapproved, dict):
        return
    recipe_ids = preapproved.get("copy_recipe_ids", [])
    if recipe_id not in recipe_ids:
        report.error("unattended_copy_recipe_not_allowed", "$.copy_recipe_id", "Unattended generation may use only an explicitly preapproved copy recipe.")
    recipe_versions = preapproved.get("copy_recipe_versions", {})
    if isinstance(recipe_versions, dict) and recipe_versions.get(recipe_id) != recipe_version:
        report.error("unattended_copy_recipe_version", "$.copy_recipe_version", "Unattended generation must use the exact preapproved recipe version.")
    recipe_revisions = preapproved.get("copy_recipe_brand_revisions", {})
    if isinstance(recipe_revisions, dict) and recipe_revisions.get(recipe_id) != brand_revision:
        report.error("unattended_copy_recipe_revision", "$.brand_revision", "Unattended generation must use the exact preapproved Brand Copy revision.")
    if spec.get("content_pillar") not in preapproved.get("pillars", []):
        report.error("unattended_pillar_not_allowed", "$.content_pillar", "Unattended generation is limited to preapproved content pillars.")
    if spec.get("format") not in preapproved.get("formats", []):
        report.error("unattended_format_not_allowed", "$.format", "Unattended generation is limited to preapproved formats.")

    field_budgets = preapproved.get("field_budgets")
    if isinstance(field_budgets, dict):
        observed_lengths: dict[str, int] = {}
        slides = spec.get("slides") if isinstance(spec.get("slides"), list) else []
        observed_lengths["slides_max"] = len(slides)
        headline_values = [slide.get("headline", "") for slide in slides if isinstance(slide, dict)]
        body_values = [slide.get("body", "") for slide in slides if isinstance(slide, dict)]
        cta_values = [slide.get("cta", "") for slide in slides if isinstance(slide, dict)]
        observed_lengths["headline_chars"] = max((len(value) for value in headline_values if isinstance(value, str)), default=0)
        observed_lengths["body_chars"] = max((len(value) for value in body_values if isinstance(value, str)), default=0)
        observed_lengths["cta_chars"] = max((len(value) for value in cta_values if isinstance(value, str)), default=0)
        caption = spec.get("caption") if isinstance(spec.get("caption"), dict) else {}
        observed_lengths["caption_chars"] = sum(len(caption.get(key, "")) for key in ("hook", "body", "cta") if isinstance(caption.get(key), str))
        observed_lengths["alt_text_chars"] = len(spec.get("alt_text")) if isinstance(spec.get("alt_text"), str) else 0
        observed_lengths["hashtags_max"] = len(caption.get("hashtags", [])) if isinstance(caption.get("hashtags"), list) else 0
        for key, observed in observed_lengths.items():
            allowed = field_budgets.get(key)
            if isinstance(allowed, int) and observed > allowed:
                report.error("unattended_field_budget", f"$.policy.unattended.preapproved.field_budgets.{key}", f"Generated content exceeds the preapproved {key} budget.")

    if brand_bundle is None:
        return
    templates = brand_bundle.get("templates", []) if isinstance(brand_bundle, dict) else []
    matches = [record for record in templates if isinstance(record, dict) and record.get("id") == recipe_id]
    if not matches:
        report.error("copy_recipe_unregistered", "$.copy_recipe_id", "copy_recipe_id must resolve to an approved Brand Copy template-registry record in the validated bundle.")
        return
    record = matches[0]
    if record.get("status") != "approved":
        report.error("copy_recipe_unapproved", "$.copy_recipe_id", "The selected Brand Copy recipe is not approved in the validated bundle.")
    record_version = record.get("version")
    expected_version = record_version if _nonempty_string(record_version) else brand_bundle.get("revision")
    if _nonempty_string(expected_version) and recipe_version != expected_version:
        report.error("copy_recipe_version_mismatch", "$.copy_recipe_version", "copy_recipe_version must exactly match the approved Brand Copy registry record or bundle revision.")
    if _nonempty_string(brand_bundle.get("revision")) and brand_revision != brand_bundle.get("revision"):
        report.error("brand_revision_mismatch", "$.brand_revision", "brand_revision must exactly match the validated Brand Copy bundle revision.")


def _validate_brand_claims(
    claims: Any,
    state: Any,
    brand_bundle: dict[str, Any] | None,
    report: Report,
) -> None:
    """Match privileged content claims to exact approved external claim records."""

    if not isinstance(claims, list) or not claims or brand_bundle is None:
        return
    external_claims = {
        record.get("id"): record
        for record in brand_bundle.get("claims", [])
        if isinstance(record, dict) and _nonempty_string(record.get("id"))
    }
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            continue
        claim_id = claim.get("claim_id")
        external = external_claims.get(claim_id)
        path = f"$.claims[{index}]"
        if not isinstance(external, dict):
            report.error("claim_unregistered", f"{path}.claim_id", "Privileged content claim must resolve to an approved external Brand Copy claim record.")
            continue
        if external.get("status") != "approved":
            report.error("claim_external_unapproved", f"{path}.claim_id", "External Brand Copy claim is not approved.")
        if external.get("claim") != claim.get("text"):
            report.error("claim_text_mismatch", f"{path}.text", "Content claim wording must exactly match the approved external claim record.")
        if external.get("evidence_status") not in {"exact", "observed"}:
            report.error("claim_external_evidence", f"{path}.claim_id", "External Brand Copy claim lacks approved evidence status.")
        rights = external.get("rights")
        if not isinstance(rights, dict) or rights.get("status") not in {"approved", "exact"}:
            report.error("claim_external_rights", f"{path}.claim_id", "External Brand Copy claim lacks approved rights.")
        expires_at = external.get("expires_at")
        if not isinstance(expires_at, str) or claim.get("expires_on") != expires_at[:10]:
            report.error("claim_expiry_mismatch", f"{path}.expires_on", "Content claim expiry must match the external approved claim expiry.")


def _validate_template_registry(
    spec: dict[str, Any], expected_scope: dict[str, str] | None, policy: dict[str, Any], report: Report, today: date
) -> list[dict[str, Any]]:
    raw = spec.get("template_registry")
    if not isinstance(raw, dict):
        report.error("template_registry", "$.template_registry", "template_registry must be an object.")
        return []
    entries = raw.get("entries")
    if not isinstance(entries, list):
        report.error("template_registry_entries", "$.template_registry.entries", "template_registry.entries must be a list.")
        return []
    seen: set[tuple[Any, Any]] = set()
    valid_entries: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        path = f"$.template_registry.entries[{index}]"
        if not isinstance(entry, dict):
            report.error("template_registry_entry", path, "Each template registry entry must be an object.")
            continue
        _validate_provider_template_id(entry, path, report)
        template_id = entry.get("template_id")
        version = entry.get("version")
        if not _safe_registry_id(template_id):
            report.error("template_registry_id", f"{path}.template_id", "Template IDs must be lowercase kebab-case registry IDs.")
        if not _nonempty_string(version):
            report.error("template_registry_version", f"{path}.version", "Approved templates require an explicit version.")
        key = (template_id, version)
        if key in seen:
            report.error("template_registry_duplicate", path, "Template ID and version must be unique within a scope.")
        seen.add(key)
        _validate_remote_scope(entry.get("scope"), f"{path}.scope", expected_scope, report, required=True)
        status = entry.get("status")
        if status not in {"proposed", "approved", "retired"}:
            report.error("template_registry_status", f"{path}.status", "Template status must be proposed, approved, or retired.")
        if status == "approved":
            approver = entry.get("approved_by")
            approver_role = entry.get("approved_by_role")
            if approver_role not in {"lead", "admin"}:
                report.error("template_registry_approver_role", f"{path}.approved_by_role", "Only a mapped lead/admin can approve a reusable template.")
            if not _nonempty_string(approver) or not _mapped_identity(policy.get("raw", {}), approver, approver_role):
                report.error("template_registry_approver", f"{path}.approved_by", "Template approver must be a mapped lead/admin identity from local policy.")
            approved_at = _parse_datetime(entry.get("approved_at"))
            if approved_at is None:
                report.error("template_registry_approved_at", f"{path}.approved_at", "Approved templates require a timezone-aware approval timestamp.")
            elif approved_at.date() > today:
                report.error("template_registry_future", f"{path}.approved_at", "Template approval cannot be in the future.")
        if isinstance(template_id, str) and _safe_registry_id(template_id) and _nonempty_string(version):
            valid_entries.append(entry)

    unattended = policy.get("unattended") if policy.get("mode") == "unattended" else {}
    if isinstance(unattended, dict) and unattended.get("enabled") is True:
        preapproved = unattended.get("preapproved")
        template_ids = preapproved.get("template_ids", []) if isinstance(preapproved, dict) else []
        provider_ids = preapproved.get("template_provider_ids", {}) if isinstance(preapproved, dict) else {}
        for template_id in template_ids:
            matches = [entry for entry in valid_entries if entry.get("template_id") == template_id and entry.get("status") == "approved"]
            if not matches:
                report.error("unattended_template_unapproved", "$.policy.unattended.preapproved.template_ids", "Every unattended template must be an approved registry entry.")
            elif any(entry.get("scope") != _scope_with_brand(expected_scope) for entry in matches):
                report.error("unattended_template_scope", "$.template_registry.entries", "Unattended templates must be approved in the exact current scope.")
            else:
                registry_provider_ids = {
                    _provider_template_id_value(entry)
                    for entry in matches
                    if _provider_template_id_value(entry) is not None
                }
                expected_provider_id = provider_ids.get(template_id) if isinstance(provider_ids, dict) else None
                if registry_provider_ids and expected_provider_id not in registry_provider_ids:
                    report.error("unattended_template_provider_id", "$.policy.unattended.preapproved.template_provider_ids", "Unattended provider-ID preapproval must exactly match the scoped approved registry entry.")
                elif expected_provider_id is not None and not registry_provider_ids:
                    report.error("unattended_template_provider_id", "$.template_registry.entries", "A preapproved provider ID must be recorded on the approved scoped template registry entry.")
    return valid_entries


def _valid_https_url(value: Any) -> bool:
    if not _nonempty_string(value):
        return False
    parsed = urlsplit(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _normalize_cta(value: str) -> str:
    return re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE).strip()


def _tokens(value: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[\w]+", value, flags=re.UNICODE)
        if len(token) >= 4
    }


def _all_content_text(spec: dict[str, Any]) -> str:
    chunks = [str(spec.get("single_message", ""))]
    for slide in spec.get("slides", []) if isinstance(spec.get("slides"), list) else []:
        if isinstance(slide, dict):
            chunks.extend(str(slide.get(key, "")) for key in ("headline", "body", "cta"))
    caption = spec.get("caption")
    if isinstance(caption, dict):
        chunks.extend(str(caption.get(key, "")) for key in ("hook", "body", "cta"))
    return "\n".join(chunks)


def _scan_for_secrets(value: Any, report: Report, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).casefold() in SECRET_KEYS:
                report.error("secret_field", child_path, "Credential-like fields are forbidden in content records.")
            _scan_for_secrets(child, report, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_for_secrets(child, report, f"{path}[{index}]")
    elif isinstance(value, str) and re.search(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", value):
        report.error("secret_value", path, "A bearer-token-like value is forbidden in content records.")


def _is_canonical_brand_profile(brand: dict[str, Any]) -> bool:
    """Detect the Brand Copy Studio profile without rejecting legacy profiles."""

    return "revision" in brand or any(
        key in brand for key in ("rights", "terminology", "copy_constraints", "visual_copy_cues")
    )


def _validate_brand(
    brand: Any,
    report: Report,
    expected_scope: dict[str, str] | None = None,
    *,
    schema_version: Any = None,
    state: Any = None,
) -> tuple[str | None, dict[str, int]]:
    budgets = dict(DEFAULT_BUDGETS)
    if brand is None:
        return None, budgets
    if not isinstance(brand, dict):
        report.error("brand_type", "$brand", "Brand profile must be a JSON object.")
        return None, budgets

    if brand.get("schema_version") == "1.0":
        if _state_at_least(state, "HUMAN_APPROVED"):
            report.error("legacy_brand_migration_required", "$brand.schema_version", "Legacy Brand Copy schema 1.0 cannot authorize final multi-tenant content; migrate to scoped schema 1.1.")
        else:
            report.warning("legacy_brand_compatibility", "$brand.schema_version", "Legacy Brand Copy schema 1.0 is draft-only compatibility and must be migrated before final approval.")

    brand_id = brand.get("brand_id")
    if not _nonempty_string(brand_id):
        report.error("brand_id", "$brand.brand_id", "Brand profile needs a non-empty brand_id.")
        brand_id = None

    if "scope" in brand and not isinstance(brand.get("scope"), dict):
        report.error("brand_scope_type", "$brand.scope", "Brand profile scope must be an object.")
    profile_scope = brand.get("scope") if isinstance(brand.get("scope"), dict) else {}
    unknown_profile_scope = sorted(set(profile_scope) - {"tenant_id", "client_id", "product_id", "parent_brand_revision"})
    if unknown_profile_scope:
        report.error("brand_scope_field", "$brand.scope", "Brand profile scope contains unsupported fields.")
    for field in ("tenant_id", "client_id", "product_id", "parent_brand_revision"):
        if field in brand and field in profile_scope and brand.get(field) != profile_scope.get(field):
            report.error(
                "brand_scope_conflict",
                f"$brand.scope.{field}",
                "Brand profile top-level and nested scope fields must agree exactly.",
            )
    profile_tenant = brand.get("tenant_id") or profile_scope.get("tenant_id")
    profile_client = brand.get("client_id") or profile_scope.get("client_id")
    profile_product = brand.get("product_id") if brand.get("product_id") is not None else profile_scope.get("product_id")
    profile_parent_revision = brand.get("parent_brand_revision") or profile_scope.get("parent_brand_revision")
    content_tenant = expected_scope.get("tenant_id") if expected_scope else None
    content_client = expected_scope.get("client_id") if expected_scope else None
    content_product = expected_scope.get("product_id") if expected_scope else None
    profile_scope_fields = {"tenant_id", "client_id", "product_id", "parent_brand_revision"}
    scope_supplied = "scope" in brand or any(field in brand for field in profile_scope_fields)

    def validate_profile_scope(*, canonical: bool) -> None:
        if expected_scope is None:
            return
        if canonical and brand.get("schema_version") == "1.0" and not scope_supplied:
            report.warning(
                "legacy_brand_scope",
                "$brand",
                "Legacy Brand Copy schema 1.0 profile has no tenant/client/product scope; it is readable for drafts only and must be migrated before final approval.",
            )
            return
        if canonical or scope_supplied or any(value is not None for value in (profile_tenant, profile_client, profile_product)):
            if not _safe_scope_id(profile_tenant) or profile_tenant != content_tenant:
                report.error("brand_tenant_mismatch", "$brand.tenant_id", "Brand profile tenant_id must match the content scope.")
            if not _safe_scope_id(profile_client) or profile_client != content_client:
                report.error("brand_client_mismatch", "$brand.client_id", "Brand profile client_id must match the content scope.")
            if profile_product is not None:
                if not _safe_scope_id(profile_product):
                    report.error("brand_product_format", "$brand.product_id", "Brand profile product_id must be a lowercase kebab-case ID or null for a master profile.")
                elif profile_product != content_product:
                    report.error("brand_product_mismatch", "$brand.product_id", "A product overlay must match the content product_id.")
                if canonical and not _nonempty_string(profile_parent_revision):
                    report.error("brand_parent_revision", "$brand.parent_brand_revision", "A product overlay requires parent_brand_revision.")
            elif canonical:
                # A canonical master is reusable across products only when it
                # is explicitly product-neutral; absent/null product_id is the
                # only permitted master form.
                if profile_parent_revision not in (None, ""):
                    report.error("brand_parent_revision", "$brand.parent_brand_revision", "A canonical master must not carry parent_brand_revision.")
        elif schema_version == "1.1" and _state_at_least(state, "HUMAN_APPROVED"):
            report.error("legacy_brand_scope_required", "$brand", "Legacy brand profiles cannot authorize final multi-tenant content until migrated to scoped Brand Copy data.")
        elif schema_version == "1.1":
            report.warning("legacy_brand_scope", "$brand", "Legacy brand profile has no tenant/client scope; migrate before final approval.")

    if _is_canonical_brand_profile(brand):
        validate_profile_scope(canonical=True)
        status = brand.get("status")
        if status not in CANONICAL_BRAND_STATUSES:
            report.error(
                "canonical_brand_status",
                "$brand.status",
                "Canonical Brand Copy Studio status must be draft, active, or superseded.",
            )
        elif status == "draft":
            report.warning(
                "canonical_brand_draft",
                "$brand.status",
                "Draft canonical brand values cannot authorize final branded output.",
            )
        elif status == "superseded":
            report.error(
                "canonical_brand_superseded",
                "$brand.status",
                "A superseded canonical brand profile cannot be used.",
            )

        rights = brand.get("rights")
        if not isinstance(rights, dict):
            report.error("canonical_brand_rights", "$brand.rights", "Canonical brand profile needs a rights object.")
        else:
            rights_status = rights.get("status")
            if rights_status not in CANONICAL_RIGHTS_STATUSES:
                report.error("canonical_brand_rights", "$brand.rights.status", "Canonical rights status is invalid.")
            elif status == "active" and rights_status not in CANONICAL_APPROVED_RIGHTS:
                report.error(
                    "canonical_brand_rights",
                    "$brand.rights.status",
                    "An active canonical brand profile requires rights.status approved or exact.",
                )

        _scan_for_secrets(brand, report, "$brand")
        # Canonical profiles deliberately do not carry the legacy template
        # budget object. Consumers use validator defaults unless a separate
        # approved legacy profile supplies explicit budgets.
        return brand_id if isinstance(brand_id, str) else None, budgets

    validate_profile_scope(canonical=False)
    status = brand.get("status")
    if status not in {"draft", "approved", "retired"}:
        report.error("brand_status", "$brand.status", "Brand status must be draft, approved, or retired.")
    elif status == "draft":
        report.warning("brand_unapproved", "$brand.status", "Draft brand values cannot authorize final branded output.")
    elif status == "retired":
        report.error("brand_retired", "$brand.status", "A retired brand profile cannot be used.")

    owner = brand.get("owner")
    if status == "approved" and (not _nonempty_string(owner) or str(owner).casefold() == "unassigned"):
        report.error("brand_owner", "$brand.owner", "An approved brand profile needs an accountable owner.")

    visual = brand.get("visual")
    if status == "approved" and isinstance(visual, dict):
        for collection_name in ("colors", "fonts"):
            collection = visual.get(collection_name, [])
            if isinstance(collection, list):
                for index, item in enumerate(collection):
                    if isinstance(item, dict) and item.get("status") == "unverified":
                        report.error(
                            "brand_value_unverified",
                            f"$brand.visual.{collection_name}[{index}]",
                            "Approved profiles cannot contain unverified normative visual values.",
                        )

    templates = brand.get("templates")
    if isinstance(templates, dict):
        default = templates.get("default")
        if isinstance(default, dict):
            configured = default.get("field_budgets")
            if isinstance(configured, dict):
                for key, fallback in DEFAULT_BUDGETS.items():
                    value = configured.get(key, fallback)
                    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                        report.error("brand_budget", f"$brand.templates.default.field_budgets.{key}", "Budget must be a positive integer.")
                    else:
                        budgets[key] = value
            if status == "approved" and default.get("status") != "approved":
                report.error("template_budget_unapproved", "$brand.templates.default.status", "Approved brand profile needs approved default template budgets.")

    _scan_for_secrets(brand, report, "$brand")
    return brand_id if isinstance(brand_id, str) else None, budgets


def _require_string(spec: dict[str, Any], key: str, report: Report, max_chars: int | None = None) -> None:
    value = spec.get(key)
    if not _nonempty_string(value):
        report.error("required_string", f"$.{key}", "A non-empty string is required.")
    elif max_chars is not None and len(value) > max_chars:
        report.warning("long_field", f"$.{key}", f"Field has {len(value)} characters; recommended maximum is {max_chars}.")


def calculate_package_checksum(spec: dict[str, Any]) -> str | None:
    """Hash the exact publish package fields that human approval covers."""
    design = spec.get("design")
    publishing = spec.get("publishing")
    if not isinstance(design, dict) or not isinstance(publishing, dict):
        return None
    export_checksum = design.get("export_checksum")
    if not _nonempty_string(export_checksum):
        return None
    payload = {
        "content_id": spec.get("content_id"),
        "scope": spec.get("scope"),
        "brand_id": spec.get("brand_id"),
        "policy_id": spec.get("policy", {}).get("policy_id") if isinstance(spec.get("policy"), dict) else None,
        "policy_revision": spec.get("policy", {}).get("revision") if isinstance(spec.get("policy"), dict) else None,
        "template_provider_ids": (
            spec.get("policy", {}).get("unattended", {}).get("preapproved", {}).get("template_provider_ids")
            if isinstance(spec.get("policy"), dict)
            and isinstance(spec.get("policy", {}).get("unattended"), dict)
            and isinstance(spec.get("policy", {}).get("unattended", {}).get("preapproved"), dict)
            else None
        ),
        "copy_recipe_id": spec.get("copy_recipe_id"),
        "copy_recipe_version": spec.get("copy_recipe_version"),
        "brand_revision": spec.get("brand_revision"),
        "export_checksum": export_checksum,
        "template_id": design.get("template_id"),
        "template_version": design.get("template_version"),
        "provider_template_id": _provider_template_id_value(design),
        "caption": spec.get("caption"),
        "alt_text": spec.get("alt_text"),
        "target_account": publishing.get("target_account"),
        "scheduled_at": publishing.get("scheduled_at"),
        "timezone": publishing.get("timezone"),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate_metric_value(value: Any, path: str, report: Report) -> None:
    """Allow real zero and explicit not_available; never coerce missing to zero."""

    if isinstance(value, dict):
        for key, child in value.items():
            _validate_metric_value(child, f"{path}.{key}", report)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_metric_value(child, f"{path}[{index}]", report)
        return
    if value == "not_available":
        return
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        report.error("metric_value", path, "Use a non-negative number or the explicit string not_available; never null or a missing value.")
    elif value < 0:
        report.error("metric_value", path, "Metric values cannot be negative.")


def _validate_measurement(
    spec: dict[str, Any], measurement: Any, state: Any, published_at: datetime | None, report: Report
) -> None:
    if not isinstance(measurement, dict):
        report.error("measurement", "$.measurement", "measurement must be an object.")
        return

    plan = measurement.get("plan")
    if not isinstance(plan, dict):
        report.error("measurement_plan", "$.measurement.plan", "Every content pillar requires a measurement plan.")
    else:
        if plan.get("pillar") != spec.get("content_pillar"):
            report.error("measurement_pillar", "$.measurement.plan.pillar", "Measurement plan pillar must match content_pillar.")
        if not _nonempty_string(plan.get("primary_metric")):
            report.error("measurement_primary_metric", "$.measurement.plan.primary_metric", "Measurement plan requires a primary metric.")
        elif plan.get("primary_metric") in FORBIDDEN_METRIC_NAMES:
            report.error("metric_name", "$.measurement.plan.primary_metric", "Use the API-canonical metric name saved or reach, not a provider synonym.")
        if not _nonempty_string(plan.get("denominator")):
            report.error("measurement_denominator", "$.measurement.plan.denominator", "Measurement plan requires an explicit denominator.")
        elif plan.get("denominator") in FORBIDDEN_METRIC_NAMES:
            report.error("metric_name", "$.measurement.plan.denominator", "Use the API-canonical metric name saved or reach, not a provider synonym.")
        guardrails = plan.get("guardrails")
        if not isinstance(guardrails, list) or any(not _nonempty_string(item) for item in guardrails):
            report.error("measurement_guardrails", "$.measurement.plan.guardrails", "Measurement plan guardrails must be a list of named metrics or risks.")
        if not _nonempty_string(plan.get("business_outcome_source")):
            report.error("measurement_outcome_source", "$.measurement.plan.business_outcome_source", "Measurement plan requires a business outcome source or not_available.")
        cadence = plan.get("cadence")
        if cadence != list(DEFAULT_MEASUREMENT_CADENCE):
            report.error("measurement_cadence", "$.measurement.plan.cadence", "Use the default cadence 24h provisional, 72h operational, 7d cohort, and 28d portfolio.")
        format_override = plan.get("format_override")
        if format_override is not None:
            if not isinstance(format_override, dict):
                report.error("measurement_format_override", "$.measurement.plan.format_override", "A format override must be an object.")
            else:
                if format_override.get("format") != spec.get("format"):
                    report.error("measurement_format_override", "$.measurement.plan.format_override.format", "A measurement override must name the current format.")
                if not _nonempty_string(format_override.get("primary_metric")) or not _nonempty_string(format_override.get("denominator")):
                    report.error("measurement_format_override", "$.measurement.plan.format_override", "A format override requires primary_metric and denominator.")
        format_overrides = plan.get("format_overrides")
        if format_overrides is not None:
            if not isinstance(format_overrides, dict):
                report.error("measurement_format_overrides", "$.measurement.plan.format_overrides", "Format overrides must be an object keyed by format.")
            else:
                for format_name, override in format_overrides.items():
                    if format_name not in FORMATS or not isinstance(override, dict):
                        report.error("measurement_format_overrides", f"$.measurement.plan.format_overrides.{format_name}", "Each format override must name a supported format and contain an object.")
                    elif not _nonempty_string(override.get("primary_metric")) or not _nonempty_string(override.get("denominator")):
                        report.error("measurement_format_overrides", f"$.measurement.plan.format_overrides.{format_name}", "A format override requires primary_metric and denominator.")

        pillar_key = str(spec.get("content_pillar", "")).split(":", 1)[0].casefold()
        default_plan = PILLAR_MEASUREMENT_DEFAULTS.get(pillar_key)
        selected_override: dict[str, Any] | None = None
        if isinstance(format_override, dict) and format_override.get("format") == spec.get("format"):
            selected_override = format_override
        elif isinstance(format_overrides, dict) and isinstance(format_overrides.get(spec.get("format")), dict):
            selected_override = format_overrides[spec.get("format")]
        if isinstance(default_plan, dict):
            expected_plan = selected_override or default_plan
            if plan.get("primary_metric") != expected_plan.get("primary_metric"):
                report.error("measurement_primary_metric", "$.measurement.plan.primary_metric", "Primary metric must match the accepted pillar default or an explicit current-format override.")
            if plan.get("denominator") != expected_plan.get("denominator"):
                report.error("measurement_denominator", "$.measurement.plan.denominator", "Denominator must match the accepted pillar default or an explicit current-format override.")
            guardrails = plan.get("guardrails")
            expected_guardrails = expected_plan.get("guardrails", [])
            if isinstance(guardrails, list) and any(metric not in guardrails for metric in expected_guardrails):
                report.error("measurement_guardrails", "$.measurement.plan.guardrails", "Measurement plan must include the accepted pillar guardrails unless an explicit format override replaces them.")

    data_mode = measurement.get("data_mode")
    if data_mode not in MEASUREMENT_DATA_MODES:
        report.error("measurement_data_mode", "$.measurement.data_mode", "Data mode must be organic, paid, mixed, or unknown.")

    benchmark_scope = measurement.get("benchmark_scope")
    if not isinstance(benchmark_scope, dict):
        report.error("benchmark_scope", "$.measurement.benchmark_scope", "Benchmark scope must be explicit and isolated.")
    else:
        expected_keys = {
            "tenant_id",
            "client_id",
            "product_id",
            "brand_id",
            "account",
            "content_pillar",
            "format",
            "window",
        }
        if set(benchmark_scope) != expected_keys:
            report.error(
                "benchmark_scope_fields",
                "$.measurement.benchmark_scope",
                "Benchmark scope is limited to tenant/client/product/brand/account/pillar/format/window.",
            )
        scope = spec.get("scope") if isinstance(spec.get("scope"), dict) else {}
        if any(
            benchmark_scope.get(key) != expected
            for key, expected in {
                "tenant_id": scope.get("tenant_id"),
                "client_id": scope.get("client_id"),
                "product_id": scope.get("product_id"),
                "brand_id": spec.get("brand_id"),
            }.items()
        ):
            report.error(
                "benchmark_scope_mismatch",
                "$.measurement.benchmark_scope",
                "Benchmark tenant/client/product/brand must match the content isolation scope.",
            )
        if benchmark_scope.get("account") != spec.get("publishing", {}).get("target_account"):
            report.error("benchmark_account_mismatch", "$.measurement.benchmark_scope.account", "Benchmark account must match the publishing target.")
        if benchmark_scope.get("content_pillar") != spec.get("content_pillar"):
            report.error("benchmark_pillar_mismatch", "$.measurement.benchmark_scope.content_pillar", "Benchmark pillar must match content_pillar.")
        if benchmark_scope.get("format") != spec.get("format"):
            report.error("benchmark_format_mismatch", "$.measurement.benchmark_scope.format", "Benchmark format must match the content format.")
        benchmark_window = benchmark_scope.get("window")
        if benchmark_window is not None and benchmark_window not in MEASUREMENT_WINDOWS:
            report.error("benchmark_window", "$.measurement.benchmark_scope.window", "Benchmark window must be 24h, 72h, 7d, 28d, or null before measurement.")

        if benchmark_scope.get("account") is not None and not _nonempty_string(benchmark_scope.get("account")):
            report.error("benchmark_account", "$.measurement.benchmark_scope.account", "Benchmark account must be a non-empty account identifier.")

    if measurement.get("rollup") is not None:
        report.error(
            "measurement_rollup_scope",
            "$.measurement.rollup",
            "Intentional rollups must be separate aggregated reports, never embedded in a content record scope.",
        )

    window = measurement.get("window")
    if window is not None and window not in MEASUREMENT_WINDOWS:
        report.error("measurement_window", "$.measurement.window", "Measurement window must be 24h, 72h, 7d, or 28d.")
    if isinstance(benchmark_scope, dict) and benchmark_scope.get("window") != window:
        report.error("benchmark_window_mismatch", "$.measurement.benchmark_scope.window", "Benchmark window must match measurement.window.")

    captured = measurement.get("captured_at")
    if captured is not None and _parse_datetime(captured) is None:
        report.error("measurement_captured_at", "$.measurement.captured_at", "Use a timezone-aware ISO 8601 datetime.")
    metrics = measurement.get("metrics")
    if not isinstance(metrics, dict):
        report.error("metrics", "$.measurement.metrics", "measurement.metrics must be an object.")
    else:
        for key, value in metrics.items():
            if key in FORBIDDEN_METRIC_NAMES:
                report.error("metric_name", f"$.measurement.metrics.{key}", "Use the API-canonical metric name saved or reach, not a provider synonym.")
            _validate_metric_value(value, f"$.measurement.metrics.{key}", report)

    child_metrics = measurement.get("child_metrics")
    if child_metrics is not None and not isinstance(child_metrics, dict):
        report.error("child_metrics", "$.measurement.child_metrics", "child_metrics must be an object or null.")
    elif isinstance(child_metrics, dict):
        for key, value in child_metrics.items():
            if key in FORBIDDEN_METRIC_NAMES:
                report.error("metric_name", f"$.measurement.child_metrics.{key}", "Use the API-canonical metric name saved or reach, not a provider synonym.")
            _validate_metric_value(value, f"$.measurement.child_metrics.{key}", report)
            if spec.get("format") == "carousel" and value != "not_available":
                report.error("carousel_child_metric", f"$.measurement.child_metrics.{key}", "Carousel child metrics are not available; record not_available.")

    sample_size = measurement.get("sample_size")
    interpretation = measurement.get("sample_interpretation")
    if sample_size is not None and (isinstance(sample_size, bool) or not isinstance(sample_size, int) or sample_size < 0):
        report.error("sample_size", "$.measurement.sample_size", "sample_size must be a non-negative integer or null.")
    if interpretation not in MEASUREMENT_INTERPRETATIONS:
        report.error("sample_interpretation", "$.measurement.sample_interpretation", "Use descriptive, directional, operational_direction, or not_available.")
    elif isinstance(sample_size, int):
        expected_interpretation = "descriptive" if sample_size < 10 else "operational_direction" if sample_size >= 30 else "directional"
        if interpretation != expected_interpretation:
            report.error("sample_interpretation_mismatch", "$.measurement.sample_interpretation", "n<10 is descriptive; n>=30 supports operational direction; 10-29 remains directional.")

    if spec.get("format") == "story" and _state_at_least(state, "MEASURED"):
        story_fetched_at = _parse_datetime(measurement.get("story_fetched_at"))
        if story_fetched_at is None:
            report.error("story_fetch_missing", "$.measurement.story_fetched_at", "Story insights must be fetched before the 24h window closes.")
        elif published_at is not None and story_fetched_at > published_at + timedelta(hours=24):
            report.error("story_fetch_late", "$.measurement.story_fetched_at", "Story insights must be fetched before 24 hours after publication.")

    if _state_at_least(state, "MEASURED"):
        if not _nonempty_string(window):
            report.error("measurement_window", "$.measurement.window", "Measured state requires a window label.")
        if _parse_datetime(captured) is None:
            report.error("measurement_receipt", "$.measurement.captured_at", "Measured state requires a capture timestamp.")
        if not isinstance(metrics, dict) or not metrics:
            report.error("measurement_metrics", "$.measurement.metrics", "Measured state requires at least one metric.")


def validate_content_spec(
    spec: Any,
    brand: Any = None,
    today: date | None = None,
    policy_context: Any = None,
    actor_id: str | None = None,
    brand_bundle: str | Path | None = None,
    brand_policy_context: Any = None,
    brand_actor_id: str | None = None,
) -> Report:
    report = Report()
    today = today or datetime.now(timezone.utc).date()

    if not isinstance(spec, dict):
        report.error("root_type", "$", "Content spec must be a JSON object.")
        return report

    _scan_for_secrets(spec, report)
    missing = sorted(REQUIRED_TOP_LEVEL - spec.keys())
    for key in missing:
        report.error("missing_field", f"$.{key}", "Required top-level field is missing.")

    schema_version = spec.get("schema_version")
    if schema_version not in {"1.0", "1.1"}:
        report.error("schema_version", "$.schema_version", "Supported schema_version is 1.1; 1.0 requires explicit legacy_v1 compatibility.")
    if schema_version == "1.0":
        compatibility = spec.get("compatibility")
        if not isinstance(compatibility, dict) or compatibility.get("mode") != "legacy_v1":
            report.error(
                "legacy_compatibility_required",
                "$.compatibility",
                "Schema 1.0 is accepted only with compatibility.mode legacy_v1 and the canonical scope/policy fields.",
            )

    for key in ("content_id", "campaign_id", "brief_version", "copy_version", "brand_id"):
        _require_string(spec, key, report)
    content_id = spec.get("content_id")
    if _nonempty_string(content_id) and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}", content_id):
        report.error("content_id_format", "$.content_id", "Use 3-128 letters, numbers, dots, underscores, or hyphens.")

    state = spec.get("state")
    if state not in STATE_ORDER:
        report.error("state", "$.state", f"State must be one of: {', '.join(STATE_ORDER)}.")
    if spec.get("platform") not in PLATFORMS:
        report.error("platform", "$.platform", f"Unsupported platform: {spec.get('platform')!r}.")
    if spec.get("format") not in FORMATS:
        report.error("format", "$.format", f"Unsupported format: {spec.get('format')!r}.")
    if spec.get("objective") not in OBJECTIVES:
        report.error("objective", "$.objective", f"Unsupported objective: {spec.get('objective')!r}.")

    canonical_scope = _validate_scope(spec, report)
    policy = _validate_policy(spec, canonical_scope, report)
    _validate_trusted_policy(spec, policy, canonical_scope, state, policy_context, actor_id, report)
    bundle = _validate_brand_bundle(
        brand_bundle,
        canonical_scope,
        state,
        spec,
        report,
        brand_policy_context=brand_policy_context,
        brand_actor_id=brand_actor_id,
    )
    _validate_copy_recipe(spec, policy, state, bundle, report)

    _require_string(spec, "audience", report, 240)
    _require_string(spec, "content_pillar", report, 160)
    _require_string(spec, "single_message", report, 220)

    brand_id, budgets = _validate_brand(
        brand,
        report,
        canonical_scope,
        schema_version=schema_version,
        state=state,
    )
    if brand_id and spec.get("brand_id") != brand_id:
        report.error("brand_mismatch", "$.brand_id", f"Content brand_id must match {brand_id!r}.")

    template_entries = _validate_template_registry(spec, canonical_scope, policy, report, today)

    source_context = spec.get("source_context")
    if not isinstance(source_context, dict):
        report.error("source_context", "$.source_context", "source_context must be an object.")
    else:
        if not _nonempty_string(source_context.get("brief")):
            report.error("source_brief", "$.source_context.brief", "Source context needs a brief.")
        urls = source_context.get("source_urls")
        if not isinstance(urls, list):
            report.error("source_urls", "$.source_context.source_urls", "source_urls must be a list.")
        else:
            for index, value in enumerate(urls):
                if not _valid_https_url(value):
                    report.error("source_url", f"$.source_context.source_urls[{index}]", "Source URL must be HTTPS.")
        retrieved_at = source_context.get("retrieved_at")
        if retrieved_at is not None and _parse_datetime(retrieved_at) is None:
            report.error("retrieved_at", "$.source_context.retrieved_at", "Use a timezone-aware ISO 8601 datetime.")
        if source_context.get("external_content_treated_as_data") is not True:
            report.error("instruction_boundary", "$.source_context.external_content_treated_as_data", "External content must explicitly be treated as data, not instructions.")

    experiment = spec.get("experiment")
    if not isinstance(experiment, dict):
        report.error("experiment", "$.experiment", "experiment must be an object.")
    else:
        variable = experiment.get("variable")
        if variable not in EXPERIMENT_VARIABLES:
            report.error("experiment_variable", "$.experiment.variable", "Experiment changes one supported variable or none.")
        elif variable != "none":
            for key in ("experiment_id", "hypothesis", "primary_metric", "stop_rule"):
                if not _nonempty_string(experiment.get(key)):
                    report.error("experiment_field", f"$.experiment.{key}", "Active experiment requires this field.")
            if not _nonempty_string(experiment.get("variant")):
                report.error("experiment_variant", "$.experiment.variant", "Active experiment requires a variant label.")
            if not isinstance(experiment.get("guardrails"), list):
                report.error("experiment_guardrails", "$.experiment.guardrails", "guardrails must be a list.")

    slides = spec.get("slides")
    ctas: list[str] = []
    slide_text_chunks: list[str] = []
    if not isinstance(slides, list) or not slides:
        report.error("slides", "$.slides", "slides must be a non-empty list.")
        slides = []
    else:
        if len(slides) > budgets["slides_max"]:
            report.error("slides_budget", "$.slides", f"Slide count {len(slides)} exceeds budget {budgets['slides_max']}.")
        if spec.get("format") == "static" and len(slides) != 1:
            report.error("static_pages", "$.slides", "Static content must have exactly one slide.")
        if spec.get("format") == "carousel" and len(slides) < 2:
            report.error("carousel_pages", "$.slides", "Carousel content must have at least two slides.")
        for index, slide in enumerate(slides):
            path = f"$.slides[{index}]"
            if not isinstance(slide, dict):
                report.error("slide_type", path, "Each slide must be an object.")
                continue
            if slide.get("slide") != index + 1:
                report.error("slide_sequence", f"{path}.slide", f"Expected slide number {index + 1}.")
            if slide.get("role") not in SLIDE_ROLES:
                report.error("slide_role", f"{path}.role", "Unsupported slide role.")
            for field, budget_key in (("headline", "headline_chars"), ("body", "body_chars"), ("cta", "cta_chars")):
                value = slide.get(field)
                if not isinstance(value, str):
                    report.error("slide_text_type", f"{path}.{field}", "Slide text fields must be strings, including empty strings.")
                elif len(value) > budgets[budget_key]:
                    report.error("text_budget", f"{path}.{field}", f"{len(value)} characters exceeds budget {budgets[budget_key]}.")
            if index == 0 and slide.get("role") != "cover" and spec.get("format") != "text":
                report.warning("first_slide_role", f"{path}.role", "First visual slide should normally be the cover.")
            if index == 0 and not _nonempty_string(slide.get("headline")):
                report.error("cover_headline", f"{path}.headline", "The cover needs a headline.")
            if not _nonempty_string(slide.get("visual_direction")) and spec.get("format") != "text":
                report.error("visual_direction", f"{path}.visual_direction", "Provide observable composition direction.")
            if not _nonempty_string(slide.get("accessibility_note")) and spec.get("format") != "text":
                report.warning("accessibility_note", f"{path}.accessibility_note", "Add a reading-order, contrast, or non-color cue note.")
            cta_value = slide.get("cta")
            if _nonempty_string(cta_value):
                ctas.append(cta_value)
            slide_text_chunks.extend(str(slide.get(key, "")) for key in ("headline", "body", "cta"))

    caption = spec.get("caption")
    caption_text = ""
    if not isinstance(caption, dict):
        report.error("caption", "$.caption", "caption must be an object.")
    else:
        for key in ("hook", "body", "cta"):
            if not isinstance(caption.get(key), str):
                report.error("caption_type", f"$.caption.{key}", "Caption fields must be strings.")
        if _state_at_least(state, "COPY_REVIEW") and not _nonempty_string(caption.get("hook")):
            report.error("caption_hook", "$.caption.hook", "Copy review requires a hook.")
        if _nonempty_string(caption.get("cta")):
            ctas.append(caption["cta"])
        hashtags = caption.get("hashtags")
        if not isinstance(hashtags, list):
            report.error("hashtags", "$.caption.hashtags", "hashtags must be a list.")
            hashtags = []
        else:
            seen_hashtags: set[str] = set()
            for index, hashtag in enumerate(hashtags):
                if not isinstance(hashtag, str) or not re.fullmatch(r"#[^\s#]+", hashtag):
                    report.error("hashtag_format", f"$.caption.hashtags[{index}]", "Use one no-space hashtag beginning with #.")
                elif hashtag.casefold() in seen_hashtags:
                    report.warning("duplicate_hashtag", f"$.caption.hashtags[{index}]", "Duplicate hashtag.")
                else:
                    seen_hashtags.add(hashtag.casefold())
            if len(hashtags) > budgets["hashtags_max"]:
                report.error("hashtag_budget", "$.caption.hashtags", f"Hashtag count exceeds budget {budgets['hashtags_max']}.")
        caption_text = "\n\n".join(
            value for value in (caption.get("hook", ""), caption.get("body", ""), caption.get("cta", "")) if isinstance(value, str) and value
        )
        hashtag_line = " ".join(item for item in hashtags if isinstance(item, str))
        if hashtag_line:
            caption_text = f"{caption_text}\n\n{hashtag_line}" if caption_text else hashtag_line
        if len(caption_text) > budgets["caption_chars"]:
            report.error("caption_budget", "$.caption", f"Rendered caption has {len(caption_text)} characters; budget is {budgets['caption_chars']}.")

    distinct_ctas = {_normalize_cta(value) for value in ctas if _normalize_cta(value)}
    if len(distinct_ctas) > 1:
        report.error("multiple_ctas", "$.caption.cta", f"Found competing CTA phrases: {sorted(distinct_ctas)}.")
    if _state_at_least(state, "COPY_REVIEW") and not distinct_ctas:
        report.warning("missing_cta", "$.caption.cta", "No CTA is present; document an intentional no-CTA decision if appropriate.")

    alt_text = spec.get("alt_text")
    if not isinstance(alt_text, str):
        report.error("alt_text_type", "$.alt_text", "alt_text must be a string.")
    else:
        if _state_at_least(state, "COPY_REVIEW") and spec.get("format") != "text" and not alt_text.strip():
            report.error("alt_text", "$.alt_text", "Visual content requires alt text before copy review completes.")
        if len(alt_text) > budgets["alt_text_chars"]:
            report.error("alt_text_budget", "$.alt_text", f"Alt text exceeds budget {budgets['alt_text_chars']}.")

    caption_tokens = _tokens(caption_text)
    slide_tokens = _tokens(" ".join(slide_text_chunks))
    if len(caption_tokens) >= 12 and len(slide_tokens) >= 12:
        overlap = len(caption_tokens & slide_tokens) / min(len(caption_tokens), len(slide_tokens))
        if overlap >= 0.85:
            report.warning("caption_echo", "$.caption", "Caption largely repeats artwork; add context or proof.")

    claims = spec.get("claims")
    verified_claims = 0
    claim_ids: set[str] = set()
    verified_claim_ids: set[str] = set()
    if not isinstance(claims, list):
        report.error("claims", "$.claims", "claims must be a list.")
        claims = []
    else:
        for index, claim in enumerate(claims):
            path = f"$.claims[{index}]"
            if not isinstance(claim, dict):
                report.error("claim_type", path, "Each claim must be an object.")
                continue
            claim_id = claim.get("claim_id")
            if not _safe_registry_id(claim_id):
                report.error("claim_id", f"{path}.claim_id", "Claims need a stable lowercase kebab-case claim_id for scoped approval.")
            elif claim_id in claim_ids:
                report.error("claim_id_duplicate", f"{path}.claim_id", "claim_id must be unique within the content record.")
            else:
                claim_ids.add(claim_id)
            if not _nonempty_string(claim.get("text")):
                report.error("claim_text", f"{path}.text", "Claim text is required.")
            status = claim.get("status")
            if status not in CLAIM_STATUSES:
                report.error("claim_status", f"{path}.status", "Unsupported claim status.")
                continue
            if status == "verified":
                verified_claims += 1
                if isinstance(claim_id, str):
                    verified_claim_ids.add(claim_id)
                if not _valid_https_url(claim.get("source_url")):
                    report.error("claim_source", f"{path}.source_url", "Verified claim requires an HTTPS source.")
                owner = claim.get("owner")
                if not _nonempty_string(owner) or str(owner).casefold() == "unassigned":
                    report.error("claim_owner", f"{path}.owner", "Verified claim requires an accountable owner.")
                verified_on = _parse_date(claim.get("verified_on"))
                expires_on = _parse_date(claim.get("expires_on"))
                if verified_on is None:
                    report.error("claim_verified_on", f"{path}.verified_on", "Use an ISO date for verified_on.")
                elif verified_on > today:
                    report.error("claim_future_verification", f"{path}.verified_on", "Verification date cannot be in the future.")
                if expires_on is None:
                    report.error("claim_expires_on", f"{path}.expires_on", "Verified claim requires an ISO expiry date.")
                elif expires_on < today:
                    report.error("claim_expired", f"{path}.expires_on", "Claim has expired and cannot remain verified.")
                if verified_on and expires_on and expires_on < verified_on:
                    report.error("claim_date_order", path, "expires_on cannot precede verified_on.")
            elif _state_at_least(state, "HUMAN_APPROVED"):
                report.error("claim_not_verified", f"{path}.status", "Only current verified claims may enter an approved package.")

    _validate_brand_claims(claims, state, bundle, report)

    if policy.get("mode") == "unattended" and policy.get("unattended", {}).get("enabled") is True:
        preapproved = policy.get("unattended", {}).get("preapproved", {})
        preapproved_claim_ids = set(preapproved.get("claim_ids", [])) if isinstance(preapproved, dict) else set()
        for claim_id in claim_ids:
            if claim_id not in preapproved_claim_ids:
                report.error("unattended_claim_unapproved", "$.policy.unattended.preapproved.claim_ids", "Every claim used by unattended content must be explicitly preapproved.")
        for claim_id in (preapproved_claim_ids & claim_ids) - verified_claim_ids:
            report.error("unattended_claim_unverified", "$.policy.unattended.preapproved.claim_ids", "Every preapproved claim ID must refer to a verified claim.")
        if claims and not preapproved_claim_ids:
            report.error("unattended_claims_missing", "$.policy.unattended.preapproved.claim_ids", "Unattended content with claims requires explicit claim preapprovals.")

    content_text = _all_content_text(spec)
    risky_matches = sorted({match.group(0) for pattern in ABSOLUTE_CLAIM_PATTERNS for match in pattern.finditer(content_text)})
    has_numeric_language = bool(re.search(r"\b\d[\d.,]*\+?%?\b", content_text))
    if (risky_matches or has_numeric_language) and verified_claims == 0:
        message = "Potential material claim language has no verified claim record."
        if _state_at_least(state, "HUMAN_APPROVED"):
            report.error("claim_registry_missing", "$.claims", message)
        else:
            report.warning("claim_registry_missing", "$.claims", message)

    design = spec.get("design")
    export_checksum = None
    if not isinstance(design, dict):
        report.error("design", "$.design", "design must be an object.")
    else:
        design_remote_keys = (
            "template_id",
            "draft_ref",
            "canva_design_id",
            "canva_design_url",
            "provider_template_id",
            "canva_template_id",
        )
        has_design_remote_reference = any(_nonempty_string(design.get(key)) for key in design_remote_keys)
        _validate_remote_scope(
            design.get("remote_scope"),
            "$.design.remote_scope",
            canonical_scope,
            report,
            required=has_design_remote_reference,
        )
        dimensions = design.get("dimensions")
        if not isinstance(dimensions, dict):
            report.error("dimensions", "$.design.dimensions", "dimensions must be an object.")
        else:
            width = dimensions.get("width")
            height = dimensions.get("height")
            for key, value in (("width", width), ("height", height)):
                if isinstance(value, bool) or not isinstance(value, int) or not 40 <= value <= 8000:
                    report.error("dimension_value", f"$.design.dimensions.{key}", "Dimension must be an integer from 40 to 8000.")
            if isinstance(width, int) and not isinstance(width, bool) and isinstance(height, int) and not isinstance(height, bool) and width * height > 25_000_000:
                report.error("dimension_area", "$.design.dimensions", "Canvas area exceeds 25,000,000 pixels.")
        safe_area = design.get("safe_area_px")
        if isinstance(safe_area, bool) or not isinstance(safe_area, int) or safe_area < 0:
            report.error("safe_area", "$.design.safe_area_px", "safe_area_px must be a non-negative integer.")
        for key in ("canva_design_url",):
            value = design.get(key)
            if value is not None and not _valid_https_url(value):
                report.error("design_url", f"$.design.{key}", "Design URL must be HTTPS or null.")
        if _state_at_least(state, "DESIGN_DRAFT") and not any(
            _nonempty_string(design.get(key)) for key in ("draft_ref", "canva_design_id", "canva_design_url")
        ):
            report.error("draft_evidence", "$.design", "Design draft state requires a draft or Canva reference.")
        if _state_at_least(state, "BRAND_QA") and not _nonempty_string(design.get("render_ref")):
            report.error("render_evidence", "$.design.render_ref", "Brand QA requires an actual render reference.")
        export_checksum = design.get("export_checksum")
        if export_checksum is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", str(export_checksum)):
            report.error("export_checksum", "$.design.export_checksum", "Use sha256:<64 lowercase hex characters>.")
        if _state_at_least(state, "HUMAN_APPROVED") and not _nonempty_string(export_checksum):
            report.error("export_checksum_missing", "$.design.export_checksum", "Final approval requires the exported artifact checksum.")

        provider_template_id = _validate_provider_template_id(design, "$.design", report)
        template_id = design.get("template_id")
        template_version = design.get("template_version")
        if _nonempty_string(template_id):
            if not _safe_registry_id(template_id):
                report.error("template_id_format", "$.design.template_id", "Template IDs must be lowercase kebab-case registry IDs.")
            if not _nonempty_string(template_version):
                report.error("template_version", "$.design.template_version", "A template reference requires its exact version.")
            matching_templates = [
                entry for entry in template_entries if entry.get("template_id") == template_id and entry.get("version") == template_version
            ]
            if _state_at_least(state, "HUMAN_APPROVED") and not any(entry.get("status") == "approved" for entry in matching_templates):
                report.error("template_not_approved", "$.design.template_id", "Approved content may use only a template/version approved in the scoped registry.")
            approved_matches = [entry for entry in matching_templates if entry.get("status") == "approved"]
            if approved_matches:
                registry_provider_ids = {_provider_template_id_value(entry) for entry in approved_matches if _provider_template_id_value(entry) is not None}
                if registry_provider_ids and provider_template_id is None:
                    report.error("provider_template_id_missing", "$.design", "A registry entry with an opaque Canva provider ID requires the exact ID on the design reference.")
                elif registry_provider_ids and provider_template_id not in registry_provider_ids:
                    report.error("provider_template_id_mismatch", "$.design", "Design provider template ID must exactly match the approved scoped registry entry; never normalize it.")
                elif provider_template_id is not None and not registry_provider_ids:
                    report.error("provider_template_id_unregistered", "$.design", "A provider template ID may be used only when the approved scoped registry entry records the same exact ID.")
            if policy.get("mode") == "unattended" and policy.get("unattended", {}).get("enabled") is True:
                preapproved = policy.get("unattended", {}).get("preapproved", {})
                allowed_templates = set(preapproved.get("template_ids", [])) if isinstance(preapproved, dict) else set()
                if template_id not in allowed_templates:
                    report.error("unattended_template_not_allowed", "$.design.template_id", "Unattended content may use only explicitly preapproved templates.")
                version_map = preapproved.get("template_versions", {}) if isinstance(preapproved, dict) else {}
                if isinstance(version_map, dict) and version_map.get(template_id) != template_version:
                    report.error("unattended_template_version", "$.design.template_version", "Unattended content must use the exact preapproved template version.")
                provider_map = preapproved.get("template_provider_ids", {}) if isinstance(preapproved, dict) else {}
                expected_provider_id = provider_map.get(template_id) if isinstance(provider_map, dict) else None
                if design.get("provider") == "canva" or provider_template_id is not None:
                    if expected_provider_id is None:
                        report.error("unattended_template_provider_id", "$.policy.unattended.preapproved.template_provider_ids", "Unattended Canva templates require an exact preapproved provider template ID.")
                    elif provider_template_id != expected_provider_id:
                        report.error("unattended_template_provider_id", "$.design", "Unattended design provider template ID must exactly match the trusted preapproved Canva ID.")
                elif expected_provider_id is not None:
                    report.error("unattended_template_provider_id", "$.design.provider", "A preapproved Canva provider ID requires a Canva design reference with the exact ID.")
        elif policy.get("mode") == "unattended" and policy.get("unattended", {}).get("enabled") is True and _state_at_least(state, "HUMAN_APPROVED"):
            report.error("unattended_template_missing", "$.design.template_id", "Unattended content requires a preapproved template/version; freeform generation stays attended.")
        elif provider_template_id is not None and _state_at_least(state, "HUMAN_APPROVED"):
            report.error("provider_template_alias_missing", "$.design.template_id", "An opaque provider template ID must be bound to a safe local template_id registry alias before approval.")

        download = design.get("download")
        if download is not None and not isinstance(download, dict):
            report.error("download_type", "$.design.download", "design.download must be an object or null.")
        elif isinstance(download, dict):
            download_status = download.get("status")
            if download_status not in {"not_started", "downloading", "downloaded", "failed"}:
                report.error("download_status", "$.design.download.status", "Unsupported export download status.")
            if download_status == "downloaded":
                _validate_remote_scope(download.get("scope"), "$.design.download.scope", canonical_scope, report, required=True)
                local_path = download.get("local_path")
                if not _nonempty_string(local_path):
                    report.error("download_path", "$.design.download.local_path", "Downloaded exports require a local path.")
                download_checksum = download.get("sha256")
                if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(download_checksum)):
                    report.error("download_checksum", "$.design.download.sha256", "Use sha256:<64 lowercase hex characters>.")
                local_file_size: int | None = None
                local_file_sha256: str | None = None
                if _nonempty_string(local_path):
                    try:
                        local_file = Path(local_path).expanduser()
                        if local_file.is_symlink() or not local_file.is_file():
                            report.error("download_file_missing", "$.design.download.local_path", "Downloaded export local_path must point to a regular file.")
                        else:
                            local_file_size = local_file.stat().st_size
                            if local_file_size <= 0:
                                report.error("download_file_empty", "$.design.download.local_path", "Downloaded export local_path must be non-empty.")
                            else:
                                digest = hashlib.sha256()
                                with local_file.open("rb") as handle:
                                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                                        digest.update(chunk)
                                local_file_sha256 = digest.hexdigest()
                    except (OSError, ValueError):
                        report.error("download_file_missing", "$.design.download.local_path", "Downloaded export local_path could not be read.")
                receipt = download.get("receipt")
                if not isinstance(receipt, dict):
                    report.error("download_receipt", "$.design.download.receipt", "Downloaded exports require a structured receipt.")
                else:
                    if receipt.get("status") != "downloaded":
                        report.error("download_receipt_status", "$.design.download.receipt.status", "Receipt status must be downloaded.")
                    if receipt.get("output_path") != local_path:
                        report.error("download_receipt_path", "$.design.download.receipt.output_path", "Receipt output_path must match local_path.")
                    receipt_sha256 = receipt.get("sha256")
                    if not re.fullmatch(r"[0-9a-f]{64}", str(receipt_sha256)):
                        report.error("download_receipt_checksum", "$.design.download.receipt.sha256", "Receipt sha256 must be 64 lowercase hex characters.")
                    elif isinstance(download_checksum, str) and download_checksum == f"sha256:{receipt_sha256}":
                        pass
                    else:
                        report.error("download_checksum_mismatch", "$.design.download", "Download checksum and receipt checksum must match.")
                    receipt_size = receipt.get("size_bytes")
                    if isinstance(receipt_size, bool) or not isinstance(receipt_size, int) or receipt_size <= 0:
                        report.error("download_receipt_size", "$.design.download.receipt.size_bytes", "Receipt size_bytes must be a positive integer.")
                    elif local_file_size is not None and receipt_size != local_file_size:
                        report.error("download_receipt_size_mismatch", "$.design.download.receipt.size_bytes", "Receipt size_bytes must match the local file.")
                    if local_file_sha256 is not None:
                        if receipt_sha256 != local_file_sha256:
                            report.error("download_file_checksum_mismatch", "$.design.download.local_path", "Receipt sha256 must match the local file.")
                        if download_checksum != f"sha256:{local_file_sha256}":
                            report.error("download_file_checksum_mismatch", "$.design.download.sha256", "Download sha256 must match the local file.")
                if isinstance(export_checksum, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", export_checksum) and download_checksum != export_checksum:
                    report.error("export_download_checksum_mismatch", "$.design.export_checksum", "Export checksum must match the recorded download checksum.")
            elif _state_at_least(state, "HUMAN_APPROVED"):
                report.error("download_missing", "$.design.download.status", "Approved packages require a completed local export download receipt.")
        elif _state_at_least(state, "HUMAN_APPROVED"):
            report.error("download_missing", "$.design.download", "Approved packages require a completed local export download receipt.")

    qa = spec.get("qa")
    qa_keys = ("copy", "brand", "visual", "accessibility", "claims", "mobile_thumbnail")
    if not isinstance(qa, dict):
        report.error("qa", "$.qa", "qa must be an object.")
    else:
        for key in qa_keys:
            if qa.get(key) not in QA_STATUSES:
                report.error("qa_status", f"$.qa.{key}", "Unsupported QA status.")
        if not isinstance(qa.get("notes"), list):
            report.error("qa_notes", "$.qa.notes", "qa.notes must be a list.")
        if _state_at_least(state, "HUMAN_APPROVED"):
            for key in qa_keys:
                allowed = {"pass"}
                if spec.get("format") == "text" and key in {"visual", "mobile_thumbnail"}:
                    allowed.add("not_applicable")
                if qa.get(key) not in allowed:
                    report.error("qa_not_passed", f"$.qa.{key}", "Approved packages require completed passing QA.")

    publishing = spec.get("publishing")
    scheduled_at = None
    published_at = None
    preflight_checked_at = None
    if not isinstance(publishing, dict):
        report.error("publishing", "$.publishing", "publishing must be an object.")
    else:
        publishing_remote_keys = ("media_id", "public_url")
        has_publishing_remote_reference = any(_nonempty_string(publishing.get(key)) for key in publishing_remote_keys)
        _validate_remote_scope(
            publishing.get("remote_scope"),
            "$.publishing.remote_scope",
            canonical_scope,
            report,
            required=has_publishing_remote_reference,
        )
        target = publishing.get("target_account")
        if _state_at_least(state, "HUMAN_APPROVED") and not _nonempty_string(target):
            report.error("target_account", "$.publishing.target_account", "Approval must identify the target account.")
        if policy.get("mode") == "unattended" and policy.get("unattended", {}).get("enabled") is True and _state_at_least(state, "HUMAN_APPROVED"):
            preapproved = policy.get("unattended", {}).get("preapproved", {})
            targets = preapproved.get("targets", []) if isinstance(preapproved, dict) else []
            if target not in targets:
                report.error("unattended_target_not_allowed", "$.publishing.target_account", "Unattended content may publish only to an explicitly preapproved target.")
        scheduled_raw = publishing.get("scheduled_at")
        if scheduled_raw is not None:
            scheduled_at = _parse_datetime(scheduled_raw)
            if scheduled_at is None:
                report.error("scheduled_at", "$.publishing.scheduled_at", "Use a timezone-aware ISO 8601 datetime.")
        if not _nonempty_string(publishing.get("timezone")):
            report.error("timezone", "$.publishing.timezone", "Publishing timezone is required.")
        public_url = publishing.get("public_url")
        if public_url is not None and not _valid_https_url(public_url):
            report.error("public_url", "$.publishing.public_url", "Public URL must be HTTPS or null.")
        preflight = publishing.get("preflight")
        if not isinstance(preflight, dict):
            report.error("preflight", "$.publishing.preflight", "preflight must be an object.")
            preflight = {}
        else:
            for key, allowed in PREFLIGHT_STATUSES.items():
                if preflight.get(key) not in allowed:
                    report.error("preflight_status", f"$.publishing.preflight.{key}", "Unsupported preflight status.")
        preflight_raw = publishing.get("preflight_checked_at")
        if preflight_raw is not None:
            preflight_checked_at = _parse_datetime(preflight_raw)
            if preflight_checked_at is None:
                report.error("preflight_checked_at", "$.publishing.preflight_checked_at", "Use a timezone-aware ISO 8601 datetime.")
        if _state_at_least(state, "SCHEDULED"):
            if scheduled_at is None:
                report.error("schedule_missing", "$.publishing.scheduled_at", "Scheduled state requires a valid scheduled_at.")
            if not _nonempty_string(publishing.get("idempotency_key")):
                report.error("idempotency_key", "$.publishing.idempotency_key", "Scheduled publishing requires an idempotency key.")
            required_preflight = {
                "duplicate_check": "pass",
                "kill_switch": "clear",
                "account_access": "pass",
            }
            for key, expected in required_preflight.items():
                if preflight.get(key) != expected:
                    report.error("preflight_block", f"$.publishing.preflight.{key}", f"Expected {expected!r} before scheduling/publishing.")
            if preflight.get("asset_rights") not in {"pass", "not_applicable"}:
                report.error("asset_rights", "$.publishing.preflight.asset_rights", "Asset rights must pass or be not applicable.")
            if preflight_checked_at is None:
                report.error("preflight_missing", "$.publishing.preflight_checked_at", "Record the preflight timestamp.")
            publisher_id = publishing.get("publisher_id")
            if publishing.get("publisher_role") != "publisher" or not _nonempty_string(publisher_id) or not _mapped_identity(policy.get("raw", {}), publisher_id, "publisher"):
                report.error("publisher_identity", "$.publishing.publisher_id", "Only a mapped publisher identity may schedule or publish.")
            approval_for_publish = spec.get("approval")
            if publishing.get("policy_id") != policy.get("raw", {}).get("policy_id"):
                report.error("publishing_policy_id", "$.publishing.policy_id", "Scheduling/publishing must bind the exact trusted policy_id.")
            if publishing.get("policy_revision") != policy.get("raw", {}).get("revision"):
                report.error("publishing_policy_revision", "$.publishing.policy_revision", "Scheduling/publishing must bind the exact trusted policy revision.")
            if isinstance(approval_for_publish, dict) and (
                publishing.get("policy_id") != approval_for_publish.get("policy_id")
                or publishing.get("policy_revision") != approval_for_publish.get("policy_revision")
            ):
                report.error("publishing_policy_mismatch", "$.publishing", "Publishing policy ID/revision must match the approved package reference.")
            publish_checksum = publishing.get("package_checksum")
            approved_checksum = approval_for_publish.get("package_checksum") if isinstance(approval_for_publish, dict) else None
            if not _nonempty_string(publish_checksum) or publish_checksum != approved_checksum:
                report.error("publisher_checksum", "$.publishing.package_checksum", "Publisher must use the exact approved package checksum.")
        published_raw = publishing.get("published_at")
        if published_raw is not None:
            published_at = _parse_datetime(published_raw)
            if published_at is None:
                report.error("published_at", "$.publishing.published_at", "Use a timezone-aware ISO 8601 datetime.")
        if _state_at_least(state, "PUBLISHED"):
            if not _nonempty_string(publishing.get("media_id")):
                report.error("media_id", "$.publishing.media_id", "Published state requires the platform media ID.")
            if published_at is None:
                report.error("publish_receipt", "$.publishing.published_at", "Published state requires a publication timestamp.")
            if published_at and preflight_checked_at:
                age_seconds = abs((published_at - preflight_checked_at).total_seconds())
                if age_seconds > 900:
                    report.error("stale_publish_preflight", "$.publishing.preflight_checked_at", "Publishing preflight must be rechecked within 15 minutes of publication.")
        utm = publishing.get("utm")
        if not isinstance(utm, dict):
            report.error("utm", "$.publishing.utm", "utm must be an object.")
        else:
            for key in ("source", "medium", "campaign", "content"):
                if key not in utm or (utm.get(key) is not None and not isinstance(utm.get(key), str)):
                    report.error("utm_field", f"$.publishing.utm.{key}", "UTM field must be a string or null.")

    approval = spec.get("approval")
    calculated_checksum = calculate_package_checksum(spec)
    if not isinstance(approval, dict):
        report.error("approval", "$.approval", "approval must be an object.")
    else:
        approval_status = approval.get("status")
        if approval_status not in APPROVAL_STATUSES:
            report.error("approval_status", "$.approval.status", "Unsupported approval status.")
        _validate_remote_scope(approval.get("scope_ids"), "$.approval.scope_ids", canonical_scope, report, required=approval_status in {"approved", "policy_approved"})
        if approval_status == "approved":
            if not _state_at_least(state, "HUMAN_APPROVED"):
                report.error("approval_state_mismatch", "$.state", "Approved decision and lifecycle state must transition together.")
            if policy.get("mode") == "unattended" and policy.get("unattended", {}).get("enabled") is True and policy.get("approval_required") is False:
                report.error("approval_mode", "$.approval.status", "An unattended policy with approval_required false must use policy_approved, not a human approval status.")
            approver_id = approval.get("approver_id", approval.get("approver"))
            approver_role = approval.get("approver_role")
            if not _nonempty_string(approver_id):
                report.error("approver", "$.approval.approver_id", "Approved package needs an approver identity.")
            if approver_role not in {"reviewer", "lead"} or not _mapped_identity(policy.get("raw", {}), approver_id, approver_role):
                report.error("approver_role", "$.approval.approver_role", "Only a mapped reviewer or lead may approve this client/product package.")
            if approver_id != policy.get("raw", {}).get("actor_id"):
                report.error("approval_actor_mismatch", "$.approval.approver_id", "The authenticated/local-policy actor approving must match approver_id.")
            if approval.get("identity_source") not in IDENTITY_SOURCES or approval.get("identity_source") != policy.get("raw", {}).get("identity_source"):
                report.error("approval_identity_source", "$.approval.identity_source", "Approval identity must come from authenticated/local policy context.")
            if approval.get("policy_id") != policy.get("raw", {}).get("policy_id"):
                report.error("approval_policy_id", "$.approval.policy_id", "Approval must bind the exact trusted policy_id.")
            if approval.get("policy_revision") != policy.get("raw", {}).get("revision"):
                report.error("approval_policy_revision", "$.approval.policy_revision", "Approval must bind the exact trusted policy revision.")
            if _parse_datetime(approval.get("approved_at")) is None:
                report.error("approved_at", "$.approval.approved_at", "Use a timezone-aware ISO 8601 approval timestamp.")
            if approval.get("scope") != "design+caption+target+schedule":
                report.error("approval_scope", "$.approval.scope", "Approval scope must cover design, caption, target, and schedule.")
            package_checksum = approval.get("package_checksum")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(package_checksum)):
                report.error("package_checksum", "$.approval.package_checksum", "Use sha256:<64 lowercase hex characters>.")
            elif calculated_checksum != package_checksum:
                report.error("approval_checksum_mismatch", "$.approval.package_checksum", "Stored approval does not match the current publish package.")
        elif approval_status == "policy_approved":
            if not _state_at_least(state, "HUMAN_APPROVED"):
                report.error("approval_state_mismatch", "$.state", "Policy-approved decision and lifecycle state must transition together.")
            if policy.get("mode") != "unattended" or policy.get("unattended", {}).get("enabled") is not True:
                report.error("policy_approval_mode", "$.approval.status", "policy_approved is valid only for an enabled unattended policy.")
            if approval.get("policy_id") != policy.get("raw", {}).get("policy_id"):
                report.error("approval_policy_id", "$.approval.policy_id", "Policy approval must bind the exact trusted policy_id.")
            if approval.get("policy_revision") != policy.get("raw", {}).get("revision"):
                report.error("approval_policy_revision", "$.approval.policy_revision", "Policy approval must bind the exact trusted policy revision.")
            package_checksum = approval.get("package_checksum")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(package_checksum)):
                report.error("package_checksum", "$.approval.package_checksum", "Use sha256:<64 lowercase hex characters>.")
            elif calculated_checksum != package_checksum:
                report.error("approval_checksum_mismatch", "$.approval.package_checksum", "Stored policy approval must match the current publish package.")
        elif _state_at_least(state, "HUMAN_APPROVED"):
            if policy.get("mode") == "unattended" and policy.get("unattended", {}).get("enabled") is True:
                report.error("approval_missing", "$.approval.status", "Unattended lifecycle state requires policy_approved and its preapproval records.")
            else:
                report.error("approval_missing", "$.approval.status", "Lifecycle state requires an approved human decision.")

    _validate_measurement(spec, spec.get("measurement"), state, published_at, report)

    return report


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _parse_cli_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD for --today") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("content_spec", type=Path, help="Content spec JSON path")
    parser.add_argument("--brand", type=Path, help="Optional brand profile JSON path")
    parser.add_argument("--policy", type=Path, help="Trusted local_authenticated_policy JSON path (required for privileged states)")
    parser.add_argument("--actor-id", help="Trusted current runtime identity (required for privileged states)")
    parser.add_argument("--brand-bundle", type=Path, help="Validated Brand Copy Studio four-file bundle directory for privileged claims/recipes/unattended generation")
    parser.add_argument("--brand-policy", type=Path, help="Trusted Brand Copy local_authenticated_policy JSON path (separate from content policy)")
    parser.add_argument("--brand-actor-id", help="Trusted current Brand Copy activation identity (separate from content actor)")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as validation failures")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Emit a machine-readable report")
    parser.add_argument("--today", type=_parse_cli_date, help="Override today's date for deterministic checks")
    parser.add_argument("--show-package-checksum", action="store_true", help="Show the checksum approval should bind")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        spec = _load_json(args.content_spec)
        brand = _load_json(args.brand) if args.brand else None
        policy_context = _load_json(args.policy) if args.policy else None
        brand_policy_context = _load_json(args.brand_policy) if args.brand_policy else None
    except (OSError, json.JSONDecodeError) as exc:
        payload = {"valid": False, "summary": {"errors": 1, "warnings": 0}, "issues": [{"severity": "error", "code": "input", "path": "$", "message": str(exc)}]}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json_output else f"ERROR input $: {exc}")
        return 1

    report = validate_content_spec(
        spec,
        brand=brand,
        today=args.today,
        policy_context=policy_context,
        actor_id=args.actor_id,
        brand_bundle=args.brand_bundle,
        brand_policy_context=brand_policy_context,
        brand_actor_id=args.brand_actor_id,
    )
    checksum = calculate_package_checksum(spec)
    if args.json_output:
        print(json.dumps(report.to_dict(strict=args.strict, checksum=checksum), ensure_ascii=False, indent=2))
    else:
        for issue in report.issues:
            print(f"{issue.severity.upper()} {issue.code} {issue.path}: {issue.message}")
        print(f"Summary: {len(report.errors)} error(s), {len(report.warnings)} warning(s)")
        if args.show_package_checksum:
            print(f"Package checksum: {checksum or 'unavailable until export_checksum exists'}")
        print("VALID" if report.passes(args.strict) else "INVALID")
    return 0 if report.passes(args.strict) else 1


if __name__ == "__main__":
    sys.exit(main())
