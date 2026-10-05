"""Exam seating engine.

占座语义（只追加流水账）：
- 按准考证号升序逐人入场占座，每人只对当前图做一次决定，绝不回溯、
  绝不为给后号腾格而移动/改写先号；
- 每个成功占座按准考证升序产出一条只追加流水行（准考证、格子、次序）；
- 当前排座图必须能由该段流水按 seq 重放出来，对不上即失败；
- 硬约束：同一排上不得出现两个相同尾号；后号撞约束只能另排他格或进未排，
  不能挤动先号。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

@dataclass
class SeatAssign:
    candidate_id: int
    name: str
    ticket_no: str
    paper_id: int
    row: int
    col: int

# 只追加的占座流水行：准考证、格子、次序。按 seq 重放必得当前图。
@dataclass
class LedgerLine:
    seq: int
    candidate_id: int
    ticket_no: str
    row: int
    col: int

@dataclass
class Violation:
    kind: str
    a_id: int
    b_id: int
    detail: str

class SeatingError(ValueError):
    """整场拒绝 / 重放对不上；调用方必须整段不提交、回滚到保存前。"""

# 尾号取准考证号最后一位数字；非数字结尾则取最后一个字符（统一小写）。
_TAIL_RE = re.compile(r"(\d)\s*$")

def tail_digit(ticket_no: str) -> str:
    m = _TAIL_RE.search(ticket_no or "")
    if m:
        return m.group(1)
    return (ticket_no or "").strip()[-1:].lower()

def manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])

def neighbors4(r: int, c: int, rows: int, cols: int) -> list[tuple[int, int]]:
    out = []
    for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < rows and 0 <= nc < cols:
            out.append((nr, nc))
    return out

def validate_tickets(candidates: list[dict]) -> None:
    """号空或重复整场拒绝。在引擎入口统一校验。"""
    seen: set[str] = set()
    for cand in candidates:
        t = (cand.get("ticket_no") or "").strip()
        if not t:
            raise SeatingError(f"考生 id={cand.get('id')} 准考证号为空，整场拒绝排座")
        if t in seen:
            raise SeatingError(f"准考证号重复：{t}，整场拒绝排座")
        seen.add(t)

def place_candidates(rows: int, cols: int, min_dist: int, candidates: list[dict],
                     base_seq: int = 0) -> tuple[list[SeatAssign], list[dict], list[LedgerLine]]:
    """按准考证升序逐人占座（不回溯、不挤位）。

    约束：曼哈顿 >= min_dist；同 paper_id 不四邻相邻；同排不得有相同尾号。
    后号放不下就另排或进 unplaced，绝不动已占先号。
    返回 (assignments, unplaced, ledger)；ledger 按准考证升序、只追加，
    seq 从 base_seq+1 起连续递增。
    """
    validate_tickets(candidates)
    ordered = sorted(candidates, key=lambda x: (x["ticket_no"], x["id"]))
    occupied: dict[tuple[int, int], SeatAssign] = {}
    unplaced: list[dict] = []
    ledger: list[LedgerLine] = []
    seq = base_seq
    for cand in ordered:
        cand_tail = tail_digit(cand["ticket_no"])
        placed = False
        for r in range(rows):
            for c in range(cols):
                if (r, c) in occupied:
                    continue
                ok = True
                for pos, other in occupied.items():
                    if manhattan((r, c), pos) < min_dist:
                        ok = False
                        break
                    if other.paper_id == cand["paper_id"] and (r, c) in neighbors4(pos[0], pos[1], rows, cols):
                        ok = False
                        break
                if not ok:
                    continue
                for nr, nc in neighbors4(r, c, rows, cols):
                    if (nr, nc) in occupied and occupied[(nr, nc)].paper_id == cand["paper_id"]:
                        ok = False
                        break
                if not ok:
                    continue
                # 同一排不得有相同尾号的先到者；撞了只能换格，不能挤位。
                if any(o.row == r and tail_digit(o.ticket_no) == cand_tail for o in occupied.values()):
                    continue
                assign = SeatAssign(cand["id"], cand["name"], cand["ticket_no"], cand["paper_id"], r, c)
                occupied[(r, c)] = assign
                seq += 1
                ledger.append(LedgerLine(seq, cand["id"], cand["ticket_no"], r, c))
                placed = True
                break
            if placed:
                break
        if not placed:
            unplaced.append(cand)
    return list(occupied.values()), unplaced, ledger

def replay_ledger(ledger: list[LedgerLine], rows: int, cols: int) -> dict[tuple[int, int], int]:
    """按 seq 升序只追加重放：格 -> candidate_id。占同格/越界/重复号即失败（抛错）。"""
    grid: dict[tuple[int, int], int] = {}
    ticket_seen: set[str] = set()
    prev_seq = None
    for line in sorted(ledger, key=lambda l: l.seq):
        if prev_seq is not None and line.seq <= prev_seq:
            raise SeatingError(f"流水 seq 非严格递增：{line.seq}")
        prev_seq = line.seq
        if not (0 <= line.row < rows and 0 <= line.col < cols):
            raise SeatingError(f"流水重放越界：{line.ticket_no} -> ({line.row},{line.col})")
        if (line.row, line.col) in grid:
            raise SeatingError(f"流水重放格子冲突：({line.row},{line.col}) 已被占用")
        if line.ticket_no in ticket_seen:
            raise SeatingError(f"流水里同一准考证重复占座：{line.ticket_no}")
        ticket_seen.add(line.ticket_no)
        grid[(line.row, line.col)] = line.candidate_id
    return grid

def verify_plan(assigns: list[SeatAssign], ledger: list[LedgerLine],
                rows: int, cols: int) -> None:
    """当前图必须能由该段流水重放出来，对不上失败（抛 SeatingError）。"""
    if len(assigns) != len(ledger):
        raise SeatingError(
            f"图与流水条数不一致：图 {len(assigns)} 格，流水 {len(ledger)} 行")
    replayed = replay_ledger(ledger, rows, cols)
    actual = {(a.row, a.col): a.candidate_id for a in assigns}
    if replayed != actual:
        raise SeatingError("流水重放与当前排座图不一致")
    lt = {l.candidate_id: l.ticket_no for l in ledger}
    for a in assigns:
        if lt.get(a.candidate_id) != a.ticket_no:
            raise SeatingError(f"流水与图中考生准考证对不上：candidate_id={a.candidate_id}")
    # 同一 row 上不得出现两个相同尾号（硬约束兜底）。
    by_row: dict[int, set[str]] = {}
    for a in assigns:
        t = tail_digit(a.ticket_no)
        if t in by_row.setdefault(a.row, set()):
            raise SeatingError(f"第 {a.row} 排出现相同尾号 {t}，违反硬约束")
        by_row[a.row].add(t)

def find_violations(rows: int, cols: int, min_dist: int, assigns: list[SeatAssign]) -> list[Violation]:
    viols: list[Violation] = []
    for i, a in enumerate(assigns):
        for b in assigns[i + 1:]:
            d = manhattan((a.row, a.col), (b.row, b.col))
            if d < min_dist:
                viols.append(Violation("distance", a.candidate_id, b.candidate_id,
                                       f"曼哈顿距离 {d} < 最小要求 {min_dist}"))
            if a.paper_id == b.paper_id and (b.row, b.col) in neighbors4(a.row, a.col, rows, cols):
                viols.append(Violation("same_paper_adjacent", a.candidate_id, b.candidate_id,
                                       f"同试卷套 {a.paper_id} 四邻相邻"))
            # 同排同尾号是独立违规类型，说明不得写成“间距不足”。
            if a.row == b.row and tail_digit(a.ticket_no) == tail_digit(b.ticket_no):
                viols.append(Violation("same_tail_same_row", a.candidate_id, b.candidate_id,
                                       f"同一排（第 {a.row} 排）尾号 {tail_digit(a.ticket_no)} 重复："
                                       f"{a.ticket_no} 与 {b.ticket_no}，尾号必须错开（尾号撞号，非距离类违规）"))
    return viols

def ledger_to_dicts(ledger: list[LedgerLine]) -> list[dict]:
    return [asdict(l) for l in ledger]

def plan_to_dict(assigns: list[SeatAssign], unplaced: list[dict], viols: list[Violation],
                 rows: int, cols: int, ledger: list[LedgerLine] | None = None) -> dict:
    return {
        "rows": rows,
        "cols": cols,
        "assignments": [asdict(a) for a in assigns],
        "unplaced": unplaced,
        "violations": [asdict(v) for v in viols],
        "ledger": ledger_to_dicts(ledger or []),
        "stats": {
            "seated": len(assigns),
            "unplaced": len(unplaced),
            "violations": len(viols),
            "capacity": rows * cols,
            "ledger_lines": len(ledger or []),
        },
    }
