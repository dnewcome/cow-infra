# cow-infra

Copy-on-write infrastructure: fork a read-through AWS environment, mutate freely in a sandbox, diff vs. baseline. A prototype.

## Why

Ephemeral environments are trivial on Kubernetes — namespace + manifest + `kubectl apply`. On AWS they are a nightmare: IAM and Route53 are account-global, Terraform state is contended, RDS takes minutes, and "namespace" has to be faked with tag prefixes that leak at every seam.

`cow-infra` explores a different primitive: a sandbox that **reads through** to a baseline account by default, and **clones on first write**. Unchanged resources cost nothing; the sandbox only materializes the delta. When the work is good, the delta becomes a Terraform PR.

Think `git checkout -b`, but for cloud infrastructure.

## Status

**v0 prototype.** Runs against LocalStack. Covers S3 and DynamoDB. No HCL emission yet — see [Roadmap](#roadmap).

## Quickstart

Requires Docker and Python 3.10+.

```bash
docker compose up -d
python3 -m venv .venv && .venv/bin/pip install -e .
alias cow=$PWD/.venv/bin/cow

cow init                                    # seed baseline: 1 S3 bucket, 1 DDB table
cow branch feature-a                        # fork a sandbox
cow s3 ls s3://demo-bucket                  # reads fall through to baseline

echo '{"env":"sandbox","version":99}' > /tmp/c.json
cow s3 put s3://demo-bucket/config.json /tmp/c.json
cow ddb put demo-items --item '{"id":{"S":"3"},"name":{"S":"Gizmo"},"price":{"N":"42.00"}}'
cow s3 rm s3://demo-bucket/README.txt

cow diff
```

Sample `cow diff` output:

```
diff: feature-a vs baseline

  s3://demo-bucket
    + newfile.txt
    - README.txt
    ~ config.json

  ddb:demo-items
    + 3  {"id": {"S": "3"}, "name": {"S": "Gizmo"}, "price": {"N": "42"}}
    - 2  {"id": {"S": "2"}, "name": {"S": "Gadget"}, "price": {"N": "14.5"}}
    ~ 1
        baseline: {"id": {"S": "1"}, "name": {"S": "Widget"},     "price": {"N": "9.99"}}
        sandbox:  {"id": {"S": "1"}, "name": {"S": "Widget-PRO"}, "price": {"N": "19.99"}}
```

The baseline is untouched throughout — `cow` never writes to the baseline account.

## How it works

Each sandbox branch is assigned a distinct AWS account ID. LocalStack derives the account from a 12-digit numeric access key, so per-branch isolation comes for free for anything that scopes per-account (DDB, IAM, most services).

**Copy-on-write:**

- A read on an unmutated resource goes straight to the baseline account.
- The first write to a resource triggers a full clone into the sandbox account (for S3: bucket + every object; for DDB: table schema + every item).
- Subsequent reads and writes route to the sandbox account.
- The baseline is never mutated by sandbox operations.

```
                      reads (not shadowed)
                  ┌─────────────────────────► Baseline account (…001)
                  │                                    │
  cow CLI ────────┤                                    │ cloned from, on first write
                  │                                    ▼
                  └───► first write (clone) ──► Sandbox account (…00N)
                        subsequent reads/writes
```

**Name remapping (S3 only).** S3 bucket names are globally unique across all accounts in real AWS, and LocalStack enforces the same rule. Shadow buckets are created with a `cow-<branch>-<name>` prefix, and the prefix is hidden behind the resolver in `shadow.py`. DDB does not need this — table names scope per-account.

This asymmetry between S3 and DDB is inherent to AWS, not a LocalStack quirk. Any production implementation will have it.

## Commands

| Command | Description |
|---|---|
| `cow init` | Seed the baseline with demo resources |
| `cow branch <name>` | Create a new sandbox and set it active |
| `cow use <name>` | Switch active sandbox |
| `cow current` | Show the active branch and its shadow set |
| `cow branches` | List all branches |
| `cow s3 ls <s3-uri>` | List objects (read-through) |
| `cow s3 put <s3-uri> <file>` | Upload (triggers shadow on first touch) |
| `cow s3 rm <s3-uri>` | Delete (triggers shadow on first touch) |
| `cow ddb scan <table>` | Scan table (read-through) |
| `cow ddb put <table> --item <json>` | Put item (triggers shadow on first touch) |
| `cow ddb delete <table> --key <json>` | Delete item (triggers shadow on first touch) |
| `cow diff` | Compare active sandbox to baseline |

## Layout

```
cow-infra/
├── docker-compose.yml          # LocalStack (community, s3 + dynamodb)
├── pyproject.toml
└── src/cow/
    ├── cli.py                  # argparse dispatch
    ├── state.py                # .cow/state.json: branches, account IDs, shadow set
    ├── aws.py                  # boto3 client factory (account-scoped)
    ├── shadow.py               # clone + read-path resolver
    └── commands.py             # init / branch / s3 / ddb / diff
```

## Limitations

- **No HCL emission.** Sandboxes are a runtime concept; the round-trip back to Terraform is the next thing.
- **LocalStack only.** Community edition, two services. The account-ID isolation trick happens to work the same way on real AWS (with a multi-account org), but this hasn't been tried.
- **No shadow teardown.** `cow delete <branch>` is on the roadmap; today the shadow resources linger.
- **No access control on reads.** A sandbox can read baseline data by design. A production deployment needs an IAM boundary here.
- **External side effects are out of scope.** DNS, SaaS webhooks, real IAM policy evaluation — these need explicit routing and are probably never pure COW.

## Roadmap

1. **`cow pr`** — emit a Terraform HCL diff from the sandbox state, so changes go through code review as the actual mutation path. This is the piece that closes the loop on the whole idea.
2. **`cow delete <branch>`** — tear down shadow resources cleanly.
3. **Terraform-defined baseline** (replacing imperative `cow init`) so the HCL round-trip is real end-to-end.
4. **Interception proxy** so plain `aws` CLI and `boto3` can target the shim without going through `cow` subcommands.
5. **More services**: IAM, Lambda, SQS. Each service is roughly one clone helper and one resolver entry.
6. **Real AWS backend**: swap LocalStack for a multi-account org (one AWS account per sandbox), keep the same resolver logic.

## License

TBD.
