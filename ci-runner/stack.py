"""Generate the two CI-only CloudFormation stacks. No production resources are imported."""

import json
from pathlib import Path

CONFIG = json.loads(Path(__file__).with_name("config.json").read_text())
REGION = CONFIG["region"]
ACCOUNT = CONFIG["account"]
TAG = [{"Key": "ArteamisCiPool", "Value": "arteamis-ci"}]
BOUNDARY = f"arn:aws:iam::{ACCOUNT}:policy/ArteamisCiBoundary"


def ref(name):
    return {"Ref": name}


def attr(name, field):
    return {"Fn::GetAtt": [name, field]}


def statement(actions, resources, condition=None):
    result = {"Effect": "Allow", "Action": actions, "Resource": resources}
    if condition:
        result["Condition"] = condition
    return result


def document(statements):
    return {"Version": "2012-10-17", "Statement": statements}


def role(name, service, statements):
    return {"Type": "AWS::IAM::Role", "Properties": {
        "RoleName": name, "PermissionsBoundary": BOUNDARY, "Tags": TAG,
        "AssumeRolePolicyDocument": {"Version": "2012-10-17", "Statement": [{
            "Effect": "Allow", "Principal": {"Service": service}, "Action": "sts:AssumeRole"}]},
        "Policies": [{"PolicyName": "ci-only", "PolicyDocument": document(statements)}],
    }}


def ebs_permissions():
    condition = {"StringEquals": {"kms:ViaService": f"ec2.{REGION}.amazonaws.com", "kms:CallerAccount": ACCOUNT},
                 "ForAnyValue:StringEquals": {"kms:ResourceAliases": "alias/aws/ebs"}}
    key = f"arn:aws:kms:{REGION}:{ACCOUNT}:key/*"
    return [statement(["kms:Decrypt", "kms:DescribeKey", "kms:GenerateDataKeyWithoutPlaintext", "kms:ReEncrypt*"], key, condition),
            statement("kms:CreateGrant", key, {**condition, "Bool": {"kms:GrantIsForAWSResource": "true"}})]


