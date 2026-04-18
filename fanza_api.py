import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()
MY_COOKIE = os.getenv("FANZA_COOKIE")#Cookieの取得

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",#ブラウザのUser-Agentを指定
    "Accept": "application/json, text/plain, */*" #Acceptヘッダーを指定
}

def fetch_purchased_cids():#購入した作品のCIDを取得する関数
    if not MY_COOKIE:     #Cookieが設定されていない場合のエラーハンドリング
        print("FANZAのCookieが設定されていません。環境変数FANZA_COOKIEにCookieを設定してください。")
        return{}
    
    api_url = "https://www.dmm.co.jp/dc/doujin/api/mylibraries/" #FANZAのAPIエンドポイント 
    headers = HEADERS.copy() #リクエストヘッダーをコピーしてCookieを追加
    headers["Cookie"] = MY_COOKIE #Cookieの設定
    headers["Referer"] = "https://www.dmm.co.jp/dc/-/mylibrary/" #Refererヘッダーを設定 

    purchased_dict = {} #購入した作品のCIDを格納する辞書
    page = 1 #ページ番号の初期化
    limit =50  #1ページあたりの作品数の設定


    while True: #ページ取得ループの開始
        params = {"page": page, "sort": "purchasedate_desc", "genre": all, "limit": limit} #APIリクエストのパラメータを設定
        response = requests.get(api_url, headers=headers, params=params) #APIリクエストの送信

        if response.status_code != 200: #APIリクエストが成功しなかった場合のエラーハンドリング
            print(f"APIリクエストに失敗しました。ステータスコード: {response.status_code}")
            break

        try:
            data = response.json() #APIレスポンスをJSON形式で解析   
        except ValueError: #JSON解析に失敗した場合のエラーハンドリング
            print("APIレスポンスのJSON解析に失敗しました。")
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

    return purchased_dict #購入した作品のCIDを格納した辞書を返す

def fetch_work_mylists(cid): #マイリスト情報取得処理の定義
    if not MY_COOKIE: #Cookieが設定されていない場合のエラーハンドリング
        print("FANZAのCookieが設定されていません。環境変数FANZA_COOKIEにCookieを設定してください。")
        return []
    
    api_url = "https://www.dmm.co.jp/dc/doujin/api/mylibrary-mylists/" #マイリスト用のエンドポイントの定義
    headers = HEADERS.copy() #リクエストヘッダーをコピーしてCookieを追加
    headers["Cookie"] = MY_COOKIE #Cookieの設定
    headers["Referer"] = "https://www.dmm.co.jp/dc/-/mylibrary/" #Refererヘッダーを設定

    response = requests.get(api_url, headers=headers, params={"productId": cid}) #APIリクエストの送信

    if response.status_code != 200: #APIリクエストが成功しなかった場合のエラーハンドリング
        print(f"APIリクエストに失敗しました。ステータスコード: {response.status_code}")
        return []

    try:
        data = response.json() #APIレスポンスをJSON形式で解析
        items = data.get("data", {}).get("items", []) #マイリストアイテムの取得
        return [item["mylistName"]] for item in items if item.get("isRegistered") is True] #マイリストに登録されているアイテムのマイリスト名をリストで返す
    except ValueError: #JSON解析に失敗した場合のエラーハンドリング
        print("APIレスポンスのJSON解析に失敗しました。")
        return []


    mylists = data.get("data", {}).get("mylists", []) #APIレスポンスからマイリスト情報を取得
    return mylists #マイリスト情報を返す