from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class UserSession(Base):
    """セッション情報の管理モデル"""
    __tablename__ = 'user_sessions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False)  # ユーザーのメールアドレス
    cookie_data = Column(Text, nullable=False)  # Cookie情報のJSON文字列
    is_active = Column(Boolean, default=True)  # セッション有効フラグ
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)  # 最終更新日時

class Work(Base):
    """作品データの管理モデル"""
    __tablename__ = 'works'

    id = Column(String(50), primary_key=True)  # 作品のCID (contentId)
    title = Column(String(500), nullable=False)  # 作品タイトル
    circle = Column(String(255))  # サークル名 (makerName)
    genre = Column(String(100))  # 大分類ジャンル
    is_unavailable = Column(Boolean, default=False)  # 販売停止フラグ
    is_streaming = Column(Boolean, default=False)  # ストリーミング対応フラグ
    purchase_date = Column(String(50))  # 購入日時
    is_mylist_registered = Column(Boolean, default=False)  # マイリスト登録フラグ
    mylists = Column(Text)  # 所属マイリスト一覧 (JSON配列形式)
    main_image = Column(Text)  # メイン画像URL
    price = Column(Integer)  # 価格 (現在の販売価格、互換性維持)
    list_price = Column(Integer, default=0)  # 定価 (サークル設定価格)
    sale_price = Column(Integer)  # セール価格 (割引適用後の実売価格)
    purchase_price = Column(Integer)  # 購入価格 (ユーザー手動設定)
    campaign_text = Column(String(100))  # セール情報テキスト (例: "80%OFF")
    description = Column(Text)  # あらすじ
    sample_images = Column(Text)  # サンプル画像URL一覧 (JSON配列形式)
    author = Column(Text)  # 作者一覧 (JSON配列形式)
    specifications = Column(Text)  # 詳細スペック情報 (JSON辞書形式)
    local_path = Column(Text)  # ローカルファイルの絶対パス
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)  # 最終更新日時
