import json
import os
import sys
# システムパスへの backend ディレクトリ追加処理
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import urllib.parse
from flask import Flask, request, Response, jsonify, send_file
from flask_cors import CORS
from sqlalchemy import and_, or_
from database import init_db, db_session
from models import Work, UserSession
from auth import login_manager
from sync import sync_manager
from proxy import extract_m3u8_url, rewrite_m3u8, proxy_media_request
from downloader import download_manager
from logger import fanza_logger, in_memory_handler
from fanza_api import parse_cookie_json
import requests

app = Flask(__name__)
# フロントエンド開発サーバー等からのCORSを許可
CORS(app, resources={r"/api/*": {"origins": "*"}})

def migrate_db_unicode():
    """既存のDBレコードのJSON非ASCII文字のエスケープを解除する"""
    try:
        works = db_session.query(Work).all()
        updated = False
        for w in works:
            for field in ['mylists', 'sample_images', 'author', 'specifications']:
                val = getattr(w, field)
                if val:
                    try:
                        data = json.loads(val)
                        new_val = json.dumps(data, ensure_ascii=False)
                        if val != new_val:
                            setattr(w, field, new_val)
                            updated = True
                    except Exception:
                        pass
        if updated:
            db_session.commit()
            fanza_logger.info("[MIGRATE] 既存レコードのUnicodeエスケープを解除完了")
    except Exception as e:
        db_session.rollback()
        fanza_logger.error(f"[MIGRATE] マイグレーション中にエラーが発生: {str(e)}")

# データベースの初期化
init_db()
migrate_db_unicode()

@app.teardown_appcontext
def shutdown_session(exception=None):
    """リクエスト終了時のDBセッションの解放処理"""
    db_session.remove()

# ----------------- 認証・セッション管理 -----------------

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    """ログイン開始エンドポイント"""
    data = request.json or {}
    email = data.get('email')
    password = data.get('password')
    
    # 手動またはソーシャルログイン時は空値を許容
    success = login_manager.start_login(email, password)
    if success:
        return jsonify({"message": "ログイン処理を開始しました。"}), 200
    return jsonify({"error": "ログイン処理が既に実行中です。"}), 409

@app.route('/api/auth/2fa', methods=['POST'])
def api_2fa():
    """二段階認証コード送信エンドポイント"""
    data = request.json or {}
    code = data.get('code')
    if not code:
        return jsonify({"error": "認証コードは必須です。"}), 400
    
    success = login_manager.submit_otp(code)
    if success:
        return jsonify({"message": "認証コードを送信しました。"}), 200
    return jsonify({"error": "二段階認証の待機状態ではありません。"}), 400

@app.route('/api/auth/status', methods=['GET'])
def api_auth_status():
    """ログイン状態取得エンドポイント"""
    return jsonify({
        "status": login_manager.status,
        "error_message": login_manager.error_message
    })

@app.route('/api/auth/session-check', methods=['GET'])
def api_session_check():
    """現在のアクティブなログインセッションが有効であるか検証するエンドポイント"""
    session = db_session.query(UserSession).filter_by(is_active=True).order_by(UserSession.updated_at.desc()).first()
    if not session:
        return jsonify({"authenticated": False, "status": "NOT_LOGGED_IN", "message": "未ログイン"})
        
    # Cookieの有効性をFANZA APIへの軽量リクエストで検証
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.dmm.co.jp/dc/-/mylibrary/"
        }
        cookies = parse_cookie_json(session.cookie_data)
        
        # 購入済み一覧API（limit=1）を利用したセッション確認
        test_url = "https://www.dmm.co.jp/dc/doujin/api/mylibraries/"
        params = {"page": 1, "limit": 1, "genre": "all", "sort": "purchasedate_desc"}
        res = requests.get(test_url, headers=headers, params=params, cookies=cookies, timeout=10)
        
        is_valid = False
        if res.status_code == 200:
            try:
                res_data = res.json()
                if "data" in res_data:
                    is_valid = True
            except ValueError:
                pass
                
        if is_valid:
            return jsonify({
                "authenticated": True, 
                "status": "VALID", 
                "message": "ログイン中",
                "updated_at": session.updated_at.strftime('%Y-%m-%d %H:%M:%S')
            })
        else:
            # 無効なセッションの非アクティブ化
            session.is_active = False
            db_session.commit()
            fanza_logger.info("[API] セッションの期限切れを検知し無効化")
            return jsonify({"authenticated": False, "status": "EXPIRED", "message": "期限切れ"})
            
    except Exception as e:
        return jsonify({
            "authenticated": False, 
            "status": "ERROR", 
            "message": f"セッション検証失敗"
        })

