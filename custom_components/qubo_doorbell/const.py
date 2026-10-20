"""Constants for the Qubo Doorbell integration."""

DOMAIN = "qubo_doorbell"
CONF_DEVICE_ID = "device_id"
SIGNAL_EVENT = f"{DOMAIN}_event"
EVENT_QUBO = "qubo_event"
RING_KEYWORDS = ("bell", "ring", "press", "call", "visitor", "vdb")
RING_ON_SECONDS = 15
MAX_EVENT_LOG = 50
