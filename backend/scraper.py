import re
import json
from bs4 import BeautifulSoup
from logger import fanza_logger

# 辞書やリストから再帰的に特定のキーを検索してその値を返すヘルパー関数
def find_key_recursive(data, target_key):
    if isinstance(data, dict):
        if target_key in data:
            return data[target_key]
        for k, v in data.items():
            res = find_key_recursive(v, target_key)
            if res is not None:
                return res
    elif isinstance(data, list):
        for item in data:
            res = find_key_recursive(item, target_key)
            if res is not None:
                return res
    return None

# JSON-LD文字列から不要なコメントやCDATAマークアップをクリーンアップするヘルパー関数
def clean_json_ld_string(ld_str):
    if not ld_str:
        return ""
    ld_str = re.sub(r'//<!\[CDATA\[|//\]\]>', '', ld_str)
    ld_str = re.sub(r'/\*.*?\*/', '', ld_str, flags=re.DOTALL)
    ld_str = re.sub(r'^\s*//.*$', '', ld_str, flags=re.MULTILINE)
    ld_str = ld_str.strip()
    if ld_str.endswith(';'):
        ld_str = ld_str[:-1].strip()
    return ld_str

def parse_detail_html(html_text):
    """HTMLテキストから詳細メタデータを抽出する処理"""
    if not html_text:
        fanza_logger.warning("[SCRAPER] パース対象のHTMLテキストが空です。")
        return {}

    fanza_logger.info(f"[SCRAPER] 詳細HTMLのパースを開始します (サイズ: {len(html_text)} 文字)")
    soup = BeautifulSoup(html_text, 'html.parser')
    data = {}

    # 1. メイン画像URLの抽出処理
    try:
        og_image_meta = soup.find('meta', property='og:image')
        main_image = og_image_meta['content'] if og_image_meta else None
        # パッケージ画像のフォールバック
        if not main_image:
            img_elem = soup.find(id="package-src") or soup.find(class_="package")
            if img_elem:
                main_image = img_elem.get('src') or img_elem.get('data-src')
        data['main_image'] = main_image
    except Exception:
        data['main_image'] = None

    # 2. 価格の抽出および数値変換処理 (ログイン済みHTMLではJSON-LDからの取得がメイン)
    try:
        price_text = ""
        # 通常の価格表示部分からの抽出
        price_elem = (
            soup.find(class_='priceList__main') or 
            soup.find(class_='price') or
            soup.find(class_='priceList__main--small')
        )
        if price_elem:
            price_text = re.sub(r'[^\d]', '', price_elem.get_text())
            
        # メタタグからのフォールバック抽出 (購入済み商品の価格取得対策)
        if not price_text:
            meta_price = (
                soup.find('meta', itemprop='price') or 
                soup.find('meta', property='dg:price') or 
                soup.find('meta', attrs={'name': 'dg:price'}) or
                soup.find('meta', property='product:price:amount')
            )
            if meta_price:
                price_text = meta_price.get('content', '')
                
        # JSON-LD構造化データからのフォールバック抽出
        if not price_text:
            for script in soup.find_all('script', type='application/ld+json'):
                if not script.string:
                    continue
                try:
                    cleaned_str = clean_json_ld_string(script.string)
                    js_data = json.loads(cleaned_str)
                    val = find_key_recursive(js_data, 'price')
                    if val is not None:
                        price_text = str(val)
                        break
                except Exception as je:
                    fanza_logger.error(f"[SCRAPER] JSON-LDパース失敗: {str(je)}")

        # スペックテーブルからのフォールバック検索
        if not price_text:
            for table in soup.find_all('table'):
                for tr in table.find_all('tr'):
                    th = tr.find('th')
                    td = tr.find('td')
                    if th and td and ('価格' in th.get_text() or '販売価格' in th.get_text()):
                        price_text = re.sub(r'[^\d]', '', td.get_text())
                        break
                        
        data['price'] = int(price_text) if price_text else 0
        # ログイン済みHTMLではlist_priceが取れないためpriceと同値をデフォルトに
        data['list_price'] = data['price']
        data['sale_price'] = None
        data['campaign_text'] = None
    except Exception as e:
        fanza_logger.error(f"[SCRAPER] 価格処理中に例外発生: {str(e)}")
        data['price'] = 0
        data['list_price'] = 0
        data['sale_price'] = None
        data['campaign_text'] = None

    # 3. あらすじの抽出
    try:
        desc_elem = soup.find(class_='summary') or soup.find(attrs={"name": "description"})
        if desc_elem:
            if desc_elem.name == 'meta':
                data['description'] = desc_elem.get('content', '').strip()
            else:
                data['description'] = desc_elem.get_text(separator='\n').strip()
        else:
            data['description'] = ""
    except Exception:
        data['description'] = ""

    # 4. サンプル画像URLリストの抽出処理
    try:
        sample_images = []
        # fn-sample-images クラスからの抽出
        sample_wrapper = soup.find(class_='fn-sample-images')
        if sample_wrapper:
            for img in sample_wrapper.find_all('img'):
                src = img.get('src') or img.get('data-src')
                if src and src not in sample_images:
                    sample_images.append(src)
                    
        # sampleを含む画像のフォールバック検索
        if not sample_images:
            for img in soup.find_all('img'):
                cls = img.get('class', [])
                is_sample = False
                if isinstance(cls, list):
                    is_sample = any('sample' in c for c in cls)
                elif isinstance(cls, str):
                    is_sample = 'sample' in cls
                    
                if is_sample:
                    src = img.get('src') or img.get('data-src')
                    if src and src not in sample_images:
                        sample_images.append(src)
        data['sample_images'] = sample_images
    except Exception:
        data['sample_images'] = []

    # 5. 作者リストの抽出処理
    try:
        authors = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if 'author_id=' in href or '/author-detail/' in href or '/author/' in href:
                author_name = a.get_text().strip()
                if author_name and '一覧' not in author_name and author_name not in authors:
                    authors.append(author_name)
        data['author'] = authors
    except Exception:
        data['author'] = []

    # 6. 詳細スペック情報の抽出処理 (dl-dt-dd 構造および table 構造)
    try:
        specs = {}
        
        # dl.informationList 構造の走査 (最新のDMM同人仕様)
        for dl in soup.find_all('dl'):
            cls = dl.get('class', [])
            cls_str = ' '.join(cls) if isinstance(cls, list) else str(cls)
            if 'informationList' in cls_str:
                dts = dl.find_all('dt')
                dds = dl.find_all('dd')
                for dt, dd in zip(dts, dds):
                    key = dt.get_text().strip()
                    val_list = [s.strip() for s in dd.stripped_strings if s.strip()]
                    cleaned_list = []
                    for v in val_list:
                        if v in ('/', ',', '、', '|'):
                            continue
                        cleaned_list.append(v)
                    val = ', '.join(cleaned_list)
                    if key:
                        specs[key] = val
                        
        # 従来の table 構造の走査 (フォールバック、deviceInfo除く)
        for table in soup.find_all('table'):
            cls = table.get('class', [])
            cls_str = ' '.join(cls) if isinstance(cls, list) else str(cls)
            if 'deviceInfo' in cls_str:
                continue
            for tr in table.find_all('tr'):
                th = tr.find('th')
                td = tr.find('td')
                if th and td:
                    key = th.get_text().strip()
                    val_list = [s.strip() for s in td.stripped_strings if s.strip()]
                    cleaned_list = []
                    for v in val_list:
                        if v in ('/', ',', '、', '|'):
                            continue
                        cleaned_list.append(v)
                    val = ', '.join(cleaned_list)
                    if key:
                        specs[key] = val
                        
        data['specifications'] = specs
    except Exception as e:
        fanza_logger.error(f"[SCRAPER] スペック解析中に例外発生: {str(e)}")
        data['specifications'] = {}

    fanza_logger.info(f"[SCRAPER] パース完了: 画像={data.get('main_image')}, 価格={data.get('price')}, スペック項目数={len(data.get('specifications', {}))}")
    return data


