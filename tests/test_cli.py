import asyncio
from argparse import Namespace
import sys

import pytest

import app.cli as cli
from app.config import Settings
from app.models import Digest, QueryPlan, RankedItem, RunResult, SavedGoal
from app.store import Store


def _result(prompt: str) -> RunResult:
    return RunResult(
        run_id='cli-run', plan=QueryPlan(goal=prompt), digest=Digest(headline='CLI headline'),
        raw_count=2, filtered_count=2,
        items=[
            RankedItem(id='a', source='one', title='Attention item', url='https://a',
                       disposition='attention', score=.9),
            RankedItem(id='b', source='two', title='Background item', url='https://b',
                       disposition='background', score=.1),
        ],
        model_used_for_planning=False, model_used_for_screening=False,
    )


class FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def _prepare_cli(monkeypatch, tmp_path, prompts):
    settings = Settings(database_path=str(tmp_path / 'cli.db'))
    monkeypatch.setattr(cli.Settings, 'load', classmethod(lambda cls: settings))
    monkeypatch.setattr(cli.httpx, 'AsyncClient', FakeClient)
    store = Store(settings.database_path)
    for name, prompt, enabled in prompts:
        store.save_goal(SavedGoal(name=name, prompt=prompt, enabled=enabled))
    observed = []

    class FakePipeline:
        def __init__(self, client, pipeline_settings, pipeline_store):
            pass

        async def run(self, request):
            observed.append(request.input)
            return _result(request.input)

    monkeypatch.setattr(cli, 'AttentionPipeline', FakePipeline)
    return observed


def test_cli_runs_enabled_saved_goals_and_filters_background_output(tmp_path, monkeypatch, capsys):
    observed = _prepare_cli(monkeypatch, tmp_path, [
        ('enabled', 'watch agents', True), ('disabled', 'ignore this', False),
    ])
    args = Namespace(saved='*', goal='', horizon=48, json=False, all=False)

    assert asyncio.run(cli._run(args)) == 0
    output = capsys.readouterr().out
    assert observed == ['watch agents']
    assert 'Attention item' in output
    assert 'Background item' not in output


def test_cli_json_and_all_modes_and_missing_saved_goal(tmp_path, monkeypatch, capsys):
    _prepare_cli(monkeypatch, tmp_path, [('saved', 'watch agents', True)])
    args = Namespace(saved=None, goal='direct query', horizon=None, json=True, all=True)
    assert asyncio.run(cli._run(args)) == 0
    assert '"digest"' in capsys.readouterr().out

    missing = Namespace(saved='not-found', goal='', horizon=None, json=False, all=False)
    with pytest.raises(SystemExit, match='No enabled saved goal'):
        asyncio.run(cli._run(missing))


def test_cli_main_validates_arguments_and_dispatches(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['attention-leverage'])
    with pytest.raises(SystemExit):
        cli.main()

    async def fake_run(args):
        assert args.goal == 'a goal'
        assert args.horizon == 36
        return 7

    monkeypatch.setattr(cli, '_run', fake_run)
    monkeypatch.setattr(sys, 'argv', ['attention-leverage', 'a goal', '--horizon', '36', '--json', '--all'])
    assert cli.main() == 7
