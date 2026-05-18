import sqlite3
import json
import scraper

#API_response.jsonとscrape_data.jsonファイルのデータをfanza_data.dbに保存する
def save_purchased_data():

    #API_valuesにAPI_responseの辞書型のデータを保存
    API_values = []

    #API_response.jsonファイルを読み込み
    with open("API_response.json", "r", encoding="utf-8") as f:
        API_response = json.load(f)    

    #API_responseのデータが入っている構造を取得するため日付に対するvalueを代入
    API_response_items = API_response["data"]["items"]

    #API_responseの日付:データのリストin辞書を平坦化
    for data in API_response_items.items():
        for i in range(len(data[1])):
            #日付が0、商品情報が1に入ってる
            purchase_date = data[0]
            purchase_item = data[1][i]

            #商品情報に日付情報を追加
            purchase_item["data"] = purchase_date
            API_values.append(purchase_item)

    #データベースファイル作成
    fanza_data = sqlite3.connect("fanza_data.db")

    #データベースに接続
    cur = fanza_data.cursor()

    #ここからチャッピー
    columns = []

    for key, value in API_values[0].items():

        if isinstance(value, bool):
            sql_type = "INTEGER"

        elif isinstance(value, int):
            sql_type = "INTEGER"

        else:
            sql_type = "TEXT"

        columns.append(f"{key} {sql_type}")

    columns_sql = ", ".join(columns)

    # -----------------------------
    # テーブル作成
    # -----------------------------

    create_sql = f"""
    CREATE TABLE IF NOT EXISTS products (
        {columns_sql}
    )
    """

    cur.execute(create_sql)

    # -----------------------------
    # INSERT文作成
    # -----------------------------

    column_names = ", ".join(API_values[0].keys())

    placeholders = ", ".join(["?"] * len(API_values[0]))

    insert_sql = f"""
    INSERT INTO products ({column_names})
    VALUES ({placeholders})
    """

    # -----------------------------
    # データ追加
    # -----------------------------

    for data in API_values:

        values = tuple(data.values())

        cur.execute(insert_sql, values)

    # 保存
    fanza_data.commit()

    fanza_data.close()
save_purchased_data()