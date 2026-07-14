"""Print operational readiness blockers for every prioritized disease.

Usage (from backend/ with venv active):

    python -m scripts.operational_status
    # or
    python scripts/operational_status.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.db.session import build_engine, build_session_factory
from app.ml.readiness import build_model_portfolio_readiness


async def main() -> int:
    settings = get_settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    async with factory() as session:
        portfolio = await build_model_portfolio_readiness(session)
    print(json.dumps(portfolio, indent=2, default=str, ensure_ascii=False))
    diseases = portfolio.get("diseases") or []
    ops = sum(1 for item in diseases if item.get("operational_forecast_eligible"))
    print(f"\noperational_diseases={ops}/{len(diseases)}", file=sys.stderr)
    if ops == 0:
        print(
            "No hay enfermedades operativas. Cargue SIVIGILA reciente "
            "(≤35 días) y reentrene. Ver docs/github-deploy.md",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
