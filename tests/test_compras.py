from datetime import date, timedelta

from tests.test_pedidos import cambiar_estado, catalogo, crear_pedido, employee_headers, owner_headers  # noqa: F401


def test_lista_semanal_calcula_faltantes_y_presupuesto(client, employee_headers, owner_headers, catalogo):
    pedido = crear_pedido(client, employee_headers, catalogo["torta"]["id"], quantity=6)  # 12 kg, hay 10
    # Pago validado pero sin stock suficiente: sigue pendiente y genera necesidad de compra (HU021).
    pago = client.patch(
        f"/api/pedidos/{pedido['id']}/validar-pago", data={"codigo_operacion": "OP-1"}, headers=owner_headers
    )
    assert pago.status_code == 409
    res = client.get("/api/compras/lista-semanal", headers=employee_headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["fecha_inicio"] == date.today().isoformat()
    assert data["fecha_fin"] == (date.today() + timedelta(days=6)).isoformat()
    [item] = data["items"]
    assert (item["required"], item["available"], item["buy"], item["estimatedCost"]) == (12, 10, 2, 8)
    assert data["presupuesto_estimado"] == 8


def test_lista_semanal_rechaza_fechas_invalidas(client, employee_headers):
    assert client.get("/api/compras/lista-semanal?fecha_inicio=mañana", headers=employee_headers).status_code == 422
    res = client.get("/api/compras/lista-semanal?fecha_inicio=2030-01-10&fecha_fin=2030-01-01", headers=employee_headers)
    assert res.status_code == 400


def test_confirmar_item_suma_stock_solo_duena(client, owner_headers, employee_headers, catalogo):
    harina_id = catalogo["harina"]["id"]
    body = {"insumo_id": harina_id, "quantity": 5}
    assert client.post("/api/compras/confirmar-item", json=body, headers=employee_headers).status_code == 403
    res = client.post("/api/compras/confirmar-item", json=body, headers=owner_headers)
    assert res.status_code == 200, res.text
    assert res.json()["stock"] == 15
    assert client.post("/api/compras/confirmar-item", json={"insumo_id": 9999, "quantity": 1}, headers=owner_headers).status_code == 404
