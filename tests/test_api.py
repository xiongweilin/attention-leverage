import importlib
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import Settings
from app.models import Digest, QueryPlan, RankedItem, RunResult, SourceProfile


def test_http_api_routes_use_pipeline_and_store(tmp_path, monkeypatch):
    database = tmp_path / 'api.db'
    monkeypatch.setattr(Settings, 'load', classmethod(lambda cls: Settings(database_path=str(database))))
    from app import main
    main = importlib.reload(main)
    profile = SourceProfile(name='stub', category='test', description='test source')

    class FakePipeline:
        def __init__(self, client, settings, store):
            self.store = store
            self.sources = {'stub': object()}
            self.profiles = {'stub': profile}
            self.llm = SimpleNamespace(available=True)
            self.store.record_source_health('stub', True)

        async def run(self, request):
            item = RankedItem(id='item-1', source='stub', source_category='test', title='Finding',
                              url='https://example.test/finding', disposition='attention', score=.9)
            result = RunResult(
                run_id='run-1', plan=QueryPlan(goal=request.input, horizon_hours=request.horizon_hours or 72),
                digest=Digest(headline='A useful finding'), raw_count=1, filtered_count=1,
                items=[item], model_used_for_planning=True, model_used_for_screening=True,
            )
            self.store.observe_items([item])
            self.store.record_source_health('stub', True)
            self.store.record_run(result)
            return result

    monkeypatch.setattr(main, 'AttentionPipeline', FakePipeline)

    with TestClient(main.app) as client:
        index = client.get('/')
        assert index.status_code == 200
        assert '<label for="input">' in index.text
        assert '你长期没看到什么？' in index.text

        health = client.get('/api/health').json()
        assert health['ok'] is True
        assert health['llm_configured'] is True
        source_data = client.get('/api/sources').json()
        assert source_data['sources'][0]['health']['successes'] == 1
        assert client.get('/api/history?limit=0').json()['runs'] == []

        run_response = client.post('/api/run', json={'input':'watch agent releases','horizon_hours':24})
        assert run_response.status_code == 200
        assert run_response.json()['digest']['headline'] == 'A useful finding'
        assert 'cognitive_map' in run_response.json()
        assert client.get('/api/history').json()['runs'][0]['run_id'] == 'run-1'
        assert client.get('/api/history/run-1').json()['run_id'] == 'run-1'
        assert client.get('/api/history/missing').status_code == 404

        feedback = client.post('/api/feedback', json={
            'item_id':'item-1','source':'stub','useful':True,'note':'good',
        })
        assert feedback.json() == {'ok': True}

        assert client.get('/api/goals').json()['goals'] == []
        assert client.post('/api/goals', json={'name':'agent','prompt':'watch agents'}).status_code == 200
        assert client.get('/api/goals').json()['goals'][0]['name'] == 'agent'
        assert client.delete('/api/goals/agent').json() == {'ok': True}

        coverage = client.get('/api/coverage').json()
        assert 'coverage' in coverage
        cognitive = client.get('/api/cognitive-map').json()
        assert cognitive['underexplored_categories'][0]['category'] == 'test'
        assert client.get('/api/environments').json()['environments'] == []

        assert client.get('/api/assumptions').json()['assumptions'] == []
        saved = client.post('/api/assumptions', json={
            'statement':'Formal credentials are the only entry path',
            'scope':'target environment',
            'confidence':.7,
        }).json()['assumption']
        assert saved['status'] == 'active'
        assert client.get('/api/assumptions').json()['assumptions'][0]['id'] == saved['id']
        assert client.delete('/api/assumptions/'+saved['id']).json() == {'ok': True}
        assert client.get('/api/assumptions').json()['assumptions'] == []
