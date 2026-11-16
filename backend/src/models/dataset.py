from sqlalchemy import String, JSON, Double, Integer
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Dataset(Base):
    __tablename__ = 'datasets'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    source: Mapped[str] = mapped_column(String(200), default='manual.json')
    records: Mapped[list] = mapped_column(JSON, default=list)
    checksum: Mapped[str] = mapped_column(String(64))
    # 原始点总数独立保存，在线原始点释放后仍可追溯批次规模。
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    # online / archiving / cold / restoring
    storage_state: Mapped[str] = mapped_column(String(20), default='online')
    created_at: Mapped[float] = mapped_column(Double)
