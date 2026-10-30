> Historical engineering evidence. Sanitized for distribution; counts and local instructions below are dated history. Follow README.md and docs/CODEX_DEPLOYMENT.md for this release. This file does not authorize collection. Historical local screenshots/native evidence are excluded; current retained data is in the release dataset.

# Relevance-first background processing — 2026-10-28

The deployed collector now checks relevance before creating business materials. Its workflow is **read selected-source content → inspect necessary text/media → decide relevance → retain useful product information**. Processing receipts preserve progress for every outcome, including skipped events. The normal material library is no longer a copy of the selected conversation or Moments history.

**Final reviewed result:** **9 active materials = 7 relevant automatic materials + 2 protected earlier materials**. Across the 290 authorized events, the final dispositions are **7 keep, 211 skip, 56 pending relevance and 16 acquisition retry**. All **25 original business-record hashes and 13 original files remain unchanged**; **25 unreferenced blobs were removed in total**. The final code passed **259 tests, 0 skipped, 2 existing warnings, 27.39 seconds**. The initial 11-material checkpoint below is preserved to show the two false positives found and corrected during review.

| Final selected-source dispositions | Keep | Skip | Pending relevance | Acquisition retry |
| --- | ---: | ---: | ---: | ---: |
| Moments | 6 | 5 | 9 | 1 |
| One-to-one chat | 1 | 206 | 47 | 15 |
| Total | **7** | **211** | **56** | **16** |

Final evidence: [applied exact-image review](../.local/relevance-20261028T100157Z/image-review-applied.json), [reviewed delivery audit](../.local/relevance-20261028T100157Z/delivery-audit-reviewed.json), [final blob count](../.local/relevance-20261028T100157Z/final-blob-count.json), [delivered regression](../.local/relevance-20261028T100157Z/regression-delivered.xml).

The seven accepted automatic materials have **seven saved image occurrences, six distinct byte hashes, and no missing retained attachment**. The 16 acquisition failures remain in their separate candidate/retry path; they are not missing attachments on the accepted seven. [Retained-media verification](../.local/relevance-20261028T100157Z/retained-media-final.json). The [final reviewed workbench screenshot](../.local/relevance-20261028T100157Z/workbench-products-reviewed.png) shows the nine-material library.

This report supersedes the all-record ingestion and repeated historical traversal described in [the earlier October 28 integration report](BACKGROUND_SYNC_2026-10-28.md). That report's **21 Moments posts, 269 chat records and 98 saved image occurrences** remain valid dated acquisition observations. They are not the current useful-material count. Earlier evidence remains available for audit and rollback.

## Scope and initial migration checkpoint

The account remains **采集账号** (`collector-account-002`). Only **罗18955311550** (`wxid_8n1ox3efqcat11`)'s authored Moments and the exact one-to-one conversation, both directions, are authorized. Other sources remain suspended. Business data remains at `C:\TravelWorkbenchData`, and the workbench remains at `http://127.0.0.1:8765/`.

Account/process/directory/friend binding and passive read-only access restrictions remain in force. No foreground collection, account switching, native database writes, hooks, debugger attachment, injection or test messages/posts were introduced. AI provider configuration remains deferred.

The live migration completed at **18:43:17 Asia/Shanghai** (`10:43:17 UTC`). It reduced the active material library from **292 to 11**: **9 relevant automatic materials and 2 protected earlier materials**. It did not remove the entire chat source or force the result to match the two original sample promotions.

| Selected-source events | Examined | Retained as product relevant | Skipped | Pending relevance | Acquisition retry |
| --- | ---: | ---: | ---: | ---: | ---: |
| Friend's Moments | 21 | 6 | 5 | 9 | 1 |
| Exact one-to-one chat | 269 | 3 | 204 | 47 | 15 |
| Total | **290** | **9** | **209** | **56** | **16** |

The 72 staging entries comprise 56 relevance candidates and 16 acquisition failures. Only relevance candidates appear as optional candidate cards; acquisition failures are separately aggregated. The 209 skipped events have receipts, not ordinary material cards.

