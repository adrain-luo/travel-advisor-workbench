"""Verify saved manual live evidence through the running local application.

This does not run a native acquisition driver or claim automatic collection.
It preserves a labeled weekly example, blocked jobs, backup and separate restore.
"""
import hashlib
import json
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    with httpx.Client(base_url="http://127.0.0.1:8765", timeout=30) as client:
        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        def post(path, body=None):
            response = client.post(path, json=body or {})
            response.raise_for_status()
            return response.json()

        state = get("/api/state")
        assert not state["settings"]["fixture_mode"]
        selected_materials = [m for m in state["materials"] if m.get("acquisition_method") == "assistant_native_ui_manual"]
        assert len(selected_materials) == 2
        for material in selected_materials:
            assert material["identity_uncertain"]
            for attachment in material["attachments"]:
                response = client.get(f"/api/attachments/{attachment['id']}")
                response.raise_for_status()
                assert hashlib.sha256(response.content).hexdigest() == attachment["sha256"]
                assert attachment["quality"] == "client_saved"
        recommendation = next(r for r in state["recommendations"] if r["text"].startswith("【实机验证示例") and r.get("exports"))
        assert recommendation["status"] == "PREPARED"
        exported_text = client.get(recommendation["text_url"])
        exported_text.raise_for_status()
        assert exported_text.text == recommendation["text"]
        assert "2026年10月25日 21:55" in exported_text.text
        assert "20 元/人" in exported_text.text
        exported_image = client.get(recommendation["image_url"])
        exported_image.raise_for_status()
        assert exported_image.content.startswith(b"\x89PNG")
        evidence_dir = ROOT / "docs" / "evidence"
        (evidence_dir / "comparison-live-example.png").write_bytes(exported_image.content)
        (evidence_dir / "recommendation-live-example.txt").write_bytes(exported_text.content)

        weekly_title = "实机验证示例·本周资料（条件待确认）"
        weekly = next((w for w in state["weekly"] if w["title"] == weekly_title), None)
        if weekly is None:
            weekly = post("/api/weekly", {"title": weekly_title, "product_ids": recommendation["product_ids"], "recommendation_ids": [recommendation["id"]]})
        weekly_export = {"text_url": weekly["text_url"]} if weekly.get("text_url") else post(f"/api/weekly/{weekly['id']}/export")
        weekly_text = client.get(weekly_export["text_url"])
        weekly_text.raise_for_status()
        assert "实机验证示例" in weekly_text.text and "2026年10月25日 21:55" in weekly_text.text
        (evidence_dir / "weekly-live-example.txt").write_bytes(weekly_text.content)

        # The unavailable native adapter must refuse the real selected sources.
        # This is an integration-boundary check, never a successful scan claim.
        source_ids = [m["source_id"] for m in selected_materials]
        missing_jobs = [ident for ident in source_ids if not any(j["source_id"] == ident for j in state["jobs"])]
        if missing_jobs:
            post("/api/scans", {"source_ids": missing_jobs, "mode": "SINCE", "start": "2026-10-24", "timezone": "Asia/Shanghai"})
        for _ in range(40):
            state = get("/api/state")
            jobs = [j for j in state["jobs"] if j["source_id"] in source_ids]
            if all(j["state"] == "NEEDS_USER_ACTION" for j in jobs):
                break
            time.sleep(.1)
        assert len(jobs) == 2
        assert all(j["state"] == "NEEDS_USER_ACTION" and j["coverage"] == "UNKNOWN" and j["counts"]["discovered"] == 0 for j in jobs)
        backup = post("/api/backup")
        restore = post("/api/restore", {"path": backup["path"]})
        assert restore["counts"]["materials"] == 2 and restore["counts"]["products"] == 2
        report = {"phase": "manual_selected_source_followthrough", "overall_status": "PARTIAL",
                  "automatic_collection_passed": False, "live_ai_tested": False,
                  "material_ids": [m["id"] for m in selected_materials],
                  "recommendation_id": recommendation["id"], "preview_matches_export": True,
                  "images_reopened_and_hash_verified": 2, "weekly_id": weekly["id"],
                  "blocked_jobs": [{"id": j["id"], "state": j["state"], "coverage": j["coverage"], "discovered": j["counts"]["discovered"], "reason": j["stop_reason"]} for j in jobs],
                  "backup": backup["path"], "restore": restore,
                  "data_dir": state["settings"]["data_dir"]}
        (evidence_dir / "live-followthrough.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
