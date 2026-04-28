import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from fastapi import (
    FastAPI, UploadFile, File, Form, Query,
    Body, Request, HTTPException, status
)
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from supabase import create_client
from passlib.context import CryptContext
from sqlalchemy import func

from app.database import engine, SessionLocal
from app.models import Base, Documento, Usuario, LogAtividade
from app.routers.indexadores import router as indexadores_router
from app.routers.logs import router as logs_router

# ─────────────────────────────────────────────
# CONFIG & LOGGING
# ─────────────────────────────────────────────
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("docvault")

SUPABASE_URL        = os.getenv("SUPABASE_URL")
SUPABASE_KEY        = os.getenv("SUPABASE_KEY")
SECRET_KEY          = os.getenv("SECRET_KEY", "CHANGE_ME_IN_PRODUCTION")
SUPABASE_PUBLIC_URL = os.getenv("SUPABASE_PUBLIC_URL", SUPABASE_URL)

ALLOWED_EXTENSIONS  = {".pdf", ".png", ".jpg", ".jpeg", ".docx", ".xlsx", ".txt"}
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL e SUPABASE_KEY são obrigatórios.")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
log.info("Supabase conectado: %s", SUPABASE_URL)

# ─────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────
Base.metadata.create_all(bind=engine)

app = FastAPI(title="DocVault", version="2.2.0")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)
app.include_router(indexadores_router)
app.include_router(logs_router)

templates   = Jinja2Templates(directory="app/templates")
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def current_user(request: Request) -> dict:
    user = request.session.get("user")
    tipo = request.session.get("tipo")
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Não autenticado")
    return {"username": user, "tipo": tipo}