# ----------------- 同期制御 -----------------

@app.route('/api/sync/start', methods=['POST'])
def api_sync_start():
    """同期処理開始エンドポイント"""
    data = request.json or {}
    mode = data.get('mode', 'quick')  # quick or full
    
    # 有効なCookieを持つセッションの取得
    session = db_session.query(UserSession).filter_by(is_active=True).order_by(UserSession.updated_at.desc()).first()
    if not session:
        return jsonify({"error": "アクティブなログインセッションがありません。ログインしてください。"}), 401
    
    success = sync_manager.start_sync(session.cookie_data, mode=mode)
    if success:
        return jsonify({"message": "同期処理を開始しました。"}), 200
    return jsonify({"error": "同期処理が既に実行中である。"}), 409

@app.route('/api/sync/events', methods=['GET'])
def api_sync_events():
    """SSEによる同期進捗配信エンドポイント"""
    q = sync_manager.add_listener()
    
    def event_stream():
        try:
            while True:
                # 接続維持とデータ受信を待機 (タイムアウト時はkeep-alive送信)
                try:
                    data = q.get(timeout=20)
                    yield f"data: {data}\n\n"
                except:
                    yield ": keep-alive\n\n"
        finally:
            sync_manager.remove_listener(q)
            
    return Response(event_stream(), mimetype="text/event-stream")

# ----------------- 作品一覧・検索・詳細 -----------------

@app.route('/api/works', methods=['GET'])
def api_get_works():
    """作品一覧取得エンドポイント (検索・ソート・フィルタ対応)"""
    query = db_session.query(Work)
    
    # 1. フィルタ処理
    genre = request.args.get('genre')
    if genre:
        query = query.filter(Work.genre == genre)
        
    mylist = request.args.get('mylist')
    if mylist:
        # JSON配列の文字列部分一致で簡易マイリスト判定
        query = query.filter(Work.mylists.like(f'%"{mylist}"%'))
        
    streaming = request.args.get('streaming')
    if streaming == 'true':
        query = query.filter(Work.is_streaming == True)
        
    downloaded = request.args.get('downloaded')
    if downloaded == 'true':
        query = query.filter(Work.local_path != None)
    elif downloaded == 'false':
        query = query.filter(Work.local_path == None)

    # 2. 複数キーワードによる高度なAND/OR複合検索
    search_q = request.args.get('q', '').strip()
    if search_q:
        # 全角スペースを半角スペースに統一して分割
        terms = re.split(r'\s+', search_q.replace('　', ' '))
        
        # デフォルトは全単語のAND結合
        and_conditions = []
        
        # "OR" キーワードのハンドリングを簡易実装
        i = 0
        while i < len(terms):
            term = terms[i]
            if i + 1 < len(terms) and (terms[i+1].upper() == 'OR' or terms[i+1] == 'または'):
                # OR結合の構築
                if i + 2 < len(terms):
                    or_term_left = term
                    or_term_right = terms[i+2]
                    
                    # 日本語エスケープ形式の検索ワードも生成
                    left_escaped = json.dumps(or_term_left)[1:-1]
                    right_escaped = json.dumps(or_term_right)[1:-1]
                    
                    # 各項目の部分一致条件の定義
                    cond_left = or_(
                        Work.title.like(f'%{or_term_left}%'),
                        Work.circle.like(f'%{or_term_left}%'),
                        Work.author.like(f'%{or_term_left}%'),
                        Work.author.like(f'%{left_escaped}%'),
                        Work.specifications.like(f'%{or_term_left}%'),
                        Work.specifications.like(f'%{left_escaped}%'),
                        Work.genre.like(f'%{or_term_left}%')
                    )
                    cond_right = or_(
                        Work.title.like(f'%{or_term_right}%'),
                        Work.circle.like(f'%{or_term_right}%'),
                        Work.author.like(f'%{or_term_right}%'),
                        Work.author.like(f'%{right_escaped}%'),
                        Work.specifications.like(f'%{or_term_right}%'),
                        Work.specifications.like(f'%{right_escaped}%'),
                        Work.genre.like(f'%{or_term_right}%')
                    )
                    and_conditions.append(or_(cond_left, cond_right))
                    i += 3
                    continue
            
            # 通常の単語 (単一のAND条件)
            if term.upper() != 'OR' and term != 'または':
                # 日本語エスケープ形式の検索ワードも生成
                term_escaped = json.dumps(term)[1:-1]
                cond = or_(
                    Work.title.like(f'%{term}%'),
                    Work.circle.like(f'%{term}%'),
                    Work.author.like(f'%{term}%'),
                    Work.author.like(f'%{term_escaped}%'),
                    Work.specifications.like(f'%{term}%'),
                    Work.specifications.like(f'%{term_escaped}%'),
                    Work.genre.like(f'%{term}%')
                )
                and_conditions.append(cond)
            i += 1
            
        if and_conditions:
            query = query.filter(and_( *and_conditions ))

    # 3. ソート処理
    sort_key = request.args.get('sort', 'purchase_date')  # purchase_date, price, title
    direction = request.args.get('direction', 'desc')  # asc, desc
    
    col = getattr(Work, sort_key, Work.purchase_date)
    if direction == 'asc':
        query = query.order_by(col.asc())
    else:
        query = query.order_by(col.desc())
        
    works = query.all()
    
    result = []
    db_updated = False
    for w in works:
        # ローカルファイルの存在チェックによる自動クリーンアップ
        if w.local_path and not os.path.exists(w.local_path):
            w.local_path = None
            db_updated = True
            fanza_logger.info(f"[API] 実ファイル消失を検知し紐付けを自動解除: CID={w.id}")
            
        result.append({
            "id": w.id,
            "title": w.title,
            "circle": w.circle,
            "genre": w.genre,
            "is_unavailable": w.is_unavailable,
            "is_streaming": w.is_streaming,
            "purchase_date": w.purchase_date,
            "is_mylist_registered": w.is_mylist_registered,
            "main_image": w.main_image,
            "price": w.price,
            "list_price": w.list_price,
            "sale_price": w.sale_price,
            "purchase_price": w.purchase_price,
            "campaign_text": w.campaign_text,
            "local_path": w.local_path
        })
        
    if db_updated:
        try:
            db_session.commit()
        except Exception as commit_err:
            db_session.rollback()
            fanza_logger.error(f"[API] スキャン自動コミットに失敗: {str(commit_err)}")
        
    return jsonify(result)

