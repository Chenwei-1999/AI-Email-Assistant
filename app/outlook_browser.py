import re
import time
from typing import Any, Dict, List

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .browser_common import get_page_by_url
from .models import EmailItem
from .utils import redact_sensitive, trim_text


def get_outlook_page(context):
    return get_page_by_url(
        context,
        ["outlook.office.com", "outlook.live.com"],
        "https://outlook.office.com/mail/",
    )


def get_outlook_frame(page):
    return page.main_frame


def wait_for_inbox(frame, timeout_ms: int) -> None:
    frame.wait_for_selector(
        "button[aria-label='New mail'], button[aria-label='New message']",
        timeout=timeout_ms,
    )


def dismiss_popups(frame) -> None:
    selectors = [
        "button[aria-label='Close']",
        "button[aria-label='Dismiss']",
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
        "input[aria-label='Search'], input[placeholder='Search'], input[placeholder*='Search']"
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


def extract_open_email(frame, fallback: Dict[str, str], max_body_chars: int) -> EmailItem:
    def first_text(selector: str) -> str:
        loc = frame.locator(selector)
        if loc.count() == 0:
            return ""
        return loc.first.inner_text().strip()

    subject = (
        first_text("h1")
        or first_text("div[role='heading']")
        or fallback.get("subject", "")
    )
    sender = fallback.get("sender", "")
    try:
        sender_loc = frame.locator("span[title][data-testid='message-from'], span[title]")
        if sender_loc.count() > 0:
            sender = sender_loc.first.get_attribute("title") or sender_loc.first.inner_text().strip()
    except Exception:
        pass

    body = ""
    try:
        body_loc = frame.locator("div[role='document'], div[aria-label='Message body']")
        if body_loc.count() > 0:
            body = body_loc.first.inner_text().strip()
    except Exception:
        body = ""

    body = trim_text(redact_sensitive(body), max_body_chars)

    thread_id = fallback.get("thread_id", "")
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
    back = frame.locator("button[aria-label='Back'], button[aria-label='Back to Inbox']")
    if back.count() > 0 and back.first.is_visible():
        back.first.click()
        time.sleep(1.0)
        return
    frame.page.go_back()
    time.sleep(1.0)


def collect_unread_emails(
    frame,
    limit: int,
    max_body_chars: int,
    query: str,
    self_email: str,
    summary_subject: str,
    debug: bool = False,
) -> List[EmailItem]:
    frame = get_outlook_frame(frame.page)
    dismiss_popups(frame)

    emails: List[EmailItem] = []
    seen_subjects = set()

    def click_first_unread():
        script = """
        () => {
          const rows = Array.from(document.querySelectorAll('div[role="option"], div[role="row"]'));
          for (const row of rows) {
            const aria = row.getAttribute('aria-label') || '';
            const hasUnread = /unread/i.test(aria) || row.querySelector('[aria-label="Unread"]');
            if (!hasUnread) continue;
            const meta = { sender: '', subject: '', snippet: '', date: '', thread_id: '' };
            if (aria) {
              const parts = aria.split(',').map(s => s.trim());
              if (parts[0] && /unread/i.test(parts[0])) parts.shift();
              meta.sender = parts[0] || '';
              meta.subject = parts[1] || '';
              meta.date = parts[2] || '';
              meta.snippet = parts.slice(3).join(', ');
            }
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
            frame.wait_for_selector("div[role='document'], div[aria-label='Message body'], h1", timeout=10000)
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
        if email.subject and email.subject in seen_subjects:
            back_to_inbox(frame)
            continue
        if email.subject:
            seen_subjects.add(email.subject)
        emails.append(email)
        if debug:
            print(f"Collected unread: {email.sender} | {email.subject}")
        back_to_inbox(frame)

    return emails


def ensure_login(page, login_timeout_sec: int, debug: bool = False) -> Any:
    frame = get_outlook_frame(page)
    try:
        wait_for_inbox(frame, timeout_ms=10000)
        return frame
    except PlaywrightTimeoutError:
        pass

    if "login" in page.url or "microsoftonline" in page.url:
        print("Outlook not logged in. Please complete login in the opened browser window.")
        wait_for_inbox(frame, timeout_ms=login_timeout_sec * 1000)
        return get_outlook_frame(page)

    if debug:
        print("Outlook UI not ready yet. Waiting up to 30s...")
    wait_for_inbox(frame, timeout_ms=30000)
    return get_outlook_frame(page)


def open_thread(frame, email: EmailItem, debug: bool = False) -> None:
    query = f"from:{email.sender} subject:\"{email.subject}\""
    search_mail(frame, query, debug=debug)
    rows = frame.locator("div[role='option'], div[role='row']")
    if rows.count() == 0:
        return
    rows.first.click()
    frame.wait_for_selector("div[role='document'], div[aria-label='Message body'], h1", timeout=10000)


def reply_to_email(frame, reply_text: str, signature: str, dry_run: bool, debug: bool = False) -> bool:
    reply_btn = frame.locator(
        "button[aria-label='Reply'], button[aria-label='Reply all'], div[role='button'][aria-label='Reply']"
    )
    if reply_btn.count() == 0:
        if debug:
            print("Reply button not found.")
        return False
    reply_btn.first.click()
    time.sleep(1)
    body = frame.locator("div[role='textbox'][aria-label='Message body'], div[role='textbox']")
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
    send_btn = frame.locator("button[aria-label='Send'], div[role='button'][aria-label='Send']")
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
    compose = frame.locator("button[aria-label='New mail'], button[aria-label='New message']")
    if compose.count() > 0:
        try:
            compose.first.click(timeout=5000)
        except Exception:
            pass
    else:
        try:
            frame.page.keyboard.press("n")
        except Exception:
            pass
    time.sleep(1.5)
    to_box = frame.locator("input[aria-label='To'], input[aria-label='To recipients']")
    if to_box.count() > 0:
        to_box.first.click()
        to_box.first.fill(to_email)
    subject_box = frame.locator("input[aria-label='Add a subject'], input[aria-label='Subject']")
    if subject_box.count() > 0:
        subject_box.first.fill(subject)
    body_box = frame.locator("div[role='textbox'][aria-label='Message body'], div[role='textbox']")
    if body_box.count() > 0:
        body_box.last.fill(body)
    if dry_run:
        return
    send_btn = frame.locator("button[aria-label='Send'], div[role='button'][aria-label='Send']")
    if send_btn.count() > 0:
        send_btn.last.click()
        time.sleep(1)
