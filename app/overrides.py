from __future__ import annotations
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Override, Verdict
from app.schemas import OverrideCreate


async def create_override(data: OverrideCreate, session: AsyncSession) -> Override:
    verdict = await session.get(Verdict, data.verdict_id)
    if verdict is None:
        raise ValueError(f"Verdict {data.verdict_id} not found")

    override = Override(
        verdict_id=data.verdict_id,
        reviewer_id=data.reviewer_id,
        original_verdict=verdict.overall,
        new_verdict=data.new_verdict,
        justification=data.justification,
    )
    session.add(override)
    await session.commit()
    await session.refresh(override)
    return override


async def get_overrides(submission_id: uuid.UUID, session: AsyncSession) -> list[Override]:
    result = await session.execute(
        select(Override)
        .join(Verdict, Override.verdict_id == Verdict.id)
        .where(Verdict.submission_id == submission_id)
        .order_by(Override.created_at.asc())
    )
    return list(result.scalars().all())


async def effective_verdict(verdict: Verdict, session: AsyncSession) -> str:
    result = await session.execute(
        select(Override)
        .where(Override.verdict_id == verdict.id)
        .order_by(Override.created_at.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()
    return latest.new_verdict if latest else verdict.overall
