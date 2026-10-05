import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import Candidate, Hall, PaperSet, SeatLedger, SeatPlan


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestingSession()

    def _override():
        # 每个请求独立 Session，但经 StaticPool 共享同一个内存库，
        # 请求结束关闭，测试持有的 db 仍可见已 commit 的数据。
        other = TestingSession()
        try:
            yield other
        finally:
            other.close()

    app.dependency_overrides[get_db] = _override
    try:
        yield db
    finally:
        app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session):
    return TestClient(app)


def _make_hall(db, rows=5, cols=6, min_dist=2):
    hall = Hall(code="H1", name="测试室", rows=rows, cols=cols, min_manhattan=min_dist)
    db.add(hall)
    db.flush()
    p1 = PaperSet(code="PA", title="A")
    p2 = PaperSet(code="PB", title="B")
    db.add_all([p1, p2])
    db.flush()
    return hall, p1, p2


def _add_candidate(db, hall, paper, name, ticket_no):
    c = Candidate(hall_id=hall.id, name=name, ticket_no=ticket_no, paper_id=paper.id)
    db.add(c)
    db.flush()
    return c


def _segments(db, hall_id):
    plans = list(db.scalars(
        select(SeatPlan).where(SeatPlan.hall_id == hall_id).order_by(SeatPlan.id)
    ).all())
    out = []
    for p in plans:
        rows = list(db.scalars(
            select(SeatLedger).where(SeatLedger.plan_id == p.id).order_by(SeatLedger.seq)
        ).all())
        out.append((p, rows))
    return out


def test_run_appends_ledger_segment_that_replays_map(client, db_session):
    hall, p1, p2 = _make_hall(db_session)
    # 打乱号的输入顺序，验证流水按号升序而非 id
    _add_candidate(db_session, hall, p1, "甲", "T9")
    _add_candidate(db_session, hall, p2, "乙", "T2")
    _add_candidate(db_session, hall, p1, "丙", "T7")
    db_session.commit()

    res = client.post("/api/seating/run?hall_id=1")
    assert res.status_code == 200, res.text
    data = res.json()
    tickets = [l["ticket_no"] for l in data["ledger"]]
    assert tickets == sorted(tickets)
    assert [l["seq"] for l in data["ledger"]] == list(range(1, len(tickets) + 1))

    # 库里落了同一段流水
    segs = _segments(db_session, hall.id)
    assert len(segs) == 1
    plan, rows = segs[0]
    assert [r.ticket_no for r in rows] == tickets

    # 重放 == 当前图
    grid = {(r.row, r.col): r.candidate_id for r in rows}
    actual = {(a["row"], a["col"]): a["candidate_id"] for a in data["assignments"]}
    assert grid == actual

    # 同排无重复尾号
    per_row: dict[int, set] = {}
    for a in data["assignments"]:
        tail = a["ticket_no"][-1]
        assert tail not in per_row.setdefault(a["row"], set())
        per_row[a["row"]].add(tail)


def test_ledger_is_append_only_across_runs(client, db_session):
    hall, p1, p2 = _make_hall(db_session)
    c = _add_candidate(db_session, hall, p1, "甲", "T1")
    db_session.commit()
    client.post("/api/seating/run?hall_id=1")
    client.post("/api/seating/run?hall_id=1")

    segs = _segments(db_session, hall.id)
    assert len(segs) == 2
    first_rows = [r.ticket_no for r in segs[0][1]]
    # 历史段仍在、内容不变（只追加，不改写）
    assert first_rows == [r.ticket_no for r in segs[0][1]]
    assert segs[0][1][0].ticket_no == "T1"
    assert all(r.plan_id == segs[0][0].id for r in segs[0][1])


