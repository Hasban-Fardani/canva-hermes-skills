#!/usr/bin/env python3
"""Validate one local Brand Copy Studio revision.

The validator is intentionally stdlib-only and has no network or provider
dependencies. It checks the four-file contract and catches common evidence,
rights, reference, revision, and secret-handling mistakes. It does not decide
    whether a source is truthful; that remains a human authorization and review
    decision. Schema 1.0 is accepted for legacy, unscoped bundles. Schema 1.1
    is required for active production bundles and carries the shared scope.
    Active bundles and approved claims/templates additionally require a trusted
    external local access-policy object supplied through ``policy`` or ``--policy``
    and a trusted runtime actor identity supplied through ``actor_id`` or
    ``--actor-id``; mutable authorization fields inside the bundle are audit
    receipts only. Privileged states also require the evidence-backed anti-slop
    creative contract in ``brand-profile.json``; this is an explainable schema
    gate, never an AI-authorship detector.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

REQUIRED_FILES = (
    "brand-profile.json",
    "claim-registry.json",
    "template-registry.json",
    "provenance.json",
)
ALLOWED_EVIDENCE = {"exact", "observed", "inferred", "unverified"}
SUPPORTED_SCHEMA_VERSIONS = {"1.0", "1.1"}
SCOPED_SCHEMA_VERSION = "1.1"
POLICY_SCHEMA_VERSION = "1.0"
ALLOWED_STATUS = {"draft", "active", "superseded"}
ALLOWED_CLAIM_STATUS = {"approved", "needs_review", "blocked", "expired"}
APPROVED_EVIDENCE = {"exact", "observed"}
APPROVED_RIGHTS = {"approved", "exact"}
SAFE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REVISION_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{6}Z)-r([1-9]\d*)$")
SCOPE_FIELDS = ("tenant_id", "client_id", "product_id", "parent_brand_revision")
APPROVED_ROLES = {"lead", "admin"}
POLICY_ROLES = ("lead", "admin", "member", "reviewer", "publisher")
POLICY_SCOPE_FIELDS = ("tenant_id", "client_id", "brand_id", "product_id")
WILDCARD_IDENTITIES = {"*", "all", "any", "everyone"}
SECRET_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "privatekey",
    "cookie",
)
SECRET_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
)


@dataclass(frozen=True)
class TrustedAccessPolicyContext:
    """Immutable, out-of-band policy capability for privileged validation."""

    _value: dict[str, Any]

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "TrustedAccessPolicyContext":
        return cls(deepcopy(value))

    @classmethod
    def from_file(cls, value: str | Path) -> "TrustedAccessPolicyContext":
        path = _path(value)
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def as_mapping(self) -> dict[str, Any]:
        return deepcopy(self._value)
ANTI_SLOP_LIST_FIELDS = (
    "audience_situations",
    "human_proof_points",
    "distinctive_assets",
    "visual_principles",
    "composition_rules",
    "avoid_patterns",
    "situation_patterns",
    "audience_moments",
    "observable_behaviors",
    "concrete_proof_details",
    "approved_verbal_assets",
    "owned_vocabulary",
)
ANTI_SLOP_REQUIRED_FIELDS = (
    *ANTI_SLOP_LIST_FIELDS,
    "strategic_tension",
    "voice_examples",
    "model_usage_policy",
    "approval_roles",
    "feedback_reason_codes",
    "brand_stance",
    "right_to_speak",
    "what_we_refuse_to_say",
    "voice_as_behavior",
    "locale_policy",
    "fake_intimacy_policy",
    "unsupported_first_person_policy",
)
ANTI_SLOP_TEXT_ALIASES = {
    "audience_situations": ("situation", "value", "description"),
    "human_proof_points": ("proof", "proof_point", "value", "description"),
    "distinctive_assets": ("asset", "name", "value", "description"),
    "visual_principles": ("principle", "value", "description"),
    "composition_rules": ("rule", "value", "description"),
    "avoid_patterns": ("pattern", "value", "description"),
    "situation_patterns": ("situation", "value", "description"),
    "audience_moments": ("moment", "value", "description"),
    "observable_behaviors": ("behavior", "value", "description"),
    "concrete_proof_details": ("detail", "proof", "value", "description"),
    "approved_verbal_assets": ("asset", "term", "value", "description"),
    "owned_vocabulary": ("term", "value", "description"),
}
ANTI_SLOP_REASON_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
ANTI_SLOP_APPROVAL_ROLES = {"lead", "admin", "reviewer", "publisher"}
ANTI_SLOP_POLICY_ALIASES = {
    "allowed": ("allowed", "allowed_uses", "allowed_roles", "allowed_ai_roles"),
    "restricted": ("restricted", "restricted_uses", "restricted_roles", "restricted_ai_roles"),
    "prohibited": ("prohibited", "prohibited_uses", "prohibited_roles", "prohibited_ai_roles"),
}

# ``id_style_profile`` is additive: legacy bundles may omit it entirely.  The
# aliases keep handoffs produced by earlier drafts readable without making a
# second canonical representation.  Values are intentionally a small register
# vocabulary; this is a configuration gate, not a language or naturalness
# score.
STYLE_PROFILE_ALIASES = ("id_style_profile", "indonesian_style_profile", "locale_style_profile")
STYLE_PROFILE_FIELD_ALIASES = {
    "channel": ("channel", "channels"),
    "register": ("register", "style_register"),
    "audience_relation": ("audience_relation", "relationship"),
    "region_or_community": ("region_or_community", "region_community", "region"),
    "pronoun_policy": ("pronoun_policy", "pronoun_address_policy"),
    "particle_policy": ("particle_policy", "particles"),
    "code_switch_policy": ("code_switch_policy", "code_switching_policy"),
    "contraction_spelling_policy": ("contraction_spelling_policy", "spelling_policy"),
    "approved_human_examples": ("approved_human_examples", "human_examples"),
}
STYLE_PROFILE_REQUIRED_FIELDS = tuple(STYLE_PROFILE_FIELD_ALIASES)
STYLE_PROFILE_REGISTERS = {
    "formal_public",
    "neutral_editorial",
    "friendly_conversational",
    "community_specific",
    "fandom",
    "local_activation",
    "youth_community",
    # Compatibility labels seen in handoff notes.
    "formal",
    "colloquial",
    "community",
    "friendly-national",
    "youth-community",
}
STYLE_PROFILE_COLLOQUIAL_REGISTERS = {
    "friendly_conversational",
    "community_specific",
    "fandom",
    "local_activation",
    "youth_community",
    "colloquial",
    "community",
    "friendly-national",
    "youth-community",
}
STYLE_PROFILE_CHANNELS = {
    "policy",
    "website",
    "carousel",
    "caption",
    "comment",
    "chat",
    "spoken_script",
    "social_post",
    "landing_page",
    "email",
    "support",
}
STYLE_PROFILE_RELATIONS = {
    "stranger",
    "customer",
    "peer",
    "member",
    "authority",
    "mixed",
    "community",
}
STYLE_PROFILE_POLICY_KEYS = {
    "pronoun_policy": {
        "approved",
        "approved_forms",
        "approved_pronouns",
        "avoid",
        "prohibited",
        "disallowed",
        "address_terms",
        "notes",
        "assumptions",
        "evidence_status",
        "source_ids",
    },
    "particle_policy": {
        "approved",
        "allowed",
        "particles",
        "prohibited",
        "forbidden",
        "avoid",
        "no_forced_slang",
        "max_per_sentence",
        "review_rule",
        "notes",
        "evidence_status",
        "source_ids",
    },
    "code_switch_policy": {
        "allowed_terms",
        "approved_terms",
        "allowed",
        "do_not_translate",
        "do_not_translate_terms",
        "translate_surrounding_syntax",
        "translate_unlisted_terms",
        "reasons",
        "notes",
        "evidence_status",
        "source_ids",
    },
    "contraction_spelling_policy": {
        "approved_forms",
        "contractions",
        "approved",
        "standard_forms",
        "standard",
        "prohibited_forms",
        "do_not_use",
        "default_spelling",
        "rules",
        "eyd_kbbi",
        "notes",
        "evidence_status",
        "source_ids",
    },
}


def _path(path: str | Path) -> Path:
    return Path(path).expanduser()


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _record_errors(value: Any, location: str = "$", errors: list[str] | None = None) -> list[str]:
    """Find invalid evidence labels and probable secrets anywhere in JSON."""

    errors = errors if errors is not None else []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in SECRET_KEY_PARTS):
                errors.append(f"{location}.{key}: secret-like key is not allowed")
            if key == "evidence_status" and child not in ALLOWED_EVIDENCE:
                errors.append(f"{location}.evidence_status: invalid value {child!r}")
            _record_errors(child, f"{location}.{key}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _record_errors(child, f"{location}[{index}]", errors)
    elif isinstance(value, str):
        for pattern in SECRET_VALUE_PATTERNS:
            if pattern.search(value):
                errors.append(f"{location}: probable secret value is not allowed")
                break
    return errors


def _require_fields(record: dict[str, Any], fields: Iterable[str], location: str, errors: list[str]) -> None:
    for field in fields:
        if field not in record:
            errors.append(f"{location}: missing {field!r}")


def _validate_evidence_record(record: dict[str, Any], location: str, errors: list[str]) -> None:
    _require_fields(record, ("evidence_status", "source_ids"), location, errors)
    status = record.get("evidence_status")
    if status not in ALLOWED_EVIDENCE:
        errors.append(f"{location}.evidence_status: invalid value {status!r}")
    source_ids = record.get("source_ids")
    if not isinstance(source_ids, list):
        errors.append(f"{location}.source_ids: must be an array")
    else:
        for index, source_id in enumerate(source_ids):
            if not _is_nonempty_string(source_id):
                errors.append(f"{location}.source_ids[{index}]: must be a non-empty string")


def _validate_rights(value: Any, location: str, errors: list[str], required: bool = False) -> dict[str, Any] | None:
    if value is None:
        if required:
            errors.append(f"{location}: required object")
        return None
    if not isinstance(value, dict):
        errors.append(f"{location}: must be an object")
        return None
    status = value.get("status")
    allowed = ALLOWED_EVIDENCE | {"approved", "blocked", "needs_review", "expired"}
    if status is not None and status not in allowed:
        errors.append(f"{location}.status: invalid value {status!r}")
    return value


def _validate_approved_record(record: dict[str, Any], location: str, errors: list[str]) -> None:
    """An approved claim/template must be evidenced and rights-cleared."""

    if record.get("status") != "approved":
        return
    if record.get("evidence_status") not in APPROVED_EVIDENCE:
        errors.append(f"{location}: approved record requires exact or observed evidence")
    source_ids = record.get("source_ids")
    if not isinstance(source_ids, list) or not source_ids or any(not _is_nonempty_string(item) for item in source_ids):
        errors.append(f"{location}: approved record requires non-empty source_ids")
    rights = _validate_rights(record.get("rights"), f"{location}.rights", errors, required=True)
    if rights is not None and rights.get("status") not in APPROVED_RIGHTS:
        errors.append(f"{location}: approved record requires rights.status approved or exact")


def _anti_slop_fields(profile: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    """Return the anti-slop contract, accepting a nested draft alias.

    The canonical representation is top-level on ``brand-profile.json`` so
    older consumers can ignore the additive fields.  A nested ``anti_slop``
    object is accepted for forward-compatible handoffs, but conflicting values
    are always rejected rather than choosing one silently.
    """

    nested = profile.get("anti_slop")
    if nested is not None and not isinstance(nested, dict):
        errors.append("brand-profile.json.anti_slop: must be an object")
        nested = {}
    values: dict[str, Any] = {}
    for field in ANTI_SLOP_REQUIRED_FIELDS:
        direct_present = field in profile
        nested_present = isinstance(nested, dict) and field in nested
        if direct_present and nested_present and profile[field] != nested[field]:
            errors.append(f"brand-profile.json.{field}: conflicts with brand-profile.json.anti_slop.{field}")
        if direct_present:
            values[field] = profile[field]
        elif nested_present:
            values[field] = nested[field]
    # Accept the descriptive split names used by older handoff notes while
    # emitting/using the canonical ``voice_examples`` object internally.
    if "voice_examples" not in values:
        positive_keys = ("positive_voice_examples", "voice_positive_examples")
        negative_keys = ("negative_voice_examples", "voice_negative_examples")
        positive = next((profile[key] for key in positive_keys if key in profile), None)
        negative = next((profile[key] for key in negative_keys if key in profile), None)
        if isinstance(nested, dict):
            positive = next((nested[key] for key in positive_keys if key in nested), positive)
            negative = next((nested[key] for key in negative_keys if key in nested), negative)
        if positive is not None or negative is not None:
            values["voice_examples"] = {"positive": positive or [], "negative": negative or []}
    aliases = {
        "distinctive_assets": ("distinctive_brand_assets",),
        "composition_rules": ("composition", "composition_principles"),
        "avoid_patterns": ("visual_avoid_patterns",),
    }
    for field, names in aliases.items():
        if field in values:
            continue
        alias_value = next((profile[name] for name in names if name in profile), None)
        if isinstance(nested, dict):
            alias_value = next((nested[name] for name in names if name in nested), alias_value)
        if alias_value is not None:
            values[field] = alias_value
    return values


def _validate_evidence_text_record(
    record: Any,
    location: str,
    aliases: tuple[str, ...],
    record_locations: dict[str, str],
    privileged: bool,
    errors: list[str],
) -> bool:
    """Validate one anti-slop evidence item and collect its stable ID."""

    if not isinstance(record, dict):
        errors.append(f"{location}: must be an object")
        return False
    _collect_record_id(record, location, record_locations, errors)
    _require_fields(record, ("id", "evidence_status", "source_ids"), location, errors)
    if not any(_is_nonempty_string(record.get(alias)) for alias in aliases):
        errors.append(f"{location}: requires a non-empty value ({', '.join(aliases)})")
    _validate_evidence_record(record, location, errors)
    if privileged and record.get("evidence_status") not in APPROVED_EVIDENCE:
        errors.append(f"{location}: privileged anti-slop evidence requires exact or observed status")
    source_ids = record.get("source_ids")
    if privileged and isinstance(source_ids, list) and not source_ids:
        errors.append(f"{location}: privileged anti-slop evidence requires non-empty source_ids")
    return True


def _validate_record_scope(value: Any, location: str, expected_scope: tuple[Any, ...] | None, errors: list[str]) -> None:
    """Validate optional record scope without allowing cross-tenant assets."""

    if value is None:
        return
    if not isinstance(value, dict) or not isinstance(expected_scope, tuple) or len(expected_scope) < 4:
        errors.append(f"{location}: scope must be an object matching bundle scope")
        return
    actual = (
        value.get("brand_id"),
        value.get("tenant_id"),
        value.get("client_id"),
        value.get("product_id") or "",
    )
    if actual != expected_scope[:4]:
        errors.append(f"{location}: does not match bundle scope")


def _validate_anti_slop_policy(value: Any, location: str, privileged: bool, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{location}: must be an object")
        return
    for concept, aliases in ANTI_SLOP_POLICY_ALIASES.items():
        present = next((alias for alias in aliases if alias in value), None)
        if present is None:
            errors.append(f"{location}: missing {concept!r} uses")
            continue
        items = value[present]
        if not isinstance(items, list):
            errors.append(f"{location}.{present}: must be an array")
            continue
        for index, item in enumerate(items):
            if not _is_nonempty_string(item):
                errors.append(f"{location}.{present}[{index}]: must be a non-empty string")

    human_required = value.get("human_approval_required", value.get("requires_human_approval"))
    if not isinstance(human_required, bool):
        errors.append(f"{location}.human_approval_required: must be boolean")
    elif privileged and human_required is not True:
        errors.append(f"{location}.human_approval_required: must be true for privileged states")

    approval_required = value.get("approval_required_for", value.get("human_approval_for"))
    if not isinstance(approval_required, list):
        errors.append(f"{location}.approval_required_for: must be an array")
    else:
        for index, item in enumerate(approval_required):
            if not _is_nonempty_string(item):
                errors.append(f"{location}.approval_required_for[{index}]: must be a non-empty string")
        if privileged and not approval_required:
            errors.append(f"{location}.approval_required_for: must not be empty for privileged states")

    groups: dict[str, set[str]] = {}
    for concept, aliases in ANTI_SLOP_POLICY_ALIASES.items():
        present = next((alias for alias in aliases if alias in value), None)
        if present and isinstance(value[present], list):
            groups[concept] = {item.casefold() for item in value[present] if isinstance(item, str)}
    if groups.get("allowed", set()) & groups.get("prohibited", set()):
        errors.append(f"{location}: allowed and prohibited model uses must be disjoint")
    if groups.get("restricted", set()) & groups.get("prohibited", set()):
        errors.append(f"{location}: restricted and prohibited model uses must be disjoint")
    if privileged:
        delegated_uses = groups.get("allowed", set()) | groups.get("restricted", set())
        forbidden_fragments = ("approv", "activat", "publish", "signoff", "finalize", "rightsclear", "claimapproval")
        if any(any(fragment in use.replace("_", "").replace("-", "") for fragment in forbidden_fragments) for use in delegated_uses):
            errors.append(f"{location}: model policy cannot delegate approval, activation, publishing, or rights clearance")


def _validate_approval_roles(value: Any, location: str, privileged: bool, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{location}: must be an object")
        return
    required = ("copy", "claims", "design", "publish")
    for field in required:
        roles = value.get(field)
        if not isinstance(roles, list):
            errors.append(f"{location}.{field}: must be an array")
            continue
        for index, role in enumerate(roles):
            if role not in ANTI_SLOP_APPROVAL_ROLES:
                errors.append(f"{location}.{field}[{index}]: invalid approval role {role!r}")
        if privileged and not roles:
            errors.append(f"{location}.{field}: must not be empty for privileged states")
    unknown = sorted(set(value) - set(required))
    if unknown:
        errors.append(f"{location}: unknown field(s) {unknown!r}")


def _validate_feedback_reason_codes(
    value: Any,
    location: str,
    expected_scope: tuple[Any, ...] | None,
    privileged: bool,
    errors: list[str],
) -> None:
    """Validate generic feedback taxonomy while binding it to one scope."""

    if isinstance(value, list):
        # Compatibility form: each code carries its own scope.
        codes = value
        container_scope = None
    elif isinstance(value, dict):
        codes = value.get("codes")
        container_scope = value.get("scope")
        if not isinstance(container_scope, dict):
            errors.append(f"{location}.scope: must be an object")
        unknown = sorted(set(value) - {"scope", "codes"})
        if unknown:
            errors.append(f"{location}: unknown field(s) {unknown!r}")
    else:
        errors.append(f"{location}: must be an object or array")
        return

    if not isinstance(codes, list):
        errors.append(f"{location}.codes: must be an array")
        return
    if privileged and not codes:
        errors.append(f"{location}.codes: must not be empty for privileged states")

    def scope_matches(scope: Any) -> bool:
        # Legacy and ordinary drafts may carry a placeholder taxonomy while
        # scope is still being established. Exact equality is a privileged
        # activation/approval gate, where accepting a mismatch would be unsafe.
        if not privileged:
            return True
        if not isinstance(scope, dict) or not isinstance(expected_scope, tuple) or len(expected_scope) < 4:
            return False
        return (
            scope.get("brand_id"),
            scope.get("tenant_id"),
            scope.get("client_id"),
            scope.get("product_id") or "",
        ) == expected_scope[:4]

    if container_scope is not None and not scope_matches(container_scope):
        errors.append(f"{location}.scope: does not match bundle scope")
    for index, code in enumerate(codes):
        code_location = f"{location}.codes[{index}]"
        if not isinstance(code, dict):
            errors.append(f"{code_location}: must be an object")
            continue
        _require_fields(code, ("code", "dimension", "description"), code_location, errors)
        reason_code = code.get("code")
        if not _is_nonempty_string(reason_code) or not ANTI_SLOP_REASON_CODE_PATTERN.fullmatch(reason_code):
            errors.append(f"{code_location}.code: must match uppercase reason-code format")
        for field in ("dimension", "description"):
            if not _is_nonempty_string(code.get(field)):
                errors.append(f"{code_location}.{field}: must be a non-empty string")
        if container_scope is None and not scope_matches(code.get("scope")):
            errors.append(f"{code_location}.scope: does not match bundle scope")


def _validate_anti_slop_contract(
    profile: dict[str, Any],
    record_locations: dict[str, str],
    expected_scope: tuple[Any, ...] | None,
    privileged: bool,
    errors: list[str],
) -> list[tuple[str, list[str]]]:
    """Validate additive anti-slop fields and return evidence source refs."""

    fields = _anti_slop_fields(profile, errors)
    source_refs: list[tuple[str, list[str]]] = []
    if not fields:
        if privileged:
            errors.append("brand-profile.json: anti-slop contract is required for privileged states")
        return source_refs

    for field in ANTI_SLOP_LIST_FIELDS:
        if field not in fields:
            if privileged:
                errors.append(f"brand-profile.json.{field}: required for privileged states")
            continue
        records = fields[field]
        location = f"brand-profile.json.{field}"
        if not isinstance(records, list):
            errors.append(f"{location}: must be an array")
            continue
        if privileged and not records:
            errors.append(f"{location}: must not be empty for privileged states")
        for index, record in enumerate(records):
            item_location = f"{location}[{index}]"
            valid = _validate_evidence_text_record(
                record,
                item_location,
                ANTI_SLOP_TEXT_ALIASES[field],
                record_locations,
                privileged,
                errors,
            )
            if valid and isinstance(record, dict):
                source_refs.append((item_location, _validate_string_list(record.get("source_ids"), f"{item_location}.source_ids", errors)))
                _validate_record_scope(record.get("scope"), f"{item_location}.scope", expected_scope, errors)
            if field == "distinctive_assets" and isinstance(record, dict):
                if not _is_nonempty_string(record.get("role")):
                    errors.append(f"{item_location}.role: must be a non-empty semantic role")
                rights = _validate_rights(record.get("rights"), f"{item_location}.rights", errors, required=True)
                if privileged and rights is not None and rights.get("status") not in APPROVED_RIGHTS:
                    errors.append(f"{item_location}: distinctive asset rights must be approved or exact for privileged states")

    for field, aliases in {
        "brand_stance": ("stance", "value", "description"),
        "right_to_speak": ("right", "value", "description"),
        "what_we_refuse_to_say": ("refusal", "value", "description"),
        "voice_as_behavior": ("behavior", "value", "description"),
    }.items():
        record = fields.get(field)
        location = f"brand-profile.json.{field}"
        if record is None:
            if privileged:
                errors.append(f"{location}: required for privileged states")
            continue
        if _validate_evidence_text_record(record, location, aliases, record_locations, privileged, errors) and isinstance(record, dict):
            source_refs.append((location, _validate_string_list(record.get("source_ids"), f"{location}.source_ids", errors)))
            _validate_record_scope(record.get("scope"), f"{location}.scope", expected_scope, errors)

    for field in ("locale_policy", "fake_intimacy_policy", "unsupported_first_person_policy"):
        value = fields.get(field)
        location = f"brand-profile.json.{field}"
        if value is None:
            if privileged:
                errors.append(f"{location}: required for privileged states")
            continue
        if not isinstance(value, dict):
            errors.append(f"{location}: must be an object")
            continue
        _require_fields(value, ("rule", "evidence_status", "source_ids"), location, errors)
        if not _is_nonempty_string(value.get("rule")):
            errors.append(f"{location}.rule: must be a non-empty string")
        _validate_evidence_record(value, location, errors)
        if privileged and value.get("evidence_status") not in APPROVED_EVIDENCE:
            errors.append(f"{location}: privileged policy requires exact or observed status")
        if privileged and isinstance(value.get("source_ids"), list) and not value.get("source_ids"):
            errors.append(f"{location}: privileged policy requires non-empty source_ids")
        source_refs.append((location, _validate_string_list(value.get("source_ids"), f"{location}.source_ids", errors)))

    tension = fields.get("strategic_tension")
    if tension is None:
        if privileged:
            errors.append("brand-profile.json.strategic_tension: required for privileged states")
    else:
        valid = _validate_evidence_text_record(
            tension,
            "brand-profile.json.strategic_tension",
            ("tension", "value", "description"),
            record_locations,
            privileged,
            errors,
        )
        if valid and isinstance(tension, dict):
            source_refs.append(("brand-profile.json.strategic_tension", _validate_string_list(tension.get("source_ids"), "brand-profile.json.strategic_tension.source_ids", errors)))
            _validate_record_scope(tension.get("scope"), "brand-profile.json.strategic_tension.scope", expected_scope, errors)

    voice_examples = fields.get("voice_examples")
    if voice_examples is None:
        if privileged:
            errors.append("brand-profile.json.voice_examples: required for privileged states")
    elif not isinstance(voice_examples, dict):
        errors.append("brand-profile.json.voice_examples: must be an object")
    else:
        unknown = sorted(set(voice_examples) - {"positive", "negative"})
        if unknown:
            errors.append(f"brand-profile.json.voice_examples: unknown field(s) {unknown!r}")
        for polarity in ("positive", "negative"):
            examples = voice_examples.get(polarity)
            location = f"brand-profile.json.voice_examples.{polarity}"
            if not isinstance(examples, list):
                errors.append(f"{location}: must be an array")
                continue
            if privileged and not examples:
                errors.append(f"{location}: must not be empty for privileged states")
            for index, record in enumerate(examples):
                item_location = f"{location}[{index}]"
                if _validate_evidence_text_record(record, item_location, ("example", "value", "text", "description"), record_locations, privileged, errors) and isinstance(record, dict):
                    source_refs.append((item_location, _validate_string_list(record.get("source_ids"), f"{item_location}.source_ids", errors)))
                    _validate_record_scope(record.get("scope"), f"{item_location}.scope", expected_scope, errors)

    policy = fields.get("model_usage_policy")
    if policy is None and privileged:
        errors.append("brand-profile.json.model_usage_policy: required for privileged states")
    elif policy is not None:
        _validate_anti_slop_policy(policy, "brand-profile.json.model_usage_policy", privileged, errors)

    roles = fields.get("approval_roles")
    if roles is None and privileged:
        errors.append("brand-profile.json.approval_roles: required for privileged states")
    elif roles is not None:
        _validate_approval_roles(roles, "brand-profile.json.approval_roles", privileged, errors)

    feedback = fields.get("feedback_reason_codes")
    if feedback is None and privileged:
        errors.append("brand-profile.json.feedback_reason_codes: required for privileged states")
    elif feedback is not None:
        _validate_feedback_reason_codes(feedback, "brand-profile.json.feedback_reason_codes", expected_scope, privileged, errors)

    return source_refs


def _style_profile_fields(profile: dict[str, Any], errors: list[str]) -> dict[str, Any] | None:
    """Return one additive Indonesian style profile, accepting compatibility aliases."""

    present = [(name, profile.get(name)) for name in STYLE_PROFILE_ALIASES if name in profile]
    present = [(name, value) for name, value in present if value is not None]
    if not present:
        return None
    canonical_name, canonical = present[0]
    if not isinstance(canonical, dict):
        errors.append(f"brand-profile.json.{canonical_name}: must be an object")
        return None
    for alias, value in present[1:]:
        if not isinstance(value, dict):
            errors.append(f"brand-profile.json.{alias}: must be an object")
        elif value != canonical:
            errors.append(f"brand-profile.json.{canonical_name}: conflicts with brand-profile.json.{alias}")
    return canonical


def _style_profile_value(profile: dict[str, Any], field: str) -> tuple[Any, str | None]:
    """Get a profile field and its actual key, allowing descriptive aliases."""

    for alias in STYLE_PROFILE_FIELD_ALIASES[field]:
        if alias in profile:
            return profile[alias], alias
    return None, None


def _style_profile_scalar(value: Any) -> Any:
    """Accept an evidence-wrapped scalar while keeping the compact form canonical."""

    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _style_profile_strings(value: Any, location: str, errors: list[str], required: bool = False) -> list[str]:
    """Validate a scalar-or-string-list style setting and return its values."""

    value = _style_profile_scalar(value)
    if isinstance(value, str):
        if not value.strip():
            if required:
                errors.append(f"{location}: must be a non-empty string or array")
            return []
        return [value]
    if not isinstance(value, list):
        errors.append(f"{location}: must be a string or array of strings")
        return []
    result: list[str] = []
    for index, item in enumerate(value):
        if not _is_nonempty_string(item):
            errors.append(f"{location}[{index}]: must be a non-empty string")
        else:
            result.append(item)
    if required and not result:
        errors.append(f"{location}: must not be empty")
    return result


def _style_policy_evidence(
    value: Any,
    location: str,
    privileged: bool,
    errors: list[str],
    required: bool = False,
) -> list[str]:
    """Validate evidence metadata attached to a style policy."""

    if not isinstance(value, dict):
        if required:
            errors.append(f"{location}: must be an object")
        return []
    if required:
        _require_fields(value, ("evidence_status", "source_ids"), location, errors)
    if "evidence_status" in value:
        status = value.get("evidence_status")
        if status not in ALLOWED_EVIDENCE:
            errors.append(f"{location}.evidence_status: invalid value {status!r}")
        elif privileged and status not in APPROVED_EVIDENCE:
            errors.append(f"{location}: privileged style evidence requires exact or observed status")
    refs: list[str] = []
    if "source_ids" in value:
        refs = _validate_string_list(value.get("source_ids"), f"{location}.source_ids", errors)
        if privileged and not refs:
            errors.append(f"{location}: privileged style evidence requires non-empty source_ids")
    return refs


def _style_record_evidence(
    value: dict[str, Any],
    location: str,
    privileged: bool,
    errors: list[str],
    require_text: bool = False,
) -> list[str]:
    """Validate a nested style record's evidence and optional example text."""

    if require_text and not any(_is_nonempty_string(value.get(key)) for key in ("example", "text", "value", "description")):
        errors.append(f"{location}: requires a non-empty example")
    refs = _style_policy_evidence(value, location, privileged, errors, required=privileged)
    return refs


