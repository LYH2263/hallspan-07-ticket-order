from sqlalchemy import func, select

from app.models.models import Candidate, Hall, PaperSet, SeatJournal, SeatPlan


def _make_hall(session, rows=5, cols=6, min_dist=2):
    hall = Hall(code="H1", name="一号考室", rows=rows, cols=cols, min_manhattan=min_dist)
    session.add(hall); session.flush()
    papers = []
    for code in ("A", "B", "C"):
        p = PaperSet(code=f"P-{code}", title=f"卷{code}")
        session.add(p); session.flush()
        papers.append(p.id)
    return hall, papers


def _add_candidates(session, hall, papers, tickets):
    for i, t in enumerate(tickets):
        session.add(Candidate(hall_id=hall.id, name=f"考生{i}", ticket_no=t,
                              paper_id=papers[i % len(papers)]))
    session.commit()


def test_run_writes_append_only_journal_and_replays(harness):
    client, Session = harness
    with Session() as s:
        hall, papers = _make_hall(s)
        _add_candidates(s, hall, papers, [f"T{2026001+i}" for i in range(12)])

    r = client.post("/api/seating/run?hall_id=1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["replay_ok"] is True
    tickets = [e["ticket_no"] for e in body["journal"]]
    assert tickets == sorted(tickets)  # 流水升序
    assert body["stats"]["journal_entries"] == body["stats"]["seated"]

    # 独立重放端点一致
    rp = client.post("/api/seating/replay?hall_id=1").json()
    assert rp["replay_ok"] is True
    assert len(rp["grid"]) == body["stats"]["seated"]

    # 库里确有一段流水
    with Session() as s:
        assert s.scalar(select(func.count()).select_from(SeatJournal)) == body["stats"]["seated"]


def test_run_rejects_empty_or_duplicate_ticket(harness):
    client, Session = harness
    with Session() as s:
        hall, papers = _make_hall(s)
        _add_candidates(s, hall, papers, ["T001", "T001", "T003"])

    r = client.post("/api/seating/run?hall_id=1")
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "placement_rejected"
    with Session() as s:  # 整场拒绝：无图无流水
        assert s.scalar(select(func.count()).select_from(SeatPlan)) == 0
        assert s.scalar(select(func.count()).select_from(SeatJournal)) == 0


def test_rename_success_adds_journal_segment_keeps_history(harness):
    client, Session = harness
    with Session() as s:
        hall, papers = _make_hall(s)
        _add_candidates(s, hall, papers, [f"T{2026001+i}" for i in range(12)])

    r1 = client.post("/api/seating/run?hall_id=1").json()
    first_plan_id = r1["id"]
    with Session() as s:
        first_segment = [(j.seq, j.ticket_no, j.row, j.col) for j in s.scalars(
            select(SeatJournal).where(SeatJournal.plan_id == first_plan_id)
            .order_by(SeatJournal.seq)).all()]

    # 改号（换成一个不冲突、尾号不同的号）
    r2 = client.put("/api/candidates/1", json={"ticket_no": "T9999998"})
    assert r2.status_code == 200, r2.text
    new_plan_id = r2.json()["plan"]["id"]
    assert new_plan_id != first_plan_id

    with Session() as s:
        # 号段确实更新
        assert s.get(Candidate, 1).ticket_no == "T9999998"
        # 旧流水段逐字节保留（历史流水未被 UPDATE）
        old = [(j.seq, j.ticket_no, j.row, j.col) for j in s.scalars(
            select(SeatJournal).where(SeatJournal.plan_id == first_plan_id)
            .order_by(SeatJournal.seq)).all()]
        assert old == first_segment
        # 新增了一段
        assert s.scalar(select(func.count()).select_from(SeatPlan)) == 2
        new_seg = s.scalars(select(SeatJournal).where(SeatJournal.plan_id == new_plan_id)).all()
        assert {j.ticket_no for j in new_seg} >= {"T9999998"}

    # 最新图可重放
    assert client.post("/api/seating/replay?hall_id=1").json()["replay_ok"] is True


def test_rename_empty_or_duplicate_rejected_entirely(harness):
    client, Session = harness
    with Session() as s:
        hall, papers = _make_hall(s)
        _add_candidates(s, hall, papers, [f"T{2026001+i}" for i in range(12)])
    client.post("/api/seating/run?hall_id=1")
    plans_before, journals_before = _counts(Session)

    assert client.put("/api/candidates/1", json={"ticket_no": "  "}).status_code == 400
    assert client.put("/api/candidates/1", json={"ticket_no": "T2026002"}).status_code == 400

    with Session() as s:
        # 号没改、没有新增图/流水
        assert s.get(Candidate, 1).ticket_no == "T2026001"
    assert _counts(Session) == (plans_before, journals_before)


def test_rename_rolls_back_ticket_and_segment_when_plan_fails(harness, monkeypatch):
    # 号段已 UPDATE，但随后重排被判"无有效方案"（PlacementError）：
    # 号、新流水段、新图必须整段回到保存前。
    client, Session = harness
    with Session() as s:
        hall, papers = _make_hall(s, rows=2, cols=2, min_dist=2)
        _add_candidates(s, hall, papers, ["T001", "T002", "T003"])
    client.post("/api/seating/run?hall_id=1")
    plans_before, journals_before = _counts(Session)

    import app.api.seating as seating_mod
    from app.services.seat_engine import PlacementError

    def boom(*a, **k):
        raise PlacementError(["模拟：改号后无有效排座方案"])

    monkeypatch.setattr(seating_mod, "place_candidates", boom)

    r = client.put("/api/candidates/1", json={"ticket_no": "T9999998"})
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "placement_rejected"

    with Session() as s:
        assert s.get(Candidate, 1).ticket_no == "T001"  # 号段回到保存前
    assert _counts(Session) == (plans_before, journals_before)  # 无新图、无新流水段


def test_rename_same_tail_fills_row_then_unplaced_keeps_history(harness):
    # 1 排 2 列：改成同尾号后一排只能容一个，另一人进未排，仍是有效方案；
    # 成功时只新增一张图+一段流水，旧段保留。
    client, Session = harness
    with Session() as s:
        hall, papers = _make_hall(s, rows=1, cols=2, min_dist=1)
        _add_candidates(s, hall, papers, ["T001", "T002"])
    client.post("/api/seating/run?hall_id=1")
    plans_before, journals_before = _counts(Session)

    r = client.put("/api/candidates/2", json={"ticket_no": "T091"})
    assert r.status_code == 200, r.text
    assert r.json()["plan"]["stats"]["unplaced"] == 1
    assert _counts(Session) == (plans_before + 1, journals_before + 1)
    with Session() as s:  # 历史首段仍是 2 行，未被改写
        assert len(s.scalars(
            select(SeatJournal).where(SeatJournal.plan_id == 1)).all()) == 2


def test_seeded_shuffle_and_no_duplicate_tail_per_row(harness):
    client, Session = harness
    with Session() as s:
        hall, papers = _make_hall(s)
        # 刻意放多个同尾号
        tickets = ["T001", "T011", "T021", "T002", "T012", "T022",
                   "T003", "T013", "T023", "T004", "T014", "T024"]
        _add_candidates(s, hall, papers, tickets)
    body = client.post("/api/seating/run?hall_id=1").json()
    assert body["replay_ok"] is True
    # 同一排不得有两个相同尾号
    seen = set()
    for a in body["assignments"]:
        key = (a["row"], a["ticket_no"].strip()[-1])
        assert key not in seen
        seen.add(key)
    # 流水升序可重放
    assert [e["ticket_no"] for e in body["journal"]] == \
        sorted(e["ticket_no"] for e in body["journal"])


def _counts(Session):
    with Session() as s:
        return (s.scalar(select(func.count()).select_from(SeatPlan)),
                s.scalar(select(func.count()).select_from(SeatJournal)))


def test_seed_shuffles_tickets_but_placement_still_valid(harness):
    client, Session = harness
    from app.services.seed import seed_if_empty
    with Session() as s:
        seed_if_empty(s)
    with Session() as s:
        tickets_in_id_order = [c.ticket_no for c in
                               s.scalars(select(Candidate).order_by(Candidate.id)).all()]
    # 固定种子打乱：入库 id 顺序不等于准考证号升序
    assert tickets_in_id_order != sorted(tickets_in_id_order)
    body = client.post("/api/seating/run?hall_id=1").json()
    assert body["replay_ok"] is True
    assert [e["ticket_no"] for e in body["journal"]] == \
        sorted(e["ticket_no"] for e in body["journal"])
    seen = set()
    for a in body["assignments"]:
        key = (a["row"], a["ticket_no"].strip()[-1])
        assert key not in seen
        seen.add(key)
