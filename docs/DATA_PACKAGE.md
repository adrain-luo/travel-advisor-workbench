# Sanitized data package

This report is generated from the verified logical export for **v2026.10.30.1**, not from historical README totals. The source application produced a consistent SQLite-and-assets backup while holding its storage lock; the source snapshot timestamp is **2026-10-30T05:45:00.429063+00:00** (2026-10-30 13:45:00 Asia/Shanghai). The release contains the current retained state at that cutoff. The original application may continue processing later events independently.

## Version, files and checksums

- Package format: `travel-advisor-logical-v1`; application/schema version: **1**.
- Dataset ID: `4ed1d7028aededabc6d91172aacc46f4bbd57e77642adb6529a3d984ceb0a408`.
- Archive: `travel-advisor-data-v2026.10.30.1.zip`, **43,048,951 bytes**, SHA-256 `8a8e474a4b4d5fc9c2ae88df27d109955548def200b14e9e01863fb0b4fccf4b`.
- `dataset-manifest.json`: **27,683 bytes**, SHA-256 `910fe671fb492476c1c33408b13e6761ecb324ba06d1870c05ca23090f6ce773`.
- **53 payload files**, **44,609,427 payload bytes**, plus the manifest: a fresh SQLite database, **47 managed image blobs**, and **5 saved export files** (1 PNG and 4 UTF-8 text files).
- The archive has **54 files including its manifest**. Shared identical bytes are stored once. Four export records retain their original six file associations; two PNG associations share one included PNG file.

The manifest contains every relative file path, length and exported-byte SHA-256, record counts, source counts, transformations, exclusions and removed-field occurrence counts. The release build manifest binds this dataset version to the exact sanitized source commit. All necessary file references use managed relative paths and resolve inside the package; none requires the original machine's drive or account directory.

## Current source inventory

The consistent source snapshot contains **63 current records**. These are current object counts, not cumulative collection claims:

| Current source category | Count |
| --- | ---: |
| `accounts` | 2 |
| `attachments` | 14 |
| `background_jobs` | 9 |
| `background_status` | 1 |
| `cases` | 1 |
| `checkpoints` | 9 |
| `exports` | 4 |
| `extractions` | 0 |
| `jobs` | 2 |
| `live_evidence` | 1 |
| `materials` | 9 |
| `products` | 2 |
| `recommendations` | 2 |
| `source_processing` | 2 |
| `sources` | 4 |
| `verifications` | 0 |
| `weekly` | 1 |

The source also contains **13 source-event/revision associations**, **294 processing receipts**, **73 pending candidates** and **66,566 revision rows**. Its historical blob catalog and unreferenced blob files are not used as delivery counts. No deleted or intentionally excluded conversation bodies are reconstructed from those artifacts.

## Exported records and media

The freshly constructed database contains these current records:

| Exported category | Count |
| --- | ---: |
| `accounts` | 2 |
| `attachments` | 14 |
| `cases` | 1 |
| `exports` | 4 |
| `import_history` | 22 |
| `live_evidence` | 1 |
| `materials` | 9 |
| `products` | 2 |
| `recommendations` | 2 |
| `settings` | 1 |
| `sources` | 4 |
| `weekly` | 1 |

There are **121 sanitized revision rows**: 73 meaningful business versions for objects still present, plus 48 initial sanitized/current or detached-history versions. Account/job/status churn and removed-object history are not copied. All **13 source-event associations** resolve to the retained materials.

- **9 materials** remain: 7 accepted background materials and 2 protected earlier materials. The 7 background material classifications retain their original correction evidence/origin (1 manual, 6 inspection). Product facts, price conditions, manual edits and useful supplier/source labels are preserved.
- **2 products**, **1 case**, **2 saved recommendations**, **1 weekly collection**, **4 export records**, and their source/product/version relationships are included.
- **14 attachment occurrence records** remain: **9 saved material-linked image occurrences** representing **8 distinct saved images**, and **5 explicitly unavailable evidence-image occurrences**. Every material card retains its actual saved product image. Multiple source events may legitimately refer to identical bytes.
- **73 detached pending candidates** contain **83 ordered attachment slots**. **39 slots retain saved image bytes**; **28 slots are explicitly unavailable because their private/personal bytes were excluded**; **15 reference-discovered slots and 1 pending slot were never acquired**. No unsupported or missing native image/document is fabricated.
- **0 saved document attachments** were present in this snapshot. Document-parser code and dependency coverage do not establish real native-document acquisition.
- The 8 distinct material images and 39 retained candidate images form the **47 managed blobs**. The separate saved PNG export is the 48th stored image file; four saved text exports are also present.

