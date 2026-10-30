"""Durable, source-scoped background jobs; no desktop or foreground adapters."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import sys
import threading
import time
from zoneinfo import ZoneInfo

from ..store import utcnow
from .pipeline import RelevancePipeline

EXPECTED_ACCOUNT = 'fixture-account'
EXPECTED_FRIEND = 'fixture-friend'
POST_LABELS = {'travel_promotion', 'travel_sharing', 'other', 'uncertain'}
FILE_LABELS = {'travel_flyer', 'itinerary_quote', 'scenic_personal', 'screenshot', 'other', 'uncertain'}


def after(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def safe_code(exc):
    code = getattr(exc, 'code', None) or str(exc)
    return code if re.fullmatch(r'[A-Z][A-Z0-9_]{1,100}', code) else 'BACKGROUND_OPERATION_FAILED'


def parse_date(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
    return parsed.isoformat()


def initial_classification(item, file=False):
    if file:
        return {'label': 'uncertain', 'origin': 'rule', 'evidence': '待查看文件内容；不根据文件名推断用途。', 'updated_at': utcnow()}
    text = item.get('text', '')
    # These are provisional text rules, independent from successful ingestion.
    if any(word in text for word in ('双飞', '全陪班', '团期', '收客')):
        return {'label': 'travel_promotion', 'origin': 'rule', 'evidence': '原文含行程销售用语；图片用途需分别核对，历史报价不代表当前可订。', 'updated_at': utcnow()}
    return {'label': 'uncertain', 'origin': 'rule', 'evidence': '已保留原文与附件；尚无充分用途证据。', 'updated_at': utcnow()}


class BackgroundService:
    def __init__(self, store, adapter=None):
        self.store = store
        self._adapter = adapter
        self._injected_adapter = adapter is not None
        self.live_config = self._load_live_config()
        self.stop_event = threading.Event()
        self.thread = None
        self.guard = threading.RLock()
        self.source_locks = {}
        self.access_lock = threading.RLock()
        self.active = set()
        self.pipeline = RelevancePipeline(store, adapter)

    def _load_live_config(self):
        if os.environ.get('TRAVEL_ENABLE_LIVE_COLLECTION') != '1':
            return {}
        path = self.store.root / 'live-binding.json'
        try:
            value = json.loads(path.read_text(encoding='utf-8-sig'))
            required = ('account_native_id', 'account_display_name', 'friend_native_id', 'friend_display_name')
            if (not isinstance(value, dict) or any(not isinstance(value.get(key), str)
                    or not value[key].strip() or value[key].startswith('<') for key in required)):
                return {}
            if value.get('fresh_local_binding') is not True:
                return {}
            return {key: value[key].strip() for key in required}
        except (OSError, ValueError):
            return {}

    @property
    def collection_enabled(self):
        return self._injected_adapter or bool(self.live_config)

    def _require_collection(self):
        if not self.collection_enabled:
            raise ValueError('LIVE_COLLECTION_DISABLED')

    @property
    def expected_account(self):
        return EXPECTED_ACCOUNT if self._injected_adapter else self.live_config.get('account_native_id', '')

    @property
    def expected_friend(self):
        return EXPECTED_FRIEND if self._injected_adapter else self.live_config.get('friend_native_id', '')

    @property
    def account_display(self):
        return '测试采集账号' if self._injected_adapter else self.live_config.get('account_display_name', '尚未绑定本机账号')

    @property
    def friend_display(self):
        return '测试供应商' if self._injected_adapter else self.live_config.get('friend_display_name', '尚未绑定本机来源')

    @property
    def adapter(self):
        self._require_collection()
        if self._adapter is None:
            from .native import BackgroundNative
            self._adapter = BackgroundNative(self.store.root, {
                'expected_account_id': self.expected_account, 'expected_account': self.expected_account,
                'expected_friend_id': self.expected_friend, 'friend_name': self.friend_display,
                'account_display_name': self.account_display,
                'authorization_reference': 'Explicit fresh local background-only account/source configuration'})
        return self._adapter

    def start(self):
        if not self.collection_enabled:
            return
        with self.guard:
            if self.thread and self.thread.is_alive():
                return
            for job in self.store.all('background_jobs'):
                if job['state'] == 'RUNNING':
                    self.store.put('background_jobs', {**job, 'state': 'QUEUED', 'next_run_at': utcnow(),
                        'stop_reason': '应用重启后从已提交进度继续；会重新核对微信账号。'})
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._loop, name='background-sync', daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=45)
        if self._adapter and not (self.thread and self.thread.is_alive()):
            close = getattr(self._adapter, 'close', None)
            if close:
                close()

    def _loop(self):
        last_housekeeping = 0
        while not self.stop_event.is_set():
            if time.monotonic() - last_housekeeping >= 60:
                try:
                    self.pipeline.expire()
                except Exception:
                    # A transient local cleanup failure must not stop all workers.
                    pass
                last_housekeeping = time.monotonic()
            jobs = sorted(self.store.all('background_jobs'), key=lambda j: j.get('next_run_at') or '')
            for job in jobs:
                if self.stop_event.is_set():
                    break
                if job['state'] not in {'QUEUED', 'WAITING', 'RETRY'}:
                    continue
                if job.get('next_run_at') and job['next_run_at'] > utcnow():
                    continue
                try:
                    self.run_once(job['id'])
                except Exception:
                    # Do not log exception values: native transport fields can be private.
                    pass
            self.stop_event.wait(1)

    def bind(self):
        self._require_collection()
        with self.access_lock:
            try:
                binding = self.adapter.bind()
                account = binding.get('account_native_id') or binding.get('account_id')
                friend = binding.get('friend_native_id') or binding.get('friend_id')
                if account != self.expected_account or friend != self.expected_friend:
                    raise ValueError('ACCOUNT_OR_FRIEND_MISMATCH')
                record = self.store.put('accounts', {'display_name': self.account_display, 'native_id': account,
                    'native_id_verified': True, 'acquisition_mode': 'background', 'selected': True},
                    'local-background-account-' + hashlib.sha256(account.encode()).hexdigest()[:24])
                for kind in ('moments', 'chat'):
                    ident = 'local-background-' + kind + '-' + hashlib.sha256((account + '\0' + friend).encode()).hexdigest()[:24]
                    prior = self.store.get('sources', ident) or {}
                    self.store.put('sources', {**prior, 'account_id': record['id'],
                        'account_native_id': account, 'native_id': friend, 'native_id_verified': True,
                        'display_name': self.friend_display, 'kind': kind, 'acquisition_mode': 'background',
                        'selected': True}, ident)
                    if not self.store.get('source_processing', ident):
                        self.store.put('source_processing', {'source_id': ident,
                            'onboarding_state': 'INITIAL_HISTORY_PENDING', 'interval_seconds': 300}, ident)
                public = {'state': 'VERIFIED', 'label': '已验证', 'account_display': self.account_display,
                    'friend_display': self.friend_display, 'account_native_id': account,
                    'friend_native_id': friend, 'last_verified_at': utcnow(),
                    'client_version': binding.get('client_version'), 'error': None}
                self.store.put('background_status', public, 'binding')
                return public
            except Exception as exc:
                public = {'state': 'BLOCKED', 'label': '受阻', 'account_display': self.account_display,
                    'friend_display': self.friend_display, 'error': safe_code(exc),
                    'reason': '当前账号或后台读取尚未验证，请确认微信已正常登录所选账号后重试。',
                    'last_checked_at': utcnow()}
                self.store.put('background_status', public, 'binding')
                raise ValueError(public['error']) from None

    def _source_authorized(self, source):
        return bool(source and not source.get('imported') and source.get('acquisition_mode') == 'background'
            and source.get('native_id') == self.expected_friend
            and source.get('account_native_id') == self.expected_account
            and source.get('kind') in {'moments', 'chat'})

    def create_job(self, body):
        self._require_collection()
        source = self.store.get('sources', body.get('source_id', ''))
        if not self._source_authorized(source):
            raise ValueError('SOURCE_NOT_AUTHORIZED')
        mode = body.get('mode', 'history')
        if mode not in {'continuous', 'history', 'media'}:
            raise ValueError('INVALID_JOB_MODE')
        requested = body.get('range') or {}
        requested = {'start': parse_date(requested.get('start')), 'end': parse_date(requested.get('end'))}
        if requested['start'] and requested['end'] and datetime.fromisoformat(requested['start']) >= datetime.fromisoformat(requested['end']):
            raise ValueError('INVALID_RANGE')
        if mode == 'continuous':
            requested = {'start': None, 'end': None}
        with self.guard:
            processing = self.pipeline.processing(source['id'])
            initial = mode == 'history' and processing['onboarding_state'] in {'INITIAL_HISTORY_PENDING', 'INITIAL_HISTORY_RUNNING'}
            for job in self.store.all('background_jobs'):
                if not body.get('reprocess') and job['source_id'] == source['id'] and job['mode'] == mode and (mode != 'history' or job['requested_range'] == requested):
                    if job['state'] in {'PAUSED', 'BLOCKED'}:
                        return self.action(job['id'], 'resume')
                    return job
            job = self.store.put('background_jobs', {'source_id': source['id'], 'account_id': source['account_id'],
                'source_kind': source['kind'], 'mode': mode, 'state': 'QUEUED', 'requested_range': requested,
                'interval_seconds': max(30, min(3600, int(body.get('interval_seconds', processing.get('interval_seconds', 300))))),
                'initial_history': initial, 'reprocess': bool(body.get('reprocess', False)),
                'batch_size': max(1, min(200, int(body.get('batch_size', 100)))),
                'activation_baseline': utcnow(), 'cursor': None, 'coverage': 'UNKNOWN',
                'counts': {'discovered': 0, 'saved': 0, 'pending': 0, 'failed': 0},
                'cycles': 0, 'failures': 0, 'next_run_at': utcnow(), 'last_success_at': None,
                'new_event_evidence': [], 'stop_reason': '等待后台执行；不会操作微信界面。'})
            if mode != 'media':
                self.create_job({'source_id': source['id'], 'mode': 'media', 'interval_seconds': 30})
            if mode == 'continuous' and processing['onboarding_state'] == 'INITIAL_HISTORY_PENDING':
                self.create_job({'source_id': source['id'], 'mode': 'history', 'range': body.get('range') or {}})
            return job

    def action(self, ident, action):
        with self.guard:
            job = self.store.get('background_jobs', ident)
            if not job or action not in {'pause', 'resume', 'retry'}:
                raise ValueError('JOB_OR_ACTION_INVALID')
            if action == 'pause':
                return self.store.put('background_jobs', {**job, 'state': 'PAUSED', 'stop_reason': '已暂停；当前安全批次可提交，进度与附件保留。'})
            self._require_collection()
            if job.get('imported'):
                raise ValueError('IMPORTED_JOB_NOT_EXECUTABLE')
            source = self.store.get('sources', job['source_id'])
            if not self._source_authorized(source) or job.get('source_kind') != source.get('kind'):
                raise ValueError('SOURCE_NOT_AUTHORIZED')
            if job.get('local_exhausted') and job['mode'] == 'history' and not job.get('parse_gaps'):
                return self.store.put('background_jobs', {**job, 'state': 'COMPLETED_LOCAL', 'next_run_at': None,
                    'stop_reason': '本次历史范围已处理；新增范围请使用补充历史资料。'})
            if action == 'retry':
                for attachment in self.store.all('attachments'):
                    if attachment.get('source_id') == job['source_id'] and attachment.get('state') != 'SAVED' and not attachment.get('retired'):
                        self.store.update_background_attachment(attachment, {'state': 'PENDING', 'media_state': 'RETRY_PENDING',
                            'next_retry_at': utcnow(), 'attempts': 0})
                if job['mode'] != 'media':
                    self.create_job({'source_id': job['source_id'], 'mode': 'media'})
            cursor = None if job.get('parse_gaps') else job.get('cursor')
            return self.store.put('background_jobs', {**job, 'state': 'QUEUED', 'next_run_at': utcnow(),
                'cursor': cursor, 'parse_gaps': [], 'failures': 0, 'last_error': None, 'stop_reason': '等待继续；会重新核对账号。'})

    def _counts(self, job):
        assets = [a for a in self.store.all('attachments') if a.get('source_id') == job['source_id'] and not a.get('retired')]
        return {**job.get('counts', {}), 'saved': sum(a.get('state') == 'SAVED' for a in assets),
                'pending': sum(a.get('state') in {'PENDING', 'RETRY'} for a in assets),
                'failed': sum(a.get('state') in {'RETRY', 'UNAVAILABLE'} for a in assets)}

    def run_once(self, ident):
        self._require_collection()
        with self.guard:
            job = self.store.get('background_jobs', ident)
            if not job or job.get('imported') or job['state'] in {'PAUSED', 'COMPLETED_LOCAL', 'BLOCKED'}:
                return
            source = self.store.get('sources', job['source_id'])
            if not self._source_authorized(source) or job.get('source_kind') != source.get('kind'):
                self.store.put('background_jobs', {**job, 'state': 'BLOCKED', 'next_run_at': None,
                    'last_error': 'SOURCE_NOT_AUTHORIZED',
                    'stop_reason': '此任务的账号或来源与当前本机绑定不一致；请核对绑定并创建新任务。'})
                return
            lock = self.source_locks.setdefault(job['source_id'], threading.Lock())
            if not lock.acquire(blocking=False):
                return
            try:
                self.store.put('background_jobs', {**job, 'state': 'RUNNING'})
            except Exception:
                lock.release()
                raise
        try:
            self.active.add(ident)
            source = self.store.get('sources', job['source_id'])
            processing = self.pipeline.processing(source['id'])
            if job['mode'] == 'continuous' and processing['onboarding_state'] in {'INITIAL_HISTORY_PENDING', 'INITIAL_HISTORY_RUNNING'}:
                self.store.put('background_jobs', {**job, 'state': 'WAITING', 'next_run_at': after(5),
                    'stop_reason': '先完成所选初始历史范围，再开始增量更新。'})
                return
            with self.access_lock:
                # Expiration is local housekeeping and must work while logged out.
                self.pipeline.expire()
                self.bind()
                self.pipeline.adapter = self.adapter
                if self.stop_event.is_set():
                    return
                if job['mode'] == 'media':
                    self._media(source, job)
                else:
                    scope = {**job['requested_range'], 'mode': job['mode']}
                    known = {} if job.get('reprocess') else self.pipeline.known(source['id'], include_baseline=job['mode'] == 'continuous')
                    last_index = processing.get('last_index_reconciliation_at')
                    force = not last_index or (datetime.now(timezone.utc) - datetime.fromisoformat(last_index)).total_seconds() >= 3600
                    force = force or bool(self.pipeline.reconsider_keys(source['id']))
                    discover = getattr(self.adapter, 'discover_processing', None)
                    if discover:
                        page = discover(source['kind'], scope, job.get('cursor'), job['batch_size'], known,
                            force=force or job['mode'] == 'history',
                            previous_change_stamp=processing.get('change_stamp') if job['mode'] == 'continuous' else None,
                            baseline_index=bool(job.get('initial_history')))
                    else:
                        page = self.adapter.discover(source['kind'], scope, job.get('cursor'), job['batch_size'])
                        # Compatibility adapters still obey the gate; native adapters use the index above.
                        for item in page['items']:
                            if not item.get('native_revision'):
                                item['native_revision'] = hashlib.sha256(json.dumps({k: v for k, v in item.items() if k != 'native_revision'}, sort_keys=True).encode()).hexdigest()
                        page['items'] = [i for i in page['items'] if known.get(i['event_key']) != i.get('native_revision', i.get('source_revision_hash', ''))]
                    prepared = self.pipeline.prepare_page(source, page['items'])
                    from .migration import protected_materials
                    self.pipeline.commit(source, prepared, page, job, protected=protected_materials(self.store, expected_account=self.expected_account, expected_friend=self.expected_friend))
                    persisted = self.store.get('background_jobs', ident)
                    if page.get('exhausted') and not persisted.get('parse_gaps'):
                        release = getattr(self.adapter, 'release_snapshot', None)
                        if release and page.get('snapshot_id'):
                            release(page.get('snapshot_id'))
                    elif page.get('exhausted') and job['mode'] == 'continuous':
                        previous = persisted.get('parse_gap_snapshot_id')
                        self.store.put('background_jobs', {**persisted, 'parse_gap_snapshot_id': page.get('snapshot_id')})
                        release = getattr(self.adapter, 'release_snapshot', None)
                        if release and previous and previous != page.get('snapshot_id'):
                            release(previous)
            with self.guard:
                current = self.store.get('background_jobs', ident)
                if current['state'] == 'PAUSED':
                    return
                exhausted = current.get('local_exhausted')
                gaps = bool(current.get('parse_gaps')) and exhausted
                blocking_gaps = gaps and job['mode'] == 'history'
                completed = job['mode'] == 'history' and exhausted and not gaps
                next_delay = job['interval_seconds'] if exhausted or job['mode'] == 'media' else 1
                if job['mode'] == 'media':
                    pending = [asset for asset in self.store.all('attachments')
                        if asset.get('source_id') == source['id'] and asset.get('state') in {'PENDING', 'RETRY'}
                        and not asset.get('retired')]
                    now = datetime.now(timezone.utc)
                    if any(not asset.get('next_retry_at') or datetime.fromisoformat(asset['next_retry_at']) <= now for asset in pending):
                        next_delay = 1
                    elif pending:
                        earliest = min(datetime.fromisoformat(asset['next_retry_at']) for asset in pending)
                        next_delay = min(job['interval_seconds'], max(1, int((earliest - now).total_seconds()) + 1))
                current.update({'state': 'BLOCKED' if blocking_gaps else 'COMPLETED_LOCAL' if completed else 'WAITING',
                    'last_success_at': utcnow(), 'next_run_at': None if completed or blocking_gaps else after(next_delay),
                    'failures': 0, 'last_error': 'NATIVE_RECORD_PARSE_GAPS' if gaps else None, 'cycles': current.get('cycles', 0) + 1,
                    'counts': self._counts(current), 'stop_reason': '存在解析缺口；有效记录已保存，完整性未知。' if gaps else '本地快照已遍历；远端历史完整性未知。' if exhausted else '本批次已保存；按计划继续。'})
                if exhausted and (job['mode'] == 'continuous' or gaps):
                    current['cursor'] = None
                self.store.put('background_jobs', current)
        except Exception as exc:
            with self.guard:
                current = self.store.get('background_jobs', ident) or job
                if current['state'] == 'PAUSED':
                    return
                code = safe_code(exc)
                failures = current.get('failures', 0) + 1
                invalid = any(w in code for w in ('ACCOUNT', 'BINDING', 'PROCESS', 'FRIEND', 'SESSION'))
                if invalid:
                    self.store.put('background_status', {'state': 'BLOCKED', 'label': '受阻',
                        'error': code, 'account_display': self.account_display, 'friend_display': self.friend_display}, 'binding')
                # Snapshot invalidation restarts traversal of a fresh snapshot; events deduplicate.
                abandoned = None
                if invalid or 'SNAPSHOT' in code or 'CURSOR' in code:
                    abandoned = (current.get('cursor') or {}).get('snapshot_id') if isinstance(current.get('cursor'), dict) else None
                    current['cursor'] = None
                transient_binding = code == 'ACCOUNT_PROCESS_BINDING_INCOMPLETE'
                self.store.put('background_jobs', {**current, 'state': 'BLOCKED' if invalid and not transient_binding else 'RETRY',
                    'last_error': code, 'failures': failures, 'next_run_at': after(min(3600, 30 * 2 ** min(failures - 1, 7))),
                    'counts': self._counts(current), 'stop_reason': '后台读取未完成；保留进度，请查看原因。'})
                if abandoned and not current.get('parse_gaps'):
                    release = getattr(self.adapter, 'release_snapshot', None)
                    if release:
                        try:
                            release(abandoned, disposition='invalidated_cursor', reason=code)
                        except Exception:
                            # Keep the original failure and evidence if cleanup is unavailable.
                            pass
        finally:
            self.active.discard(ident)
            lock.release()

    def _media(self, source, job):
        retrieval_operations = 0
        # Acquisition retries are separate from relevance uncertainty and native indexing.
        due = [c for c in self.pipeline.candidates() if c['source_id'] == source['id']
            and c['outcome'] == 'RETRY_ACQUISITION' and c.get('next_retry_at') and c['next_retry_at'] <= utcnow()]
        for candidate in due[:2]:
            item, decision = self.pipeline.prepare(source, candidate['item'])
            retrieval_operations += decision.get('metrics', {}).get('media_retrieval_operations', 0)
            from .migration import protected_materials
            self.pipeline.commit(source, [(item, decision)], {'cursor': job.get('cursor'), 'exhausted': False}, job,
                protected=protected_materials(self.store, expected_account=self.expected_account, expected_friend=self.expected_friend))
        staging = self.store.root / 'background-staging'
        staging.mkdir(exist_ok=True)
        assets = [a for a in self.store.all('attachments') if a.get('source_id') == source['id']
                  and a.get('state') in {'PENDING', 'RETRY'} and not a.get('retired')
                  and (not a.get('next_retry_at') or a['next_retry_at'] <= utcnow())]
        for asset in assets[:5]:
            if self.stop_event.is_set() or self.store.get('background_jobs', job['id'])['state'] == 'PAUSED':
                break
            attempts = asset.get('attempts', 0) + 1
            self.store.update_background_attachment(asset, {'media_state': 'BYTES_PENDING', 'attempts': attempts})
            try:
                retrieval_operations += 1
                result = self.adapter.retrieve(asset, staging)
                if result.get('state') != 'SAVED':
                    reason = result.get('reason', 'MEDIA_UNAVAILABLE')
                    reason = reason if re.fullmatch(r'[A-Z0-9_]{1,100}', reason) else 'MEDIA_UNAVAILABLE'
                    unavailable = result.get('state') == 'UNAVAILABLE'
                    self.store.update_background_attachment(asset, {'state': 'UNAVAILABLE' if unavailable else 'RETRY',
                        'media_state': 'UNAVAILABLE' if unavailable else 'RETRY_PENDING', 'last_error': reason,
                        'next_retry_at': after(min(3600, 30 * 2 ** min(attempts, 7)))})
                    continue
                with self.store.lock:
                    fresh = self.store.get('attachments', asset['id'])
                    saved = self.store.update_native_attachment(fresh, result, staging)
                path = self.store.root / saved['path']
                assert hashlib.sha256(path.read_bytes()).hexdigest() == saved['sha256']
                extra = {key: result[key] for key in ('native_source_sha256', 'native_source_bytes',
                         'native_source_format', 'decode_method') if key in result}
                if saved['mime'].startswith('image/'):
                    from PIL import Image
                    with Image.open(path) as image:
                        image.load()
                        extra.update({'width': image.width, 'height': image.height, 'file_type': image.format})
                self.store.update_background_attachment(saved, {**extra, 'media_state': 'VALIDATED',
                    'validated_at': utcnow(), 'bytes_saved_at': saved['retrieved_at'], 'last_error': None,
                    'attempts': attempts})
                incoming = Path(result['path']).resolve()
                if incoming.is_relative_to(staging.resolve()) and incoming.is_file():
                    incoming.unlink()
            except Exception as exc:
                if any(w in safe_code(exc) for w in ('ACCOUNT', 'BINDING', 'PROCESS', 'FRIEND', 'SESSION')):
                    self.store.put('background_status', {'state': 'BLOCKED', 'label': '受阻',
                        'error': safe_code(exc), 'account_display': self.account_display, 'friend_display': self.friend_display}, 'binding')
                    raise
                self.store.update_background_attachment(asset, {'state': 'RETRY', 'media_state': 'RETRY_PENDING',
                    'last_error': safe_code(exc), 'next_retry_at': after(min(3600, 30 * 2 ** min(attempts, 7)))})
        current = self.store.get('background_jobs', job['id'])
        self.store.put('background_jobs', {**current, 'last_media_cycle': {'media_retrieval_operations': retrieval_operations,
            'candidate_retries': min(len(due), 2), 'checked_at': utcnow()}})

    def classify(self, kind, ident, body):
        with self.store.lock:
            return self._classify_locked(kind, ident, body)

    def _classify_locked(self, kind, ident, body):
        if kind not in {'materials', 'attachments'}:
            raise ValueError('CLASSIFICATION_KIND_INVALID')
        record = self.store.get(kind, ident)
        if not record or body.get('label') not in (POST_LABELS if kind == 'materials' else FILE_LABELS):
            raise ValueError('CLASSIFICATION_INVALID')
        classification = {'label': body['label'], 'origin': 'manual',
            'evidence': str(body.get('evidence', '')).strip()[:1000], 'updated_at': utcnow()}
        if kind == 'attachments' and record.get('material_id'):
            return self.store.update_background_attachment(record, {'classification': classification})
        updated = {**record, 'classification': classification}
        if kind == 'materials' and record.get('acquisition_mode') == 'background':
            source = self.store.get('sources', record['source_id'])
            jobs = [j for j in self.store.all('background_jobs') if j['source_id'] == source['id'] and j['mode'] != 'media']
            if jobs:
                job = jobs[0]
                item, decision = self.pipeline.prepare(source, updated, retrieve=False, classification_override=classification)
                if decision['outcome'] != 'KEEP_PRODUCT_RELEVANT':
                    self.pipeline.commit(source, [(item, decision)], {'cursor': job.get('cursor'),
                        'exhausted': job.get('local_exhausted', False)}, job)
                else:
                    updated = self.store.put(kind, updated)
                    with self.store.connect() as db:
                        row = db.execute('SELECT data FROM processing_receipts WHERE source_id=? AND event_key=?',
                            (source['id'], record['event_key'])).fetchone()
                        if row:
                            receipt = json.loads(row[0])
                            receipt['classification'] = {k: classification[k] for k in ('label', 'origin', 'updated_at')}
                            db.execute('UPDATE processing_receipts SET data=? WHERE source_id=? AND event_key=?',
                                (json.dumps(receipt, ensure_ascii=False), source['id'], record['event_key']))
                return updated
        return self.store.put(kind, updated)

    def summary(self):
        binding = self.store.get('background_status', 'binding') or {'state': 'UNVERIFIED', 'label': '待核对',
            'account_display': self.account_display, 'friend_display': self.friend_display}
        jobs = self.store.all('background_jobs')
        for job in jobs:
            job['counts'] = self._counts(job)
        readable = binding['state'] == 'VERIFIED' and any(j.get('last_success_at') for j in jobs if j['mode'] != 'media')
        caps = {'local_read': {'status': 'VERIFIED' if readable else 'UNVERIFIED',
                              'label': '已验证' if readable else '待核对账号', 'reason': '仅访问已验证账号及指定联系人。'},
            'new_content': {'status': 'IMPLEMENTED', 'label': '已实现，待真实新增验证',
                            'reason': '后台轮询与补读已实现；安静轮询不算新增内容证据。'},
            'local_history': {'status': 'IMPLEMENTED', 'label': '部分可用', 'reason': '可导入本地已缓存历史；完整性未知。'},
            'remote_history': {'status': 'BLOCKED', 'label': '受阻', 'reason': '尚无已验证的后台缺失历史同步接口。'},
            'media': {'status': 'PARTIAL', 'label': '部分可用', 'reason': '按来源关联逐项取得文件；失败与缺失保留独立重试。'}}
        per_source = {}
        all_assets = self.store.all('attachments')
        for kind in ('moments', 'chat'):
            scoped = [j for j in jobs if j.get('source_kind') == kind]
            read_pass = binding['state'] == 'VERIFIED' and any(j.get('last_success_at') for j in scoped if j['mode'] != 'media')
            source_ids = {j['source_id'] for j in scoped}
            assets = [a for a in all_assets if a.get('source_id') in source_ids and not a.get('retired')]
            saved = sum(a.get('state') == 'SAVED' for a in assets)
            per_source[kind] = {**caps,
                'local_read': {'status': 'VERIFIED' if read_pass else 'IMPLEMENTED',
                    'label': '已验证' if read_pass else '已实现，待读取验证', 'reason': '仅核对本来源已成功执行的读取批次。'},
                'media': {'status': 'VERIFIED' if assets and saved == len(assets) else 'PARTIAL',
                    'label': '已验证' if assets and saved == len(assets) else '部分可用',
                    'reason': f'本来源已保存 {saved} / {len(assets)} 个附件；质量与失败原因逐项保留。'}}
            if any(job.get('new_event_evidence') for job in scoped if job['mode'] == 'continuous'):
                per_source[kind]['new_content'] = {'status': 'VERIFIED', 'label': '已验证',
                    'reason': '已保存启动基线之后发布且首次发现的原生记录；具体时间与标识保留在任务证据中。'}
            if kind == 'chat':
                documents = [a for a in assets if a.get('type') == 'file']
                per_source[kind]['documents'] = {'status': 'AWAITING_SAMPLE' if not documents else 'PARTIAL',
                    'label': '等待真实样本' if not documents else '部分可用', 'reason': '只有实际文件字节保存并校验后才算文档取得。'}
        verified_new = [kind for kind, value in per_source.items() if value['new_content']['status'] == 'VERIFIED']
        if verified_new:
            caps['new_content'] = {'status': 'VERIFIED' if len(verified_new) == 2 else 'PARTIAL',
                'label': '已验证' if len(verified_new) == 2 else '部分可用',
                'reason': '各来源的真实新增证据分别保留，请查看来源能力状态。'}
        if not self.collection_enabled:
            binding = {'state': 'DISABLED', 'label': '已停用', 'account_display': self.account_display,
                'friend_display': self.friend_display, 'reason': '导入资料可直接使用；实时采集默认停用，需按部署指南重新绑定本机账号。'}
        return {'binding': binding, 'capabilities': caps, 'per_source': per_source,
            'live_collection_enabled': self.collection_enabled,
            'sources': [{**s, 'processing': self.pipeline.processing(s['id'])} for s in self.store.all('sources') if s.get('acquisition_mode') == 'background' and not s.get('imported')],
            'jobs': jobs, 'summary': {'running_jobs': sum(j['state'] in {'QUEUED', 'WAITING', 'RUNNING', 'RETRY'} for j in jobs),
                'foreground_actions': 0, 'coverage': 'UNKNOWN'}}

    def check_now(self, source_id):
        job = self.create_job({'source_id': source_id, 'mode': 'continuous'})
        return self.store.put('background_jobs', {**job, 'state': 'QUEUED', 'next_run_at': utcnow()})

    def settings(self, source_id, body):
        source = self.store.get('sources', source_id)
        if not source or source.get('imported') or source.get('acquisition_mode') != 'background':
            raise ValueError('SOURCE_NOT_AUTHORIZED')
        interval = max(30, min(3600, int(body.get('interval_seconds', 300))))
        value = self.store.get('source_processing', source_id) or {'onboarding_state': 'INITIAL_HISTORY_PENDING'}
        self.store.put('source_processing', {**value, 'interval_seconds': interval}, source_id)
        for job in self.store.all('background_jobs'):
            if job['source_id'] == source_id and job['mode'] == 'continuous':
                self.store.put('background_jobs', {**job, 'interval_seconds': interval})
        return self.pipeline.processing(source_id)

    def apply_inspection(self, records):
        """Apply reviewed labels only to exact authorized posts and verified bytes."""
        if not isinstance(records, list) or len(records) > 100:
            raise ValueError('INSPECTION_BATCH_INVALID')
        posts = images = skipped = 0
        with self.store.lock:
            materials = self.store.all('materials')
            for entry in records:
                matches = [p for p in materials if p.get('acquisition_mode') == 'background'
                    and p.get('source_kind') == 'moments' and p.get('author_id') == self.expected_friend
                    and str(p.get('native_post_id') or p.get('native_id')) == str(entry.get('native_post_id'))]
                if len(matches) != 1 or entry.get('label') not in POST_LABELS:
                    raise ValueError('INSPECTION_POST_NOT_VERIFIED')
                post = matches[0]
                assets = {a['media_index']: a for a in post.get('attachments', [])}
                for value in entry.get('images', []):
                    asset = assets.get(value.get('index'))
                    if not asset or asset.get('sha256') != value.get('sha256') or value.get('label') not in FILE_LABELS:
                        raise ValueError('INSPECTION_IMAGE_NOT_VERIFIED')
                if post.get('classification', {}).get('origin') != 'manual':
                    self.store.put('materials', {**post, 'classification': {'label': entry['label'],
                        'origin': 'inspection', 'evidence': str(entry.get('evidence', ''))[:1000], 'updated_at': utcnow()}})
                    posts += 1
                else:
                    skipped += 1
                for value in entry.get('images', []):
                    asset = assets[value['index']]
                    if asset.get('classification', {}).get('origin') == 'manual':
                        skipped += 1; continue
                    self.store.update_background_attachment(asset, {'classification': {'label': value['label'],
                        'origin': 'inspection', 'evidence': str(value.get('evidence', ''))[:1000], 'updated_at': utcnow()}})
                    images += 1
        return {'posts': posts, 'images': images, 'manual_corrections_preserved': skipped}

    def apply_relevance_review(self, entries):
        """Apply reviewed evidence only to exact current selected-source images."""
        if not isinstance(entries, list) or not 1 <= len(entries) <= 50:
            raise ValueError('RELEVANCE_REVIEW_INVALID')
        applied = preserved = 0
        with self.store.lock:
            for entry in entries:
                material = self.store.get('materials', str(entry.get('material_id', '')))
                source = self.store.get('sources', (material or {}).get('source_id', ''))
                if (not material or not source or source.get('native_id') != self.expected_friend
                    or source.get('account_native_id') != self.expected_account
                    or source.get('acquisition_mode') != 'background'
                    or material.get('acquisition_mode') != 'background'
                    or material.get('account_id') != source.get('account_id')
                    or material.get('identity_verified') is not True
                    or entry.get('event_key') != material.get('event_key')
                    or entry.get('source_id') != source['id']
                    or entry.get('label') not in POST_LABELS):
                    raise ValueError('RELEVANCE_REVIEW_SCOPE_MISMATCH')
                actual = sorted(a['sha256'] for a in material.get('attachments', []) if a.get('sha256'))
                if not actual or sorted(entry.get('asset_sha256', [])) != actual:
                    raise ValueError('RELEVANCE_REVIEW_IMAGE_MISMATCH')
                if material.get('classification', {}).get('origin') == 'manual':
                    preserved += 1
                    continue
                classification = {'label': entry['label'], 'origin': 'inspection', 'updated_at': utcnow(),
                    'evidence': str(entry.get('evidence', ''))[:1000]}
                updated = {**material, 'classification': classification}
                source_job = next(j for j in self.store.all('background_jobs') if j['source_id'] == source['id'] and j['mode'] == 'continuous')
                item, decision = self.pipeline.prepare(source, updated, retrieve=False, classification_override=classification)
                if decision['outcome'] != 'KEEP_PRODUCT_RELEVANT':
                    self.pipeline.commit(source, [(item, decision)], {'cursor': source_job.get('cursor'),
                        'exhausted': source_job.get('local_exhausted', True)}, source_job)
                else:
                    self.store.put('materials', updated)
                    with self.store.connect() as db:
                        row = db.execute('SELECT data FROM processing_receipts WHERE source_id=? AND event_key=?',
                            (source['id'], item['event_key'])).fetchone()
                        if row:
                            receipt = json.loads(row[0])
                            receipt['classification'] = {k: classification[k] for k in ('label', 'origin', 'updated_at')}
                            db.execute('UPDATE processing_receipts SET data=? WHERE source_id=? AND event_key=?',
                                (json.dumps(receipt, ensure_ascii=False), source['id'], item['event_key']))
                applied += 1
        return {'applied': applied, 'manual_decisions_preserved': preserved}
