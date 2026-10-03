"""Serializable observations; unknown values are never treated as disconnected."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class VideoMode:
    width: int
    height: int
    refresh_hz: float


@dataclass(frozen=True)
class CurrentMode:
    state: str  # listed, reported, inactive, unknown; never implies visible projection
    source: str
    reason: str
    mode: VideoMode | None = None


@dataclass(frozen=True)
class SignalProperty:
    state: str  # reported, unavailable or invalid; never a wire measurement
    meaning: str  # limit, requested, driver_status or unmeasured
    source: str
    value: int | str | bool | None = None
    note: str = ""


@dataclass(frozen=True)
class SignalTiming:
    pixel_clock_khz: int
    width: int
    height: int
    hsync_start: int
    hsync_end: int
    htotal: int
    hskew: int
    vsync_start: int
    vsync_end: int
    vtotal: int
    vscan: int
    flags: int
    nominal_refresh_hz: float


@dataclass(frozen=True)
class SignalDetails:
    state: str  # observed, unavailable, inconsistent or inactive
    source: str
    reason: str
    properties: dict[str, SignalProperty] = field(default_factory=dict)
    current_timing: SignalTiming | None = None
    current_timing_state: str = "unavailable"
    current_timing_reason: str = "Current timing could not be read."
    listed_timings: tuple[SignalTiming, ...] = ()
    listed_timings_state: str = "unavailable"
    invalid_listed_timings: int = 0


@dataclass(frozen=True)
class Connector:
    name: str
    kind: str
    status: str
    enabled: str
    modes: tuple[str, ...] | None
    current_mode: CurrentMode | None = None
    signal: SignalDetails | None = None


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
