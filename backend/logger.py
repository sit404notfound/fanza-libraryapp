import logging
from collections import deque
from datetime import datetime

class InMemoryLogHandler(logging.Handler):
    """インメモリでログを蓄積するカスタムハンドラー"""
    def __init__(self, max_len=500):
        super().__init__()
        # スレッドセーフな両端キューによるログの制限付き蓄積
        self.logs = deque(maxlen=max_len)

    def emit(self, record):
        try:
            # ログデータの辞書化
            log_entry = {
                "timestamp": datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S'),
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record)
            }
            self.logs.append(log_entry)
        except Exception:
            self.handleError(record)

    def get_logs(self):
        """蓄積されたログの取得処理"""
        return list(self.logs)

# アプリ共通のグローバルロガー定義
fanza_logger = logging.getLogger("fanza_app")
fanza_logger.setLevel(logging.DEBUG)

# メッセージ用フォーマッターの定義
formatter = logging.Formatter('%(message)s')

# インメモリハンドラーの設定と登録処理
in_memory_handler = InMemoryLogHandler()
in_memory_handler.setFormatter(formatter)
in_memory_handler.setLevel(logging.DEBUG)
fanza_logger.addHandler(in_memory_handler)

# 標準出力用ハンドラーの設定と登録処理
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('[%(levelname)s] %(asctime)s - %(message)s'))
console_handler.setLevel(logging.INFO)
fanza_logger.addHandler(console_handler)
