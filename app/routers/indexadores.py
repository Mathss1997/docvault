"""
Rotas de indexadores — adicionar ao main.py via include_router ou copiar diretamente.
"""
import json
from fastapi import APIRouter, Request, HTTPException, Body, Query
from app.database import SessionLocal
from app.models import Documento, Indexador, Tag, tag_documento
from sqlalchemy import or_, and_

router = APIRouter(prefix="/indexadores", tags=["indexadores"])

# ─── schemas de campos estruturados por categoria ───────────────────────────
CAMPOS_CATEGORIA = {
    "empenhos": [
        {"key": "numero",       "label": "Nº do Empenho",    "type": "text"},
        {"key": "ano",          "label": "Ano",               "type": "text"},
        {"key": "data_doc",     "label": "Data do Empenho",   "type": "date"},
        {"key": "responsavel",  "label": "Ordenador",         "type": "text"},
        {"key": "orgao",        "label": "Unidade Gestora",   "type": "text"},
        {"key": "valor",        "label": "Valor (R$)",        "type": "text"},
        {"key": "assunto",      "label": "Objeto / Descrição","type": "textarea"},
        {"key": "situacao",     "label": "Situação",          "type": "select",
         "options": ["Ativo", "Encerrado", "Pendente", "Cancelado"]},
        # extras específicos
        {"key": "fornecedor",   "label": "Fornecedor",        "type": "text",   "extra": True},
        {"key": "fonte",        "label": "Fonte de Recurso",  "type": "text",   "extra": True},
        {"key": "programa",     "label": "Programa",          "type": "text",   "extra": True},
    ],
    "licitacoes": [
        {"key": "numero",       "label": "Nº do Processo",    "type": "text"},
        {"key": "ano",          "label": "Ano",               "type": "text"},
        {"key": "data_doc",     "label": "Data de Abertura",  "type": "date"},
        {"key": "responsavel",  "label": "Pregoeiro / Resp.", "type": "text"},
        {"key": "orgao",        "label": "Órgão Licitante",   "type": "text"},
        {"key": "valor",        "label": "Valor Estimado",    "type": "text"},
        {"key": "assunto",      "label": "Objeto",            "type": "textarea"},
        {"key": "situacao",     "label": "Situação",          "type": "select",
         "options": ["Em andamento", "Homologada", "Revogada", "Deserta", "Encerrada"]},
        {"key": "modalidade",   "label": "Modalidade",        "type": "select",  "extra": True,
         "options": ["Pregão Eletrônico", "Pregão Presencial", "Concorrência",
                     "Tomada de Preços", "Convite", "Dispensa", "Inexigibilidade"]},
        {"key": "fornecedor",   "label": "Vencedor",          "type": "text",   "extra": True},
    ],
    "contratos": [
        {"key": "numero",       "label": "Nº do Contrato",    "type": "text"},
        {"key": "ano",          "label": "Ano",               "type": "text"},
        {"key": "data_doc",     "label": "Data de Assinatura","type": "date"},
        {"key": "responsavel",  "label": "Gestor do Contrato","type": "text"},
        {"key": "orgao",        "label": "Órgão",             "type": "text"},
        {"key": "valor",        "label": "Valor Total",       "type": "text"},
        {"key": "assunto",      "label": "Objeto",            "type": "textarea"},
        {"key": "situacao",     "label": "Situação",          "type": "select",
         "options": ["Vigente", "Encerrado", "Rescindido", "Em renovação"]},
        {"key": "fornecedor",   "label": "Contratada",        "type": "text",   "extra": True},
        {"key": "vigencia",     "label": "Vigência",          "type": "text",   "extra": True},
        {"key": "aditivo",      "label": "Aditivos",          "type": "text",   "extra": True},
    ],
}

