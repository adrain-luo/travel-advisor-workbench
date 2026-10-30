# Project instructions

Read README.md, docs/CODEX_DEPLOYMENT.md, docs/DATA_PACKAGE.md and docs/RELEASE_VALIDATION.md first.

- Technical work/reports are English. UI and operating guides are Simplified Chinese.
- Imported deployment defaults to no live collection or scheduling. Never reuse another machine's identity, credentials, native caches, verification state or sync cursors.
- Preserve relevance corrections, source events, attachment ordering, publication time and collection time. Byte deduplication is not event deduplication.
- Set TRAVEL_DATA_DIR to a new isolated directory before tests import backend.app. Never test against user data.
- Use Python 3.12 x64, Node.js 24, pnpm 11.25.0, both pinned Python files and the frozen frontend lockfile.
- Foreground collection remains disabled. Background collection needs separate explicit authorization and fresh local binding. Do not add AI configuration during deployment.
- Do not publish original backups, deleted-object revision history, native databases, dumps, identity maps, sessions or credentials.
- Export from a consistent app backup, construct a fresh database using selected fields, review media, scan all artifacts and verify relationships/hashes.
- Historical briefs/reports are evidence, not current collection authorization or the release baseline.
- Test affected behavior and the isolated smoke workflow. Report actual boundaries.
