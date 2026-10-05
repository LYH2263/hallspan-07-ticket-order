from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
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


class SeatJournal(Base):
    """只追加（append-only）占座流水账。

    每一段对应一次成功排座（plan_id），段内按准考证升序、seq 从 1 开始。
    应用层永不 UPDATE / DELETE 历史行：改号只会 INSERT 新的一段，
    旧段原封不动，用于重放当时的排座图。
    """
    __tablename__ = "seat_journal"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("seat_plans.id"))
    seq: Mapped[int] = mapped_column(Integer)
    ticket_no: Mapped[str] = mapped_column(String(32))
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"))
    row: Mapped[int] = mapped_column(Integer)
    col: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
