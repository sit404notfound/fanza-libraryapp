import time
import json
import queue
import threading
from datetime import datetime, timedelta
from database import db_session
from models import Work
from fanza_api import fetch_purchased_page, fetch_work_mylists, fetch_detail_html, fetch_detail_html_anonymous
from scraper import parse_detail_html, parse_price_html
from logger import fanza_logger
from downloader import download_manager

class SyncManager:
    """同期処理の管理クラス"""
    def __init__(self):
        self.listeners = []  # SSE接続用キューのリスト
        self.is_running = False  # 同期実行中フラグ
        self.thread = None  # 同期用スレッド
        self._lock = threading.Lock()

    def add_listener(self):
        """SSE接続リスナーの追加処理"""
        q = queue.Queue()
        with self._lock:
            self.listeners.append(q)
        return q

    def remove_listener(self, q):
        """SSE接続リスナーの削除処理"""
        with self._lock:
            if q in self.listeners:
                self.listeners.remove(q)

    def broadcast(self, status, current, total, message):
        """全リスナーへの進捗状況の配信処理"""
        data = {
            "status": status,
            "current": current,
            "total": total,
            "message": message
        }
        payload = json.dumps(data)
        with self._lock:
            for q in self.listeners:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    pass

    def start_sync(self, cookie_json, mode='quick'):
        """同期タスクの開始処理"""
        if self.is_running:
            return False
        
        self.is_running = True
        self.thread = threading.Thread(target=self._run_sync, args=(cookie_json, mode))
        self.thread.daemon = True
        self.thread.start()
        return True

    def _run_sync(self, cookie_json, mode):
        """同期処理の本体 (バックグラウンド実行)"""
        fanza_logger.info(f"[SYNC] 同期処理を開始します (モード: {mode})")
        try:
            self.broadcast("start", 0, 0, f"同期処理を開始中 ({'クイック同期' if mode == 'quick' else 'フル同期'})...")
            
            # 全購入作品リストの構築
            all_items = []
            page = 1
            limit = 50
            
            # クイック同期の場合、1ページ目(最新50件)のみ取得
            if mode == 'quick':
                self.broadcast("processing_list", 0, 0, "購入済み一覧の最新データを取得中...")
                fanza_logger.info("[SYNC] クイック同期: 1ページ目の取得リクエスト送信")
                data = fetch_purchased_page(cookie_json, page=1, limit=limit)
                if data:
                    items_dict = data.get("data", {}).get("items", {})
                    if isinstance(items_dict, dict):
                        for date_key, works in items_dict.items():
                            for w in works:
                                w["purchase_date"] = date_key
                                all_items.append(w)
                fanza_logger.info(f"[SYNC] クイック同期: 最新 {len(all_items)} 件の作品情報を取得")
                time.sleep(1.0)
            # フル同期の場合、全ページをループ取得
            else:
                while True:
                    self.broadcast("processing_list", page * limit, 0, f"購入済み一覧を取得中 (ページ: {page})...")
                    fanza_logger.info(f"[SYNC] フル同期: ページ {page} の取得リクエスト送信")
                    data = fetch_purchased_page(cookie_json, page=page, limit=limit)
                    if not data:
                        fanza_logger.warning(f"[SYNC] ページ {page} のデータ取得結果が空です。巡回を終了します。")
                        break
                    
                    items_dict = data.get("data", {}).get("items", {})
                    page_items_count = 0
                    if isinstance(items_dict, dict):
                        for date_key, works in items_dict.items():
                            for w in works:
                                w["purchase_date"] = date_key
                                all_items.append(w)
                                page_items_count += 1
                                
                    fanza_logger.info(f"[SYNC] ページ {page} から {page_items_count} 件の作品を取得 (累積: {len(all_items)} 件)")
                    if page_items_count == 0:
                        break
                    page += 1
                    time.sleep(1.0)

            total_items = len(all_items)
            fanza_logger.info(f"[SYNC] 購入済み作品リストの構築完了 (合計: {total_items} 件)")
            self.broadcast("processing_detail", 0, total_items, f"合計 {total_items} 件の作品情報を更新中...")

            # 差分終了用カウンター
            diff_count = 0
            
            for index, item in enumerate(all_items):
                cid = item.get("contentId") or item.get("productId")
                if not cid:
                    continue

                title = item.get("title", "")
                fanza_logger.info(f"[SYNC] 詳細更新処理 [{index+1}/{total_items}]: CID={cid}, タイトル={title}")
                self.broadcast("processing_detail", index + 1, total_items, f"詳細データ取得中: [{cid}] {title}")

                # データベース存在確認
                existing_work = db_session.query(Work).filter_by(id=cid).first()
                
                # クイック同期での差分判定
                # データベースに存在し、過去1日以内に更新され、かつ価格および定価取得済みの場合はスキップ
                is_recent = False
                if existing_work and existing_work.last_updated:
                    if datetime.utcnow() - existing_work.last_updated < timedelta(days=1):
                        # 価格または定価が0のものは再取得を許容する
                        if existing_work.price and existing_work.price > 0 and existing_work.list_price and existing_work.list_price > 0:
                            is_recent = True
                
                if mode == 'quick' and existing_work and is_recent:
                    diff_count += 1
                    fanza_logger.info(f"[SYNC] スキップ: CID={cid} は最近更新済みのため処理をスキップ (差分カウンター={diff_count})")
                    # 差分が一定数連続して無くなった場合は同期を終了 (ここでは連続3件とする)
                    if diff_count >= 3:
                        self.broadcast("processing_detail", total_items, total_items, "差分がなくなったため、同期を終了します。")
                        fanza_logger.info("[SYNC] クイック同期終了条件に合致。同期を早期終了します。")
                        break
                    continue
                else:
                    # 差分があればカウンターリセット
                    diff_count = 0

                # マイリスト情報の取得 (マイリストフラグがTrueの場合のみ実行)
                mylists = []
                if item.get("isMylistRegistered", False):
                    fanza_logger.info(f"[SYNC] マイリスト登録検知: CID={cid} の登録マイリスト情報を取得します。")
                    mylists = fetch_work_mylists(cookie_json, cid)
                    fanza_logger.info(f"[SYNC] マイリスト取得結果: {mylists}")
                    time.sleep(1.0)

                # 1段階目: ログイン済みHTMLから詳細メタデータを取得
                detail_data = {}
                fanza_logger.info(f"[SYNC] 詳細HTML(ログイン済み)を取得中: CID={cid}")
                html = fetch_detail_html(cookie_json, cid)
                if html:
                    fanza_logger.info(f"[SYNC] 詳細HTML取得成功 (サイズ={len(html)}), パース処理を実行")
                    detail_data = parse_detail_html(html)
                    time.sleep(0.8)
                else:
                    fanza_logger.error(f"[SYNC] 詳細HTMLの取得に失敗: CID={cid}")
                    self.broadcast("error", index + 1, total_items, f"詳細ページの取得に失敗: [{cid}] {title} (スキップ)")

                # 2段階目: 未ログインHTMLから正確な価格情報を取得
                fanza_logger.info(f"[SYNC] 価格HTML(未ログイン)を取得中: CID={cid}")
                anon_html = fetch_detail_html_anonymous(cid)
                price_data = {}
                if anon_html:
                    price_data = parse_price_html(anon_html)
                    time.sleep(0.8)
                else:
                    fanza_logger.warning(f"[SYNC] 未ログインHTMLの取得に失敗: CID={cid} (価格はログイン済みHTMLから取得)")

                # データベースの書き込みまたは更新
                if existing_work:
                    fanza_logger.info(f"[SYNC] データベースの既存レコードを更新: CID={cid}")
                    existing_work.title = title
                    existing_work.circle = item.get("makerName", "")
                    existing_work.genre = item.get("genre", "")
                    existing_work.is_unavailable = item.get("isUnavailable", False)
                    existing_work.is_streaming = item.get("isStreaming", False)
                    existing_work.purchase_date = item.get("purchase_date", "")
                    existing_work.is_mylist_registered = item.get("isMylistRegistered", False)
                    existing_work.mylists = json.dumps(mylists, ensure_ascii=False)
                    
                    if detail_data:
                        existing_work.main_image = detail_data.get("main_image", existing_work.main_image)
                        existing_work.description = detail_data.get("description", existing_work.description)
                        existing_work.sample_images = json.dumps(detail_data.get("sample_images", []), ensure_ascii=False)
                        existing_work.author = json.dumps(detail_data.get("author", []), ensure_ascii=False)
                        existing_work.specifications = json.dumps(detail_data.get("specifications", {}), ensure_ascii=False)
                    
                    # 価格データの更新 (未ログインHTMLの結果を優先)
                    if price_data:
                        lp = price_data.get('list_price', 0)
                        sp = price_data.get('sale_price')
                        ct = price_data.get('campaign_text')
                        if lp and lp > 0:
                            existing_work.list_price = lp
                        if sp and sp > 0:
                            existing_work.sale_price = sp
                            existing_work.price = sp  # 互換性: priceにもセール価格を設定
                        elif lp and lp > 0:
                            existing_work.price = lp  # セールなしの場合は定価
                            existing_work.sale_price = None
                        existing_work.campaign_text = ct
                    elif detail_data:
                        # 未ログインHTML取得失敗時はログイン済みHTMLの価格を使用
                        existing_work.price = detail_data.get("price", existing_work.price)
                        existing_work.list_price = detail_data.get("list_price", existing_work.list_price)
                    
                    existing_work.last_updated = datetime.utcnow()
                else:
                    fanza_logger.info(f"[SYNC] データベースへ新規挿入: CID={cid}")
                    new_work = Work(
                        id=cid,
                        title=title,
                        circle=item.get("makerName", ""),
                        genre=item.get("genre", ""),
                        is_unavailable=item.get("isUnavailable", False),
                        is_streaming=item.get("isStreaming", False),
                        purchase_date=item.get("purchase_date", ""),
                        is_mylist_registered=item.get("isMylistRegistered", False),
                        mylists=json.dumps(mylists, ensure_ascii=False),
                        main_image=detail_data.get("main_image"),
                        price=price_data.get('sale_price') or price_data.get('list_price') or detail_data.get("price", 0),
                        list_price=price_data.get('list_price') or detail_data.get("list_price", 0),
                        sale_price=price_data.get('sale_price'),
                        campaign_text=price_data.get('campaign_text'),
                        description=detail_data.get("description", ""),
                        sample_images=json.dumps(detail_data.get("sample_images", []), ensure_ascii=False),
                        author=json.dumps(detail_data.get("author", []), ensure_ascii=False),
                        specifications=json.dumps(detail_data.get("specifications", {}), ensure_ascii=False),
                        last_updated=datetime.utcnow()
                    )
                    db_session.add(new_work)

                db_session.commit()

            self.broadcast("complete", total_items, total_items, "すべての同期処理が正常に完了しました。")
            fanza_logger.info("[SYNC] 同期処理が正常に完了しました。")
            
            # 同期完了後にローカルファイルを自動スキャンして再紐付け
            try:
                download_manager.scan_local_files()
            except Exception as scan_err:
                fanza_logger.error(f"[SYNC] 同期後のローカルファイルスキャンに失敗: {str(scan_err)}")
        except Exception as e:
            self.broadcast("failed", 0, 0, f"同期エラーが発生しました: {str(e)}")
            fanza_logger.error(f"[SYNC] 同期中に致命的なエラーが発生: {str(e)}", exc_info=True)
        finally:
            self.is_running = False

# グローバルな同期マネージャーインスタンスの作成
sync_manager = SyncManager()
