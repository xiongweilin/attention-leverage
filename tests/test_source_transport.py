import httpx
import pytest

from app.sources.transport import SourceTransport, SourceTransportPolicy, classify_source_error


@pytest.mark.asyncio
async def test_retries_transient_http_failure_but_not_client_error():
    attempts = 0

    async def retry_handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, headers={'Retry-After': '0'}, request=request)
        return httpx.Response(200, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(retry_handler)) as client:
        transport = SourceTransport(
            'retry-test', client,
            policy=SourceTransportPolicy(max_attempts=2, backoff_seconds=0),
        )
        response = await transport.get('https://source.test/items')
    assert response.status_code == 200
    assert attempts == 2

    attempts = 0

    async def client_error_handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(client_error_handler)) as client:
        transport = SourceTransport(
            'client-error-test', client,
            policy=SourceTransportPolicy(max_attempts=3, backoff_seconds=0),
        )
        response = await transport.get('https://source.test/missing')
    assert response.status_code == 404
    assert attempts == 1


@pytest.mark.asyncio
async def test_system_then_direct_uses_direct_only_after_transport_error():
    system_attempts = 0
    direct_attempts = 0

    async def system_handler(request):
        nonlocal system_attempts
        system_attempts += 1
        raise httpx.ConnectTimeout('system route timed out')

    async def direct_handler(request):
        nonlocal direct_attempts
        direct_attempts += 1
        return httpx.Response(200, request=request)

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(system_handler)) as system_client,
        httpx.AsyncClient(transport=httpx.MockTransport(direct_handler)) as direct_client,
    ):
        transport = SourceTransport(
            'route-test', system_client, direct_client,
            SourceTransportPolicy(mode='system_then_direct', max_attempts=2, backoff_seconds=0),
        )
        response = await transport.get('https://source.test/items')
    assert response.status_code == 200
    assert system_attempts == 2
    assert direct_attempts == 1


def test_source_error_classification_exposes_status_without_request_url():
    request = httpx.Request('GET', 'https://source.test/items?query=private-term')
    response = httpx.Response(403, request=request)
    error = httpx.HTTPStatusError('forbidden', request=request, response=response)

    assert classify_source_error(error) == ('http_error', 403, 'HTTP 403')


def test_source_policy_rejects_unknown_route():
    with pytest.raises(ValueError, match='unsupported source transport mode'):
        SourceTransportPolicy.from_config({'mode': 'automatic'})
