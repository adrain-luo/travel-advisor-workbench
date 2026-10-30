"""Atomic relevance receipts, bounded candidates and promotion of useful materials."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import copy
import hashlib
import json
from pathlib import Path
import shutil

from ..store import encode, utcnow, uid
from .relevance import decide, RULE_VERSION, KEEP_PRODUCT_RELEVANT as KEEP, SKIP_IRRELEVANT as SKIP, PENDING_RELEVANCE as PENDING, RETRY_ACQUISITION as RETRY
from .inspection import inspect_record

RETENTION_DAYS = 7
MAX_CANDIDATES = 200
MAX_STAGING_BYTES = 256 * 1024 * 1024


def future(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def metrics():
    return dict.fromkeys(('inspected', 'new', 'kept', 'updated', 'skipped', 'pending',
        'acquisition_failed', 'classification_operations', 'ocr_operations', 'media_inspected',
        'media_retrieval_operations', 'native_rows_inspected', 'index_entries_inspected',
        'index_payload_bytes_hashed', 'content_reads', 'snapshot_copies', 'new_or_changed'), 0)


class RelevancePipeline:
    def __init__(self, store, adapter=None):
        self.store, self.adapter = store, adapter
        self.staging = store.root / 'relevance-staging'
        self.staging.mkdir(exist_ok=True)
        self.inflight_paths = {}

    def receipts(self, source_id):
        with self.store.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT data FROM processing_receipts WHERE source_id=?', (source_id,))]

    def known(self, source_id, *, include_baseline=True):
        with self.store.connect() as db:
            known = dict(db.execute('SELECT event_key,revision FROM source_index WHERE source_id=?', (source_id,))) if include_baseline else {}
        known.update({r['event_key']: r['revision_hash'] for r in self.receipts(source_id)})
        for event in self.reconsider_keys(source_id):
            known.pop(event, None)
        return known

    def reconsider_keys(self, source_id):
        rows = self.receipts(source_id)
        accepted = {r.get('native_server_id'): r for r in rows if r['outcome'] == KEEP and r.get('native_server_id')}
        return [r['event_key'] for r in rows if r['outcome'] in {SKIP, PENDING}
            and r.get('reply_target') in accepted and not r.get('classification')
            and r.get('context_parent_revision') != accepted[r['reply_target']]['revision_hash']][:20]

    def candidates(self):
        with self.store.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT data FROM pending_candidates')]

    def public_candidates(self):
        rows = self.candidates()
        receipts = [r for s in self.store.all('sources') for r in self.receipts(s['id'])]
        return {'items': [{'id': r['id'], 'source_id': r['source_id'],
            'publication_time': r['item'].get('publication_time') or r['item'].get('source_time'),
            'reason': r['reason_code'], 'reason_code': r['reason_code'], 'outcome': r['outcome'], 'disposition': r['outcome'],
            'expires_at': r['expires_at'], 'next_retry_at': r.get('next_retry_at'), 'imported': bool(r.get('imported')),
            'attachments': [{'index': i, 'name': a.get('name') or ('附件 ' + str(i + 1)),
                'mime': a.get('mime', 'application/octet-stream'), 'quality': a.get('quality'), 'state': a.get('state'),
                'url': f"/api/background/candidates/{r['id']}/attachments/{i}"
                    if r.get('imported') and a.get('state') in {'SAVED', 'STAGED'} and str(a.get('path', '')).startswith('blobs/') else None}
                for i, a in enumerate(r['item'].get('attachments', []))],
            'text': r['item'].get('text', '')[:1000], 'attachment_count': len(r['item'].get('attachments', []))} for r in rows],
            'summary': {'pending': sum(r['outcome'] == PENDING for r in rows),
                'acquisition_failed': sum(r['outcome'] == RETRY for r in rows),
                'expired': sum(r.get('reason_code') in {'PENDING_EXPIRED', 'STAGING_CAPACITY_EXPIRED'} for r in receipts)}}

    def prior(self, source, item):
        with self.store.connect() as db:
            row = db.execute("SELECT r.data FROM source_events e JOIN records r ON r.kind='materials' AND r.id=e.item_id WHERE e.source_id=? AND e.event_key=? ORDER BY e.rowid DESC LIMIT 1",
                (source['id'], item['event_key'])).fetchone()
        return json.loads(row[0]) if row else None

    def context(self, source, item):
        reply = item.get('reply') or {}
        target = reply.get('native_server_id') or reply.get('native_id')
        verified = reply.get('relationship_verified') or reply.get('verified')
        event = item.get('reply_to_event_key')
        if not self.reply_scope(source, item) or not verified:
            return None
        matches = []
        for r in self.receipts(source['id']):
            if r['outcome'] != KEEP or not r.get('material_id'):
                continue
            if (event and r['event_key'] == event) or (target and str(r.get('native_server_id')) == str(target)):
                matches.append(r)
        if len(matches) == 1:
                r = matches[0]
                item['reply_to_event_key'] = r['event_key']
                return {'relationship_verified': True, 'relationship': 'explicit_reply',
                    'parent_event_key': r['event_key'], 'parent_outcome': KEEP,
                    'parent_native_id': str(target), 'account_id': source['account_id'],
                    'account_native_id': source.get('account_native_id'),
                    'source_id': source['id'], 'conversation_id': item.get('conversation_id')}
        return None

    @staticmethod
    def reply_scope(source, item):
        reply = item.get('reply') or {}
        return (source.get('kind') == 'chat' and item.get('conversation_id') == source.get('native_id')
            and reply.get('conversation_id', source['native_id']) == source['native_id']
            and reply.get('account_id', source.get('account_native_id')) == source.get('account_native_id')
            and reply.get('relationship', 'explicit_reply') == 'explicit_reply')

    def prepare(self, source, incoming, *, decision=None, retrieve=True, classification_override=None):
        item = copy.deepcopy(incoming)
        item.update(account_id=source['account_id'], source_id=source['id'])
        item.setdefault('source_kind', source['kind'])
        prior = self.prior(source, item)
        if not prior:
            receipt = next((r for r in self.receipts(source['id']) if r['event_key'] == item['event_key']), {})
            if receipt.get('classification'):
                item['classification'] = receipt['classification']
        if prior:
            if prior.get('classification', {}).get('origin') in {'manual', 'inspection'}:
                item['classification'] = prior['classification']
            saved = {(str(a.get('native_id')), a.get('media_index')): a for a in prior.get('attachments', [])}
            for a in item.get('attachments', []):
                old = saved.get((str(a.get('native_id')), a.get('media_index')), {})
                if old.get('state') == 'SAVED':
                    a.update({k: v for k, v in old.items() if k not in {'private_ref', 'retrieval_reference'}})
                elif old.get('classification', {}).get('origin') in {'manual', 'inspection'}:
                    a['classification'] = old['classification']
        if classification_override is not None:
            item['classification'] = classification_override
        context = self.context(source, item)
        decision = copy.deepcopy(decision) if decision else decide(item, reply_context=context)
        downloads = 0
        if decision.get('needs_inspection'):
            for a in item.get('attachments', [])[:3]:
                if a.get('path') and (self.store.root / a['path']).is_file():
                    continue
                if retrieve and self.adapter and self.staging_bytes() < MAX_STAGING_BYTES:
                    before_paths = {p.resolve() for p in self.staging.iterdir() if p.is_file()}
                    downloads += 1
                    result = self.adapter.retrieve(a, self.staging)
                    if result.get('state') == 'SAVED':
                        path = Path(result['path']).resolve()
                        if not path.is_relative_to(self.staging.resolve()):
                            raise ValueError('INSPECTION_STAGING_PATH_INVALID')
                        if self.staging_bytes() > MAX_STAGING_BYTES:
                            if path not in before_paths and path.is_file():
                                path.unlink()
                            continue
                        if path.stat().st_size <= 32 * 1024 * 1024:
                            a.update(path=str(path.relative_to(self.store.root)), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                size=path.stat().st_size, mime=result.get('mime', 'application/octet-stream'), state='STAGED')
                            self.inflight_paths[str(path)] = future(RETENTION_DAYS * 86400)
            inspected = inspect_record(item, allowed_root=self.store.root)
            decision = decide(item, inspection=inspected, reply_context=context)
        decision.setdefault('metrics', {})['media_retrieval_operations'] = downloads
        item['relevance'] = {k: decision[k] for k in ('outcome', 'rule_version', 'reason_code')}
        if decision['outcome'] == KEEP and item.get('classification', {}).get('origin') not in {'manual', 'inspection'}:
            item['classification'] = {'label': 'travel_promotion', 'origin': 'rule', 'updated_at': utcnow(),
                'evidence': '命中旅游产品相关性规则；保留历史日期与报价条件，不代表当前可订。'}
        # Only positive candidates enter the managed blob collection.
        if decision['outcome'] == KEEP:
            for a in item.get('attachments', []):
                if a.get('state') == 'STAGED':
                    path = self.store.root / a['path']
                    a.update(self.store.staged_asset(path, self.staging, name=a.get('name'), mime=a.get('mime')))
                    a.update(state='SAVED', media_state='VALIDATED', validated_at=utcnow())
                    self.inflight_paths.pop(str(path.resolve()), None)
        elif decision['outcome'] in {PENDING, RETRY}:
            # Existing automatic blobs move to expiring staging before their cards are removed.
            for a in item.get('attachments', []):
                if a.get('path') and not str(a['path']).startswith('relevance-staging'):
                    src = (self.store.root / a['path']).resolve()
                    if src.is_relative_to(self.store.root) and src.is_file():
                        if self.staging_bytes() + src.stat().st_size <= MAX_STAGING_BYTES:
                            dest = self.staging / (a.get('sha256') or hashlib.sha256(src.read_bytes()).hexdigest())
                            if not dest.exists():
                                shutil.copyfile(src, dest)
                            a['path'] = str(dest.relative_to(self.store.root))
                            a['state'] = 'STAGED'
                            self.inflight_paths[str(dest.resolve())] = future(RETENTION_DAYS * 86400)
                        else:
                            for field in ('path', 'inspection_path'):
                                a.pop(field, None)
        return item, decision

    def prepare_page(self, source, items):
        prepared = [self.prepare(source, i) for i in items]
        parent_lists = {}
        for i, d in prepared:
            key = str(i.get('native_server_id') or i.get('server_id') or i.get('provenance', {}).get('server_id'))
            if d['outcome'] == KEEP and not d.get('context_event_key') and key not in {'None', '0', ''}:
                parent_lists.setdefault(key, []).append(i)
        parents = {k: v[0] for k, v in parent_lists.items() if len(v) == 1}
        for index, (item, decision) in enumerate(prepared):
            reply = item.get('reply') or {}
            parent = parents.get(str(reply.get('native_server_id') or reply.get('native_id')))
            if parent and self.reply_scope(source, item) and (reply.get('relationship_verified') or reply.get('verified')):
                item['reply_to_event_key'] = parent['event_key']
                context = {'relationship_verified': True, 'relationship': 'explicit_reply',
                    'parent_event_key': parent['event_key'], 'parent_outcome': KEEP,
                    'parent_native_id': reply.get('native_server_id') or reply.get('native_id'),
                    'account_id': source['account_id'], 'account_native_id': source.get('account_native_id'),
                    'source_id': source['id'], 'conversation_id': item.get('conversation_id')}
                revised = decide(item, reply_context=context)
                if revised.get('context_event_key'):
                    revised['metrics'] = {k: decision.get('metrics', {}).get(k, 0) + revised['metrics'].get(k, 0)
                        for k in set(decision.get('metrics', {})) | set(revised['metrics'])}
                    prepared[index] = item, revised
        return sorted(prepared, key=lambda pair: bool(pair[1].get('context_event_key')))

    def staging_bytes(self):
        return sum(p.stat().st_size for p in self.staging.iterdir() if p.is_file())

    @staticmethod
    def remove_material(db, ident):
        assets = [json.loads(r[0]) for r in db.execute("SELECT data FROM records WHERE kind='attachments'")]
        ids = [a['id'] for a in assets if a.get('material_id') == ident]
        for kind, keys in (('materials', [ident]), ('attachments', ids)):
            for key in keys:
                db.execute('DELETE FROM records WHERE kind=? AND id=?', (kind, key))
                db.execute('DELETE FROM revisions WHERE kind=? AND id=?', (kind, key))
        db.execute('DELETE FROM source_events WHERE item_id=?', (ident,))

    def commit(self, source, prepared, page, job, *, protected=None):
        protected = protected or {}
        batch = metrics()
        batch.update({k: v for k, v in page.get('metrics', {}).items() if isinstance(v, int)})
        batch['inspected'] = len(prepared)
        to_discard = []
        removed_assets = []
        originals = {item['event_key']: self.prior(source, item) for item, _ in prepared}
        with self.store.lock, self.store.connect() as db:
            from .migration import protected_materials
            protected = {**protected, **protected_materials(self.store,
                expected_account=source.get("account_native_id"), expected_friend=source.get("native_id"))}
            originals = {item['event_key']: self.prior(source, item) for item, _ in prepared}
            for item, decision in prepared:
                if decision['outcome'] == KEEP:
                    for a in item.get('attachments', []):
                        if a.get('state') == 'STAGED':
                            incoming_path = (self.store.root / a['path']).resolve()
                            a.update(self.store.staged_asset(incoming_path, self.staging,
                                name=a.get('name'), mime=a.get('mime')))
                            a.update(state='SAVED', media_state='VALIDATED', validated_at=utcnow())
                            self.inflight_paths.pop(str(incoming_path), None)
            # The existing material writer now participates in this same transaction.
            def may_update(item):
                prior = originals[item['event_key']] or {}
                reasons = protected.get(prior.get('id'), [])
                classification_only = (set(reasons) <= {'EXPLICIT_USER_DECISION_OR_EDIT'}
                    and prior.get('classification', {}).get('origin') == 'manual'
                    and not prior.get('user_edited') and prior.get('edited_by') not in {'user', 'manual'}
                    and prior.get('origin') != 'manual')
                return not reasons or classification_only and not job.get('migration')
            kept = [item for item, d in prepared if d['outcome'] == KEEP and not d.get('context_event_key') and may_update(item)]
            self.store.ingest_background_page(source, kept, page, job, db=db)
            for item, decision in prepared:
                oldrow = db.execute('SELECT data FROM processing_receipts WHERE account_id=? AND source_id=? AND event_key=?',
                    (source['account_id'], source['id'], item['event_key'])).fetchone()
                old = json.loads(oldrow[0]) if oldrow else {}
                revision = item.get('native_revision') or item.get('source_revision_hash') or hashlib.sha256(encode(item).encode()).hexdigest()
                expiry = old.get('expires_at') if revision == old.get('revision_hash') else None
                expiry = expiry or future(RETENTION_DAYS * 86400)
                prior = originals[item['event_key']]
                outcome = decision['outcome']
                ident = (prior or {}).get('id')
                exception = protected.get(ident)
                if (outcome != KEEP and not job.get('migration') and may_update(item)
                        and item.get('classification', {}).get('origin') == 'manual'):
                    # Explicit negative/uncertain decisions are preserved as receipts,
                    # while unrelated source bodies leave the active product list.
                    exception = None
                batch['new'] += int(not old)
                for k, v in decision.get('metrics', {}).items():
                    batch[k] = batch.get(k, 0) + v
                candidate_id = hashlib.sha256((source['id'] + '\0' + item['event_key']).encode()).hexdigest()
                db.execute('DELETE FROM pending_candidates WHERE id=?', (candidate_id,))
                context_event = decision.get('context_event_key')
                if outcome == KEEP and context_event:
                    parentrow = db.execute('SELECT data FROM processing_receipts WHERE source_id=? AND event_key=?', (source['id'], context_event)).fetchone()
                    parentreceipt = json.loads(parentrow[0]) if parentrow else {}
                    parent_id = parentreceipt.get('material_id')
                    parentrow = db.execute("SELECT data FROM records WHERE kind='materials' AND id=?", (parent_id,)).fetchone()
                    if parentrow:
                        parent = json.loads(parentrow[0])
                        context_items = {c['event_key']: c for c in parent.get('product_context', [])}
                        context_items[item['event_key']] = {k: item.get(k) for k in ('event_key', 'native_id', 'native_server_id', 'text', 'author_id', 'source_time', 'publication_time')}
                        for asset in item.get('attachments', []):
                            old_asset = next((a for a in parent.get('attachments', []) if a.get('context_event_key') == item['event_key']
                                and a.get('media_index') == asset.get('media_index')), {})
                            linked = self.store.put('attachments', {**asset, 'id': old_asset.get('id') or uid(),
                                'material_id': parent_id, 'source_id': source['id'], 'account_id': source['account_id'],
                                'context_event_key': item['event_key'], 'acquisition_mode': 'background'}, db=db)
                            parent['attachments'] = [a for a in parent.get('attachments', []) if a['id'] != linked['id']] + [linked]
                        parent['product_context'] = list(context_items.values())
                        self.store.put('materials', parent, db=db)
                        if ident and ident != parent_id and not exception:
                            self.remove_material(db, ident)
                        ident = parent_id
                        batch['updated'] += 1
                    else:
                        outcome = PENDING
                        decision = {**decision, 'reason_code': 'EXPLICIT_PARENT_NOT_AVAILABLE'}
                elif outcome == KEEP:
                    ident = db.execute('SELECT item_id FROM source_events WHERE source_id=? AND event_key=? ORDER BY rowid DESC LIMIT 1',
                        (source['id'], item['event_key'])).fetchone()[0]
                    if may_update(item):
                        batch['updated' if prior else 'kept'] += 1
                if outcome != KEEP:
                    if ident and not exception:
                        removed_assets.extend((prior or {}).get('attachments', []))
                        if prior:
                            to_discard.append(prior)
                        self.remove_material(db, ident)
                        ident = None
                    batch['skipped' if outcome == SKIP else 'acquisition_failed' if outcome == RETRY else 'pending'] += 1
                    if outcome in {PENDING, RETRY} and not exception:
                        candidate = {'id': candidate_id, 'source_id': source['id'], 'account_id': source['account_id'],
                            'item': item, 'outcome': outcome, 'reason_code': decision['reason_code'],
                            'created_at': utcnow(), 'expires_at': expiry,
                            'attempts': old.get('attempts', 0) + 1,
                            'next_retry_at': future(min(86400, 300 * 2 ** min(old.get('attempts', 0), 8))) if outcome == RETRY else None}
                        db.execute('INSERT INTO pending_candidates VALUES(?,?,?)', (candidate_id, source['id'], encode(candidate)))
                    elif outcome == SKIP and not exception:
                        to_discard.append(item)
                accepted_row = db.execute("SELECT data FROM records WHERE kind='materials' AND id=?", (ident,)).fetchone() if ident else None
                discovered = json.loads(accepted_row[0]).get('first_discovered_at') if accepted_row else None
                receipt = {'account_id': source['account_id'], 'source_id': source['id'],
                    'event_key': item['event_key'], 'native_id': str(item.get('native_id') or item.get('native_post_id') or item['event_key']),
                    'native_server_id': str(item.get('native_server_id') or item.get('server_id') or item.get('provenance', {}).get('server_id') or ''),
                    'revision_hash': revision,
                    'outcome': outcome, 'rule_version': decision.get('rule_version', RULE_VERSION),
                    'reason_code': decision['reason_code'], 'processed_at': utcnow(), 'material_id': ident,
                    'first_discovered_at': old.get('first_discovered_at') or (prior or {}).get('first_discovered_at') or discovered or utcnow(),
                    'publication_time': item.get('publication_time') or item.get('source_time'),
                    'attempts': old.get('attempts', 0) + 1, 'expires_at': expiry}
                if exception:
                    receipt['protected_exception'] = exception
                reply = item.get('reply') or {}
                if self.reply_scope(source, item) and (reply.get('relationship_verified') or reply.get('verified')):
                    target = str(reply.get('native_server_id') or reply.get('native_id') or '')
                    receipt['reply_target'] = target
                    parent = next((r for r in self.receipts(source['id']) if r.get('native_server_id') == target and r['outcome'] == KEEP), None)
                    if parent:
                        receipt['context_parent_revision'] = parent['revision_hash']
                cls = item.get('classification', {})
                if cls.get('origin') in {'manual', 'inspection'}:
                    receipt['classification'] = {k: cls[k] for k in ('label', 'origin', 'updated_at') if k in cls}
                db.execute('INSERT OR REPLACE INTO processing_receipts VALUES(?,?,?,?)', (source['account_id'], source['id'], item['event_key'], encode(receipt)))
            for item in kept:
                row = db.execute('SELECT item_id FROM source_events WHERE source_id=? AND event_key=? ORDER BY rowid DESC LIMIT 1', (source['id'], item['event_key'])).fetchone()
                r = json.loads(db.execute('SELECT data FROM processing_receipts WHERE source_id=? AND event_key=?', (source['id'], item['event_key'])).fetchone()[0])
                r['material_id'] = row[0]
                db.execute('UPDATE processing_receipts SET data=? WHERE source_id=? AND event_key=?', (encode(r), source['id'], item['event_key']))
            for entry in page.get('baseline_entries', []):
                db.execute('INSERT OR REPLACE INTO source_index VALUES(?,?,?)', (source['id'], entry['event_key'], entry['native_revision']))
            current = json.loads(db.execute("SELECT data FROM records WHERE kind='background_jobs' AND id=?", (job['id'],)).fetchone()[0])
            if job['mode'] == 'continuous':
                evidence = {e['event_key']: e for e in current.get('new_event_evidence', [])}
                baseline = datetime.fromisoformat(job['activation_baseline'])
                for raw in db.execute('SELECT data FROM processing_receipts WHERE source_id=?', (source['id'],)):
                    r = json.loads(raw[0])
                    try:
                        if datetime.fromisoformat(r['publication_time']) > baseline and datetime.fromisoformat(r['first_discovered_at']) >= baseline:
                            evidence.setdefault(r['event_key'], {'event_key': r['event_key'], 'source_time': r['publication_time'],
                                'first_discovered_at': r['first_discovered_at'], 'observation': 'processing_receipt_reconciled'})
                    except (ValueError, TypeError, KeyError):
                        pass
                current['new_event_evidence'] = list(evidence.values())[-100:]
            self.store.put('background_jobs', {**current, 'last_cycle': batch}, db=db)
            processing = self.store.get('source_processing', source['id']) or {}
            state = processing.get('onboarding_state', 'INITIAL_HISTORY_PENDING')
            if job['mode'] == 'history' and job.get('initial_history'):
                state = 'INITIAL_LOCAL_HISTORY_PROCESSED' if page.get('exhausted') and not current.get('parse_gaps') else 'INITIAL_HISTORY_RUNNING'
            if job['mode'] == 'continuous':
                state = 'INCREMENTAL_ACTIVE'
            values = {**processing, 'source_id': source['id'], 'onboarding_state': state,
                'initial_range': processing.get('initial_range', job.get('requested_range')),
                'last_checked_at': utcnow(), 'last_cycle': batch,
                'interval_seconds': processing.get('interval_seconds', 300)}
            if job['mode'] == 'media':
                values['last_cycle'] = processing.get('last_cycle', metrics())
                values['last_checked_at'] = processing.get('last_checked_at')
                values['last_pending_cycle'] = batch
                values['last_pending_checked_at'] = utcnow()
            if page.get('exhausted') and page.get('change_stamp') and (job['mode'] == 'continuous' or job.get('initial_history')):
                values['change_stamp'] = page['change_stamp']
                if not page.get('source_unchanged'):
                    values['last_index_reconciliation_at'] = utcnow()
            self.store.put('source_processing', values, source['id'], db=db)
        for item, _ in prepared:
            for a in item.get('attachments', []):
                if a.get('path'):
                    self.inflight_paths.pop(str((self.store.root / a['path']).resolve()), None)
        self.expire()
        self.cleanup(to_discard)
        if removed_assets:
            from .migration import gc_unreferenced_blobs
            batch['unreferenced_blobs_removed'] = len(gc_unreferenced_blobs(self.store, removed_assets, dry_run=False)['removed'])
        return batch

    def expire(self):
        expired = []
        with self.store.lock, self.store.connect() as db:
            rows = sorted((r for r in self.candidates() if not r.get('imported')), key=lambda r: r['created_at'])
            counts = {}
            for candidate in reversed(rows):
                source = candidate['source_id']
                counts[source] = counts.get(source, 0) + 1
                capacity = counts[source] > MAX_CANDIDATES
                if candidate['expires_at'] > utcnow() and not capacity:
                    continue
                db.execute('DELETE FROM pending_candidates WHERE id=?', (candidate['id'],))
                row = db.execute('SELECT data FROM processing_receipts WHERE source_id=? AND event_key=?', (source, candidate['item']['event_key'])).fetchone()
                if row:
                    r = json.loads(row[0])
                    r.update(reason_code='STAGING_CAPACITY_EXPIRED' if capacity else 'PENDING_EXPIRED', processed_at=utcnow())
                    db.execute('UPDATE processing_receipts SET data=? WHERE source_id=? AND event_key=?', (encode(r), source, r['event_key']))
                expired.append(candidate['item'])
        self.cleanup(expired)
        if expired:
            from .migration import gc_unreferenced_blobs
            gc_unreferenced_blobs(self.store, [{'sha256': a['sha256'], 'path': 'blobs/' + a['sha256'][:2] + '/' + a['sha256']}
                for item in expired for a in item.get('attachments', []) if a.get('sha256')], dry_run=False)

    def cleanup(self, discarded=()):
        with self.store.connect() as db:
            retained = [json.loads(r[0]) for r in db.execute('SELECT data FROM records UNION ALL SELECT data FROM revisions')]
        retained += [r['item'] for r in self.candidates()]
        refs, paths = set(), set()
        def visit(v):
            if isinstance(v, dict):
                for k, value in v.items():
                    if k in {'private_ref', 'private_source_ref'} and isinstance(value, str): refs.add(value)
                    if k in {'path', 'inspection_path'} and isinstance(value, str): paths.add(str((self.store.root / value).resolve()))
                    visit(value)
            elif isinstance(v, list):
                for value in v: visit(value)
        visit(retained)
        for path, deadline in list(self.inflight_paths.items()):
            if deadline > utcnow():
                paths.add(path)
            else:
                self.inflight_paths.pop(path, None)
        discard = getattr(self.adapter, 'discard_private', None)
        if discard and discarded:
            discard(discarded, protected_refs=refs)
        gc = getattr(self.adapter, 'gc_private_references', None)
        if gc:
            gc(refs, older_than_seconds=3600, max_files=1000)
        for path in self.staging.iterdir():
            if path.is_file() and str(path.resolve()) not in paths:
                path.unlink()

    def processing(self, source_id):
        result = self.store.get('source_processing', source_id) or {'onboarding_state': 'INITIAL_HISTORY_PENDING', 'interval_seconds': 300}
        rows = self.receipts(source_id)
        assets = [a for a in self.store.all('attachments') if a.get('source_id') == source_id and not a.get('retired')]
        result['counts'] = {'inspected': len(rows), 'new': len(rows),
            'kept': len({r['material_id'] for r in rows if r['outcome'] == KEEP and r.get('material_id')}),
            'updated': 0, 'skipped': sum(r['outcome'] == SKIP for r in rows),
            'pending': sum(r['outcome'] == PENDING for r in rows),
            'acquisition_failed': sum(r['outcome'] == RETRY for r in rows),
            'media_pending': sum(a.get('state') != 'SAVED' for a in assets)}
        return result
