# Current deliverable inventory

This inventory describes the sanitized release tree and the consistent snapshot used for release `v2026.10.30.1`. It does not use historical collection totals as the delivery baseline. Exact dataset counts, media dispositions, hashes and exclusions are in [DATA_PACKAGE.md](DATA_PACKAGE.md) and the dataset manifest. Exact tested operations and their boundaries are in [RELEASE_VALIDATION.md](RELEASE_VALIDATION.md).

## Source and application components

The source inventory currently hashes 99 files: 34 backend files, 16 frontend source/configuration files, 21 scripts, 22 test modules, 2 configuration templates, 2 dependency manifests and 2 command launchers. [SOURCE_FILE_HASHES.json](SOURCE_FILE_HASHES.json) records each relative path, byte length and SHA-256. Generated environments, frontend build products and documentation are outside that hash inventory. The final release commit identifies the complete source/documentation tree; the release build manifest records that commit. `source-inclusion.json` is the explicit packaging selection manifest.

| Component | Included implementation and responsibility |
| --- | --- |
| HTTP application | `backend/app.py`: loopback FastAPI endpoints, material and source inspection, product editing, matching, recommendation versions, weekly collections, exports and backups |
| Transactional storage | `backend/store.py`: SQLite records/revisions, source-event associations, immutable managed blobs, consistent backup and relationship validation |
| Business logic | `backend/extraction.py`, `matching.py`, `exports.py`, `time_semantics.py`: local document parsing, conservative matching, Chinese text/PNG exports and publication/observation time handling |
| Secrets boundary | `backend/secrets.py`: local credential handling; no credential value or protected credential file is shipped |
| Background workflows | `backend/background/service.py`, `pipeline.py`, `processing_index.py`: initial history, incremental source-index reconciliation, minimal processing receipts, relevance admission, independent candidate/media work and manual corrections |
| Relevance and inspection | `backend/background/relevance.py`, `inspection.py`: current corrected classification guards and bounded local OCR inspection; unrelated events do not become ordinary materials |
| Native adapters | `backend/background/{access,binding,chat,codec,image_access,media,moments,native,snapshot}.py`: source-bound Windows background adapters; deployment does not invoke them without explicit fresh local binding |
| Migration implementation | `backend/background/migration.py`: relevance migration logic preserved as source; historical migrations are not rerun when importing this release |
| Legacy collectors | `backend/collectors/`: upload/OCR and dormant native/UIA implementations retained for completeness; foreground collection remains disabled |
| Chinese frontend | `frontend/src/`: React workbench, source/material views, classifications, background status, settings, comparisons and Chinese operating controls |

## Schema and current retained data

The application schema is version **1**. `Store` creates these tables; the sanitized package constructs them afresh from selected logical fields:

| Table | Role in this release |
| --- | --- |
| `migrations` | Schema version record |
| `records` | Current application objects and detached `import_history` records |
| `revisions` | Sanitized meaningful versions of current business objects, plus initial records; no deleted-material or account/job churn history |
| `source_events` | Source occurrence and revision associations to retained materials; independent of shared file bytes |
| `blobs` | Only included managed files, with exported-byte hash, size and portable path |
| `processing_receipts` | Current outcome/provenance receipts marked ineligible for live synchronization |
| `pending_candidates` | Current unresolved/acquisition-retry candidates retained as detached historical objects, with privacy exclusions recorded per object |
| `source_index` | Empty: old account-bound synchronization state is not installed |

Current application data includes materials, source labels, products/manual edits, cases, saved recommendation versions, weekly collections, image occurrences, actual media bytes and saved Chinese exports. File slots that were never acquired remain missing. Excluded private/personal media is not recreated from unreferenced blobs or old revisions. See the dataset report for exact distinctions.

## Reproducible dependencies and resources

The tested deployment target is Windows with Python **3.12 x64**, Node.js **24 x64** and pnpm **11.25.0**. Other operating systems are unverified. Installation uses normal package downloads and does not require a Codex runtime, an inherited virtual environment, or undeclared global Python packages.

