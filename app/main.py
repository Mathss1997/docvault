import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from fastapi import (
    FastAPI, UploadFile, File, Form, Query,
    Body, Request, Depends, HTTPException, status
)
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from supabase import create_client
from passlib.context import CryptContext
from sqlalchemy import func, text

from app.database import engine, SessionLocal
from app.models import Base, Documento, Usuario

# ─────────────────────────────────────────────
# CONFIG & LOGGING
# ─────────────────────────────────────────────
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("docvault")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SECRET_KEY   = os.getenv("SECRET_KEY", "CHANGE_ME_IN_PRODUCTION_USE_ENV_VAR")
SUPABASE_PUBLIC_URL = os.getenv("SUPABASE_PUBLIC_URL", SUPABASE_URL)

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".docx", ".xlsx", ".txt"}
MAX_FILE_SIZE_MB   = 20
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "SUPABASE_URL e SUPABASE_KEY são obrigatórios. "
        "Defina-as no arquivo .env ou nas variáveis de ambiente."
    )

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
log.info("Supabase conectado: %s", SUPABASE_URL)

# ─────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────
Base.metadata.create_all(bind=engine)

app = FastAPI(title="DocVault", version="2.0.0")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

templates  = Jinja2Templates(directory="app/templates")
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request) -> dict:
    """Retorna o usuário da sessão ou lança 401."""
    user = request.session.get("user")
    tipo = request.session.get("tipo")
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autenticado"
        )
    return {"username": user, "tipo": tipo}


def require_admin(request: Request) -> dict:
    user = current_user(request)
    if user["tipo"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a administradores"
        )
    return user


def validate_file(filename: str, size: int) -> None:
    ext = os.path.splitext(filename)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de arquivo não permitido: {ext}. "
                   f"Permitidos: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    if size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Arquivo muito grande ({size // (1024*1024)} MB). "
                   f"Máximo: {MAX_FILE_SIZE_MB} MB"
        )


def build_storage_path(tipo: str, caminho: str, filename: str) -> str:
    parts = [tipo] + [p for p in caminho.split("/") if p] + [filename]
    return "/".join(parts)


def supabase_public_url(path: str) -> str:
    return f"{SUPABASE_PUBLIC_URL}/storage/v1/object/public/documentos/{path}"


# ─────────────────────────────────────────────
# EXCEÇÃO → JSON (para fetch calls)
# ─────────────────────────────────────────────
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if request.headers.get("accept", "").startswith("application/json") or \
       request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JSONResponse(
            status_code=exc.status_code,
            content={"erro": exc.detail}
        )
    # Para rotas de página, redireciona pro login
    return RedirectResponse("/login")


# ─────────────────────────────────────────────
# AUTENTICAÇÃO
# ─────────────────────────────────────────────
@app.get("/login", response_class=HTMLResponse)
def login_page():
    with open("templates/login.html", "r", encoding="utf-8") as f:
        return f.read()


@app.post("/login")
def login(request: Request, usuario: str = Form(...), senha: str = Form(...)):
    db = SessionLocal()
    try:
        user = db.query(Usuario).filter(Usuario.username == usuario).first()
    finally:
        db.close()

    if user and pwd_context.verify(senha, user.senha):
        request.session["user"] = user.username
        request.session["tipo"] = user.tipo
        log.info("Login: %s", user.username)
        return RedirectResponse("/", status_code=302)

    log.warning("Tentativa de login inválida para: %s", usuario)
    return RedirectResponse("/login?erro=1", status_code=302)


@app.get("/logout")
def logout(request: Request):
    username = request.session.get("user", "desconhecido")
    request.session.clear()
    log.info("Logout: %s", username)
    return RedirectResponse("/login")


# ─────────────────────────────────────────────
# PÁGINA PRINCIPAL
# ─────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if "user" not in request.session:
        return RedirectResponse("/login")
    with open("templates/dashboard.html", "r", encoding="utf-8") as f:
        return f.read()


# ─────────────────────────────────────────────
# USUÁRIO ATUAL
# ─────────────────────────────────────────────
@app.get("/user")
def get_user(request: Request):
    return {
        "usuario": request.session.get("user"),
        "tipo":    request.session.get("tipo"),
    }


# ─────────────────────────────────────────────
# USUÁRIOS (admin)
# ─────────────────────────────────────────────
@app.post("/usuarios/novo")
def criar_usuario(
    request: Request,
    usuario: str = Form(...),
    senha:   str = Form(...),
    tipo:    str = Form("user"),
):
    require_admin(request)
    db = SessionLocal()
    try:
        if db.query(Usuario).filter(Usuario.username == usuario).first():
            raise HTTPException(400, "Usuário já existe")

        novo = Usuario(
            username=usuario,
            senha=pwd_context.hash(senha),
            tipo=tipo,
        )
        db.add(novo)
        db.commit()
        log.info("Usuário criado: %s (%s)", usuario, tipo)
    finally:
        db.close()

    return RedirectResponse("/?sucesso=usuario_criado", status_code=303)