def test_correct_ticket_success_is_atomic_and_appends(client, db_session):
    hall, p1, p2 = _make_hall(db_session)
    c = _add_candidate(db_session, hall, p1, "甲", "T1")
    _add_candidate(db_session, hall, p2, "乙", "T2")
    db_session.commit()
    client.post("/api/seating/run?hall_id=1")

    before = _segments(db_session, hall.id)
    assert len(before) == 1
    old_snapshot = [(r.id, r.ticket_no, r.row, r.col, r.seq) for r in before[0][1]]

    res = client.patch(f"/api/candidates/{c.id}", json={"ticket_no": "T8"})
    assert res.status_code == 200, res.text

    db_session.refresh(c)
    assert c.ticket_no == "T8"

    segs = _segments(db_session, hall.id)
    assert len(segs) == 2  # 只追加了新段
    # 历史流水行原样保留，没有被这次 UPDATE 改成 T8
    hist = [(r.id, r.ticket_no, r.row, r.col, r.seq) for r in segs[0][1]]
    assert hist == old_snapshot
    assert "T8" in [r.ticket_no for r in segs[1][1]]
    # 新段可重放新图
    new_data = res.json()
    grid = {(r.row, r.col): r.candidate_id for r in segs[1][1]}
    actual = {(a["row"], a["col"]): a["candidate_id"] for a in new_data["assignments"]}
    assert grid == actual


def test_correct_ticket_duplicate_rejected_whole(client, db_session):
    hall, p1, p2 = _make_hall(db_session)
    c1 = _add_candidate(db_session, hall, p1, "甲", "T1")
    c2 = _add_candidate(db_session, hall, p2, "乙", "T2")
    db_session.commit()
    client.post("/api/seating/run?hall_id=1")

    res = client.patch(f"/api/candidates/{c1.id}", json={"ticket_no": "T2"})
    assert res.status_code == 400

    db_session.refresh(c1)
    assert c1.ticket_no == "T1"  # 号段回到保存前
    segs = _segments(db_session, hall.id)
    assert len(segs) == 1  # 没有新流水段、没有新图


def test_correct_ticket_blank_rejected_whole(client, db_session):
    hall, p1, p2 = _make_hall(db_session)
    c1 = _add_candidate(db_session, hall, p1, "甲", "T1")
    db_session.commit()
    client.post("/api/seating/run?hall_id=1")

    res = client.patch(f"/api/candidates/{c1.id}", json={"ticket_no": "   "})
    assert res.status_code == 400
    db_session.refresh(c1)
    assert c1.ticket_no == "T1"
    assert len(_segments(db_session, hall.id)) == 1


def test_failed_plan_rolls_back_ticket_and_segment(db_session, monkeypatch):
    # 无有效方案（重放对不上）时：号、最新流水段、图整段回到保存前。
    import app.services.seating_service as svc
    from app.services.seat_engine import SeatingError

    hall, p1, p2 = _make_hall(db_session)
    c = _add_candidate(db_session, hall, p1, "甲", "T1")
    db_session.commit()
    from app.services.seating_service import run_seating_txn
    run_seating_txn(db_session, hall)

    plans_before = len(_segments(db_session, hall.id))

    def boom(*a, **k):
        raise SeatingError("模拟无有效方案")

    monkeypatch.setattr(svc, "_persist_plan", boom)
    import pytest
    with pytest.raises(SeatingError):
        svc.correct_ticket_txn(db_session, c, "T9")

    db_session.refresh(c)
    assert c.ticket_no == "T1"  # 号回滚
    assert len(_segments(db_session, hall.id)) == plans_before  # 无新图新段


def test_run_rejects_blank_ticket_whole_hall(client, db_session):
    hall, p1, p2 = _make_hall(db_session)
    _add_candidate(db_session, hall, p1, "甲", "T1")
    _add_candidate(db_session, hall, p2, "乙", "")
    db_session.commit()
    res = client.post("/api/seating/run?hall_id=1")
    assert res.status_code == 400
    assert len(_segments(db_session, hall.id)) == 0  # 整场拒绝，无图无流水


def test_same_tail_single_row_later_goes_unplaced_not_shove(client, db_session):
    hall, p1, p2 = _make_hall(db_session, rows=1, cols=4, min_dist=1)
    a = _add_candidate(db_session, hall, p1, "甲", "T01")
    b = _add_candidate(db_session, hall, p2, "乙", "T11")  # 同尾 1
    db_session.commit()

    res = client.post("/api/seating/run?hall_id=1")
    assert res.status_code == 200
    data = res.json()
    assert len(data["assignments"]) == 1
    assert len(data["unplaced"]) == 1
    assert data["assignments"][0]["ticket_no"] == "T01"  # 先号在位未被挤
    assert data["unplaced"][0]["ticket_no"] == "T11"
