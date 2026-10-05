from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Candidate, Hall, SeatJournal
from app.api.seating import compute_plan
from app.services.seat_engine import PlacementError

router = APIRouter(prefix="/candidates", tags=["candidates"])


class TicketUpdate(BaseModel):
    ticket_no: str


def _to_dict(r: Candidate) -> dict:
    return {"id": r.id, "hall_id": r.hall_id, "name": r.name,
            "ticket_no": r.ticket_no, "paper_id": r.paper_id}


@router.get("")
def list_candidates(db: Session = Depends(get_db)):
    return [_to_dict(r) for r in db.scalars(select(Candidate).order_by(Candidate.id)).all()]


@router.put("/{candidate_id}")
def update_ticket(candidate_id: int, body: TicketUpdate, db: Session = Depends(get_db)):
    """改正准考证号：号段、最新流水段、排座图必须同成功或同失败。

    * 新号为空或与他人重复 → 整场拒绝，什么都不改；
    * 成功：UPDATE 该考生号 + INSERT 一段新流水 + 一张新图，一起提交；
    * 重排若无有效方案（含流水重放对不上）→ 整段回到保存前（号也不改）；
    * 历史流水段永不被本次 UPDATE/DELETE，只允许新增一段。
    """
    cand = db.get(Candidate, candidate_id)
    if not cand:
        raise HTTPException(404, "考生不存在")

    new_ticket = (body.ticket_no or "").strip()
    if not new_ticket:
        raise HTTPException(400, {"error": "empty_ticket", "message": "准考证号为空，整场拒绝"})

    dup = db.scalars(
        select(Candidate).where(
            Candidate.hall_id == cand.hall_id,
            Candidate.id != cand.id,
            Candidate.ticket_no == new_ticket,
        )
    ).first()
    if dup:
        raise HTTPException(400, {"error": "duplicate_ticket",
                                  "message": f"准考证号重复：{new_ticket}", "problems": [new_ticket]})

    hall = db.get(Hall, cand.hall_id)

    # 留档历史流水（全部旧段），提交前必须逐字节一致——本次改号不得改写历史。
    history_before = db.scalars(
        select(SeatJournal).where(SeatJournal.hall_id == cand.hall_id).order_by(
            SeatJournal.id, SeatJournal.seq)
    ).all()
    snapshot = [(j.id, j.plan_id, j.seq, j.ticket_no, j.candidate_id, j.row, j.col)
                for j in history_before]

    cand.ticket_no = new_ticket  # 号段 UPDATE（尚未 commit）
    db.flush()
    try:
        result = compute_plan(db, hall)  # 新流水段 + 新图；失败即抛错
    except PlacementError as e:
        db.rollback()  # 流水、图、连同号段 UPDATE 整段回到保存前
        raise HTTPException(400, {"error": "placement_rejected",
                                  "message": "改号后无有效排座方案，号段与排座已整段恢复",
                                  "problems": e.problems})

    # 不可变校验：除新增的一段外，任何历史流水行都不得变化。
    history_after = db.scalars(
        select(SeatJournal).where(SeatJournal.hall_id == cand.hall_id).order_by(
            SeatJournal.id, SeatJournal.seq)
    ).all()
    after_snap = [(j.id, j.plan_id, j.seq, j.ticket_no, j.candidate_id, j.row, j.col)
                  for j in history_after if j.plan_id != result["id"]]
    if after_snap != snapshot:
        db.rollback()
        raise HTTPException(500, {"error": "journal_immutable_violation",
                                  "message": "检测到历史流水被改写，整段回滚"})

    db.commit()
    return {"candidate": _to_dict(cand), "plan": result}
