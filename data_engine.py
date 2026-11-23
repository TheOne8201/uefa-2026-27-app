# -*- coding: utf-8 -*-
"""
UEFA 2026/2027 Data Engine (UCL & UEL)
100% Real Data from ESPN Public API + Trusted Google News RSS.
Zero Understat, Zero fabricated xG, Zero hardcoded secrets.
"""

from __future__ import annotations

import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus

import feedparser
import requests
from requests.adapters import HTTPAdapter

# ==============================================================================
# CẤU HÌNH HẰNG SỐ & CHỐNG TREO
# ==============================================================================
VN_TZ = timezone(timedelta(hours=7))
SEASON_YEAR = 2026
HTTP_TIMEOUT = (4, 7)

LEAGUES: dict[str, dict[str, str]] = {
    "UCL": {
        "code": "UCL",
        "name": "UEFA Champions League (UCL)",
        "short": "Champions League",
        "slug": "uefa.champions",
    },
    "UEL": {
        "code": "UEL",
        "name": "UEFA Europa League (UEL)",
        "short": "Europa League",
        "slug": "uefa.europa",
    },
}

TRUSTED_RSS_DOMAINS = [
    "uefa.com",
    "bbc.co.uk",
    "skysports.com",
    "theguardian.com",
    "reuters.com",
    "espn.com",
    "marca.com",
    "kicker.de",
    "gazzetta.it",
]

TEAM_ALIASES: dict[str, str] = {
    "real": "real madrid",
    "rm": "real madrid",
    "real madrid": "real madrid",
    "barca": "barcelona",
    "fcb": "barcelona",
    "atleti": "atletico madrid",
    "atletico": "atletico madrid",
    "bilbao": "athletic club",
    "athletic": "athletic club",
    "sociedad": "real sociedad",
    "betis": "real betis",
    "villarreal": "villarreal",
    "inter": "inter milan",
    "internazionale": "inter milan",
    "milan": "ac milan",
    "ac milan": "ac milan",
    "juve": "juventus",
    "napoli": "napoli",
    "atalanta": "atalanta",
    "roma": "as roma",
    "lazio": "lazio",
    "bologna": "bologna",
    "fiorentina": "fiorentina",
    "bayern": "bayern munich",
    "bayern munchen": "bayern munich",
    "dortmund": "borussia dortmund",
    "bvb": "borussia dortmund",
    "leverkusen": "bayer leverkusen",
    "leipzig": "rb leipzig",
    "frankfurt": "eintracht frankfurt",
    "stuttgart": "vfb stuttgart",
    "freiburg": "sc freiburg",
    "psg": "paris saint-germain",
    "paris": "paris saint-germain",
    "marseille": "olympique marseille",
    "om": "olympique marseille",
    "monaco": "as monaco",
    "lyon": "olympique lyonnais",
    "lille": "lille",
    "nice": "ogc nice",
    "brest": "stade brestois",
    "arsenal": "arsenal",
    "liverpool": "liverpool",
    "liv": "liverpool",
    "mc": "manchester city",
    "man city": "manchester city",
    "city": "manchester city",
    "mu": "manchester united",
    "man utd": "manchester united",
    "man united": "manchester united",
    "chelsea": "chelsea",
    "spurs": "tottenham hotspur",
    "tottenham": "tottenham hotspur",
    "villa": "aston villa",
    "aston villa": "aston villa",
    "newcastle": "newcastle united",
    "sporting": "sporting cp",
    "sporting lisbon": "sporting cp",
    "benfica": "benfica",
    "porto": "fc porto",
    "braga": "braga",
    "ajax": "ajax",
    "psv": "psv eindhoven",
    "feyenoord": "feyenoord",
    "az": "az alkmaar",
    "twente": "fc twente",
    "fenerbahce": "fenerbahce",
    "fener": "fenerbahce",
    "galatasaray": "galatasaray",
    "gala": "galatasaray",
    "besiktas": "besiktas",
    "brugge": "club brugge",
    "club brugge": "club brugge",
    "anderlecht": "anderlecht",
    "union sg": "union saint-gilloise",
    "celtic": "celtic",
    "rangers": "rangers",
    "olympiacos": "olympiacos",
    "paok": "paok",
    "shakhtar": "shakhtar donetsk",
    "dinamo zagreb": "dinamo zagreb",
    "zagreb": "dinamo zagreb",
    "sparta prague": "sparta prague",
    "slavia prague": "slavia prague",
    "salzburg": "rb salzburg",
    "sturm graz": "sturm graz",
    "bodo": "bodo/glimt",
    "bodo glimt": "bodo/glimt",
    "red star": "crvena zvezda",
    "zvezda": "crvena zvezda",
    "young boys": "young boys",
    "basel": "fc basel",
    "copenhagen": "fc copenhagen",
    "midtjylland": "fc midtjylland",
    "ferencvaros": "ferencvaros",
    "qarabag": "qarabag",
}


