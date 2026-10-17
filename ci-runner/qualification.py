"""Collect secretless run/capacity/cleanup evidence. Never dispatches or retries a job."""
import argparse
import datetime as dt
import json
import subprocess
import time
from pathlib import Path

import controller
import provision


def gh(repo, path, key=None):
    result = subprocess.run(['gh', 'api', '--paginate', 'repos/' + repo + path], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('GitHub qualification metadata unavailable')
    # --paginate concatenates objects; decode without assuming a single page.
    raw, decoder, values = result.stdout.strip(), json.JSONDecoder(), []
    while raw:
        data, end = decoder.raw_decode(raw)
        values.extend(data[key] if key else [data]); raw = raw[end:].lstrip()
    return values if key else values[0]


def capture(profile, repo, run_id):
    run = gh(repo, f'/actions/runs/{run_id}')
    jobs = gh(repo, f'/actions/runs/{run_id}/jobs?filter=all&per_page=100', 'jobs')
    fields = ('id', 'name', 'status', 'conclusion', 'run_attempt', 'runner_id', 'runner_name',
              'labels', 'created_at', 'started_at', 'completed_at')
    records = [{key: j.get(key) for key in fields} for j in jobs]
    # Record only the specific public billing classifier, never raw annotations/logs.
    annotations = {}
    for job in jobs:
        if job.get('conclusion') == 'failure':
            annotations[job['id']] = gh(repo, f"/check-runs/{job['id']}/annotations?per_page=100")
    result = provision.aws(profile, 'ec2', 'describe-instances', '--filters',
                           'Name=tag:ArteamisCiPool,Values=arteamis-ci', 'Name=tag:ArteamisCiRole,Values=runner')
    instances = []
    for reservation in result['Reservations']:
        for item in reservation['Instances']:
            instances.append({'id': item['InstanceId'], 'state': item['State']['Name'],
                'launch_time': item['LaunchTime'], 'tags': item.get('Tags', []),
                'volumes': [b['Ebs']['VolumeId'] for b in item.get('BlockDeviceMappings', []) if 'Ebs' in b]})
    volumes = provision.aws(profile, 'ec2', 'describe-volumes', '--filters', 'Name=tag:ArteamisCiPool,Values=arteamis-ci')
    return {'time': dt.datetime.now(dt.timezone.utc).isoformat(),
        'run': {key: run.get(key) for key in ('id', 'head_sha', 'head_branch', 'event', 'path', 'run_attempt', 'status', 'conclusion', 'html_url')},
        'billing_only': controller.billing_only(jobs, annotations), 'jobs': records, 'instances': instances,
        'volumes': [{'id': v['VolumeId'], 'state': v['State']} for v in volumes['Volumes']]}


def watch(profile, repo, run_id, output, minutes):
    if not 1 <= minutes <= 120:
        raise ValueError('Observation window must be 1 to 120 minutes')
    if output.exists():
        raise ValueError('Preserve existing qualification records; choose a new output')
    deadline, observations = time.monotonic() + minutes * 60, []
    while True:
        record = capture(profile, repo, run_id); observations.append(record)
        active = sum(i['state'] in ('pending','running','stopping','stopped','shutting-down') for i in record['instances'])
        document = {'repository': repo, 'run_id': run_id, 'observations': observations,
                    'maximum_observed_capacity': max(sum(i['state'] in ('pending','running','stopping','stopped','shutting-down')
                        for i in row['instances']) for row in observations)}
        provision.write_json(output, document)
        print(json.dumps({'time': record['time'], 'status': record['run']['status'], 'active': active, 'volumes': len(record['volumes'])}), flush=True)
        if active > 2:
            raise RuntimeError('Capacity exceeded; disable the controller and review the evidence')
        if time.monotonic() >= deadline:
            return
        time.sleep(15)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', default='arteamis-ci-operator')
    parser.add_argument('--repository', default='arteamis-system/backend')
    parser.add_argument('--run', required=True, type=int)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--minutes', default=20, type=int)
    args = parser.parse_args()
    config = json.loads(Path(__file__).with_name('config.json').read_text())
    if args.repository not in config['repositories']:
        parser.error('Use an approved private repository')
    provision.identity(args.profile)
    watch(args.profile, args.repository, args.run, args.output, args.minutes)
