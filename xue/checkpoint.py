import json
from dataclasses import asdict, dataclass, field


@dataclass
class Checkpoint:
    seed_url: str
    visited: list[str] = field(default_factory=list)
    queue: list[tuple[str, int]] = field(default_factory=list)
    discovered_domains: list[str] = field(default_factory=list)
    total_discovered: int = 0
    timestamp: str = ""

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls, path: str) -> "Checkpoint":
        with open(path) as f:
            data = json.load(f)
        return cls(**data)
