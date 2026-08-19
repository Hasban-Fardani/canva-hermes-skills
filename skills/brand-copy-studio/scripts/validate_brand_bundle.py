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
    receipts only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
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


def _load_policy(value: dict[str, Any] | str | Path | None, errors: list[str]) -> dict[str, Any] | None:
    """Load a trusted local policy object supplied out-of-band by the caller."""

    if value is None:
        return None
    if isinstance(value, dict):
        _record_errors(value, "policy", errors)
        return value
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
    policy: dict[str, Any] | str | Path | None = None,
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
    schema_versions: set[Any] = set()
    scope_values: dict[str, tuple[Any, ...]] = {}
    for filename, document in docs.items():
        _require_fields(document, envelope, filename, errors)
        schema_version = document.get("schema_version")
        schema_versions.add(schema_version)
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
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
    profile_source_refs: list[tuple[str, list[str]]] = []
    for field in ("voice", "terminology", "copy_constraints", "visual_copy_cues", "gaps"):
        records = profile.get(field, [])
        if isinstance(records, list):
            for index, record in enumerate(records):
                if isinstance(record, dict):
                    profile_source_refs.append((f"brand-profile.json.{field}[{index}]", _validate_string_list(record.get("source_ids"), f"brand-profile.json.{field}[{index}].source_ids", errors)))
    claim_source_refs = [(f"claim-registry.json.claims[{index}]", _validate_string_list(record.get("source_ids"), f"claim-registry.json.claims[{index}].source_ids", errors)) for index, record in enumerate(claims) if isinstance(record, dict)]
    template_source_refs = [(f"template-registry.json.templates[{index}]", _validate_string_list(record.get("source_ids"), f"template-registry.json.templates[{index}].source_ids", errors)) for index, record in enumerate(templates) if isinstance(record, dict)]
    for location, refs in profile_source_refs + claim_source_refs + template_source_refs:
        for source_id in refs:
            if source_id not in source_ids:
                errors.append(f"{location}.source_ids: unknown source ID {source_id!r}")
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
        for location, record in observed_records:
            if record.get("evidence_status") == "exact":
                errors.append(f"{location}: observe operation requires observed, inferred, or unverified evidence")
            if record.get("status") == "approved":
                errors.append(f"{location}: observe operation cannot create approved records")
            rights = record.get("rights")
            if isinstance(rights, dict) and rights.get("status") in APPROVED_RIGHTS:
                errors.append(f"{location}: observe operation cannot clear rights before owner approval")

    approved_registry_records = [
        (registry_name, index, record)
        for registry_name, records, field_name in (
            ("claim-registry.json", claims, "claims"),
            ("template-registry.json", templates, "templates"),
        )
        for index, record in enumerate(records)
        if isinstance(record, dict) and record.get("status") == "approved"
    ]
    needs_privileged_authority = common["status"] == "active" or bool(approved_registry_records)
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