def _validate_style_profile(
    style: dict[str, Any] | None,
    location: str,
    privileged: bool,
    colloquial: bool,
    errors: list[str],
) -> list[tuple[str, list[str]]]:
    """Validate the additive Indonesian register profile.

    Draft profiles are intentionally allowed to be incomplete.  Once a profile
    participates in an active/approved state, every register decision is
    explicit and evidence-backed; colloquial/community profiles additionally
    require the anti-cosmetic particle and example safeguards.
    """

    if style is None:
        return []
    source_refs: list[tuple[str, list[str]]] = []
    allowed_fields = {
        *STYLE_PROFILE_REQUIRED_FIELDS,
        "evidence_status",
        "source_ids",
        "notes",
        "no_forced_slang",
        "style_register",
        "region_community",
        "pronoun_address_policy",
        "code_switching_policy",
        "spelling_policy",
        "human_examples",
        "register_basis",
    }
    unknown = sorted(set(style) - allowed_fields)
    if unknown:
        errors.append(f"{location}: unknown field(s) {unknown!r}")

    profile_refs = _style_policy_evidence(style, location, privileged, errors, required=privileged)
    if "evidence_status" in style or "source_ids" in style:
        source_refs.append((location, profile_refs))

    values: dict[str, Any] = {}
    for field in STYLE_PROFILE_REQUIRED_FIELDS:
        value, actual_key = _style_profile_value(style, field)
        if actual_key is None:
            if privileged:
                errors.append(f"{location}.{field}: required for privileged style output")
            continue
        field_location = f"{location}.{actual_key}"
        values[field] = value
        if field in {"channel", "register", "audience_relation", "region_or_community"}:
            required_value = privileged
            strings = _style_profile_strings(value, field_location, errors, required=required_value)
            if field == "channel":
                unknown_channels = sorted(set(strings) - STYLE_PROFILE_CHANNELS)
                if unknown_channels:
                    errors.append(f"{field_location}: unsupported channel(s) {unknown_channels!r}")
            elif field == "register":
                unknown_registers = sorted(set(strings) - STYLE_PROFILE_REGISTERS)
                if unknown_registers:
                    errors.append(f"{field_location}: unsupported register(s) {unknown_registers!r}")
            elif field == "audience_relation":
                unknown_relations = sorted(set(strings) - STYLE_PROFILE_RELATIONS)
                if unknown_relations:
                    errors.append(f"{field_location}: unsupported audience relation(s) {unknown_relations!r}")
            continue
        if field == "approved_human_examples":
            if not isinstance(value, list):
                errors.append(f"{field_location}: must be an array")
                continue
            if privileged and not value:
                errors.append(f"{field_location}: must not be empty for privileged style output")
            for index, example in enumerate(value):
                example_location = f"{field_location}[{index}]"
                if not isinstance(example, dict):
                    errors.append(f"{example_location}: must be an object")
                    continue
                if privileged and not _is_nonempty_string(example.get("id")):
                    errors.append(f"{example_location}.id: must be a non-empty string")
                refs = _style_record_evidence(example, example_location, privileged, errors, require_text=True)
                if privileged:
                    for key in ("channel", "register", "audience_relation", "region_or_community"):
                        if not _is_nonempty_string(example.get(key)):
                            errors.append(f"{example_location}.{key}: required for privileged human example")
                source_refs.append((example_location, refs))
            continue
        policy = value
        policy_location = field_location
        if not isinstance(policy, dict):
            errors.append(f"{policy_location}: must be an object")
            continue
        unknown_policy_fields = sorted(set(policy) - STYLE_PROFILE_POLICY_KEYS.get(field, set()))
        if unknown_policy_fields:
            errors.append(f"{policy_location}: unknown field(s) {unknown_policy_fields!r}")
        refs = _style_policy_evidence(policy, policy_location, privileged, errors, required=privileged)
        source_refs.append((policy_location, refs))

        if field == "pronoun_policy":
            approved = next((policy[key] for key in ("approved", "approved_forms", "approved_pronouns") if key in policy), None)
            avoid = next((policy[key] for key in ("avoid", "prohibited", "disallowed") if key in policy), None)
            if privileged:
                _style_profile_strings(approved, f"{policy_location}.approved", errors, required=colloquial)
                _style_profile_strings(avoid, f"{policy_location}.avoid", errors, required=False)
        elif field == "particle_policy":
            particles = next((policy[key] for key in ("approved", "allowed", "particles") if key in policy), None)
            if not isinstance(particles, list):
                errors.append(f"{policy_location}.approved: must be an array")
                particles = []
            no_forced_slang = policy.get("no_forced_slang")
            if privileged and no_forced_slang is not True:
                errors.append(f"{policy_location}.no_forced_slang: must be true for privileged style output")
            for index, particle in enumerate(particles):
                particle_location = f"{policy_location}.approved[{index}]"
                if isinstance(particle, str):
                    if privileged:
                        errors.append(f"{particle_location}: must be an object with speech_act, function, and approved_examples")
                    continue
                if not isinstance(particle, dict):
                    errors.append(f"{particle_location}: must be an object")
                    continue
                if privileged and not _is_nonempty_string(particle.get("particle")):
                    errors.append(f"{particle_location}.particle: must be a non-empty string")
                speech_acts = particle.get("speech_acts", particle.get("speech_act"))
                if privileged and not _style_profile_strings(speech_acts, f"{particle_location}.speech_act", errors, required=True):
                    pass
                if privileged and not _is_nonempty_string(particle.get("function")):
                    errors.append(f"{particle_location}.function: must be a non-empty string")
                examples = particle.get("approved_examples", particle.get("examples"))
                if not isinstance(examples, list) or not examples:
                    if privileged:
                        errors.append(f"{particle_location}.approved_examples: must be a non-empty array")
                refs = _style_record_evidence(particle, particle_location, privileged, errors)
                source_refs.append((particle_location, refs))
                if isinstance(examples, list):
                    for example_index, example in enumerate(examples):
                        if not _is_nonempty_string(example) and not isinstance(example, dict):
                            errors.append(f"{particle_location}.approved_examples[{example_index}]: must be text or object")
            continue
        if field == "code_switch_policy":
            allowed_terms = policy.get("allowed_terms", policy.get("approved_terms", policy.get("allowed")))
            do_not_translate = policy.get("do_not_translate", policy.get("do_not_translate_terms"))
            if not isinstance(allowed_terms, list):
                errors.append(f"{policy_location}.allowed_terms: must be an array")
            if not isinstance(do_not_translate, list):
                errors.append(f"{policy_location}.do_not_translate: must be an array")
            if privileged:
                for key, items in (("allowed_terms", allowed_terms), ("do_not_translate", do_not_translate)):
                    if isinstance(items, list) and not items:
                        # An empty list is explicit: no approved switch/term.
                        continue
                    if isinstance(items, list):
                        for index, item in enumerate(items):
                            item_location = f"{policy_location}.{key}[{index}]"
                            if isinstance(item, str):
                                errors.append(f"{item_location}: must be an evidence-backed object with a reason")
                            elif not isinstance(item, dict):
                                errors.append(f"{item_location}: must be an object")
                            elif not _is_nonempty_string(item.get("term")):
                                errors.append(f"{item_location}.term: must be a non-empty string")
                            elif not _is_nonempty_string(item.get("reason")):
                                errors.append(f"{item_location}.reason: must be a non-empty string")
                            elif isinstance(item, dict):
                                item_refs = _style_record_evidence(item, item_location, privileged, errors)
                                source_refs.append((item_location, item_refs))
                if not isinstance(policy.get("translate_surrounding_syntax"), bool):
                    errors.append(f"{policy_location}.translate_surrounding_syntax: must be boolean")
            continue
        if field == "contraction_spelling_policy":
            for key in ("approved_forms", "contractions", "approved", "standard_forms", "standard", "prohibited_forms", "do_not_use", "rules"):
                if key in policy and not isinstance(policy[key], list):
                    errors.append(f"{policy_location}.{key}: must be an array")
            if privileged and not any(key in policy for key in ("default_spelling", "rules", "approved_forms", "standard_forms", "standard")):
                errors.append(f"{policy_location}: requires an explicit default_spelling or spelling rules")
            if privileged and "default_spelling" in policy and not _is_nonempty_string(policy.get("default_spelling")):
                errors.append(f"{policy_location}.default_spelling: must be a non-empty string")

    if privileged and colloquial:
        # A colloquial profile must prove the relationship it is asking the
        # model to perform; a particle list alone is never enough.
        approved_pronouns = values.get("pronoun_policy")
        if isinstance(approved_pronouns, dict):
            forms = approved_pronouns.get("approved", approved_pronouns.get("approved_forms"))
            if not _style_profile_strings(forms, f"{location}.pronoun_policy.approved", errors, required=True):
                pass
    return source_refs


