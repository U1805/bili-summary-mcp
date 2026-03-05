from pydantic import BaseModel, Field


class SummarizeRequest(BaseModel):
    url: str = Field(..., description="Bilibili video URL")
    prompt: str | None = Field(default=None, description="Optional custom prompt")


class SummarizeResponse(BaseModel):
    summary: str
    title: str
    duration: float | None = None
    filepath: str
    prompt: str | None = None

