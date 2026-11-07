import os
from pathlib import Path
from sqlalchemy import create_engine, Integer, BigInteger, String, JSON, ForeignKey, CheckConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATA = Path(os.environ.get('DATA_DIR', 'data'))
DATA.mkdir(parents=True, exist_ok=True)
engine = create_engine(os.environ.get('DATABASE_URL', 'sqlite:///data/sherlock.db'))
Session = sessionmaker(engine, expire_on_commit=False)
class Base(DeclarativeBase): pass
class Refund(Base):
    __tablename__ = 'refund'
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    amount: Mapped[int] = mapped_column(BigInteger)
    importer: Mapped[str] = mapped_column(String)
    date: Mapped[str] = mapped_column(String)
    revision: Mapped[int] = mapped_column(default=0)
    __table_args__ = (CheckConstraint('id = 1'), CheckConstraint('amount > 0'))
class Document(Base):
    __tablename__ = 'document'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String, unique=True)
    path: Mapped[str] = mapped_column(String)
    parsed: Mapped[dict] = mapped_column(JSON)
class ExtractedFact(Base):
    __tablename__ = 'extracted_fact'
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey('document.id'))
    field: Mapped[str] = mapped_column(String)
    value: Mapped[dict] = mapped_column(JSON)
    evidence: Mapped[dict] = mapped_column(JSON)

class Allocation(Base):
    __tablename__ = 'allocation'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String, default='unallocated')
    disposition: Mapped[str] = mapped_column(String, default='unallocated')
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    chain: Mapped[dict] = mapped_column(JSON)
    evidence: Mapped[list] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String)
    issues: Mapped[list] = mapped_column(JSON)
    obligation: Mapped[dict] = mapped_column(JSON)
    reviewed_hold: Mapped[bool] = mapped_column(default=False)
    __table_args__ = (CheckConstraint('amount >= 0'), CheckConstraint('confidence >= 0 AND confidence <= 10000'), CheckConstraint("status IN ('unallocated','auto-proposed','human-confirmed','human-overridden')"))
class Event(Base):
    __tablename__ = 'review_event'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    allocation_id: Mapped[str] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String)
    at: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    before: Mapped[dict] = mapped_column(JSON)
    after: Mapped[dict] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer)
class Artifact(Base):
    __tablename__ = 'artifact'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    csv: Mapped[str] = mapped_column(String)
    memo: Mapped[str] = mapped_column(String)

def init(): Base.metadata.create_all(engine)
