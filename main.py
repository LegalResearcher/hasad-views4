import os
import re
import sys
import tempfile
import time

import requests

from account_rotation import select_rotating_account
from browser_sender import BrowserSender

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(ROOT, "state")
os.makedirs(STATE_DIR, exist_ok=True)
LINKS_PATH = os.path.join(STATE_DIR, "telegram_links.txt")
PROCESSED_PATH = os.path.join(STATE_DIR, "processed_links.txt")
TARGET_CHANNEL = "hasadalyoum"
START_AFTER_POST_ID = 26732
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
}


def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def read_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as file:
        return [line.strip() for line in file if line.strip()]


def write_lines(path, lines):
    directory = os.path.dirname(os.path.abspath(path))
    fd, temp_path = tempfile.mkstemp(prefix=".state-", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            for line in lines:
                file.write(line + "\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def post_id(link):
    match = re.fullmatch(rf"https://t\.me/{re.escape(TARGET_CHANNEL)}/(\d+)", link)
    return int(match.group(1)) if match else None


def fetch_links():
    response = requests.get(
        f"https://t.me/s/{TARGET_CHANNEL}", headers=HEADERS, timeout=30
    )
    if response.status_code != 200:
        raise RuntimeError(f"Telegram returned HTTP {response.status_code}")
    ids = sorted({
        int(value) for value in re.findall(
            rf"/{re.escape(TARGET_CHANNEL)}/(\d+)", response.text
        ) if int(value) > START_AFTER_POST_ID
    }, reverse=True)
    return [f"https://t.me/{TARGET_CHANNEL}/{number}" for number in ids]


def pull_once():
    discovered = fetch_links()
    processed = set(read_lines(PROCESSED_PATH))
    current_batch = sorted(
        {
            link for link in discovered
            if post_id(link) is not None
            and post_id(link) > START_AFTER_POST_ID
            and link not in processed
        },
        key=post_id,
        reverse=True,
    )

    if not current_batch:
        # No replay: clear a leftover queue from an interrupted prior run.
        write_lines(LINKS_PATH, [])
        log(f"🔎 لا توجد روابط جديدة بعد المنشور {START_AFTER_POST_ID}.")
        return []

    # The queue represents this run's new batch only; the same links will not
    # be replayed if a later request in the batch fails.
    write_lines(LINKS_PATH, current_batch)
    write_lines(
        PROCESSED_PATH,
        list(dict.fromkeys(read_lines(PROCESSED_PATH) + current_batch)),
    )
    log(
        f"🆕 عُثر على {len(current_batch)} روابط جديدة بعد {START_AFTER_POST_ID}؛ "
        "الترتيب من الأحدث إلى الأقدم."
    )
    return current_batch


def remove_from_queue(links):
    selected = set(links)
    remaining = [link for link in read_lines(LINKS_PATH) if link not in selected]
    write_lines(LINKS_PATH, remaining)


def run_browser_send(sender, links):
    if not links:
        log("💤 لا توجد روابط جديدة للتنفيذ.")
        return 0
    failures = 0
    processed_count = 0
    for link in links:
        log(f"معالجة رابط جديد: {link}")
        processed_count += 1
        try:
            status = sender(link)
        except Exception as error:
            log(f"⚠️ تعذر تنفيذ الرابط ({type(error).__name__}: {error})")
            status = "fail"
        if status == "ok":
            log("✅ نجح الرابط.")
        elif status == "fatal":
            log("⏹️ توقف: تحقق من بيانات الدخول أو الرصيد.")
            failures += 1
            break
        else:
            log("⚠️ لم ينجح الطلب عبر الموقع.")
            failures += 1
    remove_from_queue(links[:processed_count])
    log(f"انتهى التشغيل بعد معالجة {processed_count} روابط جديدة.")
    return 1 if failures else 0


def main():
    try:
        links = pull_once()
    except Exception as error:
        log(f"❌ تعذر سحب الروابط الجديدة ({type(error).__name__}: {error})")
        return 1

    if not links:
        return 0

    try:
        account_number, username, password = select_rotating_account(os.environ, STATE_DIR)
    except (OSError, ValueError) as error:
        log(f"❌ تعذر اختيار الحساب؛ تحقق من الأسرار وحالة account_rotation.json: {error}")
        return 1

    log(
        f"🚀 تشغيل حصاد | القناة: @{TARGET_CHANNEL} | "
        f"الحساب رقم {account_number} من 3 | {len(links)} روابط جديدة"
    )
    with BrowserSender(username, password) as sender:
        return run_browser_send(sender, links)


if __name__ == "__main__":
    sys.exit(main())
