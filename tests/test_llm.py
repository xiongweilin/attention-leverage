import json

import httpx

from app.config import Settings
from app.llm import OpenAICompatibleLLM


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