@app.route('/api/works/<cid>', methods=['GET'])
def api_get_work_detail(cid):
    """作品詳細情報取得エンドポイント"""
    w = db_session.query(Work).filter_by(id=cid).first()
    if not w:
        return jsonify({"error": "作品が見つかりません。"}), 404
        
    # ローカルファイルの存在チェックによる自動クリーンアップ
    if w.local_path and not os.path.exists(w.local_path):
        w.local_path = None
        try:
            db_session.commit()
            fanza_logger.info(f"[API] 詳細取得時に実ファイル消失を検知し紐付けを自動解除: CID={w.id}")
        except Exception as commit_err:
            db_session.rollback()
            fanza_logger.error(f"[API] 詳細自動コミットに失敗: {str(commit_err)}")
        
    return jsonify({
        "id": w.id,
        "title": w.title,
        "circle": w.circle,
        "genre": w.genre,
        "is_unavailable": w.is_unavailable,
        "is_streaming": w.is_streaming,
        "purchase_date": w.purchase_date,
        "is_mylist_registered": w.is_mylist_registered,
        "mylists": json.loads(w.mylists) if w.mylists else [],
        "main_image": w.main_image,
        "price": w.price,
        "list_price": w.list_price,
        "sale_price": w.sale_price,
        "purchase_price": w.purchase_price,
        "campaign_text": w.campaign_text,
        "description": w.description,
        "sample_images": json.loads(w.sample_images) if w.sample_images else [],
        "author": json.loads(w.author) if w.author else [],
        "specifications": json.loads(w.specifications) if w.specifications else {},
        "local_path": w.local_path
    })

@app.route('/api/works/<cid>/purchase-price', methods=['POST'])
def api_update_purchase_price(cid):
    """手動で購入価格を更新するエンドポイント"""
    w = db_session.query(Work).filter_by(id=cid).first()
    if not w:
        return jsonify({"error": "作品が見つかりません。"}), 404
        
    data = request.json or {}
    purchase_price = data.get('purchase_price')
    
    # 数値変換またはNone化処理
    if purchase_price is not None:
        try:
            purchase_price = int(purchase_price)
        except (ValueError, TypeError):
            return jsonify({"error": "無効な価格数値である。"}), 400
            
    w.purchase_price = purchase_price
    try:
        db_session.commit()
        fanza_logger.info(f"[API] 購入価格を手動更新: CID={cid}, 価格={purchase_price}")
        return jsonify({"message": "購入価格を更新した。", "purchase_price": purchase_price})
    except Exception as e:
        db_session.rollback()
        fanza_logger.error(f"[API] 購入価格の更新に失敗: {str(e)}")
        return jsonify({"error": "データベース更新に失敗した。"}), 500

