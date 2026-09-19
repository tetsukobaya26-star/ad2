import asyncio
import os
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
import pandas as pd
from playwright.async_api import async_playwright
import gspread
from google.oauth2.service_account import Credentials

KEYWORD = "Tiktok18"
COUNTRY = "JP"

# 日本標準時 (JST = UTC+9) のタイムゾーン定義
JST = timezone(timedelta(hours=9))

def download_image(url, save_path):
    """画像URLからファイルをローカルに保存する関数"""
    if not url or url == "なし" or not url.startswith("http"):
        return "なし"
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        with urllib.request.urlopen(req, timeout=15) as response, open(save_path, 'wb') as out_file:
            out_file.write(response.read())
        print(f"  [画像保存成功]: {save_path}")
        return save_path
    except Exception as e:
        print(f"  [画像保存エラー] ({url[:50]}...): {e}")
        return "保存失敗"

def is_profile_icon(src_url):
    """URLパターンから広告主のプロフィールアイコン（サムネイル）かどうか判定する"""
    if not src_url or not src_url.startswith("http"):
        return True
    
    # Metaのページアイコンや小さなプロフィール画像によく含まれるURLキーワード
    icon_patterns = [
        "p50x50", "p60x60", "p100x100", "p160x160", "p200x200", "p300x300",
        "t39.30808-1", "t39.31096-6", "s100x100", "s160x160", "s300x300",
        "_n.jpg?_nc_cat=", "profile"
    ]
    
    src_lower = src_url.lower()
    for pattern in icon_patterns:
        if pattern in src_lower:
            return True
    return False

