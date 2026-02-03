import json
from typing import Any, Dict, List

from .models import EmailItem


def build_prompt(email: EmailItem) -> str:
    return (
        "You are a professor. Classify the email and respond in JSON.\n"
        "Rules:\n"
        "- action=ignore: newsletters, notifications, no-reply/automated messages, FYI-only info, or anything that does not need a response.\n"
        "- action=auto_reply: outreach/intro emails that can be politely acknowledged (e.g., prospective student inquiry, collaboration intro, general inquiry) and do NOT require a decision from me.\n"
        "- action=important: messages that require my personal decision, commitment, or time-sensitive action.\n"
        "If the email explicitly says the address does not accept replies, set ignore.\n"
        "Return a JSON object with keys: action (ignore|auto_reply|important), "
        "reason (short), summary (1-2 sentences), reply (only if auto_reply, 2-5 sentences).\n\n"
        f"From: {email.sender}\n"
        f"Subject: {email.subject}\n"
        f"Date: {email.date}\n"
        f"Snippet: {email.snippet}\n"
        f"Body: {email.body}\n"
    )


def build_summary_prompt(payload: List[Dict[str, Any]]) -> str:
    return (
        "你是教授的助理，请用中文写一份“日报式”的邮件摘要。要求：\n"
        "1) 分为三部分：已自动回复（需附上回复内容）、需要我回复、已忽略。\n"
        "2) 每封邮件一条短 bullet，包含发件人、主题、1 句摘要。\n"
        "3) 在“已自动回复”里附上实际回复文本。\n"
        "4) 最后一行给出今日总览：总邮件数、自动回复数、需要我回复数、忽略数。\n"
        "若某部分为空，写“(无)”。\n\n"
        "数据如下（JSON）：\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