@app.get("/usuarios")
def listar_usuarios(request: Request):
    require_admin(request)
    db = SessionLocal()
    try:
        users = db.query(Usuario).all()
        return [{"id": u.id, "username": u.username, "tipo": u.tipo} for u in users]
    finally:
        db.close()


@app.delete("/usuarios/{user_id}")
def deletar_usuario(user_id: int, request: Request):
    require_admin(request)
    db = SessionLocal()
    try:
        user = db.query(Usuario).filter(Usuario.id == user_id).first()
        if not user:
            raise HTTPException(404, "Usuário não encontrado")
        db.delete(user)
        db.commit()
        log.info("Usuário removido: %s", user.username)
        return {"ok": True}
    finally:
        db.close()


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────
@app.get("/dashboard")
def dashboard(request: Request):
    current_user(request)
    db = SessionLocal()
    try:
        total = db.query(func.count(Documento.id)).scalar()
        categorias = dict(
            db.query(Documento.categoria, func.count(Documento.id))
            .group_by(Documento.categoria)
            .all()
        )
        recentes = (
            db.query(Documento.nome, Documento.categoria, Documento.caminho, Documento.usuario, Documento.data)
            .order_by(Documento.data.desc())
            .limit(10)
            .all()
        )
        return {
            "total": total,
            "categorias": categorias,
            "recentes": [
                {
                    "nome":      r.nome,
                    "categoria": r.categoria,
                    "caminho":   r.caminho,
                    "usuario":   r.usuario,
                    "data":      str(r.data),
                }
                for r in recentes
            ],
        }
    finally:
        db.close()


# ─────────────────────────────────────────────
# ARQUIVOS — listagem
# ─────────────────────────────────────────────
@app.get("/files")
def list_files(request: Request):
    current_user(request)
    db = SessionLocal()
    resultado = {}

    try:
        documentos = db.query(Documento).all()

        for doc in documentos:
            caminho = (doc.caminho or "").strip("/")
            pasta   = f"{doc.categoria}/{caminho}" if caminho else doc.categoria

            try:
                lista = supabase.storage.from_("documentos").list(pasta)
                existe = any(arq.get("name") == doc.nome for arq in lista)
            except Exception as e:
                log.error("Erro ao listar storage para %s: %s", pasta, e)
                existe = False

            if existe:
                resultado.setdefault(doc.categoria, []).append({
                    "nome":    doc.nome,
                    "usuario": doc.usuario,
                    "data":    doc.data,
                    "caminho": doc.caminho or "",
                })
            else:
                log.warning("Arquivo fantasma removido do banco: %s", doc.nome)
                db.delete(doc)
                db.commit()

    finally:
        db.close()

    return resultado


# ─────────────────────────────────────────────
# UPLOAD — explorador (múltiplos arquivos)
# ─────────────────────────────────────────────
@app.post("/upload_explorer")
async def upload_explorer(
    request: Request,
    files:   list[UploadFile] = File(...),
    tipo:    str = Form(...),
    caminho: str = Form(""),
):
    user = current_user(request)
    resultados = []

    for file in files:
        conteudo = await file.read()
        try:
            validate_file(file.filename, len(conteudo))
        except HTTPException as e:
            resultados.append({"nome": file.filename, "erro": e.detail})
            continue

        path_supabase = build_storage_path(tipo, caminho, file.filename)

        try:
            supabase.storage.from_("documentos").upload(
                path=path_supabase,
                file=conteudo,
            )
        except Exception as e:
            log.error("Erro upload Supabase %s: %s", path_supabase, e)
            resultados.append({"nome": file.filename, "erro": str(e)})
            continue

        db = SessionLocal()
        try:
            db.add(Documento(
                nome=file.filename,
                categoria=tipo,
                caminho=caminho,
                usuario=user["username"],
                data=str(datetime.now()),
            ))
            db.commit()
        finally:
            db.close()

        log.info("Upload: %s → %s", user["username"], path_supabase)
        resultados.append({"nome": file.filename, "ok": True})

    erros = [r for r in resultados if "erro" in r]
    return {
        "ok":        len(erros) == 0,
        "resultados": resultados,
        "mensagem":  f"{len(resultados) - len(erros)}/{len(resultados)} arquivo(s) enviado(s) com sucesso.",
    }


