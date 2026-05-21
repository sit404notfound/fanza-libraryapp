import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()
MY_COOKIE = os.getenv("FANZA_COOKIE")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*"
}

def fetch_purchased_cids():
    if not MY_COOKIE:
        print("FANZA_COOKIEが未設定")
        return {}
    api_url = "https://www.dmm.co.jp/dc/doujin/api/mylibraries/"
    headers = HEADERS.copy()
    headers["Cookie"] = MY_COOKIE
    headers["Referer"] = "https://www.dmm.co.jp/dc/-/mylibrary/"
    purchased_dict = {}
    page, limit = 1, 50

    while True:
        params = {"page": page, "sort": "purchasedate_desc", "genre": "all", "limit": limit}
        response = requests.get(api_url, headers=headers, params=params)
        if response.status_code != 200: break
        try: data = response.json()
        except ValueError: break

        items_dict = data.get("data", {}).get("items", {})
        item_count_in_page = 0
        if isinstance(items_dict, dict):
            for date_key, works in items_dict.items():
                for work in works:
                    cid = work.get("contentId") or work.get("productId")
                    if cid:
                        purchased_dict[cid] = {
                            "title": work.get("title", ""),
                            "circle": work.get("makerName", ""),
                            "genre": work.get("genre", ""),
                            "is_unavailable": work.get("isUnavailable", False),
                            "is_streaming": work.get("isStreaming", False),
                            "purchase_date": date_key,
                            "is_mylist_registered": work.get("isMylistRegistered", False)
                        }
                        item_count_in_page += 1
        if item_count_in_page == 0: break
        page += 1
        time.sleep(1.0)
    return purchased_dict

def fetch_work_mylists(cid):
    if not MY_COOKIE: return []
    api_url = "https://www.dmm.co.jp/dc/doujin/api/mylibrary-mylists/"
    headers = HEADERS.copy()
    headers["Cookie"] = MY_COOKIE
    headers["Referer"] = "https://www.dmm.co.jp/dc/-/mylibrary/"
    response = requests.get(api_url, headers=headers, params={"productId": cid})
    if response.status_code != 200: return []
    try:
        data = response.json()
        items = data.get("data", {}).get("items", [])
        return [item["mylistName"] for item in items if item.get("isRegistered") is True]
    except ValueError: return []

def fetch_detail_html(cid):
    url = f"https://www.dmm.co.jp/dc/doujin/-/detail/=/cid={cid}/"
    cookies = {"age_check_done": "1"}
    response = requests.get(url, headers=HEADERS, cookies=cookies)
    if response.status_code != 200: return None
    return response.text

if __name__ == "__main__":
    print("購入済み作品を取得")
    purchased = fetch_purchased_cids()
    print(f"取得件数: {len(purchased)}件")
    
    if purchased:
        # 最初の作品IDを抽出
        first_cid = list(purchased.keys())[0]
        print(f"\nテスト用CID: {first_cid}")
        print(f"タイトル: {purchased[first_cid]['title']}")
        
        print("\nマイリスト情報を取得中...")
        mylists = fetch_work_mylists(first_cid)
        print(f"登録マイリスト: {mylists}") 
        
        print("\n詳細ページのHTMLを取得中...")
        html = fetch_detail_html(first_cid)
        html_length = len(html) if html else 0
        print(html[:500])  # HTMLの最初の500文字を表示
        print(f"HTML取得完了 (文字数: {html_length})")