# -*- coding: utf-8 -*-
"""
UEFA 2026/2027 Telegram Bot Runner (GitHub Actions)
Hỗ trợ 2 chế độ:
  1. BOT_MODE=command   : Nhận lệnh 2 chiều (/match, /ucl, /uel, /help) từ Cloudflare Worker.
  2. BOT_MODE=auto_scan : Quét tự động đêm Cúp châu Âu (đúng 2 lệnh gọi Scoreboard UCL+UEL),
                          chống spam & chống 429 (KHÔNG gọi Gemini AI hàng loạt).
Zero hardcoded secrets.
"""

from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_and_export import (
    format_full_telegram_report,
    format_t75_auto_alert_telegram,
    format_t90_digest_telegram,
    send_telegram_message,
    summarize_uefa_rss_with_ai,
)
from data_engine import (
    VN_TZ,
    analyze_match,
    find_team_next_match,
    get_fast_t75_snapshot,
    get_league_standings,
    get_scoreboard_for_auto_scan,
    normalize_text,
    resolve_team_alias,
)

STATE_FILE = Path("uefa_sent_state.json")


def _load_state() -> dict[str, dict[str, float]]:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {
                    "t90_sent": dict(data.get("t90_sent", {})),
                    "t75_sent": dict(data.get("t75_sent", {})),
                }
        except Exception:
            pass
    return {"t90_sent": {}, "t75_sent": {}}


def _save_state(state: dict[str, dict[str, float]]) -> None:
    now_ts = datetime.now(timezone.utc).timestamp()
    cutoff = now_ts - 36 * 3600  # Chỉ giữ lịch sử chống trùng 36 giờ gần nhất
    cleaned = {
        "t90_sent": {k: v for k, v in state.get("t90_sent", {}).items() if v >= cutoff},
        "t75_sent": {k: v for k, v in state.get("t75_sent", {}).items() if v >= cutoff},
    }
    STATE_FILE.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")


def _matches_watchlist(fixture: dict[str, Any], watchlist_raw: str) -> bool:
    if not watchlist_raw.strip():
        return True
    tokens = [resolve_team_alias(t) for t in watchlist_raw.split(",") if t.strip()]
    if not tokens:
        return True
    hn = normalize_text(fixture["home_name"])
    an = normalize_text(fixture["away_name"])
    for tok in tokens:
        if tok and (tok in hn or tok in an):
            return True
    return False


# ==============================================================================
# CHẾ ĐỘ 1: XỬ LÝ LỆNH 2 CHIỀU TỪ TELEGRAM (/match, /ucl, /uel)
# ==============================================================================
def run_command_mode() -> None:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    default_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()

    chat_id = os.environ.get("CMD_CHAT_ID", "").strip() or default_chat
    raw_cmd = os.environ.get("CMD_TEXT", "").strip()

    if not bot_token or not chat_id:
        print("Thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID.")
        sys.exit(1)

    cleaned = re.sub(r"\s+", " ", raw_cmd).strip()
    low = cleaned.lower()

    if not cleaned or low.startswith("/start") or low.startswith("/help"):
        help_msg = (
            "🏆 <b>BOT PHÂN TÍCH CÚP CHÂU ÂU UEFA 2026/2027 (UCL &amp; UEL)</b>\n\n"
            "📌 <b>Các lệnh hỗ trợ 24/7:</b>\n"
            "• <code>/match Real</code> — Tự nhận diện UCL/UEL và trả báo cáo đầy đủ + T-75 + AI báo chí\n"
            "• <code>/ucl Arsenal</code> — Tìm nhanh trận tại Champions League\n"
            "• <code>/uel MU</code> — Tìm nhanh trận tại Europa League\n\n"
            "💡 Hỗ trợ biệt danh quen thuộc: Real, Barca, Inter, Bayern, MU, MC, Arsenal, "
            "Sporting, Ajax, Fenerbahce, Gala, Roma, BVB, PSG..."
        )
        send_telegram_message(bot_token, chat_id, help_msg)
        return

    # Tách lệnh (/match, /ucl, /uel — hỗ trợ cả dạng /match@TenBot)
    preferred_league: str | None = None
    m_cmd = re.match(r"^/(match|ucl|uel)(?:@[a-zA-Z0-9_]+)?\s*(.*)$", cleaned, flags=re.IGNORECASE)
    if m_cmd:
        cmd_name = m_cmd.group(1).lower()
        query_team = m_cmd.group(2).strip()
        if cmd_name == "ucl":
            preferred_league = "UCL"
        elif cmd_name == "uel":
            preferred_league = "UEL"
    else:
        query_team = cleaned

    if not query_team:
        send_telegram_message(
            bot_token,
            chat_id,
            "⚠️ Bạn chưa nhập tên đội bóng. Ví dụ: <code>/match Real</code> hoặc <code>/uel Roma</code>.",
        )
        return

    fixture = find_team_next_match(query_team, preferred_league=preferred_league)
    if not fixture:
        send_telegram_message(
            bot_token,
            chat_id,
            f"❌ Chưa tìm thấy trận đấu nào gần đây của <b>{query_team}</b> tại UCL/UEL 2026/27.\n"
            "Hãy thử nhập tên tiếng Anh ngắn gọn (VD: <code>/match Bayern</code>, <code>/match Sporting</code>).",
        )
        return

    report = analyze_match(fixture, include_rss=True)
    ai_summary = summarize_uefa_rss_with_ai(fixture, report["rss_articles"], gemini_key)
    msg_html = format_full_telegram_report(report, ai_summary)
    ok, info = send_telegram_message(bot_token, chat_id, msg_html)
    print(f"[COMMAND] {fixture['home_name']} vs {fixture['away_name']} -> {ok} | {info}")


