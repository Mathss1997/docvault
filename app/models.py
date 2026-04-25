from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


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
    # Ex: {"fornecedor": "Empresa X", "modalidade": "Pregão"}
    extras       = Column(Text, default="{}")

    # Tags livres armazenadas como CSV simples
    # Ex: "urgente,2024,prefeitura,contrato"
    # Sem tabela intermediária — mais simples e sem risco de mapper error
    tags_csv     = Column(Text, default="")

    # Timestamps
    criado_em    = Column(String)
    atualizado_em = Column(String)

    documento = relationship("Documento", back_populates="indexador")


class Usuario(Base):
    __tablename__ = "usuarios"

    id       = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True)
    senha    = Column(String)
    tipo     = Column(String)
