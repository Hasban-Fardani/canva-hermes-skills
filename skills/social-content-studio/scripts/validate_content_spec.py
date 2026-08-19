#!/usr/bin/env python3
"""Validate a Social Content Studio JSON record with optional Brand Copy evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from types import MappingProxyType
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

# Anti-slop is an editorial/production quality contract.  It deliberately
# contains no authorship or detector probability field: findings must point to
# an observable copy, visual, evidence, or process issue.
ANTI_SLOP_STATES = {"DESIGN_DRAFT", "BRAND_QA", "HUMAN_APPROVED", "SCHEDULED", "PUBLISHED", "MEASURED"}
ANTI_SLOP_EVIDENCE_KEYS = (
    "ocr",
    "layout",
    "semantic",
    "wcag",
    "rights",
    "recent_similarity",
)
ANTI_SLOP_EVIDENCE_STATUSES = {"pending", "pass", "fail", "not_applicable"}
ANTI_SLOP_HARD_BLOCKER_KEYS = {
    "scope_alignment", "source_and_claim_evidence", "rights_provenance",
    "ocr_exact_match", "layout_integrity", "semantic_contract",
    "wcag_accessibility", "template_controls", "approval_package",
}
ANTI_SLOP_REASON_CODES = {
    "generic_language",
    "same_layout_cluster",
    "repeated_hook",
    "repeated_cta",
    "decorative_filler",
    "unsupported_claim",
    "missing_source",
    "rights_unresolved",
    "ocr_mismatch",
    "layout_collision",
    "semantic_mismatch",
    "wcag_contrast",
    "missing_alt_text",
    "template_scope_mismatch",
    "folder_scope_mismatch",
    "brand_controls_missing",
    "route_not_distinct",
    "route_not_selected",
    "independent_critique_missing",
    "approval_package_missing",
    "REDUNDANT_DECORATIVE_MICROCOPY",
}
COPY_QUALITY_REASON_CODES = {
    "ABSTRACT_WITHOUT_SCENE", "NEGATION_INSIGHT_WITHOUT_EVIDENCE", "FAKE_INTIMACY_WITHOUT_PROVENANCE",
    "GENERIC_MOTIVATIONAL_CLOSURE", "DECORATIVE_SAVE_CTA", "PARAPHRASE_NO_PROGRESS",
    "INTERCHANGEABLE_BRAND_COPY", "UNSUPPORTED_PERSONAL_OR_PERFORMANCE_CLAIM",
    "REDUNDANT_DECORATIVE_MICROCOPY",
}
# Indonesian register findings are editorial warnings, not authorship labels or
# EYD failures.  Keep the codes stable so a native/pairwise review can refer to
# the same observable span across revisions.
INDONESIAN_REASON_CODES = {
    "id_explicit_subject_repeat",
    "id_identical_sentence_frame",
    "id_abstract_nominalization_cluster",
    "id_particle_without_provenance",
    "id_unexplained_code_switch",
    "id_calque_or_translation_residue",
    "id_register_jump",
}
COPY_QUALITY_REASON_CODES |= INDONESIAN_REASON_CODES
INDONESIAN_REGISTERS = {
    "formal_public",
    "neutral_editorial",
    "friendly_conversational",
    "community_specific",
    "colloquial",
    "youth_community",
    "fandom",
    "local_activation",
}
INDONESIAN_COLLOQUIAL_REGISTERS = {
    "friendly_conversational",
    "community_specific",
    "colloquial",
    "youth_community",
    "fandom",
    "local_activation",
}
INDONESIAN_PARTICLES = {
    "yuk", "ayo", "nih", "lho", "kok", "sih", "kan", "deh", "dong", "aja", "ya",
}
INDONESIAN_COLLOQUIAL_MARKERS = {
    "kamu", "gue", "gua", "lu", "lo", "nggak", "gak", "ga", "udah", "pengen", "pake",
    "sampe", "aja", "yuk", "ayo", "nih", "lho", "kok", "sih", "deh", "dong", "bestie",
    "cobain", "gas", "boncos", "bareng", "banget", "pantengin", "cuss", "kalap",
}
INDONESIAN_FORMAL_MARKERS = {
    "anda", "dapat", "mohon", "dimohon", "berdasarkan", "sehubungan", "pelanggan", "pengguna",
    "diharapkan", "silakan", "ketentuan", "persyaratan", "penggunaan",
}
INDONESIAN_ABSTRACT_NOUNS = {
    "pengalaman", "kenyamanan", "kemudahan", "solusi", "peningkatan", "kualitas", "penggunaan",
    "dampak", "layanan", "kebutuhan", "pelaksanaan", "pencapaian", "kesempatan", "keamanan",
    "kepercayaan", "perjalanan", "pemanfaatan", "pengembangan", "perubahan", "efektivitas",
    "efisiensi", "kenyamanan", "keberhasilan", "penyediaan", "pengoptimalan",
}
INDONESIAN_GENERIC_VERBS = {
    "menghadirkan", "meningkatkan", "mewujudkan", "mendukung", "memberikan", "menciptakan",
    "menawarkan", "memastikan", "mengoptimalkan", "memfasilitasi", "menghadirkanlah",
}
INDONESIAN_CONCRETE_WORDS = {
    "tab", "dokumen", "tautan", "pesanan", "sumber", "catatan", "rapat", "kulkas", "menu",
    "parkir", "bandara", "antrean", "file", "berkas", "alamat", "angka", "jam", "lokasi",
    "produk", "aplikasi", "formulir", "tombol", "pesan", "langkah", "keputusan", "pekerjaan",
}
INDONESIAN_ACTION_VERBS = {
    "cek", "buka", "tutup", "pilih", "pesan", "kirim", "baca", "mulai", "simpan", "tulis",
    "gunakan", "datang", "makan", "jalan", "ubah", "kurangi", "mengurangi", "mempercepat",
    "mengecek", "mengemas", "mengirim", "membaca", "membuka", "menutup", "memilih", "menyebut",
    "menyelesaikan", "pisahkan", "kelompokkan", "bandingkan", "tandai", "daftar", "ajak", "coba",
}
INDONESIAN_CODE_SWITCH_PHRASES = (
    "now or never", "stay tuned", "feel the excitement", "you can", "after that", "finally",
    "check out", "stopped by", "quality time", "skin journey", "worth it", "discover",
    "experience", "feel the", "best practice", "settings", "save", "dashboard",
)
INDONESIAN_SUBJECTS = {
    "kami", "kita", "anda", "kamu", "gue", "gua", "lu", "lo", "produk", "produk ini",
    "layanan", "layanan ini", "tim", "tim kami", "pengguna", "pelanggan",
}
INDONESIAN_AUXILIARIES = {"dapat", "bisa", "akan", "sudah", "telah", "perlu", "harus", "boleh"}
ID_REVIEW_METHODS = {
    "native_editor",
    "native_review",
    "pairwise_native_editor",
    "pairwise_review",
    "pairwise",
    "neutral_editorial_fallback",
    "neutral-editorial-fallback",
}

# Text that is visible in a Canva design is content, even when it is small.
# These roles are intentionally narrow: a role is only an exception when it
# also has a concrete justification and provenance.  This prevents a generic
# "label" or "footer" tag from becoming a blanket bypass for filler copy.
MICROCOPY_FUNCTIONAL_ROLES = {
    "source",
    "legal",
    "accessibility",
    "navigation",
    "action",
    "label",
    "branding",
    "annotation",
}
MICROCOPY_PROVENANCE_KEYS = (
    "provenance",
    "source_ids",
    "source_id",
    "proof_ids",
    "claim_id",
    "source_ref",
    "legal_reference",
    "brand_id",
)
MICROCOPY_PAGE_COUNT_RE = re.compile(
    r"^(?:page|slide|halaman)\s*\d+(?:\s*(?:/|of|dari)\s*\d+)?$|^\d+\s*/\s*\d+$",
    re.IGNORECASE,
)
MICROCOPY_ARROW_RE = re.compile(r"^[\s\-–—·•]*(?:[←↑→↓↔↕➜➝➞➟➤➔»«]|->|<-)+[\s\-–—·•]*$")
MICROCOPY_FAKE_ANNOTATION_RE = re.compile(
    r"^(?:note|catatan|tip|pro\s+tip|insight|ps|psst|fyi|quick\s+note)\s*(?:[:.!-]\s*.*)?$",
    re.IGNORECASE,
)
MICROCOPY_FILLER_RE = re.compile(
    r"^(?:(?:just\s+)?a\s+little\s+reminder|just\s+a\s+thought|let\s+that\s+sink\s+in|you(?:'|’)ve\s+got\s+this|"
    r"good\s+things\s+take\s+time|keep\s+going|small\s+steps|sedikit\s+pengingat|"
    r"catatan\s+kecil|tetap\s+semangat|semangat\s+(?:hari\s+ini|ya))\s*[.!…]*$",
    re.IGNORECASE,
)
MICROCOPY_REDUNDANT_LABEL_RE = re.compile(
    r"^(?:section|chapter|category|topic|overview|introduction|intro|guide|tips?|insight|"
    r"the\s+basics|the\s+takeaway|in\s+focus|our\s+approach|next|more|about|"
    r"bagian|bab|kategori|topik|ringkasan|pengantar|panduan|tips?|insight|"
    r"bagian\s+\d+|part\s+\d+|step\s+\d+)\s*[.!…]*$",
    re.IGNORECASE,
)
MICROCOPY_DECORATIVE_JOB_RE = re.compile(
    r"\b(?:decorative|ornament(?:al)?|filler|fill\s+space|visual\s+interest|hiasan|ornamen|pengisi)\b",
    re.IGNORECASE,
)
JSON_PATH_TOKEN_RE = re.compile(r"(?:\.([A-Za-z_][A-Za-z0-9_-]*)|\[(\d+)\])")
ANTI_SLOP_REASON_CODE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,63}")
ANTI_SLOP_SLOP_DIMENSIONS = (
    "generic_language",
    "visual_convergence",
    "decorative_filler",
    "evidence_gap",
    "process_debt",
)
ANTI_SLOP_RUBRIC_WEIGHTS = {
    "brief_and_communication_fit": 20,
    "distinctive_idea": 20,
    "brand_expression": 15,
    "hierarchy_and_readability": 15,
    "copy_clarity_and_evidence": 15,
    "craft_and_consistency": 10,
    "channel_and_accessibility": 5,
}
UNIVERSAL_DETECTOR_KEY_RE = re.compile(
    r"(?:ai|llm|model|machine)[_-]?(?:probability|score|likelihood|authorship)|"
    r"(?:detector|classifier)(?:[_-](?:score|probability|confidence|result|label))?|"
    r"(?:authorship|human(?:ness|likeness))[_-]?(?:probability|score|likelihood|confidence)",
    re.IGNORECASE,
)
GENERIC_ROUTE_RE = re.compile(
    r"\b(?:konten|post|materi)\s+(?:edukasi|informatif)|"
    r"\b(?:meningkatkan|membangun)\s+(?:awareness|engagement)|"
    r"\b(?:bagikan|memberikan)\s+(?:tips|informasi|edukasi)\b|"
    r"\b(?:solusi|layanan)\s+(?:inovatif|terbaik|mudah|cepat|aman|terpercaya)\b",
    re.IGNORECASE,
)

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


@dataclass(frozen=True)
class TrustedPolicyContext:
    """Immutable receipt for a policy loaded outside the content record."""
    payload: Any
    source_path: str
    canonical_digest: str

    @property
    def data(self) -> dict[str, Any]:
        return self.payload


def load_trusted_policy(path: Path) -> TrustedPolicyContext:
    data = _load_json(path)
    if not isinstance(data, dict):
        raise ValueError("Trusted policy file must contain an object")
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return TrustedPolicyContext(MappingProxyType(data), str(path.resolve()), "sha256:" + hashlib.sha256(canonical).hexdigest())
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
    evidence_span: dict[str, Any] | None = None


class Report:
    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def error(self, code: str, path: str, message: str, evidence_span: dict[str, Any] | None = None) -> None:
        self.issues.append(Issue("error", code, path, message, evidence_span))

    def warning(self, code: str, path: str, message: str, evidence_span: dict[str, Any] | None = None) -> None:
        self.issues.append(Issue("warning", code, path, message, evidence_span))

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
    if not isinstance(scope, dict) or any(not isinstance(scope.get(key), str) for key in ("tenant_id", "client_id", "product_id", "brand_id")):
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


def _canonical_unattended_authorization(value: Any) -> dict[str, Any] | None:
    """Return only capability-bearing unattended fields in canonical form.

    The embedded record is audit-only.  A separately loaded policy must carry
    this complete subtree, so changing a target, claim, recipe, budget, or
    template cannot smuggle a new capability past the trusted boundary.
    """

    if not isinstance(value, dict):
        return None
    preapproved = value.get("preapproved")
    if not isinstance(preapproved, dict):
        return None
    return {
        "enabled": value.get("enabled"),
        "policy_id": value.get("policy_id"),
        "policy_revision": value.get("policy_revision"),
        "scope": value.get("scope"),
        "enabled_by": value.get("enabled_by"),
        "enabled_by_role": value.get("enabled_by_role"),
        "enabled_at": value.get("enabled_at"),
        "preapproved": {
            "copy_recipe_ids": preapproved.get("copy_recipe_ids"),
            "copy_recipe_versions": preapproved.get("copy_recipe_versions"),
            "copy_recipe_brand_revisions": preapproved.get("copy_recipe_brand_revisions"),
            "template_ids": preapproved.get("template_ids"),
            "template_versions": preapproved.get("template_versions"),
            "template_provider_ids": preapproved.get("template_provider_ids"),
            "claim_ids": preapproved.get("claim_ids"),
            "targets": preapproved.get("targets"),
            "pillars": preapproved.get("pillars"),
            "formats": preapproved.get("formats"),
            "field_budgets": preapproved.get("field_budgets"),
        },
    }


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
            not _nonempty_string(identity) or identity in {"*", "any", "prompt", "all", "everyone"} for identity in identities
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
    if not isinstance(policy_context, TrustedPolicyContext):
        if policy_context is spec.get("policy") or policy_context == spec.get("policy"):
            report.error("trusted_policy_embedded", "$policy", "The embedded or copied policy snapshot cannot authorize privileged content.")
        report.error("trusted_policy_type", "$policy", "Privileged states require an immutable TrustedPolicyContext produced by load_trusted_policy; arbitrary dictionaries cannot authorize.")
        return
    policy_context = policy_context.data
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
    for key in ("policy_id", "revision", "actor_id", "actor_role", "identity_source"):
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
        trusted_unattended = policy_context.get("unattended")
        embedded_authorization = _canonical_unattended_authorization(embedded_unattended)
        trusted_authorization = _canonical_unattended_authorization(trusted_unattended)
        if trusted_authorization is None or trusted_authorization != embedded_authorization:
            report.error(
                "trusted_policy_unattended_exact",
                "$policy.unattended",
                "Trusted policy must exactly match the complete embedded unattended authorization subtree; embedded content remains audit-only.",
            )
        embedded_preapproved = embedded_unattended.get("preapproved")
        embedded_provider_ids = embedded_preapproved.get("template_provider_ids") if isinstance(embedded_preapproved, dict) else None
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
    if policy_context.get("identity_source") not in IDENTITY_SOURCES:
        report.error("trusted_policy_identity_source", "$policy.identity_source", "Trusted policy identity_source must be an authenticated source.")
    if policy_context.get("actor_role") not in POLICY_ROLES:
        report.error("trusted_policy_actor_role", "$policy.actor_role", "Trusted policy actor_role must be an allowlisted role.")
    mapping = policy_context.get("role_mapping")
    if isinstance(mapping, dict) and policy_context.get("actor_id") not in mapping.get(policy_context.get("actor_role"), []):
        report.error("trusted_policy_actor_membership", "$policy.role_mapping", "Trusted actor must be explicitly listed in the trusted role mapping.")
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
            if role not in POLICY_ROLES or not isinstance(identities, list) or any(identity in {"*", "any", "prompt", "all", "everyone"} for identity in identities):
                report.error("trusted_policy_roles", "$policy.role_mapping", "Trusted role mapping may not contain wildcard or prompt identities.")


BRAND_BUNDLE_FILES = ("brand-profile.json", "claim-registry.json", "template-registry.json", "provenance.json")


def _load_brand_bundle_validator() -> Any:
    """Load the sibling Brand Copy validator without copying its contract here."""

    cached = sys.modules.get("social_content_brand_bundle_validator")
    if cached is not None:
        return cached
    validator_path = Path(__file__).resolve().parents[2] / "brand-copy-studio" / "scripts" / "validate_brand_bundle.py"
    if not validator_path.is_file():
        return None
    module_spec = importlib.util.spec_from_file_location("social_content_brand_bundle_validator", validator_path)
    if module_spec is None or module_spec.loader is None:
        return None
    module = importlib.util.module_from_spec(module_spec)
    module_name = module_spec.name
    previous_module = sys.modules.get(module_name)
    # Python 3.14's dataclass resolver requires the dynamically loaded module
    # to be visible in sys.modules while decorators execute.
    sys.modules[module_name] = module
    try:
        module_spec.loader.exec_module(module)
    except (ImportError, OSError, SyntaxError, TypeError, ValueError):
        if previous_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module
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


def _validate_master_brand_bundle(
    master_brand_bundle: str | Path,
    expected_scope: dict[str, str] | None,
    validator: Any,
    brand_policy_context: Any,
    brand_actor_id: str | None,
    report: Report,
) -> str | None:
    """Load a canonical master bundle and return its independently read revision."""

    root = Path(master_brand_bundle).expanduser()
    if not root.is_dir():
        report.error("master_brand_bundle_path", "$master_brand_bundle", "Master Brand Copy bundle directory does not exist.")
        return None
    documents = _read_brand_bundle_documents(root, report)
    if documents is None:
        return None

    profile = documents["brand-profile.json"]
    profile_scope = profile.get("scope") if isinstance(profile.get("scope"), dict) else {}
    for field in ("tenant_id", "client_id", "product_id", "parent_brand_revision"):
        if field in profile and field in profile_scope and profile.get(field) != profile_scope.get(field):
            report.error(
                "master_brand_bundle_scope_conflict",
                f"$master_brand_bundle/brand-profile.json.scope.{field}",
                "Master Brand Copy top-level and nested scope fields must agree exactly.",
            )

    master_product = profile_scope.get("product_id", profile.get("product_id"))
    master_parent_revision = profile_scope.get("parent_brand_revision", profile.get("parent_brand_revision"))
    if master_product not in (None, ""):
        report.error(
            "master_brand_bundle_product",
            "$master_brand_bundle/brand-profile.json.scope.product_id",
            "The runtime master Brand Copy bundle must have a null product_id.",
        )
    if master_parent_revision not in (None, ""):
        report.error(
            "master_brand_bundle_parent",
            "$master_brand_bundle/brand-profile.json.scope.parent_brand_revision",
            "A runtime master Brand Copy bundle must not carry parent_brand_revision.",
        )
    if expected_scope and (
        profile_scope.get("tenant_id", profile.get("tenant_id")) != expected_scope.get("tenant_id")
        or profile_scope.get("client_id", profile.get("client_id")) != expected_scope.get("client_id")
        or profile.get("brand_id") != expected_scope.get("brand_id")
    ):
        report.error(
            "master_brand_bundle_scope",
            "$master_brand_bundle",
            "Master Brand Copy bundle tenant, client, and brand must match the content isolation scope.",
        )
    if profile.get("status") != "active":
        report.error(
            "master_brand_bundle_status",
            "$master_brand_bundle/brand-profile.json.status",
            "A privileged product overlay requires an active master Brand Copy bundle.",
        )
    revision = profile.get("revision")
    if not _nonempty_string(revision):
        report.error(
            "master_brand_bundle_revision",
            "$master_brand_bundle/brand-profile.json.revision",
            "The master Brand Copy profile must carry a non-empty canonical revision.",
        )
        revision = None

    if validator is not None:
        # An overlay Brand policy is product-scoped and cannot authorize a
        # master scope. When no master-scoped policy context was supplied, the
        # sibling validator still provides structural/evidence validation; the
        # overlay's separate Brand authority remains required for privileged
        # consumption below.
        master_policy = None
        master_actor_id = None
        if brand_policy_context is not None and hasattr(brand_policy_context, "as_mapping"):
            candidate = brand_policy_context.as_mapping()
            candidate_scope = candidate.get("scope") if isinstance(candidate, dict) else None
            if isinstance(candidate_scope, dict) and candidate_scope.get("product_id") in (None, ""):
                master_policy = brand_policy_context
                master_actor_id = brand_actor_id
        expected_master_scope = {
            "tenant_id": expected_scope.get("tenant_id") if expected_scope else None,
            "client_id": expected_scope.get("client_id") if expected_scope else None,
            "product_id": None,
            "parent_brand_revision": None,
        }
        try:
            master_errors = validator.validate_brand_bundle(
                root,
                expected_brand_id=expected_scope.get("brand_id") if expected_scope else None,
                expected_scope=expected_master_scope,
                policy=master_policy,
                actor_id=master_actor_id,
            )
        except (AttributeError, TypeError, OSError, ValueError) as exc:
            master_errors = [f"validator invocation failed: {exc}"]
        authority_only = (
            "external trusted local access policy",
            "external access policy scope",
            "requires trusted runtime actor_id",
            "requires external policy scope and actor match",
            "authorization actor_id and role are not mapped by external access policy",
        )
        for error in master_errors:
            if master_policy is None and any(marker in str(error) for marker in authority_only):
                continue
            report.error("master_brand_bundle_invalid", "$master_brand_bundle", str(error))
    return revision if isinstance(revision, str) else None


def _validate_brand_bundle(
    brand_bundle: str | Path | None,
    expected_scope: dict[str, str] | None,
    state: Any,
    spec: dict[str, Any],
    report: Report,
    *,
    brand_policy_context: Any = None,
    brand_actor_id: str | None = None,
    master_brand_bundle: str | Path | None = None,
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

    product_overlay = bundle_product is not None
    validator = _load_brand_bundle_validator()
    trusted_parent_revision = None
    if privileged and product_overlay:
        if master_brand_bundle is None:
            report.error(
                "brand_master_bundle_required",
                "$master_brand_bundle",
                "Privileged product overlays require an independently supplied master Brand Copy bundle.",
            )
        elif validator is None:
            report.error(
                "brand_bundle_validator",
                "$master_brand_bundle",
                "The sibling Brand Copy bundle validator is unavailable; fail closed for privileged use.",
            )
        else:
            trusted_parent_revision = _validate_master_brand_bundle(
                master_brand_bundle,
                expected_scope,
                validator,
                brand_policy_context,
                brand_actor_id,
                report,
            )
        if trusted_parent_revision is not None and bundle_scope["parent_brand_revision"] != trusted_parent_revision:
            report.error(
                "brand_master_revision_mismatch",
                "$brand_bundle/brand-profile.json.scope.parent_brand_revision",
                "Product overlay parent_brand_revision must exactly match the canonical revision from the independently loaded master Brand Copy bundle.",
            )

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

    if validator is None:
        report.error("brand_bundle_validator", "$brand_bundle", "The sibling Brand Copy bundle validator is unavailable; fail closed for privileged use.")
    elif not brand_authority_missing:
        expected_parent_revision = (
            trusted_parent_revision
            if product_overlay and trusted_parent_revision is not None
            else bundle_scope["parent_brand_revision"]
        )
        bundle_expected_scope = {
            "tenant_id": bundle_scope["tenant_id"],
            "client_id": bundle_scope["client_id"],
            "product_id": bundle_product,
            "parent_brand_revision": expected_parent_revision,
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


def _message_unit_text(unit: dict[str, Any]) -> str:
    """Return the visible text from a message-unit record."""

    for key in ("text", "value", "content", "copy"):
        value = unit.get(key)
        if isinstance(value, str):
            return value
    return ""


def _message_unit_path(unit: dict[str, Any], fallback: str) -> str:
    for key in ("path", "field_path", "json_path", "location"):
        value = unit.get(key)
        if isinstance(value, str) and value.strip():
            return value
    surface = unit.get("surface")
    field = unit.get("field", unit.get("element"))
    if isinstance(surface, str) and isinstance(field, str) and surface.strip() and field.strip():
        prefix = surface.strip()
        if not prefix.startswith("$"):
            prefix = f"$.{prefix}"
        return f"{prefix}.{field.strip()}"
    return fallback


def _resolve_json_path(value: Any, path: str) -> tuple[bool, Any]:
    """Resolve the small JSONPath subset used for visible text bindings."""

    if not isinstance(path, str) or not path.startswith("$"):
        return False, None
    current = value
    position = 1
    if path == "$":
        return True, current
    while position < len(path):
        match = JSON_PATH_TOKEN_RE.match(path, position)
        if match is None:
            return False, None
        key, index_text = match.groups()
        if key is not None:
            if not isinstance(current, dict) or key not in current:
                return False, None
            current = current[key]
        else:
            if not isinstance(current, list):
                return False, None
            index = int(index_text)
            if index >= len(current):
                return False, None
            current = current[index]
        position = match.end()
    return True, current


def _message_unit_alias_conflicts(spec: dict[str, Any]) -> list[str]:
    conflicts: list[str] = []
    scopes: list[tuple[str, dict[str, Any]]] = [("$", spec)]
    slides = spec.get("slides")
    if isinstance(slides, list):
        scopes.extend((f"$.slides[{index}]", slide) for index, slide in enumerate(slides) if isinstance(slide, dict))
    caption = spec.get("caption")
    if isinstance(caption, dict):
        scopes.append(("$.caption", caption))
    for path, scope in scopes:
        if "message_units" in scope and "text_elements" in scope:
            conflicts.append(path)
    return conflicts


def _message_unit_information_job(unit: dict[str, Any]) -> str | None:
    for key in ("information_job", "message_job", "job"):
        value = unit.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _message_unit_role(unit: dict[str, Any]) -> str | None:
    for key in ("functional_role", "role", "function"):
        value = unit.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().casefold()
    return None


def _provenance_id_values(value: Any) -> tuple[list[str], bool]:
    """Return provenance IDs and whether the supplied shape is well-formed."""

    if isinstance(value, str):
        return ([value], bool(value.strip()))
    if isinstance(value, list):
        if not value or any(not isinstance(item, str) or not item.strip() for item in value):
            return ([], False)
        return (value, True)
    return ([], False)


def _approved_provenance_ids(spec: dict[str, Any], authority: dict[str, Any] | None) -> set[str]:
    """Return IDs from independently validated authority, never the mutable content packet."""

    ids: set[str] = set()
    if not isinstance(authority, dict):
        return ids
    profile = authority.get("profile")
    if isinstance(profile, dict) and profile.get("status") in {"active", "approved"}:
        brand_id = profile.get("brand_id")
        if isinstance(brand_id, str) and brand_id.strip():
            ids.add(brand_id)
    documents = authority.get("documents") if isinstance(authority.get("documents"), dict) else {}
    provenance = documents.get("provenance.json") if isinstance(documents.get("provenance.json"), dict) else {}
    sources = provenance.get("sources", [])
    if isinstance(sources, list):
        for record in sources:
            if not isinstance(record, dict):
                continue
            authorization = record.get("authorization")
            status = authorization.get("status") if isinstance(authorization, dict) else record.get("status")
            identifier = record.get("source_id")
            if status in {"approved", "exact"} and isinstance(identifier, str) and identifier.strip():
                ids.add(identifier)
    for key, records in (("claim-registry.json", authority.get("claims")), ("template-registry.json", authority.get("templates"))):
        if not isinstance(records, list):
            document = documents.get(key) if isinstance(documents.get(key), dict) else {}
            records = document.get("claims", document.get("templates", []))
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, dict) or record.get("status") != "approved":
                continue
            identifier = record.get("id", record.get("claim_id"))
            if isinstance(identifier, str) and identifier.strip():
                ids.add(identifier)
    return ids


def _approved_brand_asset_ids(authority: dict[str, Any] | None) -> set[str]:
    """Return only asset IDs from an independently validated active brand bundle."""

    if not isinstance(authority, dict):
        return set()
    profile = authority.get("profile")
    if not isinstance(profile, dict) or profile.get("status") not in {"active", "approved"}:
        return set()
    identifiers: set[str] = set()
    for key in ("distinctive_assets", "brand_assets", "visual_assets", "assets"):
        records = profile.get(key, [])
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            rights = record.get("rights")
            rights_status = rights.get("status") if isinstance(rights, dict) else None
            if record.get("status") != "approved" and record.get("evidence_status") not in {"exact", "observed"} and rights_status not in {"approved", "exact"}:
                continue
            for field in ("id", "asset_id", "brand_asset_id", "asset_ref"):
                value = record.get(field)
                if isinstance(value, str) and value.strip():
                    identifiers.add(value)
    return identifiers


def _validate_message_unit_provenance(
    unit: dict[str, Any],
    path: str,
    spec: dict[str, Any],
    role: str | None,
    report: Report,
    authority: dict[str, Any] | None,
) -> bool:
    """Validate provenance shape and resolve IDs used by functional roles."""

    id_fields = ("source_ids", "proof_ids", "source_id", "source_ref", "claim_id", "legal_reference", "brand_id")
    ids: list[str] = []
    valid = True
    for key in id_fields:
        if key not in unit:
            continue
        values, field_valid = _provenance_id_values(unit.get(key))
        if not field_valid:
            report.error("message_unit_provenance_type", f"{path}.{key}", "Provenance IDs must be non-empty strings or a non-empty list of non-empty strings.")
            valid = False
        ids.extend(values)

    provenance = unit.get("provenance")
    required_role = role in {"source", "legal", "accessibility", "navigation", "label", "branding", "annotation"}
    if required_role and provenance is None and not ids:
        report.error("message_unit_provenance_missing", f"{path}.provenance", "This functional role requires provenance or a top-level provenance ID field.")
        valid = False
    if provenance is not None:
        if not isinstance(provenance, (dict, list)):
            report.error("message_unit_provenance_type", f"{path}.provenance", "provenance must be an object or list; IDs inside it must be non-empty strings.")
            valid = False
        elif isinstance(provenance, list):
            values, field_valid = _provenance_id_values(provenance)
            if not field_valid:
                report.error("message_unit_provenance_type", f"{path}.provenance", "A provenance list must contain non-empty string IDs.")
                valid = False
            ids.extend(values)
        else:
            recognized = False
            for key in id_fields:
                if key not in provenance:
                    continue
                recognized = True
                values, field_valid = _provenance_id_values(provenance.get(key))
                if not field_valid:
                    report.error("message_unit_provenance_type", f"{path}.provenance.{key}", "Provenance IDs must be non-empty strings or a non-empty list of non-empty strings.")
                    valid = False
                ids.extend(values)
            for key in ("id", "ref"):
                if key in provenance:
                    recognized = True
                    value = provenance.get(key)
                    if not isinstance(value, str) or not value.strip():
                        report.error("message_unit_provenance_type", f"{path}.provenance.{key}", "Provenance references must be non-empty strings.")
                        valid = False
                    else:
                        ids.append(value)
            if not recognized:
                report.error("message_unit_provenance_type", f"{path}.provenance", "provenance must contain a non-empty ID or reference.")
                valid = False

    if role in {"source", "label", "branding", "annotation"} and not ids:
        report.error("message_unit_provenance_id_missing", f"{path}.provenance", "This functional role requires at least one provenance ID.")
        valid = False
    approved_ids = _approved_provenance_ids(spec, authority)
    unresolved = sorted(set(ids) - approved_ids)
    if required_role and unresolved:
        report.error(
            "message_unit_provenance_unresolved",
            f"{path}.provenance",
            f"Provenance IDs must resolve to scoped source/proof/claim/brand records; unresolved: {unresolved}.",
        )
        valid = False
    return valid


def _message_unit_role_justification(unit: dict[str, Any]) -> str | None:
    for key in ("role_justification", "justification", "rationale", "reason"):
        value = unit.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _message_unit_is_obviously_decorative(text: str) -> bool:
    candidate = re.sub(r"\s+", " ", text.strip())
    if not candidate:
        return False
    if MICROCOPY_PAGE_COUNT_RE.fullmatch(candidate) or MICROCOPY_ARROW_RE.fullmatch(candidate):
        return True
    if (
        MICROCOPY_FAKE_ANNOTATION_RE.fullmatch(candidate)
        or MICROCOPY_FILLER_RE.fullmatch(candidate)
        or MICROCOPY_REDUNDANT_LABEL_RE.fullmatch(candidate)
    ):
        return True
    return False


def _message_unit_decorative_role_allowed(text: str, role: str | None, role_is_justified: bool) -> bool:
    """Allow only semantically matching, provenance-backed exceptions."""

    if not role_is_justified:
        return False
    candidate = re.sub(r"\s+", " ", text.strip())
    if MICROCOPY_PAGE_COUNT_RE.fullmatch(candidate) or MICROCOPY_ARROW_RE.fullmatch(candidate):
        return role == "navigation"
    if MICROCOPY_FAKE_ANNOTATION_RE.fullmatch(candidate):
        return role == "annotation"
    if MICROCOPY_FILLER_RE.fullmatch(candidate):
        return False
    if MICROCOPY_REDUNDANT_LABEL_RE.fullmatch(candidate):
        return role in {"accessibility", "branding", "label", "navigation"}
    return True


def _message_unit_action_allowed(path: str, text: str, role: str | None = "action") -> bool:
    """Recognize non-empty, non-decorative action copy only on action surfaces."""

    if role != "action":
        return False
    field = path.rsplit(".", 1)[-1].casefold() if isinstance(path, str) else ""
    action_path = field in {"cta", "action", "button", "link", "next", "previous", "prev", "submit"}
    candidate = re.sub(r"\s+", " ", text.strip())
    has_words = bool(re.search(r"[\w]", candidate, flags=re.UNICODE))
    return action_path and len(candidate) >= 2 and has_words and not _message_unit_is_obviously_decorative(candidate)


def _message_unit_role_evidence(
    path: str,
    unit: dict[str, Any],
    role: str | None,
    spec: dict[str, Any],
    authority: dict[str, Any] | None,
) -> bool:
    """Require role-specific semantics bound to content or approved brand assets."""

    if role == "label":
        for key in ("label_for", "target_field", "control_id", "for"):
            target = unit.get(key)
            if isinstance(target, str) and target.startswith("$"):
                exists, value = _resolve_json_path(spec, target)
                if exists and isinstance(value, str) and value.strip():
                    return True
        return False
    evidence_keys = {
        "navigation": ("navigation_target", "destination", "destination_path", "href", "target_path", "route"),
        "accessibility": ("aria_for", "accessibility_target", "assistive_target", "screen_reader_for"),
    }
    if role == "branding":
        approved_assets = _approved_brand_asset_ids(authority)
        for key in ("brand_asset_id", "brand_asset_ref", "brand_mark_id", "logo_id"):
            values, valid = _provenance_id_values(unit.get(key)) if key in unit else ([], False)
            if valid and values and set(values).issubset(approved_assets):
                return True
        return False
    if role in {"navigation", "accessibility"}:
        for key in evidence_keys[role]:
            target = unit.get(key)
            if not isinstance(target, str) or not target.strip():
                continue
            if target.startswith("$"):
                exists, value = _resolve_json_path(spec, target)
                if exists and (role == "navigation" or isinstance(value, str)):
                    return True
            elif key == "href" and _valid_https_url(target):
                return True
        return False
    return True


def _message_unit_job_is_distinct(text: str, information_job: str | None) -> bool:
    """Reject jobs that merely rename a decorative element or its ornament."""

    if not information_job:
        return False
    normalized_job = re.sub(r"\s+", " ", information_job.casefold().strip())
    normalized_text = re.sub(r"\s+", " ", text.casefold().strip())
    if MICROCOPY_DECORATIVE_JOB_RE.search(normalized_job):
        return False
    if normalized_job in {normalized_text, "label", "header", "footer", "annotation", "page count", "page number"}:
        return False
    return True


def _implicit_message_units(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Represent legacy visible fields for pattern checks and migration hints."""

    units: list[dict[str, Any]] = []
    slides = spec.get("slides")
    if isinstance(slides, list):
        for index, slide in enumerate(slides):
            if not isinstance(slide, dict):
                continue
            for field in ("headline", "body", "cta"):
                text = slide.get(field)
                if isinstance(text, str) and text.strip():
                    units.append(
                        {
                            "text": text,
                            "path": f"$.slides[{index}].{field}",
                            "information_job": slide.get("information_job"),
                            "functional_role": "action" if field == "cta" else None,
                            "_implicit": True,
                        }
                    )
    caption = spec.get("caption")
    if isinstance(caption, dict):
        for field in ("hook", "body", "cta"):
            text = caption.get(field)
            if isinstance(text, str) and text.strip():
                units.append(
                    {
                        "text": text,
                        "path": f"$.caption.{field}",
                        "functional_role": "action" if field == "cta" else None,
                        "_implicit": True,
                    }
                )
    return units