# ----------------- メディア再生・中継・ダウンロード -----------------

@app.route('/api/works/<cid>/download', methods=['POST'])
def api_download_work(cid):
    """ダウンロード開始エンドポイント"""
    session = db_session.query(UserSession).filter_by(is_active=True).order_by(UserSession.updated_at.desc()).first()
    if not session:
        return jsonify({"error": "アクティブなログインセッションがありません。"}), 401
        
    # ダウンロード開始前に紐付けが実在するかチェック
    w = db_session.query(Work).filter_by(id=cid).first()
    if w and w.local_path and not os.path.exists(w.local_path):
        w.local_path = None
        try:
            db_session.commit()
            fanza_logger.info(f"[API] ダウンロード開始前に実ファイル消失を検知し紐付け解除: CID={cid}")
        except Exception as commit_err:
            db_session.rollback()
            fanza_logger.error(f"[API] ダウンロード前自動コミットに失敗: {str(commit_err)}")
            
    success = download_manager.start_download(session.cookie_data, cid)
    if success:
        return jsonify({"message": "ダウンロード処理を開始しました。"}), 200
    return jsonify({"error": "既にダウンロード処理が実行中である。"}), 409

@app.route('/api/download/status/<cid>', methods=['GET'])
def api_download_status(cid):
    """特定作品のダウンロードステータス取得エンドポイント"""
    return jsonify(download_manager.get_status(cid))

@app.route('/api/stream/playlist/<cid>', methods=['GET'])
def api_stream_playlist(cid):
    """ストリーミング用プロキシm3u8配信エンドポイント"""
    session = db_session.query(UserSession).filter_by(is_active=True).order_by(UserSession.updated_at.desc()).first()
    if not session:
        return jsonify({"error": "アクティブなログインセッションがありません。"}), 401

    # 1. FANZA側からm3u8のURLを取得
    m3u8_url = extract_m3u8_url(session.cookie_data, cid)
    if not m3u8_url:
        return jsonify({"error": "ストリーミング配信URLの取得に失敗しました。"}), 404
        
    # 2. m3u8ファイルの取得
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    cookies = parse_cookie_json(session.cookie_data)
    res = requests.get(m3u8_url, headers=headers, cookies=cookies, timeout=15)
    if res.status_code != 200:
        return jsonify({"error": "m3u8ファイルの取得に失敗しました。"}), 502
        
    # 3. m3u8内のURL書き換え
    proxy_endpoint = request.host_url + "api/proxy/media"
    rewritten_content = rewrite_m3u8(res.text, m3u8_url, proxy_endpoint)
    
    return Response(rewritten_content, mimetype="application/x-mpegURL")

@app.route('/api/proxy/media', methods=['GET'])
def api_proxy_media():
    """動画セグメント等の中継プロキシエンドポイント"""
    target_url = request.args.get('url')
    if not target_url:
        return jsonify({"error": "urlパラメータは必須です。"}), 400
        
    session = db_session.query(UserSession).filter_by(is_active=True).order_by(UserSession.updated_at.desc()).first()
    cookie_data = session.cookie_data if session else "{}"
    
    res = proxy_media_request(cookie_data, target_url)
    if not res:
        return jsonify({"error": "中継リクエストに失敗しました。"}), 502
        
    # レスポンスのヘッダー引き継ぎ
    headers = {}
    if 'content-type' in res.headers:
        headers['Content-Type'] = res.headers['content-type']
    if 'content-length' in res.headers:
        headers['Content-Length'] = res.headers['content-length']
        
    # ストリームによるレスポンス返却
    def generate():
        for chunk in res.iter_content(chunk_size=1024*64):
            yield chunk
            
    return Response(generate(), status=res.status_code, headers=headers)

@app.route('/api/works/<cid>/local-file', methods=['GET'])
def api_serve_local_file(cid):
    """ローカルファイルのオフライン配信エンドポイント"""
    w = db_session.query(Work).filter_by(id=cid).first()
    if not w or not w.local_path:
        return jsonify({"error": "ローカルファイルが登録されていません。"}), 404
        
    if not os.path.exists(w.local_path):
        return jsonify({"error": "ローカルファイルが見つかりません。ファイルが削除された可能性があります。"}), 404
        
    # ローカルファイルを直接返却
    return send_file(w.local_path, as_attachment=False)

