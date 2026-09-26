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
        headers = {}
        if self.settings.openai_api_key:
            headers['Authorization'] = f'Bearer {self.settings.openai_api_key}'
        response = await self.client.post(
            f'{self.settings.openai_base_url}/responses',
            headers=headers,
            json={
                'model': self.settings.openai_model,
                'instructions': f'{system}\n\nReturn only one valid JSON object, without markdown fences or surrounding prose.',
                'input': user,
            },
            timeout=self.settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        content = self._response_text(response)
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMUnavailable('Model did not return valid JSON') from exc

    @classmethod
    def _response_text(cls, response: httpx.Response) -> str:
        body = response.text
        is_sse = (
            'text/event-stream' in response.headers.get('content-type', '').lower()
            or any(line.startswith(('event:', 'data:')) for line in body.splitlines())
        )
        if not is_sse:
            content = cls._output_text(response.json())
            if content:
                return content
            raise LLMUnavailable('Responses API returned no text output')

        deltas: list[str] = []
        completed_text = ''
        for line in body.splitlines():
            if not line.startswith('data:'):
                continue
            data = line[5:].strip()
            if not data or data == '[DONE]':
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            if event.get('type') == 'response.output_text.delta':
                delta = event.get('delta')
                if isinstance(delta, str):
                    deltas.append(delta)
            elif event.get('type') == 'response.output_text.done' and isinstance(event.get('text'), str):
                completed_text = event['text']
            elif event.get('type') == 'response.completed':
                completed_text = cls._output_text(event.get('response', {})) or completed_text
            elif event.get('type') == 'response.failed':
                raise LLMUnavailable('Responses API stream failed')
        content = ''.join(deltas) or completed_text
        if not content:
            raise LLMUnavailable('Responses API stream returned no text output')
        return content

    @staticmethod
    def _output_text(payload: Any) -> str:
        if not isinstance(payload, dict):
            return ''
        direct = payload.get('output_text')
        if isinstance(direct, str) and direct:
            return direct
        parts: list[str] = []
        output = payload.get('output')
        if not isinstance(output, list):
            return ''
        for item in output:
            if not isinstance(item, dict) or item.get('type') != 'message':
                continue
            content = item.get('content')
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and part.get('type') in {'output_text', 'text'}:
                    text = part.get('text')
                    if isinstance(text, str):
                        parts.append(text)
        return ''.join(parts)
