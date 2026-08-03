from __future__ import annotations
import json

CLAUDE_MODEL = "claude-opus-4-8"

_INSTRUCTIONS = (
    "あなたはセーリングのコーチング分析AIです。以下の練習の発話ログから、"
    "選手ごとに (1) 練習のサマリ、(2) 受けた指摘(category と text)を抽出し、"
    "次のJSONだけを出力してください: "
    '{"players":[{"name": <話者ラベル>, "summary": <文字列>, '
    '"advice":[{"category": <短い分類>, "text": <指摘内容>}]}]}'
)


def build_prompt(session, speakers, utterances) -> str:
    role = {s.id: (s.role or s.label) for s in speakers}
    lines = []
    for u in utterances:
        who = role.get(u.speaker_id, "?")
        to = role.get(u.target_speaker_id, "") if u.target_speaker_id else ""
        arrow = f"{who}→{to}" if to else who
        lines.append(f"[{u.start_s:.1f}s] {arrow}: {u.text}")
    return _INSTRUCTIONS + "\n\n発話ログ:\n" + "\n".join(lines)


def call_claude(prompt: str, config) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    msg = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=4096, temperature=0.0,
        messages=[{"role": "user", "content": prompt}])
    text = msg.content[0].text
    return json.loads(text)


def run(session_id: int, store, config) -> None:
    job = store.get_job(session_id, "s5")
    if job and job.status == "done":
        return
    try:
        sess = store.get_session(session_id)
        speakers = store.get_speakers(session_id)
        utterances = store.get_utterances(session_id)
        result = call_claude(build_prompt(sess, speakers, utterances), config)
        for p in result.get("players", []):
            name = p.get("name", "unknown")
            store.add_summary(session_id, name,
                              {"summary": p.get("summary", ""), "advice": p.get("advice", [])})
            for a in p.get("advice", []):
                store.add_advice(session_id, name, a.get("category"), a.get("text", ""))
        store.set_job(session_id, "s5", "done")
    except Exception as e:
        store.set_job(session_id, "s5", "error", error=str(e))
        raise
