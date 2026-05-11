import requests
import bs4
import os
import re
import json
from dotenv import load_dotenv

MYPURCHASES_API_URL = "https://www.dmm.co.jp/dc/doujin/api/mylibraries/?page=1&sort=purchasedate_desc&genre=all&limit=20"

#APIとスクレイピングでデータを取り出し、jsonファイル形式で保存する
def fetch_purchased_data():

    #cookieをenvファイルから呼び出し
    load_dotenv()
    FANZA_COOKIE = {"cookie": os.getenv("FANZA_COOKIE")}

    #変数代入
    API_MAX_PAGES = 1000
    API_max_items = 20
    HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"}
    
    #requestsでAPIにアクセスしてjson形式に変換
    API_response = requests.get(url=MYPURCHASES_API_URL, headers=HEADERS, cookies=FANZA_COOKIE).json()

    #API_response.jsonにAPIのデータを保存
    with open("API_response.json", "w", encoding="utf-8") as f:
        json.dump(API_response, f, ensure_ascii=False, indent=4)

fetch_purchased_data()