def _create_session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=24, pool_maxsize=24)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/129.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/xml, application/xml;q=0.9, */*;q=0.8",
        }
    )
    return session


_SESSION = _create_session()


# ==============================================================================
# HÀM TIỆN ÍCH CƠ BẢN
# ==============================================================================
def _http_get_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        resp = _SESSION.get(url, params=params, timeout=HTTP_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _http_get_bytes(url: str) -> bytes:
    try:
        resp = _SESSION.get(url, timeout=HTTP_TIMEOUT)
        if resp.status_code == 200:
            return resp.content
    except Exception:
        pass
    return b""


def normalize_text(text: str) -> str:
    if not text:
        return ""
    s = unicodedata.normalize("NFD", str(text))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D")
    s = re.sub(r"[^a-zA-Z0-9\s/-]", " ", s).lower()
    return re.sub(r"\s+", " ", s).strip()


def resolve_team_alias(query: str) -> str:
    norm = normalize_text(query)
    if norm in TEAM_ALIASES:
        return TEAM_ALIASES[norm]
    return norm


def parse_iso_to_vn(iso_str: str) -> datetime | None:
    if not iso_str:
        return None
    try:
        cleaned = iso_str.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(VN_TZ)
    except Exception:
        return None


def fmt_vn_time(dt: datetime | None) -> str:
    if not dt:
        return "Chưa xác định"
    return dt.strftime("%H:%M %d/%m/%Y (GMT+7)")


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        if val is None or val == "":
            return default
        return int(float(str(val).replace("%", "").strip()))
    except Exception:
        return default


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None or val == "":
            return default
        return float(str(val).replace("%", "").strip())
    except Exception:
        return default


def _extract_score(comp_entry: dict[str, Any]) -> int | None:
    raw = comp_entry.get("score")
    if isinstance(raw, dict):
        val = raw.get("value")
        if val is None:
            val = raw.get("displayValue")
    else:
        val = raw
    if val is None or str(val).strip() == "":
        return None
    try:
        return int(float(str(val).strip()))
    except Exception:
        return None


# ==============================================================================
# 1. LỊCH THI ĐẤU & DANH SÁCH ĐỘI (SCOREBOARD CALENDAR + TEAM SCHEDULE)
# ==============================================================================
def _parse_scoreboard_events(data: dict[str, Any], league_code: str) -> list[dict[str, Any]]:
    league_info = LEAGUES[league_code]
    events = data.get("events", []) or []
    fixtures: list[dict[str, Any]] = []

    for ev in events:
        event_id = str(ev.get("id", "")).strip()
        if not event_id:
            continue
        comps = ev.get("competitions", []) or []
        if not comps:
            continue
        comp = comps[0]
        competitors = comp.get("competitors", []) or []
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue

        home_team = home.get("team", {}) or {}
        away_team = away.get("team", {}) or {}
        dt_vn = parse_iso_to_vn(ev.get("date", ""))
        status_type = (comp.get("status", {}) or {}).get("type", {}) or {}
        status_state = str(status_type.get("state", "pre"))
        status_detail = str(status_type.get("shortDetail") or status_type.get("description") or "")

        venue_obj = comp.get("venue", {}) or {}
        venue_name = venue_obj.get("fullName", "")
        venue_city = (venue_obj.get("address", {}) or {}).get("city", "")
        venue_str = f"{venue_name}, {venue_city}".strip(", ") if venue_name else "Chưa cập nhật"

        notes = comp.get("notes", []) or []
        note_text = " | ".join(
            str(n.get("headline", "")).strip() for n in notes if n.get("headline")
        )
        round_name = ""
        season_type_obj = ev.get("season", {}) or {}
        if isinstance(season_type_obj.get("slug"), str):
            round_name = season_type_obj.get("slug", "")
        if note_text:
            round_name = note_text

        home_score = _extract_score(home)
        away_score = _extract_score(away)
        time_label = dt_vn.strftime("%d/%m %H:%M") if dt_vn else "TBD"
        score_tag = (
            f" [{home_score}-{away_score}]"
            if status_state in ("in", "post") and home_score is not None and away_score is not None
            else ""
        )

        fixtures.append(
            {
                "event_id": event_id,
                "league_code": league_code,
                "league_name": league_info["name"],
                "slug": league_info["slug"],
                "date_utc": ev.get("date", ""),
                "kickoff_vn": fmt_vn_time(dt_vn),
                "kickoff_dt_vn": dt_vn,
                "status_state": status_state,
                "status_detail": status_detail,
                "round_name": round_name or league_info["short"],
                "venue": venue_str,
                "home_id": str(home_team.get("id", "")),
                "home_name": str(home_team.get("displayName") or home_team.get("name") or ""),
                "home_abbr": str(home_team.get("abbreviation") or ""),
                "home_logo": str(home_team.get("logo") or ""),
                "away_id": str(away_team.get("id", "")),
                "away_name": str(away_team.get("displayName") or away_team.get("name") or ""),
                "away_abbr": str(away_team.get("abbreviation") or ""),
                "away_logo": str(away_team.get("logo") or ""),
                "home_score": home_score,
                "away_score": away_score,
                "display_label": (
                    f"{time_label} | {home_team.get('displayName', '')} vs "
                    f"{away_team.get('displayName', '')}{score_tag}"
                ),
            }
        )

    fixtures.sort(key=lambda x: x["date_utc"] or "9999")
    return fixtures


def get_upcoming_fixtures(
    league_code: str,
    days_ahead: int = 60,
    days_back: int = 2,
) -> list[dict[str, Any]]:
    """
    Lấy đầy đủ danh sách các trận sắp tới của UCL/UEL bằng 2 lớp tự động:
      1) Đọc trực tiếp lịch ngày thi đấu chính thức (`calendar`) từ ESPN Scoreboard
         và gọi song song từng ngày YYYYMMDD.
      2) Nếu `calendar` chưa trả về trận sắp đá, lấy ngày đá kế tiếp từ lịch riêng
         của 6 CLB đại diện trong giải rồi kéo toàn bộ cặp đấu các ngày đó.
    """
    slug = LEAGUES[league_code]["slug"]
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
    now_utc = datetime.now(timezone.utc)
    min_dt = now_utc - timedelta(days=days_back)
    max_dt = now_utc + timedelta(days=max(days_ahead, 60))

    merged: dict[str, dict[str, Any]] = {}
    base_data = _http_get_json(url, params={"limit": 100})
    for fx in _parse_scoreboard_events(base_data, league_code):
        merged[fx["event_id"]] = fx

    # Lớp 1: Trích các ngày thi đấu chính thức từ trường `calendar` của ESPN
    target_dates: list[str] = []
    for lg_obj in base_data.get("leagues", []) or []:
        for cal_item in lg_obj.get("calendar", []) or []:
            cal_str = (
                cal_item
                if isinstance(cal_item, str)
                else str((cal_item or {}).get("startDate") or (cal_item or {}).get("value") or "")
            )
            dt_cal = parse_iso_to_vn(cal_str)
            if dt_cal:
                dt_cal_utc = dt_cal.astimezone(timezone.utc)
                if min_dt <= dt_cal_utc <= max_dt:
                    d_key = dt_cal_utc.strftime("%Y%m%d")
                    if d_key not in target_dates:
                        target_dates.append(d_key)

    target_dates.sort()
    if target_dates:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futs = [
                pool.submit(_http_get_json, url, {"dates": d_key, "limit": 100})
                for d_key in target_dates[:8]
            ]
            try:
                for fut in as_completed(futs, timeout=9):
                    try:
                        for fx in _parse_scoreboard_events(fut.result(), league_code):
                            merged[fx["event_id"]] = fx
                    except Exception:
                        pass
            except Exception:
                pass

    # Lớp 2: Nếu chưa có trận sắp đá (pre/in), dò ngày thi đấu từ lịch riêng 6 CLB trong giải
    has_upcoming = any(f["status_state"] in ("pre", "in") for f in merged.values())
    if not has_upcoming:
        teams = get_league_teams(league_code)
        if teams:
            step = max(1, len(teams) // 6)
            sample_teams = teams[::step][:6]
            target_kw = "champions league" if league_code == "UCL" else "europa league"
            discovered_dates: set[str] = set()

            with ThreadPoolExecutor(max_workers=6) as pool:
                futs = [
                    pool.submit(get_team_all_comp_schedule, t["id"], SEASON_YEAR, True)
                    for t in sample_teams
                ]
                try:
                    for fut in as_completed(futs, timeout=9):
                        try:
                            for m in fut.result():
                                is_this_comp = (
                                    m.get("league_slug") == slug
                                    or target_kw in m.get("league_name", "").lower()
                                )
                                if not is_this_comp:
                                    continue
                                if m["state"] in ("pre", "in") and m.get("dt_vn"):
                                    d_utc = m["dt_vn"].astimezone(timezone.utc).strftime("%Y%m%d")
                                    discovered_dates.add(d_utc)
                                    # Thêm luôn trận tìm thấy từ lịch CLB làm phương án dự phòng
                                    if m["event_id"] not in merged:
                                        merged[m["event_id"]] = _build_light_fixture(m, league_code)
                        except Exception:
                            pass
                except Exception:
                    pass

            if discovered_dates:
                with ThreadPoolExecutor(max_workers=6) as pool:
                    futs = [
                        pool.submit(_http_get_json, url, {"dates": d_key, "limit": 100})
                        for d_key in sorted(discovered_dates)[:6]
                    ]
                    try:
                        for fut in as_completed(futs, timeout=8):
                            try:
                                for fx in _parse_scoreboard_events(fut.result(), league_code):
                                    merged[fx["event_id"]] = fx
                            except Exception:
                                pass
                    except Exception:
                        pass

    fixtures = list(merged.values())
    fixtures.sort(key=lambda x: x["date_utc"] or "9999")
    return fixtures


def get_scoreboard_for_auto_scan(league_code: str) -> list[dict[str, Any]]:
    """Đúng 1 lượt gọi Scoreboard cho chế độ quét tự động GitHub Actions (hôm nay + ngày mai)."""
    slug = LEAGUES[league_code]["slug"]
    now_utc = datetime.now(timezone.utc)
    start_str = (now_utc - timedelta(hours=6)).strftime("%Y%m%d")
    end_str = (now_utc + timedelta(hours=30)).strftime("%Y%m%d")
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
    data = _http_get_json(url, params={"dates": f"{start_str}-{end_str}", "limit": 100})
    return _parse_scoreboard_events(data, league_code)


def get_league_teams(league_code: str) -> list[dict[str, str]]:
    """Lấy danh sách toàn bộ đội bóng tham dự giải từ ESPN Teams + Standings."""
    slug = LEAGUES[league_code]["slug"]
    teams_map: dict[str, dict[str, str]] = {}

    url_teams = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/teams"
    data = _http_get_json(url_teams, params={"limit": 100})
    sports = data.get("sports", []) or []
    for sp in sports:
        for lg in sp.get("leagues", []) or []:
            for item in lg.get("teams", []) or []:
                t = item.get("team", {}) or {}
                tid = str(t.get("id", "")).strip()
                tname = str(t.get("displayName") or t.get("name") or "").strip()
                if tid and tname:
                    teams_map[tid] = {
                        "id": tid,
                        "name": tname,
                        "abbr": str(t.get("abbreviation", "")),
                    }

    if len(teams_map) < 20:
        standings = get_league_standings(league_code)
        for row in standings.get("table", []):
            tid = str(row.get("team_id", ""))
            if tid and tid not in teams_map:
                teams_map[tid] = {
                    "id": tid,
                    "name": row.get("team_name", ""),
                    "abbr": row.get("team_abbr", ""),
                }

    return sorted(teams_map.values(), key=lambda x: x["name"])


def _build_light_fixture(m: dict[str, Any], league_code: str) -> dict[str, Any]:
    league_info = LEAGUES[league_code]
    dt_vn = m.get("dt_vn") or parse_iso_to_vn(m.get("date_utc", ""))
    time_label = dt_vn.strftime("%d/%m %H:%M") if dt_vn else "TBD"
    h_score = m.get("home_score")
    a_score = m.get("away_score")
    state = m.get("state", "pre")
    score_tag = (
        f" [{h_score}-{a_score}]"
        if state in ("in", "post") and h_score is not None and a_score is not None
        else ""
    )
    return {
        "event_id": m["event_id"],
        "league_code": league_code,
        "league_name": league_info["name"],
        "slug": league_info["slug"],
        "date_utc": m.get("date_utc", ""),
        "kickoff_vn": fmt_vn_time(dt_vn),
        "kickoff_dt_vn": dt_vn,
        "status_state": state,
        "status_detail": state.upper(),
        "round_name": league_info["short"],
        "venue": "Sân CLB chủ nhà",
        "home_id": m.get("home_id", ""),
        "home_name": m.get("home_name", ""),
        "home_abbr": "",
        "home_logo": "",
        "away_id": m.get("away_id", ""),
        "away_name": m.get("away_name", ""),
        "away_abbr": "",
        "away_logo": "",
        "home_score": h_score,
        "away_score": a_score,
        "display_label": (
            f"{time_label} | {m.get('home_name', '')} vs {m.get('away_name', '')}{score_tag}"
        ),
    }


def _schedule_item_to_fixture(m: dict[str, Any], league_code: str) -> dict[str, Any]:
    """Chuyển đổi bản ghi lịch đội bóng thành chuẩn fixture đầy đủ thông tin sân bãi."""
    league_info = LEAGUES[league_code]
    dt_vn = m.get("dt_vn") or parse_iso_to_vn(m.get("date_utc", ""))
    if dt_vn:
        day_str = dt_vn.astimezone(timezone.utc).strftime("%Y%m%d")
        sb_url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league_info['slug']}/scoreboard"
        sb_data = _http_get_json(sb_url, params={"dates": day_str, "limit": 50})
        for fx in _parse_scoreboard_events(sb_data, league_code):
            if fx["event_id"] == m["event_id"]:
                return fx
    return _build_light_fixture(m, league_code)


def find_team_next_match(
    query_text: str,
    preferred_league: str | None = None,
) -> dict[str, Any] | None:
    """
    Tìm trận đấu sắp tới (ưu tiên chưa đá/đang đá) của 1 đội bóng trên UCL/UEL:
      1) Quét trực tiếp các trận sắp tới từ get_upcoming_fixtures
      2) Tra team_id và kéo lịch riêng của đội (kèm ?fixture=true)
    """
    resolved = resolve_team_alias(query_text)
    raw_norm = normalize_text(query_text)
    if not resolved and not raw_norm:
        return None

    target_leagues = [preferred_league] if preferred_league in LEAGUES else ["UCL", "UEL"]

    def _match_team_name(name_str: str, abbr_str: str = "") -> int:
        tn = normalize_text(name_str)
        ta = normalize_text(abbr_str)
        best = 0
        for q in (resolved, raw_norm):
            if not q:
                continue
            if q == tn:
                best = max(best, 100)
            elif q in tn:
                best = max(best, 90)
            elif ta and q == ta:
                best = max(best, 80)
            elif len(q.split()) >= 1 and all(tok in tn for tok in q.split()):
                best = max(best, 75)
        return best

    # 1. Tìm trong danh sách trận sắp đá (pre/in) của UCL & UEL
    upcoming_all: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = [pool.submit(get_upcoming_fixtures, lg, 60, 1) for lg in target_leagues]
        for fut in as_completed(futs, timeout=12):
            try:
                upcoming_all.extend(fut.result())
            except Exception:
                pass

    upcoming_hits: list[tuple[int, dict[str, Any]]] = []
    for fx in upcoming_all:
        if fx["status_state"] not in ("pre", "in"):
            continue
        sc = max(
            _match_team_name(fx["home_name"], fx.get("home_abbr", "")),
            _match_team_name(fx["away_name"], fx.get("away_abbr", "")),
        )
        if sc > 0:
            upcoming_hits.append((sc, fx))

    if upcoming_hits:
        upcoming_hits.sort(key=lambda x: (-x[0], x[1]["date_utc"] or "9999"))
        return upcoming_hits[0][1]

    # 2. Tra ID đội trong danh sách giải và kéo lịch riêng (gồm cả ?fixture=true)
    teams_by_league: dict[str, list[dict[str, str]]] = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = {pool.submit(get_league_teams, lg): lg for lg in target_leagues}
        for fut in as_completed(futs, timeout=10):
            lg = futs[fut]
            try:
                teams_by_league[lg] = fut.result()
            except Exception:
                teams_by_league[lg] = []

    matched_teams: list[tuple[int, str, dict[str, str]]] = []
    for lg, t_list in teams_by_league.items():
        for t in t_list:
            sc = _match_team_name(t.get("name", ""), t.get("abbr", ""))
            if sc > 0:
                matched_teams.append((sc, lg, t))

    matched_teams.sort(key=lambda x: -x[0])

    for _, lg, team_obj in matched_teams[:2]:
        team_id = team_obj["id"]
        target_slug = LEAGUES[lg]["slug"]
        target_kw = "champions league" if lg == "UCL" else "europa league"
        sched = get_team_all_comp_schedule(team_id, SEASON_YEAR, include_fixtures=True)

        uefa_matches = [
            m
            for m in sched
            if m.get("league_slug") == target_slug
            or target_kw in m.get("league_name", "").lower()
        ]
        if not uefa_matches:
            continue

        upcoming = [m for m in uefa_matches if m["state"] in ("pre", "in")]
        if upcoming:
            upcoming.sort(key=lambda x: x["date_utc"] or "9999")
            return _schedule_item_to_fixture(upcoming[0], lg)

        completed = [m for m in uefa_matches if m["state"] == "post"]
        if completed:
            completed.sort(key=lambda x: x["date_utc"] or "", reverse=True)
            return _schedule_item_to_fixture(completed[0], lg)

    return None


# ==============================================================================
# 2. BẢNG XẾP HẠNG LEAGUE PHASE 36 ĐỘI & CỤC DIỆN KNOCK-OUT
# ==============================================================================
def _classify_uefa_zone(rank: int) -> str:
    if 1 <= rank <= 8:
        return "Top 8 - Đi thẳng Vòng 1/8"
    if 9 <= rank <= 24:
        return "Hạng 9-24 - Đá Play-off"
    if rank >= 25:
        return "Hạng 25-36 - Nhóm bị loại"
    return "Chưa phân vùng"


def _extract_standings_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not isinstance(data, dict):
        return entries

    if data.get("children"):
        for child in data["children"]:
            st = child.get("standings", {}) or {}
            child_entries = st.get("entries", []) or []
            if len(child_entries) > len(entries):
                entries = child_entries
    if not entries and data.get("standings"):
        entries = (data.get("standings", {}) or {}).get("entries", []) or []
    return entries


def get_league_standings(league_code: str) -> dict[str, Any]:
    """Lấy bảng xếp hạng League Phase 36 đội từ ESPN Standings."""
    slug = LEAGUES[league_code]["slug"]
    endpoints = [
        (f"https://site.api.espn.com/apis/v2/sports/soccer/{slug}/standings", None),
        (f"https://site.api.espn.com/apis/v2/sports/soccer/{slug}/standings", {"season": SEASON_YEAR}),
        (f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/standings", None),
    ]

    entries: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = [pool.submit(_http_get_json, u, p) for u, p in endpoints]
        try:
            for fut in as_completed(futs, timeout=8):
                try:
                    cand = _extract_standings_entries(fut.result())
                    if len(cand) > len(entries):
                        entries = cand
                except Exception:
                    pass
        except Exception:
            pass

    rows: list[dict[str, Any]] = []
    for idx, entry in enumerate(entries, start=1):
        team = entry.get("team", {}) or {}
        stats_list = entry.get("stats", []) or []
        stat_map: dict[str, Any] = {}
        for st in stats_list:
            name = st.get("name") or st.get("abbreviation") or ""
            stat_map[name] = st.get("value", st.get("displayValue"))

        note_rank = (entry.get("note", {}) or {}).get("rank")
        rank = _safe_int(stat_map.get("rank") or note_rank, idx)
        played = _safe_int(stat_map.get("gamesPlayed"), 0)
        wins = _safe_int(stat_map.get("wins"), 0)
        draws = _safe_int(stat_map.get("ties"), 0)
        losses = _safe_int(stat_map.get("losses"), 0)
        gf = _safe_int(stat_map.get("pointsFor"), 0)
        ga = _safe_int(stat_map.get("pointsAgainst"), 0)
        gd = _safe_int(stat_map.get("pointDifferential"), gf - ga)
        pts = _safe_int(stat_map.get("points"), 0)

        rows.append(
            {
                "rank": rank,
                "team_id": str(team.get("id", "")),
                "team_name": str(team.get("displayName") or team.get("name") or ""),
                "team_abbr": str(team.get("abbreviation") or ""),
                "played": played,
                "wins": wins,
                "draws": draws,
                "losses": losses,
                "gf": gf,
                "ga": ga,
                "gd": gd,
                "points": pts,
                "zone": _classify_uefa_zone(rank),
            }
        )

    rows.sort(key=lambda r: (r["rank"], -r["points"], -r["gd"]))

    top8_cutoff = rows[7]["points"] if len(rows) >= 8 else None
    top24_cutoff = rows[23]["points"] if len(rows) >= 24 else None

    return {
        "league_code": league_code,
        "table": rows,
        "top8_cutoff": top8_cutoff,
        "top24_cutoff": top24_cutoff,
    }


def extract_knockout_context(summary: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    """Tự động nhận diện trận thuộc League Phase hay vòng Knock-out (lượt đi/lượt về)."""
    header = summary.get("header", {}) or {}
    comps = header.get("competitions", []) or []
    comp = comps[0] if comps else {}
    notes = comp.get("notes", []) or []
    note_lines = [str(n.get("headline", "")).strip() for n in notes if n.get("headline")]

    season_info = header.get("season", {}) or {}
    season_name = str(season_info.get("name") or "")
    round_str = " | ".join(note_lines) or fixture.get("round_name", "")
    combined_lower = f"{round_str} {season_name}".lower()

    ko_keywords = [
        "knockout",
        "playoff",
        "play-off",
        "round of 16",
        "quarterfinal",
        "quarter-final",
        "semifinal",
        "semi-final",
        "final",
        "1st leg",
        "2nd leg",
        "first leg",
        "second leg",
        "aggregate",
    ]
    is_knockout = any(kw in combined_lower for kw in ko_keywords)

    leg_info = ""
    if "1st leg" in combined_lower or "first leg" in combined_lower:
        leg_info = "Lượt đi (1st Leg)"
    elif "2nd leg" in combined_lower or "second leg" in combined_lower:
        leg_info = "Lượt về (2nd Leg)"
    elif "final" in combined_lower and "semi" not in combined_lower and "quarter" not in combined_lower:
        leg_info = "Chung kết (1 trận duy nhất)"

    series = comp.get("series", {}) or {}
    series_summary = str(series.get("summary") or "")

    return {
        "is_knockout": is_knockout,
        "stage_label": "Vòng Knock-out" if is_knockout else "Vòng League Phase (36 đội)",
        "round_detail": round_str or "League Phase",
        "leg_info": leg_info,
        "aggregate_summary": series_summary,
        "notes": note_lines,
    }


# ==============================================================================
# 3. NHÂN SỰ, ĐỘI HÌNH T-75, CHẤN THƯƠNG ĐÃ LỌC & TRỤ CỘT 4 TUYẾN
# ==============================================================================
def get_team_roster_4_lines(slug: str, team_id: str) -> dict[str, Any]:
    """
    Lấy danh sách cầu thủ hiện tại & thông số thật mùa 2026/27 từ ESPN Roster,
    phân nhóm 4 tuyến (Thủ môn, Hậu vệ, Tiền vệ, Tiền đạo) + tập ID cầu thủ còn trong đội.
    """
    if not team_id:
        return {"lines": {}, "active_ids": set(), "active_names": set(), "count": 0}

    url_league = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/teams/{team_id}/roster"
    data = _http_get_json(url_league)
    athletes_raw = data.get("athletes", []) or []

    if not athletes_raw:
        url_all = f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{team_id}/roster"
        data = _http_get_json(url_all)
        athletes_raw = data.get("athletes", []) or []

    flat_players: list[dict[str, Any]] = []
    for item in athletes_raw:
        if isinstance(item, dict) and "items" in item and isinstance(item["items"], list):
            flat_players.extend(item["items"])
        elif isinstance(item, dict):
            flat_players.append(item)

    active_ids: set[str] = set()
    active_names: set[str] = set()
    lines: dict[str, list[dict[str, Any]]] = {
        "Thủ môn": [],
        "Hậu vệ": [],
        "Tiền vệ": [],
        "Tiền đạo": [],
    }

    for p in flat_players:
        pid = str(p.get("id", "")).strip()
        pname = str(p.get("displayName") or p.get("fullName") or p.get("shortName") or "").strip()
        if not pname:
            continue
        if pid:
            active_ids.add(pid)
        active_names.add(normalize_text(pname))

        pos_obj = p.get("position", {}) or {}
        pos_abbr = str(pos_obj.get("abbreviation") or "").upper()
        pos_name = str(pos_obj.get("name") or "").lower()

        if pos_abbr in ("G", "GK") or "goalkeeper" in pos_name:
            line_key = "Thủ môn"
        elif pos_abbr in ("D", "DF", "CB", "LB", "RB", "WB") or "defender" in pos_name:
            line_key = "Hậu vệ"
        elif pos_abbr in ("M", "MF", "CM", "DM", "AM", "LM", "RM") or "midfielder" in pos_name:
            line_key = "Tiền vệ"
        else:
            line_key = "Tiền đạo"

        apps = 0
        goals = 0
        assists = 0
        stats_root = p.get("statistics", {}) or {}
        splits = stats_root.get("splits", {}) or {}
        categories = splits.get("categories", []) or []
        for cat in categories:
            for st in cat.get("stats", []) or []:
                sname = str(st.get("name") or "").lower()
                sval = _safe_int(st.get("value"), 0)
                if sname in ("appearances", "gamesplayed"):
                    apps = max(apps, sval)
                elif sname in ("totalgoals", "goals"):
                    goals = max(goals, sval)
                elif sname in ("goalassists", "assists"):
                    assists = max(assists, sval)

        lines[line_key].append(
            {
                "id": pid,
                "name": pname,
                "jersey": str(p.get("jersey") or ""),
                "pos": pos_abbr or line_key,
                "appearances": apps,
                "goals": goals,
                "assists": assists,
            }
        )

    for k in lines:
        lines[k].sort(
            key=lambda x: (x["appearances"], x["goals"] * 2 + x["assists"]),
            reverse=True,
        )

    return {
        "lines": {
            "Thủ môn": lines["Thủ môn"][:2],
            "Hậu vệ": lines["Hậu vệ"][:5],
            "Tiền vệ": lines["Tiền vệ"][:5],
            "Tiền đạo": lines["Tiền đạo"][:4],
        },
        "active_ids": active_ids,
        "active_names": active_names,
        "count": len(flat_players),
    }


def extract_lineups_t75(
    summary: dict[str, Any],
    home_id: str,
    away_id: str,
) -> dict[str, dict[str, Any]]:
    """Trích đội hình ra sân chính thức T-75 từ ESPN Summary (tuyệt đối không bịa)."""
    result = {
        "home": {"confirmed": False, "formation": "", "starters": [], "subs": []},
        "away": {"confirmed": False, "formation": "", "starters": [], "subs": []},
    }
    rosters = summary.get("rosters", []) or []
    for r in rosters:
        tid = str((r.get("team", {}) or {}).get("id", ""))
        side = "home" if tid == home_id else ("away" if tid == away_id else None)
        if not side:
            continue
        formation = str(r.get("formation") or "")
        starters: list[dict[str, str]] = []
        subs: list[dict[str, str]] = []

        for entry in r.get("roster", []) or []:
            ath = entry.get("athlete", {}) or {}
            name = str(ath.get("displayName") or ath.get("shortName") or "").strip()
            if not name:
                continue
            jersey = str(entry.get("jersey") or ath.get("jersey") or "")
            pos = str((entry.get("position", {}) or {}).get("abbreviation") or "")
            item = {"name": name, "jersey": jersey, "pos": pos}
            if entry.get("starter") is True:
                starters.append(item)
            else:
                subs.append(item)

        result[side] = {
            "confirmed": len(starters) >= 11,
            "formation": formation,
            "starters": starters,
            "subs": subs,
        }
    return result


def extract_injuries_filtered(
    summary: dict[str, Any],
    home_id: str,
    away_id: str,
    home_roster_info: dict[str, Any],
    away_roster_info: dict[str, Any],
) -> dict[str, list[dict[str, str]]]:
    """
    Trích chấn thương/treo giò từ ESPN Summary và lọc bỏ cầu thủ đã bán/cho mượn
    bằng cách đối chiếu với danh sách đội hình hiện tại (active_ids / active_names).
    """
    out: dict[str, list[dict[str, str]]] = {"home": [], "away": []}
    injuries_blocks = summary.get("injuries", []) or []

    for block in injuries_blocks:
        tid = str((block.get("team", {}) or {}).get("id", ""))
        side = "home" if tid == home_id else ("away" if tid == away_id else None)
        if not side:
            continue

        roster_info = home_roster_info if side == "home" else away_roster_info
        active_ids: set[str] = roster_info.get("active_ids", set())
        active_names: set[str] = roster_info.get("active_names", set())
        use_roster_filter = roster_info.get("count", 0) >= 15

        seen_names: set[str] = set()
        for inj in block.get("injuries", []) or []:
            ath = inj.get("athlete", {}) or {}
            pid = str(ath.get("id", "")).strip()
            pname = str(ath.get("displayName") or ath.get("shortName") or "").strip()
            if not pname:
                continue

            status = str(inj.get("status") or "").strip()
            details = inj.get("details", {}) or {}
            detail_type = str(details.get("type") or details.get("detail") or "").strip()
            return_date = str(details.get("returnDate") or "").strip()
            comment = str(inj.get("shortComment") or inj.get("longComment") or "").strip()

            low_check = f"{status} {detail_type} {comment}".lower()
            if any(k in low_check for k in ("loaned", "transferred", "departed", "sold")):
                continue

            norm_name = normalize_text(pname)
            if use_roster_filter:
                if (pid and pid not in active_ids) and (norm_name not in active_names):
                    continue

            if norm_name in seen_names:
                continue
            seen_names.add(norm_name)

            pos = str((ath.get("position", {}) or {}).get("abbreviation") or "")
            out[side].append(
                {
                    "name": pname,
                    "pos": pos,
                    "status": status or "Chấn thương/Vắng mặt",
                    "detail": detail_type or comment[:80] or "Đang theo dõi",
                    "return_date": return_date,
                }
            )
    return out


# ==============================================================================
# 4. LỊCH ĐA GIẢI "BÁNH MÌ KẸP", PHONG ĐỘ & VÁ LỖI H2H 4 MÙA
# ==============================================================================
def _parse_schedule_events(data: dict[str, Any], team_id: str) -> list[dict[str, Any]]:
    events = data.get("events", []) or []
    parsed: list[dict[str, Any]] = []

    for ev in events:
        ev_id = str(ev.get("id", "")).strip()
        comps = ev.get("competitions", []) or []
        if not ev_id or not comps:
            continue
        comp = comps[0]
        competitors = comp.get("competitors", []) or []
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue

        h_team = home.get("team", {}) or {}
        a_team = away.get("team", {}) or {}
        h_id = str(h_team.get("id", ""))
        a_id = str(a_team.get("id", ""))
        if team_id not in (h_id, a_id):
            continue

        is_home = h_id == team_id
        opp_team = a_team if is_home else h_team
        dt_vn = parse_iso_to_vn(ev.get("date", ""))
        status_type = (comp.get("status", {}) or {}).get("type", {}) or {}
        state = str(status_type.get("state", "pre"))

        h_score = _extract_score(home)
        a_score = _extract_score(away)
        gf = h_score if is_home else a_score
        ga = a_score if is_home else h_score

        league_obj = ev.get("league", {}) or {}
        lg_slug = str(league_obj.get("slug") or "")
        lg_name = str(league_obj.get("shortName") or league_obj.get("name") or lg_slug or "Giải khác")

        result_char = ""
        if state == "post" and gf is not None and ga is not None:
            result_char = "W" if gf > ga else ("D" if gf == ga else "L")

        parsed.append(
            {
                "event_id": ev_id,
                "date_utc": ev.get("date", ""),
                "dt_vn": dt_vn,
                "kickoff_vn": fmt_vn_time(dt_vn),
                "state": state,
                "league_slug": lg_slug,
                "league_name": lg_name,
                "is_home": is_home,
                "venue_tag": "Sân nhà" if is_home else "Sân khách",
                "home_id": h_id,
                "away_id": a_id,
                "home_name": str(h_team.get("displayName") or h_team.get("name") or ""),
                "away_name": str(a_team.get("displayName") or a_team.get("name") or ""),
                "opponent_id": str(opp_team.get("id", "")),
                "opponent_name": str(opp_team.get("displayName") or opp_team.get("name") or ""),
                "home_score": h_score,
                "away_score": a_score,
                "gf": gf,
                "ga": ga,
                "result": result_char,
            }
        )
    return parsed


def get_team_all_comp_schedule(
    team_id: str,
    season: int = SEASON_YEAR,
    include_fixtures: bool = True,
) -> list[dict[str, Any]]:
    """
    Gọi lịch đa giải của đội trên ESPN (/soccer/all/teams/{id}/schedule):
    kết hợp cả kết quả đã đá lẫn tham số fixture=true cho các trận sắp đá.
    """
    if not team_id:
        return []
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{team_id}/schedule"

    merged: dict[str, dict[str, Any]] = {}
    if include_fixtures:
        with ThreadPoolExecutor(max_workers=3) as pool:
            f_past = pool.submit(_http_get_json, url, {"season": season})
            f_next = pool.submit(_http_get_json, url, {"season": season, "fixture": "true"})
            f_curr = pool.submit(_http_get_json, url, {"fixture": "true"})
            for fut in (f_past, f_next, f_curr):
                try:
                    for item in _parse_schedule_events(fut.result(timeout=8), team_id):
                        merged[item["event_id"]] = item
                except Exception:
                    pass
    else:
        data = _http_get_json(url, params={"season": season})
        for item in _parse_schedule_events(data, team_id):
            merged[item["event_id"]] = item

    parsed = list(merged.values())
    parsed.sort(key=lambda x: x["date_utc"] or "")
    return parsed


def build_sandwich_schedule(
    schedule: list[dict[str, Any]],
    target_event_id: str,
    target_dt_vn: datetime | None,
) -> dict[str, Any]:
    """Xây dựng thế 'Bánh mì kẹp' 7 ngày trước và 7 ngày sau trận Cúp châu Âu."""
    if not target_dt_vn:
        return {
            "before": [],
            "after": [],
            "days_rest_before": None,
            "days_rest_after": None,
            "warning_level": "Chưa đủ dữ liệu lịch",
            "warning_detail": "Chưa xác định được ngày giờ thi đấu để tính số ngày nghỉ.",
        }

    before: list[dict[str, Any]] = []
    after: list[dict[str, Any]] = []

    for m in schedule:
        if m["event_id"] == target_event_id or not m["dt_vn"]:
            continue
        delta_hours = (m["dt_vn"] - target_dt_vn).total_seconds() / 3600.0
        delta_days = round(abs(delta_hours) / 24.0, 1)

        if -180 <= delta_hours < -6:
            item = dict(m)
            item["gap_days"] = delta_days
            before.append(item)
        elif 6 < delta_hours <= 180:
            item = dict(m)
            item["gap_days"] = delta_days
            after.append(item)

    before.sort(key=lambda x: x["dt_vn"], reverse=True)
    after.sort(key=lambda x: x["dt_vn"])

    days_before = before[0]["gap_days"] if before else None
    days_after = after[0]["gap_days"] if after else None

    min_rest_candidates = [d for d in (days_before, days_after) if d is not None]
    min_rest = min(min_rest_candidates) if min_rest_candidates else None

    if min_rest is None:
        level = "Bình thường"
        detail = "Không ghi nhận trận đấu nào khác trong khung 7 ngày trước và sau trận trên ESPN."
    elif min_rest <= 3.3:
        level = "CẢNH BÁO ĐỎ - Mật độ dày đặc / Nguy cơ xoay tua cao"
        detail = (
            f"Khoảng nghỉ sát nhất chỉ {min_rest} ngày "
            f"(trước trận: {days_before if days_before is not None else 'trống'} ngày | "
            f"sau trận: {days_after if days_after is not None else 'trống'} ngày)."
        )
    elif min_rest <= 4.3:
        level = "CẢNH BÁO VÀNG - Mật độ trung bình"
        detail = (
            f"Khoảng nghỉ sát nhất là {min_rest} ngày "
            f"(trước trận: {days_before if days_before is not None else 'trống'} ngày | "
            f"sau trận: {days_after if days_after is not None else 'trống'} ngày)."
        )
    else:
        level = "XANH - Quỹ thời gian hồi phục tốt"
        detail = f"Khoảng nghỉ sát nhất đạt {min_rest} ngày, thuận lợi tung đội hình mạnh nhất."

    return {
        "before": before[:2],
        "after": after[:2],
        "days_rest_before": days_before,
        "days_rest_after": days_after,
        "warning_level": level,
        "warning_detail": detail,
    }


def extract_h2h_with_fallback(
    summary: dict[str, Any],
    home_id: str,
    away_id: str,
    home_schedule_curr: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Lấy tối đa 5 trận H2H gần nhất từ ESPN Summary.
    Nếu headToHeadGames bị trống, tự động quét song song 4 mùa gần nhất (2026..2023).
    """
    h2h_list: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for block in summary.get("headToHeadGames", []) or []:
        for ev in block.get("events", []) or []:
            ev_id = str(ev.get("id", "")).strip()
            if not ev_id or ev_id in seen_ids:
                continue
            dt_vn = parse_iso_to_vn(ev.get("gameDate") or ev.get("date") or "")
            home_score = _safe_int(ev.get("homeTeamScore"), -1)
            away_score = _safe_int(ev.get("awayTeamScore"), -1)
            if home_score < 0 or away_score < 0:
                continue
            seen_ids.add(ev_id)
            h2h_list.append(
                {
                    "event_id": ev_id,
                    "date_utc": ev.get("gameDate") or ev.get("date") or "",
                    "date_vn": dt_vn.strftime("%d/%m/%Y") if dt_vn else "N/A",
                    "league": str(ev.get("leagueName") or ev.get("leagueAbbreviation") or "Cúp/Giải"),
                    "home_name": str(ev.get("homeTeamName") or ""),
                    "away_name": str(ev.get("awayTeamName") or ""),
                    "score": f"{home_score} - {away_score}",
                }
            )

    if len(h2h_list) >= 3:
        h2h_list.sort(key=lambda x: x["date_utc"], reverse=True)
        return h2h_list[:5]

    all_past_events = list(home_schedule_curr)
    past_seasons = [SEASON_YEAR - 1, SEASON_YEAR - 2, SEASON_YEAR - 3]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = [pool.submit(get_team_all_comp_schedule, home_id, yr, False) for yr in past_seasons]
        try:
            for fut in as_completed(futs, timeout=8):
                try:
                    all_past_events.extend(fut.result())
                except Exception:
                    pass
        except Exception:
            pass

    for m in all_past_events:
        if m["state"] != "post":
            continue
        if m["opponent_id"] != away_id:
            continue
        if m["event_id"] in seen_ids:
            continue
        if m["home_score"] is None or m["away_score"] is None:
            continue
        seen_ids.add(m["event_id"])
        h2h_list.append(
            {
                "event_id": m["event_id"],
                "date_utc": m["date_utc"],
                "date_vn": m["dt_vn"].strftime("%d/%m/%Y") if m["dt_vn"] else "N/A",
                "league": m["league_name"],
                "home_name": m["home_name"],
                "away_name": m["away_name"],
                "score": f"{m['home_score']} - {m['away_score']}",
            }
        )

    h2h_list.sort(key=lambda x: x["date_utc"], reverse=True)
    return h2h_list[:5]


# ==============================================================================
# 5. PHONG ĐỘ 5 TRẬN & HIỆU SUẤT NÂNG CAO TỪ ESPN BOXSCORE + KEYEVENTS
# ==============================================================================
def _summarize_form_list(matches: list[dict[str, Any]], limit: int = 5) -> dict[str, Any]:
    recent = matches[:limit]
    total = len(recent)
    gf_sum = sum(m["gf"] or 0 for m in recent)
    ga_sum = sum(m["ga"] or 0 for m in recent)
    w = sum(1 for m in recent if m["result"] == "W")
    d = sum(1 for m in recent if m["result"] == "D")
    l = sum(1 for m in recent if m["result"] == "L")
    win_by_2_list = [
        f"{m['dt_vn'].strftime('%d/%m') if m['dt_vn'] else ''} vs {m['opponent_name']} ({m['gf']}-{m['ga']})"
        for m in recent
        if m["gf"] is not None and m["ga"] is not None and (m["gf"] - m["ga"]) >= 2
    ]
    win_by_2_pct = round((len(win_by_2_list) / total) * 100.0, 1) if total > 0 else 0.0
    form_str = "-".join(m["result"] for m in recent if m["result"]) or "Chưa có"

    return {
        "count": total,
        "form_str": form_str,
        "record": f"{w}T - {d}H - {l}B",
        "gf": gf_sum,
        "ga": ga_sum,
        "win_by_2_count": len(win_by_2_list),
        "win_by_2_pct": win_by_2_pct,
        "win_by_2_list": win_by_2_list,
        "matches": recent,
    }


def compute_team_form(
    schedule: list[dict[str, Any]],
    target_dt_vn: datetime | None,
) -> dict[str, Any]:
    """Tính phong độ 5 trận gần nhất: Cúp châu Âu, Mọi đấu trường, Sân nhà, Sân khách."""
    completed = [
        m
        for m in schedule
        if m["state"] == "post"
        and m["gf"] is not None
        and m["ga"] is not None
        and (target_dt_vn is None or (m["dt_vn"] and m["dt_vn"] < target_dt_vn))
    ]
    completed.sort(key=lambda x: x["date_utc"], reverse=True)

    euro_only = [
        m
        for m in completed
        if m["league_slug"] in ("uefa.champions", "uefa.europa", "uefa.europa.conf")
    ]
    home_only = [m for m in completed if m["is_home"]]
    away_only = [m for m in completed if not m["is_home"]]

    return {
        "all_5": _summarize_form_list(completed, 5),
        "euro_5": _summarize_form_list(euro_only, 5),
        "home_5": _summarize_form_list(home_only, 5),
        "away_5": _summarize_form_list(away_only, 5),
        "completed_for_boxscore": completed[:8],
    }


def _classify_goal_event(event_type_text: str, description: str) -> str:
    combined = f"{event_type_text} {description}".lower()
    if "own goal" in combined:
        return "Phản lưới"
    if "penalty" in combined:
        return "Phạt đền"
    if "corner" in combined:
        return "Phạt góc"
    if "free kick" in combined or "free-kick" in combined:
        return "Đá phạt"
    return "Bóng sống"


def _fetch_single_boxscore_stats(match_item: dict[str, Any], team_id: str) -> dict[str, Any] | None:
    slug = match_item.get("league_slug") or "soccer"
    ev_id = match_item.get("event_id")
    if not ev_id:
        return None
    api_slug = slug if "." in slug else "all"
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{api_slug}/summary"
    data = _http_get_json(url, params={"event": ev_id})
    if not data:
        return None

    box_teams = (data.get("boxscore", {}) or {}).get("teams", []) or []
    team_stats: dict[str, float] = {}
    opp_stats: dict[str, float] = {}

    for bt in box_teams:
        tid = str((bt.get("team", {}) or {}).get("id", ""))
        stat_dict: dict[str, float] = {}
        for st in bt.get("statistics", []) or []:
            sname = str(st.get("name") or "").lower()
            sval = _safe_float(st.get("displayValue") or st.get("value"), -1.0)
            if sval >= 0:
                stat_dict[sname] = sval
        if tid == team_id:
            team_stats = stat_dict
        else:
            opp_stats = stat_dict

    if not team_stats:
        return None

    shots = team_stats.get("totalshots", 0.0)
    sot = team_stats.get("shotsontarget", 0.0)
    opp_sot = opp_stats.get("shotsontarget", 0.0)
    corners = team_stats.get("woncorners", 0.0)
    poss = team_stats.get("possessionpct", 0.0)

    goals_for_types = {"Bóng sống": 0, "Phạt góc": 0, "Đá phạt": 0, "Phạt đền": 0, "Phản lưới": 0}
    goals_against_types = {"Bóng sống": 0, "Phạt góc": 0, "Đá phạt": 0, "Phạt đền": 0, "Phản lưới": 0}

    key_events = data.get("keyEvents", []) or []
    for ke in key_events:
        if not ke.get("scoringPlay"):
            t_txt = str((ke.get("type", {}) or {}).get("text", "")).lower()
            if "goal" not in t_txt and "penalty - scored" not in t_txt:
                continue
        ke_team_id = str((ke.get("team", {}) or {}).get("id", ""))
        type_text = str((ke.get("type", {}) or {}).get("text", ""))
        desc_text = str(ke.get("text", ""))
        cat = _classify_goal_event(type_text, desc_text)

        if ke_team_id == team_id:
            goals_for_types[cat] += 1
        elif ke_team_id:
            goals_against_types[cat] += 1

    return {
        "is_home": match_item["is_home"],
        "gf": match_item["gf"] or 0,
        "ga": match_item["ga"] or 0,
        "shots": shots,
        "sot": sot,
        "opp_sot": opp_sot,
        "corners": corners,
        "possession": poss,
        "goals_for_types": goals_for_types,
        "goals_against_types": goals_against_types,
    }


def _aggregate_boxscores(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {
            "sample_size": 0,
            "shots_avg": 0.0,
            "sot_avg": 0.0,
            "opp_sot_avg": 0.0,
            "sot_diff_avg": 0.0,
            "conversion_pct": 0.0,
            "corners_avg": 0.0,
            "possession_avg": 0.0,
            "goals_for_types": {"Bóng sống": 0, "Phạt góc": 0, "Đá phạt": 0, "Phạt đền": 0, "Phản lưới": 0},
            "goals_against_types": {"Bóng sống": 0, "Phạt góc": 0, "Đá phạt": 0, "Phạt đền": 0, "Phản lưới": 0},
        }

    total_shots = sum(r["shots"] for r in rows)
    total_sot = sum(r["sot"] for r in rows)
    total_opp_sot = sum(r["opp_sot"] for r in rows)
    total_corners = sum(r["corners"] for r in rows)
    poss_vals = [r["possession"] for r in rows if r["possession"] > 0]
    total_gf = sum(r["gf"] for r in rows)

    gf_types = {"Bóng sống": 0, "Phạt góc": 0, "Đá phạt": 0, "Phạt đền": 0, "Phản lưới": 0}
    ga_types = {"Bóng sống": 0, "Phạt góc": 0, "Đá phạt": 0, "Phạt đền": 0, "Phản lưới": 0}
    for r in rows:
        for k in gf_types:
            gf_types[k] += r["goals_for_types"].get(k, 0)
            ga_types[k] += r["goals_against_types"].get(k, 0)

    return {
        "sample_size": n,
        "shots_avg": round(total_shots / n, 2),
        "sot_avg": round(total_sot / n, 2),
        "opp_sot_avg": round(total_opp_sot / n, 2),
        "sot_diff_avg": round((total_sot - total_opp_sot) / n, 2),
        "conversion_pct": round((total_gf / total_sot) * 100.0, 1) if total_sot > 0 else 0.0,
        "corners_avg": round(total_corners / n, 2),
        "possession_avg": round(sum(poss_vals) / len(poss_vals), 1) if poss_vals else 0.0,
        "goals_for_types": gf_types,
        "goals_against_types": ga_types,
    }


def compute_advanced_boxscore_metrics(
    home_matches: list[dict[str, Any]],
    home_id: str,
    away_matches: list[dict[str, Any]],
    away_id: str,
) -> dict[str, dict[str, Any]]:
    """
    Kéo song song ESPN Boxscore & KeyEvents của tối đa 8 trận gần nhất cho mỗi đội,
    tách rõ Tổng / Sân nhà / Sân khách. Giới hạn chờ tổng 9 giây để không treo app.
    """
    home_rows: list[dict[str, Any]] = []
    away_rows: list[dict[str, Any]] = []

    tasks: list[tuple[str, dict[str, Any], str]] = []
    for m in home_matches[:8]:
        tasks.append(("home", m, home_id))
    for m in away_matches[:8]:
        tasks.append(("away", m, away_id))

    if tasks:
        with ThreadPoolExecutor(max_workers=10) as pool:
            fut_map = {
                pool.submit(_fetch_single_boxscore_stats, m, tid): side
                for side, m, tid in tasks
            }
            try:
                for fut in as_completed(fut_map, timeout=9):
                    side = fut_map[fut]
                    try:
                        res = fut.result()
                        if res:
                            if side == "home":
                                home_rows.append(res)
                            else:
                                away_rows.append(res)
                    except Exception:
                        pass
            except Exception:
                pass

    return {
        "home": {
            "overall": _aggregate_boxscores(home_rows),
            "home_split": _aggregate_boxscores([r for r in home_rows if r["is_home"]]),
            "away_split": _aggregate_boxscores([r for r in home_rows if not r["is_home"]]),
        },
        "away": {
            "overall": _aggregate_boxscores(away_rows),
            "home_split": _aggregate_boxscores([r for r in away_rows if r["is_home"]]),
            "away_split": _aggregate_boxscores([r for r in away_rows if not r["is_home"]]),
        },
    }


# ==============================================================================
# 6. BÁO CHÍ GOOGLE NEWS RSS UY TÍN CHUYÊN CÚP CHÂU ÂU
# ==============================================================================
def _clean_html_snippet(raw_html: str, max_len: int = 180) -> str:
    txt = re.sub(r"<[^>]+>", " ", raw_html or "")
    txt = re.sub(r"\s+", " ", txt).strip()
    if len(txt) > max_len:
        return txt[: max_len - 3].rstrip() + "..."
    return txt


def _fetch_single_rss_query(query: str) -> list[dict[str, Any]]:
    site_filter = " OR ".join(f"site:{d}" for d in TRUSTED_RSS_DOMAINS)
    full_q = f"({query}) ({site_filter})"
    url = (
        f"https://news.google.com/rss/search?q={quote_plus(full_q)}"
        "&hl=en-GB&gl=GB&ceid=GB:en"
    )
    raw_bytes = _http_get_bytes(url)
    if not raw_bytes:
        return []

    parsed = feedparser.parse(raw_bytes)
    articles: list[dict[str, Any]] = []
    for entry in (parsed.entries or [])[:10]:
        title = str(entry.get("title") or "").strip()
        link = str(entry.get("link") or "").strip()
        source_obj = entry.get("source", {}) or {}
        source_name = str(source_obj.get("title") or "").strip()
        if not source_name and " - " in title:
            parts = title.rsplit(" - ", 1)
            title = parts[0].strip()
            source_name = parts[1].strip()
        if not source_name:
            source_name = "RSS News"

        pub_raw = str(entry.get("published") or "")
        pub_dt: datetime | None = None
        pub_str = "Gần đây"
        if pub_raw:
            try:
                pub_dt = parsedate_to_datetime(pub_raw)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                pub_str = pub_dt.astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M")
            except Exception:
                pub_str = pub_raw[:25]

        snippet = _clean_html_snippet(str(entry.get("summary") or ""), max_len=180)
        articles.append(
            {
                "title": title,
                "source": source_name,
                "published_str": pub_str,
                "published_ts": pub_dt.timestamp() if pub_dt else 0.0,
                "snippet": snippet,
                "link": link,
            }
        )
    return articles


def fetch_uefa_rss_news(
    home_name: str,
    away_name: str,
    league_code: str,
    max_articles: int = 8,
) -> list[dict[str, Any]]:
    """
    Kéo song song Google News RSS từ các đầu báo châu Âu uy tín cho cả 2 đội.
    Trả về tối đa 8 bài mới nhất, snippet rút gọn <= 180 ký tự.
    """
    comp_kw = "Champions League" if league_code == "UCL" else "Europa League"
    queries = [
        f'"{home_name}" "{away_name}" {comp_kw}',
        f'"{home_name}" {comp_kw} injury OR suspended OR squad OR press conference',
        f'"{away_name}" {comp_kw} injury OR suspended OR squad OR press conference',
    ]

    collected: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = [pool.submit(_fetch_single_rss_query, q) for q in queries]
        try:
            for fut in as_completed(futs, timeout=7):
                try:
                    collected.extend(fut.result())
                except Exception:
                    pass
        except Exception:
            pass

    dedup: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    collected.sort(key=lambda x: x["published_ts"], reverse=True)
    for art in collected:
        key = normalize_text(art["title"])[:65]
        if not key or key in seen_titles:
            continue
        seen_titles.add(key)
        dedup.append(art)
        if len(dedup) >= max_articles:
            break

    return dedup


# ==============================================================================
# 7. BỘ ĐIỀU PHỐI PHÂN TÍCH TỔNG THỂ (FULL & FAST T-75)
# ==============================================================================
def analyze_match(
    fixture: dict[str, Any],
    include_rss: bool = True,
) -> dict[str, Any]:
    """
    Chạy song song toàn bộ nguồn dữ liệu cho 1 trận UCL/UEL (tổng thời gian 10-20s).
    """
    league_code = fixture["league_code"]
    slug = fixture["slug"]
    event_id = fixture["event_id"]
    home_id = fixture["home_id"]
    away_id = fixture["away_id"]

    summary: dict[str, Any] = {}
    standings: dict[str, Any] = {"table": [], "top8_cutoff": None, "top24_cutoff": None}
    home_roster: dict[str, Any] = {"lines": {}, "active_ids": set(), "active_names": set(), "count": 0}
    away_roster: dict[str, Any] = {"lines": {}, "active_ids": set(), "active_names": set(), "count": 0}
    home_sched: list[dict[str, Any]] = []
    away_sched: list[dict[str, Any]] = []
    rss_articles: list[dict[str, Any]] = []

    url_summary = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary"

    with ThreadPoolExecutor(max_workers=7) as pool:
        f_summary = pool.submit(_http_get_json, url_summary, {"event": event_id})
        f_standings = pool.submit(get_league_standings, league_code)
        f_h_roster = pool.submit(get_team_roster_4_lines, slug, home_id)
        f_a_roster = pool.submit(get_team_roster_4_lines, slug, away_id)
        f_h_sched = pool.submit(get_team_all_comp_schedule, home_id, SEASON_YEAR, True)
        f_a_sched = pool.submit(get_team_all_comp_schedule, away_id, SEASON_YEAR, True)
        f_rss = (
            pool.submit(fetch_uefa_rss_news, fixture["home_name"], fixture["away_name"], league_code, 8)
            if include_rss
            else None
        )

        try:
            summary = f_summary.result(timeout=9)
        except Exception:
            pass
        try:
            standings = f_standings.result(timeout=9)
        except Exception:
            pass
        try:
            home_roster = f_h_roster.result(timeout=9)
        except Exception:
            pass
        try:
            away_roster = f_a_roster.result(timeout=9)
        except Exception:
            pass
        try:
            home_sched = f_h_sched.result(timeout=9)
        except Exception:
            pass
        try:
            away_sched = f_a_sched.result(timeout=9)
        except Exception:
            pass
        if f_rss is not None:
            try:
                rss_articles = f_rss.result(timeout=9)
            except Exception:
                pass

    lineups = extract_lineups_t75(summary, home_id, away_id)
    injuries = extract_injuries_filtered(summary, home_id, away_id, home_roster, away_roster)
    knockout = extract_knockout_context(summary, fixture)

    target_dt_vn = fixture.get("kickoff_dt_vn") or parse_iso_to_vn(fixture.get("date_utc", ""))
    home_sandwich = build_sandwich_schedule(home_sched, event_id, target_dt_vn)
    away_sandwich = build_sandwich_schedule(away_sched, event_id, target_dt_vn)

    home_form = compute_team_form(home_sched, target_dt_vn)
    away_form = compute_team_form(away_sched, target_dt_vn)

    h2h: list[dict[str, Any]] = []
    boxscore_metrics: dict[str, Any] = {
        "home": {"overall": _aggregate_boxscores([]), "home_split": _aggregate_boxscores([]), "away_split": _aggregate_boxscores([])},
        "away": {"overall": _aggregate_boxscores([]), "home_split": _aggregate_boxscores([]), "away_split": _aggregate_boxscores([])},
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_h2h = pool.submit(extract_h2h_with_fallback, summary, home_id, away_id, home_sched)
        f_box = pool.submit(
            compute_advanced_boxscore_metrics,
            home_form["completed_for_boxscore"],
            home_id,
            away_form["completed_for_boxscore"],
            away_id,
        )
        try:
            h2h = f_h2h.result(timeout=10)
        except Exception:
            pass
        try:
            boxscore_metrics = f_box.result(timeout=10)
        except Exception:
            pass

    home_standing = next((r for r in standings.get("table", []) if r["team_id"] == home_id), None)
    away_standing = next((r for r in standings.get("table", []) if r["team_id"] == away_id), None)

    return {
        "generated_at_vn": fmt_vn_time(datetime.now(VN_TZ)),
        "fixture": fixture,
        "lineups": lineups,
        "injuries": injuries,
        "key_players": {
            "home": home_roster.get("lines", {}),
            "away": away_roster.get("lines", {}),
        },
        "standings": standings,
        "home_standing": home_standing,
        "away_standing": away_standing,
        "knockout": knockout,
        "h2h": h2h,
        "form": {
            "home": home_form,
            "away": away_form,
        },
        "boxscore": boxscore_metrics,
        "sandwich": {
            "home": home_sandwich,
            "away": away_sandwich,
        },
        "rss_articles": rss_articles,
    }


def get_fast_t75_snapshot(
    fixture: dict[str, Any],
    standings_cache: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Bản nhẹ siêu tốc dành riêng cho GitHub Actions quét T-70..T-30:
    Chỉ kéo Summary (đội hình T-75 + chấn thương đã lọc) + Standings. KHÔNG gọi Gemini AI.
    """
    league_code = fixture["league_code"]
    slug = fixture["slug"]
    event_id = fixture["event_id"]
    home_id = fixture["home_id"]
    away_id = fixture["away_id"]

    url_summary = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary"
    summary: dict[str, Any] = {}
    home_roster: dict[str, Any] = {"lines": {}, "active_ids": set(), "active_names": set(), "count": 0}
    away_roster: dict[str, Any] = {"lines": {}, "active_ids": set(), "active_names": set(), "count": 0}

    with ThreadPoolExecutor(max_workers=3) as pool:
        f_sum = pool.submit(_http_get_json, url_summary, {"event": event_id})
        f_hr = pool.submit(get_team_roster_4_lines, slug, home_id)
        f_ar = pool.submit(get_team_roster_4_lines, slug, away_id)
        try:
            summary = f_sum.result(timeout=8)
        except Exception:
            pass
        try:
            home_roster = f_hr.result(timeout=8)
        except Exception:
            pass
        try:
            away_roster = f_ar.result(timeout=8)
        except Exception:
            pass

    standings = (
        standings_cache.get(league_code)
        if standings_cache and league_code in standings_cache
        else get_league_standings(league_code)
    )
    lineups = extract_lineups_t75(summary, home_id, away_id)
    injuries = extract_injuries_filtered(summary, home_id, away_id, home_roster, away_roster)
    knockout = extract_knockout_context(summary, fixture)

    home_standing = next((r for r in standings.get("table", []) if r["team_id"] == home_id), None)
    away_standing = next((r for r in standings.get("table", []) if r["team_id"] == away_id), None)

    return {
        "fixture": fixture,
        "lineups": lineups,
        "injuries": injuries,
        "knockout": knockout,
        "home_standing": home_standing,
        "away_standing": away_standing,
        "has_confirmed_lineups": lineups["home"]["confirmed"] or lineups["away"]["confirmed"],
    }
