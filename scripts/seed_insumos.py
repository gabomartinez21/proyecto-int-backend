import json, sys, urllib.error, urllib.parse, urllib.request

BASE = "http://localhost:8000"
USER, PASS = "admin", "Barbarita2026!"   # debe ser el usuario dueño (owner)

# nombre, unidad, mínimo, costo, stock inicial
INSUMOS = [
    ("Harina", "kg", 5, 3.80, 20),
    ("Azúcar", "kg", 4, 4.20, 15),
    ("Huevos", "unidad", 30, 0.55, 120),
    ("Mantequilla", "kg", 2, 28.00, 6),
    ("Leche", "L", 5, 4.50, 20),
    ("Chocolate de cobertura", "kg", 2, 32.00, 1.5),
    ("Arroz", "kg", 10, 4.50, 40),
    ("Pollo", "kg", 8, 11.50, 25),
    ("Aceite", "L", 3, 9.80, 8),
    ("Papa", "kg", 10, 2.80, 30),
]

def call(method, path, body=None, token=None, form=False):
    headers, data = {}, None
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

status, data = call("POST", "/api/auth/login", {"username": USER, "password": PASS}, form=True)
if status != 200:
    sys.exit(f"Login falló ({status}): {data}")
token = data["access_token"]

for name, unit, minimum, cost, stock in INSUMOS:
    status, ins = call("POST", "/api/insumos",
                       {"name": name, "unit": unit, "minimum": minimum, "cost": cost}, token)
    if status == 409:
        print(f"= {name}: ya existe, se omite")
        continue
    if status != 201:
        print(f"! {name}: error {status} {ins}")
        continue
    status, _ = call("POST", f"/api/insumos/{ins['id']}/stock",
                     {"kind": "entrada", "quantity": stock, "note": "Stock inicial"}, token)
    print(f"+ {name}: {stock} {unit}" if status == 200 else f"! {name}: el stock falló ({status})")