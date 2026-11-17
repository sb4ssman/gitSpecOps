# What leaves a machine, and who can read it

gitSpecOps is built for one person's own machines. It adds no accounts and no servers: every
way out of a machine rides on something you already signed in to (Tailscale, your sync client,
GitHub), and that system's access control is the boundary. This page says, per way out, exactly
what travels.

Nothing in this table happens until you turn it on in setup or Settings.

| What | Travels by | What it holds | Who can read it | Optional? | Protected how | To stop |
|---|---|---|---|---|---|---|
| **Status report** (one per machine) | Tailscale, a synced folder, a private repository: whichever you chose | Per repository: an opaque id, branch id, commit ids, counts (ahead, behind, staged, unstaged, untracked, stashes), an operation in progress. Per library: its name, a disk fingerprint | Tailscale: your own devices only. Folder: whoever can read that folder. Repository: its collaborators, and GitHub | The whole fleet is optional; each way is chosen separately | Repository and branch names are replaced by keyed hashes (the fleet key), so a report does not list your repositories | `gitso fleet leave`, or untick the way in Settings |
| **Repository names and folder names** | Inside the status report | The readable name, owner and host; the folder a copy sits in (a name, never a path) | As the report that carries them | Yes, per way: names can go over Tailscale and stay out of the folder or the repository | Sent in the clear where you allow them | Turn names off for that way |
| **Uncommitted-work summary** | Tailscale only, when a page asks | File names, each file's status and line counts; whether a change is line endings only | The machine that asked, which must be one of your devices | It answers only when asked | Never file contents | Leave the fleet |
| **Requests** ("fast-forward these", "clone this") | Tailscale only | The repositories, the kind, the library named; afterwards one fixed sentence per repository | Your own devices | `auto_requests: false` makes them wait for Apply | Git's own messages never travel; they stay in the receiving machine's task log | Withdraw the request; leave the fleet |
| **Protected values** (never-publish and allowed lists) | Tailscale; a synced folder only if you turn sealing on | The values themselves | Tailscale: your own devices. Folder: sealed, so only a machine with the fleet key | Sharing happens in a fleet; the folder route is off by default | Folder copies are sealed with AES-256-GCM under a key made from the fleet key | Leave the fleet; turn sealing off |
| **Fleet key** | Tailscale, once, when a machine joins | The key | Devices owned by your Tailscale login | Joining by key typed by hand needs no transfer | Tailscale's device identity check | Make a new fleet |
| **Recovery snapshots** | Only where you separately enrolled capture | Your unfinished work: file names and **file contents** (patches) | Whoever can read the capture location | Off until you enroll it | Written in the clear, like the working files they came from; screened for secrets first (binary content cannot be screened) | Turn capture off; delete the snapshots |
| **The page on your phone** | Tailscale, port 8770 | The same map, read-only | Your own devices | Off unless "Also on my Tailscale devices" is chosen | Answers only to the machine's numeric Tailscale address | Choose "On this computer only" |
| **Security audit results** | Nowhere | | Only the page on the machine that ran it | | Values are masked until you press Show at that machine | |

## Never, by any route

Folder paths, diffs, commit messages, credentials, and (apart from recovery snapshots you
enrolled) file contents.

## What is not encrypted by gitSpecOps

Status reports in a synced folder or a private repository are plain JSON: their protection is
that folder's or repository's access control, plus the hashed names above. Recovery snapshots
are plain too, by decision (see `RECOVERY-DESIGN.md`, "Trust boundary"): a key that must reach
every machine to restore your work is a second system to lose. Tailscale traffic is encrypted
by Tailscale (WireGuard); gitSpecOps adds nothing on top.

## Where the page itself answers

The page is served on `127.0.0.1` only. Every action needs a token the page was given, the
right Host and Origin, a JSON body of a bounded size. Another machine cannot press a button on
this one; it can only send a request of the two safe kinds above.
