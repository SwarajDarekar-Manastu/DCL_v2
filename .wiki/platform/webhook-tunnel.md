# Public HTTPS for Graph webhooks (Cloudflare Tunnel evaluation)

| Field | Value |
|-------|-------|
| Feature id | `platform/webhook-tunnel` |
| Status | planned (recommendation; the user decides) |
| Owner session | S4 (tunnel), S1 (receiver, subscriptions) |
| Spec | docs/architecture/02 §3.3; DECISIONS 2026-10-23 (real-time sync) |
| Last updated | 2026-10-23 |

## Question

Graph sends change notifications only to a public HTTPS URL. The stack runs on a LAN host (192.168.40.73) with no public address. Should we put a Cloudflare Tunnel in front of the API's webhook receiver, or stay on the 5-minute delta poll?

## Recommendation

**Stay on the 5-minute poll now. Add a named Cloudflare Tunnel later, when all three of these are true:**

1. S1's webhook receiver exists. `backend/api/sync.py` is still a stub, so a tunnel today would expose nothing useful.
2. A domain whose DNS is on Cloudflare is available for a fixed hostname such as `dcl-hooks.<domain>`.
3. IT accepts an outbound tunnel from this host to Cloudflare.

The poll already gives a worst case of about 5 minutes from a save to the start of a delta run. Webhooks shorten that to the 30 s debounce of 02 §3.3. Webhooks never replace the poll or the daily delta: they are a trigger, not a source of truth.

## What the tunnel would be

- A `cloudflared` container on the stack network (pinned image), started with a tunnel token held as a secret (not in the repo or `.env.example`). It opens only outbound connections, so no router port forwarding and no inbound firewall rule are needed.
- One ingress rule: `https://dcl-hooks.<domain>/` with a path rule matching the webhook route only, forwarded to `http://api:8200`. A catch-all rule returns 404. The Console, the rest of the API, Open WebUI, Grafana and MinIO stay LAN-only.
- Cloudflare terminates TLS, so it can see notification bodies. For drive subscriptions these hold only subscription id, resource, change type and the `clientState` secret, never file content. The receiver must check `clientState` (02 §3.3 step 1) and answer the validation handshake (echo `validationToken` as text/plain within 10 s).
- Optional hardening: a Cloudflare WAF rule that admits only Microsoft's published Graph notification source ranges.
- Effort: about half a day for S4 (service, secret, health check, runbook entry, alert when the tunnel is down), after the receiver lands.

## Options compared

| Option | Fixed URL | Needs | Verdict |
|--------|-----------|-------|---------|
| Poll every 5 min (current) | n/a | nothing | Keep in all cases |
| Cloudflare named tunnel | yes | Cloudflare account (free tier), domain on Cloudflare, IT approval | Recommended when the three conditions hold |
| Cloudflare quick tunnel (`trycloudflare.com`) | no, changes on every restart | nothing | Rejected: every restart breaks every subscription; no uptime promise |
| Tailscale Funnel | yes (`*.ts.net`) | Tailscale account on the host | Workable fallback if no domain is on Cloudflare |
| Graph delivery to Azure Event Hubs (outbound pull) | n/a | Azure subscription, Event Hub; check that drive resources are supported | Worth checking if the tenant prefers Azure-only data paths |
| Reverse proxy on a public VM + VPN back | yes | a VM to run and patch | Rejected: more to operate than a tunnel |

## Decision needed from the user

1. Is there a domain on Cloudflare we may use, and does IT allow an outbound Cloudflare tunnel from this host?
2. If yes: should S4 add the tunnel once S1's receiver is merged, or wait until latency of the poll is a real complaint?

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-23 | S4 | Evaluation and recommendation written (DECISIONS 2026-10-23) |