def require_admin(request: Request) -> dict:
    user = current_user(request)
    if user["tipo"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso restrito a administradores")
    return user


def validate_file(filename: str, size: int) -> None:
    ext = os.path.splitext(filename)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Tipo não permitido: {ext}")
    if size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(400, f"Arquivo muito grande. Máx: 20 MB")


def build_storage_path(tipo: str, caminho: str, filename: str) -> str:
    parts = [tipo] + [p for p in caminho.split("/") if p] + [filename]
    return "/".join(parts)


def get_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "—"


# ─────────────────────────────────────────────
# REGISTRO DE LOG
# ─────────────────────────────────────────────
def registrar_log(
    usuario:  str,
    acao:     str,
    detalhe:  str = "",
    contexto: str = "",
    ip:       str = "",
):
    """Insere um registro de log. Nunca lança exceção — falha silenciosa."""
    try:
        db = SessionLocal()
        try:
            db.add(LogAtividade(
                usuario   = usuario,
                acao      = acao,
                detalhe   = detalhe[:500] if detalhe else "",
                contexto  = contexto[:200] if contexto else "",
                ip        = ip,
                criado_em = datetime.now().isoformat(),
            ))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        log.error("Falha ao registrar log: %s", e)


# ─────────────────────────────────────────────
# EXCEPTION HANDLER
# ─────────────────────────────────────────────
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    accept = request.headers.get("accept", "")
    xrw    = request.headers.get("x-requested-with", "")
    if "application/json" in accept or xrw == "XMLHttpRequest":
        return JSONResponse(status_code=exc.status_code, content={"erro": exc.detail})
    return RedirectResponse("/login")


# ─────────────────────────────────────────────
# AUTH
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

    ip = get_ip(request)

    if user and pwd_context.verify(senha, user.senha):
        request.session["user"] = user.username
        request.session["tipo"] = user.tipo
        log.info("Login: %s", user.username)
        registrar_log(user.username, "LOGIN", ip=ip)
        return RedirectResponse("/", status_code=302)

    log.warning("Login inválido: %s", usuario)
    registrar_log(usuario, "LOGIN", detalhe="Tentativa inválida", ip=ip)
    return RedirectResponse("/login?erro=1", status_code=302)


@app.get("/logout")
def logout(request: Request):
    username = request.session.get("user", "—")
    registrar_log(username, "LOGOUT", ip=get_ip(request))
    request.session.clear()
    return RedirectResponse("/login")


# ─────────────────────────────────────────────
# PÁGINAS
# ─────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if "user" not in request.session:
        return RedirectResponse("/login")
    with open("templates/dashboard.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/user")
def get_user(request: Request):
    return {
        "usuario": request.session.get("user"),
        "tipo":    request.session.get("tipo"),
    }


# ─────────────────────────────────────────────
# USUÁRIOS
# ─────────────────────────────────────────────
@app.post("/usuarios/novo")
def criar_usuario(request: Request, data: dict = Body(...)):
    require_admin(request)
    usuario = data.get("usuario", "").strip()
    senha   = data.get("senha", "")
    tipo    = data.get("tipo", "user")
    if not usuario or not senha:
        raise HTTPException(400, "Usuário e senha são obrigatórios")
    db = SessionLocal()
    try:
        if db.query(Usuario).filter(Usuario.username == usuario).first():
            raise HTTPException(400, "Usuário já existe")
        db.add(Usuario(
            username=usuario,
            senha=pwd_context.hash(senha),
            tipo=tipo,
            criado_em=datetime.now().isoformat(),
        ))
        db.commit()
        log.info("Usuário criado: %s (%s)", usuario, tipo)
        registrar_log(request.session.get("user","admin"), "LOGIN",
                      detalhe=f"Criou usuário: {usuario} ({tipo})", ip=get_ip(request))
        return {"ok": True, "mensagem": f"Usuário '{usuario}' criado com sucesso"}
    finally:
        db.close()


@app.get("/usuarios")
def listar_usuarios(request: Request):
    require_admin(request)
    db = SessionLocal()
    try:
        users = db.query(Usuario).all()
        return [{
            "id":        u.id,
            "username":  u.username,
            "tipo":      u.tipo,
            "criado_em": u.criado_em or "",
        } for u in users]
    finally:
        db.close()


@app.put("/usuarios/{user_id}")
def editar_usuario(user_id: int, request: Request, data: dict = Body(...)):
    require_admin(request)
    db = SessionLocal()
    try:
        user = db.query(Usuario).filter(Usuario.id == user_id).first()
        if not user:
            raise HTTPException(404, "Usuário não encontrado")
        novo_tipo = data.get("tipo")
        if novo_tipo and novo_tipo in ("admin", "user", "comum"):
            user.tipo = novo_tipo
        db.commit()
        log.info("Usuário editado: %s → %s", user.username, novo_tipo)
        return {"ok": True}
    finally:
        db.close()


@app.put("/usuarios/{user_id}/senha")
def reset_senha(user_id: int, request: Request, data: dict = Body(...)):
    require_admin(request)
    nova_senha = data.get("senha", "")
    if len(nova_senha) < 4:
        raise HTTPException(400, "Senha deve ter pelo menos 4 caracteres")
    db = SessionLocal()
    try:
        user = db.query(Usuario).filter(Usuario.id == user_id).first()
        if not user:
            raise HTTPException(404, "Usuário não encontrado")
        user.senha = pwd_context.hash(nova_senha)
        db.commit()
        log.info("Senha resetada: %s", user.username)
        registrar_log(request.session.get("user","admin"), "LOGIN",
                      detalhe=f"Reset senha: {user.username}", ip=get_ip(request))
        return {"ok": True, "mensagem": f"Senha de '{user.username}' atualizada"}
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
        nome = user.username
        db.delete(user)
        db.commit()
        registrar_log(request.session.get("user","admin"), "DELETE",
                      detalhe=f"Removeu usuário: {nome}", ip=get_ip(request))
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
            .group_by(Documento.categoria).all()
        )
        recentes = (
            db.query(Documento)
            .order_by(Documento.data.desc())
            .limit(10).all()
        )
        return {
            "total": total,
            "categorias": categorias,
            "recentes": [
                {"nome": r.nome, "categoria": r.categoria,
                 "caminho": r.caminho, "usuario": r.usuario, "data": str(r.data)}
                for r in recentes
            ],
        }
    finally:
        db.close()


