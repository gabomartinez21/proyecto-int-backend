from typing import Annotated

import pytest
from fastapi import Depends

from app.core.security import create_access_token
from app.deps import require_owner
from app.main import app
from app.models import User


# --- Registro ---

def test_register_ok(client):
    response = client.post(
        "/api/auth/register",
        json={"username": "maria", "full_name": "María Pérez", "password": "secreto123"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "maria"
    assert body["full_name"] == "María Pérez"
    assert set(body) == {"id", "username", "full_name", "role"}
    assert "hashed_password" not in body and "password" not in body


def test_register_duplicate_username_returns_409(client, register_user):
    register_user("maria")
    response = client.post(
        "/api/auth/register",
        json={"username": "maria", "full_name": "Otra María", "password": "secreto123"},
    )
    assert response.status_code == 409


def test_register_short_password_returns_422(client):
    response = client.post(
        "/api/auth/register",
        json={"username": "maria", "full_name": "María Pérez", "password": "corta"},
    )
    assert response.status_code == 422


def test_first_user_is_owner_and_next_is_employee(register_user):
    assert register_user("duena")["role"] == "owner"
    assert register_user("empleado")["role"] == "employee"


# --- Login ---

def test_login_ok_returns_token(client, register_user):
    register_user("maria", "secreto123")
    response = client.post("/api/auth/login", data={"username": "maria", "password": "secreto123"})
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["role"] == "owner"


def test_login_wrong_password_returns_401(client, register_user):
    register_user("maria", "secreto123")
    response = client.post("/api/auth/login", data={"username": "maria", "password": "incorrecta"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Usuario o contraseña incorrectos"


def test_login_unknown_user_returns_same_401(client):
    response = client.post("/api/auth/login", data={"username": "nadie", "password": "secreto123"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Usuario o contraseña incorrectos"


def test_login_inactive_user_returns_same_401(client, db, register_user):
    user_id = register_user("maria", "secreto123")["id"]
    db.get(User, user_id).is_active = False
    db.commit()
    response = client.post("/api/auth/login", data={"username": "maria", "password": "secreto123"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Usuario o contraseña incorrectos"


# --- /me ---

def test_me_with_valid_token(client, register_user, login):
    register_user("maria")
    token = login("maria")
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["username"] == "maria"


def test_me_without_token_returns_401(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_tampered_token_returns_401(client, register_user, login):
    register_user("maria")
    token = login("maria")
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}.{signature[:-4]}abcd"
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tampered}"})
    assert response.status_code == 401


def test_me_with_token_of_missing_user_returns_401(client):
    token = create_access_token(999)
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


# --- require_owner ---

@pytest.fixture()
def owner_only_route():
    path = "/__test__/owner-only"

    @app.get(path)
    def owner_only(user: Annotated[User, Depends(require_owner)]):
        return {"ok": True}

    yield path
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != path]


def test_require_owner(client, register_user, login, owner_only_route):
    register_user("duena")
    register_user("empleado")
    owner_token = login("duena")
    employee_token = login("empleado")

    response = client.get(owner_only_route, headers={"Authorization": f"Bearer {employee_token}"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Esta acción requiere permisos de dueño"

    response = client.get(owner_only_route, headers={"Authorization": f"Bearer {owner_token}"})
    assert response.status_code == 200
