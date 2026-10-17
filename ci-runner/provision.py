"""Explicit CI-only provisioning commands, using the AWS CLI and standard library."""

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import zipfile
import uuid
import gzip
from pathlib import Path

import stack
import alerts

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / ".build"


class AwsError(RuntimeError):
    def __init__(self, service, operation, error):
        match = re.search(r"An error occurred \(([^)]+)\)", error)
        self.code = match[1] if match else "Unknown"
        self.missing_stack = "does not exist" in error
        self.no_updates = "No updates are to be performed" in error
        super().__init__(f"AWS {service} {operation} failed ({self.code}); inspect IAM/CloudTrail")


def aws(profile, *args):
    result = subprocess.run(["aws", "--profile", profile, "--region", stack.REGION,
                             "--cli-binary-format", "raw-in-base64-out", *args, "--output", "json"],
                            capture_output=True, text=True)
    if result.returncode:
        # AWS errors may include request material. Do not print raw errors or argv.
        raise AwsError(args[0], args[1], result.stderr)
    return json.loads(result.stdout) if result.stdout.strip() else None


def identity(profile):
    caller = aws(profile, "sts", "get-caller-identity")
    if caller["Arn"].endswith(":root") or caller["Account"] != stack.ACCOUNT:
        raise RuntimeError("Use a non-root identity in the Arteamis AWS account")
    print("AWS identity:", caller["Arn"])


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")
    return path


def outputs(profile):
    result = aws(profile, "cloudformation", "describe-stacks", "--stack-name", "arteamis-ci-foundation")
    return {item["OutputKey"]: item["OutputValue"] for item in result["Stacks"][0]["Outputs"]}


def apply_stack(profile, name, template, execute=False):
    """Persist the exact AWS change set before any explicit execution."""
    path = write_json(BUILD / (name + ".json"), template)
    try:
        observed = aws(profile, "cloudformation", "describe-stacks", "--stack-name", name)
        kind = "CREATE" if observed["Stacks"][0]["StackStatus"] == "REVIEW_IN_PROGRESS" else "UPDATE"
    except AwsError as error:
        if error.code != "ValidationError" or not error.missing_stack:
            raise
        kind = "CREATE"
    change = "arteamis-ci-review-" + str(int(time.time()))
    aws(profile, "cloudformation", "create-change-set", "--stack-name", name,
        "--change-set-name", change, "--change-set-type", kind, "--template-body", "file://" + str(path),
        "--capabilities", "CAPABILITY_NAMED_IAM", "--tags", "Key=ArteamisCiPool,Value=arteamis-ci")
    try:
        aws(profile, "cloudformation", "wait", "change-set-create-complete", "--stack-name", name, "--change-set-name", change)
    except AwsError:
        result = aws(profile, "cloudformation", "describe-change-set", "--stack-name", name, "--change-set-name", change)
        if any(reason in result.get("StatusReason", "") for reason in ("didn't contain changes", "No updates are to be performed")):
            print("No stack changes:", name)
            return True
        raise RuntimeError("Change set failed; inspect CloudFormation before execution") from None
    review = aws(profile, "cloudformation", "describe-change-set", "--stack-name", name, "--change-set-name", change)
    write_json(BUILD / (name + "-changeset.json"), review)
    print("Review change set:", name, change, "saved under", BUILD)
    if not execute:
        print("Not executed. After review, execute the named change set in CloudFormation or rerun with --execute.")
        return False
    aws(profile, "cloudformation", "execute-change-set", "--stack-name", name, "--change-set-name", change)
    aws(profile, "cloudformation", "wait", "stack-create-complete" if kind == "CREATE" else "stack-update-complete", "--stack-name", name)
    return True


def package():
    if sys.version_info < (3, 12):
        raise ValueError("Packaging requires Python 3.12 or newer")
    target = BUILD / "package"
    if target.exists():
        import shutil
        shutil.rmtree(target)
    target.mkdir(parents=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--only-binary=:all:",
                    "--platform", "manylinux_2_28_x86_64", "--platform", "manylinux2014_x86_64", "--implementation", "cp",
                    "--python-version", "3.12", "--no-compile", "--target", str(target), "-r", str(ROOT / "requirements.txt")], check=True)
    for name in ("controller.py", "pool.py", "reaper.py", "config.json"):
        (target / name).write_bytes((ROOT / name).read_bytes())
    archive = BUILD / "controller.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(target.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                info = zipfile.ZipInfo(str(path.relative_to(target)), (1980, 1, 1, 0, 0, 0))
                info.external_attr = 0o644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                bundle.writestr(info, path.read_bytes())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True))
    write_json(BUILD / "artifact.json", {"sha256": digest, "file": str(archive), "runtime": "python3.12",
                                        "architecture": "x86_64", "source_commit": source, "source_dirty": dirty})
    print("CI Lambda artifact:", archive, "SHA-256:", digest)
    return archive, digest


