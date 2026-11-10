"""一次性校准：把历史项目的健康度按看板同一套规则回写，并打印分布。"""

from __future__ import annotations

import asyncio
from collections import Counter

from sqlalchemy import select

from pms.core.database import get_session_factory
from pms.project.models import PrjProject
from pms.report import service as report_service


async def main() -> None:
    factory = get_session_factory()
    async with factory() as session:
        ids = (
            await session.execute(select(PrjProject.id).where(PrjProject.deleted == 0))
        ).scalars().all()
        counter: Counter[str] = Counter()
        samples: list[str] = []
        for project_id in ids:
            health = await report_service.refresh_project_health(session, project_id)
            counter[health] += 1
            if health != "GREEN" and len(samples) < 5:
                metric = await report_service.project_metric(
                    session, await report_service.project_service.get_project(session, project_id)
                )
                samples.append(
                    f"{metric.project_name} {health} spi={metric.spi} delay={metric.delay_days} "
                    f"fill={metric.log_fill_rate} risk={metric.risk_open} issue={metric.issue_open}"
                )
        await session.commit()
        print("项目数", len(ids), dict(counter))
        for line in samples:
            print(" -", line)


asyncio.run(main())
