# Security and privacy

Filigree 0.1 is for a single trusted user's local computer. It is **not a public web server** or a multi-user authorization system. Bind is fixed to `127.0.0.1`. Do not expose it through a public tunnel or reverse proxy.

The HTTP interface validates Host and Origin and requires a per-process token for writes. This reduces browser cross-origin and DNS-rebinding attacks. It does not defend against software already running as your OS user. MCP clients have local read/propose access and can read private project knowledge; configure only trusted clients.

**Trust boundary.** The local HTTP token and the browser interface are **not human authentication**: any process of your OS user can read the token and call the API, and "accepted" only means *accepted through the local review interface*. Deliberate creation of an already-accepted entry through that interface is allowed (a person typing in their own workbench). MCP, import and automatic capture can **only propose**; the `channel` recorded on each entry and change event (`http-ui`, `mcp`, `import`, `capture`, `local`) is set by the server, and any `channel` a client sends is refused or ignored. The `agent` field, like every actor name, is a label **declared** by the client and is shown as such ("Déclaré par … (non authentifié)"); editing it creates a normal revision and event, never an impersonation claim. Do not treat a name, a label or a channel as proof of who acted.

**Corrections and recovery.** Titles and bodies of a superseded entry may still be corrected, but every correction is an append-only revision (earlier revisions stay readable in the history, the change event stays) and a superseded entry never returns to `accepted`. To undo a replacement, create a new **accepted** entry that `supersedes` the current one. Entries or event files that cannot be read are quarantined (never rewritten) and the interface announces them instead of silently omitting them.

Imported material is untrusted data. Sources are claims about provenance, not cryptographic proof of authorship. Filigree does not execute imported commands or render imported HTML. An agent reading memory must independently respect its own instruction hierarchy; a warning is not a complete prompt-injection defense.

Some recognizable secrets are redacted before persistence. This is a heuristic, **not a guarantee**. Review all material before Git publication. Knowledge bodies, selected source excerpts, earlier revisions and import fingerprints are part of the memory repository. Original trace files stay wherever you imported them from; Filigree does not move them into its repository. Deleting a current note does not erase Git history. There is no encryption at rest.

Memory uses advisory OS locks, atomic replacement and a recovery journal. Use a local filesystem, one shared data root and the application for writes. Manual edits while it runs, filesystem sync tools and network shares are outside the concurrency guarantee. Manual Markdown edits are read, but do not automatically create audit revisions.

Report vulnerabilities privately to the repository maintainer through GitHub's available private reporting channel. Do not open a public issue containing secrets or private traces. If private reporting is unavailable, ask for a secure contact without posting the exploit data.