def install_app(profile, path):
    if path.stat().st_mode & 0o077:
        raise ValueError("App configuration must have mode 0600")
    app = json.loads(path.read_text())
    if not all(app.get(key) for key in ("app_id", "installation_id", "private_key")):
        raise ValueError("App registration and repository installation must both be complete")
    with tempfile.TemporaryDirectory() as work:
        temporary = Path(work) / "parameter.json"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump({"Name": "/arteamis/ci/github-app", "Type": "SecureString", "Value": json.dumps(app), "Overwrite": False}, stream)
        aws(profile, "ssm", "put-parameter", "--cli-input-json", "file://" + str(temporary))
    print("App configuration installed as controller-only SecureString /arteamis/ci/github-app")


def wait_image(profile, image):
    # The stock CLI waiter stops after ten minutes; a valid snapshot can still
    # be pending at 99%. Keep the builder's 30-minute shutdown bound.
    deadline = time.monotonic() + 1500
    while time.monotonic() < deadline:
        state = aws(profile, "ec2", "describe-images", "--image-ids", image)["Images"][0]["State"]
        if state == "available":
            return
        if state == "failed":
            raise RuntimeError("Runner image creation failed")
        time.sleep(15)
    raise RuntimeError("Runner image is still pending; inspect its snapshot before activation")


def bake(profile):
    if (BUILD / "builder.json").exists():
        raise ValueError("Reconcile and archive the prior builder request before another bake; never replace an ambiguous token")
    network = outputs(profile)
    source = aws(profile, "ssm", "get-parameter", "--name", "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id")["Parameter"]["Value"]
    expiry = int(time.time()) + 1800
    tag = {"Name": "arteamis-ci-ami-builder", "ArteamisCiPool": "arteamis-ci", "ArteamisCiRole": "builder", "ArteamisCiExpires": str(expiry)}
    # The AWS CLI encodes RunInstances UserData, like boto3.
    data = "#!/bin/bash\nshutdown -h +30\n"
    request = {"ImageId": source, "InstanceType": "m6i.large", "MinCount": 1, "MaxCount": 1, "ClientToken": uuid.uuid4().hex,
        "InstanceInitiatedShutdownBehavior": "terminate", "UserData": data, "IamInstanceProfile": {"Name": "arteamis-ci-runner"},
        "MetadataOptions": {"HttpTokens": "required", "HttpPutResponseHopLimit": 1},
        "NetworkInterfaces": [{"DeviceIndex": 0, "AssociatePublicIpAddress": True, "SubnetId": network["SubnetId"], "Groups": [network["SecurityGroupId"]], "DeleteOnTermination": True}],
        "BlockDeviceMappings": [{"DeviceName": "/dev/sda1", "Ebs": {"VolumeSize": 30, "VolumeType": "gp3", "Encrypted": True,
            "KmsKeyId": f"arn:aws:kms:{stack.REGION}:{stack.ACCOUNT}:alias/aws/ebs", "DeleteOnTermination": True}}],
        "TagSpecifications": [{"ResourceType": kind, "Tags": [{"Key": key, "Value": value} for key, value in tag.items()]} for kind in ("instance", "volume", "network-interface")]}
    request_file = write_json(BUILD / "builder.json", request)
    instance = aws(profile, "ec2", "run-instances", "--cli-input-json", "file://" + str(request_file))["Instances"][0]["InstanceId"]
    try:
        print("AMI builder:", instance, "self-termination scheduled in 30 minutes")
        deadline = time.time() + 900
        while time.time() < deadline:
            ready = aws(profile, "ssm", "describe-instance-information", "--filters", "Key=InstanceIds,Values=" + instance)
            if any(item.get("PingStatus") == "Online" for item in ready["InstanceInformationList"]):
                break
            time.sleep(10)
        else:
            raise RuntimeError("AMI builder did not register with SSM")
        script = (ROOT / "bake.sh").read_text()
        parameters = write_json(BUILD / "bake-parameters.json", {"commands": [script], "executionTimeout": ["900"]})
        command = aws(profile, "ssm", "send-command", "--instance-ids", instance, "--document-name", "AWS-RunShellScript", "--parameters", "file://" + str(parameters))["Command"]["CommandId"]
        deadline = time.time() + 1000
        while time.time() < deadline:
            try:
                invocation = aws(profile, "ssm", "get-command-invocation", "--command-id", command, "--instance-id", instance)
            except RuntimeError:
                time.sleep(5)
                continue
            if invocation["Status"] == "Success":
                match = re.search(r"ARTEAMIS_INVENTORY=([A-Za-z0-9+/=]+)", invocation.get("StandardOutputContent", ""))
                if not match:
                    raise RuntimeError("Missing AMI inventory; inspect builder before approving an image")
                inventory = json.loads(gzip.decompress(base64.b64decode(match[1])))
                write_json(BUILD / "ami-inventory.json", inventory)
                break
            if invocation["Status"] in ("Failed", "Cancelled", "TimedOut"):
                raise RuntimeError("AMI bake failed; inspect the builder SSM command")
            time.sleep(10)
        else:
            raise RuntimeError("AMI bake deadline exceeded")
        digest = hashlib.sha256(script.encode()).hexdigest()
        image = aws(profile, "ec2", "create-image", "--instance-id", instance, "--name", "arteamis-ci-" + digest[:12] + "-" + str(int(time.time())),
            "--tag-specifications", json.dumps([{"ResourceType": "image", "Tags": stack.TAG + [{"Key": "ArteamisCiSourceHash", "Value": digest}]},
                                                {"ResourceType": "snapshot", "Tags": stack.TAG}]))["ImageId"]
        print("AMI:", image, "bake SHA-256:", digest)
        write_json(BUILD / "ami.json", {"image_id": image, "base_image_id": source, "bake_sha256": digest, "builder_instance": instance})
        wait_image(profile, image)
    finally:
        aws(profile, "ec2", "terminate-instances", "--instance-ids", instance)