Pending candidates retain their source-event identity, original time, outcome, reason, classification evidence and attachment order. They stay outside ordinary materials and matching inputs. Imported previews are read-only. Retry times and expiry are disabled; no scheduler operates on the imported candidates.

## Filtering and correction provenance

All **294 processing receipts** are retained as detached provenance:

| Outcome | Count |
| --- | ---: |
| `KEEP_PRODUCT_RELEVANT` | 7 |
| `SKIP_IRRELEVANT` | 214 |
| `PENDING_RELEVANCE` | 57 |
| `RETRY_ACQUISITION` | 16 |

Skipped receipts contain minimal processing information, not the removed unrelated bodies. Manual/inspection classification labels, evidence, rule versions, publication/collection timestamps, first-discovery information, reason codes and material associations are preserved where present. Missing history is not inferred from local exhaustion. Original publication/message time remains distinct from observation/import time, and old offers are not represented as currently bookable.

Source occurrence identity is separate from content-addressed blob identity. Native content identifiers, including values larger than JavaScript's exact integer range, are serialized as strings. Historical material/source identity-verification booleans are preserved only in `historical_identity_evidence`, explicitly scoped to the original snapshot. They do not verify a receiving account.

An independent source-to-export comparison passed for all 9 materials' text/source/time/classification/relevance fields and attachment order, both products' offer/manual-edit/evidence/source fields, all 294 receipt outcomes/corrections/timestamps, all 73 candidate dispositions/text-exclusion decisions/slot order, and all 13 source-event relationships. One never-acquired candidate slot has no original attachment ID; its ordered position is preserved instead of fabricating a native identity.

## Owner identity, credentials and runtime state

Two collecting-account records use stable anonymous aliases (`collector-account-001` and `collector-account-002`); own outgoing message senders use `self`. Source identities matching an excluded owner are replaced consistently. Supplier identities, names, prices and labels outside that exclusion remain useful provenance. The real-identity mapping stays private on the original machine and is not part of the source tree, data archive, manifest or Git history.

Selected-field construction removes native/private retrieval references, signed media access material, owner identifiers and machine paths, old verification/binding state, sessions, executable jobs/cursors, private caches and unreferenced historical assets. No original database file, native WeChat database, encrypted/decrypted snapshot, process dump, key, credential store or unrelated backup is shipped. An empty provider configuration is installed; AI setup remains deferred.

Accounts and sources are marked imported, unselected and unverified. **22 historical job/checkpoint/source-processing records** are preserved in detached `import_history`; there are no executable imported jobs, leases, old process handles or active source indexes. Import creates `imported-installation.json` with live collection disabled. Optional future live collection requires separate authorization and fresh local binding; it must not reuse this dataset's receipts or account state.

## Transformations and explicit exclusions

Local media review covered **82 image-path occurrences** and the nonempty retained candidate bodies. **6 images** became local metadata-stripped PNG derivatives, removing EXIF/XMP/ICC/comment metadata while preserving reviewed visible content. Their exported hashes, dimensions, MIME types and download filenames describe the derivative bytes; `original_verified` is false. They are **not byte-identical** to their originals. No external AI service or file-upload scanner was used.

| Original non-sensitive file reference | Exported derivative | Exported SHA-256 |
| --- | --- | --- |
| `blobs/7e/7e88abd7c837c4d09b65db5b7179defd9c1492a5ae80e2ec269d8674a7aadf7f` | `blobs/30/3032026e48d0cc388de4536b1dc703ca40a5f5524d711ad61442d8ddee673b0a` | `3032026e48d0cc388de4536b1dc703ca40a5f5524d711ad61442d8ddee673b0a` |
| `relevance-staging/5745e64292c7dbbca5b9daed240ee4669bb1fe2e9aaae27d24e985a019b6418c` | `blobs/fc/fc7efdf6c60ac66f4f722486aeb97937de15cef40e648e165f28d2ee6c43d73c` | `fc7efdf6c60ac66f4f722486aeb97937de15cef40e648e165f28d2ee6c43d73c` |
| `relevance-staging/7a3a3c746ac3ff8c9c9363392a97081ce43fba3009e7b6655964e503ebc9ae6c` | `blobs/e6/e6e56e2d9d1dcfda502c559ade101b6e2a1d615c32ef1f1903faac8b85790d46` | `e6e56e2d9d1dcfda502c559ade101b6e2a1d615c32ef1f1903faac8b85790d46` |
| `relevance-staging/ba898bc672663de8ea71931ea91896ca84c64c5e1ed931929e9c4fca82a48bed` | `blobs/27/27d87d7dd0643bd14d18d550254300c9aa9141ab86f2f31ac563c2c5287a725a` | `27d87d7dd0643bd14d18d550254300c9aa9141ab86f2f31ac563c2c5287a725a` |
| `relevance-staging/d9ec4622f0cbae50de63872b6cff8a891ff005482efe88774bda8e9a1106f9c9` | `blobs/f0/f051a72c99b884d3189056f85e2a2da952277a8b41af9982f023cfff6fa3ad29` | `f051a72c99b884d3189056f85e2a2da952277a8b41af9982f023cfff6fa3ad29` |
| `relevance-staging/eb8124922bab6d15dd06e8d0424ea3043db0ce2d2478cd5e30e6c189cabbca88` | `blobs/a1/a170c062652d17b042d70665ad468d2ab8952595d05f2d530a4305fefc7fd458` | `a170c062652d17b042d70665ad468d2ab8952595d05f2d530a4305fefc7fd458` |

