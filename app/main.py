from fastapi import FastAPI, UploadFile, File, Form, Query, Body, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import os
from datetime import datetime
from urllib.parse import unquote

# ====================== SUPABASE ======================
import os
from dotenv import load_dotenv
from supabase import create_client

# Carrega as variáveis do arquivo .env (raiz do projeto)
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

print("🔑 SUPABASE KEY:", SUPABASE_KEY[:20] if SUPABASE_KEY else "NÃO DEFINIDA")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("""
    ❌ ERRO: SUPABASE_URL ou SUPABASE_KEY não foram encontrados!
    Crie um arquivo .env na raiz do projeto (C:\\Users\\nmath\\ged_novo) com:
    
    SUPABASE_URL=https://eqykwinmscoziwybpxsd.supabase.co
    SUPABASE_KEY=sb_publishable_sua_chave_aqui
    """)

print(f"✅ Supabase carregado: {SUPABASE_URL}")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Banco local (SQLAlchemy)
from app.database import engine, SessionLocal
from app.models import Base, Documento, Usuario

# Cria tabelas
Base.metadata.create_all(bind=engine)

# Configurações
app = FastAPI()
@app.on_event("startup")
def debug_supabase():
    print("🚀 DEBUG STARTUP")
    print("🔑 SUPABASE KEY:", SUPABASE_KEY[:20] if SUPABASE_KEY else "NÃO DEFINIDA")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.add_middleware(SessionMiddleware, secret_key="segredo123")

templates = Jinja2Templates(directory="app/templates")

# Criptografia de senha
from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ====================== ROTAS ======================

@app.get("/", response_class=HTMLResponse)
def home(request: Request):

    print("🚀 DEBUG REQUEST")
    print("🔑 SUPABASE KEY:", SUPABASE_KEY[:20] if SUPABASE_KEY else "NÃO DEFINIDA")

    if "user" not in request.session:
        return RedirectResponse("/login")

    file_path = os.path.join(BASE_DIR, "..", "templates", "dashboard.html")
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/login", response_class=HTMLResponse)
def login_page():
    file_path = os.path.join(BASE_DIR, "..", "templates", "login.html")
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

@app.post("/login")
def login(request: Request, usuario: str = Form(...), senha: str = Form(...)):
    db = SessionLocal()
    user = db.query(Usuario).filter(Usuario.username == usuario).first()
    db.close()

    if user and pwd_context.verify(senha, user.senha):
        request.session["user"] = user.username
        request.session["tipo"] = user.tipo
        return RedirectResponse("/", status_code=302)

    return RedirectResponse("/login", status_code=302)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login")

# Upload
@app.post("/upload")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    categoria: str = Form(...),
    pasta: str = Form(...)
):
    if "user" not in request.session:
        return RedirectResponse("/login")

    usuario = request.session["user"]

    try:
        conteudo = await file.read()
        if pasta:
            caminho_supabase = f"{categoria}/{pasta}/{file.filename}"
        else:
            caminho_supabase = f"{categoria}/{file.filename}"

        supabase.storage.from_("documentos").upload(
            path=caminho_supabase,
            file=conteudo,
            file_options={"content-type": "application/pdf"}
        
        )
    except Exception as e:
        print("ERRO NO UPLOAD:", str(e))
        return {"erro": str(e)}

    db = SessionLocal()
    novo_doc = Documento(
        nome=file.filename,
        categoria=categoria,
        caminho=pasta if pasta else "",
        usuario=usuario,
        data=str(datetime.now())
    )
    db.add(novo_doc)
    db.commit()
    db.close()

    return RedirectResponse(url="/", status_code=303)
   

@app.post("/upload_explorer")
async def upload_explorer(
    request: Request,
    file: UploadFile = File(...),
    tipo: str = Form(...),
    caminho: str = Form("")
):
    if "user" not in request.session:
        return {"erro": "Não autenticado"}

    usuario = request.session["user"]

    try:
        conteudo = await file.read()

        # Monta o caminho correto no Supabase
        if caminho:
            path_supabase = f"{tipo}/{caminho}/{file.filename}"
        else:
            path_supabase = f"{tipo}/{file.filename}"

        print(f"[UPLOAD EXPLORER] Enviando para: {path_supabase}")

        response = supabase.storage.from_("documentos").upload(
            path=path_supabase,
            file=conteudo
        )

        print("[UPLOAD EXPLORER] Sucesso:", response)
        print("📦 TAMANHO:", len(conteudo))

        return {"ok": True, "mensagem": "Arquivo enviado com sucesso"}

    except Exception as e:
        print("[UPLOAD EXPLORER] ERRO:", str(e))
        return {"erro": str(e)}

