from __future__ import annotations

import argparse
import sys

from . import commands


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cow", description="Copy-on-write infrastructure sandbox")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="Seed the baseline with demo resources")

    pb = sub.add_parser("branch", help="Create a new sandbox branch")
    pb.add_argument("name")

    pu = sub.add_parser("use", help="Switch active sandbox branch")
    pu.add_argument("name")

    sub.add_parser("current", help="Show the active branch")
    sub.add_parser("branches", help="List all branches")
    sub.add_parser("diff", help="Diff the active branch against baseline")

    ps3 = sub.add_parser("s3", help="S3 operations")
    s3sub = ps3.add_subparsers(dest="s3cmd", required=True)

    s3_ls = s3sub.add_parser("ls")
    s3_ls.add_argument("uri")

    s3_put = s3sub.add_parser("put")
    s3_put.add_argument("uri")
    s3_put.add_argument("file", help="local file, or '-' for stdin")

    s3_rm = s3sub.add_parser("rm")
    s3_rm.add_argument("uri")

    pd = sub.add_parser("ddb", help="DynamoDB operations")
    ddbsub = pd.add_subparsers(dest="ddbcmd", required=True)

    ddb_scan = ddbsub.add_parser("scan")
    ddb_scan.add_argument("table")

    ddb_put = ddbsub.add_parser("put")
    ddb_put.add_argument("table")
    ddb_put.add_argument("--item", required=True, help="JSON item with DDB type wrappers")

    ddb_del = ddbsub.add_parser("delete")
    ddb_del.add_argument("table")
    ddb_del.add_argument("--key", required=True, help="JSON key with DDB type wrappers")

    return p


DISPATCH = {
    ("init",): commands.cmd_init,
    ("branch",): commands.cmd_branch,
    ("use",): commands.cmd_use,
    ("current",): commands.cmd_current,
    ("branches",): commands.cmd_branches,
    ("diff",): commands.cmd_diff,
    ("s3", "ls"): commands.cmd_s3_ls,
    ("s3", "put"): commands.cmd_s3_put,
    ("s3", "rm"): commands.cmd_s3_rm,
    ("ddb", "scan"): commands.cmd_ddb_scan,
    ("ddb", "put"): commands.cmd_ddb_put,
    ("ddb", "delete"): commands.cmd_ddb_delete,
}


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd in ("s3", "ddb"):
        key = (args.cmd, getattr(args, f"{args.cmd}cmd"))
    else:
        key = (args.cmd,)
    DISPATCH[key](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