**33 image files** and **3 personal candidate bodies** are explicitly excluded. This is a sanitized current export with documented exclusions, not a claim that every original byte is delivered. The five legacy evidence screenshots comprise an owner profile/avatar and four context screenshots with pervasive repeated owner-identifying watermarks; reliable removal would obscure their source content. Their standalone product posters and structured provenance remain included. The remaining 28 exclusions are personal/scenic/household/medical/location content; five already carried `scenic_personal` classifications. Excluded bodies are blanked while their detached receipts and source/time relationships remain.

Each exclusion is identified below using a non-sensitive local reference. The manifest contains the same complete list; no excluded identity value is repeated in the removal report.

| Reference | Category | Reason |
| --- | --- | --- |
| `blobs/2c/2cbd01942f78b467ebe7b2f224cff07f8b78892ee6e02a5adb37d5c735dc5fe9` | privacy | Pervasive repeated owner identity watermark across context screenshot; cannot reliably remove without obscuring source content. |
| `blobs/67/67cb475aefaffe2b5e84e4d614c9b1e10854da47f9446f0e243aac9e70751f2b` | privacy | Owner account profile screenshot; contains excluded collecting identity and avatar. |
| `blobs/92/92ffb31e6b129e634b65de5dfbe6fef2e378912163fbed024c9cda753d537605` | privacy | Pervasive repeated owner identity watermark across context screenshot; cannot reliably remove without obscuring source content. |
| `blobs/99/99b77a913dc1494f164159b3a392b67fdc9a3b166bf845ff55699a60a7c8cd5b` | privacy | Pervasive repeated owner identity watermark across context screenshot; cannot reliably remove without obscuring source content. |
| `blobs/f0/f04e6b666b701fd3c4e3d783f7aa4f4d9d5a6d5edc12f1ba3757cda94c5d009f` | privacy | Pervasive repeated owner identity watermark across context screenshot; cannot reliably remove without obscuring source content. |
| `relevance-staging/040efa568aa0ff42e86b5df61bacdce09734f8fe9e91efffaf8b68c7e817a1fd` | privacy | Personal meal photograph accompanying non-product anecdote; detached provenance retained. |
| `relevance-staging/087f386cd89f9eb1f1a42782d71c508290c3a1c48bb65a01d840e6b59ff45394` | privacy | Personal flower photograph with no necessary product content; detached provenance retained. |
| `relevance-staging/0f0f76728b798d3ccec1f460bacd0f54c6f1fb99f4eb980cd17374f166cff229` | privacy | Private residential floor plan; sensitive household layout unrelated to travel products. |
| `relevance-staging/0f2f19e75d1531e3177ca525819f6f4778fb30f04e079faf30f968f3a6821f04` | privacy | Private personal portrait/household photograph unrelated to retained travel products. |
| `relevance-staging/137cfbc48f82f223ea727c2d8e31682def9ba53cfd28c462217470b82034450f` | privacy | Personal home-interior recommendation composite; private surroundings cannot be separated from image content. |
| `relevance-staging/1645ab19027fb53f10a3156b10d4c2154456850142c94f24525deb404d8b724e` | privacy | Private personal portrait/household photograph unrelated to retained travel products. |
| `relevance-staging/1aa420c74763c6f944d607286b60dd1c9d508aaf957e1692cb7e9ab4a4ef7d63` | privacy | Private personal portrait/household photograph unrelated to retained travel products. |
| `relevance-staging/208f8332074588c78999824090ff35a68fe1b2be9164d3caf1d32bde7681aed0` | privacy | Private personal portrait/household photograph unrelated to retained travel products. |
| `relevance-staging/2434ff3fb4423d83cd859b8de7e999da3cf175eb72a06b7ab25e87f57203fb02` | privacy | Private medical record photograph; sensitive personal information unrelated to retained travel products. |
| `relevance-staging/38e8e889689f0471cb4f0cb642cd844713f5a3f1ad6a817f08e240deeeafec88` | privacy | Previously inspected and classified scenic_personal; excluded image bytes are not resurrected in the release. |
| `relevance-staging/471a75a15378865f6fcaef5a1a3238b17ac4b4cfa35fb6efeb017dee3bca87bc` | privacy | Private home interior photograph; retained only as detached processing provenance. |
| `relevance-staging/5b84ff04a4f17ce931af0c2e1b616f71dfe15e976a6f9cd865712901044479b8` | privacy | Private home interior photograph; retained only as detached processing provenance. |
| `relevance-staging/5e4b094284662ceff13eab1c15bb2cb3d4efe907ae721ac89e7dcd27531e2a59` | privacy | Private personal portrait/household photograph unrelated to retained travel products. |
| `relevance-staging/5ea6ed91085e660fe7b60809dfee7d4a4b0d6ae0ce0edda02471e5d0f282a909` | privacy | Previously inspected and classified scenic_personal; excluded image bytes are not resurrected in the release. |
| `relevance-staging/5eacb3ef980f005cefe1be8fde80f0f468e32b08fe97e07029e8c26a86cb2b36` | privacy | Previously inspected and classified scenic_personal; excluded image bytes are not resurrected in the release. |
| `relevance-staging/63b2c38fe0ae4da8a0677f97977810225125adf72d4b78b38b2cf05e2d34bb45` | privacy | Portrait image accompanying non-product personal anecdote; detached provenance retained. |
| `relevance-staging/7be6547d7b50c8de223f6913ced032ed7abd2fdf4568000e68f7da1cba3026aa` | privacy | Personal home-interior recommendation composite; private surroundings cannot be separated from image content. |
| `relevance-staging/a49201a2ae4e047c59e6d75dc3f1d4f3cca5a44485d58925f4605ae830468571` | privacy | Private household photograph; personal surroundings unrelated to travel-product content. |
| `relevance-staging/a84a3d96845239259928fd63576112ec899956acb04fe7c47763de0cffe0ee38` | privacy | Personal navigation screenshot exposes precise local location; no retained travel-product content. |
| `relevance-staging/ada0a9dcec55695c732ce96aa730eabdd9244845c85e324217c0130cc5fef741` | privacy | Personal portrait in household/furniture setting; no necessary travel-product content. |
| `relevance-staging/b5fd79a2637f20172c3f93cab3a15d6082244b9241b1f7934e01fd42de6d8c16` | privacy | Private personal portrait/household photograph unrelated to retained travel products. |
| `relevance-staging/c714a218368805df0e4fe52083a030d0da79c2c19a373d2bca98f5417e066228` | privacy | Previously inspected and classified scenic_personal; excluded image bytes are not resurrected in the release. |
| `relevance-staging/cfcc6bd3af4c4712a10148236feb8cef5afcdbe9fb12fbe9f1e702cdd030a6e4` | privacy | Previously inspected and classified scenic_personal; excluded image bytes are not resurrected in the release. |
| `relevance-staging/d40b08112ba73e51b0e6e7927abce23ce2898f70a5ac883761bfe8e7aae7cbf3` | privacy | Personal home-interior recommendation composite; private surroundings cannot be separated from image content. |
| `relevance-staging/df02ea9e4cb7ae9424cd29b2a8afc31ab0ca947abbf169cc873c277c1106a947` | privacy | Private home interior photograph; retained only as detached processing provenance. |
| `relevance-staging/e0098f7587a2f446a95a6a7eff29b89cbb1ab1b9db14866a0a9c35caee93c250` | privacy | Private home interior photograph; retained only as detached processing provenance. |
| `relevance-staging/f1f59911abe68468c78ce673511be10c69d1bf274e55de154e87149bc6a754b8` | privacy | Personal food photograph with no necessary product content; detached provenance retained. |
| `relevance-staging/fdca330e4c5cb27ef41204e5ba3b798f3f5e3af3b67f87e780ad0154bbb8f914` | privacy | Private home interior photograph; retained only as detached processing provenance. |
| `candidate:f36faa969e6e812af8ae8407efd759892a201e7f44f3578986c47f277098d833` | candidate_body | Personal non-product anecdote associated with excluded private media; source/event/time and processing disposition retained. |
| `candidate:da4352e99225647759e628826ea18f61caf5be7e334adc4a3e757d8c71323b50` | candidate_body | Personal non-product anecdote associated with excluded private media; source/event/time and processing disposition retained. |
| `candidate:b85bb2bfc629e5faab66cee5550ab58eb9975b76aae0a8c0ea5c755c5c377e2c` | candidate_body | Personal non-product anecdote associated with excluded private media; source/event/time and processing disposition retained. |

