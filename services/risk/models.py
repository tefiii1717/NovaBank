from sqlalchemy import Column, String, Float, DateTime
from datetime import datetime
from database import Base

class RiskValidation(Base):
    __tablename__ = "risk_validations"

    idempotency_key = Column(String, primary_key=True, index=True)
    numero_cuenta = Column(String, nullable=False)
    monto = Column(Float, nullable=False)
    resultado = Column(String, nullable=False)
    creado_en = Column(DateTime, default=datetime.utcnow)
