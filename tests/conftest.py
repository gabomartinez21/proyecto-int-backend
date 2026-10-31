from collections.abc import Callable, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def db() -> Generator[Session, None, None]:
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    # Sin "with": no se ejecuta el lifespan, así que nunca se conecta a Postgres.
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def register_user(client: TestClient) -> Callable[..., dict]:
    def _register(username: str = "maria", password: str = "secreto123", full_name: str = "María Pérez"):
        response = client.post(
            "/api/auth/register",
            json={"username": username, "full_name": full_name, "password": password},
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _register


@pytest.fixture()
def login(client: TestClient) -> Callable[..., str]:
    def _login(username: str = "maria", password: str = "secreto123") -> str:
        response = client.post("/api/auth/login", data={"username": username, "password": password})
        assert response.status_code == 200, response.text
        return response.json()["access_token"]

    return _login
