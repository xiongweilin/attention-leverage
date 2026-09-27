from __future__ import annotations

import argparse
import asyncio

import httpx

from .config import Settings
from .models import RunRequest
from .pipeline import AttentionPipeline
from .store import Store


async def _run(args) -> int:
    settings = Settings.load()
    store = Store(settings.database_path)
    prompts = _prompts(args, store)
    async with httpx.AsyncClient(
        timeout=settings.request_timeout_seconds,
        follow_redirects=True,
        headers={'User-Agent':'attention-leverage/0.4 (+https://github.com/xiongweilin/attention-leverage)'},
    ) as client, httpx.AsyncClient(
        timeout=settings.request_timeout_seconds,
        follow_redirects=True,
        headers={'User-Agent':'attention-leverage/0.4 (+https://github.com/xiongweilin/attention-leverage)'},
        trust_env=False,
    ) as direct_client:
        pipeline = AttentionPipeline(client, settings, store, direct_client=direct_client)
        for prompt in prompts:
            result = await pipeline.run(RunRequest(input=prompt, horizon_hours=args.horizon))
            _print_result(result, args)
    return 0


def _prompts(args, store: Store) -> list[str]:
    if not args.saved:
        return [args.goal]
    prompts = [
        goal.prompt for goal in store.list_goals()
        if goal.enabled and (args.saved == '*' or goal.name == args.saved)
    ]
    if not prompts:
        raise SystemExit(f'No enabled saved goal matched {args.saved!r}')
    return prompts


def _print_result(result, args) -> None:
    if args.json:
        print(result.model_dump_json(indent=2))
        return

    print(f'\n# {result.digest.headline or result.plan.goal}')
    cognitive = result.cognitive_map
    if cognitive.long_unseen:
        print('\n## Long-unseen')
        for x in cognitive.long_unseen[:5]:
            print(f'- {x.area}: {x.why_unseen}')
    if cognitive.distant_environments:
        print('\n## Distant environments')
        for x in cognitive.distant_environments[:5]:
            print(f'- {x.name} (distance {x.distance:.2f}): {x.why_distant}')
    if cognitive.reinterpretations:
        print('\n## Reinterpretation triggers')
        for x in cognitive.reinterpretations[:5]:
            print(f'- {x.trigger}: {x.old_frame} -> {x.new_frame}')
    if cognitive.model_failures:
        print('\n## Model challenges')
        for x in cognitive.model_failures[:5]:
            print(f'- [{x.strength}] {x.assumption}: {x.signal}')

    print('\n## Attention')
    for item in result.items:
        if item.disposition == 'background' and not args.all:
            continue
        print(f'- [{item.disposition}] {item.title} ({item.source})\n  {item.url}\n  {item.reason}')


def main() -> int:
    parser = argparse.ArgumentParser(description='Goal-driven heterogeneous information aggregation with cognitive calibration')
    parser.add_argument('goal', nargs='?', default='')
    parser.add_argument('--saved', help='Run one saved goal by name, or * for all enabled goals')
    parser.add_argument('--horizon', type=int)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--all', action='store_true', help='Include background items in text output')
    args = parser.parse_args()
    if not args.saved and not args.goal:
        parser.error('provide a goal or --saved')
    return asyncio.run(_run(args))


if __name__ == '__main__':
    raise SystemExit(main())
