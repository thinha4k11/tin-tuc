#!/usr/bin/env python3
"""
Tổng hợp tin VnExpress + Dân Trí từ RSS -> một trang HTML để đọc cá nhân.
Chỉ dùng thư viện chuẩn của Python, không cần cài thêm gì.

Cách dùng:
    python tong_hop_tin.py            # tải tin, tạo tin_tuc.html và mở trình duyệt
    python tong_hop_tin.py --no-open  # chỉ tạo file, không mở trình duyệt
    python tong_hop_tin.py --watch 20 # tự cập nhật mỗi 20 phút (Ctrl+C để dừng)
"""

import argparse
import html
import json
import re
import sys
import time
import webbrowser
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# DANH SÁCH NGUỒN — thêm / bớt chuyên mục ở đây
# (tên báo, chuyên mục, link RSS)
# ---------------------------------------------------------------------------
FEEDS = [
    ("VnExpress", "Mới nhất",  "https://vnexpress.net/rss/tin-moi-nhat.rss"),
    ("VnExpress", "Thời sự",   "https://vnexpress.net/rss/thoi-su.rss"),
    ("VnExpress", "Thế giới",  "https://vnexpress.net/rss/the-gioi.rss"),
    ("VnExpress", "Kinh doanh","https://vnexpress.net/rss/kinh-doanh.rss"),
    ("VnExpress", "Công nghệ", "https://vnexpress.net/rss/so-hoa.rss"),
    ("VnExpress", "Thể thao",  "https://vnexpress.net/rss/the-thao.rss"),
    ("VnExpress", "Giải trí",  "https://vnexpress.net/rss/giai-tri.rss"),

    ("Dân Trí",   "Mới nhất",  "https://dantri.com.vn/rss/home.rss"),
    ("Dân Trí",   "Thời sự",   "https://dantri.com.vn/rss/thoi-su.rss"),
    ("Dân Trí",   "Thế giới",  "https://dantri.com.vn/rss/the-gioi.rss"),
    ("Dân Trí",   "Kinh doanh","https://dantri.com.vn/rss/kinh-doanh.rss"),
    ("Dân Trí",   "Công nghệ", "https://dantri.com.vn/rss/cong-nghe.rss"),
    ("Dân Trí",   "Thể thao",  "https://dantri.com.vn/rss/the-thao.rss"),
    ("Dân Trí",   "Giải trí",  "https://dantri.com.vn/rss/giai-tri.rss"),
]

OUTPUT = Path(__file__).with_name("tin_tuc.html")
VN_TZ = timezone(timedelta(hours=7))
UA = "Mozilla/5.0 (personal RSS reader)"

IMG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.I)
TAG_RE = re.compile(r"<[^>]+>")


def fetch(url: str, timeout: int = 15) -> bytes:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def clean_text(raw: str) -> str:
    text = TAG_RE.sub(" ", raw or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_date(s: str):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s.strip())
        if d.tzinfo is None:
            d = d.replace(tzinfo=VN_TZ)
        return d
    except Exception:
        return None


def parse_feed(source: str, category: str, data: bytes) -> list[dict]:
    root = ET.fromstring(data)
    items = []
    for it in root.iter("item"):
        title = clean_text(it.findtext("title", ""))
        link = (it.findtext("link", "") or "").strip()
        desc_raw = it.findtext("description", "") or ""
        if not title or not link:
            continue

        img = None
        enc = it.find("enclosure")
        if enc is not None and "image" in (enc.get("type") or "image"):
            img = enc.get("url")
        if not img:
            m = IMG_RE.search(html.unescape(desc_raw))
            if m:
                img = m.group(1)

        d = parse_date(it.findtext("pubDate", ""))
        items.append({
            "source": source,
            "category": category,
            "title": title,
            "link": link,
            "summary": clean_text(desc_raw),
            "image": img,
            "ts": d.timestamp() if d else 0,
        })
    return items


