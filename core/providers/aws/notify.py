"""SnsNotifier: tells the super admin that someone asked for access.

One SNS topic (the stack's AccessRequests topic), with the super admin's email
subscribed at deploy time (-c admin_email=...). The message names the
requester, the role and where to decide; never a password.
"""
from __future__ import annotations

import boto3

from core.providers.aws import session as shared

from core.providers.aws.config import REGION


class SnsNotifier:
    def __init__(self, topic_arn: str, region: str = REGION, client=None):
        self.topic = topic_arn
        self.sns = client or shared.client("sns", region)

    def __call__(self, subject: str, message: str) -> None:
        self.sns.publish(TopicArn=self.topic, Subject=subject[:100], Message=message)
