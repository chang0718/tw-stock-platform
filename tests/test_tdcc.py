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


def test_wow_after_second_week(monkeypatch, tmp_path):
    monkeypatch.setattr(tdcc_loader, "_HISTORY_FILE", tmp_path / "hist.json")
    ld = TDCCLoader()

    # 第 1 週
    monkeypatch.setattr(ld, "_fetch_all", lambda: {
        "6531": {"date": "2026-06-26", "levels": {"15": 50.0, "12": 10.0}}
    })
    ld.get_major_holders("6531")

    # 第 2 週：大戶增加
    monkeypatch.setattr(ld, "_fetch_all", lambda: {
        "6531": {"date": "2026-07-03", "levels": {"15": 52.97, "12": 10.0}}
    })
    r = ld.get_major_holders("6531")
    assert r["wow_ge1000"] == round(52.97 - 50.0, 2)
    assert len(r["trend"]) == 2


def test_missing_ticker(monkeypatch, tmp_path):
    monkeypatch.setattr(tdcc_loader, "_HISTORY_FILE", tmp_path / "hist.json")
    ld = TDCCLoader()
    monkeypatch.setattr(ld, "_fetch_all", _fake_alldata)
    assert ld.get_major_holders("9999") == {"has_data": False}
