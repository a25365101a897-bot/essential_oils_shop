import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    ADMIN_PASSWORD = os.environ.get("FLASK_ADMIN_PW", "changeme")
    CONTENT_DIR = os.path.join(os.path.dirname(__file__), "content")