# ==============================================================================
# CHẾ ĐỘ 2: QUÉT TỰ ĐỘNG ĐÊM CÚP CHÂU ÂU (CHỐNG BÃO TIN NHẮN & CHỐNG 429)
# ==============================================================================
def run_auto_scan_mode() -> None:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    watchlist_raw = os.environ.get("WATCHLIST_TEAMS", "").strip()

    if not bot_token or not chat_id:
        print("Thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID.")
        sys.exit(1)

    state = _load_state()
    now_vn = datetime.now(VN_TZ)
    now_ts = datetime.now(timezone.utc).timestamp()

    # Đúng 2 lượt gọi Scoreboard: uefa.champions và uefa.europa
    all_fixtures: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_ucl = pool.submit(get_scoreboard_for_auto_scan, "UCL")
        f_uel = pool.submit(get_scoreboard_for_auto_scan, "UEL")
        try:
            all_fixtures.extend(f_ucl.result(timeout=10))
        except Exception as exc:
            print(f"[AUTO_SCAN] Lỗi tải UCL scoreboard: {exc}")
        try:
            all_fixtures.extend(f_uel.result(timeout=10))
        except Exception as exc:
            print(f"[AUTO_SCAN] Lỗi tải UEL scoreboard: {exc}")

    print(f"[AUTO_SCAN] Tổng số trận trong khung quét: {len(all_fixtures)}")

    t90_candidates: list[dict[str, Any]] = []
    t75_candidates: list[dict[str, Any]] = []

    for fx in all_fixtures:
        if fx["status_state"] != "pre":
            continue
        dt_vn = fx.get("kickoff_dt_vn")
        if not dt_vn:
            continue

        mins_to_ko = (dt_vn - now_vn).total_seconds() / 60.0
        ev_id = fx["event_id"]

        # (1) Mốc trước giờ đá ~90 phút (76 đến 105 phút) -> gom 1 tin tổng hợp duy nhất
        if 76 <= mins_to_ko <= 105 and ev_id not in state["t90_sent"]:
            t90_candidates.append(fx)

        # (2) Mốc T-70 đến T-30 (25 đến 72 phút) -> kiểm tra đội hình T-75 chính thức
        if 25 <= mins_to_ko <= 72 and ev_id not in state["t75_sent"]:
            if _matches_watchlist(fx, watchlist_raw):
                t75_candidates.append(fx)

    # Gửi 1 tin nhắn tổng hợp mốc T-90
    if t90_candidates:
        t90_candidates.sort(key=lambda x: x["date_utc"] or "")
        first_time = t90_candidates[0]["kickoff_dt_vn"].strftime("%H:%M %d/%m")
        digest_msg = format_t90_digest_telegram(t90_candidates, f"Khung {first_time} GMT+7")
        ok, info = send_telegram_message(bot_token, chat_id, digest_msg)
        print(f"[T-90 DIGEST] {len(t90_candidates)} trận -> {ok} | {info}")
        if ok:
            for fx in t90_candidates:
                state["t90_sent"][fx["event_id"]] = now_ts

    # Gửi đội hình chính thức T-75 (KHÔNG gọi Gemini AI để tránh lỗi 429)
    if t75_candidates:
        needed_leagues = {fx["league_code"] for fx in t75_candidates}
        standings_cache: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_map = {pool.submit(get_league_standings, lg): lg for lg in needed_leagues}
            for fut in as_completed(f_map, timeout=10):
                lg = f_map[fut]
                try:
                    standings_cache[lg] = fut.result()
                except Exception:
                    standings_cache[lg] = {"table": []}

        snapshots: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            futs = [pool.submit(get_fast_t75_snapshot, fx, standings_cache) for fx in t75_candidates]
            try:
                for fut in as_completed(futs, timeout=20):
                    try:
                        snap = fut.result()
                        if snap and snap.get("has_confirmed_lineups"):
                            snapshots.append(snap)
                    except Exception:
                        pass
            except Exception:
                pass

        snapshots.sort(key=lambda s: s["fixture"]["date_utc"] or "")
        print(f"[T-75 CHECK] Ứng viên: {len(t75_candidates)} | Đã có đội hình chính thức: {len(snapshots)}")

        for snap in snapshots:
            ev_id = snap["fixture"]["event_id"]
            alert_msg = format_t75_auto_alert_telegram(snap)
            ok, info = send_telegram_message(bot_token, chat_id, alert_msg)
            print(f"[T-75 ALERT] {snap['fixture']['home_name']} vs {snap['fixture']['away_name']} -> {ok} | {info}")
            if ok:
                state["t75_sent"][ev_id] = now_ts

    _save_state(state)


if __name__ == "__main__":
    mode = os.environ.get("BOT_MODE", "auto_scan").strip().lower()
    if mode == "command":
        run_command_mode()
    else:
        run_auto_scan_mode()
