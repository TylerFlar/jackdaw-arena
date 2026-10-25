"""``arena``: run the service's tasks from a shell (development, or by hand in production).

arena migrate
arena janitor
arena house --agent smart --episodes 500
arena serve --port 8000
"""

from __future__ import annotations

import argparse
import json


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="arena", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply database migrations")
    sub.add_parser("janitor", help="end idle episodes")
    house = sub.add_parser("house", help="play episodes with a house baseline")
    house.add_argument("--agent", choices=("random", "smart"), default="random")
    house.add_argument("--episodes", type=int, default=100)
    house.add_argument("--track", default="red-1")
    house.add_argument("--seed", type=int, default=0)
    oa = sub.add_parser("openapi", help="print the OpenAPI document (no database needed)")
    oa.add_argument("-o", "--out", help="write it to this file (LF line endings) instead")
    serve = sub.add_parser("serve", help="run the API with uvicorn")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn

        uvicorn.run(
            "arena.main:create_app", factory=True, host=args.host, port=args.port,
            reload=args.reload, access_log=False,
        )  # fmt: skip
        return

    if args.command == "openapi":
        from sqlalchemy import create_engine

        from arena.main import create_app
        from arena.settings import Settings

        # Engines connect lazily: describing the API never touches a database.
        app = create_app(Settings(env="dev"), engine=create_engine("postgresql+psycopg://"))
        doc = json.dumps(app.openapi(), indent=1, sort_keys=True) + "\n"
        if args.out:
            with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(doc)
        else:
            print(doc, end="")
        return

    from arena.db.engine import make_engine
    from arena.db.migrate import migrate
    from arena.settings import load_settings

    settings = load_settings()
    engine = make_engine(settings)
    if args.command == "migrate":
        print(json.dumps({"applied": migrate(engine, dsql=settings.db == "dsql")}))
        return

    from arena.clock import utcnow
    from arena.services.episodes import EpisodeService
    from arena.services.seeds import secure_seeds

    service = EpisodeService(engine, utcnow, secure_seeds, cache_size=settings.cache_size)
    if args.command == "janitor":
        print(json.dumps({"ended": service.janitor(settings.idle_timeout_s)}))
    elif args.command == "house":
        from arena.house import run_house

        summary = run_house(service, args.agent, args.episodes, args.track, seed=args.seed)
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
