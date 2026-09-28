"""SB Filter constants."""

DOMAIN = "sb_filter"
GRAMMAR_VERSION = 3          # bump when FILTER.md changes meaning; vectors carry it too
DEBOUNCE_SECONDS = 1.0       # coalesce bursts of state changes into one recompute
DURATION_TICK_SECONDS = 30   # a state_for term moves on its own; re-evaluate this often
RATE_TICK_SECONDS = 60       # a rate moves as its reference sample slides even without new samples
RATE_MAX_SAMPLES = 2000      # per entity ring buffer cap