## Removed or relocated field accounting

The following counts are field occurrences visited across current records, retained business versions and nested objects. They are not distinct-record counts. Sensitive fields are removed; material/source historical verification booleans are relocated to detached evidence; nonportable runtime fields are omitted. Structured source labels and business content remain included.

| Original field name | Removed/relocated occurrences |
| --- | ---: |
| `account_native_id` | 2 |
| `activation_baseline` | 9 |
| `analyzed` | 2 |
| `attempts` | 346 |
| `batch_size` | 9 |
| `capabilities` | 2 |
| `change_stamp` | 2 |
| `checkpoint` | 2 |
| `created_checkpoints` | 1 |
| `created_jobs` | 1 |
| `cursor` | 18 |
| `cutoff_at` | 2 |
| `evidence_references` | 1 |
| `expires_at` | 367 |
| `identity_evidence` | 3 |
| `identity_verified` | 209 |
| `job_id` | 9 |
| `last_cutoff` | 9 |
| `last_error` | 310 |
| `manifest` | 1 |
| `manifest_sha256` | 1 |
| `media_failures` | 2 |
| `migration` | 2 |
| `native_id` | 2 |
| `native_id_verified` | 149 |
| `native_source_bytes` | 87 |
| `native_source_format` | 87 |
| `native_source_sha256` | 87 |
| `new_event_evidence` | 9 |
| `next_retry_at` | 73 |
| `next_run_at` | 9 |
| `originals` | 2 |
| `parse_gaps` | 9 |
| `previews` | 2 |
| `private_ref` | 382 |
| `private_source_ref` | 166 |
| `requested_start` | 2 |
| `retired` | 331 |
| `review_metrics_reused` | 2 |
| `scope` | 2 |
| `selected` | 6 |
| `sender_identity_verified` | 143 |
| `snapshot_id` | 9 |
| `source_name` | 2 |
| `unresolved_dates` | 2 |
| `unsupported` | 2 |
| `verification_status` | 3 |

