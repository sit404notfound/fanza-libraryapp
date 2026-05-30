import os
import re
import time
import queue
import threading
import urllib.parse
import requests
from bs4 import BeautifulSoup
from fanza_api import parse_cookie_json
from database import db_session
from models import Work
from logger import fanza_logger

class DownloadManager:
    """ダウンロード管理クラス"""
    def __init__(self):
        self.downloads = {}  # 各作品のダウンロード進捗状況 {cid: {percent, status, file_size}}
        self._lock = threading.Lock()
        self.download_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'downloads')
        
        # 保存ディレクトリの作成
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)

        # 設定のロードおよび自動スキャンの非同期実行
        self.load_settings()
        threading.Thread(target=self.scan_local_files, daemon=True).start()

    def load_settings(self):
        """settings.jsonから設定をロードする"""
        settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings.json')
        if os.path.exists(settings_path):
            try:
                import json
                with open(settings_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    dl_dir = data.get('download_dir')
                    if dl_dir and os.path.exists(dl_dir) and os.path.isdir(dl_dir):
                        self.download_dir = dl_dir
                        fanza_logger.info(f"[SETTINGS] 設定をロードしました。保存先: {self.download_dir}")
            except Exception as e:
                fanza_logger.error(f"[SETTINGS] 設定ファイルのロード失敗: {str(e)}")

    def save_settings(self):
        """settings.jsonに現在の設定を保存する"""
        settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings.json')
        try:
            import json
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump({"download_dir": self.download_dir}, f, ensure_ascii=False, indent=4)
                fanza_logger.info(f"[SETTINGS] 設定を保存しました。保存先: {self.download_dir}")
        except Exception as e:
            fanza_logger.error(f"[SETTINGS] 設定ファイルの保存失敗: {str(e)}")

    def scan_local_files(self):
        """保存先ディレクトリをスキャンし、存在するファイルをデータベースのWorkレコードに紐づける"""
        fanza_logger.info(f"[SCAN] ローカルファイルのスキャンを開始します: Dir={self.download_dir}")
        if not os.path.exists(self.download_dir) or not os.path.isdir(self.download_dir):
            fanza_logger.warning(f"[SCAN] スキャン対象のディレクトリが存在しません: {self.download_dir}")
            return
            
        try:
            items = os.listdir(self.download_dir)
            fanza_logger.info(f"[SCAN] 検出されたファイル/フォルダ数: {len(items)}")
            
            works = db_session.query(Work).all()
            updated_count = 0
            
            for work in works:
                cid = work.id
                matched_item = None
                for item in items:
                    if item.startswith('.') or item == '.temp':
                        continue
                        
                    # CIDがファイル名やフォルダ名に含まれているか部分一致でチェック
                    if cid.lower() in item.lower():
                        if item.lower().endswith(('.tmp', '.part', '.download')):
                            continue
                        matched_item = item
                        break
                
                if matched_item:
                    full_path = os.path.abspath(os.path.join(self.download_dir, matched_item))
                    if work.local_path != full_path:
                        work.local_path = full_path
                        updated_count += 1
                        fanza_logger.info(f"[SCAN] 紐付け成功: CID={cid} -> Path={full_path}")
                else:
                    if work.local_path:
                        # 紐付いていたパスが存在しなくなった場合は紐付けを解除
                        if not os.path.exists(work.local_path):
                            work.local_path = None
                            updated_count += 1
                            fanza_logger.info(f"[SCAN] 紐付け解除 (実ファイル消失): CID={cid}")
                            
            if updated_count > 0:
                db_session.commit()
                fanza_logger.info(f"[SCAN] スキャン完了: {updated_count} 件のレコードを更新しました。")
            else:
                fanza_logger.info("[SCAN] スキャン完了: 更新が必要なレコードはありませんでした。")
                
        except Exception as e:
            db_session.rollback()
            fanza_logger.error(f"[SCAN] スキャン中にエラーが発生しました: {str(e)}", exc_info=True)

    def set_download_dir(self, path):
        """保存先ディレクトリの設定処理"""
        with self._lock:
            if os.path.exists(path) and os.path.isdir(path):
                self.download_dir = path
                self.save_settings()
                # ディレクトリ変更後に自動スキャンをスレッドで起動してDBに即反映する
                threading.Thread(target=self.scan_local_files, daemon=True).start()
                return True
            return False

    def get_status(self, cid):
        """進捗状況の取得処理"""
        with self._lock:
            status = self.downloads.get(cid, {"percent": 0, "status": "IDLE"})
            # 完了状態であるのに実ファイルが存在しない場合はIDLEへ初期化
            if status.get("status") == "COMPLETED":
                work = db_session.query(Work).filter_by(id=cid).first()
                if not work or not work.local_path or not os.path.exists(work.local_path):
                    status = {"percent": 0, "status": "IDLE", "message": ""}
                    self.downloads[cid] = status
            return status

    def start_download(self, cookie_json, cid):
        """ダウンロードの開始処理"""
        with self._lock:
            if cid in self.downloads and self.downloads[cid]["status"] == "DOWNLOADING":
                return False
            self.downloads[cid] = {"percent": 0, "status": "STARTING", "file_size": 0}

        thread = threading.Thread(target=self._run_download, args=(cookie_json, cid))
        thread.daemon = True
        thread.start()
        return True

    def _run_download(self, cookie_json, cid):
        """ダウンロード実行処理 (バックグラウンド実行)"""
        fanza_logger.info(f"[DOWNLOAD] 開始: contentId={cid}")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.dmm.co.jp/dc/-/mylibrary/"
        }
        cookies = parse_cookie_json(cookie_json)

        try:
            # 1. 詳細APIの解析
            self._update_status(cid, 0, "PREPARING", "詳細APIの取得中...")
            api_url = f"https://www.dmm.co.jp/dc/doujin/api/mylibraries/details/{cid}/"
            fanza_logger.info(f"[DOWNLOAD] 詳細API: {api_url}")
            
            res = requests.get(api_url, headers=headers, cookies=cookies, timeout=15)
            fanza_logger.info(f"[DOWNLOAD] 詳細API取得レスポンス: status_code={res.status_code}")
            if res.status_code != 200:
                err_msg = f"詳細APIの取得に失敗 (HTTP {res.status_code})"
                self._update_status(cid, 0, "FAILED", err_msg)
                fanza_logger.error(f"[DOWNLOAD] エラー: {err_msg}")
                return

            api_data = res.json()
            if api_data.get('error_code') != 0:
                err_msg = f"詳細APIエラー (code: {api_data.get('error_code')})"
                self._update_status(cid, 0, "FAILED", err_msg)
                fanza_logger.error(f"[DOWNLOAD] エラー: {err_msg}")
                return

            detail = api_data.get('data', {})
            download_links = detail.get('downloadLinks', {})
            file_size_str = detail.get('fileSize', '')
            
            download_url = None
            if download_links:
                # "1"キーを最優先し、存在しなければ最初のエントリを取得
                download_url = download_links.get("1") or next(iter(download_links.values()), None)

            if not download_url:
                err_msg = "ダウンロードリンクの検出に失敗 (購入済みライブラリへのログインセッション切れ、または一時的なサーバーエラーの可能性)"
                self._update_status(cid, 0, "FAILED", err_msg)
                fanza_logger.error(f"[DOWNLOAD] エラー: {err_msg}")
                return

            # 相対URLの補完
            download_url = urllib.parse.urljoin("https://www.dmm.co.jp", download_url)
            fanza_logger.info(f"[DOWNLOAD] 検出されたダウンロードURL: {download_url} (サイズ: {file_size_str})")

            # ファイル名の決定 (サークル名とタイトルを付与)
            maker_name = detail.get('makerName', '').strip()
            title = detail.get('title', '').strip()
            
            if maker_name and title:
                file_name = f"[{maker_name}] {title} ({cid}).zip"
            else:
                file_name = f"{cid}.zip"
            
            # 安全なファイル名へのクレンジング
            file_name = re.sub(r'[\\/*?:"<>|]', '_', file_name)
            save_path = os.path.join(self.download_dir, file_name)
            fanza_logger.info(f"[DOWNLOAD] 保存先パス: {save_path}")

            self._update_status(cid, 5, "DOWNLOADING", "ダウンロード接続中...")

            # 2. ファイルのダウンロードと保存
            fanza_logger.info(f"[DOWNLOAD] ファイルサーバーへリクエスト送信: {download_url}")
            res_file = requests.get(download_url, headers=headers, cookies=cookies, stream=True, timeout=60)
            fanza_logger.info(f"[DOWNLOAD] ファイルレスポンス: status_code={res_file.status_code}")
            if res_file.status_code != 200:
                err_msg = f"ファイルの取得に失敗 (HTTP {res_file.status_code})"
                self._update_status(cid, 0, "FAILED", err_msg)
                fanza_logger.error(f"[DOWNLOAD] エラー: {err_msg}")
                return

            total_length = res_file.headers.get('content-length')
            if total_length is None:
                total_length = 0
                fanza_logger.warning("[DOWNLOAD] Content-Length がヘッダーに存在しません。進捗予測なしでダウンロードします。")
            else:
                total_length = int(total_length)
                fanza_logger.info(f"[DOWNLOAD] ファイルサイズ: {total_length // 1024 // 1024}MB ({total_length} bytes)")

            self._update_status(cid, 10, "DOWNLOADING", "ダウンロード中...")

            downloaded = 0
            last_log_time = time.time()
            with open(save_path, 'wb') as f:
                for chunk in res_file.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        # 5秒ごとにログに出力
                        current_time = time.time()
                        if current_time - last_log_time > 5.0:
                            if total_length > 0:
                                fanza_logger.info(f"[DOWNLOAD] 進行中: {downloaded // 1024 // 1024}MB / {total_length // 1024 // 1024}MB ({int((downloaded / total_length) * 100)}%)")
                            else:
                                fanza_logger.info(f"[DOWNLOAD] 進行中: {downloaded // 1024 // 1024}MB 取得済み")
                            last_log_time = current_time

                        if total_length > 0:
                            percent = int(10 + (downloaded / total_length) * 85)
                            self._update_status(cid, percent, "DOWNLOADING", f"ダウンロード中 ({downloaded // 1024 // 1024}MB / {total_length // 1024 // 1024}MB)")
                        else:
                            self._update_status(cid, 50, "DOWNLOADING", f"ダウンロード中 ({downloaded // 1024 // 1024}MB)")

            fanza_logger.info(f"[DOWNLOAD] ファイルのローカル書き出し完了: {downloaded} bytes")

            # 3. データベースへの登録
            self._update_status(cid, 95, "SAVING", "データベースへの登録中...")
            
            work = db_session.query(Work).filter_by(id=cid).first()
            if work:
                work.local_path = os.path.abspath(save_path)
                db_session.commit()
                fanza_logger.info(f"[DOWNLOAD] データベースに local_path={work.local_path} を登録しました。")
            else:
                fanza_logger.warning(f"[DOWNLOAD] 警告: CID={cid} がデータベース内に存在しないため、パス登録をスキップしました。")
                
            self._update_status(cid, 100, "COMPLETED", "ダウンロード完了")
            fanza_logger.info(f"[DOWNLOAD] 正常完了: CID={cid}")

        except Exception as e:
            err_msg = f"ダウンロードエラー: {str(e)}"
            self._update_status(cid, 0, "FAILED", err_msg)
            fanza_logger.error(f"[DOWNLOAD] 例外エラー: {err_msg}", exc_info=True)

    def _update_status(self, cid, percent, status, message=""):
        """進捗ステータスの更新処理"""
        with self._lock:
            self.downloads[cid] = {
                "percent": percent,
                "status": status,
                "message": message
            }

# グローバルなダウンロードマネージャーインスタンスの作成
download_manager = DownloadManager()