# ─────────────────────────────────────────────
# FILES
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
                lista  = supabase.storage.from_("documentos").list(pasta)
                existe = any(a.get("name") == doc.nome for a in lista)
            except Exception as e:
                log.error("Erro storage list %s: %s", pasta, e)
                existe = False
            if existe:
                resultado.setdefault(doc.categoria, []).append({
                    "id":           doc.id,
                    "nome":         doc.nome,
                    "usuario":      doc.usuario,
                    "data":         doc.data,
                    "caminho":      doc.caminho or "",
                    "assinado":     doc.assinado == "sim" if hasattr(doc, "assinado") else False,
                    "assinado_por": doc.assinado_por if hasattr(doc, "assinado_por") else None,
                    "assinado_em":  doc.assinado_em if hasattr(doc, "assinado_em") else None,
                })
            else:
                log.warning("Fantasma removido: %s", doc.nome)
                db.delete(doc)
                db.commit()
    finally:
        db.close()
    return resultado


# ─────────────────────────────────────────────
# UPLOAD (múltiplos arquivos)
# ─────────────────────────────────────────────
@app.post("/upload_explorer")
async def upload_explorer(
    request: Request,
    files:   list[UploadFile] = File(...),
    tipo:    str = Form(...),
    caminho: str = Form(""),
):
    user = current_user(request)
    ip   = get_ip(request)
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
            supabase.storage.from_("documentos").upload(path=path_supabase, file=conteudo)
        except Exception as e:
            log.error("Erro upload %s: %s", path_supabase, e)
            resultados.append({"nome": file.filename, "erro": str(e)})
            continue

        db = SessionLocal()
        try:
            db.add(Documento(
                nome=file.filename, categoria=tipo,
                caminho=caminho, usuario=user["username"],
                data=str(datetime.now()),
            ))
            db.commit()
        finally:
            db.close()

        registrar_log(
            user["username"], "UPLOAD",
            detalhe=file.filename,
            contexto=f"{tipo}/{caminho}" if caminho else tipo,
            ip=ip,
        )
        resultados.append({"nome": file.filename, "ok": True})

    erros = [r for r in resultados if "erro" in r]
    return {
        "ok": len(erros) == 0,
        "resultados": resultados,
        "mensagem": f"{len(resultados)-len(erros)}/{len(resultados)} arquivo(s) enviado(s).",
    }


# ─────────────────────────────────────────────
# EXPLORAR
# ─────────────────────────────────────────────
@app.get("/explorar")
def explorar(request: Request, tipo: str, caminho: str = ""):
    current_user(request)
    prefix = f"{tipo}/{caminho}" if caminho else tipo
    try:
        response = supabase.storage.from_("documentos").list(prefix)
    except Exception as e:
        raise HTTPException(500, f"Erro ao listar pasta: {e}")
    pastas, arquivos = [], []
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
    user = current_user(request)
    tipo    = data.get("tipo")
    caminho = data.get("caminho", "")
    nome    = data.get("nome", "").strip()
    if not tipo or not nome:
        raise HTTPException(400, "Tipo e nome são obrigatórios")
    path = build_storage_path(tipo, caminho, f"{nome}/.keep")
    try:
        supabase.storage.from_("documentos").upload(
            path=path, file=b"", file_options={"content-type": "text/plain"})
        registrar_log(
            user["username"], "CREATE_FOLDER",
            detalhe=nome,
            contexto=f"{tipo}/{caminho}" if caminho else tipo,
            ip=get_ip(request),
        )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, f"Erro ao criar pasta: {e}")


# ─────────────────────────────────────────────
# DELETE
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
    resp = req_lib.delete(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    })
    if resp.status_code not in (200, 204):
        raise HTTPException(500, f"Erro storage: {resp.text}")

    db = SessionLocal()
    try:
        db.query(Documento).filter(
            Documento.nome == nome,
            Documento.categoria == tipo,
            Documento.caminho == (caminho or ""),
        ).delete()
        db.commit()
    finally:
        db.close()

    registrar_log(
        user["username"], "DELETE",
        detalhe=nome,
        contexto=f"{tipo}/{caminho}" if caminho else tipo,
        ip=get_ip(request),
    )
    return {"ok": True}


