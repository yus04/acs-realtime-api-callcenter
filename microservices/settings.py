from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    ACS_CONNECTION_STRING: str = "your_connection_string"
    DISTRIBUTION_POLICY_ID: str = "default_dist_policy_id"
    DISTRIBUTION_POLICY_NAME: str = "default_dist_policy_name"
    QUEUE_ID: str = "default_queue_id"
    QUEUE_NAME: str = "default_queue_name"
    WORKER_ID: str = "default_worker_id"
    WORKER_CAPACITY: int = 10
    WORKER_LABELS: dict = {"Role": "default_role"}
    CHANNEL_ID: str = "voice"
    CAPACITY_COST_PER_JOB: int = 1
    CALLBACK_BASEURL: str = "https://example.com/callback"
    AZURE_OPENAI_SERVICE_ENDPOINT: str ="https://your_aoai_endpoint"
    AZURE_OPENAI_DEPLOYMENT_NAME: str ="your_aoai_deployment_name"
    AZURE_OPENAI_SERVICE_KEY: str ="your_aoai_service_key"
    OPERATOR_PHONE_NUMBER: str = "+1234567890"
    OPERATOR_CALLBACK_BASEURL: str = "https://example.com/operator_callback"

    class Config:
        env_file = ".env"

settings = Settings()