def export_to_google_sheets(ads_data):
    """Google スプレッドシートにデータを追加する関数"""
    sa_key_str = os.environ.get('GCP_SA_KEY')
    spreadsheet_id = os.environ.get('SPREADSHEET_ID')

    if not sa_key_str or not spreadsheet_id:
        print("環境変数 GCP_SA_KEY または SPREADSHEET_ID が設定されていないため、スプレッドシート出力をスキップします。")
        return

    try:
        key_data = json.loads(sa_key_str)
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        creds = Credentials.from_service_account_info(key_data, scopes=scopes)
        client = gspread.authorize(creds)

        sheet = client.open_by_key(spreadsheet_id).sheet1

        existing_records = sheet.get_all_values()
        headers = ["Scraped At", "Ad ID", "Page Name", "Ad Text", "Image File", "Image URL", "Link CTA/Text", "Landing Page Link"]
        
        if not existing_records:
            sheet.append_row(headers)

        now_jst_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
        rows_to_append = []
        for item in ads_data:
            rows_to_append.append([
                now_jst_str,
                item.get("Ad ID", ""),
                item.get("Page Name", ""),
                item.get("Ad Text", ""),
                item.get("Image File", ""),
                item.get("Image URL", ""),
                item.get("Link CTA/Text", ""),
                item.get("Landing Page Link", "")
            ])

        sheet.append_rows(rows_to_append)
        print(f"Google スプレッドシートに {len(rows_to_append)} 件のデータを追加しました。")

    except Exception as e:
        print(f"Google スプレッドシートへの書き込み中にエラーが発生しました: {e}")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            viewport={"width": 1280, "height": 900}
        )
        
        page = await context.new_page()
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        exact_keyword = f'"{KEYWORD}"'
        encoded_keyword = urllib.parse.quote(exact_keyword)

        url = f"https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country={COUNTRY}&q={encoded_keyword}&sort_data[direction]=desc&sort_data[mode]=relevance_monthly_grouped&search_type=keyword_exact_phrase&media_type=all"
        print(f"アクセス中 (日本国内・完全一致): {url}")
        
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
        except Exception as e:
            print(f"ページ読み込み進行中: {e}")

        try:
            await page.wait_for_selector('div:has-text("ID:"), div[role="region"]', timeout=30000)
            print("コンテンツの読み込みを確認しました。")
        except Exception:
            print("要素の自動待機タイムアウト。そのまま代替取得とスクロールを試行します。")

        for _ in range(5):
            await page.evaluate("window.scrollBy(0, 1200)")
            await page.wait_for_timeout(2000)

        ad_cards = await page.query_selector_all('div:has-text("ID:")')
        if not ad_cards:
            ad_cards = await page.query_selector_all('div[role="region"]')

        print(f"取得できた広告要素数: {len(ad_cards)}")

        now_jst = datetime.now(JST)
        today_str = now_jst.strftime("%Y-%m-%d")
        
        output_dir = os.path.join("data", today_str)
        img_dir = os.path.join(output_dir, "images")
        os.makedirs(img_dir, exist_ok=True)

        ads_data = []

        for idx, card in enumerate(ad_cards):
            try:
                card_text = await card.inner_text()
                if not card_text.strip() or len(card_text) < 20:
                    continue

                # 1. 広告IDの抽出
                ad_id = f"unknown_{idx}"
                for line in card_text.split('\n'):
                    if "ID:" in line or "ID :" in line:
                        ad_id = line.replace("ID:", "").replace("ID :", "").strip()
                        break

                # 2. 広告主（ページ名）の抽出
                page_name = "不明"
                header_elem = await card.query_selector('a[href*="facebook.com/"], div[role="heading"], span[class*="xt0psk2"]')
                if header_elem:
                    text_val = (await header_elem.inner_text()).strip()
                    if text_val and "ID:" not in text_val and "アクティブ" not in text_val:
                        page_name = text_val.split('\n')[0]

                if page_name == "不明":
                    ignore_keywords = ["アクティブ", "掲載開始日", "ID:", "非アクティブ", "複数の広告", "バージョン", "プラットフォーム", "詳細を見る", "管理者"]
                    lines = [l.strip() for l in card_text.split('\n') if l.strip()]
                    for line in lines:
                        if not any(k in line for k in ignore_keywords) and len(line) < 100:
                            page_name = line
                            break

                # 3. 広告テキスト
                body_elem = await card.query_selector('div[style*="white-space: pre-wrap"]')
                if body_elem:
                    ad_text = (await body_elem.inner_text()).strip()
                else:
                    lines = [l.strip() for l in card_text.split('\n') if l.strip()]
                    filtered_lines = [l for l in lines if page_name not in l and "ID:" not in l and "掲載開始日" not in l and "アクティブ" not in l]
                    ad_text = " / ".join(filtered_lines[:6]) if filtered_lines else card_text[:200]

                # 4. 広告本編のクリエイティブ画像の取得（精密ロジック）
                image_url = "なし"

                # 判定対象となるコンテキスト（カード内、またはカード内のiframe内）
                target_elements = [card]
                iframe_elem = await card.query_selector('iframe')
                if iframe_elem:
                    frame = await iframe_elem.content_frame()
                    if frame:
                        target_elements.append(frame)

                for elem in target_elements:
                    # 優先度A: 動画のposter画像
                    video_elem = await elem.query_selector('video')
                    if video_elem:
                        poster = await video_elem.get_attribute("poster")
                        if poster and poster.startswith("http") and not is_profile_icon(poster):
                            image_url = poster
                            break

                    # 優先度B: クリエイティブ専用領域内のimgタグ
                    # Meta広告ライブラリでは、クリエイティブ画像は特定クラスやalt属性を持つことが多い
                    img_elements = await elem.query_selector_all('img')
                    candidate_imgs = []

                    for img in img_elements:
                        src = await img.get_attribute("src")
                        alt = await img.get_attribute("alt") or ""
                        
                        if not src or not src.startswith("http"):
                            continue

                        # アイコン判定関数で弾く
                        if is_profile_icon(src):
                            continue

                        # altにページ名が含まれている場合はプロフィール画像の可能性が高いのでスキップ
                        if page_name != "不明" and page_name in alt:
                            continue

                        candidate_imgs.append(src)

                    if candidate_imgs:
                        # 候補のうち最も下部（または複数ある場合はクリエイティブ画像）を採用
                        image_url = candidate_imgs[0]
                        break

                # サムネイル画像のダウンロード実行
                local_img_path = "なし"
                if image_url != "なし":
                    img_filename = f"{ad_id}.jpg"
                    save_target = os.path.join(img_dir, img_filename)
                    local_img_path = download_image(image_url, save_target)

                # 5. リンク表示文言 (CTA)
                cta_text = "なし"
                cta_elem = await card.query_selector('div[role="button"], a[role="button"]')
                if cta_elem:
                    cta_text = (await cta_elem.inner_text()).strip()

                # 6. 最終リンク先 (LP)
                link_url = "なし"
                links = await card.query_selector_all('a[href]')
                for link in links:
                    href = await link.get_attribute("href")
                    if href:
                        if "l.facebook.com/l.php" in href:
                            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                            if "u" in parsed:
                                link_url = urllib.parse.unquote(parsed["u"][0])
                                break
                        elif not href.startswith("https://www.facebook.com") and not href.startswith("#") and href.startswith("http"):
                            link_url = href
                            break

                ads_data.append({
                    "Ad ID": ad_id,
                    "Page Name": page_name,
                    "Ad Text": ad_text,
                    "Image File": local_img_path,
                    "Image URL": image_url,
                    "Link CTA/Text": cta_text,
                    "Landing Page Link": link_url
                })

            except Exception as e:
                print(f"カード解析エラー (要素 {idx}): {e}")
                continue

        await browser.close()

        if ads_data:
            time_str = now_jst.strftime("%H%M")
            file_path = os.path.join(output_dir, f"meta_ads_{time_str}.csv")
            
            df = pd.DataFrame(ads_data)
            df.to_csv(file_path, index=False, encoding="utf-8-sig")
            print(f"正常に保存完了 (JST): {file_path} ({len(ads_data)}件)")

            export_to_google_sheets(ads_data)

        else:
            print("該当する日本国内の広告データが取得できませんでした。")

if __name__ == "__main__":
    asyncio.run(main())
