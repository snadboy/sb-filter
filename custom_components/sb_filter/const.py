"""SB Filter constants."""

DOMAIN = "sb_filter"
GRAMMAR_VERSION = 5          # bump when FILTER.md changes meaning; vectors carry it too
DEBOUNCE_SECONDS = 1.0       # coalesce bursts of changes into one recompute
SIGNAL_SUBS = "sb_filter_subscriptions_changed"
KIND_FILTER = "filter"       # entry.data["kind"] of a named filter; the engine's own entry has no kind
STATIC_URL = "/sb_filter_static"
COMMON_CLASSES = ("battery:%", "temperature", "temperature:°F", "humidity:%", "illuminance:lx", "power:W", "energy:kWh",
                  "occupancy", "motion", "door", "window", "moisture", "problem", "connectivity")
