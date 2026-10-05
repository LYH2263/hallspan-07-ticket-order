import random

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models.models import Candidate, Hall, PaperSet

# 固定种子：可复现地把准考证号打乱后再入库/再排，
# 保证"先入库者"不等于"小准考证号者"，排座不得只按号序占座。
SEED = 20261004


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
    tickets = [f"T{2026001 + i}" for i in range(len(names))]
    random.Random(SEED).shuffle(tickets)  # 种子打乱准考证号后再排
    for i, name in enumerate(names):
        db.add(Candidate(hall_id=hall.id, name=name, ticket_no=tickets[i],
                         paper_id=paper_ids[i % len(papers)]))
    db.commit()