def _declared_message_units(spec: dict[str, Any]) -> tuple[list[tuple[str, dict[str, Any]]], bool]:
    """Collect canonical and nested text manifests without treating text as instructions."""

    declared: list[tuple[str, dict[str, Any]]] = []
    explicit = False
    for key in ("message_units", "text_elements"):
        value = spec.get(key)
        if value is None:
            continue
        explicit = True
        if not isinstance(value, list):
            declared.append((f"$.{key}", {"_invalid": value}))
            continue
        for index, unit in enumerate(value):
            declared.append((f"$.{key}[{index}]", unit if isinstance(unit, dict) else {"_invalid": unit}))

    slides = spec.get("slides")
    if isinstance(slides, list):
        for index, slide in enumerate(slides):
            if not isinstance(slide, dict):
                continue
            for key in ("message_units", "text_elements"):
                value = slide.get(key)
                if value is None:
                    continue
                explicit = True
                if not isinstance(value, list):
                    declared.append((f"$.slides[{index}].{key}", {"_invalid": value}))
                    continue
                for unit_index, unit in enumerate(value):
                    declared.append(
                        (
                            f"$.slides[{index}].{key}[{unit_index}]",
                            unit if isinstance(unit, dict) else {"_invalid": unit},
                        )
                    )

    caption = spec.get("caption")
    if isinstance(caption, dict):
        for key in ("message_units", "text_elements"):
            value = caption.get(key)
            if value is None:
                continue
            explicit = True
            if not isinstance(value, list):
                declared.append((f"$.caption.{key}", {"_invalid": value}))
                continue
            for unit_index, unit in enumerate(value):
                declared.append(
                    (
                        f"$.caption.{key}[{unit_index}]",
                        unit if isinstance(unit, dict) else {"_invalid": unit},
                    )
                )
    return declared, explicit


