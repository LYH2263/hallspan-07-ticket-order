import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Candidate, Hall, SeatJournal, SeatPlan
from app.services.seat_engine import (
    JournalEntry,
    PlacementError,
    find_violations,
    place_candidates,
    plan_to_dict,
    replay_journal,
)

router = APIRouter(prefix="/seating", tags=["seating"])


def _load_candidates(db: Session, hall_id: int) -> list[dict]:
    return [
        {"id": c.id, "name": c.name, "ticket_no": c.ticket_no, "paper_id": c.paper_id}
        for c in db.scalars(select(Candidate).where(Candidate.hall_id == hall_id)).all()
    ]


def compute_plan(db: Session, hall: Hall) -> dict:
    """计算并在【当前事务内】落库：新图（seat_plans）+ 新流水段（seat_journal）。

    只 INSERT，绝不 UPDATE/DELETE 任何历史流水。调用方负责 commit/rollback：
    号段 UPDATE、新流水段、新图同成功或同失败。
    """
    cands = _load_candidates(db, hall.id)
    assigns, unplaced, journal = place_candidates(
        hall.rows, hall.cols, hall.min_manhattan, cands
    )  # 号空/重复在此抛 PlacementError，此刻尚未写入任何东西
    viols = find_violations(hall.rows, hall.cols, hall.min_manhattan, assigns)
    result = plan_to_dict(assigns, unplaced, viols, hall.rows, hall.cols, journal)
    result["hall"] = {"id": hall.id, "name": hall.name, "min_manhattan": hall.min_manhattan}

    plan = SeatPlan(hall_id=hall.id, created_at=datetime.utcnow(),
                    result_json=json.dumps(result, ensure_ascii=False))
    db.add(plan)
    db.flush()  # 取 plan.id
    for e in journal:  # 只追加一段新流水；历史行原封不动
        db.add(SeatJournal(
            hall_id=hall.id, plan_id=plan.id, seq=e.seq, ticket_no=e.ticket_no,
            candidate_id=e.candidate_id, row=e.row, col=e.col,
            created_at=datetime.utcnow(),
        ))
    db.flush()

    # 提交前终检：用刚落库的流水段重放，必须能还原这张图，否则整段作废。
    persisted = _journal_entries(db, hall.id, plan.id)
    if not _journal_replays_plan(hall, persisted, result):
        raise PlacementError(["流水重放与当前排座图不一致，整段回滚"])
    result["id"] = plan.id
    result["replay_ok"] = True
    return result


def _journal_entries(db: Session, hall_id: int, plan_id: int) -> list[JournalEntry]:
    rows = db.scalars(
        select(SeatJournal)
        .where(SeatJournal.hall_id == hall_id, SeatJournal.plan_id == plan_id)
        .order_by(SeatJournal.seq)
    ).all()
    return [JournalEntry(seq=r.seq, ticket_no=r.ticket_no, candidate_id=r.candidate_id,
                         row=r.row, col=r.col) for r in rows]


def _journal_replays_plan(hall: Hall, journal: list[JournalEntry], plan_result: dict) -> bool:
    try:
        grid = replay_journal(hall.rows, hall.cols, journal)
    except PlacementError:
        return False
    expect = {(a["row"], a["col"]): a["candidate_id"] for a in plan_result["assignments"]}
    return grid == expect and len(grid) == len(expect)


@router.post("/run")
def run_seating(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    try:
        result = compute_plan(db, hall)
        db.commit()
    except PlacementError as e:
        db.rollback()
        raise HTTPException(400, {"error": "placement_rejected", "problems": e.problems})
    return result


@router.get("/latest")
def latest(hall_id: int = 1, db: Session = Depends(get_db)):
    plan = db.scalars(
        select(SeatPlan).where(SeatPlan.hall_id == hall_id).order_by(SeatPlan.id.desc())
    ).first()
    if not plan:
        return run_seating(hall_id=hall_id, db=db)
    data = json.loads(plan.result_json)
    journal = _journal_entries(db, hall_id, plan.id)
    data["replay_ok"] = _journal_replays_plan(hall, journal, data) if journal else False
    return {"id": plan.id, **data}


@router.get("/journal")
def journal(hall_id: int = 1, db: Session = Depends(get_db)):
    """最新一段只追加流水（按次序 seq 升序）及重放校验结果。"""
    plan = db.scalars(
        select(SeatPlan).where(SeatPlan.hall_id == hall_id).order_by(SeatPlan.id.desc())
    ).first()
    if not plan:
        return {"hall_id": hall_id, "plan_id": None, "entries": [], "replay_ok": False}
    entries = _journal_entries(db, hall_id, plan.id)
    data = json.loads(plan.result_json)
    ok = _journal_replays_plan(hall, entries, data)
    return {
        "hall_id": hall_id,
        "plan_id": plan.id,
        "replay_ok": ok,
        "entries": [vars(e) for e in entries],
    }


@router.post("/replay")
def replay(hall_id: int = 1, db: Session = Depends(get_db)):
    """用最新流水段重放当前图；对不上返回 409（流水与图不一致）。"""
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    plan = db.scalars(
        select(SeatPlan).where(SeatPlan.hall_id == hall_id).order_by(SeatPlan.id.desc())
    ).first()
    if not plan:
        raise HTTPException(404, "尚无排座流水")
    entries = _journal_entries(db, hall_id, plan.id)
    data = json.loads(plan.result_json)
    if not _journal_replays_plan(hall, entries, data):
        raise HTTPException(409, {"error": "replay_mismatch",
                                  "message": "流水无法重放当前排座图"})
    grid = replay_journal(hall.rows, hall.cols, entries)
    return {"plan_id": plan.id, "replay_ok": True,
            "grid": [{"row": r, "col": c, "candidate_id": cid} for (r, c), cid in
                     sorted(grid.items())]}


@router.get("/violations")
def violations(hall_id: int = 1, db: Session = Depends(get_db)):
    data = latest(hall_id=hall_id, db=db)
    return {"hall_id": hall_id, "violations": data.get("violations", []),
            "unplaced": data.get("unplaced", [])}


@router.get("/stats")
def stats(hall_id: int = 1, db: Session = Depends(get_db)):
    data = latest(hall_id=hall_id, db=db)
    return {"hall_id": hall_id, **data.get("stats", {})}
