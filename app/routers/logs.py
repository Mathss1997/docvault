"""
Router de logs de atividade.
Coloque em app/routers/logs.py
Inclua no main.py: app.include_router(logs_router)
"""
from fastapi import APIRouter, Request, HTTPException, Query
from app.database import SessionLocal
from app.models import LogAtividade

router = APIRouter(prefix="/logs", tags=["logs"])

# ─── Ícones e cores por ação ─────────────────────────────────────────────────
META_ACAO = {
    "LOGIN":         {"icon": "🔑", "label": "Login",            "color": "blue"},
    "LOGOUT":        {"icon": "🚪", "label": "Logout",           "color": "slate"},
    "UPLOAD":        {"icon": "📤", "label": "Upload",           "color": "green"},
    "DOWNLOAD":      {"icon": "📥", "label": "Download",         "color": "teal"},
    "DELETE":        {"icon": "🗑",  "label": "Exclusão",         "color": "rose"},
    "CREATE_FOLDER": {"icon": "📁", "label": "Nova pasta",       "color": "amber"},
    "INDEXAR":       {"icon": "⊛",  "label": "Indexação",        "color": "violet"},
}


def require_admin(request: Request):
    if request.session.get("tipo") != "admin":
        raise HTTPException(403, "Acesso restrito a administradores")


def log_to_dict(log: LogAtividade) -> dict:
    meta = META_ACAO.get(log.acao, {"icon": "•", "label": log.acao, "color": "slate"})
    return {
        "id":        log.id,
        "usuario":   log.usuario,
        "acao":      log.acao,
        "label":     meta["label"],
        "icon":      meta["icon"],
        "color":     meta["color"],
        "detalhe":   log.detalhe,
        "contexto":  log.contexto,
        "ip":        log.ip,
        "criado_em": log.criado_em,
    }


# ─── GET /logs — listagem com filtros e paginação ────────────────────────────
@router.get("")
def listar_logs(
    request: Request,
    usuario:  str = Query(""),
    acao:     str = Query(""),
    q:        str = Query("", description="Busca livre no detalhe"),
    data_de:  str = Query(""),
    data_ate: str = Query(""),
    page:     int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    require_admin(request)
    db = SessionLocal()
    try:
        query = db.query(LogAtividade)

        if usuario:
            query = query.filter(LogAtividade.usuario.ilike(f"%{usuario}%"))
        if acao:
            query = query.filter(LogAtividade.acao == acao)
        if q:
            query = query.filter(LogAtividade.detalhe.ilike(f"%{q}%"))
        if data_de:
            query = query.filter(LogAtividade.criado_em >= data_de)
        if data_ate:
            # inclui o dia inteiro
            query = query.filter(LogAtividade.criado_em <= data_ate + "T23:59:59")

        total = query.count()
        logs  = (
            query
            .order_by(LogAtividade.criado_em.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        return {
            "total":    total,
            "page":     page,
            "per_page": per_page,
            "pages":    max(1, (total + per_page - 1) // per_page),
            "logs":     [log_to_dict(l) for l in logs],
        }
    finally:
        db.close()


# ─── GET /logs/resumo — contadores para o dashboard ─────────────────────────
@router.get("/resumo")
def resumo(request: Request):
    require_admin(request)
    db = SessionLocal()
    try:
        total   = db.query(LogAtividade).count()
        por_acao = {}
        for acao, meta in META_ACAO.items():
            count = db.query(LogAtividade).filter(LogAtividade.acao == acao).count()
            por_acao[acao] = {"count": count, **meta}

        # últimos 10 eventos
        recentes = (
            db.query(LogAtividade)
            .order_by(LogAtividade.criado_em.desc())
            .limit(10)
            .all()
        )

        return {
            "total":    total,
            "por_acao": por_acao,
            "recentes": [log_to_dict(l) for l in recentes],
        }
    finally:
        db.close()


# ─── GET /logs/acoes — lista de ações disponíveis para filtro ────────────────
@router.get("/acoes")
def listar_acoes(request: Request):
    require_admin(request)
    return [{"value": k, **v} for k, v in META_ACAO.items()]
