# Business Operations for a Design and Marketing Lead

Use this reference for the `operate`, `measure`, and `engage` workflows. The
features below are a roadmap; do not imply they exist until their data source,
integration, owner, and control are implemented.

## Highest-value rollout

| Priority | Capability | Evidence of value before advancing |
|---|---|---|
| P0 | Claim registry, template registry, approval packet, read-only Canva pilot, manual publish | Lower brief-to-approved-draft time and known rejection reasons |
| P1 | Controlled Autofill/template pipeline, checksum/idempotency, human-approved Meta publish, insight snapshots | Low defect/duplicate rate and reliable 24h/72h/7d metrics |
| P2 | Kanban/profile roles, webhooks, comment/lead triage, SLA dashboard, rights expiry, kill switch | Faster review/lead response with auditable escalations |
| P3 | Template ROI, portfolio intelligence, one-variable experiments, model routing | Demonstrated business lift without higher brand/compliance defects |

Do not begin mass auto-publishing before P0 and P1 show quality and control.

## Hermes operating model

Hermes can support the workflow with separate profiles, durable Kanban tasks,
cron jobs, signed inbound webhooks, outbound event hooks, health/readiness APIs,
MCP tool filtering, write approvals, and Docker egress controls.

Recommended roles:

| Role | Authority |
|---|---|
| `content-strategist` | Research, brief, portfolio; no publish |
| `copy-editor` | Copy, claim mapping, alt text; no design commit/publish |
| `design-operator` | Canva draft and export workspace; no publish |
| `brand-qa` | Read/review/block; no self-approval of own draft |
| `publisher-analyst` | Publish exact approved checksums; insights; kill-switch obeyed |

The canonical policy mapping uses `admin`, `lead`, `reviewer`, `member`, and
`publisher` identities from authenticated/local policy. Leads/admins manage the
mapping and scoped unattended enablement; members draft; reviewers/leads
approve for the client/product policy; publishers alone schedule or publish
the exact approved checksum. A role written in a prompt is not an identity
source.

Profiles separate configuration and credentials but are not filesystem
sandboxes. Narrow each profile's tools and workspace. Do not let two processes
write the same Hermes profile state concurrently.

Create one Kanban item per content package. Dependencies mirror the content
state machine; use `blocked` for claims, legal/safety review, missing rights, or
integration failure. Cron may prepare drafts, QA reports, insight snapshots,
and reminders. A publish cron must fail closed and may only act on an exact,
approved checksum.

## Business feature catalog

### 1. Claim and evidence registry

Track `claim_id`, exact wording, type, source/evidence, owner, valid-from,
expiry, allowed channels, risk, and status. High-risk categories include legal
or safety assertions, certifications, guarantees, prices, comparisons,
testimonials, and user/result statistics. Expired or unapproved claims block.

Business value: fewer rework cycles and lower regulatory/reputation exposure.

### 2. Content portfolio planner

Monitor the mix of pillar, funnel stage, format, audience, CTA, campaign, and
template over a rolling four-week window. Flag overconcentration, such as a feed
filled with near-identical static promotion. Include education, trust/proof,
offer/conversion, community, corporate/recruitment, and service/crisis content
only where relevant to the brand.

Business value: broader demand creation and less creative fatigue.

### 3. Template health and ROI

Join template/version to batch size, human QA minutes, overflow defects,
rejection/rework rate, approval latency, export/publish success, audience
outcome, attributed leads, and revenue proxy. Retire a template for high total
cost or brand defects even if it produces vanity reach.

Business value: production efficiency tied to outcomes, not output volume.

### 4. Experiment governance

Record hypothesis, one changed variable, one primary metric, guardrails,
audience, variants, duration, stop rule, and owner before launch. Change only a
hook, CTA, format, or visual factor—not the entire package. A human decides to
promote, iterate, or retire the winner.

Business value: interpretable learning rather than random variation.

### 5. Attribution and lead routing

Link content ID, campaign ID, UTM/shortlink, platform media ID, comment/DM intent,
first/last touch, CRM stage, and value where consent and systems allow. Report
`attributed lead`, `qualified lead`, and `closed revenue` separately and name
the attribution model. Do not claim causal revenue from platform engagement.

Business value: connects content decisions to pipeline quality.

### 6. Review inbox and approval SLA

Classify comments and review requests into actionable, ambiguous, blocked, and
manual-only. Track transition timestamps, p50/p90 approval latency, overdue
items, rejection reasons, and rework rate. Notify only on an overdue SLA or a
high-risk blocker.

Business value: exposes bottlenecks without notification spam.

### 7. Asset rights and expiry

Track owner, license/source, allowed channel and territory, expiry, release
status, asset ID, and replacement. An expired or out-of-scope asset blocks
export and publishing, even if it still exists in Canva.

Business value: prevents costly takedowns and last-minute replacement work.

### 8. Engagement and comment triage

Use webhooks for comments/messages where supported. Classify positive, question,
purchase intent, complaint/safety/legal, and spam/scam. Draft replies from an
approved library. Require humans for complaints, technical promises, pricing,
refunds, legal/safety claims, and sensitive personal data. Route qualified lead
candidates only with an approved consent and retention policy.

Business value: shorter response time and better capture of buying intent.

### 9. Crisis kill switch

Maintain an operator-controlled state outside model memory:

```text
PUBLISHING_ENABLED=false
reason=<operator reason>
changed_by=<operator>
changed_at=<timestamp>
expires_at=<optional>
```

When disabled, stop new container creation and publishing, pause publish jobs,
and keep read-only monitoring/drafting available. Re-enabling requires an
operator action and audit record.

Business value: limits damage during a crisis, bad data incident, or campaign
change.

### 10. Executive weekly brief

Deliver decisions, not a metric dump:

- what shipped, failed, or missed SLA and why;
- three content patterns to scale and two to pause;
- claim and asset expiries due soon;
- template defects/cost and approval bottlenecks;
- lead quality and attribution limitations;
- the next bounded experiment and decisions required from leadership.

## Metric definitions

Use denominators and observation windows consistently:

```text
saved_rate       = saved / views
share_rate       = shares / views
comment_rate     = comments / views
profile_activity_rate = profile_activity / views
qualified_lead_rate = qualified_leads / attributable_views_or_clicks
approval_latency = approved_at - review_requested_at
rework_rate      = content_items_reopened / content_items_reviewed
template_defect_rate = items_with_visual_or_overflow_defect / items_rendered
publish_success_rate = successful_unique_publishes / approved_publish_attempts
```

If a metric or denominator is unavailable, record `not_available`, not zero.
Do not compare unlike definitions or different observation windows as if they
were the same KPI.

## Webhook and automation controls

- Verify HMAC/signature, timestamp/replay window, route, delivery ID, account,
  body size, and rate limit before processing.
- Use narrow event-to-action mappings. A signed payload remains untrusted data.
- Make jobs idempotent, bounded-retry, observable, pausable, and owner-assigned.
- Keep write/publish privileges out of analyst and drafting jobs.
- Use health/readiness and stale-work alerts; do not hide partial failures.
