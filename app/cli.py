from __future__ import annotations

import argparse
import asyncio

import httpx

from .config import Settings
from .models import RunRequest
from .pipeline import AttentionPipeline
from .store import Store


async def _run(args) -> int:
    settings = Settings.load(); store = Store(settings.database_path)
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, follow_redirects=True,
        headers={'User-Agent':'attention-leverage/0.3 (+https://github.com/xiongweilin/attention-leverage)'}) as client:
        pipeline = AttentionPipeline(client, settings, store)
        prompts = []
        if args.saved:
            prompts = [g.prompt for g in store.list_goals() if g.enabled and (args.saved == '*' or g.name == args.saved)]
            if not prompts:
                raise SystemExit(f'No enabled saved goal matched {args.saved!r}')
        else:
            prompts = [args.goal]
        for prompt in prompts:
            result = await pipeline.run(RunRequest(input=prompt, horizon_hours=args.horizon))
            if args.json:
                print(result.model_dump_json(indent=2))
            else:
                print(f'\n# {result.digest.headline or result.plan.goal}')
                for item in result.items:
                    if item.disposition == 'background' and not args.all:
                        continue
                    print(f'- [{item.disposition}] {item.title} ({item.source})\n  {item.url}\n  {item.reason}')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Goal-driven heterogeneous information aggregation')
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
