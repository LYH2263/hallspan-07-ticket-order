import pytest

from app.services.seat_engine import (
    LedgerLine,
    SeatAssign,
    SeatingError,
    find_violations,
    manhattan,
    place_candidates,
    replay_ledger,
    tail_digit,
    verify_plan,
)

def _cands(n, tickets=None, papers=None):
    tickets = tickets or [f"T{i:03d}" for i in range(1, n + 1)]
    papers = papers or [1 + (i % 2) for i in range(n)]
    return [{"id": i + 1, "name": f"C{i+1}", "ticket_no": tickets[i], "paper_id": papers[i]}
            for i in range(n)]

def test_manhattan():
    assert manhattan((0, 0), (2, 1)) == 3

def test_tail_digit():
    assert tail_digit("T2026012") == "2"
    assert tail_digit("T2026010") == "0"

def test_min_distance_placement():
    assigns, unplaced, ledger = place_candidates(4, 4, 2, _cands(4))
    assert len(assigns) + len(unplaced) == 4
    for i, a in enumerate(assigns):
        for b in assigns[i + 1:]:
            assert manhattan((a.row, a.col), (b.row, b.col)) >= 2

def test_same_paper_not_adjacent_in_result():
    cands = [
        {"id": 1, "name": "A", "ticket_no": "T1", "paper_id": 1},
        {"id": 2, "name": "B", "ticket_no": "T2", "paper_id": 1},
        {"id": 3, "name": "C", "ticket_no": "T3", "paper_id": 2},
    ]
    assigns, _, _ = place_candidates(3, 3, 1, cands)
    viols = find_violations(3, 3, 1, assigns)
    assert not any(v.kind == "same_paper_adjacent" for v in viols)

def test_violation_detection():
    assigns = [
        SeatAssign(1, "A", "T1", 1, 0, 0),
        SeatAssign(2, "B", "T2", 1, 0, 1),
    ]
    viols = find_violations(2, 2, 2, assigns)
    kinds = {v.kind for v in viols}
    assert "distance" in kinds
    assert "same_paper_adjacent" in kinds

# ---- 流水只追加 / 升序 / 可重放 ----

def test_ledger_is_ticket_ascending_regardless_of_input_order():
    # 输入按 id 给出，但号被打乱；流水必须按准考证升序。
    tickets = ["T9", "T2", "T7", "T1"]
    cands = _cands(4, tickets=tickets)
    assigns, unplaced, ledger = place_candidates(5, 5, 2, cands)
    seated_tickets = [l.ticket_no for l in ledger]
    assert seated_tickets == sorted(seated_tickets)
    assert set(seated_tickets) == {a.ticket_no for a in assigns}
    # seq 从 1 连续
    assert [l.seq for l in ledger] == list(range(1, len(ledger) + 1))

def test_ledger_replays_to_current_map():
    cands = _cands(8, tickets=["T8", "T3", "T5", "T1", "T9", "T2", "T6", "T4"])
    assigns, _, ledger = place_candidates(5, 5, 2, cands)
    verify_plan(assigns, ledger, 5, 5)  # 不抛即一致
    grid = replay_ledger(ledger, 5, 5)
    assert grid == {(a.row, a.col): a.candidate_id for a in assigns}

def test_replay_rejects_cell_collision():
    bad = [
        LedgerLine(1, 1, "T1", 0, 0),
        LedgerLine(2, 2, "T2", 0, 0),  # 同格
    ]
    with pytest.raises(SeatingError):
        replay_ledger(bad, 3, 3)

def test_verify_fails_when_ledger_does_not_match_map():
    cands = _cands(3)
    assigns, _, ledger = place_candidates(3, 3, 2, cands)
    # 篡改图：把某人挪到别的格子 -> 与流水对不上
    assigns[0] = SeatAssign(assigns[0].candidate_id, assigns[0].name,
                            assigns[0].ticket_no, assigns[0].paper_id, 2, 2)
    with pytest.raises(SeatingError):
        verify_plan(assigns, ledger, 3, 3)

# ---- 同排尾号唯一：后号另排或进未排，绝不挤位 ----

def test_same_tail_not_on_same_row_other_seat_or_unplaced():
    # 尾号 1 与 尾号 11 同尾；窄厅（1 排）放不下第二个 -> 进未排，而不是挤走先号
    cands = [
        {"id": 1, "name": "A", "ticket_no": "T01", "paper_id": 1},
        {"id": 2, "name": "B", "ticket_no": "T11", "paper_id": 2},
    ]
    assigns, unplaced, ledger = place_candidates(1, 4, 1, cands)
    rows_of = {a.ticket_no: a.row for a in assigns}
    tails_per_row: dict[int, set] = {}
    for a in assigns:
        assert tail_digit(a.ticket_no) not in tails_per_row.setdefault(a.row, set())
        tails_per_row[a.row].add(tail_digit(a.ticket_no))
    assert len(assigns) + len(unplaced) == 2
    # 先号 T01（升序在前）必落位，且未被挤动
    assert rows_of.get("T01") == 0

def test_same_tail_can_use_another_row():
    cands = [
        {"id": 1, "name": "A", "ticket_no": "T01", "paper_id": 1},
        {"id": 2, "name": "B", "ticket_no": "T11", "paper_id": 2},
    ]
    assigns, unplaced, ledger = place_candidates(2, 2, 1, cands)
    assert not unplaced
    by = {a.ticket_no: a for a in assigns}
    assert by["T01"].row != by["T11"].row
    verify_plan(assigns, ledger, 2, 2)

def test_same_tail_violation_is_its_own_kind_not_distance():
    assigns = [
        SeatAssign(1, "A", "T01", 1, 0, 0),
        SeatAssign(2, "B", "T11", 2, 0, 2),  # 同排同尾，距离 2（非间距不足）
    ]
    viols = find_violations(1, 4, 2, assigns)
    tail_viols = [v for v in viols if v.kind == "same_tail_same_row"]
    assert len(tail_viols) == 1
    assert "间距" not in tail_viols[0].detail  # 说明不得写成间距不足
    assert "尾号" in tail_viols[0].detail

def test_no_backtracking_earlier_ticket_never_moved_for_later():
    # T01 升序第一，占 (0,0)；后到的同尾 T11 不能改变 T01 的格子
    cands = [
        {"id": 1, "name": "A", "ticket_no": "T01", "paper_id": 1},
        {"id": 2, "name": "B", "ticket_no": "T11", "paper_id": 1},
        {"id": 3, "name": "C", "ticket_no": "T02", "paper_id": 2},
    ]
    assigns, _, ledger = place_candidates(3, 3, 2, cands)
    first = next(l for l in ledger if l.ticket_no == "T01")
    assert (first.row, first.col) == (0, 0)

# ---- 号空 / 重复整场拒绝 ----

def test_blank_ticket_rejected():
    cands = _cands(2, tickets=["T1", "   "])
    with pytest.raises(SeatingError):
        place_candidates(3, 3, 2, cands)

def test_duplicate_ticket_rejected():
    cands = _cands(3, tickets=["T1", "T2", "T2"])
    with pytest.raises(SeatingError):
        place_candidates(3, 3, 2, cands)
