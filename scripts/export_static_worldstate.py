"""
Export the VH-WSM world-state as static JSON so the product works with no
always-on compute (GitHub Pages / object storage / CDN).

Usage:
    python scripts/export_static_worldstate.py --out public/api
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from api.models.database import SessionLocal, Base, engine
from core.worldstate import registry as R
from core.worldstate import service


def _write(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join("public", "api"))
    args = ap.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        n = 0
        for code in R.UNIVERSE:
            st = service.build_state(db, code)
            if st is None:
                continue
            _write(os.path.join(args.out, "latest", f"{code}.json"), st)
            n += 1

        # world-level aggregates (reuse router logic via direct queries)
        from api.routers.worldstate import world_graph, world_clusters, leaderboard, model_card
        import asyncio

        _write(os.path.join(args.out, "world", "graph.json"),
               asyncio.run(world_graph(db)))
        _write(os.path.join(args.out, "world", "clusters.json"),
               asyncio.run(world_clusters(db)))
        _write(os.path.join(args.out, "model", "leaderboard.json"),
               asyncio.run(leaderboard(db)))
        _write(os.path.join(args.out, "model", "card.json"),
               asyncio.run(model_card()))

        index = {
            "model_version": R.MODEL_VERSION,
            "countries": R.UNIVERSE,
            "endpoints": {
                "country": "latest/{CODE}.json",
                "graph": "world/graph.json",
                "clusters": "world/clusters.json",
                "leaderboard": "model/leaderboard.json",
                "card": "model/card.json",
            },
        }
        _write(os.path.join(args.out, "index.json"), index)
        print(f"Exported {n} country states + world/model JSON → {args.out}/")
    finally:
        db.close()


if __name__ == "__main__":
    main()