# Outras rotas (mantive as principais)
@app.get("/files")
def list_files():
    db = SessionLocal()
    documentos = db.query(Documento).all()
    resultado = {}
    for doc in documentos:
        if doc.categoria not in resultado:
            resultado[doc.categoria] = []
        resultado[doc.categoria].append({
            "nome": doc.nome,
            "usuario": doc.usuario,
            "data": doc.data,
            "caminho": doc.caminho,
        })
    db.close()
    return resultado

@app.get("/user")
def get_user(request: Request):
    return {
        "usuario": request.session.get("user"),
        "tipo": request.session.get("tipo")
    }

@app.get("/dashboard")
def dashboard():
    from sqlalchemy import func
    from app.database import SessionLocal
    from app.models import Documento

    db = SessionLocal()

    total = db.query(func.count(Documento.id)).scalar()

    categorias = dict(
        db.query(Documento.categoria, func.count(Documento.id))
        .group_by(Documento.categoria)
        .all()
    )

    recentes = (
        db.query(Documento.nome, Documento.data)
        .order_by(Documento.data.desc())
        .limit(5)
        .all()
    )

    return {
        "total": total,
        "categorias": categorias,
        "recentes": [
            {"nome": r.nome, "data": str(r.data)} for r in recentes
        ]
    }

# ====================== CRIAR PASTA (corrigida) ======================
@app.post("/criar_pasta")
async def criar_pasta(data: dict = Body(...)):
    try:
        tipo = data.get("tipo")
        caminho = data.get("caminho", "")
        nome = data.get("nome")

        if not tipo or not nome:
            return {"erro": "Tipo e nome da pasta são obrigatórios"}

        if caminho:
            path = f"{tipo}/{caminho}/{nome}/.keep"
        else:
            path = f"{tipo}/{nome}/.keep"

        print(f"[CRIAR PASTA] Tentando criar: {path}")

        # Versão simplificada e mais estável
        response = supabase.storage.from_("documentos").upload(
            path=path,
            file=b"",                           # arquivo vazio
            file_options={"content-type": "text/plain"}
        )

        print(f"[CRIAR PASTA] Sucesso! Resposta: {response}")
        return {"ok": True, "mensagem": "Pasta criada com sucesso"}

    except Exception as e:
        error_msg = str(e)
        print(f"[CRIAR PASTA] ERRO DETALHADO: {error_msg}")
        return {"erro": error_msg}
# ====================== EXPLORAR ======================
@app.get("/explorar")
def explorar(tipo: str, caminho: str = ""):
    prefix = f"{tipo}/{caminho}" if caminho else tipo
    response = supabase.storage.from_("documentos").list(prefix)

    pastas = set()
    arquivos = []

    for item in response:
        nome = item["name"]
        if nome == ".keep":
            continue
        if item.get("id") is None:   # é pasta
            pastas.add(nome)
        else:
            arquivos.append(nome)

    return {
        "pastas": list(pastas),
        "arquivos": arquivos,
        "caminho": caminho
    }

# ====================== DELETE ======================
@app.delete("/delete")
def delete_file(tipo: str, caminho: str = "", nome: str = Query(...)):
    try:
        print("🔥 DELETE RECEBIDO:", tipo, caminho, nome)

        # 🔥 monta caminho REAL correto
        caminho = caminho.strip("/") if caminho else ""
        nome = nome.strip("/")

        if caminho:
            path = f"{tipo}/{caminho}/{nome}"
        else:
            path = f"{tipo}/{nome}"

        path = path.replace("//", "/")

        print("🔥 PATH FINAL REAL:", path)

        # 🔥 DELETE DIRETO (SEM LIST)
        supabase.storage.from_("documentos").remove([path])

        print("🔥 DELETE EXECUTADO")

        # 🔥 remove do banco
        db = SessionLocal()
        db.query(Documento).filter(
            Documento.nome == nome
        ).delete()
        db.commit()
        db.close()

        return {"ok": True}

    except Exception as e:
        print("❌ ERRO DELETE:", str(e))
        return {"erro": str(e)}


@app.get("/fix-db")
def fix_db():
    from sqlalchemy import text

    try:
        db = SessionLocal()
        db.execute(text("ALTER TABLE documentos ADD COLUMN caminho TEXT;"))
        db.commit()
        db.close()
        return {"ok": True, "msg": "Coluna criada!"}
    except Exception as e:
        return {"erro": str(e)}