# ----------------- メディアプロキシ・ZIPファイル配信 -----------------

import requests
import zipfile
import mimetypes
from io import BytesIO

@app.route('/api/proxy/image', methods=['GET'])
def api_proxy_image():
    """画像のReferer制限を回避するための中継プロキシエンドポイント"""
    target_url = request.args.get('url')
    if not target_url:
        return jsonify({"error": "urlパラメータは必須です。"}), 400
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.dmm.co.jp/"
    }
    
    try:
        # 画像データを取得
        res = requests.get(target_url, headers=headers, stream=True, timeout=15)
        if res.status_code != 200:
            return jsonify({"error": "画像の取得に失敗しました。"}), res.status_code
            
        proxy_headers = {}
        if 'content-type' in res.headers:
            proxy_headers['Content-Type'] = res.headers['content-type']
        if 'content-length' in res.headers:
            proxy_headers['Content-Length'] = res.headers['content-length']
            
        # キャッシュ制御ヘッダーを追加
        proxy_headers['Cache-Control'] = 'public, max-age=86400'
            
        def generate():
            for chunk in res.iter_content(chunk_size=1024*64):
                yield chunk
                
        return Response(generate(), status=res.status_code, headers=proxy_headers)
    except Exception as e:
        return jsonify({"error": f"プロキシエラー: {str(e)}"}), 502

@app.route('/api/works/<cid>/zip-images', methods=['GET'])
def api_get_zip_images(cid):
    """ZIPファイル内の画像ファイル一覧をソートして返却するエンドポイント"""
    w = db_session.query(Work).filter_by(id=cid).first()
    if not w or not w.local_path:
        return jsonify({"error": "ローカルファイルが登録されていません。"}), 404
        
    if not os.path.exists(w.local_path):
        return jsonify({"error": "ローカルファイルが見つかりません。"}), 404
        
    if not zipfile.is_zipfile(w.local_path):
        return jsonify({"error": "対象のファイルはZIP形式ではありません。"}), 400
        
    try:
        with zipfile.ZipFile(w.local_path, 'r') as z:
            # 画像ファイルの拡張子を持つエントリを抽出
            image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')
            namelist = z.namelist()
            images = [
                name for name in namelist 
                if not name.endswith('/') and name.lower().endswith(image_extensions)
            ]
            images.sort()
            return jsonify(images)
    except Exception as e:
        return jsonify({"error": f"ZIPファイルの解析に失敗しました: {str(e)}"}), 500

@app.route('/api/works/<cid>/zip-images/<path:filename>', methods=['GET'])
def api_serve_zip_image(cid, filename):
    """ZIPファイル内の特定の画像データを展開して配信するエンドポイント"""
    w = db_session.query(Work).filter_by(id=cid).first()
    if not w or not w.local_path:
        return jsonify({"error": "ローカルファイルが登録されていません。"}), 404
        
    if not os.path.exists(w.local_path):
        return jsonify({"error": "ローカルファイルが見つかりません。"}), 404
        
    try:
        with zipfile.ZipFile(w.local_path, 'r') as z:
            if filename not in z.namelist():
                return jsonify({"error": f"指定されたファイルが見つかりません: {filename}"}), 404
                
            data = z.read(filename)
            mime_type, _ = mimetypes.guess_type(filename)
            if not mime_type:
                mime_type = 'application/octet-stream'
                
            return send_file(
                BytesIO(data),
                mimetype=mime_type,
                as_attachment=False
            )
    except Exception as e:
        return jsonify({"error": f"画像の配信に失敗しました: {str(e)}"}), 500

@app.route('/api/system/logs', methods=['GET'])
def api_get_system_logs():
    """蓄積されたシステム動作ログを取得するエンドポイント"""
    logs = in_memory_handler.get_logs()
    return jsonify(logs)

