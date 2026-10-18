"""Independent AWS-only cleanup. GitHub availability cannot disable the deadline."""

import time
from pool import audit, expired, instances


def reap(ec2, now):
    expired_ids = [i["InstanceId"] for i in instances(ec2, [{"Name": "tag:ArteamisCiPool", "Values": ["arteamis-ci"]},
        {"Name": "tag:ArteamisCiRole", "Values": ["runner", "builder"]}]) if expired(i, now)]
    if expired_ids:
        ec2.terminate_instances(InstanceIds=expired_ids)
    audit("reaper", terminated=len(expired_ids))
    return {"terminated": expired_ids}


def lambda_handler(_event, _context):
    import boto3

    return reap(boto3.client("ec2"), int(time.time()))
