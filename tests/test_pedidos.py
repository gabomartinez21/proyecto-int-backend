from datetime import date

import pytest


@pytest.fixture()
def owner_headers(register_user, login):
    register_user("duena")
    return {"Authorization": f"Bearer {login('duena')}"}


@pytest.fixture()
def employee_headers(owner_headers, register_user, login):
    register_user("empleado")
    return {"Authorization": f"Bearer {login('empleado')}"}


@pytest.fixture()
def catalogo(client, owner_headers):
    """Harina con 10 kg de stock y una torta que usa 2 kg por unidad."""
    harina = client.post(
        "/api/insumos", json={"name": "Harina", "unit": "kg", "minimum": 1, "cost": 4}, headers=owner_headers
    ).json()
    client.post(
        f"/api/insumos/{harina['id']}/stock",
        json={"kind": "entrada", "quantity": 10, "note": "Compra inicial"},
        headers=owner_headers,
    )
    torta = client.post(
        "/api/productos", json={"name": "Torta", "category": "Postres", "price": 50}, headers=owner_headers
    ).json()
    client.put(
        f"/api/productos/{torta['id']}/receta",
        json={"recipe": [{"ingredientId": harina["id"], "quantity": 2}]},
        headers=owner_headers,
    )
    return {"harina": harina, "torta": torta}


def body_pedido(items, channel="WhatsApp"):
    return {"customer": "Ana Torres", "date": date.today().isoformat(), "channel": channel, "items": items}


