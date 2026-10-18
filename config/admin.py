import os

# Admin login username
username = os.environ.get("ADMIN_USERNAME", "root")
# Admin login password (set in docker-compose/secret.env)
password = os.environ.get("ADMIN_PASSWORD", "")
