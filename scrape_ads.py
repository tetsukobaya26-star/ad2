import asyncio
import os
import urllib.parse
from datetime import datetime
import pandas as pd
from playwright.async_api import async_playwright

# ---------------------------------------------------------
# 検索条件の設定（日本国内限定）
# ---------------------------------------------------------
KEYWORD = "Tiktok18"  # 完全一致で検索したいキーワード
COUNTRY = "JP"        # 対象国: 日本 (Japan)

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        exact_keyword = f'"{KEYWORD}"'
        encoded_keyword = urllib.parse.quote(exact_keyword)

        url = f"https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country={COUNTRY}&q={encoded_keyword}&sort_data[direction]=desc&sort_data[mode]=relevance_monthly_grouped&search_type=keyword_exact_phrase&media_type=all"
        print(f"アクセス中 (日本国内・完全一致): {url}")
        
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"ページ読み込み警告: {e}")

        await page.wait_for_timeout(6000)

        for _ in range(4):
            await page.evaluate("window.scrollBy(0, 1500)")
            await page.wait_for_timeout(2000)

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

        # CSVへ保存（日ごとフォルダを作成）
        if ads_data:
            # 日付（YYYY-MM-DD）のフォルダパスを作成
            today_str = datetime.now().strftime("%Y-%m-%d")
            output_dir = os.path.join("data", today_str)
            os.makedirs(output_dir, exist_ok=True)

            # フォルダ内に保存するファイルパスを設定
            file_path = os.path.join(output_dir, "meta_ads_scraped.csv")
            
            df = pd.DataFrame(ads_data)
            df.to_csv(file_path, index=False, encoding="utf-8-sig")
            print(f"正常に保存完了: {file_path} ({len(ads_data)}件)")
        else:
            print("該当する日本国内の広告データが取得できませんでした。")

if __name__ == "__main__":
    asyncio.run(main())
    
