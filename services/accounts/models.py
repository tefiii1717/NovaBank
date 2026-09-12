from sqlalchemy import Column, String, Float, DateTime
from datetime import datetime
from database import Base

class Account(Base):
    __tablename__ = "accounts"

    numero_cuenta = Column(String, primary_key=True, index=True)
    saldo = Column(Float, nullable=False, default=0.0)

class ProcessedRequest(Base):
    __tablename__ = "processed_requests"

    idempotency_key = Column(String, primary_key=True, index=True)
    resultado = Column(String, nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)
