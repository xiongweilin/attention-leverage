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
        if not cls._is_sse(response, body):
            return cls._json_response_text(response)
        return cls._stream_response_text(body)

    @staticmethod
    def _is_sse(response: httpx.Response, body: str) -> bool:
        content_type = response.headers.get('content-type', '').lower()
        return 'text/event-stream' in content_type or any(
            line.startswith(('event:', 'data:')) for line in body.splitlines()
        )

    @classmethod
    def _json_response_text(cls, response: httpx.Response) -> str:
        content = cls._output_text(response.json())
        if content:
            return content
        raise LLMUnavailable('Responses API returned no text output')

    @classmethod
    def _stream_response_text(cls, body: str) -> str:
        events = list(cls._stream_events(body))
        if any(event.get('type') == 'response.failed' for event in events):
            raise LLMUnavailable('Responses API stream failed')
        deltas = [event['delta'] for event in events if cls._is_text_delta(event)]
        if deltas:
            return ''.join(deltas)
        for event in reversed(events):
            content = cls._completed_text(event)
            if content:
                return content
        raise LLMUnavailable('Responses API stream returned no text output')

    @staticmethod
    def _stream_events(body: str):
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
            if isinstance(event, dict):
                yield event

    @staticmethod
    def _is_text_delta(event: dict[str, Any]) -> bool:
        return event.get('type') == 'response.output_text.delta' and isinstance(event.get('delta'), str)

    @classmethod
    def _completed_text(cls, event: dict[str, Any]) -> str:
        if event.get('type') == 'response.output_text.done':
            text = event.get('text')
            return text if isinstance(text, str) else ''
        if event.get('type') == 'response.completed':
            return cls._output_text(event.get('response', {}))
        return ''

    @staticmethod
    def _output_text(payload: Any) -> str:
        if not isinstance(payload, dict):
            return ''
        direct = payload.get('output_text')
        if isinstance(direct, str) and direct:
            return direct
        output = payload.get('output')
        if not isinstance(output, list):
            return ''
        return ''.join(OpenAICompatibleLLM._message_text(item) for item in output)

    @staticmethod
    def _message_text(item: Any) -> str:
        if not isinstance(item, dict) or item.get('type') != 'message':
            return ''
        content = item.get('content')
        if not isinstance(content, list):
            return ''
        return ''.join(
            part['text'] for part in content
            if isinstance(part, dict)
            and part.get('type') in {'output_text', 'text'}
            and isinstance(part.get('text'), str)
        )
