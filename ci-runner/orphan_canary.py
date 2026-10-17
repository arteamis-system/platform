"""Launch one expired, secretless CI VM to qualify the independent reaper.

This is a live, billed operation. It disables new controller work first, requires
an empty pool, and uses only a tagged CI launch-template version. No JIT runner
registration, slot or App credential is created.
"""
import argparse
import time
import uuid
import provision
import stack


def launch(profile, template, version):
    if (provision.BUILD/'orphan-request.json').exists():
        raise ValueError('Preserve and reconcile the previous orphan request before another launch')
    if provision.invoke(profile, 'disable').get('disabled') is not True:
        raise RuntimeError('Controller disable was not confirmed')
    result = provision.aws(profile, 'ec2', 'describe-instances', '--filters',
        'Name=tag:ArteamisCiPool,Values=arteamis-ci',
        'Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down')
    if any(r['Instances'] for r in result['Reservations']):
        raise ValueError('Wait for zero active CI instances before independent-cleanup qualification')
    item = provision.aws(profile, 'ec2', 'describe-launch-templates', '--launch-template-ids', template)['LaunchTemplates'][0]
    tags = {t['Key']: t['Value'] for t in item.get('Tags', [])}
    if tags.get('ArteamisCiPool') != 'arteamis-ci':
        raise ValueError('Use the dedicated Arteamis CI launch template')
    token = uuid.uuid4().hex
    info = stack.TAG + [{'Key': 'Name', 'Value': 'arteamis-ci-orphan-canary'},
        {'Key': 'ArteamisCiRole', 'Value': 'runner'}, {'Key': 'ArteamisCiExpires', 'Value': str(int(time.time())-60)}]
    request = {'LaunchTemplate': {'LaunchTemplateId': template, 'Version': str(version)},
        'MinCount': 1, 'MaxCount': 1, 'ClientToken': token,
        'UserData': '#!/bin/bash\nshutdown -h +10\nsleep 540\nshutdown -h now\n',
        'TagSpecifications': [{'ResourceType': kind, 'Tags': info} for kind in ('instance', 'volume')]}
    path = provision.write_json(provision.BUILD/'orphan-request.json', request)
    # Persist the idempotency token before the request; on a timeout inspect
    # DescribeInstances/CloudTrail for this token. Never generate another token.
    created = provision.aws(profile, 'ec2', 'run-instances', '--cli-input-json', 'file://'+str(path))
    print('Independent-cleanup canary:', created['Instances'][0]['InstanceId'])
    print('Wait for scheduled reaper evidence and deleted root volumes before resume.')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', default='arteamis-ci-operator')
    parser.add_argument('--launch-template', required=True)
    parser.add_argument('--version', type=int, required=True)
    args=parser.parse_args(); provision.identity(args.profile)
    launch(args.profile, args.launch_template, args.version)
