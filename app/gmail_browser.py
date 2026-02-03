import re
import time
from typing import Any, Dict, List

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .models import EmailItem
from .utils import redact_sensitive, trim_text
from .browser_common import get_page_by_url


def get_gmail_frame(page):
    for frame in page.frames:
        if "mail.google.com" in frame.url:
            try:
                if frame.query_selector("input[aria-label='Search mail'], input[name='q']"):
                    return frame
            except Exception:
                continue
    return page.main_frame


def wait_for_inbox(frame, timeout_ms: int) -> None:
    frame.wait_for_selector(
        "div[role='button'][aria-label='Compose'], div[role='button'][gh='cm']",
        timeout=timeout_ms,
    )


def dismiss_popups(frame) -> None:
    selectors = [
        "div[role='alert'] button:has-text('Close')",
        "div[role='alert'] >> text=No thanks",
        "div[role='alert'] >> text=OK",
    ]
    for sel in selectors:
        try:
            btn = frame.locator(sel)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click()
                time.sleep(0.5)
        except Exception:
            continue


def search_mail(frame, query: str, timeout_ms: int = 5000, debug: bool = False) -> None:
    search = frame.locator(
        "input[aria-label='Search mail'], input[aria-label='Search in mail'], input[name='q']"
    )
    if search.count() == 0:
        return
    try:
        search.first.click(timeout=timeout_ms)
        search.first.fill(query, timeout=timeout_ms)
        search.first.press("Enter", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        if debug:
            print("Search input action timed out; continuing without search.")
    except Exception:
        if debug:
            print("Search input action failed; continuing without search.")
    time.sleep(2)


def extract_row_meta(row) -> Dict[str, str]:
    def safe_text(locator) -> str:
        try:
            if locator.count() == 0:
                return ""
            return locator.first.inner_text().strip()
        except Exception:
            return ""

    sender = safe_text(row.locator("span.yP, span.zF"))
    subject = safe_text(row.locator("span.bog"))
    snippet = safe_text(row.locator("span.bqe, span.y2"))
    date = safe_text(row.locator("td.xW span"))
    thread_id = row.get_attribute("data-legacy-thread-id") or row.get_attribute("data-thread-id") or ""
    return {
        "sender": sender,
        "subject": subject,
        "snippet": snippet,
        "date": date,
        "thread_id": thread_id,
    }


def extract_open_email(frame, fallback: Dict[str, str], max_body_chars: int) -> EmailItem:
    def first_text(selector: str) -> str:
        loc = frame.locator(selector)
        if loc.count() == 0:
            return ""
        return loc.first.inner_text().strip()

    subject = first_text("h2.hP") or fallback.get("subject", "")
    sender_name = first_text("span.gD") or fallback.get("sender", "")
    sender_email = ""
    try:
        loc = frame.locator("span.gD")
        if loc.count() > 0:
            sender_email = loc.first.get_attribute("email") or ""
    except Exception:
        sender_email = ""
    sender = f"{sender_name} <{sender_email}>".strip()
    if sender == "<>":
        sender = sender_name or fallback.get("sender", "")

    body = ""
    try:
        body_loc = frame.locator("div.a3s")
        if body_loc.count() > 0:
            body = body_loc.first.inner_text().strip()
    except Exception:
        body = ""

    body = trim_text(redact_sensitive(body), max_body_chars)

    thread_id = fallback.get("thread_id", "")
    try:
        url = frame.page.url
        m = re.search(r"#.+/([A-Za-z0-9]+)$", url)
        if m:
            thread_id = thread_id or m.group(1)
    except Exception:
        pass

    custom_id = f"email-{thread_id or int(time.time() * 1000)}"

    return EmailItem(
        custom_id=custom_id,
        thread_id=thread_id,
        sender=sender,
        subject=subject,
        date=fallback.get("date", ""),
        snippet=fallback.get("snippet", ""),
        body=body,
    )


def back_to_inbox(frame) -> None:
    back = frame.locator(
        "div[role='button'][aria-label^='Back to Inbox'], div[role='button'][aria-label^='Back']"
    )
    if back.count() > 0 and back.first.is_visible():
        back.first.click()
        time.sleep(1.5)
        return
    frame.page.go_back()
    time.sleep(1.5)


def collect_unread_emails(
    frame,
    limit: int,
    max_body_chars: int,
    query: str,
    self_email: str,
    summary_subject: str,
    debug: bool = False,
) -> List[EmailItem]:
    frame = get_gmail_frame(frame.page)
    dismiss_popups(frame)
    if debug:
        print("Ensuring Inbox view.")
    try:
        inbox_link = frame.locator("a[title^='Inbox'], a[aria-label^='Inbox'], a[href*='#inbox']")
        if inbox_link.count() > 0:
            inbox_link.first.click(timeout=5000)
            time.sleep(2)
    except Exception:
        if debug:
            print("Inbox click failed; continuing.")

    emails: List[EmailItem] = []
    seen_threads = set()

    def click_first_unread():
        script = """
        () => {
          const rows = Array.from(document.querySelectorAll('tr.zA, div[role="row"]'));
          for (const row of rows) {
            const cls = row.className || '';
            const aria = row.getAttribute('aria-label') || '';
            const hasUnread =
              cls.split(' ').includes('zE') ||
              /unread/i.test(aria) ||
              row.querySelector('span.zF');
            if (!hasUnread) continue;
            const senderEl = row.querySelector('span.yP, span.zF');
            const subjectEl = row.querySelector('span.bog');
            const snippetEl = row.querySelector('span.bqe, span.y2');
            const dateEl = row.querySelector('td.xW span');
            const meta = {
              sender: senderEl ? senderEl.innerText.trim() : '',
              subject: subjectEl ? subjectEl.innerText.trim() : '',
              snippet: snippetEl ? snippetEl.innerText.trim() : '',
              date: dateEl ? dateEl.innerText.trim() : '',
              thread_id: row.getAttribute('data-legacy-thread-id') || row.getAttribute('data-thread-id') || ''
            };
            row.click();
            return meta;
          }
          return null;
        }
        """
        return frame.evaluate(script)

    for _ in range(limit):
        meta = click_first_unread()
        if meta is None:
            time.sleep(2)
            meta = click_first_unread()
        if meta is None:
            break

        try:
            frame.wait_for_selector("h2.hP, div.a3s", timeout=10000)
        except PlaywrightTimeoutError:
            back_to_inbox(frame)
            continue

        email = extract_open_email(frame, meta, max_body_chars)
        if summary_subject and email.subject.strip() == summary_subject.strip():
            back_to_inbox(frame)
            continue
        if self_email and self_email.lower() in email.sender.lower():
            back_to_inbox(frame)
            continue
        if email.thread_id and email.thread_id in seen_threads:
            back_to_inbox(frame)
            continue
        if email.thread_id:
            seen_threads.add(email.thread_id)
        emails.append(email)
        if debug:
            print(f"Collected unread: {email.sender} | {email.subject}")
        back_to_inbox(frame)

    return emails


def ensure_login(page, login_timeout_sec: int, debug: bool = False) -> Any:
    frame = get_gmail_frame(page)
    try:
        wait_for_inbox(frame, timeout_ms=10000)
        return frame
    except PlaywrightTimeoutError:
        pass

    if "accounts.google.com" in page.url:
        print("Gmail not logged in. Please complete login in the opened browser window.")
        wait_for_inbox(frame, timeout_ms=login_timeout_sec * 1000)
        return get_gmail_frame(page)

    if debug:
        print("Gmail UI not ready yet. Waiting up to 30s...")
    wait_for_inbox(frame, timeout_ms=30000)
    return get_gmail_frame(page)


def get_gmail_page(context):
    return get_page_by_url(context, ["mail.google.com"], "https://mail.google.com/")


def open_thread(frame, email: EmailItem, debug: bool = False) -> None:
    if email.thread_id:
        try:
            frame.page.goto(f"https://mail.google.com/mail/u/0/#inbox/{email.thread_id}")
            frame.wait_for_selector("h2.hP, div.a3s", timeout=8000)
            return
        except PlaywrightTimeoutError:
            if debug:
                print("Inbox thread open failed; trying all mail.")
        try:
            frame.page.goto(f"https://mail.google.com/mail/u/0/#all/{email.thread_id}")
            frame.wait_for_selector("h2.hP, div.a3s", timeout=8000)
            return
        except PlaywrightTimeoutError:
            if debug:
                print("All-mail thread open failed; falling back to search.")

    query = f'in:anywhere from:{email.sender} subject:"{email.subject}"'
    search_mail(frame, query, debug=debug)
    rows = frame.locator("tr.zA, div[role='row']")
    if rows.count() == 0:
        return
    rows.first.click()
    frame.wait_for_selector("h2.hP, div.a3s", timeout=10000)


def reply_to_email(frame, reply_text: str, signature: str, dry_run: bool, debug: bool = False) -> bool:
    reply_btn = frame.locator(
        "button[aria-label^='Reply'], "
        "div[role='button'][aria-label^='Reply'], "
        "div[role='button'][data-tooltip^='Reply'], "
        "div[aria-label^='Reply'], "
        "span[role='button'][aria-label^='Reply']"
    )
    if reply_btn.count() == 0:
        if debug:
            print("Reply button not found.")
        return False
    reply_btn.first.click()
    time.sleep(1)
    body = frame.locator("div[role='textbox'][aria-label='Message Body'], div[role='textbox']")
    if body.count() == 0:
        if debug:
            print("Reply textbox not found.")
        return False
    full_reply = reply_text.strip()
    if signature:
        full_reply = f"{full_reply}\n\n{signature.strip()}"
    body.last.fill(full_reply)
    if dry_run:
        if debug:
            print("Dry-run: reply drafted but not sent.")
        return True
    send_btn = frame.locator(
        "button[aria-label^='Send'], "
        "div[role='button'][aria-label^='Send'], "
        "div[role='button'][data-tooltip^='Send'], "
        "div[aria-label^='Send']"
    )
    if send_btn.count() > 0:
        send_btn.last.click()
        time.sleep(1)
        if debug:
            print("Reply sent.")
        return True
    if debug:
        print("Send button not found.")
    return False


def send_summary_email(frame, to_email: str, subject: str, body: str, dry_run: bool) -> None:
    compose = frame.locator(
        "div[role='button'][gh='cm'], div[role='button'][aria-label='Compose'], button[aria-label='Compose']"
    )
    if compose.count() > 0:
        try:
            compose.first.click(timeout=5000)
        except Exception:
            pass
    else:
        try:
            frame.page.keyboard.press("c")
        except Exception:
            pass
    time.sleep(1.5)
    to_box = frame.locator("textarea[name='to'], input[aria-label='To recipients']")
    if to_box.count() > 0:
        try:
            to_box.first.wait_for(state="visible", timeout=8000)
            to_box.first.click()
            to_box.first.fill(to_email)
        except Exception:
            try:
                frame.page.keyboard.press("c")
                time.sleep(1)
                to_box.first.click()
                to_box.first.fill(to_email)
            except Exception:
                return
    subject_box = frame.locator("input[name='subjectbox']")
    if subject_box.count() > 0:
        subject_box.first.fill(subject)
    body_box = frame.locator("div[role='textbox'][aria-label='Message Body']")
    if body_box.count() > 0:
        body_box.last.fill(body)
    if dry_run:
        return
    send_btn = frame.locator("button[aria-label^='Send'], div[role='button'][aria-label^='Send']")
    if send_btn.count() > 0:
        send_btn.last.click()
        time.sleep(1)
