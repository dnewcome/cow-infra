from __future__ import annotations

from .aws import baseline_client, sandbox_client
from .state import State


def shadow_bucket_name(branch_name: str, bucket: str) -> str:
    # S3 bucket names are globally unique even across LocalStack accounts,
    # so shadow buckets get a per-branch prefix. The prefix is an implementation
    # detail — users always reference the logical bucket name.
    return f"cow-{branch_name}-{bucket}".lower()


def resolve_s3(state: State, bucket: str):
    """Return (client, effective_bucket_name) for reads/writes of `bucket`."""
    br = state.active()
    if bucket in br.shadowed_s3:
        return sandbox_client("s3", br.account_id), shadow_bucket_name(br.name, bucket)
    return baseline_client("s3"), bucket


def resolve_ddb(state: State, table: str):
    """Return (client, effective_table_name) for reads/writes of `table`.

    DDB table names scope per-account, so the effective name is always the
    logical name — only the client differs.
    """
    br = state.active()
    if table in br.shadowed_ddb:
        return sandbox_client("dynamodb", br.account_id), table
    return baseline_client("dynamodb"), table


def ensure_shadow_s3(state: State, bucket: str) -> None:
    br = state.active()
    if bucket in br.shadowed_s3:
        return
    base = baseline_client("s3")
    sand = sandbox_client("s3", br.account_id)
    shadow_name = shadow_bucket_name(br.name, bucket)
    try:
        sand.create_bucket(Bucket=shadow_name)
    except sand.exceptions.BucketAlreadyOwnedByYou:
        pass
    paginator = base.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            body = base.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
            sand.put_object(Bucket=shadow_name, Key=obj["Key"], Body=body)
    br.shadowed_s3.append(bucket)
    state.save()
    print(f"[cow] shadowed s3://{bucket} into {br.name} (as {shadow_name})")


def ensure_shadow_ddb(state: State, table: str) -> None:
    br = state.active()
    if table in br.shadowed_ddb:
        return
    base = baseline_client("dynamodb")
    sand = sandbox_client("dynamodb", br.account_id)
    desc = base.describe_table(TableName=table)["Table"]
    try:
        sand.create_table(
            TableName=table,
            KeySchema=desc["KeySchema"],
            AttributeDefinitions=desc["AttributeDefinitions"],
            BillingMode="PAY_PER_REQUEST",
        )
        sand.get_waiter("table_exists").wait(TableName=table)
    except sand.exceptions.ResourceInUseException:
        pass
    paginator = base.get_paginator("scan")
    for page in paginator.paginate(TableName=table):
        for item in page.get("Items", []):
            sand.put_item(TableName=table, Item=item)
    br.shadowed_ddb.append(table)
    state.save()
    print(f"[cow] shadowed ddb:{table} into {br.name}")