def _style_profile_is_colloquial(style: dict[str, Any] | None) -> bool:
    """Return whether a declared profile needs community/colloquial safeguards."""

    if not isinstance(style, dict):
        return False
    register, _ = _style_profile_value(style, "register")
    registers = _style_profile_strings(register, "brand-profile.json.id_style_profile.register", [], required=False)
    return bool(set(registers) & STYLE_PROFILE_COLLOQUIAL_REGISTERS)


def _style_profile_observation_records(style: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Flatten nested style records so observe mode cannot promote exact data."""

    records: list[tuple[str, dict[str, Any]]] = [("brand-profile.json.id_style_profile", style)]
    for field in STYLE_PROFILE_REQUIRED_FIELDS:
        value, actual_key = _style_profile_value(style, field)
        if not isinstance(value, dict) or actual_key is None:
            continue
        policy_location = f"brand-profile.json.id_style_profile.{actual_key}"
        records.append((policy_location, value))
        if field == "particle_policy":
            particles = next((value[key] for key in ("approved", "allowed", "particles") if key in value), [])
            if isinstance(particles, list):
                for index, particle in enumerate(particles):
                    if isinstance(particle, dict):
                        records.append((f"{policy_location}.approved[{index}]", particle))
        elif field == "code_switch_policy":
            for key in ("allowed_terms", "approved_terms", "allowed", "do_not_translate", "do_not_translate_terms"):
                terms = value.get(key)
                if isinstance(terms, list):
                    records.extend(
                        (f"{policy_location}.{key}[{index}]", term)
                        for index, term in enumerate(terms)
                        if isinstance(term, dict)
                    )
        elif field == "approved_human_examples" and isinstance(value, list):
            records.extend(
                (f"{policy_location}[{index}]", example)
                for index, example in enumerate(value)
                if isinstance(example, dict)
            )
    return records


def _load_json(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"missing required file: {path.name}")
        return None
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{path.name}: cannot read JSON ({exc})")
        return None
    if not isinstance(value, dict):
        errors.append(f"{path.name}: top-level value must be an object")
        return None
    return value


def _validate_id(value: Any, location: str, errors: list[str]) -> bool:
    if not _is_nonempty_string(value):
        errors.append(f"{location}: must be a non-empty string")
        return False
    if not SAFE_ID_PATTERN.fullmatch(value):
        errors.append(f"{location}: must match lowercase-kebab format")
        return False
    return True


def _collect_record_id(record: dict[str, Any], location: str, record_locations: dict[str, str], errors: list[str]) -> str | None:
    record_id = record.get("id")
    if not _validate_id(record_id, f"{location}.id", errors):
        return None
    if record_id in record_locations:
        errors.append(f"{location}.id: duplicate record ID {record_id!r} (first at {record_locations[record_id]})")
    else:
        record_locations[record_id] = location
    return record_id


def _validate_profile_record(record: Any, location: str, record_locations: dict[str, str], errors: list[str]) -> None:
    if not isinstance(record, dict):
        errors.append(f"{location}: must be an object")
        return
    _collect_record_id(record, location, record_locations, errors)
    _require_fields(record, ("id", "value"), location, errors)
    _validate_evidence_record(record, location, errors)


def _validate_string_list(value: Any, location: str, errors: list[str], required: bool = True) -> list[str]:
    if value is None and not required:
        return []
    if not isinstance(value, list):
        errors.append(f"{location}: must be an array")
        return []
    result: list[str] = []
    for index, item in enumerate(value):
        if _validate_id(item, f"{location}[{index}]", errors):
            result.append(item)
    return result


def _scope_value(document: dict[str, Any], field: str) -> Any:
    """Return a normalized scoped value for cross-file comparisons."""

    scope = document.get("scope")
    if not isinstance(scope, dict):
        return None
    value = scope.get(field)
    # Null and omission both mean "master/no product" for optional fields.
    if field in {"product_id", "parent_brand_revision"} and value is None:
        return ""
    return value


def _validate_revision(value: Any, location: str, errors: list[str], required: bool = True) -> bool:
    if not _is_nonempty_string(value):
        if required:
            errors.append(f"{location}: must be a non-empty string")
        return False
    match = REVISION_PATTERN.fullmatch(value)
    if not match:
        errors.append(f"{location}: must match UTC timestamp-rN format")
        return False
    try:
        dt.datetime.strptime(match.group(1), "%Y-%m-%dT%H%M%SZ")
    except ValueError:
        errors.append(f"{location}: timestamp is not a valid UTC date/time")
        return False
    return True


def _load_policy(value: TrustedAccessPolicyContext | dict[str, Any] | str | Path | None, errors: list[str]) -> dict[str, Any] | None:
    """Load a trusted local policy object supplied out-of-band by the caller."""

    if value is None:
        return None
    if isinstance(value, TrustedAccessPolicyContext):
        policy = value.as_mapping()
        _record_errors(policy, "policy", errors)
        return policy
    if isinstance(value, dict):
        errors.append("policy: raw mappings are not accepted; load a TrustedAccessPolicyContext from an external file")
        return None
    if isinstance(value, (str, Path)):
        path = _path(value)
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            errors.append(f"policy: file not found: {path}")
            return None
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"policy: cannot read JSON ({exc})")
            return None
        if not isinstance(loaded, dict):
            errors.append("policy: top-level value must be an object")
            return None
        _record_errors(loaded, "policy", errors)
        return loaded
    errors.append("policy: must be an object or JSON file path")
    return None


def _validate_policy(policy: dict[str, Any] | None, errors: list[str]) -> dict[str, Any] | None:
    """Validate the external local access-policy contract."""

    if policy is None:
        return None
    location = "policy"
    unknown_policy_fields = sorted(set(policy) - {"schema_version", "policy_id", "revision", "source", "scope", "role_mapping"})
    if unknown_policy_fields:
        errors.append(f"{location}: unknown field(s) {unknown_policy_fields!r}")
    _require_fields(policy, ("schema_version", "policy_id", "revision", "source", "scope", "role_mapping"), location, errors)
    if policy.get("schema_version") != POLICY_SCHEMA_VERSION:
        errors.append(f"{location}.schema_version: expected {POLICY_SCHEMA_VERSION!r}")
    if not _validate_id(policy.get("policy_id"), f"{location}.policy_id", errors):
        pass
    _validate_revision(policy.get("revision"), f"{location}.revision", errors)
    if policy.get("source") != "local_authenticated_policy":
        errors.append(f"{location}.source: must be 'local_authenticated_policy'")

    scope = policy.get("scope")
    if not isinstance(scope, dict):
        errors.append(f"{location}.scope: must be an object")
    else:
        unknown = sorted(set(scope) - set(POLICY_SCOPE_FIELDS))
        missing = sorted(set(POLICY_SCOPE_FIELDS) - set(scope))
        if unknown:
            errors.append(f"{location}.scope: unknown field(s) {unknown!r}")
        if missing:
            errors.append(f"{location}.scope: missing field(s) {missing!r}")
        for field in ("tenant_id", "client_id", "brand_id"):
            if not _validate_id(scope.get(field), f"{location}.scope.{field}", errors):
                pass
        product_id = scope.get("product_id")
        if product_id is not None and not _validate_id(product_id, f"{location}.scope.product_id", errors):
            pass

    role_mapping = policy.get("role_mapping")
    if not isinstance(role_mapping, dict):
        errors.append(f"{location}.role_mapping: must be an object")
    else:
        unknown_roles = sorted(set(role_mapping) - set(POLICY_ROLES))
        if unknown_roles:
            errors.append(f"{location}.role_mapping: unknown role(s) {unknown_roles!r}")
        for role in POLICY_ROLES:
            if role not in role_mapping:
                continue
            identities = role_mapping[role]
            if not isinstance(identities, list):
                errors.append(f"{location}.role_mapping.{role}: must be an array")
                continue
            for index, identity in enumerate(identities):
                identity_location = f"{location}.role_mapping.{role}[{index}]"
                if identity in WILDCARD_IDENTITIES:
                    errors.append(f"{identity_location}: wildcard identities are not allowed")
                    continue
                if not _validate_id(identity, identity_location, errors):
                    continue
    return policy


def _policy_matches_scope(policy: dict[str, Any] | None, common_scope: tuple[Any, ...] | None) -> bool:
    if not isinstance(policy, dict) or not isinstance(common_scope, tuple) or len(common_scope) < 4:
        return False
    scope = policy.get("scope")
    if not isinstance(scope, dict):
        return False
    return (
        scope.get("brand_id"),
        scope.get("tenant_id"),
        scope.get("client_id"),
        scope.get("product_id") or "",
    ) == common_scope[:4]


def _policy_actor_matches(policy: dict[str, Any] | None, actor_id: Any, role: Any) -> bool:
    if not isinstance(policy, dict) or not _is_nonempty_string(actor_id) or role not in POLICY_ROLES:
        return False
    role_mapping = policy.get("role_mapping")
    return isinstance(role_mapping, dict) and actor_id in role_mapping.get(role, [])


def _validate_privileged_authority(
    authorization: Any,
    policy: dict[str, Any] | None,
    common_scope: tuple[Any, ...] | None,
    schema_version: Any,
    runtime_actor_id: str | None,
    errors: list[str],
) -> bool:
    """Require the external policy to corroborate the mutable audit receipt."""

    valid = True
    if policy is None:
        errors.append("privileged approval/activation requires external trusted local access policy")
        return False
    if not _is_nonempty_string(runtime_actor_id):
        errors.append("privileged approval/activation requires trusted runtime actor_id")
        return False
    if schema_version != SCOPED_SCHEMA_VERSION:
        errors.append("privileged approval/activation requires scoped schema_version '1.1'")
        valid = False
    if not _policy_matches_scope(policy, common_scope):
        errors.append("external access policy scope does not match bundle scope")
        valid = False
    if not isinstance(authorization, dict):
        errors.append("privileged approval/activation requires provenance authorization receipt")
        return False
    actor_id = authorization.get("actor_id")
    role = authorization.get("role")
    if not _is_nonempty_string(actor_id):
        errors.append("privileged approval/activation requires authorization.actor_id")
        valid = False
    if role not in APPROVED_ROLES:
        errors.append("privileged approval/activation requires lead or admin role")
        valid = False
    if actor_id != runtime_actor_id:
        errors.append("runtime actor_id does not match authorization receipt actor_id")
        valid = False
    if not _policy_actor_matches(policy, runtime_actor_id, role):
        errors.append("authorization actor_id and role are not mapped by external access policy")
        valid = False
    if authorization.get("status") not in APPROVED_RIGHTS:
        errors.append("authorization receipt requires status approved or exact")
        valid = False
    if authorization.get("verified") is not True:
        errors.append("authorization receipt requires verified true")
        valid = False
    if authorization.get("policy_source") != "local_authenticated_policy":
        errors.append("authorization receipt requires local authenticated policy source")
        valid = False
    if authorization.get("policy_id") != policy.get("policy_id"):
        errors.append("authorization receipt policy_id does not match external access policy")
        valid = False
    if authorization.get("policy_revision") != policy.get("revision"):
        errors.append("authorization receipt policy_revision does not match external access policy")
        valid = False
    return valid


def _validate_scope(document: dict[str, Any], filename: str, schema_version: Any, errors: list[str]) -> tuple[Any, ...]:
    """Validate the scoped namespace and return values used for equality checks."""

    brand_id = document.get("brand_id")
    if not _is_nonempty_string(brand_id):
        errors.append(f"{filename}.brand_id: must be a non-empty string")
    elif not SAFE_ID_PATTERN.fullmatch(brand_id):
        errors.append(f"{filename}.brand_id: must match lowercase-kebab format")

    if schema_version == "1.0":
        if "scope" in document:
            errors.append(f"{filename}.scope: legacy schema 1.0 must omit scope")
        for field in SCOPE_FIELDS:
            if field in document:
                errors.append(f"{filename}.{field}: legacy schema 1.0 must omit scoped fields")
        return (brand_id, "", "", "", "")

    scope = document.get("scope")
    if not isinstance(scope, dict):
        errors.append(f"{filename}.scope: must be an object for schema 1.1")
        return (brand_id, None, None, None, None)

    unknown_scope_fields = sorted(set(scope) - set(SCOPE_FIELDS))
    if unknown_scope_fields:
        errors.append(f"{filename}.scope: unknown field(s) {unknown_scope_fields!r}")

    for field in ("tenant_id", "client_id"):
        value = scope.get(field)
        if not _is_nonempty_string(value):
            errors.append(f"{filename}.scope.{field}: must be a non-empty string")
        elif not SAFE_ID_PATTERN.fullmatch(value):
            errors.append(f"{filename}.scope.{field}: must match lowercase-kebab format")

    product_id = scope.get("product_id")
    if product_id not in (None, ""):
        if not _is_nonempty_string(product_id) or not SAFE_ID_PATTERN.fullmatch(product_id):
            errors.append(f"{filename}.scope.product_id: must match lowercase-kebab format")
        parent_revision = scope.get("parent_brand_revision")
        if not _validate_revision(parent_revision, f"{filename}.scope.parent_brand_revision", errors):
            parent_revision = None
    else:
        product_id = ""
        parent_revision = scope.get("parent_brand_revision")
        if parent_revision not in (None, ""):
            errors.append(f"{filename}.scope.parent_brand_revision: requires scope.product_id")
        parent_revision = ""

    # A product overlay's parent brand is the top-level brand_id. The parent
    # revision is required so consumers cannot accidentally merge another brand.
    return (brand_id, _scope_value(document, "tenant_id"), _scope_value(document, "client_id"), product_id, parent_revision)


def validate_brand_bundle(
    directory: str | Path,
    expected_brand_id: str | None = None,
    expected_scope: dict[str, Any] | None = None,
    policy: TrustedAccessPolicyContext | dict[str, Any] | str | Path | None = None,
    actor_id: str | None = None,
) -> list[str]:
    """Return deterministic validation errors; an empty list means valid."""

    root = _path(directory)
    errors: list[str] = []
    if not root.is_dir():
        return [f"not a directory: {root}"]

    docs: dict[str, dict[str, Any]] = {}
    for filename in REQUIRED_FILES:
        document = _load_json(root / filename, errors)
        if document is not None:
            docs[filename] = document
            _record_errors(document, filename, errors)
    if len(docs) != len(REQUIRED_FILES):
        return sorted(set(errors))

    external_policy = _validate_policy(_load_policy(policy, errors), errors)

    envelope: tuple[str, ...] = ("schema_version", "brand_id", "revision", "status")
    schema_versions: list[Any] = []
    scope_values: dict[str, tuple[Any, ...]] = {}
    for filename, document in docs.items():
        _require_fields(document, envelope, filename, errors)
        schema_version = document.get("schema_version")
        if not any(existing == schema_version for existing in schema_versions):
            schema_versions.append(schema_version)
        if not isinstance(schema_version, str) or schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            errors.append(f"{filename}.schema_version: expected '1.0' or '1.1'")
        scope_values[filename] = _validate_scope(document, filename, schema_version, errors)
        revision = document.get("revision")
        _validate_revision(revision, f"{filename}.revision", errors)
        if document.get("status") not in ALLOWED_STATUS:
            errors.append(f"{filename}.status: invalid value {document.get('status')!r}")

    common = {field: docs[REQUIRED_FILES[0]].get(field) for field in envelope}
    for filename, document in docs.items():
        for field, expected in common.items():
            if document.get(field) != expected:
                errors.append(f"{filename}.{field}: does not match bundle envelope ({expected!r})")
    if len(schema_versions) != 1:
        errors.append("bundle.schema_version: all four files must use the same schema version")
    common_scope = scope_values.get(REQUIRED_FILES[0])
    for filename, values in scope_values.items():
        if common_scope is not None and values != common_scope:
            errors.append(f"{filename}.scope: does not match bundle scope")
    if expected_brand_id is not None and common["brand_id"] != expected_brand_id:
        errors.append(f"brand_id: expected {expected_brand_id!r}, got {common['brand_id']!r}")
    if expected_scope is not None and common_scope is not None:
        expected_values = (
            common["brand_id"],
            expected_scope.get("tenant_id", ""),
            expected_scope.get("client_id", ""),
            expected_scope.get("product_id") or "",
            expected_scope.get("parent_brand_revision") or "",
        )
        if common_scope != expected_values:
            errors.append(f"scope: expected {expected_scope!r}, got {common_scope!r}")

    record_locations: dict[str, str] = {}
    profile = docs["brand-profile.json"]
    for field in ("identity", "audience", "rights"):
        if field not in profile or not isinstance(profile[field], dict):
            errors.append(f"brand-profile.json.{field}: must be an object")
    profile_arrays = ("voice", "terminology", "copy_constraints", "visual_copy_cues", "gaps")
    for field in profile_arrays:
        records = profile.get(field)
        if not isinstance(records, list):
            errors.append(f"brand-profile.json.{field}: must be an array")
            continue
        for index, record in enumerate(records):
            location = f"brand-profile.json.{field}[{index}]"
            if field == "gaps":
                if isinstance(record, str):
                    continue
                if not isinstance(record, dict):
                    errors.append(f"{location}: must be a string or object")
                    continue
                _collect_record_id(record, location, record_locations, errors)
                _require_fields(record, ("id", "reason"), location, errors)
                _validate_evidence_record(record, location, errors)
            else:
                _validate_profile_record(record, location, record_locations, errors)

    claims = docs["claim-registry.json"].get("claims")
    if not isinstance(claims, list):
        errors.append("claim-registry.json.claims: must be an array")
        claims = []
    claim_ids: set[str] = set()
    for index, record in enumerate(claims):
        location = f"claim-registry.json.claims[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{location}: must be an object")
            continue
        claim_id = _collect_record_id(record, location, record_locations, errors)
        if claim_id is not None:
            claim_ids.add(claim_id)
        _require_fields(record, ("id", "claim", "status"), location, errors)
        if not _is_nonempty_string(record.get("claim")):
            errors.append(f"{location}.claim: must be a non-empty string")
        _validate_evidence_record(record, location, errors)
        if record.get("status") not in ALLOWED_CLAIM_STATUS:
            errors.append(f"{location}.status: invalid value {record.get('status')!r}")
        _validate_rights(record.get("rights"), f"{location}.rights", errors)
        _validate_record_scope(record.get("scope"), f"{location}.scope", common_scope, errors)
        _validate_approved_record(record, location, errors)

    templates = docs["template-registry.json"].get("templates")
    if not isinstance(templates, list):
        errors.append("template-registry.json.templates: must be an array")
        templates = []
    template_claim_refs: list[tuple[str, list[str]]] = []
    for index, record in enumerate(templates):
        location = f"template-registry.json.templates[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{location}: must be an object")
            continue
        _collect_record_id(record, location, record_locations, errors)
        _require_fields(record, ("id", "name", "purpose", "channel", "slots", "claim_ids", "status"), location, errors)
        for field in ("name", "purpose", "channel"):
            if not _is_nonempty_string(record.get(field)):
                errors.append(f"{location}.{field}: must be a non-empty string")
        _validate_evidence_record(record, location, errors)
        if record.get("status") not in ALLOWED_CLAIM_STATUS:
            errors.append(f"{location}.status: invalid value {record.get('status')!r}")
        slots = record.get("slots")
        if not isinstance(slots, list):
            errors.append(f"{location}.slots: must be an array")
        else:
            for slot_index, slot in enumerate(slots):
                slot_location = f"{location}.slots[{slot_index}]"
                if not isinstance(slot, dict):
                    errors.append(f"{slot_location}: must be an object")
                    continue
                _require_fields(slot, ("name", "type", "required"), slot_location, errors)
                for field in ("name", "type"):
                    if not _is_nonempty_string(slot.get(field)):
                        errors.append(f"{slot_location}.{field}: must be a non-empty string")
                if not isinstance(slot.get("required"), bool):
                    errors.append(f"{slot_location}.required: must be boolean")
        claim_refs = _validate_string_list(record.get("claim_ids"), f"{location}.claim_ids", errors)
        template_claim_refs.append((location, claim_refs))
        _validate_rights(record.get("rights"), f"{location}.rights", errors)
        _validate_record_scope(record.get("scope"), f"{location}.scope", common_scope, errors)
        _validate_approved_record(record, location, errors)

    provenance = docs["provenance.json"]
    sources = provenance.get("sources")
    evidence_ledger = provenance.get("evidence_ledger")
    if not isinstance(sources, list):
        errors.append("provenance.json.sources: must be an array")
        sources = []
    if not isinstance(evidence_ledger, list):
        errors.append("provenance.json.evidence_ledger: must be an array")
        evidence_ledger = []

    source_locations: dict[str, str] = {}
    for index, source in enumerate(sources):
        location = f"provenance.json.sources[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{location}: must be an object")
            continue
        source_id = source.get("source_id")
        if _validate_id(source_id, f"{location}.source_id", errors):
            if source_id in source_locations:
                errors.append(f"{location}.source_id: duplicate source ID {source_id!r} (first at {source_locations[source_id]})")
            else:
                source_locations[source_id] = location
        _require_fields(source, ("source_id", "kind", "locator", "authorization", "captured_at"), location, errors)
        for field in ("kind", "locator", "captured_at"):
            if not _is_nonempty_string(source.get(field)):
                errors.append(f"{location}.{field}: must be a non-empty string")
        _validate_rights(source.get("authorization"), f"{location}.authorization", errors, required=True)
        _validate_record_scope(source.get("scope"), f"{location}.scope", common_scope, errors)

    ledger_record_refs: list[tuple[str, str | None, list[str]]] = []
    for index, entry in enumerate(evidence_ledger):
        location = f"provenance.json.evidence_ledger[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{location}: must be an object")
            continue
        record_id = entry.get("record_id")
        if not _validate_id(record_id, f"{location}.record_id", errors):
            record_id = None
        _require_fields(entry, ("record_id", "source_ids", "evidence_status"), location, errors)
        _validate_evidence_record(entry, location, errors)
        ledger_record_refs.append((location, record_id, _validate_string_list(entry.get("source_ids"), f"{location}.source_ids", errors)))

    authorization = _validate_rights(provenance.get("authorization"), "provenance.json.authorization", errors, required=True)
    update = provenance.get("update")
    update_operation: Any = None
    if not isinstance(update, dict):
        errors.append("provenance.json.update: must be an object")
    else:
        _require_fields(update, ("operation",), "provenance.json.update", errors)
        update_operation = update.get("operation")
        if not _is_nonempty_string(update_operation):
            errors.append("provenance.json.update.operation: must be a non-empty string")

    source_ids = set(source_locations)
    source_authorization_status = {
        source.get("source_id"): (source.get("authorization") or {}).get("status")
        for source in sources
        if isinstance(source, dict)
    }
    profile_source_refs: list[tuple[str, list[str]]] = []
    for field in ("voice", "terminology", "copy_constraints", "visual_copy_cues", "gaps"):
        records = profile.get(field, [])
        if isinstance(records, list):
            for index, record in enumerate(records):
                if isinstance(record, dict):
                    profile_source_refs.append((f"brand-profile.json.{field}[{index}]", _validate_string_list(record.get("source_ids"), f"brand-profile.json.{field}[{index}].source_ids", errors)))
    approved_registry_records = [
        (registry_name, index, record)
        for registry_name, records in (
            ("claim-registry.json", claims),
            ("template-registry.json", templates),
        )
        for index, record in enumerate(records)
        if isinstance(record, dict) and record.get("status") == "approved"
    ]
    needs_privileged_authority = common["status"] == "active" or bool(approved_registry_records)
    profile_source_refs.extend(
        _validate_anti_slop_contract(
            profile,
            record_locations,
            common_scope,
            needs_privileged_authority,
            errors,
        )
    )
    style_profile = _style_profile_fields(profile, errors)
    style_profile_colloquial = _style_profile_is_colloquial(style_profile)
    # A declared profile in an active/approved bundle is privileged even when
    # its register is incomplete.  Treat an unknown register as unsafe rather
    # than silently emitting community-specific language.
    style_profile_privileged = needs_privileged_authority and style_profile is not None
    if style_profile_privileged and not style_profile_colloquial:
        register_value, _ = _style_profile_value(style_profile or {}, "register")
        register_values = _style_profile_strings(register_value, "brand-profile.json.id_style_profile.register", [], required=False)
        if not register_values or not (set(register_values) & STYLE_PROFILE_REGISTERS):
            style_profile_colloquial = True
    profile_source_refs.extend(
        _validate_style_profile(
            style_profile,
            "brand-profile.json.id_style_profile",
            style_profile_privileged,
            style_profile_colloquial,
            errors,
        )
    )
    claim_source_refs = [(f"claim-registry.json.claims[{index}]", _validate_string_list(record.get("source_ids"), f"claim-registry.json.claims[{index}].source_ids", errors)) for index, record in enumerate(claims) if isinstance(record, dict)]
    template_source_refs = [(f"template-registry.json.templates[{index}]", _validate_string_list(record.get("source_ids"), f"template-registry.json.templates[{index}].source_ids", errors)) for index, record in enumerate(templates) if isinstance(record, dict)]
    for location, refs in profile_source_refs + claim_source_refs + template_source_refs:
        for source_id in refs:
            if source_id not in source_ids:
                errors.append(f"{location}.source_ids: unknown source ID {source_id!r}")
            elif needs_privileged_authority and source_authorization_status.get(source_id) not in APPROVED_RIGHTS:
                errors.append(f"{location}.source_ids: privileged evidence requires authorized source {source_id!r}")
    for location, record_id, refs in ledger_record_refs:
        if record_id is not None and record_id not in record_locations:
            errors.append(f"{location}.record_id: unknown record ID {record_id!r}")
        for source_id in refs:
            if source_id not in source_ids:
                errors.append(f"{location}.source_ids: unknown source ID {source_id!r}")
    for location, refs in template_claim_refs:
        for claim_id in refs:
            if claim_id not in claim_ids:
                errors.append(f"{location}.claim_ids: unknown claim ID {claim_id!r}")

    if update_operation == "observe":
        # Public observation is intentionally useful without login or prior
        # ownership proof, but it can only produce a non-active draft. Visible
        # patterns stay observed/inferred/unverified until a later authorized
        # capture/refresh clears them with authoritative evidence.
        if common["status"] != "draft":
            errors.append("observe operation may only create a draft bundle")
        profile_rights = profile.get("rights")
        if isinstance(profile_rights, dict) and profile_rights.get("status") in APPROVED_RIGHTS:
            errors.append("observe operation cannot mark profile rights approved before owner approval")
        observed_records: list[tuple[str, dict[str, Any]]] = []
        for field in ("voice", "terminology", "copy_constraints", "visual_copy_cues"):
            records = profile.get(field, [])
            if isinstance(records, list):
                observed_records.extend(
                    (f"brand-profile.json.{field}[{index}]", record)
                    for index, record in enumerate(records)
                    if isinstance(record, dict)
                )
        observed_records.extend(
            (f"claim-registry.json.claims[{index}]", record)
            for index, record in enumerate(claims)
            if isinstance(record, dict)
        )
        observed_records.extend(
            (f"template-registry.json.templates[{index}]", record)
            for index, record in enumerate(templates)
            if isinstance(record, dict)
        )
        anti_slop_fields = _anti_slop_fields(profile, errors)
        for field in ANTI_SLOP_LIST_FIELDS:
            records = anti_slop_fields.get(field, [])
            if isinstance(records, list):
                observed_records.extend(
                    (f"brand-profile.json.{field}[{index}]", record)
                    for index, record in enumerate(records)
                    if isinstance(record, dict)
                )
        tension = anti_slop_fields.get("strategic_tension")
        if isinstance(tension, dict):
            observed_records.append(("brand-profile.json.strategic_tension", tension))
        voice_examples = anti_slop_fields.get("voice_examples")
        if isinstance(voice_examples, dict):
            for polarity in ("positive", "negative"):
                records = voice_examples.get(polarity, [])
                if isinstance(records, list):
                    observed_records.extend(
                        (f"brand-profile.json.voice_examples.{polarity}[{index}]", record)
                        for index, record in enumerate(records)
                        if isinstance(record, dict)
                    )
        for field in (
            "brand_stance",
            "right_to_speak",
            "what_we_refuse_to_say",
            "voice_as_behavior",
            "locale_policy",
            "fake_intimacy_policy",
            "unsupported_first_person_policy",
        ):
            record = anti_slop_fields.get(field)
            if isinstance(record, dict):
                observed_records.append((f"brand-profile.json.{field}", record))
        if isinstance(style_profile, dict):
            observed_records.extend(_style_profile_observation_records(style_profile))
        for location, record in observed_records:
            if record.get("evidence_status") == "exact":
                errors.append(f"{location}: observe operation requires observed, inferred, or unverified evidence")
            if record.get("status") == "approved":
                errors.append(f"{location}: observe operation cannot create approved records")
            rights = record.get("rights")
            if isinstance(rights, dict) and rights.get("status") in APPROVED_RIGHTS:
                errors.append(f"{location}: observe operation cannot clear rights before owner approval")

    authority_ok = True
    if needs_privileged_authority:
        authority_ok = _validate_privileged_authority(
            authorization,
            external_policy,
            common_scope,
            common["schema_version"],
            actor_id,
            errors,
        )

    if common["status"] == "active":
        if common["schema_version"] != SCOPED_SCHEMA_VERSION:
            errors.append("active production bundle requires schema_version '1.1' with scope")
        profile_rights = profile.get("rights")
        if not isinstance(profile_rights, dict) or profile_rights.get("status") not in APPROVED_RIGHTS:
            errors.append("active bundle requires brand-profile.json.rights.status approved or exact")
        if not isinstance(authorization, dict) or authorization.get("status") not in APPROVED_RIGHTS:
            errors.append("active bundle requires provenance.json.authorization.status approved or exact")
        if isinstance(authorization, dict):
            if not _is_nonempty_string(authorization.get("actor_id")):
                errors.append("active bundle requires provenance.json.authorization.actor_id")
            if authorization.get("role") not in APPROVED_ROLES:
                errors.append("active bundle requires local authenticated lead or admin role")
            if authorization.get("verified") is not True:
                errors.append("active bundle requires provenance.json.authorization.verified true")
            if authorization.get("policy_source") != "local_authenticated_policy":
                errors.append("active bundle requires local authenticated policy authorization")

    for registry_name, index, record in approved_registry_records:
        if not authority_ok:
            field_name = "claims" if registry_name.startswith("claim") else "templates"
            errors.append(
                f"{registry_name}.{field_name}[{index}]: approved record requires external policy scope and actor match"
            )

    return sorted(set(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="local brand directory containing the four JSON outputs")
    parser.add_argument("--brand-id", help="require this stable brand identifier")
    parser.add_argument("--tenant-id", help="require this scoped tenant identifier")
    parser.add_argument("--client-id", help="require this scoped client identifier")
    parser.add_argument("--product-id", help="require this scoped product overlay identifier")
    parser.add_argument("--policy", help="trusted local authenticated access-policy JSON file for active/approved validation")
    parser.add_argument("--actor-id", help="trusted current runtime identity for active/approved validation")
    args = parser.parse_args(argv)
    expected_scope = None
    if any(value is not None for value in (args.tenant_id, args.client_id, args.product_id)):
        expected_scope = {
            "tenant_id": args.tenant_id or "",
            "client_id": args.client_id or "",
            "product_id": args.product_id or "",
        }
    errors = validate_brand_bundle(args.directory, args.brand_id, expected_scope, args.policy, args.actor_id)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"valid brand bundle: {_path(args.directory)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
