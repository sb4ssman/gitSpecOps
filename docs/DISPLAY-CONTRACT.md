# Fleet display contract

The fleet host publishes a presentation-independent JSON document at `GET /v1/dashboard`.
The standard interface and any other skin (an LCARS-inspired one, for example) consume this
exact document. A skin may change layout, language density, typography, sound, animation and
navigation. It must not reclassify Git facts, reinterpret freshness, infer attention from colors
or manufacture operations that the host did not advertise.

The contract identifier is `gitspecops.fleet.display`; its integer version is currently `1`.
Clients must reject an unsupported version while retaining their previous view. Additive
fields do not require a new version. Removing a field, changing its type or semantic meaning,
renaming a semantic value, or changing how a client must interpret a field requires a new
version and a migration period.

```text
observer -> manifest (names only, never paths) -> peers / shared folder / state repo
         -> Elaborate/_fleet/display.py build_display() -> display v1 -> skin
```

Only `display.py` turns fleet state into display semantics: every fact is worked out **once**, in
Python, and every page reads the same fact. It has no HTTP, filesystem, HTML or current-user
dependencies, and its clock is injectable. In the standard skin (`App/_web/skins/`),
`_common/fleet_client.js` owns refresh and compatibility checks, `_common/fleet_view.js` holds
presentation-neutral search, filter, grouping and sorting, and `standard/` draws.

## One vocabulary

Two hierarchies, the same words on every page:

```text
Cloud (provider: GitHub, GitLab, ...) > Owner > Repository
Machine > Library > Folder (an organization's folder) > Copy
```

- A **library** is a folder a machine watches. Its name always says what holds it, so every
  machine's libraries read alike: `Github (T:\)`, `Github (memory-lambda)`, `Github (~)` (a home
  folder: never the account's name). Names only; a path never leaves the machine.
- A **copy** is one checkout of a repository in one library on one machine. A machine may keep
  a repository in several libraries; each is its own copy.
- A **copy is always said against its provider**: "matches GitHub", "3 behind GitHub", "2 ahead
  of GitHub (not pushed)", "no remote: the only copy is on machines", as of that machine's last
  fetch. The commit it is on is shown beside it, and the provider's commit beside the provider.
- **Perspective**: every page starts from the machine showing it (`this_machine`).

## Pages (the standard skin)

The menu is the tiles: each item carries its number and a line, from `summary` and the lists
below. Network map is the visual; every other page is tables.

| Page | Shows | Reads |
|---|---|---|
| Network map | Zoomable picture: clouds, machines, libraries, organizations, copies | `machines`, `rows`, `map.links` |
| Repositories | Every repository, a column per library under each machine, the provider, advice; "Audit these" per group | `rows`, `groups` / `place_groups`, `filters` |
| Orgs/Archives | Each organization counted per library; one organization as the same grid, with requests | `rows` |
| Machines | Each machine and the libraries under it | `machines`, `libraries`, `issues` |
| Clouds | Providers, and how the machines talk | `providers`, `integrations` |
| Security | Audits of chosen repositories, files and every commit | local actions only |
| Settings | This machine's setup and the app | `capabilities`, `integrations`, `features`, local actions |

The same grid (`standard/fleet_grid.js`) draws Repositories and a single organization, so a copy
reads identically on both: same column order (perspective first), same words, same commit
subtext, same colours, one shade per machine, equal column widths.

## Top-level fields

| Field | Meaning |
|---|---|
| `contract` | Stable name and integer version. |
| `product` | Product name, build version and release channel shown to users. |
| `generated_at` | Time-dependent classification instant. |
| `fleet_id`, `fleet_name` | Public fleet label (never the key) and the fleet's chosen name. |
| `this_machine` | The machine showing this document: the default perspective. |
| `summary` | Totals: repositories, attention, machines, current and stale machines, organizations, libraries, providers, copies. |
| `machines` | Stable ID, label, age, freshness, observed time, repository count. |
| `libraries` | One entry per library on each machine: `machine_id`, `library`, `repositories`, `organizations`, `attention` (that library's own copies). |
| `providers` | One entry per provider host: `host`, `label`, `owners`, `repositories`, `attention`. `local` is "no remote". |
| `groups`, `place_groups` | Repositories grouped by owner, or by library and folder ("Library on machine" when it is another machine's). |
| `rows` | Repository identity, explicit attention decision, tags, advice, place and per-machine cells. |
| `map` | `links`: machine pairs sharing repositories, how many, how many differ, how many need attention. |
| `issues` | Sanitized observation issues attached to machine IDs. |
| `filters` | Filter vocabulary and labels supported by this contract instance. |
| `notices` | Host-authored limitations or qualifications that every skin must expose. |
| `capabilities` | Feature availability and a human reason. |
| `integrations` | How machines talk: Tailscale, a shared (synchronized) folder, a gitso-managed state repository; each `enabled`/`available` with a detail line. |
| `features` | Event-driven observation, remote Git actions, recovery snapshots. |
| `requests` | Requests between machines: waiting here, answered, sent. |
| `activity`, `mark` | What the app is doing now, and the mark's two states (this machine, the fleet). |
| `local_actions` | Present only on the page served to this computer: the token for its local actions. Never on the Tailscale view. |

## Semantic rules

- `needs_attention` is authoritative. A skin may emphasize it but may not recompute it from
  `severity`, status text or tone. A row needs attention when some copy holds unfinished work
  (stashed or worse, including work a stale report last showed). Being absent from a machine
  is normal, and a clean copy on a stale report is `unknown`, never an all-clear.
- Each present cell also carries `needs_attention`: that copy's own unfinished work. Counts per
  machine use the cell's value, never the row's. Per library, `libraries.attention` counts each
  library's own copies.
- A cell's `copies` (present when a machine keeps the repository in more than one library) lists
  each folder's own facts: `place`, `head`, `upstream_head`, `branch`, ahead/behind, uncommitted
  counts, stashes. The cell's own facts are the combination (worst case). A skin that splits a
  machine into library columns reads `copies`, and colours each copy by the same rule.
- `facts.head` and `facts.upstream_head` are full commit ids (or `null` when withheld or when a
  machine's copies disagree); skins show the first seven characters. `null` is "not shared".
- `tone` is one of `danger`, `warning`, `success`, `neutral` or `muted`. It conveys emphasis,
  not meaning; the adjacent text remains required for accessibility.
- `tags` drive filtering: `attention`, `dirty`, `ahead`, `local_only`, `stale`, `missing`.
  Additive tags may appear later and must be ignored safely by older clients.
- A missing machine cell is explicit: `present=false`, `freshness=absent`, `facts=null`.
- Notices about cached remote refs and stale reports are part of the contract. A skin may
  relocate them but must not hide them behind an error-only path.
- `capabilities` advertises availability; it grants no authorization. Every action goes through
  the local, token-checked actions and is checked again by the machine doing the work.

## Testing a skin

`python _build/demo_fleet.py` serves the real page with an invented, messy fleet (four machines,
one with two libraries, one stale; every kind of trouble) built through the same manifest and
display code; `--json` prints the document. A skin should also be tested against an empty fleet
and an unsupported contract version, at narrow widths, with the keyboard, and never with state
communicated by colour alone.