def collect() -> tuple[list[dict], list[str]]:
    errors = []

    def job(feed):
        source, category, url = feed
        try:
            return parse_feed(source, category, fetch(url))
        except Exception as e:
            errors.append(f"{source} / {category}: {e}")
            return []

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(job, FEEDS))

    # Gộp, bỏ trùng theo link (tin "Mới nhất" thường trùng với chuyên mục)
    by_link: dict[str, dict] = {}
    for batch in results:
        for item in batch:
            key = item["link"].split("?")[0]
            old = by_link.get(key)
            if old is None:
                by_link[key] = item
            elif old["category"] == "Mới nhất" and item["category"] != "Mới nhất":
                item["ts"] = max(item["ts"], old["ts"])
                by_link[key] = item

    news = sorted(by_link.values(), key=lambda x: x["ts"], reverse=True)
    return news, errors


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="apple-mobile-web-app-title" content="Tin tổng hợp">
<meta name="theme-color" content="#f6f5f2">
<title>Tin tổng hợp</title>
<style>
  :root {
    --bg: #f6f5f2; --card: #fff; --text: #1d1d1f; --muted: #6b6b70;
    --line: #e4e2dc; --vne: #9f224e; --dt: #0a7d3e; --accent: #1d1d1f;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#141416; --card:#1e1e21; --text:#ececee; --muted:#9a9aa1;
            --line:#2c2c30; --accent:#ececee; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font: 16px/1.5 -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
  header { position:sticky; top:0; z-index:5; background:var(--bg);
           border-bottom:1px solid var(--line); padding:14px 20px 10px; }
  .top { display:flex; align-items:baseline; gap:12px; flex-wrap:wrap; max-width:1200px; margin:0 auto; }
  h1 { font-size:22px; margin:0; letter-spacing:-.01em; }
  .updated { color:var(--muted); font-size:13px; }
  .controls { display:flex; gap:8px; flex-wrap:wrap; max-width:1200px; margin:10px auto 0; align-items:center; }
  .chip { border:1px solid var(--line); background:var(--card); color:var(--text);
          padding:5px 12px; border-radius:999px; font-size:14px; cursor:pointer; }
  .chip.on { background:var(--accent); color:var(--bg); border-color:var(--accent); }
  .sep { width:1px; height:22px; background:var(--line); margin:0 4px; }
  input[type=search] { flex:1; min-width:180px; padding:7px 12px; border-radius:8px;
          border:1px solid var(--line); background:var(--card); color:var(--text); font-size:14px; }
  main { max-width:1200px; margin:0 auto; padding:18px 20px 60px;
         display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:16px; }
  article { background:var(--card); border:1px solid var(--line); border-radius:10px;
            overflow:hidden; display:flex; flex-direction:column; }
  article img { width:100%; aspect-ratio:16/9; object-fit:cover; display:block; background:var(--line); }
  .body { padding:12px 14px 0; flex:1; }
  .meta { font-size:12px; color:var(--muted); margin-bottom:4px; }
  h2 { font-size:17px; line-height:1.35; margin:0 0 6px; }
  h2 a { color:inherit; text-decoration:none; }
  h2 a:hover { text-decoration:underline; }
  p { margin:0 0 12px; color:var(--muted); font-size:14px; }
  a.source { display:block; border-top:1px solid var(--line); padding:7px 14px; font-size:12px;
             color:var(--muted); opacity:.6; text-decoration:none;
             white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  a.source:hover { opacity:1; text-decoration:underline; }
  .empty { grid-column:1/-1; text-align:center; color:var(--muted); padding:40px; }
  .err { max-width:1200px; margin:10px auto 0; color:#b4441b; font-size:13px; }
</style>
</head>
<body>
<header>
  <div class="top">
    <h1>Tin tổng hợp</h1>
    <span class="updated">Cập nhật lúc __UPDATED__ · <span id="count"></span></span>
  </div>
  <div class="controls" id="srcBar"></div>
  <div class="controls" id="catBar"></div>
  <div class="controls"><input type="search" id="q" placeholder="Tìm trong tiêu đề, tóm tắt…"></div>
  __ERRORS__
</header>
<main id="list"></main>

<script>
const NEWS = __DATA__;
const state = { src: "Tất cả", cat: "Tất cả", q: "" };

function chips(el, key, values) {
  el.innerHTML = "";
  ["Tất cả", ...values].forEach(v => {
    const b = document.createElement("button");
    b.className = "chip" + (state[key] === v ? " on" : "");
    b.textContent = v;
    b.onclick = () => { state[key] = v; render(); };
    el.appendChild(b);
  });
}

function fmt(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const diff = (Date.now() - d) / 60000;
  if (diff < 60) return Math.max(1, Math.round(diff)) + " phút trước";
  if (diff < 60 * 24) return Math.round(diff / 60) + " giờ trước";
  return d.toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" });
}

function esc(s) { const d = document.createElement("div"); d.textContent = s ?? ""; return d.innerHTML; }

function render() {
  const sources = [...new Set(NEWS.map(n => n.source))];
  const cats = [...new Set(NEWS.map(n => n.category))].filter(c => c !== "Mới nhất");
  chips(document.getElementById("srcBar"), "src", sources);
  chips(document.getElementById("catBar"), "cat", cats);

  const q = state.q.trim().toLowerCase();
  const list = NEWS.filter(n =>
    (state.src === "Tất cả" || n.source === state.src) &&
    (state.cat === "Tất cả" || n.category === state.cat) &&
    (!q || (n.title + " " + n.summary).toLowerCase().includes(q))
  );

  document.getElementById("count").textContent = list.length + " tin";
  const main = document.getElementById("list");
  if (!list.length) { main.innerHTML = '<div class="empty">Không có tin phù hợp.</div>'; return; }

  main.innerHTML = list.map(n => `
    <article>
      ${n.image ? `<a href="${esc(n.link)}" target="_blank" rel="noopener"><img loading="lazy" referrerpolicy="no-referrer" src="${esc(n.image)}" alt="" onerror="this.closest('a').remove()"></a>` : ""}
      <div class="body">
        <div class="meta">${esc(n.category)} · ${fmt(n.ts)}</div>
        <h2><a href="${esc(n.link)}" target="_blank" rel="noopener">${esc(n.title)}</a></h2>
        ${n.summary ? `<p>${esc(n.summary)}</p>` : ""}
      </div>
      <a class="source" href="${esc(n.link)}" target="_blank" rel="noopener" title="${esc(n.link)}">Nguồn: ${esc(n.source)} — ${esc(n.link.replace(/^https?:\/\//, ""))}</a>
    </article>`).join("");
}

document.getElementById("q").addEventListener("input", e => { state.q = e.target.value; render(); });
render();
</script>
</body>
</html>
"""


def build_html(news: list[dict], errors: list[str]) -> str:
    updated = datetime.now(VN_TZ).strftime("%H:%M %d/%m/%Y")
    err_html = ""
    if errors:
        err_html = '<div class="err">Không tải được: ' + html.escape("; ".join(errors)) + "</div>"
    data = json.dumps(news, ensure_ascii=False).replace("</", "<\\/")
    return (HTML_TEMPLATE
            .replace("__UPDATED__", updated)
            .replace("__ERRORS__", err_html)
            .replace("__DATA__", data))


def run_once(open_browser: bool) -> None:
    news, errors = collect()
    OUTPUT.write_text(build_html(news, errors), encoding="utf-8")
    stamp = datetime.now(VN_TZ).strftime("%H:%M:%S")
    print(f"[{stamp}] {len(news)} tin -> {OUTPUT}")
    for e in errors:
        print("  ! " + e, file=sys.stderr)
    if open_browser:
        webbrowser.open(OUTPUT.resolve().as_uri())


def main() -> None:
    ap = argparse.ArgumentParser(description="Tổng hợp tin VnExpress + Dân Trí")
    ap.add_argument("--no-open", action="store_true", help="không tự mở trình duyệt")
    ap.add_argument("--watch", type=int, metavar="PHÚT", help="tự cập nhật mỗi N phút")
    ap.add_argument("--out", help="đường dẫn file HTML xuất ra (mặc định: tin_tuc.html)")
    args = ap.parse_args()

    global OUTPUT
    if args.out:
        OUTPUT = Path(args.out)
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    run_once(open_browser=not args.no_open)
    if args.watch:
        print(f"Tự cập nhật mỗi {args.watch} phút. Tải lại trang trên trình duyệt (F5) để xem tin mới. Ctrl+C để dừng.")
        try:
            while True:
                time.sleep(args.watch * 60)
                run_once(open_browser=False)
        except KeyboardInterrupt:
            print("Đã dừng.")


if __name__ == "__main__":
    main()
