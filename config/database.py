import os

# Postgres URL (hostname postgres inside compose)
url = os.environ.get(
    "DATABASE_URL",
    "postgresql://photo:photo@postgres:5432/photo",
)
