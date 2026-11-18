from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "GBA Construction Multi-Agent Simulation"
    api_prefix: str = ""


settings = Settings()
