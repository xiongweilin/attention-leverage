from datetime import datetime, timezone

from app.config import Settings
from app.models import CognitiveMap, Digest, QueryPlan, RankedItem, RawItem, RunRequest, SourceProfile, SourceQuery
from app.pipeline import AttentionPipeline
from app.store import Store


class GoodSource:
    profile = SourceProfile(name='good', category='release', description='test source', authority='primary')

    async def search(self, query, horizon_hours):
        return [
            RawItem(id='g1', source='good', source_category='release', title='Agent release',
                    url='https://example.test/1', published_at=datetime.now(timezone.utc), authority='primary'),
            RawItem(id='g2', source='good', source_category='release', title='Agent patch',
                    url='https://example.test/2', published_at=datetime.now(timezone.utc), authority='primary'),
        ]


class FailingSource:
    profile = SourceProfile(name='bad', category='news', description='offline source')

    async def search(self, query, horizon_hours):
        raise RuntimeError('offline')


class FakePlanner:
    async def plan(self, goal, horizon_hours, cognitive_context):
        assert 'underexplored_categories' in cognitive_context
        return QueryPlan(
            goal=goal, horizon_hours=horizon_hours or 24, keywords=['agent'],
            source_queries=[
                SourceQuery(source='good', query='agent', mode='verification', purpose='verify release'),
                SourceQuery(source='bad', query='agent', mode='blindspot', purpose='probe news'),
            ],
            working_assumptions=['releases are the strongest signal'],
        ), True


class FakeScreener:
    async def screen(self, plan, candidates, cognitive_context):
        assert plan.working_assumptions
        ranked = [RankedItem(
            **candidate.model_dump(), relevance=.9, novelty=1, actionability=.8,
            confidence=.9, importance=.9, model_pressure=.7, environment_distance=.4,
            reason='Useful release', disposition='attention', score=.9,
        ) for candidate in candidates]
        cognitive = CognitiveMap(next_explorations=['probe a different environment'])
        return Digest(headline='One material change'), cognitive, ranked, True


async def test_pipeline_gathers_sources_records_failures_coverage_and_persists(tmp_path, monkeypatch):
    import app.pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, 'build_sources', lambda client, settings: {
        'good': GoodSource(), 'bad': FailingSource(),
    })
    settings = Settings(
        database_path=str(tmp_path / 'pipeline.db'), source_concurrency=1,
        max_raw_items=1, max_filtered_items=10, max_output_items=1,
    )
    store = Store(settings.database_path)
    pipeline = AttentionPipeline(object(), settings, store)
    pipeline.planner = FakePlanner()
    pipeline.screener = FakeScreener()

    result = await pipeline.run(RunRequest(input='watch agent releases', horizon_hours=24))

    assert result.model_used_for_planning is True
    assert result.model_used_for_screening is True
    assert result.raw_count == 1
    assert result.filtered_count == 1
    assert len(result.items) == 1
    assert result.source_counts == {'good': 1}
    assert result.cognitive_map.next_explorations
    assert 'RuntimeError: offline' in result.source_errors['bad']
    assert store.get_run(result.run_id)['digest']['headline'] == 'One material change'
    health = {row['source']: row for row in store.health()}
    assert health['good']['successes'] == 1
    assert health['bad']['failures'] == 1
    coverage = {row['category']: row for row in store.coverage()}
    assert coverage['release']['searches'] == 1
    assert coverage['release']['results'] == 2
    assert coverage['news']['searches'] == 1
    assert coverage['news']['results'] == 0


async def test_pipeline_with_no_planned_queries_returns_empty_result(tmp_path, monkeypatch):
    import app.pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, 'build_sources', lambda client, settings: {})
    settings = Settings(database_path=str(tmp_path / 'empty.db'))
    pipeline = AttentionPipeline(object(), settings, Store(settings.database_path))

    class EmptyPlanner:
        async def plan(self, goal, horizon_hours, cognitive_context):
            return QueryPlan(goal=goal, horizon_hours=24), False

    class EmptyScreener:
        async def screen(self, plan, candidates, cognitive_context):
            return Digest(headline='No candidates'), CognitiveMap(), [], False

    pipeline.planner = EmptyPlanner()
    pipeline.screener = EmptyScreener()
    result = await pipeline.run(RunRequest(input='watch nothing'))
    assert result.raw_count == 0
    assert result.items == []
    assert result.digest.headline == 'No candidates'
    assert result.cognitive_map.model_failures == []
