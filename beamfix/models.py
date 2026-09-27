"""Serializable observations; unknown values are never treated as disconnected."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class VideoMode:
    width: int
    height: int
    refresh_hz: float


@dataclass(frozen=True)
class CurrentMode:
    state: str  # listed, inactive, unknown; never implies visible projection
    source: str
    reason: str
    mode: VideoMode | None = None


@dataclass(frozen=True)
class Connector:
    name: str
    kind: str
    status: str
    enabled: str
    modes: tuple[str, ...] | None
    current_mode: CurrentMode | None = None


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
