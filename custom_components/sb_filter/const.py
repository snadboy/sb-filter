"""SB Filter constants."""

DOMAIN = "sb_filter"
GRAMMAR_VERSION = 5          # bump when FILTER.md changes meaning; vectors carry it too
DEBOUNCE_SECONDS = 1.0       # coalesce bursts of changes into one recompute
SIGNAL_SUBS = "sb_filter_subscriptions_changed"
