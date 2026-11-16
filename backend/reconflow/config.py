from decimal import Decimal
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_mode: str = "local"
    database_url: SecretStr = SecretStr(
        "postgresql://reconflow:reconflow@localhost:55432/reconflow"
    )
    db_driver: str = "postgres"
    db_cluster_arn: str = ""
    db_secret_arn: str = ""
    db_name: str = "reconflow"
    session_secret: SecretStr = SecretStr("")
    session_secret_arn: str = ""
    openai_api_key: SecretStr = SecretStr("")
    openai_secret_arn: str = ""
    openai_model: str = "gpt-6-luna"
    ai_monthly_budget_eur: Decimal = Decimal("10")
    ai_usd_to_eur: Decimal = Decimal("1.10")
    ai_input_usd_per_million: Decimal = Decimal("0.10")
    ai_output_usd_per_million: Decimal = Decimal("0.50")
    ai_context_token_ceiling: int = 1050000
    ai_max_output_tokens: int = 4000
    aws_region: str = "eu-north-1"
    aws_endpoint_url: str | None = None
    local_document_root: str = ".local-data"
    s3_bucket: str = "reconflow-local"
    sqs_queue_url: str = "http://localhost:55000/123456789012/reconflow-jobs"
    public_origin: str = "http://localhost:5173"
    max_upload_bytes: int = 4 * 1024 * 1024
    max_documents: int = 20
    max_csv_rows: int = 10000
    max_jobs_per_session: int = 30
    max_sessions_per_hour: int = 100
    benchmarks_enabled: bool = False
    vast_api_key: SecretStr = SecretStr("")
    vast_secret_arn: str = ""
    benchmark_operator_password: SecretStr = SecretStr("")
    benchmark_operator_secret_arn: str = ""
    gpu_monthly_budget_eur: Decimal = Decimal("10")
    gpu_session_budget_eur: Decimal = Decimal("1")
    gpu_usd_to_eur: Decimal = Decimal("1.10")
    gpu_max_minutes: int = 30
    gpu_idle_seconds: int = 300
    gpu_startup_seconds: int = 600
    gpu_request_seconds: int = 120
    gpu_disk_gb: int = 30
    gpu_download_gb: Decimal = Decimal("25")
    gpu_upload_gb: Decimal = Decimal("1")
    gpu_runner_image: str = ""
    gpu_runner_artifact_key: str = ""
    gpu_runner_artifact_sha256: str = ""

    @property
    def public_demo(self) -> bool:
        return self.app_mode == "demo"


@lru_cache
def settings() -> Settings:
    config = Settings()
    secret_fields = {
        "session_secret": config.session_secret_arn,
        "openai_api_key": config.openai_secret_arn,
        "vast_api_key": config.vast_secret_arn,
        "benchmark_operator_password": config.benchmark_operator_secret_arn,
    }
    if any(secret_fields.values()):
        import boto3

        client = boto3.client("secretsmanager", region_name=config.aws_region)
        for name, arn in secret_fields.items():
            if arn:
                value = client.get_secret_value(SecretId=arn)["SecretString"]
                setattr(config, name, SecretStr(value))
    if len(config.session_secret.get_secret_value()) < 32:
        raise RuntimeError("SESSION_SECRET must contain at least 32 characters")
    return config
