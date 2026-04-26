import sys
import io
import requests
from bs4 import BeautifulSoup
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

RSS_URL = "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"


def fetch_news(limit=10):
    resp = requests.get(RSS_URL, timeout=10)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.content, "xml")
    items = soup.find_all("item")[:limit]

    news = []
    for item in items:
        title = item.title.text if item.title else ""
        link = item.link.text if item.link else ""
        pub_date = item.pubDate.text if item.pubDate else ""
        summary_raw = item.description.text if item.description else ""

        summary = BeautifulSoup(summary_raw, "html.parser").get_text(strip=True)

        try:
            dt = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S GMT")
            pub_date = dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            pass

        news.append({
            "title": title,
            "summary": summary[:120] + ("..." if len(summary) > 120 else ""),
            "link": link,
            "pub_date": pub_date,
        })

    return news


def display(news_list):
    print(f"{'='*60}")
    print(f"  Google News 한국어 RSS  |  {datetime.now():%Y-%m-%d %H:%M}")
    print(f"{'='*60}")

    for i, n in enumerate(news_list, 1):
        print(f"\n[{i:>2}] {n['title']}")
        print(f"     {n['summary']}")
        print(f"     {n['link']}")
        print(f"     {n['pub_date']}")

    print(f"\n{'='*60}")
    print(f"  총 {len(news_list)}건\n")


if __name__ == "__main__":
    display(fetch_news())
