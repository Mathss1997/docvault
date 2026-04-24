from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Documento(Base):
    __tablename__ = "documentos"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String)
    categoria = Column(String)
    caminho = Column(String)
    usuario = Column(String)
    data = Column(String)

    from sqlalchemy import Column, Integer, String

class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True)
    senha = Column(String)
    tipo = Column(String)  # admin ou user