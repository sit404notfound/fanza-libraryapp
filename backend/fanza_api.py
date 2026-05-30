import time
import requests
import json

# 共通ヘッダー定義
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
}

def parse_cookie_json(cookie_json):
    """JSON形式のCookieを辞書型に変換する処理"""
    try:
        cookies_list = json.loads(cookie_json)
        cookie_dict = {c['name']: c['value'] for c in cookies_list}
        # 年齢確認回避Cookieの強制設定
        cookie_dict['age_check_done'] = '1'
        return cookie_dict
    except Exception:
        return {'age_check_done': '1'}

def fetch_purchased_page(cookie_json, page=1, limit=50):
    """購入済み作品一覧の1ページ分を取得するAPI通信処理"""
    api_url = "https://www.dmm.co.jp/dc/doujin/api/mylibraries/"
    headers = HEADERS.copy()
    headers["Referer"] = "https://www.dmm.co.jp/dc/-/mylibrary/"
    
    cookies = parse_cookie_json(cookie_json)
    params = {
        "page": page,
        "sort": "purchasedate_desc",
        "genre": "all",
        "limit": limit
    }
    
    try:
        response = requests.get(api_url, headers=headers, params=params, cookies=cookies, timeout=15)
        if response.status_code != 200:
            return None
        return response.json()
    except Exception:
        return None

def fetch_work_mylists(cookie_json, cid):
    """作品の登録マイリスト情報を取得するAPI通信処理"""
    api_url = "https://www.dmm.co.jp/dc/doujin/api/mylibrary-mylists/"
    headers = HEADERS.copy()
    headers["Referer"] = "https://www.dmm.co.jp/dc/-/mylibrary/"
    
    cookies = parse_cookie_json(cookie_json)
    params = {"productId": cid}
    
    try:
        response = requests.get(api_url, headers=headers, params=params, cookies=cookies, timeout=15)
        if response.status_code != 200:
            return []
        data = response.json()
        items = data.get("data", {}).get("items", [])
        # isRegisteredがTrueのマイリスト名のみ抽出
        return [item["mylistName"] for item in items if item.get("isRegistered") is True]
    except Exception:
        return []

def fetch_detail_html(cookie_json, cid):
    """作品詳細ページのHTMLを取得する通信処理"""
    url = f"https://www.dmm.co.jp/dc/doujin/-/detail/=/cid={cid}/"
    headers = HEADERS.copy()
    cookies = parse_cookie_json(cookie_json)
    
    try:
        response = requests.get(url, headers=headers, cookies=cookies, timeout=15)
        if response.status_code != 200:
            return None
        # 文字化け防止のためのエンコーディング明示処理
        response.encoding = 'utf-8'
        return response.text
    except Exception:
        return None

def fetch_detail_html_anonymous(cid):
    """Cookie無し（未ログイン状態）で詳細ページHTMLを取得する処理。
    未ログインHTMLには価格セクションが表示されるため定価とセール価格を正確に取得可能。"""
    url = f"https://www.dmm.co.jp/dc/doujin/-/detail/=/cid={cid}/"
    headers = HEADERS.copy()
    cookies = {'age_check_done': '1'}

    try:
        response = requests.get(url, headers=headers, cookies=cookies, timeout=15)
        if response.status_code != 200:
            return None
        response.encoding = 'utf-8'
        return response.text
    except Exception:
        return None