Evidence: [decision manifest](../.local/relevance-20261028T100157Z/decision-manifest.json), [pre-migration baseline](../.local/relevance-20261028T100157Z/baseline.json), [live migration result](../.local/relevance-20261028T100157Z/migration-live.json).

## Processing receipts and relevance decisions

The minimal ledger records account/source identity, lossless native event identity, revision fingerprint, disposition, rule version, reason and processing time. It also retains the limited association and decision metadata required to preserve explicit corrections and reconsider verified product replies. Receipts are separate from `materials`, product search and recommendation input. Removing an irrelevant material does not remove its receipt or reset the source cursor.

The four dispositions are:

| Disposition | Storage and processing behavior |
| --- | --- |
| `KEEP_PRODUCT_RELEVANT` | Create or update useful material and its necessary source/attachment evidence. An explicitly linked short reply can supplement its parent material. |
| `SKIP_IRRELEVANT` | Commit a minimal receipt and advance progress. Do not keep unrelated body text or personal images as permanent business artifacts. |
| `PENDING_RELEVANCE` | Keep a bounded candidate separate from the business corpus. Missing recognition evidence is not a negative decision. |
| `RETRY_ACQUISITION` | Keep acquisition work distinguishable from relevance. Missing bytes or an unreadable format do not establish irrelevance. |

The material writer, receipts, candidate changes and batch checkpoint commit atomically. Duplicate or unchanged accepted/skipped revisions do not create new materials or trigger routine reclassification. New related evidence can cause targeted reconsideration; a rule-version change does not automatically launch full historical reanalysis.

Relevant evidence includes tour promotions, itineraries, departures, prices and quotation conditions, accommodation/transport/meals, inclusions/exclusions, booking requirements, availability and product changes or cancellations. A price is not mandatory for a flyer. A destination mention or a phone number in the contact name is insufficient. Short price/seat replies require a verified reply relationship and product context; time proximity alone is not used as a link. Related context is displayed with the retained material rather than making each message a separate card.

Explicit user decisions and existing trusted inspection labels are preserved. Of the nine positive migration decisions, **three use trusted product classifications and six use local OCR product evidence**. This is a result for these records, not an estimate of general visual-classification accuracy. In the known eight-post sample, the two confirmed promotions remain relevant, the five confirmed sharing/personal/other posts are excluded from ordinary materials, and the uncertain post stays separate. The later manually corrected Northern Xinjiang promotion is outside those eight.

Historical publication dates and offer conditions remain attached to retained material. Relevance does not establish present availability, a current quotation or bookability.

### Review of the OCR-based positives

All **six OCR-positive occurrences, covering five distinct saved images**, received a subsequent exact-image visual review. Four occurrences contained usable travel-product information. Two chat occurrences were business-planning infographics and were false positives; their travel-related example vocabulary was insufficient evidence of an actual product. This finding is why the initial 9-kept / 209-skipped / 11-material totals above are a dated migration checkpoint rather than final acceptance.

The initial exact-image regression under rule `.2`, and the subsequent `.3` attempt, did not reject both negative examples. These failures were retained. The narrow planning-context guard under rule `.4` was then verified on the actual two images: both returned `SKIP_IRRELEVANT` with `OCR_NONPRODUCT_PLANNING_EVIDENCE`. See [exact-image review](../.local/relevance-20261028T100157Z/image-review-exact.json) and [successful guard verification](../.local/relevance-20261028T100157Z/image-review-guard-v4.json).

This is a localized rule correction and review of a finite set of saved images. It does not establish general automatic image-understanding accuracy. Exact inspection decisions are bound to the source event and byte hashes; unrelated uploads and protected user decisions remain outside the cleanup scope. All six reviews were applied: four positive occurrences retained their product evidence, while the two negative chat occurrences were removed through the receipt pipeline. The library changed from 11 to **9** materials and the ledger from 209 to **211** skips. [Applied review evidence](../.local/relevance-20261028T100157Z/image-review-applied.json).

## Temporary inspection and retention

Image-only records can reach inspection with an empty caption. The existing local RapidOCR route is used where available; only lines with confidence **at least 0.90** contribute text evidence. Inspection is bounded to **three images and a 20-second record budget**, with byte, pixel and output limits. Missing models, timeouts, absent files and unsupported formats remain unresolved or acquisition failures. They are not silently converted to irrelevant results.

