from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Table
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()


class Documento(Base):
    __tablename__ = "documentos"

    id        = Column(Integer, primary_key=True, index=True)
    nome      = Column(String)
    categoria = Column(String)
    caminho   = Column(String)
    usuario   = Column(String)
    data      = Column(String)

    # relacionamentos
    indexador = relationship("Indexador", back_populates="documento",
                             uselist=False, cascade="all, delete-orphan")


class Usuario(Base):
    __tablename__ = "usuarios"

    id       = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True)
    senha    = Column(String)
    tipo     = Column(String)   # admin | user


class Indexador(Base):
    """
    Campos estruturados (fixos) vinculados a um documento.
    Campos genéricos que funcionam para qualquer categoria.
    Campos específicos de categoria ficam em 'extras' (JSON serializado).
    """
    __tablename__ = "indexadores"

    id          = Column(Integer, primary_key=True, index=True)
    documento_id = Column(Integer, ForeignKey("documentos.id"), unique=True, nullable=False)

    # ── Campos genéricos (qualquer categoria) ──────────────────
    numero      = Column(String)      # nº do documento / processo
    ano         = Column(String)      # ano de referência
    data_doc    = Column(String)      # data do documento (não do upload)
    assunto     = Column(String)      # descrição resumida
    responsavel = Column(String)      # pessoa/setor responsável
    orgao       = Column(String)      # órgão / departamento
    valor       = Column(String)      # valor (R$) — string para flexibilidade
    situacao    = Column(String)      # Ativo | Encerrado | Pendente | Cancelado

    # ── Campos específicos por categoria (JSON) ─────────────────
    # Ex: {"fornecedor": "Empresa X", "modalidade": "Pregão", ...}
    extras      = Column(Text, default="{}")

    # ── Tags livres ─────────────────────────────────────────────
    # armazenadas separadas na tabela Tag, relacionamento N:N via TagDocumento
    tags        = relationship("Tag", secondary="tag_documento",
                               back_populates="documentos", lazy="joined")

    # relacionamento inverso
    documento   = relationship("Documento", back_populates="indexador")

    criado_em   = Column(String, default=lambda: str(datetime.now()))
    atualizado_em = Column(String, default=lambda: str(datetime.now()),
                           onupdate=lambda: str(datetime.now()))


class Tag(Base):
    __tablename__ = "tags"

    id   = Column(Integer, primary_key=True, index=True)
    nome = Column(String, unique=True, index=True)   # normalizado em lowercase

    documentos = relationship("Documento", secondary="tag_documento",
                              back_populates=None)


# Tabela de associação Indexador ↔ Tag (via documento)
tag_documento = Table(
    "tag_documento",
    Base.metadata,
    Column("documento_id", Integer, ForeignKey("documentos.id"), primary_key=True),
    Column("tag_id",       Integer, ForeignKey("tags.id"),       primary_key=True),
)

# Corrige back_populates após declaração da tabela intermediária
Tag.documentos = relationship("Documento", secondary=tag_documento)