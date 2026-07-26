import os

# Set this before application modules are imported during test collection. The
# settings object is cached when the database module creates its engine.
os.environ["SKIP_DATABASE_INIT"] = "true"

# Repository-root test runs can otherwise inherit a developer's .env file.
# Empty values still exercise Settings' normalisation, so tests which provide
# one explicit GitHub value continue to verify that partial configuration fails.
for name in (
    "GITHUB_APP_ID",
    "GITHUB_APP_PRIVATE_KEY_BASE64",
    "GITHUB_APP_INSTALLATION_ID",
    "GITHUB_APP_SLUG",
    "GITHUB_WEBHOOK_SECRET",
):
    os.environ[name] = ""
