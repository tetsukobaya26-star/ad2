import asyncio
import urllib.parse
import pandas as pd
from playwright.async_api import async_playwright

# ---------------------------------------------------------
# 検索条件の設定
# ---------------------------------------------------------
KEYWORD = "Tiktok18"  # 完全一致で検索したいキーワード
COUNTRY = "JP"        # 対象国 (JP: 日本)

async def main():
    async with async_playwright() as p:
        # ヘッドレスモードで起動
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

        # キーワードをダブルクォーテーションで囲み完全一致URLを作成
        exact_keyword = f'"{KEYWORD}"'
        encoded_keyword = urllib.parse.quote(exact_keyword)

        url = f"https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country={COUNTRY}&q={encoded_keyword}&search_type=keyword_unordered&media_type=all"
        print(f"アクセス中 (完全一致): {url}")
        
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"ページ読み込み警告: {e}")

        await page.wait_for_timeout(5000)

        # 画面をスクロールして追加の広告を読み込み
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
                # 1. テキスト情報の取得
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

                # 2. 広告画像・動画サムネイルURLの取得
                img_element = await card.query_selector('img[src*="fbcdn"], img[src*="scontent"]')
                image_url = await img_element.get_attribute("src") if img_element else "なし"

                # 3. 遷移先URL（LPリンク / CTAボタン）の解析取得
                link_url = "なし"
                links = await card.query_selector_all('a[href]')
                for link in links:
                    href = await link.get_attribute("href")
                    if href and "l.facebook.com/l.php" in href:
                        # リダイレクトURLから本来の遷移先URLをデコード抽出
                        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                        if "u" in parsed:
                            link_url = parsed["u"][0]
                            break
                    elif href and not href.startswith("https://www.facebook.com") and not href.startswith("#"):
                        link_url = href
                        break

                if len(lines) >= 2:
                    ads_data.append({
                        "Page Name": page_name,
                        "Ad ID / Details": ad_id,
                        "Image URL": image_url,
                        "Landing Page Link": link_url,
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
            print("該当する広告データが取得できませんでした。")

if __name__ == "__main__":
    asyncio.run(main())
