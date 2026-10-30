"""Finite authorized localhost check; report metadata/counters only."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import urllib.request

def request(route, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request('http://127.0.0.1:8765/api/' + route, data=data,
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)

def now():
    return datetime.now(timezone.utc).isoformat()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    started = now()
    state = request('state')
    ids = {m['id'] for m in state['materials']}
    background = state['background']
    resumed = []
    for job in background['jobs']:
        if job['mode'] in {'continuous', 'media'} and job['source_id'] in {s['id'] for s in background['sources']}:
            request('background/jobs/' + job['id'] + '/resume', {})
            resumed.append(job['id'])
    cycles = []
    for cycle in range(2):
        for source in background['sources']:
            job = request('background/sources/' + source['id'] + '/check', {})
            before = job.get('last_page_at')
            deadline = time.monotonic() + 60
            while True:
                current = request('background')
                current_job = next(j for j in current['jobs'] if j['id'] == job['id'])
                if current_job.get('last_page_at') != before and current_job['state'] in {'WAITING', 'BLOCKED', 'RETRY'}:
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError('BOUNDED_CHECK_DID_NOT_COMPLETE')
                time.sleep(1)
            processing = next(s['processing'] for s in current['sources'] if s['id'] == source['id'])
            cycles.append({'cycle': cycle + 1, 'source_id': source['id'], 'job_state': current_job['state'],
                'metrics': current_job.get('last_cycle'), 'processing': processing,
                'new_event_evidence_count': len(current_job.get('new_event_evidence', []))})
    end = request('state')
    output = {'observation_started_at': started, 'observation_ended_at': now(), 'resumed_jobs': resumed,
        'cycles': cycles, 'material_ids_unchanged': ids == {m['id'] for m in end['materials']},
        'materials_count': len(end['materials']), 'candidates_summary': request('background/candidates')['summary'],
        'jobs': [{k: j.get(k) for k in ('id', 'source_id', 'mode', 'state', 'interval_seconds', 'next_run_at', 'last_media_cycle', 'last_error')}
            for j in end['background']['jobs']], 'new_native_event_status': 'NOT_TESTED_NO_REAL_NEW_CONTENT_OBSERVED'}
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in output.items() if k not in {'cycles', 'jobs'}}, ensure_ascii=True))