Necessary bytes first enter temporary staging. Relevant bytes can be promoted into managed storage. Confirmed unrelated temporary copies are removed when no retained reference requires them. Candidates have a **seven-day** retention deadline, a **200-entry per-source** limit and a **256 MiB staging** bound. Acquisition retries use backoff. Expiration or capacity eviction records that reason and never means “confirmed irrelevant.”

The backup evaluation performed **290 relevance decisions, 62 OCR operations and one OCR cache hit across 63 inspected media occurrences**. Those operations happened once against the backup's saved content. Live application of the decision manifest read the 290 selected native records to reconcile identity/revision and reused the recorded outcomes: it performed **zero additional classification or OCR operations**. Migration replay fields that carry decision metrics must not be added to the backup-review counters as a second recognition run. The [metadata finalization](../.local/relevance-20261028T100157Z/metadata-finalization.json) records this distinction and the update of six automatic product labels; trusted manual/inspection labels were untouched.

## One-time history and incremental updates

Each source persists `INITIAL_HISTORY_PENDING`, `INITIAL_HISTORY_RUNNING`, `INITIAL_LOCAL_HISTORY_PROCESSED`, then `INCREMENTAL_ACTIVE`. The first history task processes the chosen half-open date range once and preserves its boundary and cursor. Committed progress survives pause/restart. The completed initial state is not reset by resuming a normal job.

Normal update checks now default to **300 seconds**, configurable from 30 to 3,600 seconds. “立即检查” requests a check without resetting progress. Explicit “补充历史资料” runs an additional range, and its reprocessing option deliberately revisits already processed revisions while preserving user decisions. History, incremental and media-recovery progress remain independent.

On a warm bound session, ordinary checks first compare stable metadata and bounded DB/WAL edge samples. An unchanged stamp skips snapshot copying, index traversal, body parsing, OCR and media retrieval. This stamp is a change hint, not proof that every byte is unchanged.

When the stamp changes, or the separately bounded **hourly forced reconciliation** is due, the adapter creates an authenticated local snapshot and compares native event IDs and revision fingerprints with the ledger/source index. The broader index path reads and hashes native payload bytes; it does not parse already known unchanged message bodies into content or reclassify them. Snapshot copying and payload hashing remain explicit costs in the metrics. Only new/changed revisions and due targeted work enter content processing. This discovers newly available older records by event identity rather than relying solely on publication-time watermarks. A baseline can record existing out-of-range identities without promoting their bodies.

Available local history remains different from complete remote history. Neither the new ledger nor the incremental index retrieves records absent from native local storage.

## Reversible migration and preservation

The pre-change rollback backup is [backup-20261028T100157-04ce6b.zip](C:/TravelWorkbenchData/backups/backup-20261028T100157-04ce6b.zip), stored under the application's local `backups` directory. Its verified baseline includes record hashes and a file manifest without reproducing source bodies in the engineering JSON. This backup is outside normal business search; it is a rollback artifact, not a newly maintained archive of excluded conversation.

The affected continuous/history/media jobs were paused before applying the gate and dispositions. Backup evaluation and an isolated rehearsal preceded the live migration. Relevant material and its evidence were retained, unresolved content moved to staging, and confirmed unrelated material/attachment rows and associated business revisions were removed. Their processing receipts and committed source progress remain. Retries for discarded attachments no longer run.

All **25 protected earlier records** matched their baseline hashes after migration; the difference list is empty. The two original manually collected materials and existing products, cases, recommendations, exports and weekly collections were preserved. One automatically imported material with an explicit user decision was also recognized as a protected exception; it remains included among the seven final positive imports and does not add an extra material.

Cleanup checks retained current records, revisions, pending candidates and protected business references before removing an owned content-addressed blob. Shared bytes required by any retained object remain. The initial migration removed **23 unreferenced blob files**; exact-image review removed two further unused blobs, for a **final total of 25**. Non-owned paths were rejected as cleanup targets. SQLite `secure_delete`, WAL truncation and `VACUUM` were used to remove retired business bodies from active database storage; this does not make a claim about forensic erasure of operating-system or device backups. Original WeChat databases and caches were untouched.

