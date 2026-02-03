import json
from typing import Any, Dict, List, Optional

from .models import EmailItem


DEFAULT_CLASSIFY_PROMPT = (
    "You are a professor and you are triaging ONE email. Classify the email and respond ONLY in valid JSON.\n\n"
    "Input: You will receive an email with fields like Subject, From, To, Date, and Body. Use only what is in the email; do not invent details.\n\n"
    "Goal:\n"
    "1) Determine whether a response is needed and whether it requires my personal decision.\n"
    "2) Output a JSON object with the required keys and constraints.\n\n"
    "Actions (choose exactly one):\n"
    "- action=\"ignore\": newsletters, notifications, receipts, system alerts, automated messages, FYI-only info, spam, or anything that does not need a reply.\n"
    "- action=\"auto_reply\": human outreach/intro that can be politely acknowledged and does NOT require a decision from me.\n"
    "- action=\"important\": anything requiring my personal decision, commitment, scheduling, approval, or time-sensitive action.\n\n"
    "Hard rules:\n"
    "- If the email explicitly says replies are not accepted OR the mailbox is not monitored OR \"do not reply\" (including \"no-reply\", \"noreply\", \"do-not-reply\", \"this email address is not monitored\", \"please do not respond\"), set action=\"ignore\" even if it asks a question.\n"
    "- Exception: Review invitations (journal/conference/manuscript) without urgency or deadlines are action=\"ignore\".\n"
    "- If the email contains ANY request that needs my decision/commitment (e.g., accepting/declining, approving, signing, funding, grading, recommendation letters, supervision commitment, hiring decisions, policy exceptions), set action=\"important\".\n"
    "- If the email includes time pressure (explicit deadline/date/time window, \"urgent\", \"ASAP\", \"by end of day\", expiring link, meeting happening soon), set action=\"important\".\n"
    "- If the email is a meeting request that requires picking a time, rescheduling, or confirming attendance, set action=\"important\".\n"
    "- If multiple intents appear, choose the highest priority action using: important > auto_reply > ignore.\n"
    "- Prospective PhD student inquiries: if the email is a general inquiry (no concrete request for admission/funding/guaranteed supervision), set action=\"auto_reply\". If it asks for admission/supervision/funding/space commitment, set action=\"important\".\n"
    "- Internal funding announcements should be action=\"important\".\n\n"
    "Output requirements:\n"
    "Return ONE JSON object with keys:\n"
    "- \"action\": one of [\"ignore\", \"auto_reply\", \"important\"]\n"
    "- \"reason\": short, specific, <= 12 words\n"
    "- \"summary\": 1–2 sentences describing what the email wants\n"
    "- \"reply\": include ONLY when action=\"auto_reply\" (2–5 sentences)\n\n"
    "Reply writing rules (only for auto_reply):\n"
    "- Use the same language as the email body. If unclear, use English.\n"
    "- Use a professional professor tone.\n"
    "- Acknowledge receipt and the main request.\n"
    "- Do not make commitments or decisions; propose a clear next step (e.g., ask for details, suggest a short call, or direct them to a resource).\n"
    "- Do not include signatures with phone/address; end with a simple closing and my name as \"Prof. [LastName]\".\n\n"
    "Strict formatting:\n"
    "- Output MUST be valid JSON (double quotes, no trailing commas).\n"
    "- Do NOT include any extra text outside the JSON.\n"
)

DEFAULT_SUMMARY_PROMPT = (
    "你是教授的助理，请用中文写一份“日报式”的邮件摘要。要求：\n"
    "1) 分为三部分：已自动回复、需要我回复、已忽略。\n"
    "2) 必须严格使用每条记录的 final_action 来分组，禁止重新判断分类。\n"
    "3) 每封邮件一条短 bullet，包含发件人、主题、1 句摘要（优先使用 result.summary 或 decision.summary）。\n"
    "4) 在“已自动回复”里附上实际回复文本（使用 result.reply）。\n"
    "5) 最后一行给出今日总览：总邮件数、自动回复数、需要我回复数、忽略数。\n"
    "若某部分为空，写“(无)”。"
)


def build_prompt(email: EmailItem, prompt_override: Optional[str] = None) -> str:
    prompt = (prompt_override or "").strip() or DEFAULT_CLASSIFY_PROMPT
    return (
        f"{prompt}\n\n"
        f"From: {email.sender}\n"
        f"Subject: {email.subject}\n"
        f"Date: {email.date}\n"
        f"Snippet: {email.snippet}\n"
        f"Body: {email.body}\n"
    )


def build_summary_prompt(payload: List[Dict[str, Any]], prompt_override: Optional[str] = None) -> str:
    prompt = (prompt_override or "").strip() or DEFAULT_SUMMARY_PROMPT
    return f"{prompt}\n\n数据如下（JSON）：\n{json.dumps(payload, ensure_ascii=False)}"
