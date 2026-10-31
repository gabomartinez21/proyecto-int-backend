# Consolidador de Pedidos e Insumos — Backend

API interna para un negocio de comida por encargo. Stack: **Python 3.12, FastAPI, SQLAlchemy 2.0, PostgreSQL 16, JWT**.

Por ahora incluye solo el esqueleto y la autenticación (registro, login y usuario actual).

## Requisitos

- Python 3.12
- Docker + Docker Compose

## Cómo correr el proyecto

```bash
# 1. Entorno virtual
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Dependencias
pip install -r requirements.txt

# 3. Variables de entorno
cp .env.example .env               # cambia SECRET_KEY

# 4. Base de datos (PostgreSQL 16)
docker compose up -d

# 5. API
uvicorn app.main:app --reload
```

Abre la documentación interactiva en http://localhost:8000/docs.

> **Puerto 5432 ocupado** (por ejemplo, si tienes otro Postgres corriendo): en `.env` cambia
> `POSTGRES_PORT` y el puerto dentro de `DATABASE_URL` al mismo valor (ej. `5434`) y vuelve a correr `docker compose up -d`.

### Probar la autenticación desde /docs

1. `POST /api/auth/register` crea un usuario. **El primer usuario registrado queda como dueño (`owner`)**; los siguientes, como `employee`.
2. Pulsa **Authorize** e ingresa usuario y contraseña. Swagger llama a `POST /api/auth/login` y guarda el token.
3. `GET /api/auth/me` devuelve el usuario autenticado.

## Tests

Los tests usan SQLite en memoria, así que **no necesitan Postgres ni Docker**:

```bash
pytest
pytest -v                          # detalle por test
```

## Estructura

```
app/
  main.py            # instancia FastAPI, CORS, routers, /health
  database.py        # engine, SessionLocal, Base, get_db
  models.py          # modelos SQLAlchemy (por ahora solo User)
  schemas.py         # schemas Pydantic (por ahora solo auth)
  deps.py            # get_current_user, require_owner
  core/config.py     # configuración (lee .env)
  core/security.py   # hash de contraseñas y JWT
  routers/auth.py    # /api/auth/*
tests/
```

## Variables de entorno

| Variable | Descripción |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://usuario:clave@host:puerto/bd` |
| `SECRET_KEY` | Clave para firmar los JWT. Usa una larga y aleatoria. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Duración del token (por defecto 60). |
| `CORS_ORIGINS` | Lista JSON de orígenes permitidos (por defecto `http://localhost:5173` y `http://localhost:3000`). |
| `POSTGRES_PORT` | Puerto del host para el contenedor de Postgres (solo lo usa docker compose). |

## Cómo agregar un módulo nuevo

Ejemplo: módulo de *insumos*.

1. **Modelo**: agrega la clase en `app/models.py` heredando de `Base` (estilo `Mapped` / `mapped_column`).
2. **Schemas**: agrega los schemas Pydantic de entrada y salida en `app/schemas.py` (`InsumoCreate`, `InsumoOut`...).
3. **Router**: crea `app/routers/insumos.py` con `router = APIRouter(prefix="/api/insumos", tags=["insumos"])`.
   - Protege los endpoints con `Depends(get_current_user)` o, si solo el dueño puede usarlos (stock, recetas), con `Depends(require_owner)`.
   - Obtén la sesión de BD con `db: Annotated[Session, Depends(get_db)]`.
   - Si la lógica crece, sácala a una carpeta `app/services/` y deja el router delgado.
4. **Registro**: en `app/main.py`, importa el router y añade `app.include_router(insumos.router)`.
5. **Tests**: crea `tests/test_insumos.py` usando los fixtures de `tests/conftest.py` (`client`, `register_user`, `login`).

Cuando `models.py` o `schemas.py` crezcan demasiado, se pueden convertir en paquetes (`app/models/`, `app/schemas/`).

## Pendientes

- **Migraciones con Alembic**: hoy las tablas se crean con `Base.metadata.create_all` al iniciar la app (en el `lifespan` de `app/main.py`).
  Eso **no** modifica tablas que ya existen: si cambias una columna, tendrás que borrar el volumen (`docker compose down -v`)
  hasta que migremos a Alembic.