def runtime_permissions():
    ec2 = f"arn:aws:ec2:{REGION}:{ACCOUNT}:"
    pool = {"StringEquals": {"ec2:ResourceTag/ArteamisCiPool": "arteamis-ci", "ec2:ResourceTag/ArteamisCiRole": ["runner", "builder"]}}
    return [
        statement("ec2:DescribeInstances", "*"),
        statement("ec2:TerminateInstances", ec2 + "instance/*", pool),
        statement("ec2:RunInstances", [ec2 + "subnet/*", ec2 + "security-group/*", ec2 + "launch-template/*"],
                  {"StringEquals": {"ec2:ResourceTag/ArteamisCiPool": "arteamis-ci"}}),
        statement("ec2:RunInstances", f"arn:aws:ec2:{REGION}::image/*",
                  {"StringEquals": {"ec2:ResourceTag/ArteamisCiPool": "arteamis-ci", "aws:ResourceAccount": ACCOUNT}}),
        statement("ec2:RunInstances", ec2 + "instance/*", {"StringEquals": {
            "aws:RequestTag/ArteamisCiPool": "arteamis-ci", "aws:RequestTag/ArteamisCiRole": "runner", "ec2:InstanceType": "m6i.large"}}),
        statement("ec2:RunInstances", [ec2 + "volume/*", ec2 + "network-interface/*"],
                  {"StringEquals": {"aws:RequestTag/ArteamisCiPool": "arteamis-ci", "aws:RequestTag/ArteamisCiRole": "runner"}}),
        statement("ec2:CreateTags", [ec2 + "instance/*", ec2 + "volume/*", ec2 + "network-interface/*"],
                  {"StringEquals": {"ec2:CreateAction": "RunInstances", "aws:RequestTag/ArteamisCiPool": "arteamis-ci"}}),
        statement("iam:PassRole", f"arn:aws:iam::{ACCOUNT}:role/arteamis-ci-runner",
                  {"StringEquals": {"iam:PassedToService": "ec2.amazonaws.com"}}),
        statement(["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"],
                  f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/arteamis-ci-state"),
        statement("ssm:GetParameter", f"arn:aws:ssm:{REGION}:{ACCOUNT}:parameter/arteamis/ci/github-app"),
        statement("kms:Decrypt", f"arn:aws:kms:{REGION}:{ACCOUNT}:key/*", {"StringEquals": {
            "kms:ViaService": f"ssm.{REGION}.amazonaws.com",
            "kms:EncryptionContext:PARAMETER_ARN": f"arn:aws:ssm:{REGION}:{ACCOUNT}:parameter/arteamis/ci/github-app"}}),
        statement(["logs:CreateLogStream", "logs:PutLogEvents"],
                  f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/lambda/arteamis-ci-*:log-stream:*"),
    ] + ebs_permissions()


def ssm_permissions():
    return [statement("ssm:UpdateInstanceInformation", "*"),
            statement(["ssmmessages:CreateControlChannel", "ssmmessages:CreateDataChannel",
                       "ssmmessages:OpenControlChannel", "ssmmessages:OpenDataChannel"], "*")]


def boundary():
    # Administrator-managed. The operator cannot remove or modify this boundary.
    return document(runtime_permissions() + ssm_permissions() + [
        statement("lambda:InvokeFunction", [f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:arteamis-ci-controller",
                                             f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:arteamis-ci-reaper"]),
    ])


def foundation():
    resources = {
        "Vpc": {"Type": "AWS::EC2::VPC", "Properties": {"CidrBlock": "10.78.0.0/24", "EnableDnsSupport": True, "EnableDnsHostnames": True, "Tags": TAG}},
        "Subnet": {"Type": "AWS::EC2::Subnet", "Properties": {"VpcId": ref("Vpc"), "CidrBlock": "10.78.0.0/26", "MapPublicIpOnLaunch": True, "Tags": TAG}},
        "Gateway": {"Type": "AWS::EC2::InternetGateway", "Properties": {"Tags": TAG}},
        "Attachment": {"Type": "AWS::EC2::VPCGatewayAttachment", "Properties": {"VpcId": ref("Vpc"), "InternetGatewayId": ref("Gateway")}},
        "RouteTable": {"Type": "AWS::EC2::RouteTable", "Properties": {"VpcId": ref("Vpc"), "Tags": TAG}},
        "Route": {"Type": "AWS::EC2::Route", "DependsOn": "Attachment", "Properties": {"RouteTableId": ref("RouteTable"), "DestinationCidrBlock": "0.0.0.0/0", "GatewayId": ref("Gateway")}},
        "Association": {"Type": "AWS::EC2::SubnetRouteTableAssociation", "Properties": {"SubnetId": ref("Subnet"), "RouteTableId": ref("RouteTable")}},
        "SecurityGroup": {"Type": "AWS::EC2::SecurityGroup", "Properties": {"GroupDescription": "Isolated Arteamis CI, no inbound access", "VpcId": ref("Vpc"), "Tags": TAG,
            "SecurityGroupEgress": [{"IpProtocol": "tcp", "FromPort": port, "ToPort": port, "CidrIp": "0.0.0.0/0"} for port in (22, 80, 443)]}},
        "RunnerRole": role("arteamis-ci-runner", "ec2.amazonaws.com", ssm_permissions()),
        "RunnerProfile": {"Type": "AWS::IAM::InstanceProfile", "Properties": {"InstanceProfileName": "arteamis-ci-runner", "Roles": [ref("RunnerRole")]}},
        "ControllerRole": role("arteamis-ci-controller", "lambda.amazonaws.com", runtime_permissions()),
        "ReaperRole": role("arteamis-ci-reaper", "lambda.amazonaws.com", [s for s in runtime_permissions()
            if s["Action"] in ("ec2:DescribeInstances", "ec2:TerminateInstances") or isinstance(s["Action"], list) and "logs:PutLogEvents" in s["Action"]]),
        "SchedulerRole": role("arteamis-ci-scheduler", "scheduler.amazonaws.com", [statement("lambda:InvokeFunction", [
            f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:arteamis-ci-controller", f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:arteamis-ci-reaper"])]),
        "State": {"Type": "AWS::DynamoDB::Table", "DeletionPolicy": "Retain", "UpdateReplacePolicy": "Retain", "Properties": {
            "TableName": "arteamis-ci-state", "BillingMode": "PAY_PER_REQUEST", "AttributeDefinitions": [{"AttributeName": "key", "AttributeType": "S"}],
            "KeySchema": [{"AttributeName": "key", "KeyType": "HASH"}], "PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True}, "Tags": TAG}},
        "Artifacts": {"Type": "AWS::S3::Bucket", "DeletionPolicy": "Retain", "UpdateReplacePolicy": "Retain", "Properties": {
            "BucketName": f"arteamis-ci-artifacts-{ACCOUNT}-{REGION}", "Tags": TAG, "VersioningConfiguration": {"Status": "Enabled"},
            "BucketEncryption": {"ServerSideEncryptionConfiguration": [{"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]},
            "LifecycleConfiguration": {"Rules": [{"Id": "BoundedControllerArtifacts", "Status": "Enabled", "Prefix": "controller/",
                "ExpirationInDays": 90, "NoncurrentVersionExpiration": {"NoncurrentDays": 14},
                "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1}}]},
            "PublicAccessBlockConfiguration": {k: True for k in ["BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"]}}},
        "ArtifactPolicy": {"Type": "AWS::S3::BucketPolicy", "Properties": {"Bucket": ref("Artifacts"), "PolicyDocument": document([{
            "Effect": "Deny", "Principal": "*", "Action": "s3:*", "Resource": [attr("Artifacts", "Arn"), {"Fn::Join": ["", [attr("Artifacts", "Arn"), "/*"]]}],
            "Condition": {"Bool": {"aws:SecureTransport": "false"}}}])}},
    }
    for key, name in (("ControllerLogs", "arteamis-ci-controller"), ("ReaperLogs", "arteamis-ci-reaper")):
        resources[key] = {"Type": "AWS::Logs::LogGroup", "Properties": {"LogGroupName": "/aws/lambda/" + name, "RetentionInDays": 14, "Tags": TAG}}
    return {"AWSTemplateFormatVersion": "2010-09-09", "Description": "Arteamis isolated CI runner foundation", "Resources": resources,
            "Outputs": {key: {"Value": value} for key, value in {"SubnetId": ref("Subnet"), "SecurityGroupId": ref("SecurityGroup"),
                "RunnerProfileArn": attr("RunnerProfile", "Arn"), "ArtifactBucket": ref("Artifacts")}.items()}}


def runtime(ami, artifact_key, outputs, routing_verified=False, enabled=False, alarm_topic=None, qualification_only=True):
    role_arn = lambda name: f"arn:aws:iam::{ACCOUNT}:role/{name}"
    resources = {
        "LaunchTemplate": {"Type": "AWS::EC2::LaunchTemplate", "Properties": {"LaunchTemplateName": "arteamis-ci-runner", "TagSpecifications": [{"ResourceType": "launch-template", "Tags": TAG}],
            "LaunchTemplateData": {"ImageId": ami, "InstanceType": "m6i.large", "IamInstanceProfile": {"Arn": outputs["RunnerProfileArn"]},
                "InstanceInitiatedShutdownBehavior": "terminate", "MetadataOptions": {"HttpTokens": "required", "HttpPutResponseHopLimit": 1},
                "NetworkInterfaces": [{"DeviceIndex": 0, "AssociatePublicIpAddress": True, "SubnetId": outputs["SubnetId"], "Groups": [outputs["SecurityGroupId"]], "DeleteOnTermination": True}],
                "BlockDeviceMappings": [{"DeviceName": "/dev/sda1", "Ebs": {"VolumeSize": 100, "VolumeType": "gp3", "Encrypted": True,
                    "KmsKeyId": f"arn:aws:kms:{REGION}:{ACCOUNT}:alias/aws/ebs", "DeleteOnTermination": True}}],
                "TagSpecifications": [{"ResourceType": "network-interface", "Tags": TAG + [{"Key": "ArteamisCiRole", "Value": "runner"}]}]}}},
    }
    # The DynamoDB lease serializes controller mutations. Reserving Lambda
    # concurrency can violate this account's minimum unreserved quota.
    for key, name, handler in (("Controller", "arteamis-ci-controller", "controller.lambda_handler"), ("Reaper", "arteamis-ci-reaper", "reaper.lambda_handler")):
        properties = {"FunctionName": name, "Role": role_arn(name), "Runtime": "python3.12", "Architectures": ["x86_64"], "Handler": handler,
                      "Timeout": 300 if key == "Controller" else 30, "MemorySize": 256 if key == "Controller" else 128,
                      "Code": {"S3Bucket": outputs["ArtifactBucket"], "S3Key": artifact_key}, "Tags": TAG}
        if key == "Controller":
            properties["Environment"] = {"Variables": {"STATE_TABLE": "arteamis-ci-state", "APP_PARAMETER": "/arteamis/ci/github-app",
                "LAUNCH_TEMPLATE": ref("LaunchTemplate"), "LAUNCH_TEMPLATE_VERSION": attr("LaunchTemplate", "LatestVersionNumber"),
                "ROUTING_VERIFIED": str(routing_verified).lower(), "QUALIFICATION_ONLY": str(qualification_only).lower()}}
        resources[key] = {"Type": "AWS::Lambda::Function", "Properties": properties}
        resources[key + "Schedule"] = {"Type": "AWS::Scheduler::Schedule", "Properties": {
            "Name": name, "ScheduleExpression": "rate(1 minute)", "FlexibleTimeWindow": {"Mode": "OFF"},
            "State": "ENABLED" if key == "Reaper" or enabled else "DISABLED",
            "Target": {"Arn": attr(key, "Arn"), "RoleArn": role_arn("arteamis-ci-scheduler"), "Input": "{}",
                       "RetryPolicy": {"MaximumEventAgeInSeconds": 60, "MaximumRetryAttempts": 0}}}}
        resources[key + "ErrorAlarm"] = {"Type": "AWS::CloudWatch::Alarm", "Properties": {"AlarmName": name + "-errors", "Namespace": "AWS/Lambda",
            "MetricName": "Errors", "Dimensions": [{"Name": "FunctionName", "Value": name}], "Statistic": "Sum", "Period": 300,
            "EvaluationPeriods": 1, "Threshold": 1, "ComparisonOperator": "GreaterThanOrEqualToThreshold", "TreatMissingData": "notBreaching"}}
    resources["ControllerErrorFilter"] = {"Type": "AWS::Logs::MetricFilter", "Properties": {"LogGroupName": "/aws/lambda/arteamis-ci-controller",
        "FilterPattern": '{ ($.event = "repository-error") || ($.event = "vm-launch-error") || ($.event = "vm-launch-limit") }',
        "MetricTransformations": [{"MetricNamespace": "Arteamis/CI", "MetricName": "ControllerFailures", "MetricValue": "1", "DefaultValue": 0}]}}
    resources["ControllerFailureAlarm"] = {"Type": "AWS::CloudWatch::Alarm", "Properties": {"AlarmName": "arteamis-ci-controller-failures", "Namespace": "Arteamis/CI",
        "MetricName": "ControllerFailures", "Statistic": "Sum", "Period": 300, "EvaluationPeriods": 1, "Threshold": 1,
        "ComparisonOperator": "GreaterThanOrEqualToThreshold", "TreatMissingData": "notBreaching"}}
    for key, name, group, pattern in (
        ("QueueDelay", "queue-delay", "arteamis-ci-controller", '{ $.event = "queue-delayed" }'),
        ("ExpiredVm", "expired-vm", "arteamis-ci-reaper", '{ $.terminated > 0 }'),
    ):
        resources[key + "Filter"] = {"Type": "AWS::Logs::MetricFilter", "Properties": {
            "LogGroupName": "/aws/lambda/" + group, "FilterPattern": pattern,
            "MetricTransformations": [{"MetricNamespace": "Arteamis/CI", "MetricName": key, "MetricValue": "1", "DefaultValue": 0}]}}
        resources[key + "Alarm"] = {"Type": "AWS::CloudWatch::Alarm", "Properties": {
            "AlarmName": "arteamis-ci-" + name, "Namespace": "Arteamis/CI", "MetricName": key, "Statistic": "Sum", "Period": 300,
            "EvaluationPeriods": 1, "Threshold": 1, "ComparisonOperator": "GreaterThanOrEqualToThreshold", "TreatMissingData": "notBreaching"}}
    if alarm_topic:
        for resource in resources.values():
            if resource["Type"] == "AWS::CloudWatch::Alarm":
                resource["Properties"]["AlarmActions"] = [alarm_topic]
                resource["Properties"]["OKActions"] = [alarm_topic]
                resource["Properties"]["Tags"] = TAG
    return {"AWSTemplateFormatVersion": "2010-09-09", "Description": "Arteamis bounded ephemeral CI runner control plane", "Resources": resources,
            "Outputs": {"LaunchTemplateId": {"Value": ref("LaunchTemplate")}}}


if __name__ == "__main__":
    target = Path(__file__).with_name("generated")
    target.mkdir(exist_ok=True)
    for name, value in (("foundation.json", foundation()), ("boundary.json", boundary())):
        (target / name).write_text(json.dumps(value, indent=2) + "\n")
    sample = runtime("ami-00000000000000000", "controller/preview.zip", {"SubnetId": "subnet-00000000000000000",
        "SecurityGroupId": "sg-00000000000000000", "RunnerProfileArn": f"arn:aws:iam::{ACCOUNT}:instance-profile/arteamis-ci-runner",
        "ArtifactBucket": f"arteamis-ci-artifacts-{ACCOUNT}-{REGION}"})
    (target / "runtime-preview.json").write_text(json.dumps(sample, indent=2) + "\n")
    print(str(target))
