import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    ADMIN_PASSWORD = os.environ.get("FLASK_ADMIN_PW", "changeme")
    CONTENT_DIR = os.path.join(os.path.dirname(__file__), "content")


    SQLALCHEMY_DATABASE_URI = "postgresql://essential_oils_db_6jad_user:UZrgmO6QMD8Wnud8kTpNyOSVeCgG0ZvG@dpg-d4bl0v7diees73alaa10-a.oregon-postgres.render.com/essential_oils_db_6jad"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "DATABASE_URL"
