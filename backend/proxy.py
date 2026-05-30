import re
import urllib.parse
import requests
from fanza_api import parse_cookie_json
from database import db_session
from models import UserSession

def extract_m3u8_url(cookie_json, cid):
    """動画再生ページからm3u8プレイリストURLを抽出する処理"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.dmm.co.jp/dc/-/mylibrary/"
    }
    cookies = parse_cookie_json(cookie_json)
    
    # 1. ブラウザ再生ページの取得
    play_url = f"https://www.dmm.co.jp/dc/doujin/-/play/=/cid={cid}/"
    try:
        res = requests.get(play_url, headers=headers, cookies=cookies, timeout=15)
        if res.status_code != 200:
            return None
        
        # HTML内からプレイヤーのiframeのsrcを検索
        # 通常 play.dmm.co.jp/play/doujin/ 等のURLが含まれる
        iframe_match = re.search(r'iframe[^>]+src="([^"]+)"', res.text)
        iframe_url = iframe_match.group(1) if iframe_match else None
        
        if not iframe_url:
            # HTML内に直接m3u8が存在するかチェック
            m3u8_match = re.search(r'(https?://[^\s"\'`<>]+?\.m3u8[^\s"\'`<>]*)', res.text)
            if m3u8_match:
                return m3u8_match.group(1)
            return None
            
        # iframe_urlが相対パスの場合は補完
        if iframe_url.startswith('//'):
            iframe_url = 'https:' + iframe_url
            
        # 2. プレイヤーページの取得
        res_iframe = requests.get(iframe_url, headers=headers, cookies=cookies, timeout=15)
        if res_iframe.status_code != 200:
            return None
            
        # プレイヤーページのJSからm3u8のURLを抽出
        m3u8_match = re.search(r'(https?://[^\s"\'`<>]+?\.m3u8[^\s"\'`<>]*)', res_iframe.text)
        if m3u8_match:
            # HTMLエスケープのアンエスケープ
            url = m3u8_match.group(1).replace('&amp;', '&').replace('\\/', '/')
            return url
            
    except Exception:
        pass
        
    return None

def rewrite_m3u8(m3u8_content, playlist_url, proxy_endpoint):
    """m3u8ファイル内のURLをFlaskプロキシ経由に書き換える処理"""
    lines = m3u8_content.split('\n')
    new_lines = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # 鍵ファイル等のURIの書き換え
        if 'URI=' in line:
            def repl(match):
                url = match.group(1)
                abs_url = urllib.parse.urljoin(playlist_url, url)
                return f'URI="{proxy_endpoint}?url={urllib.parse.quote(abs_url)}"'
            line = re.sub(r'URI="([^"]+)"', repl, line)
            new_lines.append(line)
        elif line.startswith('#'):
            new_lines.append(line)
        else:
            # セグメント等の配信ファイルURLの書き換え
            abs_url = urllib.parse.urljoin(playlist_url, line)
            new_line = f"{proxy_endpoint}?url={urllib.parse.quote(abs_url)}"
            new_lines.append(new_line)
            
    return '\n'.join(new_lines)

def proxy_media_request(cookie_json, target_url):
    """指定URLに対してCookieを付与し、ストリームで中継する処理"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://play.dmm.co.jp/"
    }
    cookies = parse_cookie_json(cookie_json)
    
    try:
        # ストリーム再生に対応するため stream=True で取得
        response = requests.get(target_url, headers=headers, cookies=cookies, stream=True, timeout=30)
        return response
    except Exception as e:
        return None