After the image-review correction, [the reviewed delivery audit](../.local/relevance-20261028T100157Z/delivery-audit-reviewed.json) again verified all **25 original business-record hashes and 13 original files unchanged**. All **211 skipped events** were absent from active material cards, removed-material revisions and protected business references. Only the required minimal skip receipts remain. [The final blob reconciliation](../.local/relevance-20261028T100157Z/final-blob-count.json) distinguishes the initial cleanup from the two later removals.

For rollback, first stop the application's background workers and restore the identified backup to an independent directory using the existing backup/restore verification flow. Verify its manifest and business links before changing the application's data-directory configuration. Keep the current corrected directory and rollback archive until validation completes. Restoring the old dataset would also restore the earlier all-record corpus, so do not resume the old collector as a normal workflow.

## Live unchanged-cycle and restart verification

The recorded verification window is **18:46:23.435399–18:46:38.397672 Asia/Shanghai** (`10:46:23.435399–10:46:38.397672 UTC`), about 15 seconds. Two immediate checks were exercised for each exact authorized source; these were verification checks, not two naturally elapsed five-minute intervals.

| Per-source operation in each of the two checks | Chat | Moments |
| --- | ---: | ---: |
| Metadata/edge bytes sampled | 49,152 | 16,384 |
| Snapshot copies | 0 | 0 |
| Native rows/index entries inspected | 0 / 0 | 0 / 0 |
| Index payload bytes hashed | 0 | 0 |
| Content reads / new or changed events | 0 / 0 | 0 / 0 |
| Classification / OCR operations | 0 / 0 | 0 / 0 |
| Media retrieval operations | 0 | 0 |
| Materials retained or updated | 0 / 0 | 0 / 0 |

The **11 material IDs were unchanged**, and the skipped records did not reappear after jobs resumed. The candidate summary remained 56 pending relevance and 16 acquisition retries. Independent media checks in this window had no due candidate retries or downloads. These results show the unchanged fast path; they do not imply that every future poll has zero work or that forced reconciliation is free.

No genuine new native post/message appeared during the finite window. **Real new-event discovery remains `NOT_TESTED`**. Fixture tests exercise deterministic new relevant/irrelevant events, changed revisions, late arrivals, receipt persistence and deduplication; they do not turn an empty live observation into a new-content pass. Evidence: [live two-cycle verification](../.local/relevance-20261028T100157Z/live-two-cycles.json).

A second observation after the managed restart ran from **18:55:17.193323 to 18:55:33.146270 Asia/Shanghai**. Again, all four source-check results had zero content reads, new/changed events, classification, OCR, media retrieval, material creation or updates. Index work was nonzero and is reported separately:

| Post-restart check | Snapshot copies | Native rows / index entries | Index payload bytes hashed |
| --- | ---: | ---: | ---: |
| Chat 1 | 1 | 51 / 50 | 21,285 |
| Moments 1 | 1 | 21 / 21 | 94,344 |
| Chat 2 | 0 | 51 / 50 | 20,622 |
| Moments 2 | 0 | 0 / 0 | 0 |

The chat index continued its committed batch cursor; the second Moments check used the unchanged fast path. These are zero-content-processing results, not zero-I/O results. Material IDs remained unchanged at this pre-inspection-correction checkpoint and no genuine new native event appeared. Evidence: [post-restart checks](../.local/relevance-20261028T100157Z/live-after-final-restart.json).

The independent audit at **18:58:56.727117 Asia/Shanghai** verified all **25 original business-record hashes and 13 original files unchanged**. All 209 then-skipped events were absent from active materials, removed-material revisions and product/case/recommendation/weekly/export references; skip receipts contained no body or media. SQLite integrity was `ok`. See [delivery audit](../.local/relevance-20261028T100157Z/delivery-audit.json). A [workbench screenshot](../.local/relevance-20261028T100157Z/workbench-products-final.png) records the UI at that checkpoint; counts in dated screenshots do not override subsequent corrections.