CAMPOS_GENERICOS = [
    {"key": "numero",      "label": "Número / Referência", "type": "text"},
    {"key": "ano",         "label": "Ano",                 "type": "text"},
    {"key": "data_doc",    "label": "Data do Documento",   "type": "date"},
    {"key": "assunto",     "label": "Assunto",             "type": "textarea"},
    {"key": "responsavel", "label": "Responsável",         "type": "text"},
    {"key": "orgao",       "label": "Órgão / Setor",       "type": "text"},
    {"key": "valor",       "label": "Valor (R$)",          "type": "text"},
    {"key": "situacao",    "label": "Situação",            "type": "select",
     "options": ["Ativo", "Encerrado", "Pendente", "Cancelado"]},
]


# ─── helpers ────────────────────────────────────────────────────────────────

def require_auth(request: Request):
    if "user" not in request.session:
        raise HTTPException(401, "Não autenticado")
    return {"username": request.session["user"], "tipo": request.session["tipo"]}


def get_or_create_tag(db, nome: str) -> Tag:
    nome = nome.strip().lower()[:60]
    tag = db.query(Tag).filter(Tag.nome == nome).first()
    if not tag:
        tag = Tag(nome=nome)
        db.add(tag)
        db.flush()
    return tag


def indexador_to_dict(idx: Indexador) -> dict:
    extras = {}
    try:
        extras = json.loads(idx.extras or "{}")
    except Exception:
        pass
    return {
        "id":           idx.id,
        "documento_id": idx.documento_id,
        "numero":       idx.numero,
        "ano":          idx.ano,
        "data_doc":     idx.data_doc,
        "assunto":      idx.assunto,
        "responsavel":  idx.responsavel,
        "orgao":        idx.orgao,
        "valor":        idx.valor,
        "situacao":     idx.situacao,
        "extras":       extras,
        "tags":         [t.nome for t in (idx.tags or [])],
        "criado_em":    idx.criado_em,
        "atualizado_em": idx.atualizado_em,
    }


# ─── GET /indexadores/campos?categoria=empenhos ─────────────────────────────
@router.get("/campos")
def get_campos(categoria: str = ""):
    campos = CAMPOS_CATEGORIA.get(categoria.lower(), CAMPOS_GENERICOS)
    return {"campos": campos}


# ─── GET /indexadores/tags — autocomplete ───────────────────────────────────
@router.get("/tags")
def list_tags(request: Request, q: str = ""):
    require_auth(request)
    db = SessionLocal()
    try:
        query = db.query(Tag)
        if q:
            query = query.filter(Tag.nome.ilike(f"%{q}%"))
        tags = query.order_by(Tag.nome).limit(30).all()
        return [t.nome for t in tags]
    finally:
        db.close()


# ─── GET /indexadores/{documento_id} ────────────────────────────────────────
@router.get("/{documento_id}")
def get_indexador(documento_id: int, request: Request):
    require_auth(request)
    db = SessionLocal()
    try:
        idx = db.query(Indexador).filter(Indexador.documento_id == documento_id).first()
        if not idx:
            return {"indexador": None}
        return {"indexador": indexador_to_dict(idx)}
    finally:
        db.close()


# ─── POST /indexadores/{documento_id} — salvar / atualizar ──────────────────
@router.post("/{documento_id}")
def salvar_indexador(documento_id: int, request: Request, data: dict = Body(...)):
    require_auth(request)
    db = SessionLocal()
    try:
        doc = db.query(Documento).filter(Documento.id == documento_id).first()
        if not doc:
            raise HTTPException(404, "Documento não encontrado")

        # separa campos fixos de extras
        campos_fixos = {"numero", "ano", "data_doc", "assunto",
                        "responsavel", "orgao", "valor", "situacao"}
        fixos  = {k: v for k, v in data.items() if k in campos_fixos}
        extras = {k: v for k, v in data.items()
                  if k not in campos_fixos and k != "tags"}
        tags_raw = data.get("tags", [])

        idx = db.query(Indexador).filter(Indexador.documento_id == documento_id).first()
        if not idx:
            idx = Indexador(documento_id=documento_id)
            db.add(idx)

        # atualiza fixos
        for k, v in fixos.items():
            setattr(idx, k, v or None)

        idx.extras = json.dumps(extras, ensure_ascii=False)

        # atualiza tags
        idx.tags = []
        db.flush()
        for t in tags_raw:
            if t.strip():
                idx.tags.append(get_or_create_tag(db, t))

        from datetime import datetime
        idx.atualizado_em = str(datetime.now())

        db.commit()
        db.refresh(idx)
        return {"ok": True, "indexador": indexador_to_dict(idx)}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Erro ao salvar indexador: {e}")
    finally:
        db.close()


