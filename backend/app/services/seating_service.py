"""排座事务编排：号段校验、算图、只追加流水段、重放校验、整段提交/回滚。

“流水只追加”：任何一次成功排座或改正准考证号，都只 INSERT 新 SeatPlan +
新一段 SeatLedger；历史流水行永不 UPDATE。改号若没有有效方案（重放对不上、
同排尾号冲突放不下等），号 UPDATE、最新流水段、图三者整段回滚到保存前。
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Candidate, Hall, SeatLedger, SeatPlan
from app.services.seat_engine import (
    SeatingError,
    find_violations,
    place_candidates,
    plan_to_dict,
    verify_plan,
)

def load_candidates(db: Session, hall_id: int) -> list[dict]:
    # 显式按号排序无意义：流水的升序由引擎负责；这里只按 id 稳定取全量。
    rows = db.scalars(
        select(Candidate).where(Candidate.hall_id == hall_id).order_by(Candidate.id)
    ).all()
    return [{"id": c.id, "name": c.name, "ticket_no": c.ticket_no, "paper_id": c.paper_id}
            for c in rows]

def validate_ticket_update(db: Session, hall_id: int, candidate_id: int,
                           new_ticket: str) -> None:
    """改正准考证号的入口校验：号空或与同场他人重复 -> 整场拒绝。"""
    t = (new_ticket or "").strip()
    if not t:
        raise SeatingError("准考证号为空，整场拒绝")
    dup = db.scalars(
        select(Candidate).where(
            Candidate.hall_id == hall_id,
            Candidate.ticket_no == t,
            Candidate.id != candidate_id,
        )
    ).first()
    if dup:
        raise SeatingError(f"准考证号与同考室考生重复：{t}，整场拒绝")

def _persist_plan(db: Session, hall: Hall, cands: list[dict]) -> dict:
    """算图 -> 重放校验 -> 同事务落 SeatPlan + 一段只追加流水（不 commit）。"""
    assigns, unplaced, ledger = place_candidates(
        hall.rows, hall.cols, hall.min_manhattan, cands
    )
    # 当前图必须能被该段流水重放出来；对不上直接失败，不落任何行。
    verify_plan(assigns, ledger, hall.rows, hall.cols)
    viols = find_violations(hall.rows, hall.cols, hall.min_manhattan, assigns)
    result = plan_to_dict(assigns, unplaced, viols, hall.rows, hall.cols, ledger)
    result["hall"] = {"id": hall.id, "name": hall.name, "min_manhattan": hall.min_manhattan}

    plan = SeatPlan(hall_id=hall.id, created_at=datetime.utcnow(),
                    result_json=json.dumps(result, ensure_ascii=False))
    db.add(plan)
    db.flush()  # 取 plan.id；尚未 commit，失败可整体回滚
    for line in ledger:
        db.add(SeatLedger(
            hall_id=hall.id, plan_id=plan.id, seq=line.seq,
            candidate_id=line.candidate_id, ticket_no=line.ticket_no,
            row=line.row, col=line.col, created_at=datetime.utcnow(),
        ))
    db.flush()
    result["id"] = plan.id
    return result

def run_seating_txn(db: Session, hall: Hall) -> dict:
    """整场重排：取当前全量号段算图并提交一段新流水。"""
    cands = load_candidates(db, hall.id)
    result = _persist_plan(db, hall, cands)
    db.commit()
    return result

def correct_ticket_txn(db: Session, candidate: Candidate, new_ticket: str) -> dict:
    """改正准考证号：号段、最新流水段、图同成功或同失败。

    - 号空/重复：SeatingError，什么都不改；
    - 有有效方案：一个事务内 UPDATE 号 + INSERT 新 SeatPlan + INSERT 新流水段，
      重放校验通过才 commit；
    - 无有效方案/重放对不上：整体 rollback，号、流水、图全部回到保存前，
      历史流水行绝不被这次改号 UPDATE。
    """
    hall = db.get(Hall, candidate.hall_id)
    if hall is None:
        raise SeatingError("考室不存在")
    validate_ticket_update(db, candidate.hall_id, candidate.id, new_ticket)

    new_ticket = new_ticket.strip()
    candidate.ticket_no = new_ticket
    db.flush()  # 号段更新进事务，但未提交；失败随整段回滚

    cands = load_candidates(db, candidate.hall_id)
    try:
        result = _persist_plan(db, hall, cands)
    except SeatingError:
        db.rollback()
        raise
    db.commit()
    return result
