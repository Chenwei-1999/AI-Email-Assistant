import argparse
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from .config import get_env, load_config, now_iso
from .browser_common import create_browser_context
from .models import EmailItem
from .openai_batch import (
    build_batch_jsonl,
    create_batch,
    download_file,
    get_batch,
    parse_batch_output,
    parse_summary_batch_output,
    submit_summary_batch,
    upload_batch_file,
)
from .processing import apply_actions, build_summary_payload
from .utils import completion_window_to_seconds, read_state, write_state


def _send_summary_via_browser(
    get_page_fn,
    ensure_login_fn,
    send_summary_email_fn,
    profile_dir,
    headless,
    cdp_url,
    login_timeout,
    self_email,
    summary_subject,
    summary_text,
    dry_run,
    debug=False,
):
    with sync_playwright() as p:
        browser, context, owns_context = create_browser_context(p, profile_dir, headless, cdp_url)
        page = get_page_fn(context)
        frame = ensure_login_fn(page, login_timeout, debug=debug)
        try:
            send_summary_email_fn(frame, self_email, summary_subject, summary_text, dry_run)
        except Exception:
            if debug:
                print("Summary email failed to send.")
        if owns_context:
            context.close()
        elif browser:
            browser.close()


def _wait_for_summary_batch(
    api_base,
    api_key,
    summary_batch_id,
    summary_custom_id,
    completion_window,
    self_email,
    summary_subject,
    profile_dir,
    headless,
    cdp_url,
    login_timeout,
    dry_run,
    debug,
    state,
    state_path,
    get_page_fn,
    ensure_login_fn,
    send_summary_email_fn,
):
    waited = 0
    while waited < completion_window_to_seconds(completion_window):
        time.sleep(30)
        waited += 30
        batch = get_batch(api_base, api_key, summary_batch_id)
        status = batch.get("status")
        if debug:
            print(f"Wait summary batch status: {status}")
        if status == "completed":
            output_file_id = batch.get("output_file_id")
            if output_file_id and self_email:
                output_text = download_file(api_base, api_key, output_file_id)
                summary_text = parse_summary_batch_output(output_text, summary_custom_id)
                _send_summary_via_browser(
                    get_page_fn,
                    ensure_login_fn,
                    send_summary_email_fn,
                    profile_dir,
                    headless,
                    cdp_url,
                    login_timeout,
                    self_email,
                    summary_subject,
                    summary_text,
                    dry_run,
                    debug,
                )
            state.pop("pending_summary_batch", None)
            write_state(state_path, state)
            return
        if status in {"failed", "cancelled", "expired"}:
            state.pop("pending_summary_batch", None)
            write_state(state_path, state)
            return


def _handle_pending_summary_batch(
    api_base,
    api_key,
    completion_window,
    pending_summary,
    self_email,
    summary_subject,
    profile_dir,
    headless,
    cdp_url,
    login_timeout,
    dry_run,
    debug,
    state,
    state_path,
    wait,
    apply_only,
    get_page_fn,
    ensure_login_fn,
    send_summary_email_fn,
):
    summary_batch_id = pending_summary.get("batch_id")
    summary_custom_id = pending_summary.get("custom_id")
    if not summary_batch_id or not summary_custom_id:
        return
    batch = get_batch(api_base, api_key, summary_batch_id)
    status = batch.get("status")
    if debug:
        print(f"Pending summary batch status: {status}")
    if status == "completed":
        output_file_id = batch.get("output_file_id")
        if output_file_id and self_email:
            output_text = download_file(api_base, api_key, output_file_id)
            summary_text = parse_summary_batch_output(output_text, summary_custom_id)
            _send_summary_via_browser(
                get_page_fn,
                ensure_login_fn,
                send_summary_email_fn,
                profile_dir,
                headless,
                cdp_url,
                login_timeout,
                self_email,
                summary_subject,
                summary_text,
                dry_run,
                debug,
            )
        state.pop("pending_summary_batch", None)
        write_state(state_path, state)
        return
    if status in {"failed", "cancelled", "expired"}:
        state.pop("pending_summary_batch", None)
        write_state(state_path, state)
        return
    if wait:
        _wait_for_summary_batch(
            api_base,
            api_key,
            summary_batch_id,
            summary_custom_id,
            completion_window,
            self_email,
            summary_subject,
            profile_dir,
            headless,
            cdp_url,
            login_timeout,
            dry_run,
            debug,
            state,
            state_path,
            get_page_fn,
            ensure_login_fn,
            send_summary_email_fn,
        )
        return
    if apply_only:
        return
    return


