"""Administrator-owned CI alerts and tag-filtered monthly budget.

The notification address is supplied privately in the AWS console.
"""

import json
from pathlib import Path

from stack import ACCOUNT, REGION
TOPIC = f"arn:aws:sns:{REGION}:{ACCOUNT}:arteamis-ci-alerts"
TAGS = [{"Key": "ArteamisCiPool", "Value": "arteamis-ci"}]


def template():
    notifications = []
    for kind, threshold in (("ACTUAL", 80), ("ACTUAL", 100), ("FORECASTED", 100)):
        notifications.append({
            "Notification": {"NotificationType": kind, "ComparisonOperator": "GREATER_THAN",
                             "ThresholdType": "PERCENTAGE", "Threshold": threshold},
            "Subscribers": [{"SubscriptionType": "SNS", "Address": {"Ref": "Topic"}}],
        })
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "Arteamis CI-only notifications and monthly cost alert; no IAM or production changes",
        "Parameters": {
            "AlertEmail": {"Type": "String", "NoEcho": True,
                           "Description": "Your CI alert email. Enter it only here, then confirm AWS's subscription email.",
                           "AllowedPattern": r"^[^\s@]+@[^\s@]+\.[^\s@]+$"},
            "MonthlyUsd": {"Type": "Number", "Default": 20, "MinValue": 1, "MaxValue": 1000,
                           "Description": "Monthly CI budget in USD. Notifications do not stop running jobs."},
        },
        "Resources": {
            "Topic": {"Type": "AWS::SNS::Topic", "Properties": {
                "TopicName": "arteamis-ci-alerts", "DisplayName": "Arteamis CI alerts", "Tags": TAGS}},
            "TopicPolicy": {"Type": "AWS::SNS::TopicPolicy", "Properties": {
                "Topics": [{"Ref": "Topic"}], "PolicyDocument": {
                    "Id": TOPIC + "/policy", "Version": "2012-10-17", "Statement": [
                        {"Sid": "CloudWatchCiAlarmsPublish", "Effect": "Allow", "Principal": {"Service": "cloudwatch.amazonaws.com"},
                         "Action": "sns:Publish", "Resource": {"Ref": "Topic"},
                         "Condition": {"StringEquals": {"aws:SourceAccount": ACCOUNT},
                                       "ArnLike": {"aws:SourceArn": f"arn:aws:cloudwatch:{REGION}:{ACCOUNT}:alarm:arteamis-ci-*"}}},
                        {"Sid": "BudgetsCiMonthlyPublish", "Effect": "Allow", "Principal": {"Service": "budgets.amazonaws.com"},
                         "Action": "sns:Publish", "Resource": {"Ref": "Topic"},
                         "Condition": {"StringEquals": {"aws:SourceAccount": ACCOUNT},
                                       "ArnEquals": {"aws:SourceArn": f"arn:aws:budgets::{ACCOUNT}:budget/arteamis-ci-monthly"}}},
                    ]}}},
            "Subscription": {"Type": "AWS::SNS::Subscription", "Properties": {
                "TopicArn": {"Ref": "Topic"}, "Protocol": "email", "Endpoint": {"Ref": "AlertEmail"}}},
            "Budget": {"Type": "AWS::Budgets::Budget", "DependsOn": "TopicPolicy", "Properties": {
                "Budget": {"BudgetName": "arteamis-ci-monthly", "BudgetType": "COST", "TimeUnit": "MONTHLY",
                           "BudgetLimit": {"Amount": {"Ref": "MonthlyUsd"}, "Unit": "USD"},
                           "Metrics": ["UnblendedCost"],
                           "FilterExpression": {"Tags": {"Key": "ArteamisCiPool", "Values": ["arteamis-ci"], "MatchOptions": ["EQUALS"]}}},
                "NotificationsWithSubscribers": notifications,
                "ResourceTags": TAGS}},
        },
        "Outputs": {"TopicArn": {"Value": {"Ref": "Topic"}},
                    "BudgetName": {"Value": "arteamis-ci-monthly"}},
    }


if __name__ == "__main__":
    import sys
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("generated") / "admin-alerts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(template(), indent=2) + "\n")
    print(path)