**Final post-review observation:** **19:22:25.678–19:22:41.716 Asia/Shanghai** (`11:22:25.678–11:22:41.716 UTC`). Two checks per selected source again produced **zero snapshot copies, index inspections, content reads, classifications, OCR operations, downloads or material changes**. The final **nine material IDs were unchanged**, and the two removed false positives did not reappear. No real new native event arrived, so new-content acceptance remains `NOT_TESTED`. This finite unchanged-source proof is recorded in [live-reviewed-final.json](../.local/relevance-20261028T100157Z/live-reviewed-final.json); it does not replace the separate nonzero-index post-restart measurements above.

## Running jobs and Chinese workbench

At the recorded cycle checkpoint, the four existing normal jobs were resumed with the same identities:

| Source | Mode | Interval | Job ID | Recorded state |
| --- | --- | ---: | --- | --- |
| Moments | Incremental | 300 s | `a244f9af673a4067976f5daea24fd171` | `WAITING`, active |
| One-to-one chat | Incremental | 300 s | `5351a146bad8453992333b774e2d8772` | `WAITING`, active |
| Moments | Independent media | 30 s | `81d3a61881434d25a253bf6518639ad9` | `WAITING`, active |
| One-to-one chat | Independent media | 30 s | `77fbbd8e2fac4352a9e6c50ca007480f` | `WAITING`, active |

Existing all-history/date-range jobs and the migration history checkpoints remain `COMPLETED_LOCAL`. That means their available local range was processed, not that all remote history is available. The managed application was restarted after final runtime fixes at **18:54:43 Asia/Shanghai**, retaining the active job identities. A final post-restart runtime observation can supersede the explicitly dated cycle checkpoint without changing the migration result.

The **final reviewed-code deployment** started at **19:20:29 Asia/Shanghai** (`11:20:29 UTC`), parent PID **68448**, child PID **4284**, retaining the same four normal active jobs. These are dated process observations from `.local/server.json`, not reusable process authorization. The earlier 18:54 restart is retained as a preceding checkpoint. The final 19:22 checks above verify the reviewed deployment; local-history jobs remain completed and missing-native history remains blocked.

“产品资料” uses the backend's retained material corpus. “待识别” is optional and separate. The source cards distinguish inspected events, newly discovered events, retained product materials, skipped events, pending relevance and missing attachments. Last-cycle details separate index/content reads, classification/OCR, media retrieval and material changes. Quiet checks update status without creating scan-result cards. Accepted materials retain source attribution, original times, related product context and attachment evidence. No per-item approval workflow was introduced. See the [Chinese user guide](../USER_GUIDE.zh-CN.md).

## Verification and remaining limits

**Delivered full regression: 259 passed, 0 skipped, 2 existing warnings, 27.39 seconds**, recorded in [regression-delivered.xml](../.local/relevance-20261028T100157Z/regression-delivered.xml). It includes the final rule `.4`, Latin-boundary refinement and exact-inspection scope protections. TypeScript checking and the Vite production frontend build also passed for the corrected interface.

The **233-pass** [pre-review checkpoint](../.local/relevance-20261028T100157Z/regression-final.xml), subsequent 258-pass run before the last boundary refinement, and earlier 198-test independent/34-test integration runs remain dated intermediate evidence. They are not additive totals. The actual-image failures under `.2`/`.3` and successful `.4` guard check are retained rather than hidden by the final suite. Fixture, native-reader, migration and live evidence remain distinct.

Key implementation files are `backend/background/{relevance,inspection,pipeline,processing_index,migration}.py`, the updated background service/native adapter and Store transaction support, `scripts/migrate_relevance.py`, and `frontend/src/{App,BackgroundSync,api,styles}`. The source-bound reader and account/key/media validation restrictions continue to apply. [The delivered source/build manifest](../.local/relevance-20261028T100157Z/delivery-manifest-reviewed.json) pins 85 local source and build files by SHA-256.

Remaining limitations are explicit: 56 candidates need more relevance evidence, 16 events have acquisition failures, local OCR/rules do not reliably understand all visual or conversational meaning, historical offers are not automatically current, and a true new native event was unavailable for live acceptance. Missing-native history retrieval remains **BLOCKED**. This correction improves ingestion, scheduling and cleanup; it does not claim to solve the separate remote-history limitation.
