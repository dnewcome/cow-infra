from __future__ import annotations

import boto3

from .state import BASELINE_ACCOUNT_ID, LOCALSTACK_ENDPOINT, REGION


def _client(service: str, account_id: str):
    # LocalStack derives the account ID from a 12-digit numeric access key.
    return boto3.client(
        service,
        endpoint_url=LOCALSTACK_ENDPOINT,
        region_name=REGION,
        aws_access_key_id=account_id,
        aws_secret_access_key="test",
    )


def baseline_client(service: str):
    return _client(service, BASELINE_ACCOUNT_ID)


def sandbox_client(service: str, account_id: str):
    return _client(service, account_id)
