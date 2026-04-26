from datetime import datetime
from pathlib import Path
import os
import sqlite3
import uuid

from flask import Flask, abort, redirect, render_template, request, url_for
from PIL import Image
from werkzeug.utils import secure_filename

import psycopg2
import psycopg2.extras

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = os.getenv("DATABASE_URL")
DB_PATH = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "board.db")))
UPLOAD_DIR = Path(os.getenv("UPLOAD_FOLDER", str(BASE_DIR / "static" / "uploads")))
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_DIMENSION = 1280


def get_db_connection():
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        conn.autocommit = False
        return conn
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ph():
    """Return placeholder: %s for PostgreSQL, ? for SQLite."""
    return "%s" if DATABASE_URL else "?"


def init_db() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ph = _ph()
    with get_db_connection() as conn:
        if DATABASE_URL:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS post (
                    id SERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    image_path TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            cols = {
                row[0]
                for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'post'"
                ).fetchall()
            }
        else:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS post (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    image_path TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(post)").fetchall()
            }
        if "image_path" not in cols:
            conn.execute("ALTER TABLE post ADD COLUMN image_path TEXT")
        conn.commit()


def save_uploaded_image(current_image_path: str | None = None) -> tuple[str | None, str | None]:
    image_file = request.files.get("image")
    if image_file is None or image_file.filename == "":
        return current_image_path, None

    filename = secure_filename(image_file.filename)
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        return current_image_path, "이미지 파일은 png, jpg, jpeg, gif, webp만 업로드할 수 있습니다."

    image_file.stream.seek(0, 2)
    file_size = image_file.stream.tell()
    image_file.stream.seek(0)
    if file_size > MAX_IMAGE_SIZE_BYTES:
        return current_image_path, "이미지 크기는 최대 5MB까지 업로드할 수 있습니다."

    stored_name = f"{uuid.uuid4().hex}.{extension}"
    destination = UPLOAD_DIR / stored_name

    try:
        with Image.open(image_file.stream) as img:
            img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION))

            save_kwargs = {}
            if extension in {"jpg", "jpeg"}:
                save_format = "JPEG"
                if img.mode != "RGB":
                    img = img.convert("RGB")
                save_kwargs = {"optimize": True, "quality": 85}
            elif extension == "png":
                save_format = "PNG"
                save_kwargs = {"optimize": True}
            elif extension == "webp":
                save_format = "WEBP"
                save_kwargs = {"quality": 85}
            elif extension == "gif":
                save_format = "GIF"
            else:
                save_format = img.format or "PNG"

            img.save(destination, format=save_format, **save_kwargs)
    except OSError:
        return current_image_path, "유효한 이미지 파일이 아닙니다."

    return f"uploads/{stored_name}", None


@app.route("/")
def root() -> str:
    return redirect(url_for("post_list"))


PER_PAGE = 10


SORT_OPTIONS = {
    "latest": "id DESC",
    "oldest": "id ASC",
    "title": "title ASC",
}


def _row_to_dict(row) -> dict:
    """Convert a DB row (sqlite3.Row or psycopg2 tuple) to dict."""
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except (TypeError, ValueError):
        return {}


@app.route("/posts")
def post_list() -> str:
    ph = _ph()
    page = request.args.get("page", 1, type=int)
    query = request.args.get("q", "").strip()
    sort = request.args.get("sort", "latest")
    if sort not in SORT_OPTIONS:
        sort = "latest"
    order_by = SORT_OPTIONS[sort]

    with get_db_connection() as conn:
        if query:
            like = f"%{query}%"
            total = conn.execute(
                f"SELECT COUNT(*) FROM post WHERE title LIKE {ph} OR content LIKE {ph}",
                (like, like),
            ).fetchone()[0]
            total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
            page = max(1, min(page, total_pages))
            offset = (page - 1) * PER_PAGE
            rows = conn.execute(
                f"SELECT id, title, content, image_path, created_at FROM post WHERE title LIKE {ph} OR content LIKE {ph} ORDER BY {order_by} LIMIT {ph} OFFSET {ph}",
                (like, like, PER_PAGE, offset),
            ).fetchall()
        else:
            total = conn.execute("SELECT COUNT(*) FROM post").fetchone()[0]
            total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
            page = max(1, min(page, total_pages))
            offset = (page - 1) * PER_PAGE
            rows = conn.execute(
                f"SELECT id, title, content, image_path, created_at FROM post ORDER BY {order_by} LIMIT {ph} OFFSET {ph}",
                (PER_PAGE, offset),
            ).fetchall()
        posts = [_row_to_dict(r) for r in rows]
    return render_template(
        "list.html",
        posts=posts,
        page=page,
        total_pages=total_pages,
        query=query,
        sort=sort,
    )