@app.route('/api/works/<cid>/files', methods=['GET'])
def api_get_zip_files(cid):
    """パッケージ（ZIPまたはフォルダ）内のすべてのファイルをスキャンして返すエンドポイント"""
    w = db_session.query(Work).filter_by(id=cid).first()
    if not w:
        fanza_logger.warning(f"[API] パッケージファイル一覧要求: CID={cid} の作品がデータベースに存在しません。")
        return jsonify([])

    image_exts = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')
    video_exts = ('.mp4', '.mkv', '.webm', '.avi', '.mov', '.wmv')
    audio_exts = ('.mp3', '.wav', '.flac', '.m4a', '.ogg', '.aac', '.wma')
    pdf_exts = ('.pdf',)

    # --- ローカルファイルが存在する場合の処理 ---
    if w.local_path and os.path.exists(w.local_path):
        # 1. フォルダ（ディレクトリ）の場合の処理
        if os.path.isdir(w.local_path):
            try:
                fanza_logger.info(f"[API] フォルダ内のファイルスキャン開始: CID={cid}, Path={w.local_path}")
                files = []
                for root, dirs, filenames in os.walk(w.local_path):
                    # テンポラリ解凍用フォルダ等は除外
                    if '.temp' in root or '__pycache__' in root:
                        continue
                    for filename in filenames:
                        abs_filepath = os.path.join(root, filename)
                        rel_path = os.path.relpath(abs_filepath, w.local_path).replace('\\', '/')
                        
                        lower_name = filename.lower()
                        size = os.path.getsize(abs_filepath)
                        
                        media_type = 'other'
                        if lower_name.endswith(image_exts):
                            media_type = 'image'
                        elif lower_name.endswith(video_exts):
                            media_type = 'video'
                        elif lower_name.endswith(audio_exts):
                            media_type = 'audio'
                        elif lower_name.endswith(pdf_exts):
                            media_type = 'pdf'
                            
                        files.append({
                            "name": rel_path,
                            "size": size,
                            "type": media_type
                        })
                files.sort(key=lambda x: x["name"])
                fanza_logger.info(f"[API] フォルダスキャン完了: 収録ファイル数={len(files)}")
                return jsonify(files)
            except Exception as e:
                fanza_logger.error(f"[API] フォルダスキャン中にエラーが発生: {str(e)}", exc_info=True)
                return jsonify([])

        # 2. ZIPファイルの場合の処理
        elif zipfile.is_zipfile(w.local_path):
            try:
                fanza_logger.info(f"[API] ZIPファイル解析開始: CID={cid}, Path={w.local_path}")
                with zipfile.ZipFile(w.local_path, 'r') as z:
                    files = []
                    
                    for zinfo in z.infolist():
                        if zinfo.is_dir():
                            continue
                        
                        # 文字化け対策: CP437バイトに戻してcp932でデコード
                        try:
                            name = zinfo.filename.encode('cp437').decode('cp932', errors='replace')
                        except Exception:
                            name = zinfo.filename
                        
                        # スラッシュ区切りに統一
                        name = name.replace('\\', '/')
                        lower_name = name.lower()
                        size = zinfo.file_size
                        
                        media_type = 'other'
                        if lower_name.endswith(image_exts):
                            media_type = 'image'
                        elif lower_name.endswith(video_exts):
                            media_type = 'video'
                        elif lower_name.endswith(audio_exts):
                            media_type = 'audio'
                        elif lower_name.endswith(pdf_exts):
                            media_type = 'pdf'
                        
                        files.append({
                            "name": name,
                            "size": size,
                            "type": media_type
                        })
                        
                    files.sort(key=lambda x: x["name"])
                    fanza_logger.info(f"[API] ZIPファイル解析完了: 収録ファイル数={len(files)}")
                    return jsonify(files)
            except Exception as e:
                fanza_logger.error(f"[API] ZIPファイル解析中にエラーが発生: {str(e)}", exc_info=True)
                return jsonify([])

    fanza_logger.warning(f"[API] パッケージファイルが見つからないか未サポートです: CID={cid}, Path={w.local_path}")
    return jsonify([])

