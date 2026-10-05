"""SQLite 内存库 + 依赖注入覆盖；不触发 app 的 Postgres lifespan。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite://")  # 必须在导入 app 之前

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app  # noqa: F401  (导入即注册路由与模型)


@pytest.fixture
def harness():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)  # 不使用 with，避免触发连 Postgres 的 lifespan
    try:
        yield client, TestingSession
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
