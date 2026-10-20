"""Constants for the Qubo Doorbell integration."""

DOMAIN = "qubo_doorbell"
CONF_DEVICE_ID = "device_id"
SIGNAL_EVENT = f"{DOMAIN}_event"
EVENT_QUBO = "qubo_event"
RING_KEYWORDS = ("bell", "ring", "press", "call", "visitor", "vdb")
RING_ON_SECONDS = 15
MAX_EVENT_LOG = 50

# Snapshot history (options)
CONF_HISTORY_ENABLED = "history_enabled"
CONF_HISTORY_FOLDER = "history_folder"
CONF_HISTORY_MAX_MB = "history_max_mb"
DEFAULT_HISTORY_ENABLED = False
DEFAULT_HISTORY_FOLDER = "qubo_doorbell"
DEFAULT_HISTORY_MAX_MB = 100
SIGNAL_HISTORY = f"{DOMAIN}_history"
# A snapshot arriving within this many seconds of a button press is labelled "ring"
RING_SNAPSHOT_WINDOW = 90
# Event parameter keys that may carry a photo link
SNAPSHOT_KEYS = ("snapshotUrl", "imageUrl", "thumbnailUrl", "snapshot_url", "image_url", "thumbUrl")

# Motion photos (grabbed from the live stream when the doorbell reports motion/person)
CONF_MOTION_SNAPSHOTS = "motion_snapshots"
CONF_MOTION_COOLDOWN = "motion_cooldown"
DEFAULT_MOTION_SNAPSHOTS = False
DEFAULT_MOTION_COOLDOWN = 60
MOTION_CAUSES = {"MOTION_DETECTED": "motion", "PERSON_DETECTED": "person"}
# Skip a motion grab if the Qubo app was streaming within this many seconds
VIEWER_GRACE = 30

# Video clips (recorded from the same live-stream session on motion/person)
CONF_VIDEO_ENABLED = "video_enabled"
CONF_VIDEO_SECONDS = "video_seconds"
CONF_VIDEO_MAX_MB = "video_max_mb"
DEFAULT_VIDEO_ENABLED = False
DEFAULT_VIDEO_SECONDS = 15
DEFAULT_VIDEO_MAX_MB = 500
