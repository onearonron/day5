import sys

sys.stdout.reconfigure(encoding="utf-8")

from crawler import fetch_news
from app import get_db_connection, _ph, DATABASE_URL


def seed(limit=10):
    news = fetch_news(limit)
    ph = _ph()
    added = 0
    skipped = 0

    conn = get_db_connection()
    try:
        for n in news:
            exists = conn.execute(
                f"SELECT 1 FROM post WHERE title = {ph}", (n["title"],)
            ).fetchone()
            if exists:
                skipped += 1
                continue

            conn.execute(
                f"INSERT INTO post (title, content, created_at) VALUES ({ph}, {ph}, {ph})",
                (n["title"], n["summary"], n["pub_date"]),
            )
            added += 1

        conn.commit()
        print(f"[seed] {added}건 추가, {skipped}건 중복 건너뜀")
    finally:
        conn.close()


if __name__ == "__main__":
    seed()
