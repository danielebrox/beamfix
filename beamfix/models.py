"""Serializable observations; unknown values are never treated as disconnected."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Connector:
    name: str
    kind: str
    status: str
    enabled: str
    modes: tuple[str, ...] | None


@dataclass(frozen=True)
class GPU:
    card: str
    driver: str | None


@dataclass
class Snapshot:
    system: str
    kernel: str
    session: str
    desktop: str
    gpus: list[GPU] = field(default_factory=list)
    connectors: list[Connector] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    message: str
    suggestion: str
    connector: str | None = None
