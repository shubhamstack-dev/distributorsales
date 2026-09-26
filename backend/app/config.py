"""Settings, all from the environment so nothing secret lives in the code."""
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL", "mysql+pymysql://root:root@localhost:3306/distributor_sales")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]

# One shared password guards the API. Small tool, few people; the point is that
# the API is not open, not that it has its own directory of users.
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
SECRET_KEY = os.getenv("SECRET_KEY") or ""
if not SECRET_KEY:
    SECRET_KEY = os.urandom(32).hex()
    print("[startup] WARNING: SECRET_KEY is not set, so a temporary one is in use and every "
          "restart will sign everyone out. Set SECRET_KEY in the environment.", flush=True)
TOKEN_HOURS = int(os.getenv("TOKEN_HOURS", "12"))

STAGING_DIR = os.getenv("STAGING_DIR", os.path.join(os.getcwd(), "data", "staging"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "60"))
STAGING_HOURS = int(os.getenv("STAGING_HOURS", "6"))