# ─────────────────────────────────────────────
# SIGNED URL + LOG DE DOWNLOAD
# ─────────────────────────────────────────────
@app.get("/signed-url")
def signed_url(
    request: Request,
    tipo:    str = Query(...),
    caminho: str = Query(""),
    nome:    str = Query(...),
):
    user = current_user(request)
    path = build_storage_path(tipo, caminho, nome)
    try:
        result = supabase.storage.from_("documentos").create_signed_url(path, 3600)
        # Registra download apenas quando a URL é gerada para visualização/download
        registrar_log(
            user["username"], "DOWNLOAD",
            detalhe=nome,
            contexto=f"{tipo}/{caminho}" if caminho else tipo,
            ip=get_ip(request),
        )
        return {"url": result["signedURL"]}
    except Exception as e:
        raise HTTPException(500, f"Erro ao gerar link: {e}")




@app.delete("/excluir_pasta")
async def excluir_pasta(request: Request, data: dict = Body(...)):
    """Exclui uma pasta e todos os arquivos dentro dela no Supabase Storage."""
    user = require_admin(request)
    tipo    = data.get("tipo", "")
    caminho = data.get("caminho", "")

    if not tipo or not caminho:
        raise HTTPException(400, "Tipo e caminho são obrigatórios")

    path_base = f"{tipo}/{caminho}"

    try:
        # Lista todos os arquivos na pasta
        items = supabase.storage.from_("documentos").list(path_base)
        arquivos = [f"{path_base}/{item['name']}" for item in items if item.get("name") and not item.get("id") is None]

        # Remove arquivos do storage
        if arquivos:
            supabase.storage.from_("documentos").remove(arquivos)

        # Remove subpastas recursivamente (arquivos dentro de subpastas)
        for item in items:
            if item.get("name") and item.get("id") is None:
                sub_path = f"{path_base}/{item['name']}"
                try:
                    sub_items = supabase.storage.from_("documentos").list(sub_path)
                    sub_files = [f"{sub_path}/{s['name']}" for s in sub_items if s.get("name")]
                    if sub_files:
                        supabase.storage.from_("documentos").remove(sub_files)
                except Exception:
                    pass

        # Remove registros do banco
        db = SessionLocal()
        try:
            docs = db.query(Documento).filter(
                Documento.categoria == tipo,
                Documento.caminho.like(f"{caminho}%"),
            ).all()
            for doc in docs:
                db.delete(doc)
            db.commit()
        finally:
            db.close()

        registrar_log(
            user["username"], "DELETE",
            detalhe=f"Pasta excluída: {caminho}",
            contexto=tipo,
            ip=get_ip(request),
        )

        log.info("Pasta excluída: %s/%s por %s", tipo, caminho, user["username"])
        return {"ok": True, "mensagem": f"Pasta '{caminho}' excluída"}

    except HTTPException:
        raise
    except Exception as e:
        log.error("Erro ao excluir pasta: %s", e)
        raise HTTPException(500, f"Erro ao excluir pasta: {e}")

