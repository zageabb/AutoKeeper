"""FastAPI web interface. Bind Uvicorn only to loopback behind UDA/Caddy."""
import hmac
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    APIRouter, Depends, FastAPI, File, Header, HTTPException, Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import core
from .importer import MAX_IMPORT, import_vehicles, read_import

HERE = Path(__file__).resolve().parent
basic = HTTPBasic(auto_error=False)
templates = Jinja2Templates(directory=str(HERE / "web"))


class VehicleInput(BaseModel):
    registration: str
    owner: str = ""
    company: str = ""
    email: str = ""
    make: str = ""
    model: str = ""
    colour: str = ""


def require_admin(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(basic),
    x_uda_user: str | None = Header(default=None),
    x_uda_groups: str | None = Header(default=None),
):
    auth_mode = os.getenv("AUTOKEEPER_AUTH_MODE", "basic").strip().casefold()
    if auth_mode == "uda":
        groups = {
            group.strip().casefold()
            for group in (x_uda_groups or "").split(",")
            if group.strip()
        }
        if x_uda_user and ("personal" in groups or "*" in groups):
            request.state.authenticated_user = x_uda_user
            return
        raise HTTPException(401, "UDA authentication required")
    if auth_mode != "basic":
        raise HTTPException(503, "AUTOKEEPER_AUTH_MODE must be 'basic' or 'uda'")

    password = os.getenv("APP_ADMIN_PASSWORD", "")
    if not password or password == "REPLACE_WITH_LONG_RANDOM_PASSWORD":
        if os.getenv("AUTOKEEPER_DEV_NO_AUTH") == "1":
            return
        raise HTTPException(503, "Administrator password is not configured")
    expected_user = os.getenv("APP_ADMIN_USERNAME", "admin")
    if (not credentials
        or not hmac.compare_digest(credentials.username, expected_user)
        or not hmac.compare_digest(credentials.password, password)):
        raise HTTPException(401, "Authentication required",
                            headers={"WWW-Authenticate": 'Basic realm="AutoKeeper"'})


def require_write(x_autokeeper_request: str | None = Header(default=None)):
    # A non-simple request header prevents cross-site HTML form CSRF against
    # browser-cached Basic auth or UDA session; do not enable permissive CORS.
    if x_autokeeper_request != "same-origin":
        raise HTTPException(403, "Missing same-origin write header")


def create_app(db_path=None):
    db_path = db_path or os.getenv("AUTOKEEPER_DB_PATH", "data/autokeeper.db")
    # LOCAL_UBUNTU_PROXY_COMPAT:
    # Caddy strips /apps/autokeeper/ and the externally visible prefix is
    # supplied as an explicit deployment setting, never trusted from callers.
    root_path = os.getenv("AUTOKEEPER_ROOT_PATH", "").rstrip("/")

    @asynccontextmanager
    async def lifespan(app):
        db = core.open_db(db_path)
        try:
            core.init_db(db)
        finally:
            db.close()
        yield

    app = FastAPI(title="AutoKeeper", root_path=root_path, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=str(HERE / "web" / "static")),
              name="static")

    def get_db():
        db = core.open_db(db_path)
        try:
            core.init_db(db)
            yield db
        finally:
            db.close()

    @app.get("/health")
    def health():
        return {"status": "ok", "application": "AutoKeeper"}

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, _=Depends(require_admin)):
        return templates.TemplateResponse(
            request=request, name="index.html",
            context={"base_path": root_path}
        )

    api = APIRouter(prefix="/api", dependencies=[Depends(require_admin)])

    @api.get("/dashboard")
    def dashboard(db=Depends(get_db)):
        return core.get_dashboard(db)

    @api.get("/vehicles/{vehicle_id}/history")
    def history(vehicle_id: int, db=Depends(get_db)):
        if not core.get_vehicle(db, vehicle_id):
            raise HTTPException(404, "Vehicle not found")
        return [dict(r) for r in db.execute("""
            SELECT checked_at,success,mot_expiry_date,tax_due_date,error
            FROM checks WHERE vehicle_id=? ORDER BY id DESC LIMIT 30
        """, (vehicle_id,))]

    @api.post("/vehicles", dependencies=[Depends(require_write)])
    def create_vehicle(body: VehicleInput, db=Depends(get_db)):
        try:
            return core.view_vehicle(core.save_vehicle(db, body.model_dump()))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "That registration is already in the register") from exc

    @api.put("/vehicles/{vehicle_id}", dependencies=[Depends(require_write)])
    def update_vehicle(vehicle_id: int, body: VehicleInput, db=Depends(get_db)):
        try:
            return core.view_vehicle(core.save_vehicle(db, body.model_dump(), vehicle_id))
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "That registration is already in the register") from exc

    @api.delete("/vehicles/{vehicle_id}", dependencies=[Depends(require_write)])
    def delete_vehicle(vehicle_id: int, db=Depends(get_db)):
        if not core.get_vehicle(db, vehicle_id):
            raise HTTPException(404, "Vehicle not found")
        db.execute("DELETE FROM vehicles WHERE id=?", (vehicle_id,))
        db.commit()
        return {"deleted": vehicle_id}

    @api.post("/vehicles/{vehicle_id}/refresh", dependencies=[Depends(require_write)])
    def refresh_one(vehicle_id: int, db=Depends(get_db)):
        try:
            return core.refresh_vehicle(db, vehicle_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    @api.post("/refresh-all", dependencies=[Depends(require_write)])
    def refresh_all(db=Depends(get_db)):
        if not os.getenv("DVLA_API_KEY"):
            raise HTTPException(503, "DVLA_API_KEY is not configured")
        return core.refresh_all(db)

    @api.post("/reminders/preview", dependencies=[Depends(require_write)])
    def preview_reminders(db=Depends(get_db)):
        return core.reminders(db, dry_run=True)

    @api.post("/import", dependencies=[Depends(require_write)])
    async def import_file(file: UploadFile = File(...), db=Depends(get_db)):
        content = await file.read(MAX_IMPORT + 1)
        try:
            records = read_import(content, file.filename or "")
            return import_vehicles(db, records)
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    app.include_router(api)
    return app


app = create_app()