| Manifest | Scope | SHA-256 |
| --- | --- | --- |
| `requirements.lock.txt` | FastAPI/Starlette/Uvicorn, HTTP, SQLite-adjacent application dependencies, Pillow, Office/PDF parsing, Windows integration, cryptography and tests | `60dc29bc8b919ed66f0ae7f2ab52dbad787708ac11b3625dca54a5e093665699` |
| `requirements-ocr.lock.txt` | RapidOCR 3.9.2, ONNX Runtime, OpenCV, NumPy and pinned supporting packages | `66f5ffcd9bfd67b292120e4fa95e18b8a0207f6dd6bc8e33ca703efc815985c9` |
| `frontend/package.json` | React 19.2.0, TypeScript 5.9.3, Vite 7.1.7 and frontend tooling | `8130a3787173aeda510bbe2a32d48a28c2592c15e1ba8934f2d5fa284390aa68` |
| `frontend/pnpm-lock.yaml` | Exact resolved frontend dependency graph | `2d5e4d31fdd64183a5b0b4db126239301e28c97752878f7aea722dcb222ef333` |

`scripts/verify_resources.py` checks all three OCR model hashes installed by the pinned RapidOCR package and verifies an available Chinese export font. Font files are supplied by the receiving machine's licensed Windows installation, not redistributed. `imageio-ffmpeg`, Pillow and the native background codec/media modules cover the existing media paths; imported saved bytes need no original database or image key. No locally modified third-party dependency source is required. See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) for rights and notices. This release is not an offline installer.

## Installation, lifecycle and data tools

| Entry point | Purpose |
| --- | --- |
| `scripts/setup.ps1` | Validate Python, create an isolated environment, install pinned dependencies, verify OCR/fonts, install frozen frontend dependencies and build |
| `scripts/start.ps1`, `start.cmd` | Start the selected data directory and port; loopback service and instance ownership checks |
| `scripts/stop.ps1`, `stop.cmd` | Stop only the managed instance matching its saved ownership metadata |
| `scripts/fetch_release.py` | Fetch authorized private release assets and verify supplied checksums |
| `scripts/portable_data.py export` | Construct a fresh selected-field database from a consistent private snapshot, local identity map and explicit file/body privacy-review policy |
| `scripts/portable_data.py verify/import/pack/unpack` | Verify hashes/schema/relationships; import safely into a fresh directory; repeat the same import without overwriting local edits; reject traversal and conflicting existing data |
| `scripts/portable_data.py backup/restore` | Request an application-supported consistent backup of an imported instance; restore verified data to a new directory |
| `scripts/smoke.py` | Verify health, Chinese UI bundles, sources, media and optional isolated business operations/Chinese exports |
| `scripts/privacy_scan.py` | Scan selected source, serialized content, containers and Git objects using local identity inputs without uploading to an external scanner |
| `config/environment.example.ps1`, `config/live-binding.example.json` | Placeholder configuration and separate optional fresh local binding |

Historical collection/relevance diagnostic scripts are retained as engineering source, including `verify_*`, `migrate_relevance.py`, `import_live_evidence.py`, `review_relevance_images.py`, `finalize_relevance_metadata.py`, `audit_relevance_delivery.py`, `probe_background_access.py` and `ocr_experiment.py`. They are not part of the imported deployment command sequence and must not be run against a user's installation as a deployment shortcut.

## Tests, documentation and exclusions

The 22 test modules cover domain matching/extraction, storage/API behavior, collectors, background codecs/native readers, relevance migration/admission/corrections, incremental processing, recovery, imported runtime safety and data portability. Tests create bounded synthetic fixtures; private account caches, native database snapshots and historical personal screenshot evidence are not test dependencies. The current finite verification result belongs in the release validation report rather than being inferred from a test-file count.

Required entry points are [README](../README.md), the [Chinese installation/operating guide](DEPLOYMENT.zh-CN.md), the [English Codex handoff](CODEX_DEPLOYMENT.md), [DATA_PACKAGE.md](DATA_PACKAGE.md), [RELEASE_VALIDATION.md](RELEASE_VALIDATION.md) and root [AGENTS.md](../AGENTS.md). Historical briefs are preserved only in sanitized form and do not authorize collection on a receiving machine.

The deliverable excludes the original `.git` history, `.venv`, `node_modules`, generated caches, credential stores, private identity maps, native WeChat databases, account caches, decrypted native snapshots, process dumps, unrelated old backups, executable account-bound job state and intentionally excluded personal/unrelated content. The private source backup is an export input only, not a release asset.
