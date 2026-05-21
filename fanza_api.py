import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()
MY_COOKIE = os.getenv("FANZA_COOKIE")

HEADER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36","Accept": "application/json, text/javascript, */*",}

def fetch_purchased_cids():
    if not MY_COOKIE:
        print("FANZA_COOKIEが未設定")
        return {}
    api_url = "[https://www.dmm.co.jp/dc/doujin/api/mylibraries/](https://www.dmm.co.jp/dc/doujin/api/mylibraries/)"
    header = HEADER.copy()
    header["Cookie"] = MY_COOKIE
    header["Referer"] = "[https://www.dmm.co.jp/dc/-/mylibrary/](https://www.dmm.co.jp/dc/-/mylibrary/)"
    purchased_cids = {}
    page, limit = 1, 50

    while True:
        params = {"page":page, "sort":"purchasedate_desc","genre":"all","limit":limit}
        response = requests.get(api_url, headers=header, params=params)
        if response.status_code != 200: break
        try: data = response.json()
        except ValueError: break

        items_dict = data.get("data",{}).get("items",{})
        item_count_in_page = 0
        if isinstance(items_dict, dict):
            for data_key, works in items_dict.items():
                for work in works:
                    cid = work.get("content_Id") or work.get("productId")
                    if cid:
                        purchased_cids[cid] = {
                            "title": work.get("title",""),
                            "circle": work.get("makerName",""),
                            "genre": work.get("genre",""),
                            "is_unavailable": work.get("isUnavailable", False),
                            "is_streaming": work.get("isStreaming", False),
                            "purchased_date": date_key,
                            "is_mylist_registered": work.get("isMylistRegistered", False),
                        }
                        item_count_in_page += 1
        if item_count_in_page == 0: break
        page += 1
    return purchased_dict