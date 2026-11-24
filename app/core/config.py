from functools import lru_cache
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"

    frontend_url: str | None = None
    # Comma-separated list of frontend origins. If provided, this supersedes single frontend_url.
    frontend_urls: list[str] | None = None

    mongo_url: str = "mongodb://localhost:27017"
    mongo_app_name: str = "counting_down_app"
    # Connections per process. Keep it small for serverless functions, where every concurrent
    # instance opens its own pool.
    mongo_max_pool_size: int = Field(default=100, ge=1)
    # Create indexes during web startup. Disable when scripts/ensure_indexes.py runs at deploy.
    ensure_indexes_on_startup: bool = True

    todos_collection_name: str = "todos"
    messages_collection_name: str = "messages"
    flights_collection_name: str = "flights"
    airports_collection_name: str = "airports"
    advent_collection_name: str = "advents"
    sessions_collection_name: str = "sessions"
    image_metadata_collection_name: str = "images"
    mediation_sessions_collection_name: str = "mediation_sessions"
    mediation_perspectives_collection_name: str = "mediation_perspectives"
    mediation_ai_reflections_collection_name: str = "mediation_ai_reflections"
    mediation_advices_collection_name: str = "mediation_advices"
    mediation_comments_collection_name: str = "mediation_comments"
    mediation_moderation_results_collection_name: str = "mediation_moderation_results"
    mediation_ai_jobs_collection_name: str = "mediation_ai_jobs"
    relationship_boundaries_collection_name: str = "relationship_boundaries"
    relationship_requests_collection_name: str = "relationship_requests"
    personal_goals_collection_name: str = "personal_goals"
    relationship_agreements_collection_name: str = "relationship_agreements"
    agreement_revisions_collection_name: str = "agreement_revisions"
    agreement_acceptances_collection_name: str = "agreement_acceptances"
    agreement_responses_collection_name: str = "agreement_responses"
    relationship_profile_collection_name: str = "relationship_profile"
    xiaobao_conversations_collection_name: str = "xiaobao_conversations"
    xiaobao_messages_collection_name: str = "xiaobao_messages"
    xiaobao_proposals_collection_name: str = "xiaobao_proposals"
    xiaobao_rate_limits_collection_name: str = "xiaobao_rate_limits"
    xiaobao_checkpoints_collection_name: str = "xiaobao_graph_checkpoints"
    xiaobao_checkpoint_writes_collection_name: str = "xiaobao_graph_checkpoint_writes"
    xiaobao_routines_collection_name: str = "xiaobao_routines"
    xiaobao_routine_runs_collection_name: str = "xiaobao_routine_runs"
    xiaobao_push_subscriptions_collection_name: str = "xiaobao_push_subscriptions"
    xiaobao_push_deliveries_collection_name: str = "xiaobao_push_deliveries"

    aws_s3_image_folder: str = "images/"
    aws_s3_thumbnail_folder: str = "thumbnails/"
    thumbnail_size: int = 128
    image_worker_enabled: bool = True
    image_worker_poll_seconds: float = Field(default=30.0, gt=0)
    thumbnail_xl_size: int = 1200
    # Optional explicit list of thumbnail sizes (comma-separated). If provided, supersedes
    # thumbnail_size/thumbnail_xl_size.
    thumbnail_sizes: list[int] | None = None
    # Allow custom thumbnail sizes outside the configured list, within min/max bounds.
    thumbnail_allow_custom_sizes: bool = True
    thumbnail_min_size: int = 32
    thumbnail_max_size: int = 2000
    aws_s3_presign_expires: int = 3600
    aws_s3_max_presign_expires: int = 1 * 24 * 3600  # 1 days in seconds

    access_key_danfeng: str | None = None
    access_key_joris: str | None = None
    session_duration: int = 7 * 24 * 60 * 60  # 7 days in seconds

    openai_api_key: str | None = None
    openai_model_mediation: str = "gpt-5"
    openai_model_moderation: str = "omni-moderation-latest"
    openai_model_xiaobao: str = "gpt-5.6-terra"
    xiaobao_reasoning_effort: str = "low"
    xiaobao_max_output_tokens: int = 1200
    xiaobao_history_message_limit: int = 20
    xiaobao_history_character_limit: int = 20_000
    xiaobao_mediation_session_limit: int = 10
    xiaobao_mediation_comment_limit: int = 20
    xiaobao_mediation_context_character_limit: int = 30_000
    xiaobao_mediation_private_context_character_limit: int = 15_000
    xiaobao_rate_limit_requests: int = 10
    xiaobao_rate_limit_window_seconds: int = 300
    xiaobao_checkpoint_ttl_seconds: int = 7 * 24 * 60 * 60
    xiaobao_routine_clock_poll_interval_seconds: float = 15.0
    xiaobao_routine_worker_poll_interval_seconds: float = 2.0
    xiaobao_routine_lease_seconds: float = 300.0
    xiaobao_routine_max_attempts: int = 3
    xiaobao_routine_retry_base_seconds: float = 30.0
    xiaobao_routine_retry_max_seconds: float = 900.0
    xiaobao_routine_materialize_batch_size: int = 50
    xiaobao_web_push_enabled: bool = False
    xiaobao_web_push_vapid_public_key: str | None = None
    xiaobao_web_push_vapid_private_key: str | None = None
    xiaobao_web_push_vapid_subject: str | None = None
    xiaobao_web_push_subscription_encryption_key: str | None = None
    xiaobao_web_push_worker_poll_interval_seconds: float = 2.0
    xiaobao_web_push_lease_seconds: float = 60.0
    xiaobao_web_push_max_attempts: int = 3
    xiaobao_web_push_retry_base_seconds: float = 30.0
    xiaobao_web_push_retry_max_seconds: float = 900.0
    xiaobao_web_push_ttl_seconds: int = 300
    mediation_worker_enabled: bool = False
    # Run the routine clock, routine runs and push delivery inside the web process.
    xiaobao_in_process_jobs_enabled: bool = False
    # How the web process signals the background job runner after creating work.
    job_wakeup_mode: Literal["none", "lambda"] = "none"
    job_wakeup_lambda_function_name: str | None = None
    mediation_worker_poll_interval_seconds: float = 2.0
    mediation_job_processing_timeout_seconds: float = 300.0

    aws_region: str = "eu-west-1"
    aws_s3_bucket: str = "my-app-bucket"

    aws_access_key: str | None = None
    aws_secret_key: str | None = None

    # AeroDataBox (via RapidAPI)
    aerodatabox_api_key: str | None = None
    aerodatabox_base_url: str = "https://aerodatabox.p.rapidapi.com"
    aerodatabox_api_host: str = "aerodatabox.p.rapidapi.com"
    aerodatabox_timeout_seconds: float = 10.0
    aerodatabox_lookup_window_days: int = 7
    aerodatabox_cache_ttl_success_seconds: int = 21_600  # 6 h
    aerodatabox_cache_ttl_no_results_seconds: int = 1_800  # 30 min

    default_page_size: int = 20
    max_page_size: int = 100

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        populate_by_name=True,
        case_sensitive=False,
    )

    @field_validator("frontend_urls", mode="before")
    @classmethod
    def split_frontend_urls(cls, v: str | list[str] | None) -> list[str] | None:
        """Allow FRONTEND_URLS env var to be provided as a comma-separated string.

        Example:
            FRONTEND_URLS="https://a.example.com, https://b.example.com, http://localhost:3000"
        """
        if v is None:
            return None
        if isinstance(v, str):
            parts = [p.strip() for p in v.split(",") if p.strip()]
            return parts or None
        return v

    @field_validator("thumbnail_sizes", mode="before")
    @classmethod
    def split_thumbnail_sizes(cls, v: str | list[int] | None) -> list[int] | None:
        """Allow THUMBNAIL_SIZES env var to be provided as a comma-separated string.

        Example:
            THUMBNAIL_SIZES="128, 512, 1200"
        """
        if v is None:
            return None
        if isinstance(v, str):
            parts = [p.strip() for p in v.split(",") if p.strip()]
            sizes: list[int] = []
            for part in parts:
                try:
                    sizes.append(int(part))
                except ValueError as exc:
                    raise ValueError(f"Invalid thumbnail size: {part}") from exc
            return sizes or None
        return v

    @model_validator(mode="after")
    def require_access_keys_in_production(self) -> Settings:
        if self.app_env.lower() == "prod":
            missing: list[str] = []
            if not self.access_key_danfeng:
                missing.append("ACCESS_KEY_DANFENG")
            if not self.access_key_joris:
                missing.append("ACCESS_KEY_JORIS")
            if missing:
                raise ValueError(
                    "Missing required access key env vars in production: " + ", ".join(missing)
                )
            if self.xiaobao_web_push_enabled and not self.xiaobao_web_push_ready:
                raise ValueError(
                    "XIAOBAO_WEB_PUSH_ENABLED requires VAPID and subscription encryption settings"
                )
            if self.xiaobao_web_push_enabled:
                assert self.xiaobao_web_push_subscription_encryption_key is not None
                try:
                    Fernet(self.xiaobao_web_push_subscription_encryption_key.encode("ascii"))
                except (UnicodeEncodeError, ValueError) as exc:
                    raise ValueError(
                        "XIAOBAO_WEB_PUSH_SUBSCRIPTION_ENCRYPTION_KEY must be a Fernet key"
                    ) from exc
                subject = self.xiaobao_web_push_vapid_subject
                if not subject or not subject.startswith(("mailto:", "https://")):
                    raise ValueError("XIAOBAO_WEB_PUSH_VAPID_SUBJECT must be mailto: or HTTPS")
                if self.xiaobao_web_push_ttl_seconds <= 0:
                    raise ValueError("XIAOBAO_WEB_PUSH_TTL_SECONDS must be positive")
        return self

    @model_validator(mode="after")
    def require_wakeup_target(self) -> Settings:
        if self.job_wakeup_mode == "lambda" and not self.job_wakeup_lambda_function_name:
            raise ValueError("JOB_WAKEUP_MODE=lambda requires JOB_WAKEUP_LAMBDA_FUNCTION_NAME")
        return self

    @property
    def xiaobao_web_push_ready(self) -> bool:
        return bool(
            self.xiaobao_web_push_enabled
            and self.xiaobao_web_push_vapid_public_key
            and self.xiaobao_web_push_vapid_private_key
            and self.xiaobao_web_push_vapid_subject
            and self.xiaobao_web_push_subscription_encryption_key
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
