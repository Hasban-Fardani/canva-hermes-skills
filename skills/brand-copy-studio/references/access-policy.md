# External access policy

The four brand files keep an authorization receipt for audit, but that mutable
receipt is not the authority for approval or activation. A caller that validates
an `active` bundle or an `approved` claim/template must supply a trusted local
access-policy object separately, using the validator library's `policy` argument
or CLI `--policy <path>` option, plus the trusted current runtime identity via
the library's `actor_id` argument or CLI `--actor-id` option.

Start from [assets/access-policy.template.json](../assets/access-policy.template.json).
The policy is provider-neutral and contains no real users:

```json
{
  "schema_version": "1.0",
  "policy_id": "policy-example",
  "revision": "2026-01-01T000000Z-r1",
  "source": "local_authenticated_policy",
  "scope": {
    "tenant_id": "tenant-example",
    "client_id": "client-example",
    "brand_id": "brand-example",
    "product_id": null
  },
  "role_mapping": {
    "lead": [],
    "admin": [],
    "member": [],
    "reviewer": [],
    "publisher": []
  }
}
```

Contract rules:

- `schema_version`, `policy_id`, and the UTC `revision` identify the policy
  record; `source` must be exactly `local_authenticated_policy`.
- `scope` has exactly `tenant_id`, `client_id`, `brand_id`, and `product_id`.
  IDs use lowercase-kebab format. `product_id: null` means the master brand;
  a product overlay uses its exact product ID.
- `role_mapping` may contain any of the five roles: `lead`, `admin`, `member`,
  `reviewer`, and `publisher`. Omitted roles and empty arrays mean that no
  identity currently holds that role. Each configured entry maps to explicit
  identity IDs; wildcards are rejected, while one identity may hold multiple
  explicitly named roles.
- For privileged work, policy scope must exactly match the bundle's tenant,
  client, brand, and product scope. The bundle's authorization receipt must
  name the same identity as the trusted runtime actor and map it to its declared
  `lead` or `admin` role. Embedded `actor_id`, `role`, `verified`, or
  `policy_source` fields cannot promote an identity not present in this external
  policy or impersonate a different runtime actor. The receipt must also carry
  the exact external `policy_id` and `policy_revision`.

Draft and `observe` validation does not require a policy or runtime actor.
`observe` remains a non-active, unverified draft; later capture/refresh and
activation require the external policy, trusted runtime actor, and authoritative
source or owner approval.
