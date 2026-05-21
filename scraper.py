import sqlite3
import bs4
import os
import requests
import json
from dotenv import load_dotenv

#スクレイピングでデータを取り出し、jsonファイル形式で保存する
def scrape_fetch_purchased():

    #データベースに接続
    con = sqlite3.connect("fanza_data.db")

    #カーソルを生成
    cur = con.cursor()

    #テーブルの商品IDを取得
    cur.execute("SELECT contentId FROM = ?")
    purchases_ID = cur.fetchall()

    for id in purchases_ID():
        print(id)
    #取得した商品IDのwebページにアクセス
    #スクレイピングで足りない商品情報を取り出す
    #IDとその他商品情報でまとめられた辞書のリストをjson形式で保存
    #待機時間0.5

scrape_fetch_purchased()