# ─────────────────────────────────────────────
# UPLOAD — rota legada (formulário simples)
# ─────────────────────────────────────────────
@app.post("/upload")
async def upload(
    request:   Request,
    file:      UploadFile = File(...),
    categoria: str = Form(...),
    pasta:     str = Form(""),
):
    user = current_user(request)
    conteudo = await file.read()
    validate_file(file.filename, len(conteudo))

    path_supabase = build_storage_path(categoria, pasta, file.filename)

    try:
        supabase.storage.from_("documentos").upload(
            path=path_supabase,
            file=conteudo,
            file_options={"content-type": "application/pdf"},
        )
    except Exception as e:
        log.error("Erro upload: %s", e)
        raise HTTPException(500, f"Erro ao enviar arquivo: {e}")

    db = SessionLocal()
    try:
        db.add(Documento(
            nome=file.filename,
            categoria=categoria,
            caminho=pasta,
            usuario=user["username"],
            data=str(datetime.now()),
        ))
        db.commit()
    finally:
        db.close()

    return RedirectResponse(url="/", status_code=303)


# ─────────────────────────────────────────────
# EXPLORAR pastas
# ─────────────────────────────────────────────
@app.get("/explorar")
def explorar(request: Request, tipo: str, caminho: str = ""):
    current_user(request)
    prefix = f"{tipo}/{caminho}" if caminho else tipo

    try:
        response = supabase.storage.from_("documentos").list(prefix)
    except Exception as e:
        log.error("Erro ao explorar %s: %s", prefix, e)
        raise HTTPException(500, "Erro ao listar pasta")

    pastas   = []
    arquivos = []

    for item in response:
        nome = item["name"]
        if nome in (".keep", ".emptyFolderPlaceholder"):
            continue
        if item.get("id") is None:
            pastas.append(nome)
        else:
            arquivos.append(nome)

    return {"pastas": pastas, "arquivos": arquivos, "caminho": caminho}


# ─────────────────────────────────────────────
# CRIAR PASTA
# ─────────────────────────────────────────────
@app.post("/criar_pasta")
async def criar_pasta(request: Request, data: dict = Body(...)):
    current_user(request)
    tipo   = data.get("tipo")
    caminho = data.get("caminho", "")
    nome   = data.get("nome", "").strip()

    if not tipo or not nome:
        raise HTTPException(400, "Tipo e nome da pasta são obrigatórios")

    path = build_storage_path(tipo, caminho, f"{nome}/.keep")

    try:
        supabase.storage.from_("documentos").upload(
            path=path,
            file=b"",
            file_options={"content-type": "text/plain"},
        )
        log.info("Pasta criada: %s", path)
        return {"ok": True, "mensagem": f"Pasta '{nome}' criada com sucesso"}
    except Exception as e:
        log.error("Erro ao criar pasta %s: %s", path, e)
        raise HTTPException(500, f"Erro ao criar pasta: {e}")


# ─────────────────────────────────────────────
# DELETE arquivo
# ─────────────────────────────────────────────
@app.delete("/delete")
def delete_file(
    request: Request,
    tipo:    str = Query(...),
    caminho: str = Query(""),
    nome:    str = Query(...),
):
    user = current_user(request)

    nome    = nome.replace("📄", "").strip()
    caminho = caminho.strip("/")
    path    = build_storage_path(tipo, caminho, nome)

    import requests as req_lib
    url = f"{SUPABASE_URL}/storage/v1/object/documentos/{path}"
    headers = {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    resp = req_lib.delete(url, headers=headers)

    if resp.status_code not in (200, 204):
        log.error("Erro ao deletar no Supabase: %s %s", resp.status_code, resp.text)
        raise HTTPException(500, f"Erro ao deletar arquivo no storage: {resp.text}")

    db = SessionLocal()
    try:
        db.query(Documento).filter(
            Documento.nome      == nome,
            Documento.categoria == tipo,
            Documento.caminho   == (caminho or ""),
        ).delete()
        db.commit()
    finally:
        db.close()

    log.info("Arquivo deletado por %s: %s", user["username"], path)
    return {"ok": True}


# ─────────────────────────────────────────────
# URL ASSINADA (seguro — não expõe chave no front)
# ─────────────────────────────────────────────
@app.get("/signed-url")
def signed_url(
    request: Request,
    tipo:    str = Query(...),
    caminho: str = Query(""),
    nome:    str = Query(...),
):
    current_user(request)
    path = build_storage_path(tipo, caminho, nome)
    try:
        result = supabase.storage.from_("documentos").create_signed_url(path, 3600)
        return {"url": result["signedURL"]}
    except Exception as e:
        log.error("Erro ao gerar signed URL para %s: %s", path, e)
        raise HTTPException(500, "Erro ao gerar link de acesso")
