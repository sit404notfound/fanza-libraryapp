import os
import time
import requests
from dotenv import load_dotenv
import json
from requests.exceptions import RequestException

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",#ブラウザのUser-Agentを指定
    "Accept": "application/json, text/plain, */*" #Acceptヘッダーを指定
}
MAX_PAGES = 1000 #最大ページ数の設定（安全策として）

def get_session(): #API通信用のセッションを構築
    load_dotenv() #環境変数の読み込み
    cookie = os.getenv("FANZA_COOKIE") #Cookieの取得
    
    session = requests.Session() #セッションの作成
    session.headers.update(HEADERS) #セッションのヘッダーに共通ヘッダーを設定
    if cookie: #Cookieが存在する場合の処理
        session.headers.update({"Cookie": cookie}) #セッションのヘッダーにCookieを追加
    return session


def fetch_purchased_cids():#購入した作品のCIDを取得する関数
    session = get_session() #API通信用のセッションを取得
    if "Cookie" not in session.headers: #セッションにCookieが設定されていない場合のエラーハンドリング
        print("FANZAのCookieが設定されていません。環境変数FANZA_COOKIEにCookieを設定してください。")
        return {}
    
    api_url = "https://www.dmm.co.jp/dc/doujin/api/mylibraries/"
    session.headers.update({"Referer": "https://www.dmm.co.jp/dc/-/mylibrary/"}) #Refererヘッダーを設定

    purchased_dict = {} #購入した作品のCIDを格納する辞書
    page = 1 #ページ番号の初期化
    limit =50  #1ページあたりの作品数の設定


    while page <= MAX_PAGES: #ページ取得ループの開始
        params = {"page": page, "sort": "purchasedate_desc", "genre": "all", "limit": limit} #APIリクエストのパラメータを設定
        
        try: # ネットワークリクエストの実行
            response = session.get(api_url, params=params, timeout=10)
            response.raise_for_status() # HTTPエラーを捕捉
            data = response.json()
        except RequestException as e: # 通信エラーやタイムアウトの捕捉
            print(f"APIリクエスト時にネットワークエラーが発生: {e}")
            break
        except ValueError: # JSONパースエラーの捕捉
            print("APIレスポンスのJSON解析に失敗。")
            break

        items_dict = data.get("data", {}).get("items", {}) #APIレスポンスから作品情報を取得
        item_count_in_page = 0 #現在のページに含まれる作品数のカウンタを初期化

        if isinstance(items_dict, dict): #辞書型の判定
            for date_key, works in items_dict.items(): #日付ごとのループ処理
                for work in works: #作品ごとのループ処理
                    cid = work.get("contentId") or work.get("productId")#作品のCIDを取得
                    if cid: #CIDが存在する場合に辞書に追加
                        purchased_dict[cid] = {
                            "title": work.get("title", ""), #作品のタイトルを取得
                            "circle": work.get("makerName", ""), #サークル名を取得
                            "genre": work.get("genre", ""), #大分類ジャンルを取得
                            "is_unavailable": work.get("isUnavailable", False), #購入停止のフラグの取得
                            "is_streaming": work.get("isStreaming", False), #ストリーミングのフラグの取得
                            "purchase_date": date_key, #購入日を取得
                            "is_mylist_registered": work.get("isMylistRegistered", False) #マイリスト登録のフラグの取得
                        }
                        item_count_in_page += 1 #取得件数の加算

        if item_count_in_page == 0: #取得件数0の判定
            break #ループの終了

        page += 1 #次のページへ進むためのページ番号の加算
        time.sleep(1) #APIリクエストの間隔を空ける

    if page > MAX_PAGES: #最大ページ数を超えた場合の警告
        print(f"警告: 最大ページ数 {MAX_PAGES} に達しました。全てのデータが取得できていない可能性があります。")

    return purchased_dict #購入した作品のCIDを格納した辞書を返す

def fetch_work_mylists(cid): #マイリスト情報取得処理の定義
    session = get_session()
    if "Cookie" not in session.headers:
        print("FANZAのCookieが設定されていません。")
        return []
    
    api_url = "https://www.dmm.co.jp/dc/doujin/api/mylibrary-mylists/"
    session.headers.update({"Referer": "https://www.dmm.co.jp/dc/-/mylibrary/"})

    try: # APIリクエストの送信
        response = session.get(api_url, params={"productId": cid}, timeout=10)
        response.raise_for_status()
        data = response.json()
        items = data.get("data", {}).get("items", [])
        return [item["mylistName"] for item in items if item.get("isRegistered") is True]
    except (RequestException, ValueError) as e: # エラーの捕捉
        print(f"マイリスト取得エラー (CID: {cid}): {e}")
        return []
    
def fetch_detail_html(cid):  # 詳細HTML取得処理の定義
    session = get_session() # API通信用のセッションを取得
    url = f"https://www.dmm.co.jp/dc/doujin/-/detail/=/cid={cid}/" # 対象URLの構築
    cookies = {"age_check_done": "1"} # 年齢確認用Cookieの定義

    try: # GETリクエストの送信
        response = session.get(url, cookies=cookies, timeout=10)
        response.raise_for_status()
        return response.text
    except RequestException as e: # 通信エラーの捕捉
        print(f"HTML取得エラー (CID: {cid}): {e}")
        return None

def run_tests(): # テスト実行関数を定義
    print("=== fetch_purchased_cids のテスト ===") # 開始メッセージの出力
    purchased_data = fetch_purchased_cids() # 購入済みCID一覧の取得
    
    if not purchased_data: # データ有無の判定
        print("データの取得に失敗、またはCookieが未設定。") # エラーの出力
        return # 処理の終了

    print(f"取得件数: {len(purchased_data)}件") # 取得件数の出力
    sample_cid = list(purchased_data.keys())[0] # サンプル用CIDの抽出
    print(f"サンプルデータ ({sample_cid}):") # 対象CIDの出力
    print(json.dumps(purchased_data[sample_cid], ensure_ascii=False, indent=2)) # JSON形式での整形出力

    print("\n=== fetch_work_mylists のテスト ===") # 開始メッセージの出力
    mylists = fetch_work_mylists(sample_cid) # マイリスト情報の取得
    print(f"CID '{sample_cid}' の登録マイリスト: {mylists}") # 結果の出力

    print("\n=== fetch_detail_html のテスト ===") # 開始メッセージの出力
    html_text = fetch_detail_html(sample_cid) # 詳細HTMLの取得
    if html_text: # 取得成功の判定
        print(f"HTML取得成功 (総文字数: {len(html_text)})") # 文字数の出力
        print(f"先頭200文字の確認:\n{html_text[:200]}...") # 内容の一部出力
    else: # 取得失敗の判定
        print("HTMLの取得に失敗。") # エラーの出力

if __name__ == "__main__": # メインモジュール実行の判定
    run_tests() # テストの実行