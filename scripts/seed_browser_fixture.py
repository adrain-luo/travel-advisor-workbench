"""Seed only the explicitly isolated browser QA server; never the live dataset."""
import httpx


def main():
    base = "http://127.0.0.1:8766"
    with httpx.Client(base_url=base, timeout=10) as client:
        state = client.get("/api/state").json()
        if not state["settings"].get("fixture_mode"):
            raise SystemExit("Refusing to seed a non-fixture dataset")
        if state["materials"] or state["products"]:
            print("Fixture dataset already contains records; nothing added.")
            return
        material = client.post("/api/paste", json={"text": "测试夹具，非真实供应商报价：云南五日轻松行，上海出发，2026-11-02，成人双人间每人3000元，明确无购物，无必付附加费用，包含大交通。", "supplier": "测试供应商", "source_note": "自动化验证夹具，不能用于真实推荐"}).json()
        response = client.post("/api/products", json={"title": "测试夹具·云南五日轻松行", "supplier": "测试供应商", "destination": "云南", "departure_city": "上海", "duration_days": 5, "shopping": "none", "hotels": "测试舒适型酒店", "itinerary": "测试行程：昆明、大理，包含半日自由活动。", "notes": "夹具用来验证条件和导出，不是实际出行建议。", "source_item_ids": [material["id"]], "offers": [{"price": 3000, "price_kind": "exact", "currency": "CNY", "unit": "per_person", "traveler": "adult", "occupancy": "双人间", "departure_date": "2026-11-02", "extras": [], "transport_included": True}]})
        response.raise_for_status()
        print("Explicitly labeled fixture product and original text created on port 8766 only.")


if __name__ == "__main__":
    main()
