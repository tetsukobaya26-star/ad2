import asyncio
import pandas as pd
from playwright.async_api import async_playwright

# 検索条件の設定
KEYWORD = "Tiktok18"  # 検索したいキーワード
COUNTRY = "JP"            # 対象国 (JP: 日本)

async def main():
    async with async_playwright() as p:
        # headless=False にするとブラウザの動く様子が確認できます（デバッグ時推奨）
        browser = await p.chromium.launch(headless=True)
        
        # 一般的なブラウザのUser-Agentを設定してBOT検知を回避
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="ja-JP"
        )
        page = await context.new_page()

        # Meta広告ライブラリの検索URL構築
        url = f"https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country={COUNTRY}&q={KEYWORD}&search_type=keyword_unordered&media_type=all"
        print(f"アクセス中: {url}")
        
        await page.goto(url, wait_until="networkidle")
        await page.wait_for_timeout(5000)  # 動的コンテンツの読み込み待ち

        # ページを少しスクロールしてより多くの広告カードを読み込む
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 1000)")
            await page.wait_for_timeout(2000)

        # 広告カード要素の取得
        # ※MetaのDOM構造は定期的に変更されるため、属性やタグ名で取得
        ad_cards = await page.query_selector_all('div[class*="xh8ye4b"]')  # 広告カードの共通コンテナ
        
        if not ad_cards:
            # 汎用的なクラス指定フォールバック
            ad_cards = await page.query_selector_all('div:has-text("ID:")')

        print(f"取得できた広告要素数: {len(ad_cards)}")

        ads_data = []

        for card in ad_cards:
            try:
                text_content = await card.inner_text()
                lines = [line.strip() for line in text_content.split('\n') if line.strip()]

                # テキストから簡易的に情報を抽出
                page_name = lines[0] if len(lines) > 0 else "不明"
                
                # 「ID:」が含まれる行から広告IDを抽出
                ad_id = "不明"
                for line in lines:
                    if "ID:" in line or "ID :" in line:
                        ad_id = line
                        break

                ads_data.append({
                    "Page Name": page_name,
                    "Ad ID / Details": ad_id,
                    "Full Text": " / ".join(lines[:10])  # 先頭数行をテキストとして保存
                })
            except Exception as e:
                continue

        await browser.close()

        # CSVへ保存
        if ads_data:
            df = pd.DataFrame(ads_data)
            df.to_csv("meta_ads_scraped.csv", index=False, encoding="utf-8-sig")
            print(f"正常に保存完了: meta_ads_scraped.csv ({len(ads_data)}件)")
        else:
            print("広告データが取得できませんでした。構造が変更されている可能性があります。")

if __name__ == "__main__":
    asyncio.run(main())