def _validate_message_unit_contract(
    spec: dict[str, Any],
    state: Any,
    report: Report,
    provenance_authority: dict[str, Any] | None = None,
) -> None:
    """Require every production text unit to have a job or provenance-backed role.

    The pattern checks are deliberately conservative.  They only flag a short
    text when it is a known page-count/arrow/filler/annotation pattern or when
    the same unqualified theme header is repeated.  Source, legal,
    accessibility, navigation, action, label, branding, and annotation units
    remain valid when their role is justified and provenance is recorded.
    """

    production = _anti_slop_route_required(spec, state)
    declared, explicit = _declared_message_units(spec)
    for conflict in _message_unit_alias_conflicts(spec):
        report.error(
            "message_unit_alias_conflict",
            conflict,
            "Declare only one message_units/text_elements manifest alias at each scope; accepting both would make the visible-text contract ambiguous.",
        )
    if production and not explicit and _implicit_message_units(spec):
        report.error(
            "message_units_required",
            "$.message_units",
            "Canva mutation/production requires a message_units (or text_elements) manifest so every visible text element has an information_job or justified functional_role.",
        )
    if production and explicit:
        declared_paths = {
            _message_unit_path(unit, "")
            for _, unit in declared
            if "_invalid" not in unit and _message_unit_path(unit, "")
        }
        implicit_paths = {unit["path"] for unit in _implicit_message_units(spec)}
        missing_paths = sorted(implicit_paths - declared_paths)
        if missing_paths:
            report.error(
                "message_unit_coverage",
                "$.message_units",
                "Production message_units must cover every non-empty headline, body, CTA, caption hook, caption body, and caption CTA; missing: "
                + ", ".join(missing_paths),
            )

    bound_paths: dict[str, list[str]] = {}
    for container_path, unit in declared:
        if "_invalid" in unit:
            continue
        bound_path = _message_unit_path(unit, container_path)
        if bound_path:
            bound_paths.setdefault(bound_path, []).append(container_path)
    for bound_path, containers in bound_paths.items():
        if len(containers) > 1:
            report.error(
                "message_unit_duplicate_path",
                bound_path,
                "Each visible content path may be declared by only one message unit across top-level and nested manifests/aliases.",
            )

    units: list[tuple[str, dict[str, Any]]] = list(declared)
    # Implicit fields support migration warnings and catch obvious decorative
    # copy even before a production manifest has been added.
    units.extend((unit["path"], unit) for unit in _implicit_message_units(spec))
    if not units:
        return

    normalized_visible: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for path, unit in declared:
        if "_invalid" in unit:
            report.error("message_unit_type", path, "Each message unit must be an object.")
            continue
        path = _message_unit_path(unit, path)
        text_key = "text"
        text = unit.get(text_key)
        if text_key not in unit:
            report.error("message_unit_text_required", f"{path}.{text_key}", "Each accepted message unit must declare its canonical text in text.")
            text = ""
        elif not isinstance(text, str):
            report.error("message_unit_text_type", f"{path}.{text_key}", "Visible message-unit text must be a string.")
            text = ""
        bound_path = path
        path_exists, actual_value = _resolve_json_path(spec, bound_path)
        if not bound_path or not path_exists:
            report.error("message_unit_path_invalid", f"{path}.path", "Message-unit path must resolve to an existing content field.")
        elif not isinstance(actual_value, str):
            report.error("message_unit_path_type", f"{path}.path", "Message-unit path must resolve to a string text value.")
        elif text != actual_value:
            report.error("message_unit_text_mismatch", f"{path}.text", "Message-unit text must exactly match the value at its path.")
        visible = unit.get("visible", True)
        if not isinstance(visible, bool):
            report.error("message_unit_visible", f"{path}.visible", "visible must be a boolean when supplied.")
            visible = True
        if visible and not text.strip():
            report.error("message_unit_text", f"{path}.text", "Visible message units require non-empty text.")
            continue
        if not visible and isinstance(actual_value, str) and actual_value.strip():
            report.error(
                "message_unit_visibility_mismatch",
                f"{path}.visible",
                "visible:false cannot suppress canonical visible copy; resolve the path and classify the actual text with its job or functional role.",
            )
            visible = True
        if not visible:
            continue
        if not _nonempty_string(_message_unit_path(unit, "")):
            report.error("message_unit_location", path, "Each visible message unit needs a stable path or location.")
        job = _message_unit_information_job(unit)
        role = _message_unit_role(unit)
        justification = _message_unit_role_justification(unit)
        has_job = _message_unit_job_is_distinct(text, job)
        if role is not None and role not in MICROCOPY_FUNCTIONAL_ROLES:
            report.error(
                "message_unit_functional_role",
                f"{path}.functional_role",
                f"Functional role must be one of: {', '.join(sorted(MICROCOPY_FUNCTIONAL_ROLES))}.",
            )
        provenance_valid = _validate_message_unit_provenance(unit, path, spec, role, report, provenance_authority) if role is not None or "provenance" in unit else True
        role_evidence_valid = True
        if role in {"label", "navigation", "accessibility", "branding"}:
            role_evidence_valid = _message_unit_role_evidence(path, unit, role, spec, provenance_authority)
            if not role_evidence_valid:
                report.error(
                    "message_unit_role_evidence",
                    f"{path}.functional_role",
                    "Role-specific evidence must resolve to a content target or an approved brand asset; a self-attested ID is not sufficient.",
                )
        role_is_justified = role in MICROCOPY_FUNCTIONAL_ROLES and bool(justification) and provenance_valid and role_evidence_valid
        if role == "action" and not _message_unit_action_allowed(path, text):
            report.error(
                "message_unit_action_semantics",
                f"{path}.functional_role",
                "An action role is valid only for an actual CTA/action surface with action-shaped copy; it cannot bypass a repeated or generic header check.",
            )
            role_is_justified = False
        if role is not None and role in MICROCOPY_FUNCTIONAL_ROLES and not justification:
            report.error(
                "message_unit_role_justification",
                f"{path}.role_justification",
                "A functional role needs a concrete justification explaining the information, action, accessibility, or navigation job.",
            )
        if role in {"source", "legal", "accessibility", "navigation", "label", "branding", "annotation"} and not provenance_valid:
            report.error(
                "message_unit_provenance",
                f"{path}.provenance",
                "Source/legal/accessibility/navigation/label/branding/annotation text needs provenance that resolves to an approved source, claim, policy, or brand record.",
            )
        if production and not (has_job or role_is_justified):
            report.error(
                "message_unit_information_job_missing",
                f"{path}.information_job",
                "Every visible production text element needs a distinct information_job or a justified functional_role; decorative text cannot occupy space without a job.",
            )
        elif not (has_job or role_is_justified):
            report.warning(
                "message_unit_information_job_missing",
                f"{path}.information_job",
                "Record the information_job or a justified functional_role before Canva production; visible decorative text is not a content job.",
            )
        obviously_decorative = _message_unit_is_obviously_decorative(text)
        if obviously_decorative and (
            not _message_unit_decorative_role_allowed(text, role, role_is_justified)
            or (role in {"label", "navigation", "accessibility", "branding"} and not _message_unit_role_evidence(path, unit, role, spec, provenance_authority))
        ):
            severity = report.error if production else report.warning
            severity(
                "REDUNDANT_DECORATIVE_MICROCOPY",
                path,
                "This small text matches a page-count, arrow, filler, or fake-annotation pattern but records no distinct information, action, accessibility, or navigation job.",
            )
        if obviously_decorative and job and not has_job and not role_is_justified:
            severity = report.error if production else report.warning
            severity(
                "REDUNDANT_DECORATIVE_MICROCOPY",
                path,
                "The recorded job is decorative or merely repeats the text; replace it with a distinct job or remove the text.",
            )
        if not obviously_decorative:
            normalized_visible.setdefault(re.sub(r"\s+", " ", text.casefold().strip()), []).append((path, unit))

    # Repeated theme headers are only a finding when no unit has a distinct job
    # or a justified functional role.  Repeated CTAs, source labels, legal
    # notices, and navigation metadata therefore remain valid by contract.
    for text, matches in normalized_visible.items():
        if len(matches) < 2:
            continue
        jobs = {
            re.sub(r"\s+", " ", (_message_unit_information_job(unit) or "").casefold().strip())
            for _, unit in matches
        }
        cta_repeat = (
            all(path.endswith(".cta") and _message_unit_action_allowed(path, _message_unit_text(unit)) for path, unit in matches)
            and len(jobs - {""}) == len(matches)
        )
        role_repeat = all(
            (_message_unit_role(unit) == "action" and _message_unit_action_allowed(path, _message_unit_text(unit)))
            or (_message_unit_role(unit) in {"source", "legal", "accessibility", "navigation", "label", "branding"}
                and _message_unit_role_justification(unit)
                and _validate_message_unit_provenance(unit, path, spec, _message_unit_role(unit), report, provenance_authority)
                and _message_unit_role_evidence(path, unit, _message_unit_role(unit), spec, provenance_authority)
            )
            for path, unit in matches
        )
        if cta_repeat or role_repeat:
            continue
        for path, unit in matches:
            severity = report.error if production else report.warning
            severity(
                "REDUNDANT_DECORATIVE_MICROCOPY",
                path,
                "This visible label repeats a theme header without a distinct information job; remove it or document its functional role and provenance.",
            )

    if not explicit:
        implicit_visible: dict[str, list[dict[str, Any]]] = {}
        for unit in _implicit_message_units(spec):
            text = unit["text"]
            if _message_unit_is_obviously_decorative(text):
                severity = report.error if production else report.warning
                severity(
                    "REDUNDANT_DECORATIVE_MICROCOPY",
                    unit["path"],
                    "Visible microcopy matches a decorative page-count, arrow, filler, or fake-annotation pattern but has no declared information_job or functional role.",
                )
            implicit_visible.setdefault(re.sub(r"\s+", " ", text.casefold().strip()), []).append(unit)
        for text, matches in implicit_visible.items():
            if len(matches) < 2:
                continue
            # Existing slide-level information_job is not enough to justify a
            # repeated theme header: the header itself needs a job or role.
            if any(_message_unit_is_obviously_decorative(unit["text"]) for unit in matches):
                continue
            if all(
                unit.get("functional_role") == "action"
                and _message_unit_action_allowed(unit["path"], unit["text"])
                for unit in matches
            ):
                continue
            severity = report.error if production else report.warning
            for unit in matches:
                severity(
                    "REDUNDANT_DECORATIVE_MICROCOPY",
                    unit["path"],
                    "Visible text repeats across message units without a field-level job or functional role; it appears to be a decorative theme header.",
                )


