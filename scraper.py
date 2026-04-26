import requests
import bs4
import os
import re
import json
from dotenv import load_dotenv

MYPURCHASES_API_URL = "https://www.dmm.co.jp/dc/doujin/api/mylibraries/?page=1&sort=purchasedate_desc&genre=all&limit=20"


def fetch_purchased_data():
    #cookieをenvファイルから呼び出し
    load_dotenv()
    FANZA_COOKIE = {"cookie": os.getenv("FANZA_COOKIE")}

    #変数代入
    API_MAX_PAGES = 1000
    API_max_items = 20
    HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"}
    all_data = []
    
    #requestsでAPIにアクセス、テキスト形式で取得
    API_response = requests.get(url=MYPURCHASES_API_URL, headers=HEADERS, cookies=FANZA_COOKIE).text

    #[]の中身だけを取り出してリスト化
    data_list = re.findall(r"\[(.*?)\]", API_response)

   
    for i in data_list:
        try:#リストの中身が{}で囲まれただけのstrならjsonを読み込む
            all_data.append(json.loads(i))

        except:#複数ある場合はもう一度{}で分割して同様にjson形式を読み込む
            split_data = re.findall(r"\{.*?\}", i)
            for k in split_data:
                all_data.append(json.loads(k))

    #all_dataには[{商品ごとの情報}, {...}, {...}]という形で書かれてる    
    for purchases in all_data:
        title = purchases["title"]
        #これでタイトルだけを取り出す
        print(title)
fetch_purchased_data()