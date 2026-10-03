"""Shared limits, ordering and geometry for desktop-specific mode planners."""

MAX_MODE_TRIALS = 5


def mode_rank(width, height, hz, identifier):
    # Trial order only: listed modes are not evidence of projector compatibility.
    return abs(hz - 60), width > 1920 or height > 1080, -width * height, identifier


def overlaps(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]
