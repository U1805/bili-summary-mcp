from typing import Any

from pydantic import BaseModel, Field


class ModelCard(BaseModel):
    id: str
    object: str = "model"
    owned_by: str = "qwen"


class ModelsResponse(BaseModel):
    object: str = "list"
    data: list[ModelCard]


class ChatMessage(BaseModel):
    role: str
    content: Any


class ChatCompletionsRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage] = Field(default_factory=list)
    temperature: float | None = None
    stream: bool = False
    max_tokens: int | None = None

