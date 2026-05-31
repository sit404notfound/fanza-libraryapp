import time
import json
import queue
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from database import db_session
from models import Work
from fanza_api import fetch_purchased_page, fetch_work_mylists, fetch_detail_html, fetch_detail_html_anonymous
from scraper import parse_detail_html, parse_price_html
from logger import fanza_logger
from downloader import download_manager

# 並列リクエストの最大ワーカー数
MAX_WORKERS = 4

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

    @staticmethod
    def _is_data_incomplete(work):
        """作品データが不完全かどうかを判定する処理"""
        if not work:
            return True
        # 画像未取得
        if not work.main_image:
            return True
        # あらすじ未取得
        if not work.description:
            return True
        # スペック未取得
        if not work.specifications or work.specifications.strip() in ('{}', '', 'null'):
            return True
        # 価格情報未取得
        if work.price is None or work.list_price is None:
            return True
        return False

    @staticmethod
    def _fetch_work_data(cookie_json, cid, need_detail=True, need_price=True):
        """1作品分の詳細データと価格データを最適化して取得する処理。
        ネットワークI/O部分のみ実行しDB操作は行わない。
        
        高速化のため、まず未ログイン状態で詳細ページを取得し、詳細と価格の両方のパースを試みる。
        未ログイン状態で詳細（画像やあらすじ）が取得できなかった場合（販売終了・ログイン必須など）、
        フォールバックとしてログイン済み状態で再取得する。
        """
        result = {'cid': cid, 'detail_data': {}, 'price_data': {}}
        anon_html = None

        # 1. まず未ログイン（匿名）で詳細ページHTMLを取得する
        if need_detail or need_price:
            try:
                # サーバー負荷低減とブロック回避のための微小ディレイ
                time.sleep(0.2)
                anon_html = fetch_detail_html_anonymous(cid)
            except Exception as e:
                fanza_logger.error(f"[SYNC] 未ログインHTML取得エラー: CID={cid}, {str(e)}")

        # 2. 未ログインHTMLが取得できた場合、詳細と価格のパースを試みる
        if anon_html:
            if need_price:
                try:
                    result['price_data'] = parse_price_html(anon_html)
                except Exception as e:
                    fanza_logger.error(f"[SYNC] 未ログイン価格パースエラー: CID={cid}, {str(e)}")
            
            if need_detail:
                try:
                    detail = parse_detail_html(anon_html)
                    # 詳細データが十分に取得できているか検証
                    if detail and detail.get('main_image') and detail.get('description'):
                        result['detail_data'] = detail
                        need_detail = False  # 取得成功のためログイン済みHTMLの取得はスキップ
                    else:
                        fanza_logger.info(f"[SYNC] 未ログインHTMLから詳細データが十分に取得できなかったためフォールバックします: CID={cid}")
                except Exception as e:
                    fanza_logger.error(f"[SYNC] 未ログイン詳細パースエラー: CID={cid}, {str(e)}")

        # 3. フォールバック: ログイン済みHTMLを取得して詳細データを補完する
        if need_detail:
            try:
                time.sleep(0.2)
                html = fetch_detail_html(cookie_json, cid)
                if html:
                    result['detail_data'] = parse_detail_html(html)
                    
                    # ログイン済みHTMLしか取得できなかった場合で、価格が必要な場合のフォールバック価格設定
                    if need_price and not result.get('price_data'):
                        detail_price = result['detail_data'].get('price', 0)
                        detail_list_price = result['detail_data'].get('list_price', 0)
                        result['price_data'] = {
                            'list_price': detail_list_price,
                            'sale_price': detail_price if detail_price < detail_list_price else None,
                            'campaign_text': None
                        }
            except Exception as e:
                fanza_logger.error(f"[SYNC] ログイン済み詳細HTML取得エラー: CID={cid}, {str(e)}")

        return result

    def _run_sync(self, cookie_json, mode):
        """同期処理の本体 (バックグラウンド実行)"""
        mode_labels = {
            'quick': 'クイック同期',
            'full': 'フル同期',
            'repair': '修復同期'
        }
        fanza_logger.info(f"[SYNC] 同期処理を開始します (モード: {mode})")
        try:
            self.broadcast("start", 0, 0, f"同期処理を開始中 ({mode_labels.get(mode, mode)})...")

            if mode == 'repair':
                self._run_repair_sync(cookie_json)
            else:
                self._run_list_sync(cookie_json, mode)

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

    def _run_repair_sync(self, cookie_json):
        """修復同期: 不完全なデータを持つ作品のみを対象にして再取得する処理"""
        fanza_logger.info("[SYNC] 修復同期: 不完全データの作品を検出中...")
        self.broadcast("processing_list", 0, 0, "不完全データの作品を検出中...")

        # DB全作品をスキャンして不完全なものを抽出
        all_works = db_session.query(Work).all()
        incomplete_works = [w for w in all_works if self._is_data_incomplete(w)]
        total = len(incomplete_works)

        fanza_logger.info(f"[SYNC] 修復対象: {total}件 / 全{len(all_works)}件")
        self.broadcast("processing_detail", 0, total, f"修復対象: {total}件の不完全データを検出")

        if total == 0:
            self.broadcast("complete", 0, 0, "不完全なデータは見つかりませんでした。")
            return

        # 並列でデータを取得して逐次DB更新
        processed = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for work in incomplete_works:
                # 何が不足しているか判定してリクエストを最適化
                need_detail = (
                    not work.main_image or
                    not work.description or
                    not work.specifications or work.specifications in ('{}', '', 'null') or
                    not work.author or work.author in ('[]', '', 'null') or
                    not work.sample_images or work.sample_images in ('[]', '', 'null')
                )
                need_price = (
                    not work.price or work.price <= 0 or
                    not work.list_price or work.list_price <= 0 or
                    (work.list_price == work.price and work.sale_price is None and work.campaign_text is None)
                )
                future = executor.submit(
                    self._fetch_work_data, cookie_json, work.id,
                    need_detail=need_detail, need_price=need_price
                )
                futures[future] = work

            for future in as_completed(futures):
                work = futures[future]
                processed += 1
                try:
                    result = future.result()
                    detail_data = result.get('detail_data', {})
                    price_data = result.get('price_data', {})

                    # DB更新 (不足フィールドのみ上書き)
                    if detail_data:
                        if not work.main_image and detail_data.get('main_image'):
                            work.main_image = detail_data['main_image']
                        if not work.description and detail_data.get('description'):
                            work.description = detail_data['description']
                        if (not work.sample_images or work.sample_images in ('[]', '', 'null')) and detail_data.get('sample_images'):
                            work.sample_images = json.dumps(detail_data['sample_images'], ensure_ascii=False)
                        if (not work.author or work.author in ('[]', '', 'null')) and detail_data.get('author'):
                            work.author = json.dumps(detail_data['author'], ensure_ascii=False)
                        if (not work.specifications or work.specifications in ('{}', '', 'null')) and detail_data.get('specifications'):
                            work.specifications = json.dumps(detail_data['specifications'], ensure_ascii=False)

                    if price_data:
                        lp = price_data.get('list_price', 0)
                        sp = price_data.get('sale_price')
                        ct = price_data.get('campaign_text')
                        if lp and lp > 0:
                            work.list_price = lp
                        if sp and sp > 0:
                            work.sale_price = sp
                            work.price = sp
                        elif lp and lp > 0 and (not work.price or work.price <= 0):
                            work.price = lp
                        if ct:
                            work.campaign_text = ct

                    work.last_updated = datetime.utcnow()
                    db_session.commit()

                    self.broadcast("processing_detail", processed, total, f"修復中: [{work.id}] {work.title[:30] if work.title else ''}")
                    fanza_logger.info(f"[SYNC] 修復完了 [{processed}/{total}]: CID={work.id}")
                except Exception as e:
                    fanza_logger.error(f"[SYNC] 修復エラー: CID={work.id}, {str(e)}")
                    db_session.rollback()

        self.broadcast("complete", total, total, f"修復同期が完了しました。{total}件を処理。")
        fanza_logger.info(f"[SYNC] 修復同期が完了しました。{total}件を処理。")

    def _run_list_sync(self, cookie_json, mode):
        """リスト同期: 購入済み一覧からの通常同期処理 (クイック/フル)"""
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

        # 取得が必要な作品のフィルタリング
        items_to_fetch = []
        for item in all_items:
            cid = item.get("contentId") or item.get("productId")
            if not cid:
                continue
            existing = db_session.query(Work).filter_by(id=cid).first()

            # 差分判定 (クイック・フル両方で適用可能なスキップ条件)
            if existing and existing.last_updated:
                # クイック同期の場合: 1日以内に更新されており、かつ不完全データでなければスキップ
                if mode == 'quick':
                    if datetime.utcnow() - existing.last_updated < timedelta(days=1):
                        if not self._is_data_incomplete(existing):
                            diff_count += 1
                            if diff_count >= 3:
                                break
                            continue
                # フル同期の場合: 7日以内に更新されており、かつ不完全データでなければスキップ
                elif mode == 'full':
                    if datetime.utcnow() - existing.last_updated < timedelta(days=7):
                        if not self._is_data_incomplete(existing):
                            continue
            
            diff_count = 0
            items_to_fetch.append((item, existing))

        total_fetch = len(items_to_fetch)
        fanza_logger.info(f"[SYNC] 実際に取得が必要な作品: {total_fetch}件 / {total_items}件")
        self.broadcast("processing_detail", 0, total_fetch, f"{total_fetch}件の詳細データを並列取得中...")

        # 並列でHTMLデータを取得 (単一のThreadPoolExecutorで処理し、完了順に随時データベース更新)
        processed = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for item, existing in items_to_fetch:
                cid = item.get("contentId") or item.get("productId")
                future = executor.submit(self._fetch_work_data, cookie_json, cid)
                futures[future] = (item, existing)

            for future in as_completed(futures):
                item, existing = futures[future]
                cid = item.get("contentId") or item.get("productId")
                title = item.get("title", "")
                processed += 1
                
                try:
                    result = future.result()
                    detail_data = result.get('detail_data', {})
                    price_data = result.get('price_data', {})

                    # マイリスト情報の取得
                    mylists = []
                    if item.get("isMylistRegistered", False):
                        mylists = fetch_work_mylists(cookie_json, cid)

                    self.broadcast("processing_detail", processed, total_fetch, f"詳細データ取得中: [{cid}] {title}")

                    # データベースの書き込みまたは更新
                    if existing:
                        existing.title = title
                        existing.circle = item.get("makerName", "")
                        existing.genre = item.get("genre", "")
                        existing.is_unavailable = item.get("isUnavailable", False)
                        existing.is_streaming = item.get("isStreaming", False)
                        existing.purchase_date = item.get("purchase_date", "")
                        existing.is_mylist_registered = item.get("isMylistRegistered", False)
                        existing.mylists = json.dumps(mylists, ensure_ascii=False)

                        if detail_data:
                            existing.main_image = detail_data.get("main_image", existing.main_image)
                            existing.description = detail_data.get("description", existing.description)
                            existing.sample_images = json.dumps(detail_data.get("sample_images", []), ensure_ascii=False)
                            existing.author = json.dumps(detail_data.get("author", []), ensure_ascii=False)
                            existing.specifications = json.dumps(detail_data.get("specifications", {}), ensure_ascii=False)

                        # 価格データの更新
                        if price_data:
                            lp = price_data.get('list_price', 0)
                            sp = price_data.get('sale_price')
                            ct = price_data.get('campaign_text')
                            if lp and lp > 0:
                                existing.list_price = lp
                            if sp and sp > 0:
                                existing.sale_price = sp
                                existing.price = sp
                            elif lp and lp > 0:
                                existing.price = lp
                                existing.sale_price = None
                            existing.campaign_text = ct
                        elif detail_data:
                            existing.price = detail_data.get("price", existing.price)
                            existing.list_price = detail_data.get("list_price", existing.list_price)

                        existing.last_updated = datetime.utcnow()
                    else:
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
                    fanza_logger.info(f"[SYNC] 更新完了 [{processed}/{total_fetch}]: CID={cid}")
                except Exception as e:
                    fanza_logger.error(f"[SYNC] 作品更新エラー: CID={cid}, {str(e)}")
                    db_session.rollback()

        self.broadcast("complete", total_fetch, total_fetch, "すべての同期処理が正常に完了しました。")
        fanza_logger.info("[SYNC] 同期処理が正常に完了しました。")

# グローバルな同期マネージャーインスタンスの作成
sync_manager = SyncManager()
