"""TDCCLoader 大戶持股比例聚合邏輯測試（離線，不連網）。"""

import tdcc_loader
from tdcc_loader import TDCCLoader


def _fake_alldata():
    # 6531 的持股分級占比（級距→占比%）；15=≥1000張，12~15=≥400張
    return {
        "6531": {
            "date": "2026-07-03",
            "levels": {
                "1": 1.5, "11": 10.0,
                "12": 3.0, "13": 4.0, "14": 3.56, "15": 52.97,
            },
        }
    }


def test_ge_level_aggregation(monkeypatch, tmp_path):
    # 導向暫存檔避免污染本機歷史
    monkeypatch.setattr(tdcc_loader, "_HISTORY_FILE", tmp_path / "hist.json")
    ld = TDCCLoader()
    monkeypatch.setattr(ld, "_fetch_all", _fake_alldata)

    r = ld.get_major_holders("6531")
    assert r["has_data"] is True
    assert r["ge1000_ratio"] == 52.97                     # 級距 15
    assert r["ge400_ratio"] == round(3.0 + 4.0 + 3.56 + 52.97, 2)  # 12~15
    assert r["wow_ge1000"] is None                        # 首週無前值
    assert len(r["trend"]) == 1


def test_wow_reads_committed_history(monkeypatch, tmp_path):
    """get_major_holders 唯讀：週增減對照排程已寫入的歷史（不自行寫檔）。"""
    import json
    hist_path = tmp_path / "hist.json"
    # 預先寫入上一週（模擬排程 commit-back 的歷史）
    hist_path.write_text(json.dumps({
        "6531": [{"date": "2026-06-26", "ge400": 60.0, "ge1000": 50.0}]
    }), encoding="utf-8")
    monkeypatch.setattr(tdcc_loader, "_HISTORY_FILE", hist_path)

    ld = TDCCLoader()
    monkeypatch.setattr(ld, "_fetch_all", lambda: {
        "6531": {"date": "2026-07-03", "levels": {"15": 52.97, "12": 10.0}}
    })
    r = ld.get_major_holders("6531")
    assert r["wow_ge1000"] == round(52.97 - 50.0, 2)
    assert len(r["trend"]) == 2
    # 唯讀：歷史檔內容不應被 get_major_holders 改動（仍只有 1 筆）
    after = json.loads(hist_path.read_text(encoding="utf-8"))
    assert len(after["6531"]) == 1


def test_missing_ticker(monkeypatch, tmp_path):
    monkeypatch.setattr(tdcc_loader, "_HISTORY_FILE", tmp_path / "hist.json")
    ld = TDCCLoader()
    monkeypatch.setattr(ld, "_fetch_all", _fake_alldata)
    assert ld.get_major_holders("9999") == {"has_data": False}


def test_bulk_snapshot(monkeypatch, tmp_path):
    hist_path = tmp_path / "hist.json"
    monkeypatch.setattr(tdcc_loader, "_HISTORY_FILE", hist_path)
    ld = TDCCLoader()
    monkeypatch.setattr(ld, "_fetch_all", lambda: {
        "6531": {"date": "2026-07-03", "levels": {"15": 52.97, "12": 3.0}},
        "2330": {"date": "2026-07-03", "levels": {"15": 80.0}},
    })
    # 池含一個不存在的 9999 → 應被略過
    added = ld.bulk_snapshot(["6531", "2330", "9999"])
    assert added == 2
    import json
    hist = json.loads(hist_path.read_text(encoding="utf-8"))
    assert set(hist.keys()) == {"6531", "2330"}
    assert hist["2330"][-1]["ge1000"] == 80.0
    # 同日重跑 → 冪等，不新增
    assert ld.bulk_snapshot(["6531", "2330"]) == 0
