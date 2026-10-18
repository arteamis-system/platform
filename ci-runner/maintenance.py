"""Plan image retention: keep two newest images, all live images, and every template reference."""
import argparse
import json
import time
from pathlib import Path
import provision
import stack


def plan(profile):
    images = provision.aws(profile, 'ec2', 'describe-images', '--owners', 'self')['Images']
    tagged = [i for i in images if {t['Key']:t['Value'] for t in i.get('Tags',[])}.get('ArteamisCiPool') == 'arteamis-ci']
    keep = {i['ImageId'] for i in sorted(tagged, key=lambda i:i['CreationDate'], reverse=True)[:2]}
    instances = provision.aws(profile, 'ec2', 'describe-instances')['Reservations']
    keep.update(i['ImageId'] for r in instances for i in r['Instances'] if i['State']['Name'] != 'terminated')
    templates = provision.aws(profile, 'ec2', 'describe-launch-templates', '--filters', 'Name=tag:ArteamisCiPool,Values=arteamis-ci')['LaunchTemplates']
    for template in templates:
        versions = provision.aws(profile, 'ec2', 'describe-launch-template-versions', '--launch-template-id', template['LaunchTemplateId'])['LaunchTemplateVersions']
        keep.update(v['LaunchTemplateData'].get('ImageId') for v in versions)
    candidates = [i for i in tagged if i['ImageId'] not in keep and
                  i['CreationDate'] < time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(time.time()-7*86400))]
    deleting = {i['ImageId'] for i in candidates}
    referenced = {b['Ebs']['SnapshotId'] for i in images if i['ImageId'] not in deleting
                  for b in i.get('BlockDeviceMappings',[]) if 'Ebs' in b and 'SnapshotId' in b['Ebs']}
    snapshots = provision.aws(profile, 'ec2', 'describe-snapshots', '--owner-ids', stack.ACCOUNT,
        '--filters', 'Name=tag:ArteamisCiPool,Values=arteamis-ci')['Snapshots']
    allowed = {s['SnapshotId'] for s in snapshots}
    return [{'image': i['ImageId'], 'snapshots': [b['Ebs']['SnapshotId'] for b in i.get('BlockDeviceMappings',[])
              if 'Ebs' in b and b['Ebs'].get('SnapshotId') in allowed - referenced]} for i in candidates]


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', default='arteamis-ci-operator')
    parser.add_argument('--execute', action='store_true')
    args=parser.parse_args(); provision.identity(args.profile)
    result=plan(args.profile)
    provision.write_json(provision.BUILD/'image-retention-plan.json', result)
    print(json.dumps(result, indent=2))
    if args.execute:
        for item in result:
            provision.aws(args.profile,'ec2','deregister-image','--image-id',item['image'])
            for snapshot in item['snapshots']:
                provision.aws(args.profile,'ec2','delete-snapshot','--snapshot-id',snapshot)
