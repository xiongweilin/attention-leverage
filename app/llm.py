from __future__ import annotations

import json
from typing import Any

import httpx

from .config import Settings


class LLMUnavailable(RuntimeError):
    pass


class OpenAICompatibleLLM:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.client = client
        self.settings = settings

    @property
    def available(self) -> bool:
        return bool(self.settings.openai_api_key and self.settings.openai_model)

    async def json(self, system: str, user: str) -> dict[str, Any]:
        if not self.available:
            raise LLMUnavailable('OPENAI_API_KEY is not configured')
        response = await self.client.post(
            f'{self.settings.openai_base_url}/chat/completions',
            headers={'Authorization': f'Bearer {self.settings.openai_api_key}'},
            json={
                'model': self.settings.openai_model,
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': user},
                ],
                'temperature': 0.1,
                'response_format': {'type': 'json_object'},
            },
        )
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content']
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMUnavailable('Model did not return valid JSON') from exc
