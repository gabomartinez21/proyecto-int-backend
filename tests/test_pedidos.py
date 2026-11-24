from datetime import date

import pytest


@pytest.fixture()
def owner_headers(register_user, login):
    register_user("duena")
    OWNER["h"] = {"Authorization": f"Bearer {login('duena')}"}
    return OWNER["h"]


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


OWNER = {}


def cambiar_estado(client, headers, pedido_id, estado):
    if estado == "Confirmado":
        # HU024: solo la dueña valida el pago; con stock suficiente se confirma y reserva.
        return client.patch(
            f"/api/pedidos/{pedido_id}/validar-pago", data={"codigo_operacion": "OP-123"}, headers=OWNER["h"]
        )
    return client.put(
        f"/api/pedidos/{pedido_id}/estado", json={"status": estado, "receiver": "Ana Torres"}, headers=headers
    )


def stock_harina(client, headers, harina_id):
    return next(i for i in client.get("/api/insumos", headers=headers).json() if i["id"] == harina_id)["stock"]


def test_crear_pedido_copia_datos_del_producto(client, employee_headers, catalogo, owner_headers):
    torta = catalogo["torta"]
    # productId como string numérico, como lo puede mandar el frontend
    pedido = crear_pedido(client, employee_headers, str(torta["id"]), quantity=2)

    assert pedido["number"] == 1
    assert pedido["status"] == "Pendiente de pago"
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
    assert res.status_code == 400

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
    assert res.status_code == 409
    assert res.json()["detail"]["pagoValidado"] is True
    assert res.json()["detail"]["faltantes"][0]["nombre"] == "Harina"

    # Al cancelar p1 se libera la reserva
    cambiar_estado(client, employee_headers, p1["id"], "Cancelado")
    assert cambiar_estado(client, employee_headers, p2["id"], "Confirmado").status_code == 200


def test_preparar_descuenta_stock_y_registra_movimiento(client, employee_headers, owner_headers, catalogo):
    harina_id = catalogo["harina"]["id"]
    pedido = crear_pedido(client, employee_headers, catalogo["torta"]["id"], quantity=2)
    cambiar_estado(client, employee_headers, pedido["id"], "Confirmado")

    res = cambiar_estado(client, employee_headers, pedido["id"], "En preparación")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "En preparación"
    assert stock_harina(client, owner_headers, harina_id) == 6.0

    mov = client.get("/api/insumos/movimientos", headers=owner_headers).json()[0]
    assert mov["insumo_id"] == harina_id
    assert mov["quantity"] == -4.0
    assert mov["note"] == f"Preparación de pedido #{pedido['number']}"

    # Un pedido en preparación ya no reserva stock
    res = client.post(
        f"/api/insumos/{harina_id}/stock",
        json={"kind": "salida", "quantity": 6, "note": "Merma"},
        headers=owner_headers,
    )
    assert res.status_code == 200


def test_preparar_sin_stock_no_modifica_nada(client, employee_headers, owner_headers, catalogo, db):
    from app.models import Insumo

    harina_id = catalogo["harina"]["id"]
    pedido = crear_pedido(client, employee_headers, catalogo["torta"]["id"], quantity=4)  # 8 kg
    cambiar_estado(client, employee_headers, pedido["id"], "Confirmado")

    # Simula un stock que bajó por fuera del flujo normal
    db.get(Insumo, harina_id).stock = 5.0
    db.commit()

    res = cambiar_estado(client, employee_headers, pedido["id"], "En preparación")
    assert res.status_code == 400
    assert res.json()["detail"] == "Stock insuficiente."
    assert stock_harina(client, owner_headers, harina_id) == 5.0
    estado = next(p for p in client.get("/api/pedidos", headers=owner_headers).json() if p["id"] == pedido["id"])
    assert estado["status"] == "Confirmado"
    notas = [m["note"] for m in client.get("/api/insumos/movimientos", headers=owner_headers).json()]
    assert not any(n.startswith("Preparación de pedido") for n in notas)


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


# --- Sprint 3: edición de pedidos (HU013) y validación de stock (HU015/HU017) ---


def editar(client, headers, pedido_id, product_id, quantity, **extra):
    body = body_pedido([{"productId": product_id, "quantity": quantity}]) | extra
    return client.put(f"/api/pedidos/{pedido_id}", json=body, headers=headers)


def test_editar_pedido_pendiente(client, employee_headers, catalogo):
    pedido = crear_pedido(client, employee_headers, catalogo["torta"]["id"])
    res = editar(client, employee_headers, pedido["id"], catalogo["torta"]["id"], 3, customer="  Luis Pérez ", notes=" sin azúcar ")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["id"] == pedido["id"]
    assert data["customer"] == "Luis Pérez"
    assert data["notes"] == "sin azúcar"
    assert [i["quantity"] for i in data["items"]] == [3]


def test_editar_pedido_confirmado_valida_stock(client, employee_headers, catalogo):
    tid = catalogo["torta"]["id"]
    pedido = crear_pedido(client, employee_headers, tid, quantity=2)  # 4 kg
    cambiar_estado(client, employee_headers, pedido["id"], "Confirmado")

    assert editar(client, employee_headers, pedido["id"], tid, 5).status_code == 200  # 10 kg: alcanza
    res = editar(client, employee_headers, pedido["id"], tid, 6)  # 12 kg: no alcanza
    assert res.status_code == 400
    assert "Harina" in res.json()["detail"]
    actual = next(p for p in client.get("/api/pedidos", headers=employee_headers).json() if p["id"] == pedido["id"])
    assert actual["items"][0]["quantity"] == 5