def _declared_extra_message_units(spec: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return manifest text not already represented by canonical copy fields."""

    known_paths = {unit["path"] for unit in _implicit_message_units(spec)}
    extras: list[tuple[str, dict[str, Any]]] = []
    declared, _ = _declared_message_units(spec)
    for container_path, unit in declared:
        if "_invalid" in unit:
            continue
        path = _message_unit_path(unit, container_path)
        if path in known_paths:
            continue
        text = _message_unit_text(unit)
        if text.strip() and unit.get("visible", True) is not False:
            extras.append((path, unit))
    return extras


def _message_manifest_for_checksum(spec: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Canonicalize accepted units; return None to preserve legacy hashes."""

    declared, explicit = _declared_message_units(spec)
    if not explicit:
        return None
    return [
        {"container_path": container_path, "path": _message_unit_path(unit, container_path), "unit": unit}
        for container_path, unit in declared
    ]


def _all_content_text(spec: dict[str, Any]) -> str:
    chunks = [str(spec.get("single_message", ""))]
    for slide in spec.get("slides", []) if isinstance(spec.get("slides"), list) else []:
        if isinstance(slide, dict):
            chunks.extend(str(slide.get(key, "")) for key in ("headline", "body", "cta"))
    caption = spec.get("caption")
    if isinstance(caption, dict):
        chunks.extend(str(caption.get(key, "")) for key in ("hook", "body", "cta"))
    chunks.extend(_message_unit_text(unit) for _, unit in _declared_extra_message_units(spec))
    return "\n".join(chunks)


def _indonesian_text_units(spec: dict[str, Any]) -> list[tuple[str, str]]:
    """Return copy-bearing fields with stable JSON paths for evidence spans."""

    units: list[tuple[str, str]] = []
    if _nonempty_string(spec.get("single_message")):
        units.append(("$.single_message", str(spec["single_message"])))
    slides = spec.get("slides")
    if isinstance(slides, list):
        for index, slide in enumerate(slides):
            if not isinstance(slide, dict):
                continue
            for key in ("headline", "body", "cta"):
                value = slide.get(key)
                if _nonempty_string(value):
                    units.append((f"$.slides[{index}].{key}", value))
    caption = spec.get("caption")
    if isinstance(caption, dict):
        for key in ("hook", "body", "cta"):
            value = caption.get(key)
            if _nonempty_string(value):
                units.append((f"$.caption.{key}", value))
    units.extend((_message_unit_path(unit, path), _message_unit_text(unit)) for path, unit in _declared_extra_message_units(spec))
    return units


def _indonesian_words(text: str) -> list[re.Match[str]]:
    return list(re.finditer(r"[\wÀ-ÿ]+(?:[-'][\wÀ-ÿ]+)?", text, flags=re.UNICODE))


def _looks_like_indonesian(text: str) -> bool:
    words = {match.group(0).casefold() for match in _indonesian_words(text)}
    signals = {
        "yang", "dan", "dengan", "untuk", "ini", "itu", "kami", "kita", "anda", "kamu",
        "bisa", "dapat", "sebelum", "setelah", "mulai", "cek", "simpan", "pilih", "buka",
        "tutup", "layanan", "pengguna", "pelanggan", "sudah", "akan", "dari", "pada",
    }
    return bool(words & signals)


def _id_style_profile(spec: dict[str, Any]) -> dict[str, Any] | None:
    profile = spec.get("id_style_profile")
    if profile is None and isinstance(spec.get("locale_policy"), dict):
        profile = spec["locale_policy"].get("id_style_profile")
    return profile if isinstance(profile, dict) else None


def _id_register(profile: dict[str, Any] | None) -> str | None:
    if not isinstance(profile, dict):
        return None
    value = profile.get("register", profile.get("mode"))
    return value if isinstance(value, str) else None


def _id_profile_digest(profile: dict[str, Any]) -> str:
    encoded = json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _id_profile_source_ids(profile: dict[str, Any]) -> list[str]:
    values = profile.get("source_ids", profile.get("evidence_ids"))
    if isinstance(values, list):
        return [value for value in values if isinstance(value, str) and value.strip()]
    if isinstance(values, str) and values.strip():
        return [values]
    evidence = profile.get("evidence")
    if isinstance(evidence, dict):
        values = evidence.get("source_ids", evidence.get("ids"))
        if isinstance(values, list):
            return [value for value in values if isinstance(value, str) and value.strip()]
    return []


def _id_resolved_style_source_ids(spec: dict[str, Any], expected_scope: dict[str, str] | None) -> set[str]:
    """Resolve only scoped packet evidence explicitly tagged for style/register."""

    packet = spec.get("source_packet")
    if not isinstance(packet, dict):
        return set()
    expected = _scope_with_brand(expected_scope)
    records: list[Any] = []
    for key in ("evidence", "style_evidence", "provenance", "sources"):
        value = packet.get(key)
        if isinstance(value, list):
            records.extend(value)
    resolved: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        source_id = record.get("source_id", record.get("id", record.get("evidence_id")))
        if not isinstance(source_id, str) or not source_id.strip():
            continue
        tags = record.get("tags", record.get("evidence_tags", record.get("labels", [])))
        if isinstance(tags, str):
            tags = [tags]
        tag_text = {str(tag).casefold() for tag in tags} if isinstance(tags, list) else set()
        kind = str(record.get("kind", record.get("type", record.get("evidence_type", "")))).casefold()
        if not any(any(marker in tag for marker in ("style", "register", "locale", "linguistic", "copy_review")) for tag in tag_text) and not any(marker in kind for marker in ("style", "register", "locale", "linguistic")):
            continue
        record_scope = record.get("scope", packet.get("scope"))
        if expected is not None and record_scope != expected:
            continue
        resolved.add(source_id)
    return resolved


def _id_authoritative_profile(brand: Any, brand_bundle: dict[str, Any] | None) -> dict[str, Any] | None:
    for candidate in (
        brand_bundle.get("profile") if isinstance(brand_bundle, dict) else None,
        brand if isinstance(brand, dict) else None,
    ):
        if not isinstance(candidate, dict):
            continue
        profile = candidate.get("id_style_profile")
        if profile is None and isinstance(candidate.get("locale_policy"), dict):
            profile = candidate["locale_policy"].get("id_style_profile")
        if isinstance(profile, dict):
            return profile
    return None


def _id_is_colloquial_output(text: str, profile: dict[str, Any] | None = None) -> bool:
    words = {match.group(0).casefold() for match in _indonesian_words(text)}
    return bool(words & INDONESIAN_COLLOQUIAL_MARKERS) or _id_register(profile) in INDONESIAN_COLLOQUIAL_REGISTERS


def _id_is_derivational_nominal(token: str) -> bool:
    """Recognize productive nominal patterns without treating every -nya as a noun."""

    normalized = token.casefold()
    if normalized in INDONESIAN_ABSTRACT_NOUNS:
        return True
    # Lexicalized abstract heads are explicit above.  For productive forms,
    # require a nominal prefix and an -an ending; pelanggan, teman, langkahnya,
    # and sumbernya consequently remain ordinary words.
    return bool(re.fullmatch(r"(?:peng|pen|pem|peny|per|ke)[a-z]{3,}an", normalized))


def _id_policy_terms(policy: Any) -> set[str]:
    """Extract only explicitly approved terms; never infer a Jakarta default."""

    if isinstance(policy, dict):
        candidates: Any = policy.get("allowed_terms", policy.get("allowed_forms", policy.get("allowed")))
        if candidates is None:
            candidates = policy.get("approved_terms", policy.get("approved"))
        if isinstance(candidates, dict):
            return {str(key).casefold() for key in candidates}
        if isinstance(candidates, list):
            terms: set[str] = set()
            for item in candidates:
                if isinstance(item, str):
                    terms.add(item.casefold())
                elif isinstance(item, dict) and isinstance(item.get("term"), str):
                    terms.add(item["term"].casefold())
            return terms
        # A map such as {"tab": {"reason": "UI label"}} is also useful.
        return {str(key).casefold() for key in policy if isinstance(key, str) and key not in {"reason", "source", "examples"}}
    if isinstance(policy, list):
        return {str(item).casefold() for item in policy if isinstance(item, str)}
    return set()


def _id_particle_entries(profile: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(profile, dict):
        return {}
    policy = profile.get("particle_policy", profile.get("particles"))
    if not isinstance(policy, dict):
        return {}
    raw = policy.get("allowed", policy.get("approved", policy.get("forms")))
    if raw is None:
        raw = policy
    entries: dict[str, Any] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(key, str) and key.casefold() in INDONESIAN_PARTICLES:
                entries[key.casefold()] = value
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                entries[item.casefold()] = {}
            elif isinstance(item, dict):
                form = item.get("form", item.get("particle"))
                if isinstance(form, str):
                    entries[form.casefold()] = item
    return entries


def _id_span(path: str, text: str, start: int, end: int) -> dict[str, Any]:
    bounded_start = max(0, min(start, len(text)))
    bounded_end = max(bounded_start, min(end, len(text)))
    return {"path": path, "text": text[bounded_start:bounded_end], "start": bounded_start, "end": bounded_end}


def _id_warn_span(
    report: Report,
    code: str,
    path: str,
    message: str,
    text: str,
    start: int,
    end: int,
) -> None:
    span = _id_span(path, text, start, end)
    report.warning(code, path, f"{message} Evidence span: {span['text']!r}.", span)


def _validate_id_style_profile(spec: dict[str, Any], text: str, report: Report) -> dict[str, Any] | None:
    """Validate the context that licenses colloquial/community Indonesian."""

    profile = _id_style_profile(spec)
    words = {match.group(0).casefold() for match in _indonesian_words(text)}
    colloquial_output = bool(words & INDONESIAN_COLLOQUIAL_MARKERS)
    if profile is None:
        if colloquial_output:
            report.error(
                "id_style_profile_required",
                "$.id_style_profile",
                "Colloquial or community Indonesian requires an explicit id_style_profile; use neutral editorial Indonesian when no audience/register evidence is available.",
            )
        return None
    if not isinstance(spec.get("id_style_profile"), dict) and isinstance(spec.get("locale_policy"), dict) and isinstance(spec["locale_policy"].get("id_style_profile"), dict):
        profile_path = "$.locale_policy.id_style_profile"
    else:
        profile_path = "$.id_style_profile"
    register = _id_register(profile)
    if register not in INDONESIAN_REGISTERS:
        report.error("id_style_profile_register", f"{profile_path}.register", "register must be an explicit supported Indonesian register.")
        register = None
    if register in INDONESIAN_COLLOQUIAL_REGISTERS or colloquial_output:
        required_fields = ("channel", "audience_relation", "region_or_community", "pronoun_policy", "particle_policy", "code_switch_policy")
        for key in required_fields:
            value = profile.get(key)
            valid = _nonempty_string(value) if key in {"channel", "audience_relation", "region_or_community"} else isinstance(value, (dict, list))
            if not valid:
                report.error("id_style_profile_field", f"{profile_path}.{key}", "Colloquial/community output requires this register policy field; do not infer slang, region, or particles.")
        region = profile.get("region_or_community")
        if isinstance(region, str) and region.casefold() in {"default", "unspecified", "any", "jakarta default"}:
            report.error("id_style_profile_region", f"{profile_path}.region_or_community", "Region/community must be explicit; Jakarta is not a national default.")
    return profile


def _validate_id_profile_authority(
    spec: dict[str, Any],
    text: str,
    profile: dict[str, Any] | None,
    brand: Any,
    brand_bundle: dict[str, Any] | None,
    expected_scope: dict[str, str] | None,
    report: Report,
) -> None:
    """Bind embedded register choices to external Brand Copy evidence when available."""

    if profile is None:
        return
    authoritative = _id_authoritative_profile(brand, brand_bundle)
    profile_path = "$.id_style_profile" if isinstance(spec.get("id_style_profile"), dict) else "$.locale_policy.id_style_profile"
    if authoritative is not None:
        if profile != authoritative:
            report.error(
                "id_style_profile_authority",
                profile_path,
                "When a canonical Brand Copy profile or validated bundle supplies id_style_profile, content must use that exact external profile.",
            )
        return
    production = _anti_slop_route_required(spec, spec.get("state"))
    if _id_is_colloquial_output(text, profile):
        if not _id_profile_source_ids(profile):
            report.error(
                "id_style_profile_evidence",
                profile_path,
                "Embedded colloquial/community id_style_profile needs non-empty source_ids/evidence_ids; a content record cannot self-attest a voice or community.",
            )
        elif production:
            source_ids = set(_id_profile_source_ids(profile))
            resolved_ids = _id_resolved_style_source_ids(spec, expected_scope)
            missing = sorted(source_ids - resolved_ids)
            if missing:
                report.error(
                    "id_style_profile_source_unresolved",
                    profile_path,
                    f"Embedded style/register source_ids must resolve to scoped packet evidence explicitly tagged style/register; unresolved: {missing}.",
                )
        code_switch_policy = profile.get("code_switch_policy")
        if not isinstance(code_switch_policy, (dict, list)):
            report.error("id_style_profile_field", f"{profile_path}.code_switch_policy", "Colloquial/community code-switch policy must be structured and evidence-backed.")
        particle_policy = profile.get("particle_policy")
        if not isinstance(particle_policy, (dict, list)):
            report.error("id_style_profile_field", f"{profile_path}.particle_policy", "Colloquial/community particle policy must be structured and evidence-backed.")
        if production:
            words = {match.group(0).casefold() for match in _indonesian_words(text)}
            particle_entries = _id_particle_entries(profile)
            if words & INDONESIAN_PARTICLES and not particle_entries:
                report.error("id_style_profile_particle_authority", f"{profile_path}.particle_policy", "Colloquial/community particles require approved provenance/function entries before production.")
            code_switch_terms = _id_policy_terms(code_switch_policy)
            if any(re.search(re.escape(phrase), text, flags=re.IGNORECASE) for phrase in INDONESIAN_CODE_SWITCH_PHRASES) and not code_switch_terms:
                report.error("id_style_profile_code_switch_authority", f"{profile_path}.code_switch_policy", "English/UI terms in colloquial/community production require approved code-switch terms and reasons.")
    scope = profile.get("scope")
    if scope is not None:
        expected = _scope_with_brand(expected_scope)
        if expected is None or scope != expected:
            report.error("id_style_profile_scope", f"{profile_path}.scope", "Embedded id_style_profile scope must exactly match the content isolation scope.")


def _validate_id_orthography_review(spec: dict[str, Any], report: Report) -> None:
    """Validate optional EYD V evidence independently from naturalness findings."""

    review = spec.get("eyd_review", spec.get("ey_d_review"))
    if review is None and isinstance(spec.get("copy_quality_audit"), dict):
        review = spec["copy_quality_audit"].get("eyd_review", spec["copy_quality_audit"].get("ey_d_review"))
    if review is None:
        return
    path = "$.eyd_review" if spec.get("eyd_review") is not None else "$.ey_d_review"
    if not isinstance(review, dict):
        report.error("id_eyd_review_type", path, "EYD review must be a structured object and is independent from register naturalness.")
        return
    if review.get("status") not in {"pending", "pass", "fail", "not_applicable"}:
        report.error("id_eyd_review_status", f"{path}.status", "EYD review status must be pending, pass, fail, or not_applicable.")
    if review.get("standard", "EYD V") != "EYD V":
        report.error("id_eyd_review_standard", f"{path}.standard", "Orthography evidence must name EYD V; it must not be used as a naturalness score.")
    findings = review.get("findings", [])
    if not isinstance(findings, list):
        report.error("id_eyd_review_findings", f"{path}.findings", "EYD findings must be a list.")


def _visible_copy_digest(spec: dict[str, Any]) -> str:
    slides = []
    for slide in spec.get("slides", []) if isinstance(spec.get("slides"), list) else []:
        if isinstance(slide, dict):
            slides.append({key: slide.get(key) for key in ("headline", "body", "cta")})
    payload = {
        "single_message": spec.get("single_message"),
        "slides": slides,
        "caption": spec.get("caption"),
    }
    _, explicit = _declared_message_units(spec)
    if explicit:
        payload["extra_message_units"] = [
            {"path": path, "text": _message_unit_text(unit)}
            for path, unit in _declared_extra_message_units(spec)
        ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate_id_production_review(
    spec: dict[str, Any],
    audit: dict[str, Any],
    profile: dict[str, Any] | None,
    expected_scope: dict[str, str] | None,
    policy: dict[str, Any] | None,
    actor_id: str | None,
    report: Report,
) -> None:
    review = audit.get("indonesian_review", audit.get("id_review", audit.get("locale_review")))
    if not isinstance(review, dict):
        report.error(
            "id_copy_review_required",
            "$.copy_quality_audit.indonesian_review",
            "Production copy audit must record a native/pairwise review or an explicit neutral-editorial fallback.",
        )
        return
    method = review.get("method", review.get("mode"))
    if method not in ID_REVIEW_METHODS:
        report.error("id_copy_review_method", "$.copy_quality_audit.indonesian_review.method", "Use a native editor, pairwise native review, or neutral_editorial_fallback.")
    if review.get("status") not in {"pass", "accepted", "fallback"}:
        report.error("id_copy_review_status", "$.copy_quality_audit.indonesian_review.status", "Indonesian copy review must record pass/accepted or fallback status.")
    expected_full_scope = _scope_with_brand(expected_scope)
    if expected_full_scope is None or review.get("scope") != expected_full_scope:
        report.error("id_copy_review_scope", "$.copy_quality_audit.indonesian_review.scope", "Review evidence must carry the exact tenant/client/product/brand scope.")
    expected_digest = _visible_copy_digest(spec)
    if review.get("reviewed_copy_digest") != expected_digest:
        report.error("id_copy_review_copy_digest", "$.copy_quality_audit.indonesian_review.reviewed_copy_digest", "Review must bind the exact visible-copy digest.")
    if _parse_datetime(review.get("reviewed_at")) is None:
        report.error("id_copy_review_timestamp", "$.copy_quality_audit.indonesian_review.reviewed_at", "Review evidence requires a timezone-aware reviewed_at timestamp.")
    if method in {"neutral_editorial_fallback", "neutral-editorial-fallback"}:
        if _id_register(profile) != "neutral_editorial":
            report.error("id_copy_review_fallback_register", "$.copy_quality_audit.indonesian_review.method", "Neutral-editorial fallback is allowed only with id_style_profile.register neutral_editorial; it cannot authorize colloquial/community output.")
        if not isinstance(profile, dict):
            report.error("id_copy_review_fallback_profile", "$.id_style_profile", "Neutral-editorial fallback requires an explicit scoped id_style_profile.")
        else:
            if review.get("profile_checksum") != _id_profile_digest(profile):
                report.error("id_copy_review_profile_checksum", "$.copy_quality_audit.indonesian_review.profile_checksum", "Fallback must bind the exact id_style_profile checksum.")
            if profile.get("scope") != expected_full_scope:
                report.error("id_style_profile_scope", "$.id_style_profile.scope", "Neutral fallback profile must carry the exact content scope.")
        if not _nonempty_string(review.get("reason", review.get("rationale"))):
            report.error("id_copy_review_fallback_reason", "$.copy_quality_audit.indonesian_review.reason", "Neutral-editorial fallback must state why native/pairwise review was unavailable.")
        return
    reviewer_id = review.get("reviewer_id")
    reviewer_role = review.get("reviewer_role", "reviewer")
    trusted = policy.get("raw", {}) if isinstance(policy, dict) else {}
    if not _nonempty_string(reviewer_id) or reviewer_id != actor_id:
        report.error("id_copy_review_reviewer", "$.copy_quality_audit.indonesian_review.reviewer_id", "Native/pairwise review must bind the current authenticated reviewer identity.")
    if reviewer_role not in {"reviewer", "lead"} or not _mapped_identity(trusted, reviewer_id, reviewer_role):
        report.error("id_copy_review_reviewer_role", "$.copy_quality_audit.indonesian_review.reviewer_role", "Native/pairwise reviewer must be explicitly mapped in authenticated local policy.")


def _validate_indonesian_fluency(
    spec: dict[str, Any],
    report: Report,
    *,
    brand: Any = None,
    brand_bundle: dict[str, Any] | None = None,
    expected_scope: dict[str, str] | None = None,
) -> None:
    """Warn on explainable register/translation residue while preserving ellipsis."""

    units = _indonesian_text_units(spec)
    text = "\n".join(value for _, value in units)
    if not text or not _looks_like_indonesian(text):
        _validate_id_orthography_review(spec, report)
        return
    profile = _validate_id_style_profile(spec, text, report)
    _validate_id_profile_authority(spec, text, profile, brand, brand_bundle, expected_scope, report)
    _validate_id_orthography_review(spec, report)

    particle_entries = _id_particle_entries(profile)
    code_switch_policy = profile.get("code_switch_policy") if isinstance(profile, dict) else None
    allowed_code_switches = _id_policy_terms(code_switch_policy)
    transitions_declared = bool(isinstance(profile, dict) and (profile.get("allow_register_transitions") is True or profile.get("register_boundaries")))

    for path, value in units:
        lower = value.casefold()
        matches = _indonesian_words(value)

        # Particles are only useful when their speech act/relationship has
        # provenance.  A profile may explicitly allow no particles.
        for match in matches:
            token = match.group(0).casefold()
            if token not in INDONESIAN_PARTICLES:
                continue
            if profile is None:
                continue
            entry = particle_entries.get(token)
            valid_entry = isinstance(entry, dict) and _nonempty_string(entry.get("function")) and (
                _nonempty_string(entry.get("speech_act")) or _nonempty_string(entry.get("stance"))
            ) and isinstance(entry.get("approved_examples", entry.get("examples")), list) and bool(entry.get("approved_examples", entry.get("examples")))
            if not valid_entry:
                _id_warn_span(
                    report,
                    "id_particle_without_provenance",
                    path,
                    "Conversational particle needs an approved function, speech act/stance, and human example; the validator does not add particles automatically.",
                    value,
                    match.start(),
                    match.end(),
                )

        # English UI/product terms can be approved, but clauses and calques
        # need an explicit reason rather than a generic "modern" voice.
        for phrase in INDONESIAN_CODE_SWITCH_PHRASES:
            for match in re.finditer(re.escape(phrase), lower):
                phrase_terms = set(phrase.split())
                if phrase.casefold() in allowed_code_switches or phrase_terms <= allowed_code_switches:
                    continue
                _id_warn_span(
                    report,
                    "id_unexplained_code_switch",
                    path,
                    "Code-switching is not tied to an approved product, interface, or community term.",
                    value,
                    match.start(),
                    match.end(),
                )
        for pattern in (
            r"\b(?:nikmati|menghadirkan|mendukung|meningkatkan|memberikan)\s+(?:pengalaman|kenyamanan|kemudahan|solusi)\b",
            r"\b(?:dalam rangka|untuk dapat|pada akhirnya)\b",
        ):
            for match in re.finditer(pattern, lower):
                if match.group(0).casefold() in allowed_code_switches:
                    continue
                _id_warn_span(
                    report,
                    "id_calque_or_translation_residue",
                    path,
                    "This collocation may preserve translated/abstract packaging; review it against a genre-matched Indonesian example.",
                    value,
                    match.start(),
                    match.end(),
                )

        # A register jump in one copy block is a warning, not a ban.  Formal
        # terms and a colloquial CTA may be intentional when the block boundary
        # and reason are recorded in id_style_profile.
        formal_matches = [match for match in matches if match.group(0).casefold() in INDONESIAN_FORMAL_MARKERS]
        colloquial_matches = [match for match in matches if match.group(0).casefold() in INDONESIAN_COLLOQUIAL_MARKERS]
        if formal_matches and colloquial_matches and not transitions_declared:
            start = min(formal_matches[0].start(), colloquial_matches[0].start())
            end = max(formal_matches[0].end(), colloquial_matches[0].end())
            _id_warn_span(
                report,
                "id_register_jump",
                path,
                "Formal and colloquial markers share a copy block without a recorded register boundary or purpose.",
                value,
                start,
                end,
            )

        # Split on sentence punctuation, while leaving fragments and ellipses
        # alone.  No missing-subject warning is emitted: recoverable Indonesian
        # zero arguments and headline fragments are valid editorial choices.
        sentence_matches = list(re.finditer(r"[^.!?…]+(?:[.!?…]+|$)", value))
        subject_occurrences: dict[str, list[tuple[re.Match[str], int]]] = {}
        frame_occurrences: dict[str, list[tuple[re.Match[str], int]]] = {}
        for sentence in sentence_matches:
            sentence_text = sentence.group(0)
            stripped = sentence_text.lstrip()
            offset = sentence.start() + (len(sentence_text) - len(stripped))
            if not stripped.strip():
                continue
            subject = re.match(
                r"(?P<subject>kami|kita|anda|kamu|gue|gua|lu|lo|produk(?:\s+ini)?|layanan(?:\s+ini)?|tim(?:\s+kami)?|pengguna|pelanggan)\b",
                stripped,
                flags=re.IGNORECASE,
            )
            if subject:
                subject_key = re.sub(r"\s+", " ", subject.group("subject").casefold())
                subject_occurrences.setdefault(subject_key, []).append((subject, offset))
                after_subject = stripped[subject.end():].lstrip()
                aux = re.match(r"(dapat|bisa|akan|sudah|telah|perlu|harus|boleh)\b", after_subject, flags=re.IGNORECASE)
                if aux:
                    frame = f"{subject_key} {aux.group(1).casefold()}"
                    frame_occurrences.setdefault(frame, []).append((subject, offset))
        for subject, occurrences in subject_occurrences.items():
            if len(occurrences) < 2:
                continue
            for occurrence, occurrence_offset in occurrences[1:]:
                start = occurrence_offset + occurrence.start()
                _id_warn_span(
                    report,
                    "id_explicit_subject_repeat",
                    path,
                    f"Explicit subject {subject!r} repeats across clauses; review whether the referent is already recoverable or whether a contrast requires it.",
                    value,
                    start,
                    min(len(value), start + len(occurrence.group(0))),
                )
        for frame, occurrences in frame_occurrences.items():
            if len(occurrences) < 3:
                continue
            occurrence, occurrence_offset = occurrences[-1]
            start = occurrence_offset + occurrence.start()
            _id_warn_span(
                report,
                "id_identical_sentence_frame",
                path,
                f"Sentence frame {frame!r} repeats rigidly; vary the information job only when the brief supports it.",
                value,
                start,
                min(len(value), start + len(frame)),
            )

        # Abstract nominalization is only a warning when the sentence lacks a
        # concrete actor/action/object.  Legitimate technical terms and a
        # scene-led sentence therefore remain untouched.
        for sentence in sentence_matches:
            sentence_text = sentence.group(0)
            lower_sentence = sentence_text.casefold()
            abstract_matches = [
                match for match in re.finditer(r"[\w-]+", lower_sentence)
                if _id_is_derivational_nominal(match.group(0)) and match.group(0) not in INDONESIAN_CONCRETE_WORDS
            ]
            if len(abstract_matches) < 2:
                continue
            words_in_sentence = {match.group(0) for match in re.finditer(r"[\w-]+", lower_sentence)}
            has_concrete_object = bool(words_in_sentence & INDONESIAN_CONCRETE_WORDS)
            has_action = bool(words_in_sentence & INDONESIAN_ACTION_VERBS)
            has_non_generic_verb = any(
                word.startswith(("me", "ber", "di", "ter", "mem", "men", "meng", "meny")) and word not in INDONESIAN_GENERIC_VERBS
                for word in words_in_sentence
            )
            if has_concrete_object or (has_action and has_non_generic_verb):
                continue
            _id_warn_span(
                report,
                "id_abstract_nominalization_cluster",
                path,
                "Abstract nominalizations cluster without a concrete actor, action, or object; add an observable scene or retain the formal wording only with editorial intent.",
                value,
                sentence.start(),
                sentence.end(),
            )


def _scan_for_secrets(value: Any, report: Report, path: str = "$") -> None:
    if isinstance(value, str) and re.search(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", value, re.IGNORECASE):
        report.error("secret_value", path, "A bearer-token-like value is forbidden in content records; value redacted.")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).casefold() in SECRET_KEYS:
                report.error("secret_field", child_path, "Credential-like fields are forbidden in content records.")
            _scan_for_secrets(child, report, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_for_secrets(child, report, f"{path}[{index}]")


def _scan_for_universal_detector_fields(value: Any, report: Report, path: str = "$") -> None:
    """Reject authorship/detector scores; retain explainable editorial findings."""

    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if isinstance(key, str) and UNIVERSAL_DETECTOR_KEY_RE.search(key):
                report.error(
                    "universal_detector_field",
                    child_path,
                    "Do not store AI/authorship detector probabilities or scores; record an explainable finding instead.",
                )
            _scan_for_universal_detector_fields(child, report, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_for_universal_detector_fields(child, report, f"{path}[{index}]")


def _anti_scope(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return value


def _validate_anti_scope(
    value: Any,
    path: str,
    expected_scope: dict[str, str] | None,
    report: Report,
    *,
    required: bool,
) -> None:
    if value is None:
        if required:
            report.error("anti_slop_scope_missing", path, "Anti-slop evidence must carry the complete tenant/client/product/brand scope.")
        return
    if not isinstance(value, dict):
        report.error("anti_slop_scope_type", path, "Anti-slop scope must be an object.")
        return
    expected = _scope_with_brand(expected_scope)
    if expected is None or value != expected:
        if required:
            report.error("anti_slop_scope_mismatch", path, "Anti-slop evidence scope must exactly match the active content scope.")
        else:
            report.warning("anti_slop_scope_pending", path, "Draft anti-slop evidence has a scope mismatch and cannot authorize a remote or final state.")


def _validate_source_packet_and_brief(
    spec: dict[str, Any],
    expected_scope: dict[str, str] | None,
    state: Any,
    report: Report,
) -> None:
    """Validate scoped evidence and the brief tension before concept routes."""

    remote_or_final = _anti_slop_route_required(spec, state)
    packet = spec.get("source_packet")
    brief = spec.get("creative_brief")
    if packet is None and not remote_or_final:
        return
    if not isinstance(packet, dict):
        report.error("source_packet_required", "$.source_packet", "Canva mutation/final states require a scoped source_packet.")
    else:
        _validate_anti_scope(packet.get("scope"), "$.source_packet.scope", expected_scope, report, required=remote_or_final)
        for key in ("objective", "audience_situation", "observation"):
            if not _nonempty_string(packet.get(key)):
                report.error("source_packet_field", f"$.source_packet.{key}", "Source packet requires objective, audience situation, and a concrete observation.")
        proof_ids = packet.get("proof_ids", [])
        if not isinstance(proof_ids, list) or any(not _safe_registry_id(item) for item in proof_ids):
            report.error("source_packet_proof_ids", "$.source_packet.proof_ids", "proof_ids must be a list of scoped lowercase registry IDs.")
        elif remote_or_final and not proof_ids:
            report.error("source_packet_proof_ids", "$.source_packet.proof_ids", "Final states require at least one resolved proof ID.")
        sources = packet.get("sources", packet.get("source_urls"))
        if sources is not None and not isinstance(sources, list):
            report.error("source_packet_sources", "$.source_packet.sources", "Source packet sources must be a list.")
        elif isinstance(sources, list):
            if remote_or_final and not sources:
                report.error("source_packet_sources", "$.source_packet.sources", "Final states require non-empty source locators.")
            for index, source in enumerate(sources):
                if isinstance(source, str):
                    if not _valid_https_url(source):
                        report.error("source_packet_source", f"$.source_packet.sources[{index}]", "Source packet URLs must be HTTPS.")
                elif not isinstance(source, dict) or not (_nonempty_string(source.get("source_id")) or _valid_https_url(source.get("url"))):
                    report.error("source_packet_source", f"$.source_packet.sources[{index}]", "Each source needs a source_id or HTTPS url.")
        retrieved_at = packet.get("retrieved_at")
        if remote_or_final and _parse_datetime(retrieved_at) is None:
            report.error("source_packet_retrieved_at", "$.source_packet.retrieved_at", "Source packet retrieved_at must be timezone-aware ISO 8601.")
        fingerprints = packet.get("recent_fingerprints", packet.get("recent_fingerprint"))
        if fingerprints is None:
            fingerprints = spec.get("recent_fingerprints", spec.get("recent_fingerprint"))
        if fingerprints is not None:
            _validate_recent_fingerprints(fingerprints, "$.source_packet.recent_fingerprints", expected_scope, report, required=remote_or_final)
        elif remote_or_final:
            report.error("recent_fingerprints_missing", "$.source_packet.recent_fingerprints", "Canva mutation/final states require recent scoped fingerprints and similarity metadata.")

    if brief is None and not remote_or_final:
        return
    if not isinstance(brief, dict):
        report.error("creative_brief_required", "$.creative_brief", "Canva mutation/final states require a creative brief with audience tension.")
        return
    for key in ("audience_situation", "tension", "takeaway", "point_of_view", "desired_action"):
        if not _nonempty_string(brief.get(key)):
            report.error("creative_brief_field", f"$.creative_brief.{key}", "Creative brief requires a specific tension, takeaway, point of view, and action.")
    proof_ids = brief.get("proof_ids", [])
    if not isinstance(proof_ids, list) or any(not _safe_registry_id(item) for item in proof_ids):
        report.error("creative_brief_proof_ids", "$.creative_brief.proof_ids", "Creative brief proof_ids must be a list of scoped lowercase registry IDs.")
    if isinstance(packet, dict) and isinstance(packet.get("scope"), dict) and brief.get("scope") is not None:
        _validate_anti_scope(brief.get("scope"), "$.creative_brief.scope", expected_scope, report, required=remote_or_final)


def _validate_copy_first_gate(
    spec: dict[str, Any],
    state: Any,
    report: Report,
    *,
    brand: Any = None,
    brand_bundle: dict[str, Any] | None = None,
    expected_scope: dict[str, str] | None = None,
    policy: dict[str, Any] | None = None,
    actor_id: str | None = None,
) -> None:
    """Require a human-copy brief and explainable copy-quality findings before production."""
    required = _anti_slop_route_required(spec, state)
    _validate_indonesian_fluency(spec, report, brand=brand, brand_bundle=brand_bundle, expected_scope=expected_scope)
    brief = spec.get("human_copy_brief")
    audit = spec.get("copy_quality_audit")
    if brief is None and audit is None and not required:
        return
    if not isinstance(brief, dict):
        if required:
            report.error("human_copy_brief_required", "$.human_copy_brief", "Canva production requires a human copy brief before drafting.")
        return
    sections = {
        "situation": ("moment", "observable_behavior"),
        "tension": ("audience_assumption", "friction"),
        "point_of_view": ("brand_stance", "what_we_refuse_to_say", "right_to_speak"),
        "proof": ("concrete_details", "source_refs"),
        "creative_route": ("visual_dependency", "distinctive_move"),
        "message_jobs": ("headline", "body", "caption", "cta_behavior"),
    }
    for section, fields in sections.items():
        value = brief.get(section)
        if not isinstance(value, dict):
            report.error("human_copy_brief_section", f"$.human_copy_brief.{section}", "Human Copy Brief sections must be structured objects.")
            continue
        for field in fields:
            item = value.get(field)
            valid = isinstance(item, list) and bool(item) if field in {"concrete_details", "source_refs"} else _nonempty_string(item)
            if not valid:
                report.error("human_copy_brief_field", f"$.human_copy_brief.{section}.{field}", "Human Copy Brief requires concrete, human-supplied message work for this field.")
    if not isinstance(audit, dict):
        if required:
            report.error("copy_quality_audit_required", "$.copy_quality_audit", "Production requires an explainable copy quality audit.")
        return
    proof = brief.get("proof", {})
    source_refs = proof.get("source_refs") if isinstance(proof, dict) else None
    packet_ids = set(spec.get("source_packet", {}).get("proof_ids", [])) if isinstance(spec.get("source_packet"), dict) else set()
    if not isinstance(source_refs, list) or not source_refs or any(not isinstance(ref, str) or not ref.strip() or ref not in packet_ids for ref in source_refs):
        report.error("copy_quality_provenance", "$.human_copy_brief.proof.source_refs", "Copy quality cannot self-attest without source references.")
    copy_text = _all_content_text(spec).casefold()
    unsupported_intimacy = re.search(
        r"(?:\b(?:we|kami)\s+(?:know|understand|tahu)\s+(?:(?:exactly|persis)\s+)?"
        r"(?:how\s+you\s+feel|what\s+you(?:'re|\s+are)\s+feeling|apa\s+yang\s+(?:anda|kamu)\s+rasakan|perasaan(?:mu|anda|kamu))\b"
        r"|\b(?:we|kami)\s+(?:also\s+)?(?:have\s+been|experienced|juga\s+pernah\s+berada|pernah\s+berada|juga\s+mengalami|pernah\s+mengalami)\s+"
        r"(?:there|it\s+too|in\s+(?:your\s+shoes|your\s+position)|di\s+posisi\s+(?:anda|kamu))\b)",
        copy_text,
    )
    if unsupported_intimacy:
        report.error("UNSUPPORTED_PERSONAL_OR_PERFORMANCE_CLAIM", "$.copy_quality_audit", "Personal-experience language requires provenance and explicit approval.")
    reasons = audit.get("reason_codes", [])
    if not isinstance(reasons, list) or any(not isinstance(code, str) or code not in COPY_QUALITY_REASON_CODES for code in reasons):
        report.error("copy_quality_reason_codes", "$.copy_quality_audit.reason_codes", "Copy audit reason codes must use the registered explainable vocabulary.")
    findings = audit.get("findings", [])
    if not isinstance(findings, list):
        report.error("copy_quality_findings", "$.copy_quality_audit.findings", "Copy audit findings must be a list.")
    else:
        for index, finding in enumerate(findings):
            if not isinstance(finding, dict):
                report.error("copy_quality_finding", f"$.copy_quality_audit.findings[{index}]", "Each copy-quality finding must be an object.")
                continue
            code = finding.get("reason_code", finding.get("code"))
            if isinstance(code, str) and code in INDONESIAN_REASON_CODES:
                span = finding.get("evidence_span", finding.get("span"))
                if not isinstance(span, dict) or not _nonempty_string(span.get("text")) or not _nonempty_string(span.get("path")):
                    report.error(
                        "id_copy_finding_span",
                        f"$.copy_quality_audit.findings[{index}].evidence_span",
                        "Indonesian fluency findings require an evidence span with text and a copy-field path.",
                    )
    if required and audit.get("status") != "pass":
        report.error("copy_quality_status", "$.copy_quality_audit.status", "Copy quality audit must pass before Canva mutation or final states.")
    if required:
        _validate_id_production_review(
            spec,
            audit,
            _id_style_profile(spec),
            expected_scope,
            policy,
            actor_id,
            report,
        )


def _anti_slop_route_required(spec: dict[str, Any], state: Any) -> bool:
    design = spec.get("design")
    if isinstance(design, dict):
        mutation_status = design.get("mutation_status")
        if design.get("canva_mutation") is True or (isinstance(mutation_status, str) and mutation_status in {"requested", "succeeded", "committed"}):
            return True
        if any(_nonempty_string(design.get(key)) for key in ("draft_ref", "canva_design_id", "canva_design_url", "render_ref")):
            return True
    # A local DESIGN_DRAFT remains migratable legacy data.  Once a render,
    # remote design, or final/QA state exists, the anti-slop contract is a hard
    # gate.
    return state in ANTI_SLOP_STATES - {"DESIGN_DRAFT"}


def _normalise_route_value(value: Any) -> str:
    if isinstance(value, list):
        return "|".join(_normalise_route_value(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def _validate_route_set(
    spec: dict[str, Any],
    expected_scope: dict[str, str] | None,
    state: Any,
    report: Report,
) -> list[dict[str, Any]]:
    route_required = _anti_slop_route_required(spec, state) or spec.get("route_set") is not None
    raw = spec.get("route_set")
    if raw is None and not route_required:
        return []
    if not isinstance(raw, dict):
        report.error("route_set_required", "$.route_set", "Canva mutation/final states require three to five route cards before production.")
        return []
    _validate_anti_scope(raw.get("scope"), "$.route_set.scope", expected_scope, report, required=_anti_slop_route_required(spec, state))
    routes = raw.get("routes", raw.get("route_cards"))
    if not isinstance(routes, list):
        report.error("route_set_routes", "$.route_set.routes", "route_set.routes must be a list of route cards.")
        return []
    if not 3 <= len(routes) <= 5:
        report.error("route_count", "$.route_set.routes", "Provide three to five genuinely different route cards before Canva production.")
    seen: set[str] = set()
    valid_routes: list[dict[str, Any]] = []
    for index, route in enumerate(routes):
        path = f"$.route_set.routes[{index}]"
        if not isinstance(route, dict):
            report.error("route_type", path, "Each route card must be an object.")
            continue
        route_id = route.get("route_id", route.get("id", route.get("route_name")))
        if not _safe_registry_id(route_id):
            report.error("route_id", f"{path}.route_id", "Route cards need a stable lowercase route_id.")
        elif isinstance(route_id, str) and route_id in seen:
            report.error("route_id_duplicate", f"{path}.route_id", "Route IDs must be unique.")
        else:
            seen.add(route_id)
        required_fields = ("strategic_idea", "audience_tension", "message_promise", "visual_premise", "why_different_from_recent_posts")
        for key in required_fields:
            if not _nonempty_string(route.get(key)):
                report.error("route_field", f"{path}.{key}", "Each route needs a specific idea, tension, promise, visual premise, and difference rationale.")
        proof_ids = route.get("proof_ids", [])
        if not isinstance(proof_ids, list) or any(not _safe_registry_id(item) for item in proof_ids):
            report.error("route_proof_ids", f"{path}.proof_ids", "Route proof_ids must be a list of scoped lowercase IDs.")
        move = route.get("distinctive_move")
        moves = route.get("distinctive_moves")
        if moves is not None:
            if not isinstance(moves, list) or len(moves) != 1 or not _nonempty_string(moves[0]):
                report.error("distinctive_move_count", f"{path}.distinctive_moves", "Each route must specify exactly one distinctive move.")
        elif not _nonempty_string(move):
            report.error("distinctive_move", f"{path}.distinctive_move", "Each route must specify exactly one distinctive move.")
        else:
            move = [move]
        route_text = " ".join(str(route.get(key, "")) for key in required_fields + ("distinctive_move",))
        placeholder = re.search(r"\b(?:tbd|todo|placeholder|lorem|same as|route\s*[0-9]+)\b", route_text, re.I)
        if placeholder:
            report.error("route_placeholder", path, "Route contains a trivial placeholder and cannot enter production.")
        if GENERIC_ROUTE_RE.search(route_text):
            report.warning("generic_route_warning", path, "Generic language detected; retain only when the route also has concrete tension, proof, and point of view.")
            if GENERIC_ROUTE_RE.search(str(route.get("strategic_idea", ""))):
                report.error("generic_route", path, "Strategic idea is generic and cannot be the route's distinctive point of view.")
        for key in ("narrative_order", "asset_plan"):
            if not isinstance(route.get(key), (str, list)) or not _normalise_route_value(route.get(key)):
                report.error("route_field", f"{path}.{key}", "Route needs a concrete narrative_order and asset_plan.")
        valid_routes.append(route)

    route_axes = ("strategic_idea", "audience_tension", "visual_premise", "narrative_order", "asset_plan", "distinctive_move")
    for left_index, left in enumerate(valid_routes):
        for right in valid_routes[left_index + 1 :]:
            differences = sum(
                _normalise_route_value(left.get(key)) != _normalise_route_value(right.get(key)) for key in route_axes
            )
            if differences < 2:
                report.error(
                    "routes_not_distinct",
                    "$.route_set.routes",
                    f"Routes {left.get('route_id', left.get('id'))!r} and {right.get('route_id', right.get('id'))!r} differ on fewer than two axes ({', '.join(key for key in route_axes if _normalise_route_value(left.get(key)) != _normalise_route_value(right.get(key))) or 'none'}); color, font, or synonym changes are insufficient.",
                )
                break
    return valid_routes


def _validate_recent_fingerprints(
    value: Any,
    path: str,
    expected_scope: dict[str, str] | None,
    report: Report,
    *,
    required: bool,
) -> None:
    if not isinstance(value, dict):
        report.error("recent_fingerprints_type", path, "Recent fingerprints must be an object with scope and similarity metadata.")
        return
    _validate_anti_scope(value.get("scope"), f"{path}.scope", expected_scope, report, required=required)
    if not _nonempty_string(value.get("window")):
        report.error("recent_fingerprints_window", f"{path}.window", "Recent fingerprints require a bounded observation window.")
    fingerprint_fields = ("hooks", "ctas", "layout_families", "motifs", "phrases")
    if required and not any(isinstance(value.get(key), list) and value.get(key) for key in fingerprint_fields):
        report.error("recent_fingerprints_data", path, "Recent fingerprints need hooks, CTAs, layout families, motifs, or phrases.")
    similarities = value.get("similarity_checks", value.get("similarities"))
    if not isinstance(similarities, list):
        report.error("similarity_metadata", f"{path}.similarity_checks", "Recent fingerprints require deterministic similarity metadata.")
    else:
        if required and not similarities:
            report.error("similarity_metadata", f"{path}.similarity_checks", "Final states require non-empty similarity comparisons.")
        for index, item in enumerate(similarities):
            item_path = f"{path}.similarity_checks[{index}]"
            if not isinstance(item, dict):
                report.error("similarity_metadata", item_path, "Each similarity check must be an object.")
                continue
            if not _nonempty_string(item.get("candidate_id")):
                report.error("similarity_metadata", f"{item_path}.candidate_id", "Similarity checks require a candidate ID.")
            score = item.get("similarity")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
                report.error("similarity_score", f"{item_path}.similarity", "Similarity must be a number from 0 to 1.")
            if item.get("status") not in {"pass", "fail", "pending"}:
                report.error("similarity_status", f"{item_path}.status", "Similarity checks require pass, fail, or pending status.")


def _route_id_from_selection(selection: Any) -> str | None:
    if isinstance(selection, str):
        return selection
    if isinstance(selection, dict):
        value = selection.get("route_id", selection.get("selected_route_id"))
        return value if isinstance(value, str) else None
    return None


def _validate_human_selected_route(
    spec: dict[str, Any],
    routes: list[dict[str, Any]],
    expected_scope: dict[str, str] | None,
    state: Any,
    report: Report,
) -> str | None:
    selection = spec.get("human_selected_route")
    required = _anti_slop_route_required(spec, state)
    if selection is None:
        if required:
            report.error("human_selected_route_required", "$.human_selected_route", "A human must select a route before Canva mutation or final states.")
        return None
    route_id = _route_id_from_selection(selection)
    route_ids = {
        route.get("route_id", route.get("id", route.get("route_name")))
        for route in routes
        if isinstance(route.get("route_id", route.get("id", route.get("route_name"))), str)
    }
    if route_id not in route_ids:
        report.error("human_selected_route_invalid", "$.human_selected_route", "human_selected_route must reference one of the generated route cards.")
    if isinstance(selection, dict):
        if selection.get("decision") not in {"selected", "approved"}:
            report.error("human_selected_route_decision", "$.human_selected_route.decision", "Route selection decision must be selected or approved.")
        if required:
            _validate_anti_scope(selection.get("scope"), "$.human_selected_route.scope", expected_scope, report, required=True)
        if required and not _nonempty_string(selection.get("selected_by")):
            report.error("human_selected_route_actor", "$.human_selected_route.selected_by", "Route selection requires a human actor ID.")
        if required and _parse_datetime(selection.get("selected_at")) is None:
            report.error("human_selected_route_time", "$.human_selected_route.selected_at", "Route selection requires a timezone-aware timestamp.")
        if required and not _nonempty_string(selection.get("reason")):
            report.error("human_selected_route_reason", "$.human_selected_route.reason", "Route selection requires a reason.")
    elif required:
        report.error("human_selected_route_record", "$.human_selected_route", "Final/mutating routes require selection actor, timestamp, decision, and scope evidence.")
    return route_id if isinstance(route_id, str) else None


def _validate_art_direction(
    spec: dict[str, Any],
    selected_route_id: str | None,
    state: Any,
    report: Report,
) -> None:
    required = _anti_slop_route_required(spec, state)
    art = spec.get("art_direction")
    if art is None and not required:
        return
    if not isinstance(art, dict):
        report.error("art_direction_required", "$.art_direction", "Canva mutation/final states require art direction before layout production.")
        return
    if selected_route_id and art.get("route_id") != selected_route_id:
        report.error("art_direction_route_mismatch", "$.art_direction.route_id", "Art direction must reference the human-selected route.")
    if not _nonempty_string(art.get("visual_premise")):
        report.error("art_direction_field", "$.art_direction.visual_premise", "Art direction requires an observable visual premise.")
    move = art.get("distinctive_move")
    moves = art.get("distinctive_moves")
    if moves is not None:
        if not isinstance(moves, list) or len(moves) != 1 or not _nonempty_string(moves[0]):
            report.error("distinctive_move_count", "$.art_direction.distinctive_moves", "Art direction must contain exactly one distinctive move.")
    elif not _nonempty_string(move):
        report.error("distinctive_move", "$.art_direction.distinctive_move", "Art direction requires exactly one distinctive move.")
    if not _nonempty_string(art.get("rationale")):
        report.error("art_direction_rationale", "$.art_direction.rationale", "Explain how the distinctive move serves the message.")
    decorative = art.get("decorative_elements", [])
    if not isinstance(decorative, list):
        report.error("decorative_elements", "$.art_direction.decorative_elements", "decorative_elements must be a list.")
    else:
        for index, element in enumerate(decorative):
            path = f"$.art_direction.decorative_elements[{index}]"
            if not isinstance(element, dict):
                report.error("decorative_element", path, "Each decorative element must document its semantic role and rationale.")
                continue
            if not _nonempty_string(element.get("semantic_role")) or not _nonempty_string(element.get("rationale")):
                report.error("decorative_element_role", path, "Every decorative element requires semantic_role and rationale.")


def _validate_production_controls(
    spec: dict[str, Any],
    expected_scope: dict[str, str] | None,
    template_entries: list[dict[str, Any]],
    state: Any,
    report: Report,
) -> None:
    required = _anti_slop_route_required(spec, state)
    controls = spec.get("production_controls", spec.get("canva_production", spec.get("canva_runtime")))
    design = spec.get("design") if isinstance(spec.get("design"), dict) else {}
    if controls is None and not required:
        return
    if controls is None:
        # Accept the direct runtime metadata shape used by older handoffs while
        # still validating every field as the same scoped production control.
        direct_brand_controls = design.get("brand_controls_snapshot", spec.get("brand_controls_snapshot"))
        direct_folder_id = design.get("folder_id", spec.get("folder_id"))
        direct_template = design.get("template_snapshot")
        if direct_brand_controls is not None or direct_folder_id is not None or direct_template is not None:
            controls = {
                "scope": design.get("remote_scope"),
                "template": direct_template or {
                    "template_id": design.get("template_id"),
                    "version": design.get("template_version", design.get("template_revision")),
                    "provider": design.get("provider"),
                    "provider_template_id": _provider_template_id_value(design),
                    "status": design.get("template_status", "approved"),
                },
                "folder": {
                    "folder_id": direct_folder_id,
                    "status": design.get("folder_status", "approved"),
                    "scope": design.get("folder_scope", design.get("remote_scope")),
                },
                "brand_controls": direct_brand_controls,
            }
    if not isinstance(controls, dict):
        report.error("production_controls_required", "$.production_controls", "Canva mutation/final states require approved template, folder, and Brand Controls snapshots.")
        return
    _validate_anti_scope(controls.get("scope"), "$.production_controls.scope", expected_scope, report, required=required)
    template = controls.get("template", controls.get("approved_template"))
    if not isinstance(template, dict):
        template = controls
    template_id = template.get("template_id")
    template_version = template.get("version", template.get("template_version"))
    provider_id = _provider_template_id_value(template)
    if not _safe_registry_id(template_id):
        report.error("production_template_missing", "$.production_controls.template.template_id", "Production controls require a local approved template ID.")
    if not _nonempty_string(template_version):
        report.error("production_template_version", "$.production_controls.template.version", "Production controls require an exact approved template version.")
    if template.get("status") not in {"approved", "active"}:
        report.error("production_template_unapproved", "$.production_controls.template.status", "Canva mutation/final states require an approved template snapshot.")
    if _nonempty_string(design.get("template_id")) and design.get("template_id") != template_id:
        report.error("template_snapshot_mismatch", "$.production_controls.template.template_id", "Production template must match design.template_id.")
    if _nonempty_string(design.get("template_version")) and design.get("template_version") != template_version:
        report.error("template_snapshot_mismatch", "$.production_controls.template.version", "Production template version must match design.template_version.")
    design_provider = _provider_template_id_value(design)
    if design_provider is not None and provider_id != design_provider:
        report.error("template_snapshot_provider_mismatch", "$.production_controls.template", "Production template must carry the exact provider template ID used by Canva.")
    matching_entries = [entry for entry in template_entries if entry.get("template_id") == template_id and entry.get("version") == template_version and entry.get("status") == "approved"]
    if required and not matching_entries:
        report.error("production_template_registry", "$.production_controls.template", "Production template must resolve to the approved scoped template registry.")

    folder = controls.get("folder")
    if folder is None:
        folder = {
            "folder_id": controls.get("folder_id"),
            "status": controls.get("folder_status", "approved"),
            "scope": controls.get("folder_scope", controls.get("scope")),
        }
    if not isinstance(folder, dict):
        report.error("folder_snapshot", "$.production_controls.folder", "Production controls require an approved folder snapshot.")
        folder = {}
    _validate_anti_scope(folder.get("scope"), "$.production_controls.folder.scope", expected_scope, report, required=required)
    if not _nonempty_string(folder.get("folder_id")):
        report.error("folder_snapshot", "$.production_controls.folder.folder_id", "Folder snapshot requires an opaque folder_id.")
    if folder.get("status") not in {"approved", "active"}:
        report.error("folder_unapproved", "$.production_controls.folder.status", "Canva mutation/final states require an approved folder snapshot.")
    for key in ("folder_id",):
        if design.get(key) is not None and design.get(key) != folder.get(key):
            report.error("folder_snapshot_mismatch", f"$.production_controls.folder.{key}", "Folder snapshot must match the design remote folder reference.")

    brand_controls = controls.get("brand_controls", controls.get("brand_controls_snapshot"))
    if isinstance(brand_controls, str):
        brand_controls = {
            "snapshot_id": brand_controls,
            "revision": controls.get("brand_controls_revision", spec.get("brand_controls_revision", design.get("brand_controls_revision"))),
            "status": controls.get("brand_controls_status", spec.get("brand_controls_status", design.get("brand_controls_status", "approved"))),
            "scope": controls.get("brand_controls_scope", spec.get("brand_controls_scope", design.get("brand_controls_scope", design.get("remote_scope")))),
            "locked_elements": controls.get("locked_elements", spec.get("locked_elements", design.get("locked_elements", []))),
            "editable_slots": controls.get("editable_slots", spec.get("editable_slots", design.get("editable_slots", []))),
        }
    if not isinstance(brand_controls, dict):
        report.error("brand_controls_snapshot", "$.production_controls.brand_controls", "Canva mutation/final states require a Brand Controls snapshot.")
        return
    _validate_anti_scope(brand_controls.get("scope"), "$.production_controls.brand_controls.scope", expected_scope, report, required=required)
    if not _nonempty_string(brand_controls.get("snapshot_id")) or not _nonempty_string(brand_controls.get("revision")):
        report.error("brand_controls_snapshot", "$.production_controls.brand_controls", "Brand Controls snapshot requires snapshot_id and revision.")
    if brand_controls.get("status") not in {"approved", "active"}:
        report.error("brand_controls_unapproved", "$.production_controls.brand_controls.status", "Brand Controls must be approved for Canva mutation/final states.")
    for key in ("locked_elements", "editable_slots"):
        if not isinstance(brand_controls.get(key), list):
            report.error("brand_controls_fields", f"$.production_controls.brand_controls.{key}", "Brand Controls snapshot must list locked elements and editable slots.")
    if required:
        locked = set(brand_controls.get("locked_elements", [])) if isinstance(brand_controls.get("locked_elements"), list) else set()
        editable = set(brand_controls.get("editable_slots", [])) if isinstance(brand_controls.get("editable_slots"), list) else set()
        if not locked or not editable:
            report.error("brand_controls_fields", "$.production_controls.brand_controls", "Final controls require non-empty locked and editable slot sets.")
        if locked & editable:
            report.error("brand_controls_overlap", "$.production_controls.brand_controls", "Locked elements and editable slots must be disjoint.")


def _validate_page_contract(
    spec: dict[str, Any],
    source_packet: Any,
    state: Any,
    report: Report,
) -> None:
    if not _anti_slop_route_required(spec, state):
        return
    known_proof_ids = None
    if isinstance(source_packet, dict) and isinstance(source_packet.get("proof_ids"), list):
        raw_proof_ids = source_packet.get("proof_ids", [])
        known_proof_ids = {item for item in raw_proof_ids if isinstance(item, str)}
        if any(not isinstance(item, str) for item in raw_proof_ids):
            report.error("source_packet_proof_ids", "$.source_packet.proof_ids", "Every proof ID must be a scalar string registry ID.")
    slides = spec.get("slides")
    if not isinstance(slides, list):
        return
    proof_records: dict[str, dict[str, Any]] = {}
    if isinstance(source_packet, dict):
        raw_records = source_packet.get("proofs", source_packet.get("proof_entries", source_packet.get("evidence", [])))
        if isinstance(raw_records, list):
            for record in raw_records:
                if not isinstance(record, dict):
                    continue
                record_id = record.get("proof_id", record.get("id", record.get("claim_id")))
                if isinstance(record_id, str):
                    proof_records[record_id] = record
    claims = {
        claim.get("claim_id"): claim
        for claim in spec.get("claims", [])
        if isinstance(claim, dict) and isinstance(claim.get("claim_id"), str)
    }
    information_jobs: dict[str, list[int]] = {}
    for index, slide in enumerate(slides):
        path = f"$.slides[{index}]"
        if not isinstance(slide, dict):
            continue
        page_role = slide.get("page_role", slide.get("role"))
        visual_role = slide.get("visual_role")
        if not _nonempty_string(page_role):
            report.error("page_role_missing", f"{path}.page_role", "Every page needs an explicit page role.")
        if not _nonempty_string(visual_role):
            report.error("visual_role_missing", f"{path}.visual_role", "Every page needs an explicit visual role.")
        proof_ids = slide.get("proof_ids", [])
        if not isinstance(proof_ids, list) or any(not _safe_registry_id(item) for item in proof_ids):
            report.error("page_proof_ids", f"{path}.proof_ids", "Every page needs a proof_ids list of scoped IDs (empty only when no proof is used).")
        elif known_proof_ids is not None and any(item not in known_proof_ids for item in proof_ids):
            report.error("page_proof_scope", f"{path}.proof_ids", "Page proof IDs must resolve to the scoped source packet.")
        binding = slide.get("supported_message_jobs")
        for proof_id in proof_ids if isinstance(proof_ids, list) else []:
            record = proof_records.get(proof_id) or claims.get(proof_id)
            explicit_binding = (isinstance(binding, dict) and proof_id in binding) or (isinstance(binding, list) and proof_id in binding)
            if not isinstance(record, dict):
                if not explicit_binding:
                    report.error("page_proof_evidence_missing", f"{path}.proof_ids", f"Proof ID {proof_id!r} has no scoped source entry/claim or explicit supported_message_jobs binding.")
                continue
            source_text = " ".join(str(record.get(key, "")) for key in ("content", "summary", "proof", "claim", "text", "description"))
            visible_text = " ".join(str(slide.get(key, "")) for key in ("headline", "body", "cta", "information_job"))
            source_keywords = _tokens(source_text)
            visible_keywords = _tokens(visible_text)
            supported_jobs = record.get("supported_message_jobs", [])
            job_binding = isinstance(supported_jobs, list) and any(_tokens(str(job)) & _tokens(str(slide.get("information_job", ""))) for job in supported_jobs)
            if not explicit_binding and not (source_keywords & visible_keywords) and not job_binding:
                report.error("page_proof_linkage", f"{path}.proof_ids", f"Proof ID {proof_id!r} does not semantically support this slide's visible copy; add matching content/summary keywords or an explicit supported_message_jobs binding.")
        information_job = slide.get("information_job", slide.get("message_job"))
        progression = slide.get("progression")
        if not _nonempty_string(information_job):
            report.error("slide_information_job_missing", f"{path}.information_job", "Production slides must state their distinct information job.")
        else:
            job_key = re.sub(r"\s+", " ", information_job.casefold().strip())
            information_jobs.setdefault(job_key, []).append(index + 1)
        if isinstance(progression, dict):
            progression_valid = any(_nonempty_string(progression.get(key)) for key in ("advances", "from_previous", "next_step", "what_changes"))
        else:
            progression_valid = _nonempty_string(progression)
        if not progression_valid:
            report.error("slide_progression_missing", f"{path}.progression", "Production slides must record how this slide advances the audience from the previous job.")
    for job, slide_numbers in information_jobs.items():
        if len(slide_numbers) > 1:
            report.error("slide_information_job_duplicate", "$.slides", f"Each production slide needs a distinct information job; {job!r} repeats on slides {slide_numbers}.")


def _validate_evidence_status(value: Any, path: str, report: Report) -> str | None:
    if isinstance(value, str):
        status = value
    elif isinstance(value, dict):
        status = value.get("status")
    else:
        report.error("anti_slop_evidence_type", path, "Evidence must be a status string or an object with status.")
        return None
    if status not in ANTI_SLOP_EVIDENCE_STATUSES:
        report.error("anti_slop_evidence_status", path, "Evidence status must be pending, pass, fail, or not_applicable.")
        return None
    return status


def _anti_slop_package_checksum(spec: dict[str, Any], audit: dict[str, Any]) -> str | None:
    design = spec.get("design") if isinstance(spec.get("design"), dict) else {}
    package = audit.get("approval_package") if isinstance(audit.get("approval_package"), dict) else {}
    export_checksum = design.get("export_checksum")
    content_scope = spec.get("scope") if isinstance(spec.get("scope"), dict) else None
    full_content_scope = (
        {**content_scope, "brand_id": spec.get("brand_id")}
        if isinstance(content_scope, dict)
        else None
    )
    payload = {
        "content_id": spec.get("content_id"),
        "scope": full_content_scope,
        "selected_route": next((route for route in (spec.get("route_set", {}).get("routes", []) if isinstance(spec.get("route_set"), dict) else []) if route.get("route_id") == _route_id_from_selection(spec.get("human_selected_route"))), None),
        "selection_record": spec.get("human_selected_route"),
        "source_packet": spec.get("source_packet"),
        "creative_brief": spec.get("creative_brief"),
        "art_direction": spec.get("art_direction"),
        "production_controls": spec.get("production_controls"),
        "single_message": spec.get("single_message"),
        "slides": spec.get("slides"),
        "caption": spec.get("caption"),
        "id_style_profile": spec.get("id_style_profile", spec.get("locale_policy", {}).get("id_style_profile") if isinstance(spec.get("locale_policy"), dict) else None),
        "copy_quality_audit": spec.get("copy_quality_audit"),
        "evidence": audit.get("evidence"),
        "findings": audit.get("findings"),
        "hard_blockers": audit.get("hard_blockers"),
        "independent_critique": audit.get("independent_critique"),
        "render_evidence": design.get("render_evidence"),
        "audit_version": audit.get("schema_version"),
        "slop_index": audit.get("slop_index"),
        "rubric_total": (audit.get("rubric") or {}).get("total") if isinstance(audit.get("rubric"), dict) else None,
        "render_digest": package.get("render_digest"),
        "export_checksum": export_checksum,
    }
    manifest = _message_manifest_for_checksum(spec)
    if manifest is not None:
        payload["message_units"] = manifest
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate_anti_slop_audit(
    spec: dict[str, Any],
    expected_scope: dict[str, str] | None,
    state: Any,
    template_entries: list[dict[str, Any]],
    report: Report,
    provenance_authority: dict[str, Any] | None = None,
) -> None:
    routes = _validate_route_set(spec, expected_scope, state, report)
    selected_route_id = _validate_human_selected_route(spec, routes, expected_scope, state, report)
    _validate_art_direction(spec, selected_route_id, state, report)
    _validate_production_controls(spec, expected_scope, template_entries, state, report)
    _validate_page_contract(spec, spec.get("source_packet"), state, report)
    _validate_message_unit_contract(spec, state, report, provenance_authority)

    required = _anti_slop_route_required(spec, state)
    audit = spec.get("anti_slop_audit")
    if audit is None and not required:
        return
    if not isinstance(audit, dict):
        report.error("anti_slop_audit_required", "$.anti_slop_audit", "Canva mutation/final states require an explainable anti_slop_audit.")
        return
    audit_status = audit.get("status")
    if not isinstance(audit_status, str) or audit_status not in {"pending", "pass", "fail"}:
        report.error("anti_slop_audit_status", "$.anti_slop_audit.status", "Anti-slop audit status must be pending, pass, or fail.")
    if required and audit_status != "pass":
        report.error("anti_slop_audit_incomplete", "$.anti_slop_audit.status", "Canva mutation/final states require a passing anti-slop audit.")

    reason_codes = audit.get("reason_codes", [])
    if not isinstance(reason_codes, list) or any(
        not isinstance(code, str)
        or (code not in ANTI_SLOP_REASON_CODES and not ANTI_SLOP_REASON_CODE_RE.fullmatch(code))
        for code in reason_codes
    ):
        report.error("anti_slop_reason_codes", "$.anti_slop_audit.reason_codes", "Reason codes must be explainable anti-slop findings, never detector scores.")
    findings = audit.get("findings", [])
    if not isinstance(findings, list):
        report.error("anti_slop_findings", "$.anti_slop_audit.findings", "Anti-slop findings must be a list.")
    else:
        for index, finding in enumerate(findings):
            path = f"$.anti_slop_audit.findings[{index}]"
            if not isinstance(finding, dict):
                report.error("anti_slop_finding", path, "Each finding must explain a reason, dimension, and location.")
                continue
            code = finding.get("reason_code", finding.get("code"))
            if not isinstance(code, str) or (
                code not in ANTI_SLOP_REASON_CODES and not ANTI_SLOP_REASON_CODE_RE.fullmatch(code)
            ):
                report.error("anti_slop_reason_code", f"{path}.reason_code", "Finding reason_code must be explainable and registered.")
            if not _nonempty_string(finding.get("dimension")) or not _nonempty_string(finding.get("explanation", finding.get("message"))):
                report.error("anti_slop_finding_explanation", path, "Findings require a dimension and explainable message.")

    slop_index = audit.get("slop_index")
    if not isinstance(slop_index, dict):
        report.error("slop_index", "$.anti_slop_audit.slop_index", "slop_index must contain five dimensions scored from 0 to 5.")
        slop_index = {}
    for dimension in ANTI_SLOP_SLOP_DIMENSIONS:
        score = slop_index.get(dimension)
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 5:
            report.error("slop_index_dimension", f"$.anti_slop_audit.slop_index.{dimension}", "Each slop dimension must be an integer from 0 to 5.")

    rubric = audit.get("rubric")
    if not isinstance(rubric, dict):
        report.error("rubric", "$.anti_slop_audit.rubric", "Anti-slop audit requires a 100-point dimension rubric.")
        rubric = {}
    score_total = 0
    for dimension, weight in ANTI_SLOP_RUBRIC_WEIGHTS.items():
        value = rubric.get(dimension, (rubric.get("scores") or {}).get(dimension) if isinstance(rubric.get("scores"), dict) else None)
        score = value.get("score") if isinstance(value, dict) else value
        maximum = value.get("max", weight) if isinstance(value, dict) else weight
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= weight:
            report.error("rubric_score", f"$.anti_slop_audit.rubric.{dimension}", f"Rubric score must be between 0 and its {weight}-point weight.")
        if maximum != weight:
            report.error("rubric_weight", f"$.anti_slop_audit.rubric.{dimension}", f"Rubric dimension weight must remain {weight} points.")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            score_total += score
    rubric_total = rubric.get("total")
    if not isinstance(rubric_total, (int, float)) or isinstance(rubric_total, bool) or rubric_total != score_total:
        report.error("rubric_total", "$.anti_slop_audit.rubric.total", "Rubric total must equal the sum of the seven weighted dimensions and stay within 100 points.")
    elif rubric_total > 100:
        report.error("rubric_total", "$.anti_slop_audit.rubric.total", "Rubric total cannot exceed 100 points.")
    if required and isinstance(rubric_total, (int, float)) and rubric_total < 80:
        report.error("rubric_threshold", "$.anti_slop_audit.rubric.total", "Production/final content requires at least 80/100 and no hard blocker.")

    evidence = audit.get("evidence")
    if not isinstance(evidence, dict):
        report.error("anti_slop_evidence", "$.anti_slop_audit.evidence", "Anti-slop audit requires OCR, layout, semantic, WCAG, rights, and similarity evidence.")
        evidence = {}
    for key in ANTI_SLOP_EVIDENCE_KEYS:
        path = f"$.anti_slop_audit.evidence.{key}"
        evidence_value = evidence.get(key)
        if evidence_value is None:
            evidence_value = evidence.get(
                {
                    "ocr": "ocr_exact_match",
                    "layout": "layout_checks",
                    "semantic": "semantic_contract",
                    "wcag": "wcag_contrast",
                    "rights": "rights_provenance",
                    "recent_similarity": "similarity",
                }[key]
            )
        status = _validate_evidence_status(evidence_value, path, report)
        if required and (not isinstance(evidence_value, dict) or status != "pass"):
            report.error("anti_slop_evidence_block", path, "Canva mutation/final states require structured passing evidence for every quality gate.")
        if required and isinstance(evidence_value, dict):
            if _parse_datetime(evidence_value.get("checked_at", evidence_value.get("timestamp"))) is None:
                report.error("anti_slop_evidence_timestamp", path, "Required evidence needs a timezone-aware checked_at timestamp.")
            if not isinstance(evidence_value.get("page_refs", evidence_value.get("render_refs", [])), list) or not evidence_value.get("page_refs", evidence_value.get("render_refs", [])):
                report.error("anti_slop_evidence_refs", path, "Required evidence needs non-empty page or render references.")
        if key == "ocr" and isinstance(evidence_value, dict) and status == "pass" and evidence_value.get("exact_match") is not True:
            report.error("ocr_exact_match", path, "OCR evidence must explicitly record exact_match true.")
        if key == "layout" and isinstance(evidence_value, dict) and status == "pass":
            if evidence_value.get("overflow") not in (False, "none") or evidence_value.get("overlap") not in (False, "none"):
                report.error("layout_evidence_incomplete", path, "Passing layout evidence must explicitly record overflow=false and overlap=false.")
            if evidence_value.get("overflow") is True or evidence_value.get("overlap") is True:
                report.error("layout_blocker", path, "Layout evidence cannot pass with overflow or collision.")
        if key == "semantic" and isinstance(evidence_value, dict) and status == "pass":
            checks = evidence_value.get("contract_tests", evidence_value.get("checks"))
            if not isinstance(checks, list) or not checks:
                report.error("semantic_evidence_incomplete", path, "Passing semantic evidence must list object/count/color/relation/CTA contract checks.")
        if key == "rights" and isinstance(evidence_value, dict) and status == "pass":
            if not isinstance(evidence_value.get("assets"), list) and not isinstance(evidence_value.get("provenance"), list):
                report.error("rights_evidence_incomplete", path, "Passing rights evidence must list asset provenance or an explicit empty assets list.")
        if key == "recent_similarity" and isinstance(evidence_value, dict) and status == "pass":
            if not isinstance(evidence_value.get("threshold"), (int, float)) and not isinstance(evidence_value.get("similarity_checks"), list):
                report.error("similarity_evidence_incomplete", path, "Passing similarity evidence must record a threshold or similarity checks.")
        if key == "wcag" and isinstance(evidence_value, dict) and status == "pass":
            if evidence_value.get("contrast_pass") is not True:
                report.error("wcag_contrast", path, "WCAG evidence must explicitly record contrast_pass true.")
    independent = audit.get("independent_critique", spec.get("independent_critique"))
    if not isinstance(independent, dict):
        if required:
            report.error("independent_critique_missing", "$.anti_slop_audit.independent_critique", "Final content requires an independent visual critique.")
    else:
        if required and independent.get("status") != "pass":
            report.error("independent_critique_status", "$.anti_slop_audit.independent_critique.status", "Independent critique must pass before final states.")
        if not _nonempty_string(independent.get("reviewer_id")):
            report.error("independent_critique_reviewer", "$.anti_slop_audit.independent_critique.reviewer_id", "Independent critique requires a reviewer ID.")
        if independent.get("independent_from_generation") is not True:
            report.error("independent_critique_independence", "$.anti_slop_audit.independent_critique.independent_from_generation", "Critique must be independently performed.")

    blockers = audit.get("hard_blockers")
    if not isinstance(blockers, dict):
        report.error("hard_blockers", "$.anti_slop_audit.hard_blockers", "Hard blockers must be recorded as pass/fail evidence.")
    else:
        if required and set(blockers) != ANTI_SLOP_HARD_BLOCKER_KEYS:
            report.error("hard_blocker_keys", "$.anti_slop_audit.hard_blockers", "Final states require the complete allowlisted hard-blocker key set.")
        for code, status in blockers.items():
            if isinstance(status, str) and not required and status in {"pass", "fail", "pending"}:
                continue
            if not isinstance(status, dict) or status.get("status") not in {"pass", "fail", "pending"} or not _nonempty_string(status.get("evidence", status.get("reason"))):
                report.error("hard_blocker", f"$.anti_slop_audit.hard_blockers.{code}", "Each hard blocker needs typed status and evidence.")
            elif required and status.get("status") != "pass":
                report.error("hard_blocker", f"$.anti_slop_audit.hard_blockers.{code}", "Canva mutation/final states fail closed on any unresolved hard blocker.")
            elif code not in ANTI_SLOP_HARD_BLOCKER_KEYS:
                report.error("hard_blocker_key", f"$.anti_slop_audit.hard_blockers.{code}", "Unknown hard-blocker key.")

    package = audit.get("approval_package")
    if required:
        if not isinstance(package, dict):
            report.error("approval_package_missing", "$.anti_slop_audit.approval_package", "Final content requires a scoped approval package and checksum evidence.")
        else:
            _validate_anti_scope(package.get("scope"), "$.anti_slop_audit.approval_package.scope", expected_scope, report, required=True)
            if package.get("content_id") != spec.get("content_id"):
                report.error("approval_package_content", "$.anti_slop_audit.approval_package.content_id", "Approval package content_id must match the content record.")
            export_checksum = spec.get("design", {}).get("export_checksum") if isinstance(spec.get("design"), dict) else None
            if package.get("export_checksum") != export_checksum:
                report.error("approval_package_export", "$.anti_slop_audit.approval_package.export_checksum", "Approval package must bind the exact export checksum.")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(package.get("render_digest"))):
                report.error("approval_package_render", "$.anti_slop_audit.approval_package.render_digest", "Approval package requires a sha256 render digest.")
            expected_package_checksum = _anti_slop_package_checksum(spec, audit)
            if package.get("checksum") != expected_package_checksum:
                report.error("anti_slop_package_checksum", "$.anti_slop_audit.approval_package.checksum", "Approval package checksum does not match route, audit, render, and export evidence.")
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
        # Anti-slop route selection and audit package are part of the exact
        # artifact approval.  A changed route/audit must require re-approval.
        "human_selected_route": _route_id_from_selection(spec.get("human_selected_route")),
        "anti_slop_package_checksum": (
            spec.get("anti_slop_audit", {}).get("approval_package", {}).get("checksum")
            if isinstance(spec.get("anti_slop_audit"), dict)
            and isinstance(spec.get("anti_slop_audit", {}).get("approval_package"), dict)
            else None
        ),
        "single_message": spec.get("single_message"),
        "slides": spec.get("slides"),
        "caption": spec.get("caption"),
        "id_style_profile": spec.get("id_style_profile", spec.get("locale_policy", {}).get("id_style_profile") if isinstance(spec.get("locale_policy"), dict) else None),
        "copy_quality_audit": spec.get("copy_quality_audit"),
        "alt_text": spec.get("alt_text"),
        "target_account": publishing.get("target_account"),
        "scheduled_at": publishing.get("scheduled_at"),
        "timezone": publishing.get("timezone"),
    }
    manifest = _message_manifest_for_checksum(spec)
    if manifest is not None:
        payload["message_units"] = manifest
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
    master_brand_bundle: str | Path | None = None,
) -> Report:
    report = Report()
    today = today or datetime.now(timezone.utc).date()

    if not isinstance(spec, dict):
        report.error("root_type", "$", "Content spec must be a JSON object.")
        return report

    _scan_for_secrets(spec, report)
    _scan_for_universal_detector_fields(spec, report)
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
        master_brand_bundle=master_brand_bundle,
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
    _validate_source_packet_and_brief(spec, canonical_scope, state, report)

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
        local_handoff = design.get("local_handoff")
        has_local_handoff = isinstance(local_handoff, dict) and _nonempty_string(local_handoff.get("handoff_ref")) and local_handoff.get("status") in {"ready", "accepted"}
        if _state_at_least(state, "DESIGN_DRAFT") and not any(
            _nonempty_string(design.get(key)) for key in ("draft_ref", "canva_design_id", "canva_design_url")
        ) and not has_local_handoff:
            report.error("draft_evidence", "$.design", "Design draft state requires a draft or Canva reference.")
        if has_local_handoff:
            _validate_remote_scope(local_handoff.get("scope"), "$.design.local_handoff.scope", canonical_scope, report, required=True)
        if _state_at_least(state, "BRAND_QA"):
            render_evidence = design.get("render_evidence")
            if (not isinstance(render_evidence, dict) or not _nonempty_string(render_evidence.get("render_ref")) or
                not re.fullmatch(r"sha256:[0-9a-f]{64}", str(render_evidence.get("render_digest"))) or
                render_evidence.get("verification_status") != "verified" or
                render_evidence.get("provider") not in {"canva", "local_renderer"} or
                render_evidence.get("receipt_digest") != render_evidence.get("render_digest") or
                not _nonempty_string(render_evidence.get("receipt_id"))):
                report.error("render_evidence", "$.design.render_evidence", "Brand QA requires typed render_ref and render_digest evidence.")
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
            item = qa.get(key)
            status = item.get("status") if isinstance(item, dict) else item
            if status not in QA_STATUSES:
                report.error("qa_status", f"$.qa.{key}", "Unsupported QA status.")
            if _state_at_least(state, "HUMAN_APPROVED") and isinstance(item, dict):
                if _parse_datetime(item.get("checked_at")) is None or not isinstance(item.get("page_refs"), list) or not item.get("page_refs"):
                    report.error("qa_evidence", f"$.qa.{key}", "Final QA requires checked_at and non-empty page_refs.")
        if not isinstance(qa.get("notes"), list):
            report.error("qa_notes", "$.qa.notes", "qa.notes must be a list.")
        if _state_at_least(state, "HUMAN_APPROVED"):
            for key in qa_keys:
                allowed = {"pass"}
                if spec.get("format") == "text" and key in {"visual", "mobile_thumbnail"}:
                    allowed.add("not_applicable")
                status = qa.get(key).get("status") if isinstance(qa.get(key), dict) else qa.get(key)
                if status not in allowed:
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
    _validate_copy_first_gate(
        spec,
        state,
        report,
        brand=brand,
        brand_bundle=bundle,
        expected_scope=canonical_scope,
        policy=policy,
        actor_id=actor_id,
    )
    _validate_anti_slop_audit(spec, canonical_scope, state, template_entries, report, bundle)

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
    parser.add_argument("--master-brand-bundle", type=Path, help="Independently loaded active master Brand Copy four-file bundle for privileged product overlays")
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
        policy_context = load_trusted_policy(args.policy) if args.policy else None
        if args.brand_policy:
            brand_validator = _load_brand_bundle_validator()
            brand_policy_context = brand_validator.TrustedAccessPolicyContext.from_file(args.brand_policy) if brand_validator is not None else None
        else:
            brand_policy_context = None
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
        master_brand_bundle=args.master_brand_bundle,
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