def parse_price_html(html_text):
    """未ログインHTMLから定価・セール価格・キャンペーン情報を正確に抽出する処理。
    未ログインHTMLではpriceListセクションが表示されるため、以下が取得可能:
    - priceList__main: セール後の実売価格
    - priceList__sub: サークル設定価格（定価）
    - productTitle__txt--campaign: セール情報テキスト
    """
    if not html_text:
        return {}

    soup = BeautifulSoup(html_text, 'html.parser')
    result = {}

    try:
        # キャンペーン情報の抽出 (例: "【80%OFF】")
        campaign_elem = soup.find(class_='productTitle__txt--campaign')
        if campaign_elem:
            campaign_raw = campaign_elem.get_text().strip()
            # 【】内のテキストを抽出
            match = re.search(r'【(.+?)】', campaign_raw)
            result['campaign_text'] = match.group(1) if match else campaign_raw
        else:
            result['campaign_text'] = None

        # セール後の実売価格の抽出 (priceList__main)
        sale_price = 0
        main_price_elem = soup.find(class_=re.compile(r'priceList__main(?!--small)'))
        if main_price_elem:
            price_digits = re.sub(r'[^\d]', '', main_price_elem.get_text())
            if price_digits:
                sale_price = int(price_digits)

        # JSON-LDからのフォールバック
        if not sale_price:
            for script in soup.find_all('script', type='application/ld+json'):
                if not script.string:
                    continue
                try:
                    cleaned_str = clean_json_ld_string(script.string)
                    js_data = json.loads(cleaned_str)
                    val = find_key_recursive(js_data, 'price')
                    if val is not None:
                        sale_price = int(val)
                        break
                except Exception:
                    pass

        result['sale_price'] = sale_price if sale_price > 0 else None

        # サークル設定価格（定価）の抽出 (priceList__sub)
        list_price = 0
        sub_elems = soup.find_all(class_='priceList__sub')
        for elem in sub_elems:
            text = elem.get_text().strip()
            # 「サークル設定価格」等のラベル行はスキップ
            if 'サークル' in text or '設定価格' in text:
                # ラベル行の次の兄弟要素に金額がある場合もあるため、この要素内の数字も試す
                digits = re.sub(r'[^\d]', '', text)
                if digits and int(digits) > 0:
                    list_price = int(digits)
                continue
            digits = re.sub(r'[^\d]', '', text)
            if digits:
                list_price = int(digits)
                break

        # priceList__sub--big からのフォールバック
        if not list_price:
            big_elem = soup.find(class_='priceList__sub--big')
            if big_elem:
                digits = re.sub(r'[^\d]', '', big_elem.get_text())
                if digits:
                    list_price = int(digits)

        result['list_price'] = list_price if list_price > 0 else sale_price

        fanza_logger.info(
            f"[SCRAPER] 価格パース完了: 定価={result['list_price']}, "
            f"セール価格={result.get('sale_price')}, "
            f"キャンペーン={result.get('campaign_text')}"
        )
    except Exception as e:
        fanza_logger.error(f"[SCRAPER] 価格パース中に例外発生: {str(e)}")
        result['list_price'] = 0
        result['sale_price'] = None
        result['campaign_text'] = None

    return result