# ─── GET /indexadores/busca — busca avançada ────────────────────────────────
@router.get("/busca/avancada")
def busca_avancada(
    request: Request,
    q:           str = Query("", description="Busca livre (nome do arquivo ou assunto)"),
    categoria:   str = Query(""),
    numero:      str = Query(""),
    ano:         str = Query(""),
    responsavel: str = Query(""),
    orgao:       str = Query(""),
    situacao:    str = Query(""),
    tags:        str = Query("", description="tags separadas por vírgula"),
    data_de:     str = Query(""),
    data_ate:    str = Query(""),
):
    require_auth(request)
    db = SessionLocal()
    try:
        query = (
            db.query(Documento, Indexador)
            .outerjoin(Indexador, Indexador.documento_id == Documento.id)
        )

        # filtros no Documento
        if q:
            query = query.filter(
                or_(
                    Documento.nome.ilike(f"%{q}%"),
                    Indexador.assunto.ilike(f"%{q}%"),
                    Indexador.numero.ilike(f"%{q}%"),
                )
            )
        if categoria:
            query = query.filter(Documento.categoria == categoria)

        # filtros no Indexador
        if numero:
            query = query.filter(Indexador.numero.ilike(f"%{numero}%"))
        if ano:
            query = query.filter(Indexador.ano == ano)
        if responsavel:
            query = query.filter(Indexador.responsavel.ilike(f"%{responsavel}%"))
        if orgao:
            query = query.filter(Indexador.orgao.ilike(f"%{orgao}%"))
        if situacao:
            query = query.filter(Indexador.situacao == situacao)
        if data_de:
            query = query.filter(Indexador.data_doc >= data_de)
        if data_ate:
            query = query.filter(Indexador.data_doc <= data_ate)

        # filtro por tags
        if tags:
            tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()]
            for tag_nome in tag_list:
                query = query.filter(
                    Documento.id.in_(
                        db.query(tag_documento.c.documento_id)
                        .join(Tag, Tag.id == tag_documento.c.tag_id)
                        .filter(Tag.nome == tag_nome)
                        .scalar_subquery()
                    )
                )

        rows = query.order_by(Documento.data.desc()).limit(200).all()

        resultados = []
        for doc, idx in rows:
            item = {
                "id":       doc.id,
                "nome":     doc.nome,
                "categoria": doc.categoria,
                "caminho":  doc.caminho or "",
                "usuario":  doc.usuario,
                "data":     doc.data,
                "indexador": indexador_to_dict(idx) if idx else None,
            }
            resultados.append(item)

        return {"total": len(resultados), "resultados": resultados}

    finally:
        db.close()


# ─── GET /indexadores/lista — todos indexados (para a seção Indexadores) ────
@router.get("/lista/todos")
def listar_todos(request: Request, categoria: str = ""):
    require_auth(request)
    db = SessionLocal()
    try:
        query = (
            db.query(Documento, Indexador)
            .join(Indexador, Indexador.documento_id == Documento.id)
        )
        if categoria:
            query = query.filter(Documento.categoria == categoria)
        rows = query.order_by(Documento.data.desc()).limit(500).all()
        return {
            "total": len(rows),
            "resultados": [
                {
                    "id":        doc.id,
                    "nome":      doc.nome,
                    "categoria": doc.categoria,
                    "caminho":   doc.caminho or "",
                    "usuario":   doc.usuario,
                    "data":      doc.data,
                    "indexador": indexador_to_dict(idx),
                }
                for doc, idx in rows
            ],
        }
    finally:
        db.close()