
from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()

class Settings(BaseModel):
    app_name: str = os.getenv("APP_NAME", "AWM")
    app_env: str = os.getenv("APP_ENV", "dev")
    db_url: str = os.getenv("DB_URL", "sqlite:///./awm.db")
    schedule_cron_daily: str = os.getenv("SCHEDULE_CRON_DAILY", "0 3 * * *")
    spapi_refresh_token: str | None = os.getenv("SPAPI_REFRESH_TOKEN")
    spapi_client_id: str | None = os.getenv("SPAPI_CLIENT_ID")
    spapi_client_secret: str | None = os.getenv("SPAPI_CLIENT_SECRET")
    aws_access_key: str | None = os.getenv("AWS_ACCESS_KEY")
    aws_secret_key: str | None = os.getenv("AWS_SECRET_KEY")
    aws_role_arn: str | None = os.getenv("AWS_ROLE_ARN")
    marketplace_id: str = os.getenv("MARKETPLACE_ID", "ATVPDKIKX0DER")

settings = Settings()