## Verify, import, backup and restore

After fetching this version's assets with the documented private-repository access, run from the source checkout:

```powershell
.\.venv\Scripts\python.exe .\scripts\portable_data.py verify --package .\downloads\travel-advisor-data-v2026.10.30.1.zip
.\.venv\Scripts\python.exe .\scripts\portable_data.py import --package .\downloads\travel-advisor-data-v2026.10.30.1.zip --data-dir "$env:LOCALAPPDATA\TravelAdvisorWorkbench\data"
```

Verification checks package identity, exact file inventory, lengths, SHA-256, schema, SQLite integrity, current and historical business links, source-event links, media associations and embedded attachment ordering. Import verifies before writing, uses a new temporary directory and refuses to overwrite another dataset. Repeating the same package import preserves existing local edits.

For the running imported instance, use `portable_data.py backup --url http://127.0.0.1:8767 --output .\backup-imported.zip`; restore with `portable_data.py restore --archive .\backup-imported.zip --data-dir NEW_EMPTY_DIRECTORY`. Backup uses the application's lock and SQLite backup mechanism; restore validates assets and relationships into a fresh directory. It does not replace the original installation.

The data ZIP was packed and verified by the executable tool. **7 targeted portability tests passed** in the fresh staging environment, including large IDs, shared blobs, URL/path sanitization, PNG derivative metadata, repeat-safe import, tamper/traversal rejection and consistent backup/restore preserving later business edits. Local and remotely obtained deployment/UI/operation checks are reported separately in [RELEASE_VALIDATION.md](RELEASE_VALIDATION.md). See [CODEX_DEPLOYMENT.md](CODEX_DEPLOYMENT.md) for the full independent command sequence and next-release export procedure, and [DEPLOYMENT.zh-CN.md](DEPLOYMENT.zh-CN.md) for Chinese operating instructions.
