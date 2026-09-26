from app.models import SourceProfile
from app.planner import GoalPlanner


class NoLLM:
    available=False


async def test_fallback_plan_uses_category_balanced_sources():
    profiles={
        'a':SourceProfile(name='a',category='news',description='a'),
        'b':SourceProfile(name='b',category='news',description='b'),
        'c':SourceProfile(name='c',category='research',description='c'),
    }
    plan,used=await GoalPlanner(NoLLM(),profiles).plan('跟踪 agent runtime 变化',48)
    assert not used
    assert plan.horizon_hours==48
    assert {q.source for q in plan.source_queries}=={'a','c'}


async def test_fallback_prioritizes_underexplored_categories():
    profiles={
        'news':SourceProfile(name='news',category='news',description='n'),
        'people':SourceProfile(name='people',category='people_network',description='p'),
        'grants':SourceProfile(name='grants',category='grants_opportunities',description='g'),
    }
    context={'underexplored_categories':[
        {'category':'grants_opportunities','searches':0,'items':0},
        {'category':'people_network','searches':0,'items':0},
    ]}
    plan,used=await GoalPlanner(NoLLM(),profiles).plan('find entry paths',72,context)
    assert not used
    assert [q.source for q in plan.source_queries[:2]] == ['grants','people']
    assert all(q.mode == 'blindspot' for q in plan.source_queries[:2])
    assert plan.exploration_questions


async def test_model_plan_filters_unknown_sources_overrides_horizon_and_receives_context():
    class ModelLLM:
        available=True

        async def json(self, system, user):
            assert 'Available sources:' in system
            assert 'four calibration questions' in system
            assert '"assumptions"' in system
            assert user == 'watch agent releases'
            return {
                'goal':'agent releases','horizon_hours':120,'keywords':['agent'],
                'source_queries':[
                    {'source':'a','query':'agent','mode':'counterevidence'},
                    {'source':'missing','query':'agent'},
                ],
                'working_assumptions':['release cadence remains stable'],
                'exploration_questions':['what would falsify the cadence model?'],
            }

    profiles={'a':SourceProfile(name='a',category='news',description='A')}
    context={'assumptions':[{'id':'x','statement':'release cadence remains stable'}]}
    plan, used = await GoalPlanner(ModelLLM(), profiles).plan('watch agent releases', 24, context)
    assert used is True
    assert plan.horizon_hours == 24
    assert [query.source for query in plan.source_queries] == ['a']
    assert plan.source_queries[0].mode == 'counterevidence'
    assert plan.working_assumptions


async def test_model_plan_without_valid_routes_falls_back_and_model_errors_fall_back():
    class EmptyRoutesLLM:
        available=True

        async def json(self, system, user):
            return {'goal':user,'source_queries':[{'source':'unknown','query':'x'}]}

    profiles={
        'news-a':SourceProfile(name='news-a',category='news',description='A'),
        'news-b':SourceProfile(name='news-b',category='news',description='B'),
        'research':SourceProfile(name='research',category='research',description='R'),
    }
    plan, used = await GoalPlanner(EmptyRoutesLLM(), profiles).plan('  agent   release  ', 36)
    assert used is True
    assert [route.source for route in plan.source_queries] == ['news-a','research']
    assert all(route.query == 'agent release' for route in plan.source_queries)

    class BrokenLLM:
        available=True

        async def json(self, system, user):
            raise RuntimeError('offline')

    fallback, used = await GoalPlanner(BrokenLLM(), profiles).plan('Agent agent API #release', None)
    assert used is False
    assert fallback.horizon_hours == 72
    assert fallback.keywords == ['agent','api','#release']
    assert fallback.uncertainties
