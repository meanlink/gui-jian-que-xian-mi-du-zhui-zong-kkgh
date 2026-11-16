from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models

# 已有部署的轻量列升级；create_all 不会修改已存在表结构。
COLUMN_UPGRADES = {
    'datasets': {
        'row_count': 'INTEGER DEFAULT 0',
        'storage_state': "VARCHAR(20) DEFAULT 'online'",
    },
    'jobs': {
        'wait_reason': "VARCHAR(400) DEFAULT ''",
    },
}

def _add_missing_columns():
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in COLUMN_UPGRADES.items():
            if table not in tables:
                continue
            existing = {column['name'] for column in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
        if 'datasets' in tables:
            conn.execute(text("UPDATE datasets SET storage_state = 'online' WHERE storage_state IS NULL"))
        if 'jobs' in tables:
            conn.execute(text("UPDATE jobs SET wait_reason = '' WHERE wait_reason IS NULL"))
    # 老部署新增列后，用 JSON 实际长度回填原始点数；清理冷存后仍可追溯规模。
    if 'datasets' in tables:
        from sqlalchemy import select
        from src.models import Dataset
        from src.config.database import Session
        with Session() as db:
            for dataset in db.scalars(select(Dataset).where(Dataset.row_count == 0)):
                if dataset.records:
                    dataset.row_count = len(dataset.records)
            db.commit()

def migrate():
    Base.metadata.create_all(engine)
    _add_missing_columns()
if __name__=='__main__':migrate()
