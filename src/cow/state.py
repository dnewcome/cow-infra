from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

STATE_DIR = Path(".cow")
STATE_FILE = STATE_DIR / "state.json"

LOCALSTACK_ENDPOINT = "http://localhost:4566"
REGION = "us-east-1"
BASELINE_ACCOUNT_ID = "000000000001"


@dataclass
class Branch:
    name: str
    account_id: str
    shadowed_s3: list[str] = field(default_factory=list)
    shadowed_ddb: list[str] = field(default_factory=list)


@dataclass
class State:
    active_branch: str | None = None
    branches: dict[str, Branch] = field(default_factory=dict)
    next_account_suffix: int = 2

    @classmethod
    def load(cls) -> "State":
        if not STATE_FILE.exists():
            return cls()
        data = json.loads(STATE_FILE.read_text())
        branches = {name: Branch(**b) for name, b in data.get("branches", {}).items()}
        return cls(
            active_branch=data.get("active_branch"),
            branches=branches,
            next_account_suffix=data.get("next_account_suffix", 2),
        )

    def save(self) -> None:
        STATE_DIR.mkdir(exist_ok=True)
        data = {
            "active_branch": self.active_branch,
            "branches": {name: asdict(b) for name, b in self.branches.items()},
            "next_account_suffix": self.next_account_suffix,
        }
        STATE_FILE.write_text(json.dumps(data, indent=2))

    def active(self) -> Branch:
        if not self.active_branch:
            raise SystemExit("No active branch. Run `cow branch <name>`.")
        return self.branches[self.active_branch]

    def new_account_id(self) -> str:
        suffix = self.next_account_suffix
        self.next_account_suffix += 1
        return f"{suffix:012d}"
