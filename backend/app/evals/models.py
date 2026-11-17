from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Result:
    case_id: str
    status: str
    layer: str | None
    checks: list[Check]
    actual: dict = field(default_factory=dict)
    trace: dict = field(default_factory=dict)

    def dict(self):
        return asdict(self)