def crear_pedido(client, headers, product_id, quantity=1):
    res = client.post("/api/pedidos", json=body_pedido([{"productId": product_id, "quantity": quantity}]), headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def cambiar_estado(client, headers, pedido_id, estado):
    return client.put(f"/api/pedidos/{pedido_id}/estado", json={"status": estado}, headers=headers)


def stock_harina(client, headers, harina_id):
    return next(i for i in client.get("/api/insumos", headers=headers).json() if i["id"] == harina_id)["stock"]


def test_crear_pedido_copia_datos_del_producto(client, employee_headers, catalogo, owner_headers):
    torta = catalogo["torta"]
    # productId como string numérico, como lo puede mandar el frontend
    pedido = crear_pedido(client, employee_headers, str(torta["id"]), quantity=2)

    assert pedido["number"] == 1
    assert pedido["status"] == "Pendiente"
    assert pedido["items"] == [
        {
            "productId": torta["id"],
            "name": "Torta",
            "price": 50.0,
            "quantity": 2,
            "recipe": [{"ingredientId": catalogo["harina"]["id"], "quantity": 2.0}],
        }
    ]

    # Cambiar el producto después no altera el pedido
    client.put(f"/api/productos/{torta['id']}", json={"name": "Torta XL", "category": "Postres", "price": 99}, headers=owner_headers)
    listado = client.get("/api/pedidos", headers=employee_headers).json()
    assert listado == [pedido]


def test_crear_pedido_validaciones(client, owner_headers, catalogo):
    tid = catalogo["torta"]["id"]

    res = client.post("/api/pedidos", json=body_pedido([]), headers=owner_headers)
    assert res.status_code == 400
    assert res.json()["detail"] == "Agrega al menos un producto."

    res = client.post("/api/pedidos", json=body_pedido([{"productId": tid, "quantity": 1}], channel="Fax"), headers=owner_headers)
    assert res.status_code == 400
    assert res.json()["detail"] == "Canal inválido."

    res = client.post("/api/pedidos", json=body_pedido([{"productId": tid, "quantity": 0}]), headers=owner_headers)
    assert res.status_code == 422

    res = client.post("/api/pedidos", json=body_pedido([{"productId": 999, "quantity": 1}]), headers=owner_headers)
    assert res.status_code == 400
    assert res.json()["detail"] == "Cada producto debe tener una receta definida."

    sin_receta = client.post(
        "/api/productos", json={"name": "Vacío", "category": "Otros", "price": 1}, headers=owner_headers
    ).json()
    res = client.post("/api/pedidos", json=body_pedido([{"productId": sin_receta["id"], "quantity": 1}]), headers=owner_headers)
    assert res.status_code == 400
    assert res.json()["detail"] == "Cada producto debe tener una receta definida."


def test_transiciones_no_permitidas(client, employee_headers, catalogo):
    pedido = crear_pedido(client, employee_headers, catalogo["torta"]["id"])

    res = cambiar_estado(client, employee_headers, pedido["id"], "Entregado")
    assert res.status_code == 400
    assert res.json()["detail"] == "Cambio de estado no permitido."

    assert cambiar_estado(client, employee_headers, pedido["id"], "Cancelado").status_code == 200
    res = cambiar_estado(client, employee_headers, pedido["id"], "Confirmado")
    assert res.json()["detail"] == "Cambio de estado no permitido."

    assert cambiar_estado(client, employee_headers, pedido["id"], "Inventado").status_code == 400
    assert cambiar_estado(client, employee_headers, 999, "Confirmado").status_code == 404


def test_confirmar_respeta_lo_reservado_por_otros_pedidos(client, employee_headers, catalogo):
    tid = catalogo["torta"]["id"]
    p1 = crear_pedido(client, employee_headers, tid, quantity=3)  # 6 kg
    p2 = crear_pedido(client, employee_headers, tid, quantity=3)  # 6 kg

    res = cambiar_estado(client, employee_headers, p1["id"], "Confirmado")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "Confirmado"

    res = cambiar_estado(client, employee_headers, p2["id"], "Confirmado")
    assert res.status_code == 400
    assert res.json()["detail"] == "Stock insuficiente: Harina. Revisa la lista de compras."

    # Al cancelar p1 se libera la reserva
    cambiar_estado(client, employee_headers, p1["id"], "Cancelado")
    assert cambiar_estado(client, employee_headers, p2["id"], "Confirmado").status_code == 200


def test_entregar_descuenta_stock_y_registra_movimiento(client, employee_headers, owner_headers, catalogo):
    harina_id = catalogo["harina"]["id"]
    pedido = crear_pedido(client, employee_headers, catalogo["torta"]["id"], quantity=2)
    cambiar_estado(client, employee_headers, pedido["id"], "Confirmado")

    res = cambiar_estado(client, employee_headers, pedido["id"], "Entregado")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "Entregado"
    assert stock_harina(client, owner_headers, harina_id) == 6.0

    mov = client.get("/api/insumos/movimientos", headers=owner_headers).json()[0]
    assert mov["insumo_id"] == harina_id
    assert mov["quantity"] == -4.0
    assert mov["note"] == f"Entrega de pedido #{pedido['number']}"

    # Un pedido entregado ya no reserva stock
    res = client.post(
        f"/api/insumos/{harina_id}/stock",
        json={"kind": "salida", "quantity": 6, "note": "Merma"},
        headers=owner_headers,
    )
    assert res.status_code == 200


def test_entregar_sin_stock_no_modifica_nada(client, employee_headers, owner_headers, catalogo, db):
    from app.models import Insumo

    harina_id = catalogo["harina"]["id"]
    pedido = crear_pedido(client, employee_headers, catalogo["torta"]["id"], quantity=4)  # 8 kg
    cambiar_estado(client, employee_headers, pedido["id"], "Confirmado")

    # Simula un stock que bajó por fuera del flujo normal
    db.get(Insumo, harina_id).stock = 5.0
    db.commit()

    res = cambiar_estado(client, employee_headers, pedido["id"], "Entregado")
    assert res.status_code == 400
    assert res.json()["detail"] == "Stock insuficiente."
    assert stock_harina(client, owner_headers, harina_id) == 5.0
    estado = next(p for p in client.get("/api/pedidos", headers=owner_headers).json() if p["id"] == pedido["id"])
    assert estado["status"] == "Confirmado"
    notas = [m["note"] for m in client.get("/api/insumos/movimientos", headers=owner_headers).json()]
    assert not any(n.startswith("Entrega de pedido") for n in notas)


def test_no_se_puede_retirar_stock_reservado(client, employee_headers, owner_headers, catalogo):
    harina_id = catalogo["harina"]["id"]
    pedido = crear_pedido(client, employee_headers, catalogo["torta"]["id"], quantity=3)  # 6 kg
    cambiar_estado(client, employee_headers, pedido["id"], "Confirmado")

    url = f"/api/insumos/{harina_id}/stock"
    res = client.post(url, json={"kind": "salida", "quantity": 5, "note": "Merma"}, headers=owner_headers)
    assert res.status_code == 400
    assert res.json()["detail"] == "No puedes retirar stock reservado para pedidos."

    res = client.post(url, json={"kind": "salida", "quantity": 4, "note": "Merma"}, headers=owner_headers)
    assert res.status_code == 200
    assert res.json()["stock"] == 6.0
