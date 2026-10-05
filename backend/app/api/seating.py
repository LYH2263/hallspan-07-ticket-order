import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Hall, SeatLedger, SeatPlan
from app.services.seat_engine import SeatingError
from app.services.seating_service import run_seating_txn
router = APIRouter(prefix="/seating", tags=["seating"])

@router.post("/run")
def run_seating(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    try:
        # 号空/重复由引擎整场拒绝（SeatingError），事务回滚，不落任何流水/图。
        return run_seating_txn(db, hall)
    except SeatingError as e:
        raise HTTPException(400, f"排座被整场拒绝，流水与图均未提交：{e}")

def _ledger_rows(db: Session, plan_id: int) -> list[SeatLedger]:
    return list(db.scalars(
        select(SeatLedger).where(SeatLedger.plan_id == plan_id).order_by(SeatLedger.seq)
    ).all())

@router.get("/latest")
def latest(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    plan = db.scalars(
        select(SeatPlan).where(SeatPlan.hall_id == hall_id).order_by(SeatPlan.id.desc())
    ).first()
    if not plan:
        return run_seating(hall_id=hall_id, db=db)
    data = json.loads(plan.result_json)
    # 流水以库里只追加的行为准（历史行从不改写），按 seq 升序返回可重放当前图。
    rows = _ledger_rows(db, plan.id)
    data["ledger"] = [
        {"seq": r.seq, "candidate_id": r.candidate_id, "ticket_no": r.ticket_no,
         "row": r.row, "col": r.col}
        for r in rows
    ]
    return {"id": plan.id, **data}

@router.get("/violations")
def violations(hall_id: int = 1, db: Session = Depends(get_db)):
    data = latest(hall_id=hall_id, db=db)
    return {"hall_id": hall_id, "violations": data.get("violations", []), "unplaced": data.get("unplaced", [])}

@router.get("/stats")
def stats(hall_id: int = 1, db: Session = Depends(get_db)):
    data = latest(hall_id=hall_id, db=db)
    return {"hall_id": hall_id, **data.get("stats", {})}
