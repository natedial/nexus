import os


# Unit tests must never publish runs to a developer's configured Nexus database.
os.environ.setdefault("PIPELINE_OPS_MODE", "off")
