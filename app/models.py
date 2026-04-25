from sqlalchemy import Column, Integer, String, Text, ForeignKey, Table
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

# ─── Tabela de associação (declarada ANTES dos modelos que a usam) ───────────
tag_documento = Table(
    "tag_documento",
    Base.metadata,
    Column("documento_id", Integer, ForeignKey("documentos.id"), primary_key=True),
    Column("tag_id",       Integer, ForeignKey("tags.id"),       primary_key=True),
)


class Documento(Base):
    __tablename__ = "documentos"

    id        = Column(Integer, primary_key=True, index=True)
    nome      = Column(String)
    categoria = Column(String)
    caminho   = Column(String)
    usuario   = Column(String)
    data      = Column(String)

    indexador = relationship(
        "Indexador",
        back_populates="documento",
        uselist=False,
        cascade="all, delete-orphan",
    )


class Tag(Base):
    __tablename__ = "tags"

    id   = Column(Integer, primary_key=True, index=True)
    nome = Column(String, unique=True, index=True)


class Indexador(Base):
    __tablename__ = "indexadores"

    id           = Column(Integer, primary_key=True, index=True)
    documento_id = Column(Integer, ForeignKey("documentos.id"), unique=True, nullable=False)

    # Campos genéricos
    numero       = Column(String)
    ano          = Column(String)
    data_doc     = Column(String)
    assunto      = Column(String)
    responsavel  = Column(String)
    orgao        = Column(String)
    valor        = Column(String)
    situacao     = Column(String)

    # Campos extras por categoria (JSON serializado)
    extras       = Column(Text, default="{}")

    # Timestamps
    criado_em    = Column(String)
    atualizado_em = Column(String)

    # Relacionamentos
    documento = relationship("Documento", back_populates="indexador")

    tags = relationship(
        "Tag",
        secondary=tag_documento,   # objeto Table direto, não string
        lazy="joined",
    )


class Usuario(Base):
    __tablename__ = "usuarios"

    id       = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True)
    senha    = Column(String)
    tipo     = Column(String)