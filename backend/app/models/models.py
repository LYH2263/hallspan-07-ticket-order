from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class Hall(Base):
    __tablename__ = "halls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    rows: Mapped[int] = mapped_column(Integer)
    cols: Mapped[int] = mapped_column(Integer)
    min_manhattan: Mapped[int] = mapped_column(Integer, default=2)

class PaperSet(Base):
    __tablename__ = "paper_sets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(128))

class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (
        # 同一考室准考证号不得重复（号空由接口层整场拒绝）。
        UniqueConstraint("hall_id", "ticket_no", name="uq_candidate_hall_ticket"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"))
    name: Mapped[str] = mapped_column(String(64))
    ticket_no: Mapped[str] = mapped_column(String(32))
    paper_id: Mapped[int] = mapped_column(ForeignKey("paper_sets.id"))

class SeatPlan(Base):
    __tablename__ = "seat_plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    result_json: Mapped[str] = mapped_column(Text, default="{}")

class SeatLedger(Base):
    """只追加的占座流水账。

    每次成功排座追加“一段”（同一 plan_id 的连续 seq 行，按准考证升序）。
    流水只追加：任何改正/重排都只 INSERT 新段，绝不 UPDATE 历史行。
    最新一段必须能重放出其 SeatPlan 的当前图，否则该段随事务整体回滚。
    """
    __tablename__ = "seat_ledger"
    __table_args__ = (
        UniqueConstraint("plan_id", "seq", name="uq_ledger_plan_seq"),
        UniqueConstraint("plan_id", "ticket_no", name="uq_ledger_plan_ticket"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("seat_plans.id"))
    # 段内次序，从 1 起按准考证升序连续递增。
    seq: Mapped[int] = mapped_column(Integer)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))
    ticket_no: Mapped[str] = mapped_column(String(32))
    row: Mapped[int] = mapped_column(Integer)
    col: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