BASE_EVIDENCE = ("routing_reevaluated", "one_job_per_vm", "cleanup_verified", "independent_cleanup_verified",
                 "two_vm_capacity_verified", "tools_verified", "permissions_verified", "alerts_configured")
FULL_EVIDENCE = ("automatic_takeover_verified", "hosted_recovery_verified", "workflows_verified")


def validate_evidence(proof, ami):
    if proof.get("scope") not in ("canary", "all"):
        raise ValueError("Evidence scope must be canary or all")
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if (proof.get("source_commit") != source or proof.get("ami") != ami
            or proof.get("bake_sha256") != hashlib.sha256((ROOT / "bake.sh").read_bytes()).hexdigest()):
        raise ValueError("Evidence must identify this committed source and reviewed AMI bake")
    required = BASE_EVIDENCE + (FULL_EVIDENCE if proof["scope"] == "all" else ())
    for field in required:
        record = proof.get(field, {})
        if (not isinstance(record, dict) or record.get("verified") is not True
                or not isinstance(record.get("references"), list) or not record["references"]
                or not all(isinstance(ref, str) and ref.startswith(("https://", "arn:aws:")) for ref in record["references"])):
            raise ValueError("Incomplete live evidence: " + field)


def deploy(profile, ami, evidence=None, enable=False, alarm_topic=None, execute=False):
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True):
        raise ValueError("Commit and validate the platform source before deploying its CI artifacts")
    scope = "canary"
    if evidence:
        proof = json.loads(evidence.read_text())
        scope = proof.get("scope")
        validate_evidence(proof, ami)
        if alarm_topic != alerts.TOPIC:
            raise ValueError("Automatic qualification requires the dedicated CI notification topic")
    if alarm_topic:
        if alarm_topic != alerts.TOPIC:
            raise ValueError("Use only the dedicated Arteamis CI notification topic")
        notification = aws(profile, "cloudformation", "describe-stacks", "--stack-name", "arteamis-ci-alerts")["Stacks"][0]
        if notification["StackStatus"] not in ("CREATE_COMPLETE", "UPDATE_COMPLETE"):
            raise ValueError("Wait for the CI alerts stack to finish")
        if not any(item["OutputKey"] == "TopicArn" and item["OutputValue"] == alarm_topic for item in notification.get("Outputs", [])):
            raise ValueError("CI alerts stack topic mismatch")
    image = aws(profile, "ec2", "describe-images", "--image-ids", ami)["Images"][0]
    tags = {t["Key"]: t["Value"] for t in image.get("Tags", [])}
    expected_bake = hashlib.sha256((ROOT / "bake.sh").read_bytes()).hexdigest()
    if (image["State"] != "available" or image["OwnerId"] != stack.ACCOUNT or image["Architecture"] != "x86_64"
            or tags.get("ArteamisCiPool") != "arteamis-ci" or tags.get("ArteamisCiSourceHash") != expected_bake):
        raise ValueError("Use the reviewed, Arteamis-owned, tagged x86-64 runner AMI")
    archive, digest = package()
    network = outputs(profile)
    key = "controller/" + digest + ".zip"
    aws(profile, "s3api", "put-object", "--bucket", network["ArtifactBucket"], "--key", key, "--body", str(archive), "--server-side-encryption", "AES256")
    if not apply_stack(profile, "arteamis-ci-runtime", stack.runtime(
            ami, key, network, bool(evidence), enable, alarm_topic, qualification_only=scope != "all"), execute):
        return
    expected = base64.b64encode(bytes.fromhex(digest)).decode()
    for name in ("arteamis-ci-controller", "arteamis-ci-reaper"):
        function = aws(profile, "lambda", "get-function-configuration", "--function-name", name)
        if function["CodeSha256"] != expected:
            raise RuntimeError("Deployed Lambda artifact hash mismatch")
    print("CI Lambda artifact hashes verified; automatic routing gate:", bool(evidence), "controller schedule:", enable)


