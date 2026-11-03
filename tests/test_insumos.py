def test_crear_insumo_stock_inicial_cero(client, register_user, login):
    register_user("duena")
    token = login("duena")

    res = client.post(
        "/api/insumos",
        json={"name": "Harina de trigo", "unit": "kg", "minimum": 3, "cost": 5.5},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "Harina de trigo"
    assert body["stock"] == 0.0


def test_crear_insumo_duplicado_retorna_409(client, register_user, login):
    register_user("duena")
    token = login("duena")
    headers = {"Authorization": f"Bearer {token}"}

    client.post("/api/insumos", json={"name": "Harina", "unit": "kg", "minimum": 2, "cost": 5}, headers=headers)
    res = client.post("/api/insumos", json={"name": "harina", "unit": "kg", "minimum": 1, "cost": 4}, headers=headers)
    assert res.status_code == 409


def test_empleado_no_puede_crear_insumo_retorna_403(client, register_user, login):
    register_user("duena")
    register_user("empleado")
    emp_token = login("empleado")

    res = client.post(
        "/api/insumos",
        json={"name": "Azúcar", "unit": "kg", "minimum": 2, "cost": 4.5},
        headers={"Authorization": f"Bearer {emp_token}"},
    )
    assert res.status_code == 403


def test_actualizar_stock_entrada_y_salida(client, register_user, login):
    register_user("duena")
    token = login("duena")
    headers = {"Authorization": f"Bearer {token}"}

    insumo = client.post(
        "/api/insumos",
        json={"name": "Chocolate", "unit": "kg", "minimum": 1, "cost": 32},
        headers=headers,
    ).json()

    # Entrada de 5 kg
    res1 = client.post(
        f"/api/insumos/{insumo['id']}/stock",
        json={"kind": "entrada", "quantity": 5, "note": "Compra semanal"},
        headers=headers,
    )
    assert res1.status_code == 200
    assert res1.json()["stock"] == 5.0

    # Salida mayor al stock disponible debe fallar con 400
    res_fail = client.post(
        f"/api/insumos/{insumo['id']}/stock",
        json={"kind": "salida", "quantity": 10, "note": "Merma excesiva"},
        headers=headers,
    )
    assert res_fail.status_code == 400