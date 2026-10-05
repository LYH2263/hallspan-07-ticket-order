from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Candidate
from app.services.seat_engine import SeatingError
from app.services.seating_service import correct_ticket_txn

router = APIRouter(prefix="/candidates", tags=["candidates"])

class TicketPatch(BaseModel):
    ticket_no: str

@router.get("")
def list_candidates(db: Session = Depends(get_db)):
    return [{"id": r.id, "hall_id": r.hall_id, "name": r.name, "ticket_no": r.ticket_no, "paper_id": r.paper_id}
            for r in db.scalars(select(Candidate).order_by(Candidate.id)).all()]

@router.patch("/{candidate_id}")
def correct_ticket(candidate_id: int, body: TicketPatch, db: Session = Depends(get_db)):
    """改正准考证号。

    号空或重复 -> 整场拒绝（400），号段/流水/图一律不动。
    有有效方案 -> 号 UPDATE、最新流水段、新图在同一事务内同成功；
    无有效方案/重放对不上 -> 同失败，流水与图整段回到保存前，
    历史流水行不被这次改号 UPDATE。
    """
    candidate = db.get(Candidate, candidate_id)
    if not candidate:
        raise HTTPException(404, "考生不存在")
    try:
        result = correct_ticket_txn(db, candidate, body.ticket_no)
    except SeatingError as e:
        raise HTTPException(400, f"改号被拒绝，流水与图整段回到保存前：{e}")
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "准考证号重复或为空，整场拒绝（已回滚）")
    return {
        "id": candidate_id,
        "ticket_no": candidate.ticket_no,
        "plan_id": result["id"],
        "ledger": result["ledger"],
        "assignments": result["assignments"],
        "unplaced": result["unplaced"],
    }
