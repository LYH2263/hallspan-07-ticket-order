import pytest

from app.services.seat_engine import (
    JournalEntry,
    PlacementError,
    SeatAssign,
    find_violations,
    journal_to_dicts,
    manhattan,
    place_candidates,
    replay_journal,
    replay_matches,
    ticket_tail,
    validate_tickets,
)


def test_manhattan():
    assert manhattan((0, 0), (2, 1)) == 3


def test_ticket_tail():
    assert ticket_tail("T2026001") == "1"
    assert ticket_tail("  X9 ") == "9"


def test_min_distance_placement():
    cands = [{"id": i, "name": f"C{i}", "ticket_no": f"T{i:03d}", "paper_id": 1 + (i % 2)}
             for i in range(4)]
    assigns, unplaced, journal = place_candidates(4, 4, 2, cands)
    assert len(assigns) + len(unplaced) == 4
    for i, a in enumerate(assigns):
        for b in assigns[i + 1:]:
            assert manhattan((a.row, a.col), (b.row, b.col)) >= 2
    # 流水按准考证升序、seq 从 1 连续
    assert [e.ticket_no for e in journal] == sorted(e.ticket_no for e in journal)
    assert [e.seq for e in journal] == list(range(1, len(journal) + 1))


def test_empty_ticket_rejected_entire_session():
    cands = [
        {"id": 1, "name": "A", "ticket_no": "T001", "paper_id": 1},
        {"id": 2, "name": "B", "ticket_no": "   ", "paper_id": 1},
    ]
    with pytest.raises(PlacementError):
        place_candidates(4, 4, 1, cands)
    with pytest.raises(PlacementError):
        validate_tickets(cands)


def test_duplicate_ticket_rejected_entire_session():
    cands = [
        {"id": 1, "name": "A", "ticket_no": "T001", "paper_id": 1},
        {"id": 2, "name": "B", "ticket_no": "T001", "paper_id": 2},
    ]
    with pytest.raises(PlacementError):
        place_candidates(4, 4, 1, cands)


def test_seeded_shuffle_not_ticket_order_but_replayable():
    # 种子打乱准考证号后再排：不同 seed 应可能产出不同图，
    # 但无论哪个 seed，流水都升序、可重放当前图。
    cands = [{"id": i, "name": f"C{i}", "ticket_no": f"T{2026000 + i}",
              "paper_id": 1 + (i % 3)} for i in range(12)]
    layouts = set()
    for seed in range(1, 9):
        assigns, unplaced, journal = place_candidates(5, 6, 2, cands, seed=seed)
        # 流水升序
        tickets = [e.ticket_no for e in journal]
        assert tickets == sorted(tickets)
        # 该段流水必须能重放出当前图
        assert replay_matches(5, 6, assigns, journal)
        layouts.add(tuple(sorted((a.candidate_id, a.row, a.col) for a in assigns)))
    assert len(layouts) > 1  # 打乱确实影响了落座，而非死按准考证号占座


def test_journal_replays_current_map():
    cands = [{"id": i, "name": f"C{i}", "ticket_no": f"T{100 + i}",
              "paper_id": 1 + (i % 2)} for i in range(6)]
    assigns, _, journal = place_candidates(4, 4, 2, cands, seed=7)
    grid = replay_journal(4, 4, journal)
    expect = {(a.row, a.col): a.candidate_id for a in assigns}
    assert grid == expect
    # 持久化形态（dict）同样可重放
    dicts = journal_to_dicts(journal)
    assert all(set(d) == {"seq", "ticket_no", "candidate_id", "row", "col"} for d in dicts)


def test_same_row_same_tail_forces_other_seat_or_unplaced():
    # 三人尾号都是 1，卷子互不相同、min_dist=1：本可随便坐，
    # 但同排尾号互斥，必须一排一个，且不得挤动先落座者。
    cands = [
        {"id": 1, "name": "A", "ticket_no": "T01", "paper_id": 1},
        {"id": 2, "name": "B", "ticket_no": "T11", "paper_id": 2},
        {"id": 3, "name": "C", "ticket_no": "T21", "paper_id": 3},
    ]
    assigns, unplaced, journal = place_candidates(3, 3, 1, cands, seed=3)
    assert len(assigns) + len(unplaced) == 3
    rows_used = [a.row for a in assigns]
    assert len(rows_used) == len(set(rows_used))  # 同排无重复尾号
    assert replay_matches(3, 3, assigns, journal)
    assert not find_violations(3, 3, 1, assigns)


def test_same_tail_overflow_goes_unplaced_without_displacing():
    # 3 排最多容纳 3 个同尾号，第 4、5 个只能进未排，先号格子不动。
    cands = [{"id": i, "name": f"C{i}", "ticket_no": f"T{i}1",
              "paper_id": i + 1} for i in range(5)]
    assigns, unplaced, journal = place_candidates(3, 3, 1, cands, seed=11)
    assert len(assigns) == 3
    assert len(unplaced) == 2
    seated_ids = {a.candidate_id for a in assigns}
    # 重放只增不改：每个流水格唯一，无抢占
    grid = replay_journal(3, 3, journal)
    assert len(grid) == len(seated_ids)
    # 未排者不出现在流水里
    assert not ({u["id"] for u in unplaced} & {e.candidate_id for e in journal})


def test_replay_detects_backward_displacement():
    # 回头挤位 = 两行流水争同一格，重放必须判失败。
    journal = [
        JournalEntry(seq=1, ticket_no="T001", candidate_id=1, row=0, col=0),
        JournalEntry(seq=2, ticket_no="T002", candidate_id=2, row=0, col=0),
    ]
    with pytest.raises(PlacementError):
        replay_journal(3, 3, journal)


def test_same_paper_not_adjacent_in_result():
    cands = [
        {"id": 1, "name": "A", "ticket_no": "T001", "paper_id": 1},
        {"id": 2, "name": "B", "ticket_no": "T002", "paper_id": 1},
        {"id": 3, "name": "C", "ticket_no": "T003", "paper_id": 2},
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


def test_same_tail_violation_is_not_worded_as_distance():
    # 同排同尾号是独立问题，说明不得写成间距不足。
    assigns = [
        SeatAssign(1, "A", "T2026001", 1, 0, 0),
        SeatAssign(2, "B", "T2026011", 2, 0, 2),
    ]
    viols = find_violations(2, 4, 2, assigns)
    tail_viols = [v for v in viols if v.kind == "same_ticket_tail"]
    assert len(tail_viols) == 1
    detail = tail_viols[0].detail
    assert "尾号" in detail
    assert "间距" not in detail and "距离" not in detail
