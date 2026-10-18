"""Generate a separate CI setup policy; never edit ArteamisOperatorAccess."""

import json
from pathlib import Path
from stack import ACCOUNT, REGION, BOUNDARY, document, statement, ebs_permissions


def setup_policy():
    ec2 = f"arn:aws:ec2:{REGION}:{ACCOUNT}:"
    image = f"arn:aws:ec2:{REGION}::image/*"
    snapshot = f"arn:aws:ec2:{REGION}::snapshot/*"
    ci = {"StringEquals": {"ec2:ResourceTag/ArteamisCiPool": "arteamis-ci"}}
    requested = {"StringEquals": {"aws:RequestTag/ArteamisCiPool": "arteamis-ci"}}
    role_names = ("arteamis-ci-runner", "arteamis-ci-controller", "arteamis-ci-reaper", "arteamis-ci-scheduler")
    roles = [f"arn:aws:iam::{ACCOUNT}:role/{name}" for name in role_names]
    bucket = f"arn:aws:s3:::arteamis-ci-artifacts-{ACCOUNT}-{REGION}"
    statements = [
        statement(["cloudformation:CreateChangeSet", "cloudformation:DescribeChangeSet", "cloudformation:ExecuteChangeSet", "cloudformation:DeleteChangeSet", "cloudformation:CreateStack", "cloudformation:UpdateStack", "cloudformation:DeleteStack", "cloudformation:DescribeStacks", "cloudformation:DescribeStackEvents", "cloudformation:GetTemplate"],
                  [f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/arteamis-ci-foundation/*",
                   f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/arteamis-ci-runtime/*",
                   f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:changeSet/arteamis-ci-review-*/*"]),
        statement("cloudformation:DescribeStacks", f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/arteamis-ci-alerts/*"),
        statement("cloudformation:ValidateTemplate", "*"),
        statement("sts:DecodeAuthorizationMessage", "*"),
        statement("iam:CreateRole", roles, {"StringEquals": {"iam:PermissionsBoundary": BOUNDARY}}),
        statement(["iam:GetRole", "iam:DeleteRole", "iam:TagRole", "iam:UntagRole", "iam:UpdateAssumeRolePolicy", "iam:PutRolePolicy", "iam:GetRolePolicy", "iam:DeleteRolePolicy", "iam:ListRolePolicies"], roles),
        statement(["iam:CreateInstanceProfile", "iam:GetInstanceProfile", "iam:AddRoleToInstanceProfile", "iam:RemoveRoleFromInstanceProfile", "iam:DeleteInstanceProfile", "iam:TagInstanceProfile"],
                  f"arn:aws:iam::{ACCOUNT}:instance-profile/arteamis-ci-runner"),
        statement("iam:PassRole", roles, {"StringEquals": {"iam:PassedToService": ["ec2.amazonaws.com", "lambda.amazonaws.com", "scheduler.amazonaws.com"]}}),
        statement("iam:GetPolicy", BOUNDARY),
        statement(["ec2:DescribeVpcs", "ec2:DescribeVpcAttribute", "ec2:DescribeSubnets", "ec2:DescribeSecurityGroups", "ec2:DescribeRouteTables", "ec2:DescribeInternetGateways", "ec2:DescribeInstances", "ec2:DescribeVolumes", "ec2:DescribeImages", "ec2:DescribeSnapshots", "ec2:DescribeLaunchTemplates", "ec2:DescribeLaunchTemplateVersions", "ec2:DescribeInstanceAttribute", "ec2:DescribeTags"], "*"),
        statement(["ec2:CreateVpc", "ec2:CreateInternetGateway", "ec2:CreateLaunchTemplate"], ec2 + "*", requested),
        statement(["ec2:CreateSubnet", "ec2:CreateSecurityGroup", "ec2:CreateRouteTable"], ec2 + "vpc/*", ci),
        statement(["ec2:CreateSubnet", "ec2:CreateSecurityGroup", "ec2:CreateRouteTable"], [ec2 + "subnet/*", ec2 + "security-group/*", ec2 + "route-table/*"], requested),
        statement(["ec2:ModifyVpcAttribute", "ec2:DeleteVpc", "ec2:DeleteSubnet", "ec2:ModifySubnetAttribute", "ec2:AuthorizeSecurityGroupEgress", "ec2:RevokeSecurityGroupEgress", "ec2:DeleteSecurityGroup", "ec2:CreateRoute", "ec2:DeleteRoute", "ec2:DeleteRouteTable", "ec2:AssociateRouteTable", "ec2:DisassociateRouteTable", "ec2:AttachInternetGateway", "ec2:DetachInternetGateway", "ec2:DeleteInternetGateway", "ec2:CreateLaunchTemplateVersion", "ec2:ModifyLaunchTemplate", "ec2:DeleteLaunchTemplate", "ec2:DeleteLaunchTemplateVersions", "ec2:TerminateInstances"], ec2 + "*", ci),
        statement(["ec2:DeregisterImage", "ec2:DeleteSnapshot"], [image, snapshot], ci),
        statement("ec2:CreateTags", [ec2 + "*", image, snapshot], {"StringEquals": {
            "aws:RequestTag/ArteamisCiPool": "arteamis-ci", "ec2:CreateAction": ["RunInstances", "CreateVpc", "CreateSubnet", "CreateSecurityGroup", "CreateRouteTable", "CreateInternetGateway", "CreateLaunchTemplate", "CreateImage"]}}),
        statement("ec2:CreateTags", [ec2 + "*", image, snapshot], ci),
        statement("ec2:DeleteTags", [ec2 + "*", image, snapshot], ci),
        statement("ec2:RunInstances", [ec2 + "subnet/*", ec2 + "security-group/*", ec2 + "launch-template/*"], ci),
        # Trusted public Ubuntu images report ec2:Owner=amazon, not Canonical's ID.
        # ResourceAccount preserves the account restriction without admitting every Amazon AMI.
        statement("ec2:RunInstances", f"arn:aws:ec2:{REGION}::image/*", {"StringEquals": {"aws:ResourceAccount": [ACCOUNT, "099720109477"]}}),
        statement("ec2:RunInstances", ec2 + "instance/*", {"StringEquals": {"aws:RequestTag/ArteamisCiPool": "arteamis-ci", "ec2:InstanceType": "m6i.large"}}),
        statement("ec2:RunInstances", [ec2 + "volume/*", ec2 + "network-interface/*"], requested),
        statement("ec2:CreateImage", ec2 + "instance/*", {"StringEquals": {"ec2:ResourceTag/ArteamisCiPool": "arteamis-ci", "ec2:ResourceTag/ArteamisCiRole": "builder"}}),
        statement("ec2:CreateImage", [image, snapshot], requested),
        statement(["lambda:CreateFunction", "lambda:GetFunction*", "lambda:GetRuntimeManagementConfig", "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration", "lambda:PutFunctionConcurrency", "lambda:DeleteFunctionConcurrency", "lambda:DeleteFunction", "lambda:TagResource", "lambda:UntagResource", "lambda:ListTags", "lambda:InvokeFunction"], f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:arteamis-ci-*"),
        statement(["dynamodb:CreateTable", "dynamodb:DescribeTable", "dynamodb:UpdateTable", "dynamodb:UpdateContinuousBackups", "dynamodb:DescribeContinuousBackups", "dynamodb:DeleteTable", "dynamodb:TagResource", "dynamodb:UntagResource", "dynamodb:ListTagsOfResource"], f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/arteamis-ci-state"),
        statement(["s3:CreateBucket", "s3:GetBucket*", "s3:PutBucketTagging", "s3:PutEncryptionConfiguration", "s3:GetEncryptionConfiguration", "s3:PutBucketPublicAccessBlock", "s3:PutBucketVersioning", "s3:PutLifecycleConfiguration", "s3:GetLifecycleConfiguration", "s3:PutBucketPolicy", "s3:DeleteBucketPolicy", "s3:ListBucket"], bucket),
        statement(["s3:PutObject", "s3:GetObject"], bucket + "/controller/*"),
        statement("logs:DescribeLogGroups", "*"),
        statement(["logs:CreateLogGroup", "logs:PutRetentionPolicy", "logs:DeleteLogGroup", "logs:TagResource", "logs:UntagResource", "logs:ListTagsForResource", "logs:PutMetricFilter", "logs:DeleteMetricFilter", "logs:DescribeMetricFilters", "logs:FilterLogEvents"], f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/lambda/arteamis-ci-*"),
        statement(["cloudwatch:PutMetricAlarm", "cloudwatch:DescribeAlarms", "cloudwatch:DeleteAlarms", "cloudwatch:TagResource", "cloudwatch:UntagResource", "cloudwatch:ListTagsForResource"], f"arn:aws:cloudwatch:{REGION}:{ACCOUNT}:alarm:arteamis-ci-*"),
        statement(["scheduler:CreateSchedule", "scheduler:UpdateSchedule", "scheduler:GetSchedule", "scheduler:DeleteSchedule"], f"arn:aws:scheduler:{REGION}:{ACCOUNT}:schedule/default/arteamis-ci-*"),
        statement("ssm:PutParameter", f"arn:aws:ssm:{REGION}:{ACCOUNT}:parameter/arteamis/ci/github-app"),
        statement("ssm:GetParameter", f"arn:aws:ssm:{REGION}:*:parameter/aws/service/canonical/ubuntu/server/24.04/*"),
        statement("ssm:SendCommand", ec2 + "instance/*", {"StringEquals": {"ssm:resourceTag/ArteamisCiPool": "arteamis-ci", "ssm:resourceTag/ArteamisCiRole": "builder"}}),
        statement("ssm:SendCommand", f"arn:aws:ssm:{REGION}::document/AWS-RunShellScript"),
        statement(["ssm:GetCommandInvocation", "ssm:DescribeInstanceInformation"], "*"),
    ]
    return document(statements + ebs_permissions())


def generate():
    path = Path(__file__).with_name("generated")
    path.mkdir(exist_ok=True)
    groups = {"identity": [], "network": [], "services": []}
    for item in setup_policy()["Statement"]:
        actions = item["Action"] if isinstance(item["Action"], list) else [item["Action"]]
        group = "identity" if actions[0].startswith(("iam:", "cloudformation:", "sts:")) else "network" if actions[0].startswith("ec2:") else "services"
        groups[group].append(item)
    resources = {"Boundary": {"Type": "AWS::IAM::ManagedPolicy", "Properties": {
        "ManagedPolicyName": "ArteamisCiBoundary", "PolicyDocument": __import__("stack").boundary()}}}
    resources["OperatorRole"] = {"Type": "AWS::IAM::Role", "Properties": {
        "RoleName": "arteamis-ci-operator", "MaxSessionDuration": 3600,
        "AssumeRolePolicyDocument": document([{
            "Effect": "Allow", "Principal": {"AWS": {"Ref": "OperatorPrincipalArn"}}, "Action": "sts:AssumeRole"}])}}
    for name, statements in groups.items():
        policy = document(statements)
        if len(json.dumps(policy, separators=(",", ":"))) > 6144:
            raise ValueError("Managed IAM policy size limit exceeded")
        (path / ("setup-" + name + ".json")).write_text(json.dumps(policy, indent=2) + "\n")
        print(path / ("setup-" + name + ".json"))
        resources[name.title()] = {"Type": "AWS::IAM::ManagedPolicy", "DependsOn": "Boundary", "Properties": {
            "ManagedPolicyName": "ArteamisCiSetup" + name.title(), "Roles": [{"Ref": "OperatorRole"}], "PolicyDocument": policy}}
    (path / "admin-bootstrap.json").write_text(json.dumps({"AWSTemplateFormatVersion": "2010-09-09",
        "Description": "Dedicated Arteamis CI setup permissions, preserving the existing production operator policy", "Parameters": {"OperatorPrincipalArn": {"Type": "String",
        "Description": "Existing non-root IAM role or user allowed to assume the CI-only operator role",
        "AllowedPattern": "arn:aws:iam::" + ACCOUNT + ":(role|user)/.+"}}, "Resources": resources}, indent=2) + "\n")


if __name__ == "__main__":
    generate()
