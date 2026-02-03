import json
import time
from pathlib import Path
from typing import Any, Dict, List

import requests

from .models import Decision, EmailItem
from .prompts import build_prompt, build_summary_prompt


def openai_headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def openai_request(api_base: str, api_key: str, method: str, path: str, **kwargs) -> requests.Response:
    url = api_base.rstrip("/") + path
    headers = kwargs.pop("headers", {})
    headers = {**openai_headers(api_key), **headers}
    resp = requests.request(method, url, headers=headers, **kwargs)
    if resp.status_code >= 400:
        raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text}")
    return resp


def upload_batch_file(api_base: str, api_key: str, jsonl_path: Path) -> str:
    with jsonl_path.open("rb") as f:
        files = {"file": (jsonl_path.name, f, "application/jsonl")}
        data = {"purpose": "batch"}
        resp = requests.post(
            api_base.rstrip("/") + "/files",
            headers={"Authorization": f"Bearer {api_key}"},
            files=files,
            data=data,
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"OpenAI file upload failed {resp.status_code}: {resp.text}")
    return resp.json()["id"]


def create_batch(api_base: str, api_key: str, input_file_id: str, endpoint: str, completion_window: str) -> str:
    payload = {
        "input_file_id": input_file_id,
        "endpoint": endpoint,
        "completion_window": completion_window,
    }
    resp = openai_request(api_base, api_key, "POST", "/batches", json=payload)
    return resp.json()["id"]


def get_batch(api_base: str, api_key: str, batch_id: str) -> Dict[str, Any]:
    resp = openai_request(api_base, api_key, "GET", f"/batches/{batch_id}")
    return resp.json()


def download_file(api_base: str, api_key: str, file_id: str) -> str:
    resp = openai_request(api_base, api_key, "GET", f"/files/{file_id}/content")
    return resp.text


def build_batch_jsonl(
    emails: List[EmailItem],
    model: str,
    out_path: Path,
    prompt_override: str = "",
) -> None:
    with out_path.open("w", encoding="utf-8") as f:
        for email in emails:
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You must output only valid JSON."},
                    {"role": "user", "content": build_prompt(email, prompt_override=prompt_override)},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
            }
            line = {
                "custom_id": email.custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": body,
            }
            f.write(json.dumps(line, ensure_ascii=False))
            f.write("\n")


def parse_decision(content: str) -> Decision:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return Decision(action="important", reason="invalid_json", summary="Model output invalid JSON.", reply="")

    action = str(data.get("action", "important")).lower()
    if action not in {"ignore", "auto_reply", "important"}:
        action = "important"
    return Decision(
        action=action,
        reason=str(data.get("reason", "")),
        summary=str(data.get("summary", "")),
        reply=str(data.get("reply", "")),
    )


def parse_batch_output(text: str) -> Dict[str, Decision]:
    results: Dict[str, Decision] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        custom_id = obj.get("custom_id")
        if not custom_id:
            continue
        if "error" in obj:
            results[custom_id] = Decision(
                action="important", reason="batch_error", summary=str(obj.get("error")), reply=""
            )
            continue
        response = obj.get("response", {})
        body = response.get("body", {})
        content = ""
        try:
            content = body["choices"][0]["message"]["content"]
        except Exception:
            content = ""
        results[custom_id] = parse_decision(content)
    return results


def build_summary_batch_jsonl(
    payload: List[Dict[str, Any]],
    model: str,
    out_path: Path,
    prompt_override: str = "",
) -> str:
    custom_id = f"summary-{int(time.time())}"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你擅长写结构化日报。"},
            {"role": "user", "content": build_summary_prompt(payload, prompt_override=prompt_override)},
        ],
        "temperature": 0.2,
    }
    line = {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": body,
    }
    with out_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False))
        f.write("\n")
    return custom_id


def parse_summary_batch_output(text: str, custom_id: str) -> str:
    for line in text.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("custom_id") != custom_id:
            continue
        if "error" in obj and obj["error"]:
            raise RuntimeError(str(obj["error"]))
        body = obj.get("response", {}).get("body", {})
        try:
            return body["choices"][0]["message"]["content"].strip()
        except Exception:
            raise RuntimeError("Invalid summary batch output.")
    raise RuntimeError("Summary batch output not found.")


def submit_summary_batch(
    api_base: str,
    api_key: str,
    model: str,
    payload: List[Dict[str, Any]],
    batch_dir: Path,
    completion_window: str,
    prompt_override: str = "",
) -> Dict[str, str]:
    batch_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = batch_dir / f"summary-input-{int(time.time())}.jsonl"
    custom_id = build_summary_batch_jsonl(payload, model, jsonl_path, prompt_override=prompt_override)
    input_file_id = upload_batch_file(api_base, api_key, jsonl_path)
    batch_id = create_batch(api_base, api_key, input_file_id, "/v1/chat/completions", completion_window)
    return {"batch_id": batch_id, "custom_id": custom_id}
