import os
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from models import Base

# データベースファイルのパス設定
DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DB_DIR, 'library.db')
DATABASE_URI = f'sqlite:///{DB_PATH}'

# エンジンおよびセッションの初期化
engine = create_engine(DATABASE_URI, connect_args={"check_same_thread": False})
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

Base.query = db_session.query_property()

def init_db():
    """データベーステーブルの作成処理"""
    Base.metadata.create_all(bind=engine)
    
    # 既存のテーブル構造に対するカラム追加マイグレーション
    from sqlalchemy import text
    migrations = [
        "ALTER TABLE works ADD COLUMN list_price INTEGER DEFAULT 0",
        "ALTER TABLE works ADD COLUMN purchase_price INTEGER",
        "ALTER TABLE works ADD COLUMN sale_price INTEGER",
        "ALTER TABLE works ADD COLUMN campaign_text VARCHAR(100)",
    ]
    for sql in migrations:
        try:
            with engine.connect() as conn:
                conn.execute(text(sql))
        except Exception:
            pass
