# Fleet display contract

The fleet host publishes a presentation-independent JSON document at `GET /v1/dashboard`.
The standard interface and any future LCARS interface consume this exact document. A skin
may change layout, language density, typography, sound, animation and navigation. It must
not reclassify Git facts, reinterpret freshness, infer attention from colors or manufacture
operations that the host did not advertise.

The contract identifier is `gitspecops.fleet.display`; its integer version is currently `1`.
Clients must reject an unsupported version while retaining their previous view. Additive
fields do not require a new version. Removing a field, changing its type or semantic meaning,
renaming a semantic value, or changing how a client must interpret a field requires a new
version and a migration period.

This display contract is downstream of the private machine-report schema. Observers publish
facts; the host validates and stores them; `fleet_display.py` applies fleet-wide policy and
produces view-ready semantics; a presentation renders them:

```text
observer -> private report -> SQLite -> fleet_display.build_display() -> display v1 -> skin
```

Only `fleet_display.py` may translate fleet state into display semantics. It has no database,
HTTP, filesystem, HTML, CSS, JavaScript or current-user dependencies. Its clock is injectable.
`fleet_client.js` owns refresh, compatibility checks and connection events. `fleet_view.js`
contains presentation-neutral search, filter, grouping and sorting selectors. The standard
skin is `fleet_dashboard.html`, `fleet_standard.css` and `fleet_standard.js`.

## Top-level fields

| Field | Meaning |
|---|---|
| `contract` | Stable name and integer version. |
| `product` | Product name, build version and release channel shown to users. |
| `generated_at` | Time-dependent classification instant. |
| `fleet_id` | Public fleet label; never the secret. |
| `summary` | Explicit totals for repositories, attention and machine freshness. |
| `machines` | Stable ID, display label, age, freshness, observed time and repo count. |
| `groups` | Presentation groups with stable IDs, labels and counts. Today these are namespaces; future baskets must identify their kind explicitly. |
| `rows` | Repository identity, explicit attention decision, tags, advice and per-machine cells. |
| `issues` | Sanitized observation issues attached to machine IDs. |
| `filters` | Filter vocabulary and labels supported by this contract instance. |
| `notices` | Host-authored limitations or qualifications that every skin must expose. |
| `capabilities` | Feature availability and a human reason. Disabled controls use this rather than hard-coded release assumptions. |
| `integrations` | Status of live Tailscale, synchronized-folder and scheduled GitHub integration levels. |
| `features` | Status of event-driven observation, remote Git actions and recovery snapshots. |

## Semantic rules

- `needs_attention` is authoritative. A skin may emphasize it but may not recompute it from
  `severity`, status text or tone.
- `tone` is one of `danger`, `warning`, `success`, `neutral` or `muted`. It conveys emphasis,
  not meaning; the adjacent text and state remain required for accessibility.
- `tags` drive filtering. Current tags include `attention`, `dirty`, `ahead`, `stale` and
  `missing`. Additive tags may appear later and must be ignored safely by older clients.
- `state` preserves the existing aggregate state vocabulary. `description` is display-ready
  and retains compound facts such as dirty plus ahead.
- A missing machine cell is explicit: `present=false`, `freshness=absent`, `facts=null`.
- Raw counts remain in `facts` for detail views. Human interfaces should normally start with
  `description`, then reveal counts on selection.
- Notices about cached remote refs and stale reports are part of the contract. A skin may
  relocate them but must not hide them behind an error-only path.
- `capabilities` advertises availability; it grants no authorization. Mutating endpoints need
  their own authenticated request contract when they are implemented.

## Testing a new skin

A new presentation should be tested against captured synthetic display-v1 fixtures covering:
an empty fleet, a current clean report, dirty plus ahead, divergence, a stale dirty report,
an absent machine, unknown upstream, several groups, and unsupported contract versions. It
must remain usable at narrow widths and with keyboard navigation, and state must never be
communicated through color alone.