def test_no_se_edita_pedido_entregado_o_cancelado(client, employee_headers, catalogo):
    tid = catalogo["torta"]["id"]
    pedido = crear_pedido(client, employee_headers, tid)
    cambiar_estado(client, employee_headers, pedido["id"], "Cancelado")
    assert editar(client, employee_headers, pedido["id"], tid, 1).status_code == 400


def test_editar_pedido_inexistente(client, employee_headers, catalogo):
    assert editar(client, employee_headers, 9999, catalogo["torta"]["id"], 1).status_code == 404


def test_editar_conserva_fecha_pasada_pero_no_acepta_una_nueva(client, employee_headers, catalogo, db):
    from app.models import Pedido

    tid = catalogo["torta"]["id"]
    pedido = crear_pedido(client, employee_headers, tid)
    db.get(Pedido, int(pedido["id"])).date = "2020-01-01"
    db.commit()

    assert editar(client, employee_headers, pedido["id"], tid, 2, date="2020-01-01").status_code == 200
    assert editar(client, employee_headers, pedido["id"], tid, 2, date="2020-01-02").status_code == 400


def test_validar_stock_reporta_faltantes(client, employee_headers, catalogo):
    tid = catalogo["torta"]["id"]
    ok = client.post("/api/pedidos/validar-stock", json=body_pedido([{"productId": tid, "quantity": 5}]), headers=employee_headers)
    assert ok.status_code == 200

    res = client.post("/api/pedidos/validar-stock", json=body_pedido([{"productId": tid, "quantity": 6}]), headers=employee_headers)
    assert res.status_code == 409
    faltante = res.json()["detail"]["faltantes"][0]
    assert (faltante["requerido"], faltante["disponible"], faltante["faltante"]) == (12, 10, 2)


def test_flujo_completo_con_pago_validado(client, employee_headers, owner_headers, catalogo):
    pedido = crear_pedido(client, employee_headers, catalogo["torta"]["id"])
    assert pedido["paymentStatus"] == "Pendiente"
    # Empleado no puede validar pago
    res = client.patch(f"/api/pedidos/{pedido['id']}/validar-pago", data={"codigo_operacion": "X1"}, headers=employee_headers)
    assert res.status_code == 403
    # Sin evidencia
    res = client.patch(f"/api/pedidos/{pedido['id']}/validar-pago", headers=owner_headers)
    assert res.status_code == 400
    # No se confirma sin pago validado
    res = client.put(f"/api/pedidos/{pedido['id']}/estado", json={"status": "Confirmado"}, headers=employee_headers)
    assert res.status_code == 400
    res = client.patch(f"/api/pedidos/{pedido['id']}/validar-pago", data={"codigo_operacion": "OP-9"}, headers=owner_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "Confirmado" and body["paymentStatus"] == "Validado"
    assert body["paymentValidatedBy"] == "duena" and body["operationCode"] == "OP-9"
    for estado in ("En preparación", "Listo para entrega"):
        res = client.put(f"/api/pedidos/{pedido['id']}/estado", json={"status": estado}, headers=employee_headers)
        assert res.status_code == 200, res.text
    # Entregado exige receptor
    res = client.put(f"/api/pedidos/{pedido['id']}/estado", json={"status": "Entregado"}, headers=employee_headers)
    assert res.status_code == 400
    res = client.put(f"/api/pedidos/{pedido['id']}/estado", json={"status": "Entregado", "receiver": "Ana"}, headers=employee_headers)
    assert res.status_code == 200 and res.json()["deliveryReceiver"] == "Ana"
    # Repetir no duplica movimientos
    assert client.put(f"/api/pedidos/{pedido['id']}/estado", json={"status": "En preparación"}, headers=employee_headers).status_code == 400


def test_validar_pago_comprobante_invalido(client, employee_headers, owner_headers, catalogo, tmp_path, monkeypatch):
    from app.routers import pedidos as router_pedidos

    monkeypatch.setattr(router_pedidos, "COMPROBANTES_DIR", tmp_path)
    pedido = crear_pedido(client, employee_headers, catalogo["torta"]["id"])
    url = f"/api/pedidos/{pedido['id']}/validar-pago"
    res = client.patch(url, files={"comprobante": ("a.pdf", b"%PDF", "application/pdf")}, headers=owner_headers)
    assert res.status_code == 400
    grande = b"\x89PNG" + b"0" * (5 * 1024 * 1024)
    res = client.patch(url, files={"comprobante": ("a.png", grande, "image/png")}, headers=owner_headers)
    assert res.status_code == 400
    res = client.patch(url, files={"comprobante": ("a.png", b"\x89PNG....", "image/png")}, headers=owner_headers)
    assert res.status_code == 200, res.text
    assert res.json()["paymentProofUrl"].startswith("uploads/comprobantes/")


def test_validar_pago_sin_stock_deja_pago_validado(client, employee_headers, owner_headers, catalogo):
    pedido = crear_pedido(client, employee_headers, catalogo["torta"]["id"], quantity=6)  # 12 kg > 10
    res = client.patch(f"/api/pedidos/{pedido['id']}/validar-pago", data={"codigo_operacion": "OP-1"}, headers=owner_headers)
    assert res.status_code == 409
    assert res.json()["detail"]["faltantes"][0]["faltante"] == 2.0
    actual = next(p for p in client.get("/api/pedidos", headers=owner_headers).json() if p["id"] == pedido["id"])
    assert actual["status"] == "Pendiente de pago" and actual["paymentStatus"] == "Validado"
