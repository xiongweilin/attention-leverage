import json

import httpx
import pytest

from app.config import Settings
from app.llm import LLMUnavailable, OpenAICompatibleLLM


async def test_responses_stream_is_parsed_as_json():
    events = [
        {'type': 'response.output_text.delta', 'delta': '{"goal":'},
        {'type': 'response.output_text.delta', 'delta': '"test"}'},
        {'type': 'response.completed', 'response': {'status': 'completed'}},
    ]
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured['url'] = str(request.url)
        captured['authorization'] = request.headers.get('authorization')
        captured['payload'] = json.loads(request.content)
        body = ''.join(f'data: {json.dumps(event)}\n\n' for event in events)
        return httpx.Response(200, headers={'content-type': 'application/octet-stream'}, text=body)

    settings = Settings(
        openai_api_key='local-gateway',
        openai_base_url='http://127.0.0.1:4101/v1',
        openai_model='gpt-6-luna',
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await OpenAICompatibleLLM(client, settings).json('system prompt', 'user prompt')

    assert result == {'goal': 'test'}
    assert captured['url'] == 'http://127.0.0.1:4101/v1/responses'
    assert captured['authorization'] == 'Bearer local-gateway'
    assert captured['payload']['model'] == 'gpt-6-luna'
    assert captured['payload']['instructions'].startswith('system prompt')
    assert captured['payload']['input'] == 'user prompt'


async def test_non_streaming_responses_and_invalid_json():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'output_text':'{"answer":42}'})

    settings = Settings(openai_api_key='token', openai_model='model')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await OpenAICompatibleLLM(client, settings).json('s', 'u') == {'answer':42}

    async def invalid_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'output_text':'not-json'})

    async with httpx.AsyncClient(transport=httpx.MockTransport(invalid_handler)) as client:
        with pytest.raises(LLMUnavailable, match='valid JSON'):
            await OpenAICompatibleLLM(client, settings).json('s', 'u')


async def test_unconfigured_and_empty_json_responses_fail_cleanly():
    settings = Settings(openai_api_key='', openai_model='')
    async with httpx.AsyncClient() as client:
        with pytest.raises(LLMUnavailable, match='not configured'):
            await OpenAICompatibleLLM(client, settings).json('s', 'u')

    async def empty_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'output':[]})

    settings = Settings(openai_api_key='token', openai_model='model')
    async with httpx.AsyncClient(transport=httpx.MockTransport(empty_handler)) as client:
        with pytest.raises(LLMUnavailable, match='no text output'):
            await OpenAICompatibleLLM(client, settings).json('s', 'u')


def test_output_extractor_handles_message_parts_and_invalid_shapes():
    extract = OpenAICompatibleLLM._output_text
    payload = {'output':[
        None,
        {'type':'reasoning','content':[{'type':'text','text':'ignore'}]},
        {'type':'message','content':'not a list'},
        {'type':'message','content':[
            {'type':'refusal','text':'ignore'}, {'type':'output_text','text':'one'},
            {'type':'text','text':' two'}, {'type':'text','text':7},
        ]},
    ]}
    assert extract(payload) == 'one two'
    assert extract({'output_text':''}) == ''
    assert extract({'output':None}) == ''
    assert extract([]) == ''


def test_sse_fallback_events_errors_and_malformed_lines():
    cls = OpenAICompatibleLLM
    done_only = '\n'.join([
        'event: response.output_text.done',
        'data: not-json',
        'data: {"type":"response.output_text.done","text":"{\\"ok\\":true}"}',
        'data: [DONE]',
    ])
    assert cls._response_text(httpx.Response(200, text=done_only)) == '{"ok":true}'

    completed = 'data: {"type":"response.completed","response":{"output_text":"done"}}\n'
    assert cls._response_text(httpx.Response(200, text=completed)) == 'done'

    failed = 'data: {"type":"response.failed"}\n'
    with pytest.raises(LLMUnavailable, match='stream failed'):
        cls._response_text(httpx.Response(200, text=failed))
    with pytest.raises(LLMUnavailable, match='no text output'):
        cls._response_text(httpx.Response(200, text='data: [DONE]\n'))
