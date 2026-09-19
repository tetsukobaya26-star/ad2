import asyncio
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
import pandas as pd
from playwright.async_api import async_playwright

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
        time_str = now_jst.strftime("%H%M")
        
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

                # 4. 広告本編のクリエイティブ画像の取得
                image_url = "なし"

                target_elements = [card]
                iframe_elem = await card.query_selector('iframe')
                if iframe_elem:
                    frame = await iframe_elem.content_frame()
                    if frame:
                        target_elements.append(frame)

                for elem in target_elements:
                    video_elem = await elem.query_selector('video')
                    if video_elem:
                        poster = await video_elem.get_attribute("poster")
                        if poster and poster.startswith("http") and not is_profile_icon(poster):
                            image_url = poster
                            break

                    img_elements = await elem.query_selector_all('img')
                    candidate_imgs = []

                    for img in img_elements:
                        src = await img.get_attribute("src")
                        alt = await img.get_attribute("alt") or ""
                        
                        if not src or not src.startswith("http"):
                            continue

                        if is_profile_icon(src):
                            continue

                        if page_name != "不明" and page_name in alt:
                            continue

                        candidate_imgs.append(src)

                    if candidate_imgs:
                        image_url = candidate_imgs[0]
                        break

                # 画像のダウンロード
                local_img_path = "なし"
                if image_url != "なし":
                    img_filename = f"{ad_id}_{time_str}.jpg"
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
            file_path = os.path.join(output_dir, f"meta_ads_{time_str}.csv")
            
            df = pd.DataFrame(ads_data)
            df.to_csv(file_path, index=False, encoding="utf-8-sig")
            print(f"正常に保存完了 (JST): {file_path} ({len(ads_data)}件)")

        else:
            print("該当する日本国内の広告データが取得できませんでした。")

if __name__ == "__main__":
    asyncio.run(main())
