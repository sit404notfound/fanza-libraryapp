import json
import queue
import threading
from datetime import datetime
from playwright.sync_api import sync_playwright
from database import db_session
from models import UserSession

class LoginManager:
    """自動ログインの制御クラス"""
    def __init__(self):
        self.status = 'IDLE'  # 現在のログイン状態
        self.error_message = None  # エラー発生時のメッセージ
        self.otp_queue = queue.Queue()  # 2FAコード受取用のキュー
        self.thread = None  # ログイン用スレッド
        self.page = None  # Playwrightのページオブジェクト
        self.context = None  # Playwrightのコンテキストオブジェクト
        self.browser = None  # Playwrightのブラウザオブジェクト

    def start_login(self, email, password):
        """ログインプロセスの開始処理"""
        if self.status in ['LOGGING_IN', 'WAITING_FOR_2FA']:
            return False
        
        self.status = 'LOGGING_IN'
        self.error_message = None
        self.otp_queue = queue.Queue()
        
        # バックグラウンドスレッドでログイン処理を実行
        self.thread = threading.Thread(target=self._run_login, args=(email, password))
        self.thread.daemon = True
        self.thread.start()
        return True

    def submit_otp(self, otp_code):
        """二段階認証コードの送信処理"""
        if self.status != 'WAITING_FOR_2FA':
            return False
        self.otp_queue.put(otp_code)
        return True

    def _run_login(self, email, password):
        """ログインの実行処理 (Playwrightスレッド)"""
        with sync_playwright() as p:
            try:
                # ブラウザの起動 (有向モードでreCAPTCHA対応)
                self.browser = p.chromium.launch(headless=False)
                self.context = self.browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                self.page = self.context.new_page()

                # ログイン画面へ遷移
                self.page.goto("https://accounts.dmm.co.jp/service/login/password/")
                self.page.wait_for_load_state("networkidle")

                # IDとパスワードの自動入力 (入力値が存在する場合のみ実行)
                if email and password:
                    try:
                        self.page.fill("input#login_id", email)
                        self.page.fill("input#password", password)
                        self.page.click("button[type='submit'], input[type='submit']")
                    except Exception as fe:
                        fanza_logger.warning(f"[AUTH] 自動入力に失敗したため手動入力を待機: {str(fe)}")
                else:
                    fanza_logger.info("[AUTH] 認証情報が空であるため、ブラウザを起動して手動/ソーシャルログインを待機")
                
                # ログイン完了または2FA画面の動的待機 (最大20秒)
                is_2fa_detected = False
                secid_found = False
                for _ in range(240):  # 最大120秒間待機
                    try:
                        self.page.wait_for_timeout(500)
                        current_url = self.page.url
                        
                        # 2FA画面の表示確認 (自動ログイン時のみ)
                        if email and password and ("two_step_verification" in current_url or self.page.locator("input#code").count() > 0):
                            is_2fa_detected = True
                            break
                            
                        # ログイン完了の確認 (secid Cookie of 検知)
                        cookies = self.context.cookies()
                        if any(c['name'] == 'secid' for c in cookies):
                            secid_found = True
                            break
                    except Exception:
                        pass

                # 二段階認証が必要か判定
                if is_2fa_detected:
                    self.status = 'WAITING_FOR_2FA'
                    
                    try:
                        # フロントからのOTP送信を最大120秒間待機
                        otp_code = self.otp_queue.get(timeout=120)
                    except queue.Empty:
                        self.status = 'FAILED'
                        self.error_message = "二段階認証の待機がタイムアウトしました。"
                        self._cleanup()
                        return

                    # 認証コードの入力および送信
                    self.page.fill("input#code", otp_code)
                    self.page.click("button[type='submit'], input[type='submit']")
                    
                    # 2FA送信後のログイン完了待機 (最大120秒)
                    for _ in range(240):
                        try:
                            self.page.wait_for_timeout(500)
                            cookies = self.context.cookies()
                            if any(c['name'] == 'secid' for c in cookies):
                                secid_found = True
                                break
                        except Exception:
                            pass

                # ログイン成功の判定とCookie取得
                try:
                    cookies = self.context.cookies()
                except Exception:
                    cookies = []
                
                # 必須Cookieの存在確認
                if secid_found or any(c['name'] == 'secid' for c in cookies):
                    # 年齢確認回避Cookieの強制設定
                    cookies.append({
                        'name': 'age_check_done',
                        'value': '1',
                        'domain': '.dmm.co.jp',
                        'path': '/'
                    })
                    
                    # CookieデータのJSON化処理
                    cookie_json = json.dumps(cookies)
                    
                    # データベースへの永続化処理
                    db_email = email if email else "social_login_user"
                    session = db_session.query(UserSession).filter_by(email=db_email).first()
                    if session:
                        session.cookie_data = cookie_json
                        session.is_active = True
                        session.updated_at = datetime.utcnow()
                    else:
                        session = UserSession(email=db_email, cookie_data=cookie_json, is_active=True)
                        db_session.add(session)
                    
                    db_session.commit()
                    self.status = 'SUCCESS'
                else:
                    self.status = 'FAILED'
                    self.error_message = "ログインに失敗しました。認証情報を確認してください。"
            
            except Exception as e:
                self.status = 'FAILED'
                self.error_message = f"ログインエラー: {str(e)}"
            
            finally:
                self._cleanup()

    def _cleanup(self):
        """リソースの解放処理"""
        try:
            if self.browser:
                self.browser.close()
        except:
            pass
        self.page = None
        self.context = None
        self.browser = None

# グローバルなログインマネージャーインスタンスの作成
login_manager = LoginManager()