def invoke(profile, action, repository=None):
    request = {"action": action} if action != "tick" else {}
    if repository:
        request["repository"] = repository
    payload = write_json(BUILD / "invoke.json", request)
    response = BUILD / "response.json"
    deadline = time.time() + 420
    while True:
        result = aws(profile, "lambda", "invoke", "--function-name", "arteamis-ci-controller", "--payload", "fileb://" + str(payload), str(response))
        if result.get("FunctionError"):
            raise RuntimeError("Controller invocation failed; inspect its CloudWatch logs")
        outcome = json.loads(response.read_text())
        if not outcome.get("leased") or action == "tick":
            return outcome
        if time.time() >= deadline:
            raise RuntimeError("Controller operation could not acquire the lease; its action was not applied")
        time.sleep(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "package", "foundation", "install-app", "bake", "deploy", "disable", "resume", "restore-routing", "tick", "clear-override", "status"])
    parser.add_argument("--profile", default="arteamis-ci-operator")
    parser.add_argument("--app-file", type=Path)
    parser.add_argument("--ami")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--enable-canary", action="store_true")
    parser.add_argument("--alarm-topic")
    parser.add_argument("--repository")
    parser.add_argument("--execute", action="store_true", help="Execute the generated CI-only change set after offline template review")
    args = parser.parse_args()
    BUILD.mkdir(exist_ok=True)
    if args.command == "plan":
        write_json(BUILD / "foundation.json", stack.foundation())
        write_json(BUILD / "boundary.json", stack.boundary())
        print("Offline foundation and permissions-boundary plans:", BUILD)
        print("Isolated VPC; m6i.large; 100 GB gp3; maximum 2 ephemeral VMs; no production resource access")
        return
    if args.command == "package":
        package()
        return
    identity(args.profile)
    if args.command == "foundation":
        apply_stack(args.profile, "arteamis-ci-foundation", stack.foundation(), args.execute)
    elif args.command == "install-app":
        if not args.app_file:
            parser.error("install-app requires --app-file")
        install_app(args.profile, args.app_file)
    elif args.command == "bake":
        bake(args.profile)
    elif args.command == "deploy":
        if not args.ami:
            parser.error("deploy requires --ami")
        deploy(args.profile, args.ami, args.evidence, args.enable_canary or bool(args.evidence), args.alarm_topic, args.execute)
    elif args.command == "clear-override":
        config = json.loads((ROOT / "config.json").read_text())
        if args.repository not in config["repositories"]:
            parser.error("clear-override requires an allowlisted --repository")
        print(json.dumps(invoke(args.profile, args.command, args.repository)))
    else:
        print(json.dumps(invoke(args.profile, args.command)))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
