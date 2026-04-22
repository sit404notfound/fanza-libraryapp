import requests
import bs4
import os
from dotenv import load_dotenv

MYPURCHASES_API_URL = "https://www.dmm.co.jp/dc/doujin/api/mylibraries/?page=1&sort=purchasedate_desc&genre=all&limit=20"


def feach_purchased_data():
    #cookieをenvファイルから呼び出し
    load_dotenv()
    FANZA_COOKIE = os.getenv("FANZA_COOKIE")

    #変数代入
    
    API_MAX_PAGES = 1000
    API_max_items = 20
    HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
               "cookie": FANZA_COOKIE}
    
    #requestsでAPIにアクセス
    r = requests.get(url=MYPURCHASES_API_URL, headers=HEADERS)
    print(r.status_code)

feach_purchased_data()