from __future__ import annotations
import json

CLAUDE_MODEL = "claude-opus-4-8"

_INSTRUCTIONS = (
    "あなたはセーリングのコーチング分析AIです。以下の練習の発話ログから、"
    "選手ごとに (1) 練習のサマリ、(2) 受けた指摘(category と text)を抽出してください。\n\n"
    "【出力ルール】\n"
    "- 有効なJSONのみを出力すること。マークダウンのコードフェンス(``` など)は使わないこと。\n"
    "- 前置き・説明・コメントは一切不要。JSONオブジェクト1つだけ返すこと。\n\n"
    "【出力形式の例】\n"
    '{"players":['
    '{"name":"SPEAKER_01","summary":"スタート直後のタック判断が改善された。風向の読みが正確になってきている。",'
    '"advice":['
    '{"category":"タック","text":"タックのタイミングをもう少し早めると風をより活かせる。"},'
    '{"category":"帆走姿勢","text":"上り角度が浅い場面があった。セールのトリムを見直すこと。"}'
    ']},'
    '{"name":"SPEAKER_02","summary":"コーチからの指摘を素直に取り入れ、後半は安定した走りを見せた。",'
    '"advice":['
    '{"category":"集中力","text":"マーク回航後に一瞬気が緩む傾向がある。意識して継続すること。"}'
    ']}'
    ']}'
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
