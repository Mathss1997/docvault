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

    numero       = Column(String)
    ano          = Column(String)
    data_doc     = Column(String)
    assunto      = Column(String)
    responsavel  = Column(String)
    orgao        = Column(String)
    valor        = Column(String)
    situacao     = Column(String)
    extras       = Column(Text, default="{}")
    tags_csv     = Column(Text, default="")
    criado_em    = Column(String)
    atualizado_em = Column(String)

    documento = relationship("Documento", back_populates="indexador")


class Usuario(Base):
    __tablename__ = "usuarios"

    id       = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True)
    senha    = Column(String)
    tipo     = Column(String)


class LogAtividade(Base):
    """
    Registro imutável de todas as ações relevantes do sistema.
    Nunca atualizado — apenas inserido.
    """
    __tablename__ = "logs_atividade"

    id         = Column(Integer, primary_key=True, index=True)

    # Quem fez
    usuario    = Column(String, index=True, nullable=False)

    # O que fez — valores fixos:
    # LOGIN | LOGOUT | UPLOAD | DOWNLOAD | DELETE | CREATE_FOLDER | INDEXAR
    acao       = Column(String, index=True, nullable=False)

    # Detalhes livres (nome do arquivo, pasta, etc.)
    detalhe    = Column(Text)

    # Contexto adicional (categoria, caminho, etc.)
    contexto   = Column(String)

    # IP de origem
    ip         = Column(String)

    # Timestamp ISO completo — nunca nulo
    criado_em  = Column(String, index=True, nullable=False)