@app.route("/posts/new", methods=["GET", "POST"])
def post_new() -> str:
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()

        if not title or not content:
            return (
                render_template(
                    "new.html",
                    error="제목과 내용을 입력해주세요.",
                    title=title,
                    content=content,
                    form_action=url_for("post_new"),
                    submit_label="Publish",
                    page_title="글쓰기",
                    image_path=None,
                ),
                400,
            )

        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        image_path, upload_error = save_uploaded_image()
        if upload_error:
            return (
                render_template(
                    "new.html",
                    error=upload_error,
                    title=title,
                    content=content,
                    form_action=url_for("post_new"),
                    submit_label="Publish",
                    page_title="글쓰기",
                    image_path=None,
                ),
                400,
            )

        with get_db_connection() as conn:
            ph = _ph()
            if DATABASE_URL:
                cursor = conn.execute(
                    f"INSERT INTO post (title, content, image_path, created_at) VALUES ({ph}, {ph}, {ph}, {ph}) RETURNING id",
                    (title, content, image_path, created_at),
                )
                post_id = cursor.fetchone()[0]
            else:
                cursor = conn.execute(
                    f"INSERT INTO post (title, content, image_path, created_at) VALUES ({ph}, {ph}, {ph}, {ph})",
                    (title, content, image_path, created_at),
                )
                post_id = cursor.lastrowid
            conn.commit()

        return redirect(url_for("post_detail", post_id=post_id))

    return render_template(
        "new.html",
        error=None,
        title="",
        content="",
        form_action=url_for("post_new"),
        submit_label="Publish",
        page_title="글쓰기",
        image_path=None,
    )


@app.route("/posts/<int:post_id>/edit", methods=["GET", "POST"])
def post_edit(post_id: int) -> str:
    ph = _ph()
    with get_db_connection() as conn:
        row = conn.execute(
            f"SELECT id, title, content, image_path FROM post WHERE id = {ph}",
            (post_id,),
        ).fetchone()
        post = _row_to_dict(row)

    if not post:
        abort(404)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()

        if not title or not content:
            return (
                render_template(
                    "new.html",
                    error="제목과 내용을 입력해주세요.",
                    title=title,
                    content=content,
                    form_action=url_for("post_edit", post_id=post_id),
                    submit_label="Update",
                    page_title="글 수정",
                    image_path=post["image_path"],
                ),
                400,
            )

        image_path, upload_error = save_uploaded_image(post["image_path"])
        if upload_error:
            return (
                render_template(
                    "new.html",
                    error=upload_error,
                    title=title,
                    content=content,
                    form_action=url_for("post_edit", post_id=post_id),
                    submit_label="Update",
                    page_title="글 수정",
                    image_path=post["image_path"],
                ),
                400,
            )

        with get_db_connection() as conn:
            conn.execute(
                f"UPDATE post SET title = {ph}, content = {ph}, image_path = {ph} WHERE id = {ph}",
                (title, content, image_path, post_id),
            )
            conn.commit()

        return redirect(url_for("post_detail", post_id=post_id))

    return render_template(
        "new.html",
        error=None,
        title=post["title"],
        content=post["content"],
        form_action=url_for("post_edit", post_id=post_id),
        submit_label="Update",
        page_title="글 수정",
        image_path=post["image_path"],
    )


@app.route("/posts/<int:post_id>/delete", methods=["POST"])
def post_delete(post_id: int) -> str:
    ph = _ph()
    with get_db_connection() as conn:
        conn.execute(f"DELETE FROM post WHERE id = {ph}", (post_id,))
        conn.commit()

    return redirect(url_for("post_list"))


@app.route("/posts/<int:post_id>")
def post_detail(post_id: int) -> str:
    ph = _ph()
    with get_db_connection() as conn:
        row = conn.execute(
            f"SELECT id, title, content, image_path, created_at FROM post WHERE id = {ph}",
            (post_id,),
        ).fetchone()
        post = _row_to_dict(row)

    if not post:
        abort(404)

    return render_template("detail.html", post=post)


init_db()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )
