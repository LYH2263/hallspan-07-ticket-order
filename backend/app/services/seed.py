import random

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models.models import Candidate, Hall, PaperSet

# 固定种子，保证可复现：把准考证号在考生之间打乱，使名册 id 顺序不等于准考证升序。
_SHUFFLE_SEED = 2026

def seed_if_empty(db: Session) -> None:
    if (db.scalar(select(func.count()).select_from(Hall)) or 0) > 0:
        return
    hall = Hall(code="H101", name="一号考室", rows=5, cols=6, min_manhattan=2)
    db.add(hall); db.flush()
    papers = [("P-A", "语文 A 卷"), ("P-B", "语文 B 卷"), ("P-C", "语文 C 卷")]
    paper_ids = []
    for code, title in papers:
        p = PaperSet(code=code, title=title)
        db.add(p); db.flush()
        paper_ids.append(p.id)
    names = ["陈一", "李二", "张三", "赵四", "钱五", "孙六", "周七", "吴八", "郑九", "王十", "冯十一", "陈十二"]
    # 先打乱号再分配给考生：排座时流水按准考证升序追加，而非按名册 id 顺序。
    numbers = list(range(1, len(names) + 1))
    random.Random(_SHUFFLE_SEED).shuffle(numbers)
    for i, name in enumerate(names):
        db.add(Candidate(hall_id=hall.id, name=name, ticket_no=f"T{2026000 + numbers[i]}",
                         paper_id=paper_ids[i % len(paper_ids)]))
    db.commit()