@app.route('/api/works/<cid>/files/serve', methods=['GET'])
def api_serve_zip_file_content(cid):
    """パッケージ（ZIPまたはフォルダ）内の特定のファイルデータを配信するエンドポイント"""
    filepath = request.args.get('path')
    if not filepath:
        return jsonify({"error": "pathパラメータは必須です。"}), 400
        
    w = db_session.query(Work).filter_by(id=cid).first()
    if not w or not w.local_path:
        fanza_logger.warning(f"[API] パッケージファイル配信: CID={cid} のローカルパスが存在しません。")
        return jsonify({"error": "ローカルファイルが登録されていません。"}), 404
        
    if not os.path.exists(w.local_path):
        fanza_logger.error(f"[API] パッケージファイル配信: ローカルファイル/フォルダが見つかりません: {w.local_path}")
        return jsonify({"error": "ローカルファイルが見つかりません。"}), 404
        
    # 1. フォルダ（ディレクトリ）の場合の直接配信処理
    if os.path.isdir(w.local_path):
        target_file = os.path.abspath(os.path.join(w.local_path, filepath))
        # ディレクトリトラバーサル防止処理
        if not target_file.startswith(os.path.abspath(w.local_path)):
            fanza_logger.error(f"[API] ディレクトリトラバーサル検知: path={filepath}")
            return jsonify({"error": "不正なファイルパスです。"}), 400
            
        if not os.path.exists(target_file):
            return jsonify({"error": "ファイルが見つかりません。"}), 404
            
        return send_file(target_file, as_attachment=False)

    # 2. ZIPファイルの場合のオンデマンド展開配信処理
    elif zipfile.is_zipfile(w.local_path):
        temp_root = os.path.join(os.path.dirname(w.local_path), '.temp', cid)
        
        try:
            with zipfile.ZipFile(w.local_path, 'r') as z:
                # リクエストされた filepath (デコードされた名前) に対応する ZIP 内の本来の filename を検索
                target_zinfo = None
                for zinfo in z.infolist():
                    if zinfo.is_dir():
                        continue
                    try:
                        decoded_name = zinfo.filename.encode('cp437').decode('cp932', errors='replace').replace('\\', '/')
                    except Exception:
                        decoded_name = zinfo.filename.replace('\\', '/')
                    
                    if decoded_name == filepath or zinfo.filename == filepath:
                        target_zinfo = zinfo
                        break
                
                if not target_zinfo:
                    fanza_logger.error(f"[API] 指定されたファイルがZIP内に存在しません: {filepath}")
                    return jsonify({"error": "ファイルが見つかりません。"}), 404
                
                # 安全な平坦ファイル名の生成 (ハッシュ値を使用)
                import hashlib
                file_ext = os.path.splitext(filepath)[1]
                hashed_name = hashlib.md5(filepath.encode('utf-8', errors='ignore')).hexdigest() + file_ext
                dest_path = os.path.abspath(os.path.join(temp_root, hashed_name))
                
                # ディレクトリトラバーサル防止処理
                if not dest_path.startswith(os.path.abspath(temp_root)):
                    fanza_logger.error(f"[API] ディレクトリトラバーサル検知: path={filepath}")
                    return jsonify({"error": "不正なファイルパスです。"}), 400
                
                if not os.path.exists(dest_path):
                    fanza_logger.info(f"[API] ZIPからオンデマンド解凍を開始: file={filepath} -> dest={dest_path}")
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    
                    with z.open(target_zinfo.filename) as source, open(dest_path, 'wb') as target:
                        chunk_size = 1024 * 1024
                        while True:
                            chunk = source.read(chunk_size)
                            if not chunk:
                                break
                            target.write(chunk)
                    
                    fanza_logger.info(f"[API] オンデマンド解凍完了")
                else:
                    fanza_logger.info(f"[API] キャッシュ済みファイルを配信: file={filepath}")
                    
                return send_file(dest_path, as_attachment=False)
            
        except Exception as e:
            fanza_logger.error(f"[API] ファイル展開配信中にエラーが発生: {str(e)}", exc_info=True)
            return jsonify({"error": f"ファイルの展開配信に失敗: {str(e)}"}), 500

    fanza_logger.warning(f"[API] サポートされていないファイル形式の配信要求です: {w.local_path}")
    return jsonify({"error": "サポートされていないファイル形式です。"}), 400

@app.route('/api/database/clear', methods=['POST'])
def api_clear_database():
    """データベースの全作品データ削除エンドポイント"""
    try:
        # Work テーブルの全レコード削除処理
        num_deleted = db_session.query(Work).delete()
        db_session.commit()
        return jsonify({"message": f"データベースから {num_deleted} 件の作品データを削除しました。"})
    except Exception as e:
        db_session.rollback()
        return jsonify({"error": f"データベースのクリアに失敗しました: {str(e)}"}), 500

