import pytest


@pytest.fixture()
def owner_headers(register_user, login):
    register_user("duena")
    return {"Authorization": f"Bearer {login('duena')}"}


@pytest.fixture()
def employee_headers(owner_headers, register_user, login):
    register_user("empleado")
    return {"Authorization": f"Bearer {login('empleado')}"}


def crear_insumo(client, headers, name="Harina"):
    res = client.post("/api/insumos", json={"name": name, "unit": "kg", "minimum": 1, "cost": 5}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def crear_producto(client, headers, name="Torta de chocolate", **extra):
    body = {"name": name, "category": "Postres", "price": 65, **extra}
    return client.post("/api/productos", json=body, headers=headers)


def test_crear_producto_con_receta_vacia(client, owner_headers):
    res = crear_producto(client, owner_headers, name="  Torta de chocolate  ", description="Rica")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "Torta de chocolate"
    assert body["category"] == "Postres"
    assert body["price"] == 65.0
    assert body["description"] == "Rica"
    assert body["recipe"] == []


def test_listar_productos_ordenados_por_nombre(client, owner_headers, employee_headers):
    crear_producto(client, owner_headers, name="Tarta")
    crear_producto(client, owner_headers, name="Alfajor")
    res = client.get("/api/productos", headers=employee_headers)
    assert res.status_code == 200
    assert [p["name"] for p in res.json()] == ["Alfajor", "Tarta"]


def test_listar_productos_requiere_autenticacion(client):
    assert client.get("/api/productos").status_code == 401


def test_producto_duplicado_sin_distinguir_mayusculas_retorna_409(client, owner_headers):
    crear_producto(client, owner_headers, name="Brownie")
    res = crear_producto(client, owner_headers, name="BROWNIE")
    assert res.status_code == 409
    assert res.json()["detail"] == "Ya existe un producto con ese nombre."


def test_empleado_no_puede_crear_producto(client, employee_headers):
    assert crear_producto(client, employee_headers).status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {"name": "   ", "category": "Postres", "price": 10},
        {"name": "x" * 151, "category": "Postres", "price": 10},
        {"name": "Torta", "category": "Bebidas", "price": 10},
        {"name": "Torta", "category": "Postres", "price": -1},
        {"name": "Torta", "category": "Postres", "price": 2e9},
        {"name": "Torta", "category": "Postres", "price": 10, "description": "x" * 501},
    ],
)
def test_validaciones_de_producto(client, owner_headers, body):
    assert client.post("/api/productos", json=body, headers=owner_headers).status_code == 422


def test_actualizar_producto(client, owner_headers):
    pid = crear_producto(client, owner_headers).json()["id"]
    res = client.put(
        f"/api/productos/{pid}",
        json={"name": "Torta de chocolate", "category": "Eventos", "price": 80, "description": "Grande"},
        headers=owner_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["category"] == "Eventos"
    assert res.json()["price"] == 80.0


def test_actualizar_producto_inexistente_y_nombre_duplicado(client, owner_headers):
    crear_producto(client, owner_headers, name="Brownie")
    pid = crear_producto(client, owner_headers, name="Alfajor").json()["id"]
    body = {"name": "brownie", "category": "Postres", "price": 5}

    res = client.put(f"/api/productos/{pid}", json=body, headers=owner_headers)
    assert res.status_code == 409

    res = client.put("/api/productos/999", json=body, headers=owner_headers)
    assert res.status_code == 404
    assert res.json()["detail"] == "Producto inexistente."


def test_reemplazar_receta(client, owner_headers):
    harina = crear_insumo(client, owner_headers, "Harina")
    huevos = crear_insumo(client, owner_headers, "Huevos")
    pid = crear_producto(client, owner_headers).json()["id"]

    res = client.put(
        f"/api/productos/{pid}/receta",
        json={"recipe": [{"ingredientId": harina["id"], "quantity": 0.4}, {"ingredientId": huevos["id"], "quantity": 3}]},
        headers=owner_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["recipe"] == [
        {"ingredientId": harina["id"], "quantity": 0.4},
        {"ingredientId": huevos["id"], "quantity": 3.0},
    ]

    # Reemplazo completo, incluyendo un insumo que ya estaba
    res = client.put(
        f"/api/productos/{pid}/receta",
        json={"recipe": [{"ingredientId": huevos["id"], "quantity": 2}]},
        headers=owner_headers,
    )
    assert res.json()["recipe"] == [{"ingredientId": huevos["id"], "quantity": 2.0}]

    # Lista vacía permitida
    res = client.put(f"/api/productos/{pid}/receta", json={"recipe": []}, headers=owner_headers)
    assert res.status_code == 200
    assert res.json()["recipe"] == []


def test_receta_validaciones(client, owner_headers, employee_headers):
    harina = crear_insumo(client, owner_headers)
    pid = crear_producto(client, owner_headers).json()["id"]
    url = f"/api/productos/{pid}/receta"

    res = client.put(url, json={"recipe": [{"ingredientId": 999, "quantity": 1}]}, headers=owner_headers)
    assert res.status_code == 400
    assert res.json()["detail"] == "Primero debes registrar el insumo."

    dup = [{"ingredientId": harina["id"], "quantity": 1}, {"ingredientId": harina["id"], "quantity": 2}]
    res = client.put(url, json={"recipe": dup}, headers=owner_headers)
    assert res.status_code == 400
    assert res.json()["detail"] == "No repitas un ingrediente."

    res = client.put(url, json={"recipe": [{"ingredientId": harina["id"], "quantity": 0}]}, headers=owner_headers)
    assert res.status_code == 422

    res = client.put("/api/productos/999/receta", json={"recipe": []}, headers=owner_headers)
    assert res.status_code == 404

    res = client.put(url, json={"recipe": []}, headers=employee_headers)
    assert res.status_code == 403