def _submit_summary_batch(
    api_base,
    api_key,
    model,
    payload,
    batch_dir,
    completion_window,
    state,
    state_path,
):
    summary_meta = submit_summary_batch(
        api_base, api_key, model, payload, batch_dir, completion_window
    )
    state["pending_summary_batch"] = {
        "batch_id": summary_meta["batch_id"],
        "custom_id": summary_meta["custom_id"],
        "created_at": now_iso(),
    }
    write_state(state_path, state)
    return summary_meta


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[1] / "config.yaml"))
    parser.add_argument("--login", action="store_true")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--apply-only", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    api_key = get_env("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment.")

    api_base = cfg["openai"]["api_base"]
    model = cfg["openai"]["model"]
    completion_window = cfg["openai"]["completion_window"]

    provider_name = str(cfg.get("provider", "gmail")).lower()
    if provider_name == "outlook":
        from .outlook_browser import (
            collect_unread_emails,
            ensure_login,
            get_outlook_page as get_page,
            send_summary_email,
            open_thread,
            reply_to_email,
            back_to_inbox,
        )
    else:
        from .gmail_browser import (
            collect_unread_emails,
            ensure_login,
            get_gmail_page as get_page,
            send_summary_email,
            open_thread,
            reply_to_email,
            back_to_inbox,
        )

    gmail_cfg = cfg["gmail"]
    profile_dir = Path(gmail_cfg["profile_dir"]).expanduser()
    if not profile_dir.is_absolute():
        profile_dir = (Path(__file__).resolve().parents[1] / profile_dir).resolve()
    headless = bool(gmail_cfg.get("headless", False))
    cdp_url = str(gmail_cfg.get("cdp_url", "") or "").strip()
    login_timeout = int(gmail_cfg.get("login_timeout_sec", 600))
    max_unread = int(gmail_cfg.get("max_unread", 20))
    search_query = gmail_cfg.get("search_query", "is:unread in:inbox")
    self_email = gmail_cfg.get("self_email") or get_env("EMAIL_ADDRESS") or ""
    summary_subject = gmail_cfg.get("summary_subject", "Daily email summary")
    reply_signature = gmail_cfg.get("reply_signature", "")

    max_body_chars = int(cfg["rules"].get("max_body_chars", 4000))

    state_dir = Path(cfg.get("state_dir", ".state"))
    if not state_dir.is_absolute():
        state_dir = (Path(__file__).resolve().parents[1] / state_dir).resolve()
    state_path = state_dir / "state.json"
    state = read_state(state_path)
    batch_dir = state_dir / "batches"

    pending_summary = state.get("pending_summary_batch")
    if pending_summary:
        _handle_pending_summary_batch(
            api_base,
            api_key,
            completion_window,
            pending_summary,
            self_email,
            summary_subject,
            profile_dir,
            headless,
            cdp_url,
            login_timeout,
            args.dry_run,
            args.debug,
            state,
            state_path,
            args.wait,
            args.apply_only,
            get_page,
            ensure_login,
            send_summary_email,
        )
        if args.apply_only:
            return

    pending = state.get("pending_batch")
    if pending:
        batch_id = pending.get("batch_id")
        if batch_id:
            batch = get_batch(api_base, api_key, batch_id)
            status = batch.get("status")
            if args.debug:
                print(f"Pending batch status: {status}")
            if status in {"completed", "failed", "cancelled"}:
                if status == "completed":
                    output_file_id = batch.get("output_file_id")
                    if output_file_id:
                        output_text = download_file(api_base, api_key, output_file_id)
                        decisions = parse_batch_output(output_text)
                        emails = [EmailItem(**item) for item in pending.get("items", [])]
                        with sync_playwright() as p:
                            browser, context, owns_context = create_browser_context(
                                p, profile_dir, headless, cdp_url
                            )
                            page = get_page(context)
                            frame = ensure_login(page, login_timeout, debug=args.debug)
                            results = apply_actions(
                                frame,
                                emails,
                                decisions,
                                reply_signature,
                                args.dry_run,
                                open_thread,
                                reply_to_email,
                                back_to_inbox,
                                debug=args.debug,
                            )
                            if owns_context:
                                context.close()
                            elif browser:
                                browser.close()
                        if self_email:
                            payload = build_summary_payload(emails, decisions, results)
                            _submit_summary_batch(
                                api_base,
                                api_key,
                                model,
                                payload,
                                batch_dir,
                                completion_window,
                                state,
                                state_path,
                            )
                            if args.wait:
                                _handle_pending_summary_batch(
                                    api_base,
                                    api_key,
                                    completion_window,
                                    state.get("pending_summary_batch"),
                                    self_email,
                                    summary_subject,
                                    profile_dir,
                                    headless,
                                    cdp_url,
                                    login_timeout,
                                    args.dry_run,
                                    args.debug,
                                    state,
                                    state_path,
                                    True,
                                    False,
                                    get_page,
                                    ensure_login,
                                    send_summary_email,
                                )
                    state.pop("pending_batch", None)
                    write_state(state_path, state)
                else:
                    state.pop("pending_batch", None)
                    write_state(state_path, state)
            else:
                if args.wait:
                    waited = 0
                    while waited < completion_window_to_seconds(completion_window):
                        time.sleep(30)
                        waited += 30
                        batch = get_batch(api_base, api_key, batch_id)
                        status = batch.get("status")
                        if status == "completed":
                            state["pending_batch"] = pending
                            write_state(state_path, state)
                            return main()
                    return
                if args.apply_only:
                    return

    if args.apply_only:
        return

    if args.debug:
        print("Starting Gmail batch agent.")
    with sync_playwright() as p:
        browser, context, owns_context = create_browser_context(
            p, profile_dir, headless, cdp_url
        )
        page = get_page(context)
        frame = ensure_login(page, login_timeout if args.login else 10, debug=args.debug)
        if args.login:
            print("Login complete.")
        emails = collect_unread_emails(
            frame,
            limit=args.limit or max_unread,
            max_body_chars=max_body_chars,
            query=search_query,
            self_email=self_email,
            summary_subject=summary_subject,
            debug=args.debug,
        )
        if owns_context:
            context.close()
        elif browser:
            browser.close()

    if not emails:
        print("No unread emails found.")
        return

    batch_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = batch_dir / f"batch-input-{int(time.time())}.jsonl"
    build_batch_jsonl(emails, model, jsonl_path)

    input_file_id = upload_batch_file(api_base, api_key, jsonl_path)
    batch_id = create_batch(api_base, api_key, input_file_id, "/v1/chat/completions", completion_window)

    state["pending_batch"] = {
        "batch_id": batch_id,
        "created_at": now_iso(),
        "items": [email.__dict__ for email in emails],
    }
    write_state(state_path, state)
    print(f"Batch submitted: {batch_id}")

    if args.wait:
        waited = 0
        while waited < completion_window_to_seconds(completion_window):
            time.sleep(30)
            waited += 30
            batch = get_batch(api_base, api_key, batch_id)
            status = batch.get("status")
            if args.debug:
                print(f"Wait loop batch status: {status}")
            if status == "completed":
                output_file_id = batch.get("output_file_id")
                if output_file_id:
                    output_text = download_file(api_base, api_key, output_file_id)
                    decisions = parse_batch_output(output_text)
                    with sync_playwright() as p:
                        browser, context, owns_context = create_browser_context(
                            p, profile_dir, headless, cdp_url
                        )
                        page = get_page(context)
                        frame = ensure_login(page, login_timeout, debug=args.debug)
                        results = apply_actions(
                            frame,
                            emails,
                            decisions,
                            reply_signature,
                            args.dry_run,
                            open_thread,
                            reply_to_email,
                            back_to_inbox,
                            debug=args.debug,
                        )
                        if owns_context:
                            context.close()
                        elif browser:
                            browser.close()
                    if self_email:
                        payload = build_summary_payload(emails, decisions, results)
                        _submit_summary_batch(
                            api_base,
                            api_key,
                            model,
                            payload,
                            batch_dir,
                            completion_window,
                            state,
                            state_path,
                        )
                        _handle_pending_summary_batch(
                            api_base,
                            api_key,
                            completion_window,
                            state.get("pending_summary_batch"),
                            self_email,
                            summary_subject,
                            profile_dir,
                            headless,
                            cdp_url,
                            login_timeout,
                            args.dry_run,
                            args.debug,
                            state,
                            state_path,
                            True,
                            False,
                            get_page,
                            ensure_login,
                            send_summary_email,
                        )
                state.pop("pending_batch", None)
                write_state(state_path, state)
                return
            if status in {"failed", "cancelled", "expired"}:
                if args.debug:
                    print("Batch ended without completion.")
                state.pop("pending_batch", None)
                write_state(state_path, state)
                return


if __name__ == "__main__":
    main()