@app.route('/api/downloads/info', methods=['GET'])
def api_get_downloads_info():
    """ダウンロード先ディレクトリ内の容量およびファイル一覧を取得するエンドポイント"""
    dl_dir = download_manager.download_dir
    if not os.path.exists(dl_dir):
        return jsonify({"total_size_bytes": 0, "total_size_str": "0 MB", "files": []})
        
    total_size = 0
    files_info = []
    try:
        for filename in os.listdir(dl_dir):
            if filename.startswith('.') or filename == '.temp':
                continue
            filepath = os.path.join(dl_dir, filename)
            if os.path.isfile(filepath):
                size = os.path.getsize(filepath)
                total_size += size
                
                # ファイル名から CID を抽出
                cid_match = re.search(r'(d_\d+)', filename)
                cid = cid_match.group(1) if cid_match else None
                
                files_info.append({
                    "filename": filename,
                    "size_bytes": size,
                    "size_str": f"{size // 1024 // 1024} MB",
                    "cid": cid
                })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
        
    # 合計容量のフォーマット
    if total_size > 1024 * 1024 * 1024:
        total_size_str = f"{total_size / (1024 * 1024 * 1024):.2f} GB"
    else:
        total_size_str = f"{total_size / (1024 * 1024):.1f} MB"
        
    return jsonify({
        "total_size_bytes": total_size,
        "total_size_str": total_size_str,
        "files": files_info
    })

@app.route('/api/downloads', methods=['DELETE'])
def api_delete_all_downloads():
    """ダウンロード済みの全ファイルを物理削除し紐付けを解除するエンドポイント"""
    dl_dir = download_manager.download_dir
    if not os.path.exists(dl_dir):
        return jsonify({"message": "対象のディレクトリが存在しません。"})
        
    deleted_count = 0
    error_count = 0
    
    # 1. 物理ファイルの削除
    try:
        for filename in os.listdir(dl_dir):
            filepath = os.path.join(dl_dir, filename)
            try:
                if os.path.isfile(filepath):
                    os.remove(filepath)
                    deleted_count += 1
                elif os.path.isdir(filepath) and filename == '.temp':
                    # 一時キャッシュの再帰的削除
                    import shutil
                    shutil.rmtree(filepath)
            except Exception as fe:
                fanza_logger.error(f"[API] ファイル削除失敗: {filepath}, エラー: {str(fe)}")
                error_count += 1
    except Exception as e:
        return jsonify({"error": f"ディレクトリ走査失敗: {str(e)}"}), 500
        
    # 2. データベースの紐付けリセット
    try:
        works = db_session.query(Work).filter(Work.local_path != None).all()
        for w in works:
            w.local_path = None
        db_session.commit()
        fanza_logger.info(f"[API] 一括削除完了: {len(works)} 件の紐付けを解除。物理ファイル削除数: {deleted_count}")
    except Exception as dbe:
        db_session.rollback()
        return jsonify({"error": f"データベース更新失敗: {str(dbe)}"}), 500
        
    return jsonify({
        "message": "すべてのダウンロードファイルを削除し、紐付けを解除しました。",
        "deleted_files_count": deleted_count,
        "errors_count": error_count
    })

# ----------------- 設定管理 -----------------

@app.route('/api/settings/select-directory', methods=['POST'])
def api_select_directory():
    """GUIによるフォルダ選択ダイアログの表示エンドポイント"""
    try:
        import tkinter as tk
        from tkinter import filedialog
        
        # GUIスレッドの初期化および非表示設定
        root = tk.Tk()
        root.withdraw()
        root.focus_force()
        root.attributes('-topmost', True)
        
        # フォルダ選択ダイアログの起動
        directory = filedialog.askdirectory(
            parent=root,
            title="保存先フォルダを選択してください",
            initialdir=download_manager.download_dir
        )
        root.destroy()
        
        if directory:
            directory = os.path.abspath(directory)
            return jsonify({"directory": directory})
        else:
            return jsonify({"directory": None, "message": "選択キャンセル"})
    except Exception as e:
        fanza_logger.error(f"[API] フォルダ選択ダイアログの表示に失敗: {str(e)}")
        return jsonify({"error": f"フォルダ選択ダイアログの起動に失敗しました: {str(e)}"}), 500


@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    """設定の取得および更新エンドポイント"""
    if request.method == 'POST':
        data = request.json or {}
        dl_dir = data.get('download_dir')
        if dl_dir:
            success = download_manager.set_download_dir(dl_dir)
            if not success:
                return jsonify({"error": "無効なディレクトリパスです。"}), 400
        return jsonify({"message": "設定を更新しました。"})
        
    return jsonify({
        "download_dir": os.path.abspath(download_manager.download_dir)
    })

# 補助ライブラリのインポート追加
import re

if __name__ == '__main__':
    # ローカルWebアプリのためホスト5000番で開発サーバーを起動
    app.run(host='127.0.0.1', port=5000, debug=True)
