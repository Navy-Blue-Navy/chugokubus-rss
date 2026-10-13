import os
import re
import time
import hashlib
import xml.etree.ElementTree as ET

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.chugokubus.jp"
SOURCE_URL = "https://www.chugokubus.jp/information"
OUTPUT_FILE = "chugokubus.xml"

JST = timezone(
    timedelta(hours=9)
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

DATE_PATTERN = re.compile(
    r"(20\d{2})\.(\d{1,2})\.(\d{1,2})"
)

ARTICLE_URL_PATTERN = re.compile(
    r"^https://www\.chugokubus\.jp/\d+/?$"
)


def normalize_text(text):
    return re.sub(
        r"\s+",
        " ",
        text or ""
    ).strip()


def fetch_page(url):
    last_error = None

    for attempt in range(1, 4):
        try:
            print(
                f"取得 {attempt}/3:",
                url
            )

            response = requests.get(
                url,
                headers=HEADERS,
                timeout=30
            )

            print(
                "HTTP:",
                response.status_code
            )

            response.raise_for_status()

            if len(response.content) < 5000:
                raise RuntimeError(
                    "HTMLが異常に短いため取得を中止します"
                )

            return response.content

        except Exception as e:
            last_error = e

            print(
                "取得失敗:",
                repr(e)
            )

            if attempt < 3:
                print(
                    "10秒待って再試行します"
                )

                time.sleep(10)

    raise RuntimeError(
        f"3回とも取得に失敗しました: {last_error}"
    )


def parse_date(text):
    match = DATE_PATTERN.search(
        text
    )

    if not match:
        return None

    year = int(
        match.group(1)
    )

    month = int(
        match.group(2)
    )

    day = int(
        match.group(3)
    )

    return datetime(
        year,
        month,
        day,
        0,
        0,
        0,
        tzinfo=JST
    )


def make_guid(link):
    return hashlib.sha256(
        (
            "chugokubus|"
            + link
        ).encode(
            "utf-8"
        )
    ).hexdigest()


def get_last_page(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    pages = [1]

    for a in soup.find_all(
        "a",
        href=True
    ):
        href = urljoin(
            SOURCE_URL,
            a["href"]
        )

        match = re.search(
            r"/information/page/(\d+)/?$",
            href
        )

        if match:
            pages.append(
                int(
                    match.group(1)
                )
            )

    return max(
        pages
    )


def extract_categories(li, title, date_text):
    full_text = normalize_text(
        li.get_text(
            " ",
            strip=True
        )
    )

    if date_text:
        full_text = full_text.replace(
            date_text,
            "",
            1
        ).strip()

    full_text = re.sub(
        r"^NEW\s*",
        "",
        full_text
    ).strip()

    if title and title in full_text:
        prefix = full_text.split(
            title,
            1
        )[0].strip()
    else:
        prefix = ""

    return prefix


def parse_articles(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    items = []
    seen_links = set()

    main = soup.find(
        "main",
        class_="infomation"
    )

    if main is None:
        main = soup

    for li in main.find_all(
        "li"
    ):
        date_div = li.find(
            "div",
            class_="date"
        )

        text_div = li.find(
            "div",
            class_="text"
        )

        if date_div is None:
            continue

        if text_div is None:
            continue

        a = li.find(
            "a",
            href=True
        )

        if a is None:
            continue

        link = urljoin(
            BASE_URL,
            a["href"]
        )

        if not ARTICLE_URL_PATTERN.match(
            link
        ):
            continue

        if link in seen_links:
            continue

        date_text = normalize_text(
            date_div.get_text(
                " ",
                strip=True
            )
        )

        dt = parse_date(
            date_text
        )

        if dt is None:
            continue

        title = normalize_text(
            text_div.get_text(
                " ",
                strip=True
            )
        )

        if not title:
            continue

        categories = extract_categories(
            li,
            title,
            date_text
        )

        description_parts = []

        if categories:
            description_parts.append(
                "分類: " + categories
            )

        description_parts.append(
            "掲載日: "
            + dt.strftime(
                "%Y.%m.%d"
            )
        )

        description = " / ".join(
            description_parts
        )

        items.append(
            {
                "title": title,
                "link": link,
                "guid": make_guid(
                    link
                ),
                "description": description,
                "pubDate": format_datetime(
                    dt
                ),
                "_datetime": dt,
            }
        )

        seen_links.add(
            link
        )

    return items


def load_existing_items():
    items = {}

    if not os.path.exists(
        OUTPUT_FILE
    ):
        print(
            "既存RSS件数: 0"
        )

        return items

    try:
        tree = ET.parse(
            OUTPUT_FILE
        )

        root = tree.getroot()

        for item in root.findall(
            "./channel/item"
        ):
            guid = normalize_text(
                item.findtext(
                    "guid"
                )
            )

            if not guid:
                continue

            pub_date = normalize_text(
                item.findtext(
                    "pubDate"
                )
            )

            try:
                dt = parsedate_to_datetime(
                    pub_date
                )

                if dt.tzinfo is None:
                    dt = dt.replace(
                        tzinfo=JST
                    )

            except Exception:
                dt = datetime.min.replace(
                    tzinfo=timezone.utc
                )

            items[guid] = {
                "title": (
                    item.findtext(
                        "title"
                    )
                    or ""
                ),
                "link": (
                    item.findtext(
                        "link"
                    )
                    or ""
                ),
                "guid": guid,
                "description": (
                    item.findtext(
                        "description"
                    )
                    or ""
                ),
                "pubDate": pub_date,
                "_datetime": dt,
            }

        print(
            "既存RSS件数:",
            len(items)
        )

    except Exception as e:
        print(
            "既存RSS読み込み失敗:",
            repr(e)
        )

    return items


def build_rss(items):
    rss = ET.Element(
        "rss",
        {
            "version": "2.0"
        }
    )

    channel = ET.SubElement(
        rss,
        "channel"
    )

    ET.SubElement(
        channel,
        "title"
    ).text = "中国バス お知らせ"

    ET.SubElement(
        channel,
        "link"
    ).text = SOURCE_URL

    ET.SubElement(
        channel,
        "description"
    ).text = (
        "中国バス公式サイト「お知らせ」の"
        "全カテゴリーを配信する非公式RSS"
    )

    ET.SubElement(
        channel,
        "language"
    ).text = "ja"

    ET.SubElement(
        channel,
        "lastBuildDate"
    ).text = format_datetime(
        datetime.now(
            timezone.utc
        )
    )

    for data in items:
        item = ET.SubElement(
            channel,
            "item"
        )

        ET.SubElement(
            item,
            "title"
        ).text = data[
            "title"
        ]

        ET.SubElement(
            item,
            "link"
        ).text = data[
            "link"
        ]

        guid = ET.SubElement(
            item,
            "guid",
            {
                "isPermaLink": "false"
            }
        )

        guid.text = data[
            "guid"
        ]

        ET.SubElement(
            item,
            "description"
        ).text = data[
            "description"
        ]

        ET.SubElement(
            item,
            "pubDate"
        ).text = data[
            "pubDate"
        ]

    tree = ET.ElementTree(
        rss
    )

    ET.indent(
        tree,
        space="  "
    )

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True
    )


def main():
    print(
        "=" * 70
    )

    print(
        "中国バス お知らせ RSS"
    )

    print(
        "=" * 70
    )

    existing = load_existing_items()

    try:
        first_html = fetch_page(
            SOURCE_URL
        )

        last_page = get_last_page(
            first_html
        )

        print(
            "検出ページ数:",
            last_page
        )

        if last_page < 1:
            raise RuntimeError(
                "ページ数を取得できませんでした"
            )

        if last_page > 100:
            raise RuntimeError(
                "ページ数が異常なため更新を中止します"
            )

        current_items = []
        seen_current = set()

        for page in range(
            1,
            last_page + 1
        ):
            if page == 1:
                html = first_html

            else:
                url = (
                    SOURCE_URL
                    + "/page/"
                    + str(page)
                )

                html = fetch_page(
                    url
                )

            page_items = parse_articles(
                html
            )

            print(
                f"ページ{page}:",
                len(page_items),
                "件"
            )

            for item in page_items:
                guid = item[
                    "guid"
                ]

                if guid in seen_current:
                    continue

                seen_current.add(
                    guid
                )

                current_items.append(
                    item
                )

        print(
            "今回取得記事数:",
            len(current_items)
        )

        if len(current_items) < 20:
            raise RuntimeError(
                "記事取得数が20件未満のため"
                "更新を中止します"
            )

        merged = dict(
            existing
        )

        new_count = 0

        for item in current_items:
            guid = item[
                "guid"
            ]

            if guid not in merged:
                new_count += 1

            merged[
                guid
            ] = item

        items = list(
            merged.values()
        )

        items.sort(
            key=lambda x: (
                x["_datetime"],
                x["link"]
            ),
            reverse=True
        )

        print(
            "今回の新規記事:",
            new_count,
            "件"
        )

        print(
            "RSS保存件数:",
            len(items)
        )

        print()
        print(
            "上位20件"
        )

        for number, item in enumerate(
            items[:20],
            start=1
        ):
            print(
                f"{number:2}. "
                f"{item['pubDate']} | "
                f"{item['title']}"
            )

        build_rss(
            items
        )

        print()
        print(
            "RSS作成成功"
        )

        print(
            "保存先:",
            os.path.abspath(
                OUTPUT_FILE
            )
        )

    except Exception as e:
        print()
        print(
            "エラー:",
            repr(e)
        )

        print(
            "既存RSSは変更しません"
        )

        raise


if __name__ == "__main__":
    main()