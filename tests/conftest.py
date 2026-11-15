import sys
from prometheus_client import REGISTRY

# Unregister default process and platform collectors to prevent duplicate registration
# when metrics.py explicitly registers custom process Gauges
for coll in list(REGISTRY._collector_to_names.keys()):
    if coll.__class__.__name__ in ("ProcessCollector", "PlatformCollector", "GCCollector"):
        try:
            REGISTRY.unregister(coll)
        except Exception:
            pass
