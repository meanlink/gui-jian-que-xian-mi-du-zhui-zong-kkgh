import os
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./local.db')
REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')
JWT_SECRET = os.environ.get('JWT_SECRET', 'local-development-change-before-deploy')
ARTIFACT_DIR = os.getenv('ARTIFACT_DIR', '/artifacts')
# 独立冷存卷；与在线数据库、产物目录分离，便于单独扩容和清理。
COLD_STORE_DIR = os.getenv('COLD_STORE_DIR', '/coldstore')
