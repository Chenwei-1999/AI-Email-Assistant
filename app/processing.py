from typing import Dict, List

from .models import Decision, EmailItem
def apply_actions(
    frame,
    emails: List[EmailItem],
    decisions: Dict[str, Decision],
    signature: str,
    dry_run: bool,
    open_thread_fn,
    reply_fn,
    back_fn,
    debug: bool = False,
) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    seen_threads = set()
    for email in emails:
        if email.thread_id and email.thread_id in seen_threads:
            continue
        if email.thread_id:
            seen_threads.add(email.thread_id)
        decision = decisions.get(email.custom_id)
        if not decision:
            results.append(
                {
                    "custom_id": email.custom_id,
                    "sender": email.sender,
                    "subject": email.subject,
                    "action": "important",
                    "status": "missing decision",
                    "summary": "",
                    "reply": "",
                }
            )
            continue
        if decision.action == "auto_reply":
            if not decision.reply:
                results.append(
                    {
                        "custom_id": email.custom_id,
                        "sender": email.sender,
                        "subject": email.subject,
                        "action": "important",
                        "status": "missing reply text",
                        "summary": decision.summary,
                        "reply": "",
                    }
                )
                continue
            open_thread_fn(frame, email, debug=debug)
            sent = reply_fn(frame, decision.reply, signature, dry_run, debug=debug)
            results.append(
                {
                    "custom_id": email.custom_id,
                    "sender": email.sender,
                    "subject": email.subject,
                    "action": "auto_reply",
                    "status": "sent" if sent else "failed",
                    "summary": decision.summary,
                    "reply": decision.reply,
                }
            )
            back_fn(frame)
        elif decision.action == "important":
            results.append(
                {
                    "custom_id": email.custom_id,
                    "sender": email.sender,
                    "subject": email.subject,
                    "action": "important",
                    "status": "needs reply",
                    "summary": decision.summary,
                    "reply": "",
                }
            )
        else:
            results.append(
                {
                    "custom_id": email.custom_id,
                    "sender": email.sender,
                    "subject": email.subject,
                    "action": "ignore",
                    "status": "ignored",
                    "summary": decision.summary,
                    "reply": "",
                }
            )
    return results


def format_summary(results: List[Dict[str, str]]) -> str:
    lines = []
    lines.append("Summary")
    lines.append("")
    auto = [r for r in results if r["action"] == "auto_reply"]
    important = [r for r in results if r["action"] == "important"]
    ignored = [r for r in results if r["action"] == "ignore"]

    lines.append("Auto-replied:")
    if auto:
        for r in auto:
            lines.append(f"{r['sender']} | {r['subject']} | {r['status']}")
            if r.get("summary"):
                lines.append(f"Summary: {r['summary']}")
            if r.get("reply"):
                lines.append("Reply:")
                lines.append(r["reply"])
            lines.append("")
    else:
        lines.append("(none)")
        lines.append("")

    lines.append("Important (needs your reply):")
    if important:
        for r in important:
            lines.append(f"{r['sender']} | {r['subject']} | {r['status']}")
            if r.get("summary"):
                lines.append(f"Summary: {r['summary']}")
            lines.append("")
    else:
        lines.append("(none)")
        lines.append("")

    lines.append("Ignored:")
    if ignored:
        for r in ignored:
            lines.append(f"{r['sender']} | {r['subject']} | {r['status']}")
            if r.get("summary"):
                lines.append(f"Summary: {r['summary']}")
            lines.append("")
    else:
        lines.append("(none)")
    return "\n".join(lines)


def build_summary_payload(
    emails: List[EmailItem],
    decisions: Dict[str, Decision],
    results: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    by_custom = {r.get("custom_id", ""): r for r in results}
    payload = []
    for email in emails:
        decision = decisions.get(email.custom_id)
        result = by_custom.get(email.custom_id, {})
        final_action = result.get("action") or (decision.action if decision else "important")
        payload.append(
            {
                "sender": email.sender,
                "subject": email.subject,
                "date": email.date,
                "body": email.body,
                "decision": decision.__dict__ if decision else {},
                "result": result,
                "final_action": final_action,
            }
        )
    return payload
