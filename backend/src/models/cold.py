from sqlalchemy import String, Double, Integer, BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class ColdArchive(Base):
    """批次冷存副本的台账。每个批次只有一条记录，重试复用同一条。"""
    __tablename__ = 'cold_archives'
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'), unique=True)
    state: Mapped[str] = mapped_column(String(20), default='queued')
    operation: Mapped[str] = mapped_column(String(20), default='archive')
    object_key: Mapped[str] = mapped_column(String(200), default='')
    manifest_key: Mapped[str] = mapped_column(String(200), default='')
    content_checksum: Mapped[str] = mapped_column(String(64), default='')
    file_checksum: Mapped[str] = mapped_column(String(64), default='')
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    bytes_done: Mapped[int] = mapped_column(BigInteger, default=0)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[str] = mapped_column(String(60), default='')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    restore_attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(String(600), default='')
    blocked_reason: Mapped[str] = mapped_column(String(400), default='')
    sealed_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    released_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    restored_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    created_at: Mapped[float] = mapped_column(Double)
    updated_at: Mapped[float] = mapped_column(Double)
