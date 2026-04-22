from __future__ import annotations

import json
import sys
from pathlib import Path

from .aws import baseline_client, sandbox_client
from .shadow import (
    ensure_shadow_ddb,
    ensure_shadow_s3,
    resolve_ddb,
    resolve_s3,
    shadow_bucket_name,
)
from .state import Branch, State

DEMO_BUCKET = "demo-bucket"
DEMO_TABLE = "demo-items"


def cmd_init(args):
    s3 = baseline_client("s3")
    ddb = baseline_client("dynamodb")

    try:
        s3.create_bucket(Bucket=DEMO_BUCKET)
    except s3.exceptions.BucketAlreadyOwnedByYou:
        pass
    s3.put_object(Bucket=DEMO_BUCKET, Key="README.txt", Body=b"Baseline README.\n")
    s3.put_object(
        Bucket=DEMO_BUCKET,
        Key="config.json",
        Body=json.dumps({"env": "baseline", "version": 1}).encode(),
    )

    try:
        ddb.create_table(
            TableName=DEMO_TABLE,
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        ddb.get_waiter("table_exists").wait(TableName=DEMO_TABLE)
    except ddb.exceptions.ResourceInUseException:
        pass
    ddb.put_item(
        TableName=DEMO_TABLE,
        Item={"id": {"S": "1"}, "name": {"S": "Widget"}, "price": {"N": "9.99"}},
    )
    ddb.put_item(
        TableName=DEMO_TABLE,
        Item={"id": {"S": "2"}, "name": {"S": "Gadget"}, "price": {"N": "14.50"}},
    )
    print(f"Baseline seeded: s3://{DEMO_BUCKET} (2 objects), ddb:{DEMO_TABLE} (2 items)")


def cmd_branch(args):
    state = State.load()
    if args.name in state.branches:
        raise SystemExit(f"Branch {args.name!r} already exists.")
    account_id = state.new_account_id()
    state.branches[args.name] = Branch(name=args.name, account_id=account_id)
    state.active_branch = args.name
    state.save()
    print(f"Created branch {args.name!r} (account {account_id}) and set it active.")


def cmd_use(args):
    state = State.load()
    if args.name not in state.branches:
        raise SystemExit(f"No such branch: {args.name!r}")
    state.active_branch = args.name
    state.save()
    print(f"Active branch: {args.name!r}")


def cmd_current(args):
    state = State.load()
    if not state.active_branch:
        print("(no active branch)")
        return
    br = state.branches[state.active_branch]
    print(f"{br.name} (account {br.account_id})")
    print(f"  shadowed s3:  {br.shadowed_s3 or '-'}")
    print(f"  shadowed ddb: {br.shadowed_ddb or '-'}")


def cmd_branches(args):
    state = State.load()
    if not state.branches:
        print("(no branches)")
        return
    for name, br in state.branches.items():
        marker = "*" if name == state.active_branch else " "
        print(
            f"{marker} {name:20s} account={br.account_id}  "
            f"s3={len(br.shadowed_s3)}  ddb={len(br.shadowed_ddb)}"
        )


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise SystemExit(f"Not an s3 URI: {uri}")
    rest = uri[5:]
    if "/" in rest:
        bucket, key = rest.split("/", 1)
    else:
        bucket, key = rest, ""
    return bucket, key


def cmd_s3_ls(args):
    state = State.load()
    bucket, prefix = _parse_s3_uri(args.uri)
    client, eff_bucket = resolve_s3(state, bucket)
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=eff_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            print(f"{obj['Size']:>10}  {obj['Key']}")


def cmd_s3_put(args):
    state = State.load()
    bucket, key = _parse_s3_uri(args.uri)
    if not key:
        raise SystemExit("s3 put requires s3://bucket/key")
    ensure_shadow_s3(state, bucket)
    body = sys.stdin.buffer.read() if args.file == "-" else Path(args.file).read_bytes()
    client, eff_bucket = resolve_s3(state, bucket)
    client.put_object(Bucket=eff_bucket, Key=key, Body=body)
    print(f"put s3://{bucket}/{key} ({len(body)} bytes) -> {state.active_branch}")


def cmd_s3_rm(args):
    state = State.load()
    bucket, key = _parse_s3_uri(args.uri)
    if not key:
        raise SystemExit("s3 rm requires s3://bucket/key")
    ensure_shadow_s3(state, bucket)
    client, eff_bucket = resolve_s3(state, bucket)
    client.delete_object(Bucket=eff_bucket, Key=key)
    print(f"removed s3://{bucket}/{key} from {state.active_branch}")


def cmd_ddb_scan(args):
    state = State.load()
    client, eff_table = resolve_ddb(state, args.table)
    paginator = client.get_paginator("scan")
    for page in paginator.paginate(TableName=eff_table):
        for item in page.get("Items", []):
            print(json.dumps(item))


def cmd_ddb_put(args):
    state = State.load()
    ensure_shadow_ddb(state, args.table)
    item = json.loads(args.item)
    client, eff_table = resolve_ddb(state, args.table)
    client.put_item(TableName=eff_table, Item=item)
    print(f"put item in {args.table} -> {state.active_branch}")


def cmd_ddb_delete(args):
    state = State.load()
    ensure_shadow_ddb(state, args.table)
    key = json.loads(args.key)
    client, eff_table = resolve_ddb(state, args.table)
    client.delete_item(TableName=eff_table, Key=key)
    print(f"deleted key from {args.table} in {state.active_branch}")


def _list_s3(client, bucket: str) -> dict[str, str]:
    out: dict[str, str] = {}
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            out[obj["Key"]] = obj["ETag"]
    return out


def _scan_ddb(client, table: str) -> dict[str, str]:
    desc = client.describe_table(TableName=table)["Table"]
    hash_key = next(k["AttributeName"] for k in desc["KeySchema"] if k["KeyType"] == "HASH")
    out: dict[str, str] = {}
    paginator = client.get_paginator("scan")
    for page in paginator.paginate(TableName=table):
        for item in page.get("Items", []):
            key_val = next(iter(item[hash_key].values()))
            out[key_val] = json.dumps(item, sort_keys=True)
    return out


def cmd_diff(args):
    state = State.load()
    br = state.active()
    print(f"diff: {br.name} vs baseline")
    any_diff = False

    for bucket in br.shadowed_s3:
        base_objs = _list_s3(baseline_client("s3"), bucket)
        sand_objs = _list_s3(
            sandbox_client("s3", br.account_id), shadow_bucket_name(br.name, bucket)
        )
        added = set(sand_objs) - set(base_objs)
        removed = set(base_objs) - set(sand_objs)
        modified = {k for k in set(sand_objs) & set(base_objs) if sand_objs[k] != base_objs[k]}
        if added or removed or modified:
            any_diff = True
            print(f"\n  s3://{bucket}")
            for k in sorted(added):
                print(f"    + {k}")
            for k in sorted(removed):
                print(f"    - {k}")
            for k in sorted(modified):
                print(f"    ~ {k}")

    for table in br.shadowed_ddb:
        base_items = _scan_ddb(baseline_client("dynamodb"), table)
        sand_items = _scan_ddb(sandbox_client("dynamodb", br.account_id), table)
        added = set(sand_items) - set(base_items)
        removed = set(base_items) - set(sand_items)
        modified = {
            k for k in set(sand_items) & set(base_items) if sand_items[k] != base_items[k]
        }
        if added or removed or modified:
            any_diff = True
            print(f"\n  ddb:{table}")
            for k in sorted(added):
                print(f"    + {k}  {sand_items[k]}")
            for k in sorted(removed):
                print(f"    - {k}  {base_items[k]}")
            for k in sorted(modified):
                print(f"    ~ {k}")
                print(f"        baseline: {base_items[k]}")
                print(f"        sandbox:  {sand_items[k]}")

    if not any_diff:
        print("  (no differences)")
