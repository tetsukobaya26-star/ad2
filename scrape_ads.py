import asyncio
import os
import json
import urllib.parse
from datetime import datetime, timezone, timedelta
import pandas as pd
from playwright.async_api import async_playwright
import gspread
from google.oauth2.service_account import Credentials

KEYWORD = "Tiktok18"
COUNTRY = "JP"

# 日本標準時 (JST = UTC+9) のタイムゾーン定義
JST = timezone(timedelta(hours=9))

def export_to_google_sheets(ads_data):
    """Google スプレッドシートにデータを追加する関数"""
    sa_key_str = os.environ.get('GCP_SA_KEY')
    spreadsheet_id = os.environ.get('SPREADSHEET_ID')

    if not sa_key_str or not spreadsheet_id:
        print("環境変数 GCP_SA_KEY または SPREADSHEET_ID が設定されていないため、スプレッドシート出力をスキップします。")
        return

    try:
        # 認証情報の読み込み
        key_data = json.loads(sa_key_str)
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        creds = Credentials.from_service_account_info(key_data, scopes=scopes)
        client = gspread.authorize(creds)

        # スプレッドシートを開く
        sheet = client.open_by_key(spreadsheet_id).sheet1

        # 1行目が空（ヘッダーがない）場合はヘッダーを追加
        existing_records = sheet.get_all_values()
        if not existing_records:
            headers = ["Scraped At", "Country", "Page Name", "Ad ID / Details", "Image URL", "Landing Page Link", "Full Text"]
            sheet.append_row(headers)

        # 追記用データのフォーマット作成（取得日時の列を追加）
        now_jst_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
        rows_to_append = []
        for item in ads_data:
            rows_to_append.append([
                now_jst_str,
                item.get("Country", ""),
                item.get("Page Name", ""),
                item.get("Ad ID / Details", ""),
                item.get("Image URL", ""),
                item.get("Landing Page Link", ""),
                item.get("Full Text", "")
            ])

        # スプレッドシートへ一括追加
        sheet.append_rows(rows_to_append)
        print(f"Google スプレッドシートに {len(rows_to_append)} 件のデータを追加しました。")

    except Exception as e:
        print(f"Google スプレッドシートへの書き込み中にエラーが発生しました: {e}")

async def main():
    async with async_playwright() as p:
        # ボット検出を回避するための引数を追加
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
        
        # automation検出を回避するスクリプトを注入
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

        # 広告要素または「結果なし」が表示されるまで待機（最大15秒）
        try:
            await page.wait_for_selector('div[role="region"], div[class*="xh8ye4b"]', timeout=15000)
        except Exception:
            print("要素の読み込みタイムアウト。そのままスクロール処理を実行します。")

        # スクロールしてコンテンツをロード
        for _ in range(4):
            await page.evaluate("window.scrollBy(0, 1500)")
            await page.wait_for_timeout(2500)

        # 広告カードの抽出
        ad_cards = await page.query_selector_all('div[class*="xh8ye4b"]')
        if not ad_cards:
            ad_cards = await page.query_selector_all('div:has-text("ID:")')
        if not ad_cards:
            ad_cards = await page.query_selector_all('div[role="region"]')

        print(f"取得できた広告要素数: {len(ad_cards)}")

        ads_data = []

        for card in ad_cards:
            try:
                text_content = await card.inner_text()
                if not text_content.strip():
                    continue

                lines = [line.strip() for line in text_content.split('\n') if line.strip()]
                page_name = lines[0] if len(lines) > 0 else "不明"
                
                ad_id = "不明"
                for line in lines:
                    if "ID:" in line or "ID :" in line:
                        ad_id = line
                        break

                img_element = await card.query_selector('img[src*="fbcdn"], img[src*="scontent"]')
                image_url = await img_element.get_attribute("src") if img_element else "なし"

                link_url = "なし"
                links = await card.query_selector_all('a[href]')
                for link in links:
                    href = await link.get_attribute("href")
                    if href and "l.facebook.com/l.php" in href:
                        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                        if "u" in parsed:
                            link_url = parsed["u"][0]
                            break
                    elif href and not href.startswith("https://www.facebook.com") and not href.startswith("#"):
                        link_url = href
                        break

                if len(lines) >= 2:
                    ads_data.append({
                        "Country": "Japan",
                        "Page Name": page_name,
                        "Ad ID / Details": ad_id,
                        "Image URL": image_url,
                        "Landing Page Link": link_url,
                        "Full Text": " / ".join(lines[:10])
                    })
            except Exception:
                continue

        await browser.close()

        # 1. 日本標準時（JST）で従来通り CSV に保存
        if ads_data:
            now_jst = datetime.now(JST)  # 現在時刻を日本時間で取得
            today_str = now_jst.strftime("%Y-%m-%d")
            time_str = now_jst.strftime("%H%M")
            
            output_dir = os.path.join("data", today_str)
            os.makedirs(output_dir, exist_ok=True)

            file_path = os.path.join(output_dir, f"meta_ads_{time_str}.csv")
            
            df = pd.DataFrame(ads_data)
            df.to_csv(file_path, index=False, encoding="utf-8-sig")
            print(f"正常に保存完了 (JST): {file_path} ({len(ads_data)}件)")

            # 2. Google スプレッドシートへエクスポート
            export_to_google_sheets(ads_data)

        else:
            print("該当する日本国内の広告データが取得できませんでした。")

if __name__ == "__main__":
    asyncio.run(main())
