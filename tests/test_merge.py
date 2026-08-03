from sailog.stages import merge

TURNS = [{"start": 0.0, "end": 1.0, "label": "SPEAKER_00"},
         {"start": 1.0, "end": 2.0, "label": "SPEAKER_01"}]

def test_assign_speaker_by_overlap():
    assert merge.assign_speaker({"start": 0.1, "end": 0.4}, TURNS) == "SPEAKER_00"
    assert merge.assign_speaker({"start": 1.2, "end": 1.5}, TURNS) == "SPEAKER_01"

def test_group_consecutive_same_speaker():
    words = [{"start": 0.0, "end": 0.3, "word": "もっと"},
             {"start": 0.3, "end": 0.6, "word": "引いて"},
             {"start": 1.1, "end": 1.4, "word": "はい"}]
    utts = merge.group_utterances(words, TURNS)
    assert [u["text"] for u in utts] == ["もっと引いて", "はい"]
    assert utts[0]["label"] == "SPEAKER_00" and utts[1]["label"] == "SPEAKER_01"

def test_infer_targets_points_coach_to_next_player():
    utts = [{"start": 0.0, "end": 1.0, "label": "SPEAKER_00", "text": "引いて"},
            {"start": 1.0, "end": 2.0, "label": "SPEAKER_01", "text": "はい"}]
    merge.infer_targets(utts, coach_label="SPEAKER_00")
    assert utts[0]["target"] == "SPEAKER_01"
    assert utts[1]["target"] is None
