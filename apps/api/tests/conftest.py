import os

# Set this before application modules are imported during test collection. The
# settings object is cached when the database module creates its engine.
os.environ["SKIP_DATABASE_INIT"] = "true"
