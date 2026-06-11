# scripts/archive

這裡存放已完成任務的一次性重構腳本，**不應再次執行**。

| 檔案 | 原始用途 | 風險 |
|------|---------|------|
| `merge_tabs.py` | 合併 Tab 2 候選清單至 Tab 0 expander（已完成） | regex 直接覆寫 app.py，重跑會損壞 |
| `refactor_tab3.py` | 將 Tab 3 拆分為 4 個子 Tab（已完成） | regex 直接覆寫 app.py，重跑會損壞 |

如需類似重構，請手動編輯 app.py 或建立新的獨立腳本（加 DRY_RUN 保護）。