# ─────────────────────────────────────────────
# ASSINATURA DIGITAL ICP-BRASIL
# ─────────────────────────────────────────────
@app.post("/assinar")
async def assinar_documento(
    request: Request,
    tipo:        str        = Form(...),
    caminho:     str        = Form(""),
    nome:        str        = Form(...),
    certificado: UploadFile = File(...),
    senha_cert:  str        = Form(...),
):
    """
    Assina digitalmente um PDF com certificado ICP-Brasil (A1 — .pfx/.p12).
    Fluxo:
      1. Baixa o PDF do Supabase
      2. Assina com pyHanko usando o certificado fornecido
      3. Faz upload do PDF assinado de volta ao Supabase
      4. Atualiza o registro no banco
    """
    user = current_user(request)
    import tempfile
    from pathlib import Path

    # Validações
    cert_ext = (certificado.filename or "").lower().split(".")[-1]
    if cert_ext not in ("pfx", "p12"):
        raise HTTPException(400, "Certificado deve ser .pfx ou .p12")

    if not nome.lower().endswith(".pdf"):
        raise HTTPException(400, "Apenas PDFs podem ser assinados")

    # 1. Baixa o PDF do Supabase
    path_supabase = build_storage_path(tipo, caminho, nome)
    try:
        pdf_bytes = supabase.storage.from_("documentos").download(path_supabase)
    except Exception as e:
        raise HTTPException(500, f"Erro ao baixar PDF: {e}")

    # 2. Lê o certificado
    cert_bytes = await certificado.read()

    # 3. Assina o PDF
    try:
        from pyhanko.sign import signers, fields as sign_fields
        from pyhanko.sign.general import load_cert_for_signing
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
        from cryptography.hazmat.primitives.serialization import pkcs12
        from cryptography.hazmat.backends import default_backend
        import io

        # Carrega o certificado .pfx
        private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
            cert_bytes, senha_cert.encode("utf-8"), default_backend()
        )

        if not private_key or not certificate:
            raise HTTPException(400, "Certificado inv\u00e1lido ou senha incorreta")

        # Prepara o assinante
        signer = signers.SimpleSigner(
            signing_cert=certificate,
            signing_key=private_key,
            cert_registry=None,
            ca_chain=list(additional_certs) if additional_certs else [],
        )

        # Assina o PDF
        pdf_in = io.BytesIO(pdf_bytes)
        writer = IncrementalPdfFileWriter(pdf_in)

        sig_meta = signers.PdfSignatureMetadata(
            field_name="Assinatura_DocVault",
            reason=f"Documento assinado por {user['username']} via DocVault",
            name=user["username"],
            location="DocVault - Kronos Systems",
        )

        pdf_out = io.BytesIO()
        signers.sign_pdf(
            writer,
            signature_meta=sig_meta,
            signer=signer,
            output=pdf_out,
        )
        pdf_signed = pdf_out.getvalue()

    except HTTPException:
        raise
    except Exception as e:
        log.error("Erro ao assinar PDF: %s", e, exc_info=True)
        err_msg = str(e)
        if "password" in err_msg.lower() or "mac" in err_msg.lower():
            raise HTTPException(400, "Senha do certificado incorreta")
        raise HTTPException(500, f"Erro ao assinar: {e}")

    # 4. Faz upload do PDF assinado de volta
    try:
        supabase.storage.from_("documentos").update(
            path=path_supabase,
            file=pdf_signed,
            file_options={"content-type": "application/pdf"},
        )
    except Exception:
        # Se update falhar, tenta remove + upload
        try:
            supabase.storage.from_("documentos").remove([path_supabase])
            supabase.storage.from_("documentos").upload(
                path=path_supabase,
                file=pdf_signed,
                file_options={"content-type": "application/pdf"},
            )
        except Exception as e:
            raise HTTPException(500, f"Erro ao salvar PDF assinado: {e}")

    # 5. Atualiza registro no banco (marca como assinado)
    db = SessionLocal()
    try:
        doc = db.query(Documento).filter(
            Documento.nome == nome,
            Documento.categoria == tipo,
            Documento.caminho == caminho,
        ).first()
        if doc:
            doc.assinado = "sim"
            doc.assinado_por = user["username"]
            doc.assinado_em = datetime.now().isoformat()
            db.commit()
    finally:
        db.close()

    registrar_log(
        user["username"], "INDEXAR",
        detalhe=f"Assinatura digital: {nome}",
        contexto=f"{tipo}/{caminho}" if caminho else tipo,
        ip=get_ip(request),
    )

    log.info("PDF assinado: %s por %s", nome, user["username"])
    return {"ok": True, "mensagem": f"Documento assinado por {user['username']}"}


@app.get("/verificar-assinatura")
def verificar_assinatura(request: Request, tipo: str, caminho: str = "", nome: str = ""):
    """Verifica se um documento está assinado digitalmente."""
    current_user(request)
    db = SessionLocal()
    try:
        doc = db.query(Documento).filter(
            Documento.nome == nome,
            Documento.categoria == tipo,
            Documento.caminho == caminho,
        ).first()
        if doc and doc.assinado == "sim":
            return {
                "assinado": True,
                "por": doc.assinado_por or "—",
                "em": doc.assinado_em or "—",
            }
        return {"assinado": False}
    finally:
        db.close()
