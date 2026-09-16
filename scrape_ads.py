import asyncio
import urllib.parse
import pandas as pd
from playwright.async_api import async_playwright

# 検索条件の設定
KEYWORD = "Tiktok18"  # 完全一致で検索したいキーワード
COUNTRY = "JP"        # 対象国 (JP: 日本)

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="ja-JP",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()

        # 【変更点】キーワードを "" で囲み、URL用にエンコード（例: "Tiktok18" -> %22Tiktok18%22）
        exact_keyword = f'"{KEYWORD}"'
        encoded_keyword = urllib.parse.quote(exact_keyword)

        # Meta広告ライブラリの完全一致検索URL構築
        url = f"https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country={COUNTRY}&q={encoded_keyword}&search_type=keyword_unordered&media_type=all"
        print(f"アクセス中 (完全一致): {url}")
        
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"ページ読み込み警告: {e}")

        await page.wait_for_timeout(5000)

        # スクロールしてコンテンツを追加読み込み
        for _ in range(4):
            await page.evaluate("window.scrollBy(0, 1500)")
            await page.wait_for_timeout(2000)

        # 広告カード要素の取得
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

                if len(lines) >= 2:
                    ads_data.append({
                        "Page Name": page_name,
                        "Ad ID / Details": ad_id,
                        "Full Text": " / ".join(lines[:10])
                    })
            except Exception:
                continue

        await browser.close()

        # CSVへ保存
        if ads_data:
            df = pd.DataFrame(ads_data)
            df.to_csv("meta_ads_scraped.csv", index=False, encoding="utf-8-sig")
            print(f"正常に保存完了: meta_ads_scraped.csv ({len(ads_data)}件)")
        else:
            print("該当する完全一致の広告データが取得できませんでした。")

if __name__ == "__main__":
    asyncio.run(main())
