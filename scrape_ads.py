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
    if not url or url == "なし":
        return "なし"
    try:
        # User-Agent を設定して拒否を防ぐ
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=10) as response, open(save_path, 'wb') as out_file:
            out_file.write(response.read())
        return save_path
    except Exception as e:
        print(f"画像ダウンロード失敗 ({url}): {e}")
        return "保存失敗"

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
        # カラムを定義（ローカル画像パス列を追加）
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
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            viewport={"width": 1280, "height": 800}
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
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"ページ読み込み警告: {e}")

        try:
            await page.wait_for_selector('div[role="region"], div[class*="xh8ye4b"]', timeout=15000)
        except Exception:
            print("要素の読み込みタイムアウト。そのままスクロール処理を実行します。")

        for _ in range(4):
            await page.evaluate("window.scrollBy(0, 1500)")
            await page.wait_for_timeout(2500)

        # 広告カードの抽出
        ad_cards = await page.query_selector_all('div[class*="xh8ye4b"]')
        if not ad_cards:
            ad_cards = await page.query_selector_all('div[role="region"]')

        print(f"取得できた広告要素数: {len(ad_cards)}")

        now_jst = datetime.now(JST)
        today_str = now_jst.strftime("%Y-%m-%d")
        
        # 保存先フォルダ準備 (data/YYYY-MM-DD/images/)
        output_dir = os.path.join("data", today_str)
        img_dir = os.path.join(output_dir, "images")
        os.makedirs(img_dir, exist_ok=True)

        ads_data = []

        for idx, card in enumerate(ad_cards):
            try:
                card_text = await card.inner_text()
                if not card_text.strip():
                    continue

                # 1. 広告IDの特定
                ad_id = f"unknown_{idx}"
                for line in card_text.split('\n'):
                    if "ID:" in line or "ID :" in line:
                        ad_id = line.replace("ID:", "").replace("ID :", "").strip()
                        break

                # 2. 広告主（ページ名）の取得
                page_name_elem = await card.query_selector('a[href*="facebook.com/"], span[class*="xt0psk2"]')
                if page_name_elem:
                    page_name = (await page_name_elem.inner_text()).strip()
                else:
                    lines = [l.strip() for l in card_text.split('\n') if l.strip()]
                    page_name = lines[0] if lines else "不明"

                # 3. 広告テキスト（メイン文章）
                body_elem = await card.query_selector('div[style*="white-space: pre-wrap"]')
                if body_elem:
                    ad_text = (await body_elem.inner_text()).strip()
                else:
                    lines = [l.strip() for l in card_text.split('\n') if l.strip()]
                    ad_text = " / ".join(lines[2:8]) if len(lines) > 2 else card_text[:100]

                # 4. 画像URL抽出 ＆ サムネイルのダウンロード保存
                img_element = await card.query_selector('img[src*="fbcdn"], img[src*="scontent"]')
                image_url = await img_element.get_attribute("src") if img_element else "なし"
                
                local_img_path = "なし"
                if image_url != "なし":
                    # 画像の保存ファイル名 (例: data/2026-09-19/images/123456789.jpg)
                    img_filename = f"{ad_id}.jpg"
                    save_target = os.path.join(img_dir, img_filename)
                    local_img_path = download_image(image_url, save_target)

                # 5. リンク表示文言（CTAボタン等）
                cta_text = "なし"
                cta_elem = await card.query_selector('div[role="button"], a[role="button"]')
                if cta_elem:
                    cta_text = (await cta_elem.inner_text()).strip()

                # 6. 最終リンク先（LPの実際のURL）
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

            except Exception:
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
