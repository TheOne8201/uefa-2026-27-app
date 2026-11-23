# -*- coding: utf-8 -*-
"""
UEFA 2026/2027 Web App (UCL & UEL) - Streamlit Community Cloud (Python 3.11)
100% Real Data (ESPN API + Trusted Google News RSS). Zero Understat. Zero hardcoded secrets.
"""

from __future__ import annotations

import os
import re
from typing import Any

import pandas as pd
import streamlit as st

from ai_and_export import (
    build_word_report,
    format_full_telegram_report,
    send_telegram_message,
    summarize_uefa_rss_with_ai,
)
from data_engine import (
    LEAGUES,
    analyze_match,
    find_team_next_match,
    get_league_teams,
    get_upcoming_fixtures,
)

# ==============================================================================
# CẤU HÌNH TRANG & ĐỌC SECRETS AN TOÀN
# ==============================================================================
st.set_page_config(
    page_title="UEFA 2026/27 — Phân tích UCL & UEL",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _get_secret(key: str, default: str = "") -> str:
    try:
        if key in st.secrets:
            return str(st.secrets[key]).strip()
    except Exception:
        pass
    return os.environ.get(key, default).strip()


# ==============================================================================
# KHÓA MẬT KHẨU CÁ NHÂN (APP_PASSWORD)
# ==============================================================================
def _require_password() -> None:
    app_pwd = _get_secret("APP_PASSWORD")
    if not app_pwd:
        st.error(
            "Chưa cấu hình biến APP_PASSWORD trong Streamlit Secrets. "
            "Vui lòng thiết lập mật khẩu để bảo vệ Web App."
        )
        st.stop()

    if st.session_state.get("authenticated") is True:
        return

    st.markdown("## 🔒 Đăng nhập Hệ thống Phân tích UEFA 2026/2027")
    st.caption("Dữ liệu thực tế 100% cho UEFA Champions League (UCL) & UEFA Europa League (UEL).")
    with st.form("login_form"):
        entered = st.text_input("Nhập mật khẩu cá nhân:", type="password")
        submitted = st.form_submit_button("Mở khóa hệ thống", type="primary")
    if submitted:
        if entered == app_pwd:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Mật khẩu chưa chính xác. Vui lòng thử lại.")
    st.stop()


_require_password()


# ==============================================================================
# CACHE DỮ LIỆU (XÓA NHANH BẰNG NÚT LÀM MỚI ĐỂ CẬP NHẬT T-75)
# ==============================================================================
@st.cache_data(ttl=300, show_spinner=False)
def cached_upcoming_fixtures(league_code: str) -> list[dict[str, Any]]:
    return get_upcoming_fixtures(league_code)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_league_teams(league_code: str) -> list[dict[str, str]]:
    return get_league_teams(league_code)


@st.cache_data(ttl=180, show_spinner=False)
def cached_match_analysis(event_id: str, fixture_payload: dict[str, Any]) -> dict[str, Any]:
    _ = event_id
    return analyze_match(fixture_payload, include_rss=True)


# Khởi tạo lịch sử phiên làm việc
if "report_history" not in st.session_state:
    st.session_state["report_history"] = []
if "active_entry" not in st.session_state:
    st.session_state["active_entry"] = None


# ==============================================================================
# THANH ĐIỀU KHIỂN BÊN TRÁI (SIDEBAR)
# ==============================================================================
with st.sidebar:
    st.title("🏆 UEFA 2026/2027")
    st.caption("UCL & UEL • Dữ liệu thực tế ESPN & RSS")

    league_code = st.selectbox(
        "1. Chọn giải đấu:",
        options=["UCL", "UEL"],
        format_func=lambda c: LEAGUES[c]["name"],
    )

    select_mode = st.radio(
        "2. Cách chọn cặp đấu:",
        options=["Trận đấu sắp tới (Mặc định)", "Tìm theo Tên đội bóng"],
        index=0,
    )

    selected_fixture: dict[str, Any] | None = None

    if select_mode == "Trận đấu sắp tới (Mặc định)":
        fixtures = cached_upcoming_fixtures(league_code)
        if not fixtures:
            st.warning("Hiện chưa có lịch thi đấu sắp tới trên ESPN cho giải này.")
        else:
            # Ưu tiên đưa trận chưa đá / đang đá lên trước
            ordered_fx = [f for f in fixtures if f["status_state"] in ("pre", "in")] + [
                f for f in fixtures if f["status_state"] == "post"
            ]
            labels = [f["display_label"] for f in ordered_fx]
            chosen_idx = st.selectbox(
                "3. Chọn cặp đấu (Giờ VN GMT+7):",
                options=list(range(len(ordered_fx))),
                format_func=lambda i: labels[i],
            )
            selected_fixture = ordered_fx[chosen_idx]
    else:
        teams = cached_league_teams(league_code)
        team_names = [t["name"] for t in teams]
        if team_names:
            chosen_team = st.selectbox("3. Chọn đội bóng:", options=team_names)
        else:
            chosen_team = st.text_input("3. Nhập tên đội bóng (VD: Real, Arsenal, Roma):")

        if chosen_team:
            selected_fixture = find_team_next_match(chosen_team, preferred_league=league_code)
            if selected_fixture:
                st.info(
                    f"Trận kế tiếp: **{selected_fixture['home_name']} vs "
                    f"{selected_fixture['away_name']}**\n\n🕒 {selected_fixture['kickoff_vn']}"
                )
            else:
                st.warning(f"Chưa tìm thấy trận đấu nào gần đây của {chosen_team} tại {league_code}.")

    col_btn1, col_btn2 = st.columns(2)
    run_analyze = col_btn1.button("🔍 Phân tích", type="primary", use_container_width=True)
    run_refresh = col_btn2.button("🔄 Làm mới", use_container_width=True, help="Xóa cache để cập nhật đội hình T-75")

    st.divider()
    st.caption(f"📚 Lịch sử phiên: **{len(st.session_state['report_history'])}** báo cáo")
    if st.button("🚪 Đăng xuất", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()


def _execute_analysis(fixture: dict[str, Any]) -> None:
    gemini_key = _get_secret("GEMINI_API_KEY")
    with st.spinner("Đang kéo dữ liệu song song từ ESPN (T-75, BXH, Boxscore, Bánh mì kẹp, H2H) & RSS..."):
        report = cached_match_analysis(fixture["event_id"], fixture)
    with st.spinner("Đang tổng hợp tin họp báo & pháp lý UEFA từ các đầu báo RSS uy tín..."):
        ai_summary = summarize_uefa_rss_with_ai(fixture, report["rss_articles"], gemini_key)
    docx_bytes = build_word_report(report, ai_summary)

    entry = {
        "key": f"{fixture['event_id']}_{report['generated_at_vn']}",
        "label": f"[{fixture['league_code']}] {fixture['home_name']} vs {fixture['away_name']} ({report['generated_at_vn']})",
        "report": report,
        "ai_summary": ai_summary,
        "docx_bytes": docx_bytes,
    }
    st.session_state["active_entry"] = entry
    st.session_state["report_history"].insert(0, entry)
    st.session_state["report_history"] = st.session_state["report_history"][:20]


if run_refresh:
    st.cache_data.clear()
    if selected_fixture:
        _execute_analysis(selected_fixture)
        st.toast("Đã xóa cache và tải lại dữ liệu T-75 mới nhất!", icon="✅")
    else:
        st.rerun()

if run_analyze:
    if selected_fixture:
        _execute_analysis(selected_fixture)
    else:
        st.sidebar.error("Vui lòng chọn một cặp đấu hợp lệ trước khi bấm Phân tích.")


# ==============================================================================
# HIỂN THỊ NỘI DUNG CHÍNH (5 TAB RÕ RÀNG)
# ==============================================================================
active = st.session_state.get("active_entry")
if not active:
    st.title("🏆 Hệ thống Phân tích Cúp châu Âu UEFA 2026/2027")
    st.info(
        "Chọn giải đấu (**UCL** hoặc **UEL**) và cặp đấu ở cột bên trái, sau đó bấm **Phân tích** "
        "để kéo dữ liệu thực tế từ ESPN và báo chí RSS uy tín trong khoảng 10–20 giây."
    )
    st.stop()

report = active["report"]
ai_summary = active["ai_summary"]
fx = report["fixture"]
home_name = fx["home_name"]
away_name = fx["away_name"]

# Thanh tiêu đề trận đấu
st.markdown(f"### 🏆 {fx['league_name']} — {home_name} vs {away_name}")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Giờ bóng lăn (VN)", fx["kickoff_vn"].replace(" (GMT+7)", ""))
m2.metric("Giai đoạn", report["knockout"]["stage_label"])
m3.metric("Sân vận động", fx["venue"][:30])
m4.metric("Cập nhật lúc", report["generated_at_vn"].split(" ")[0])

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "1️⃣ Nhân sự, Pháp lý & T-75",
        "2️⃣ Cục diện Bảng đấu",
        "3️⃣ Phong độ, H2H & Hiệu suất",
        "4️⃣ Thế Bánh mì kẹp",
        "5️⃣ Xuất Word, Telegram & Lịch sử",
    ]
)


# ------------------------------------------------------------------------------
# TAB 1: NHÂN SỰ, PHÁP LÝ UEFA & ĐỘI HÌNH T-75
# ------------------------------------------------------------------------------
with tab1:
    st.subheader("Đội hình ra sân chính thức (T-75 trước giờ bóng lăn)")
    c_h, c_a = st.columns(2)

    for col, side_key, team_title in ((c_h, "home", home_name), (c_a, "away", away_name)):
        with col:
            lu = report["lineups"][side_key]
            st.markdown(f"#### {team_title}")
            if lu["confirmed"]:
                st.success(f"Đã công bố đội hình chính thức — Sơ đồ: **{lu['formation'] or 'Đang cập nhật'}**")
                df_xi = pd.DataFrame(
                    [
                        {"Số áo": p["jersey"], "Cầu thủ": p["name"], "Vị trí": p["pos"]}
                        for p in lu["starters"]
                    ]
                )
                st.dataframe(df_xi, use_container_width=True, hide_index=True)
                if lu["subs"]:
                    with st.expander(f"Danh sách dự bị ({len(lu['subs'])} cầu thủ)"):
                        st.write(", ".join(f"#{p['jersey']} {p['name']} ({p['pos']})" for p in lu["subs"]))
            else:
                st.warning("Chưa công bố đội hình chính thức T-75 trên ESPN. Bấm nút **Làm mới** sát giờ đá để cập nhật.")

            st.markdown("**Chấn thương / Treo giò (đã lọc cầu thủ chuyển nhượng/cho mượn):**")
            injs = report["injuries"][side_key]
            if injs:
                df_inj = pd.DataFrame(
                    [
                        {
                            "Cầu thủ": i["name"],
                            "Vị trí": i["pos"],
                            "Trạng thái": i["status"],
                            "Chi tiết": i["detail"],
                        }
                        for i in injs
                    ]
                )
                st.dataframe(df_inj, use_container_width=True, hide_index=True)
            else:
                st.caption("Chưa ghi nhận ca chấn thương hoặc treo giò nào trên ESPN.")

    st.divider()
    st.subheader("Nhóm trụ cột 4 tuyến mùa 2026/27 (ESPN Roster)")
    kp_c1, kp_c2 = st.columns(2)
    for col, side_key, team_title in ((kp_c1, "home", home_name), (kp_c2, "away", away_name)):
        with col:
            st.markdown(f"**{team_title}**")
            rows_kp = []
            for line_lbl in ("Thủ môn", "Hậu vệ", "Tiền vệ", "Tiền đạo"):
                for p in report["key_players"][side_key].get(line_lbl, []):
                    rows_kp.append(
                        {
                            "Tuyến": line_lbl,
                            "Cầu thủ": p["name"],
                            "Số trận": p["appearances"],
                            "Bàn thắng": p["goals"],
                            "Kiến tạo": p["assists"],
                        }
                    )
            if rows_kp:
                st.dataframe(pd.DataFrame(rows_kp), use_container_width=True, hide_index=True)
            else:
                st.caption("Chưa có dữ liệu thống kê đội hình mùa 2026/27 trên ESPN.")

    st.divider()
    st.subheader("Họp báo HLV, Pháp lý UEFA, Mốc thẻ & Phòng thay đồ (Nguồn RSS uy tín)")
    st.caption(f"Trạng thái xử lý: **{ai_summary.get('model_used')}** — {ai_summary.get('status_note')}")
    st.markdown(ai_summary.get("text", ""))

    if report["rss_articles"]:
        with st.expander(f"Xem danh sách {len(report['rss_articles'])} bài báo RSS gốc đã thu thập"):
            for idx, art in enumerate(report["rss_articles"], start=1):
                st.markdown(
                    f"{idx}. **[{art['source']} - {art['published_str']}]** [{art['title']}]({art['link']})\n"
                    f"   _{art['snippet']}_"
                )


# ------------------------------------------------------------------------------
# TAB 2: CỤC DIỆN BẢNG ĐẤU & ĐỘNG LỰC THI ĐẤU
# ------------------------------------------------------------------------------
with tab2:
    ko = report["knockout"]
    if ko["is_knockout"]:
        st.error(
            f"🔥 **VÒNG KNOCK-OUT:** {ko['round_detail']} | "
            f"**Lượt đấu:** {ko['leg_info'] or 'Đang cập nhật'} | "
            f"**Tổng tỷ số / Bối cảnh:** {ko['aggregate_summary'] or 'Trận lượt đi hoặc chưa có tổng tỷ số'}"
        )
    else:
        st.info(f"📌 **Giai đoạn:** {ko['stage_label']} — {ko['round_detail']}")

    st.subheader("Vị thế & Động lực của 2 đội")
    top8_cut = report["standings"].get("top8_cutoff")
    top24_cut = report["standings"].get("top24_cutoff")
    st.caption(
        f"Mốc điểm hiện tại: **Top 8 đi thẳng Vòng 1/8** = {top8_cut if top8_cut is not None else 'N/A'}đ | "
        f"**Hạng 9–24 đá Play-off** = {top24_cut if top24_cut is not None else 'N/A'}đ | **Hạng 25–36** = Nhóm bị loại"
    )

    sc1, sc2 = st.columns(2)
    for col, team_title, st_row in (
        (sc1, home_name, report.get("home_standing")),
        (sc2, away_name, report.get("away_standing")),
    ):
        with col:
            if st_row:
                st.markdown(f"#### {team_title} — Hạng #{st_row['rank']}")
                st.write(
                    f"**Điểm:** {st_row['points']}đ ({st_row['played']} trận: "
                    f"{st_row['wins']}T-{st_row['draws']}H-{st_row['losses']}B) | "
                    f"**Hiệu số:** {st_row['gd']:+d} ({st_row['gf']}:{st_row['ga']})"
                )
                st.success(f"Phân vùng động lực: **{st_row['zone']}**")
            else:
                st.warning(f"{team_title}: Chưa có dữ liệu vị trí trên bảng xếp hạng League Phase ESPN.")

    st.divider()
    st.subheader("Bảng xếp hạng League Phase 36 đội (ESPN Standings)")
    table_rows = report["standings"].get("table", [])
    if table_rows:
        df_st = pd.DataFrame(
            [
                {
                    "Hạng": r["rank"],
                    "Đội bóng": (
                        f"👉 {r['team_name']}"
                        if r["team_id"] in (fx["home_id"], fx["away_id"])
                        else r["team_name"]
                    ),
                    "Trận": r["played"],
                    "T": r["wins"],
                    "H": r["draws"],
                    "B": r["losses"],
                    "BT": r["gf"],
                    "BB": r["ga"],
                    "HS": r["gd"],
                    "Điểm": r["points"],
                    "Phân vùng": r["zone"],
                }
                for r in table_rows
            ]
        )

        def _highlight_match_teams(row: pd.Series) -> list[str]:
            if str(row["Đội bóng"]).startswith("👉"):
                return ["background-color: #fff3cd; font-weight: bold; color: #000000"] * len(row)
            return [""] * len(row)

        st.dataframe(
            df_st.style.apply(_highlight_match_teams, axis=1),
            use_container_width=True,
            hide_index=True,
            height=520,
        )
    else:
        st.caption("Chưa lấy được bảng xếp hạng 36 đội từ ESPN.")


# ------------------------------------------------------------------------------
# TAB 3: PHONG ĐỘ, ĐỐI ĐẦU (H2H) & HIỆU SUẤT ESPN BOXSCORE
# ------------------------------------------------------------------------------
with tab3:
    st.subheader("Lịch sử đối đầu H2H (Tối đa 5 lần gần nhất)")
    if report["h2h"]:
        df_h2h = pd.DataFrame(
            [
                {
                    "Ngày": m["date_vn"],
                    "Giải đấu": m["league"],
                    "Chủ nhà": m["home_name"],
                    "Tỷ số": m["score"],
                    "Đội khách": m["away_name"],
                }
                for m in report["h2h"]
            ]
        )
        st.dataframe(df_h2h, use_container_width=True, hide_index=True)
    else:
        st.info("Chưa có dữ liệu đối đầu gần đây.")

    st.divider()
    st.subheader("Phong độ 5 trận gần nhất & Tỷ lệ thắng cách biệt từ 2 bàn trở lên")
    fc1, fc2 = st.columns(2)
    for col, side_key, team_title in ((fc1, "home", home_name), (fc2, "away", away_name)):
        with col:
            f_data = report["form"][side_key]
            st.markdown(f"#### {team_title}")
            rows_f = []
            for lbl, bucket_key in (
                ("Cúp châu Âu (5 trận)", "euro_5"),
                ("Mọi đấu trường (5 trận)", "all_5"),
                ("Sân nhà (5 trận)", "home_5"),
                ("Sân khách (5 trận)", "away_5"),
            ):
                b = f_data[bucket_key]
                rows_f.append(
                    {
                        "Phạm vi": lbl,
                        "Chuỗi": b["form_str"],
                        "Thành tích": b["record"],
                        "BT:BB": f"{b['gf']}:{b['ga']}",
                        "Thắng >=2 bàn": f"{b['win_by_2_count']}/{b['count']} ({b['win_by_2_pct']}%)",
                    }
                )
            st.dataframe(pd.DataFrame(rows_f), use_container_width=True, hide_index=True)

            w2_all = f_data["all_5"]["win_by_2_list"]
            if w2_all:
                st.caption("Trận thắng cách biệt >= 2 bàn gần nhất: " + " | ".join(w2_all))
            else:
                st.caption("Không có trận thắng cách biệt >= 2 bàn trong 5 trận mọi đấu trường gần nhất.")

    st.divider()
    st.subheader("Hiệu suất trận đấu từ ESPN Boxscore & KeyEvents (100% số thật, không dùng xG)")
    bh_all = report["boxscore"]["home"]["overall"]
    bh_home = report["boxscore"]["home"]["home_split"]
    ba_all = report["boxscore"]["away"]["overall"]
    ba_away = report["boxscore"]["away"]["away_split"]

    df_box = pd.DataFrame(
        [
            {
                "Chỉ số thực tế ESPN": "Số trận mẫu Boxscore",
                f"{home_name} (Tổng)": f"{bh_all['sample_size']} trận",
                f"{home_name} (Sân nhà)": f"{bh_home['sample_size']} trận",
                f"{away_name} (Tổng)": f"{ba_all['sample_size']} trận",
                f"{away_name} (Sân khách)": f"{ba_away['sample_size']} trận",
            },
            {
                "Chỉ số thực tế ESPN": "Số cú sút TB/trận",
                f"{home_name} (Tổng)": bh_all["shots_avg"],
                f"{home_name} (Sân nhà)": bh_home["shots_avg"],
                f"{away_name} (Tổng)": ba_all["shots_avg"],
                f"{away_name} (Sân khách)": ba_away["shots_avg"],
            },
            {
                "Chỉ số thực tế ESPN": "Sút trúng đích (SoT) TB/trận",
                f"{home_name} (Tổng)": bh_all["sot_avg"],
                f"{home_name} (Sân nhà)": bh_home["sot_avg"],
                f"{away_name} (Tổng)": ba_all["sot_avg"],
                f"{away_name} (Sân khách)": ba_away["sot_avg"],
            },
            {
                "Chỉ số thực tế ESPN": "Hiệu số SoT TB/trận",
                f"{home_name} (Tổng)": f"{bh_all['sot_diff_avg']:+.2f}",
                f"{home_name} (Sân nhà)": f"{bh_home['sot_diff_avg']:+.2f}",
                f"{away_name} (Tổng)": f"{ba_all['sot_diff_avg']:+.2f}",
                f"{away_name} (Sân khách)": f"{ba_away['sot_diff_avg']:+.2f}",
            },
            {
                "Chỉ số thực tế ESPN": "Tỷ lệ chuyển hóa Bàn/SoT (%)",
                f"{home_name} (Tổng)": f"{bh_all['conversion_pct']}%",
                f"{home_name} (Sân nhà)": f"{bh_home['conversion_pct']}%",
                f"{away_name} (Tổng)": f"{ba_all['conversion_pct']}%",
                f"{away_name} (Sân khách)": f"{ba_away['conversion_pct']}%",
            },
            {
                "Chỉ số thực tế ESPN": "Phạt góc TB/trận",
                f"{home_name} (Tổng)": bh_all["corners_avg"],
                f"{home_name} (Sân nhà)": bh_home["corners_avg"],
                f"{away_name} (Tổng)": ba_all["corners_avg"],
                f"{away_name} (Sân khách)": ba_away["corners_avg"],
            },
            {
                "Chỉ số thực tế ESPN": "Kiểm soát bóng TB (%)",
                f"{home_name} (Tổng)": f"{bh_all['possession_avg']}%",
                f"{home_name} (Sân nhà)": f"{bh_home['possession_avg']}%",
                f"{away_name} (Tổng)": f"{ba_all['possession_avg']}%",
                f"{away_name} (Sân khách)": f"{ba_away['possession_avg']}%",
            },
        ]
    )
    st.dataframe(df_box, use_container_width=True, hide_index=True)

    st.markdown("**Phân loại bàn thắng / bàn thua theo tình huống (ESPN KeyEvents):**")
    g_types = ["Bóng sống", "Phạt góc", "Đá phạt", "Phạt đền", "Phản lưới"]
    df_goals = pd.DataFrame(
        [
            {
                "Tình huống": gt,
                f"Bàn thắng {home_name}": bh_all["goals_for_types"].get(gt, 0),
                f"Bàn thua {home_name}": bh_all["goals_against_types"].get(gt, 0),
                f"Bàn thắng {away_name}": ba_all["goals_for_types"].get(gt, 0),
                f"Bàn thua {away_name}": ba_all["goals_against_types"].get(gt, 0),
            }
            for gt in g_types
        ]
    )
    st.dataframe(df_goals, use_container_width=True, hide_index=True)


# ------------------------------------------------------------------------------
# TAB 4: THẾ "BÁNH MÌ KẸP" (LỊCH 4–7 NGÀY TRƯỚC & SAU TRẬN)
# ------------------------------------------------------------------------------
with tab4:
    st.subheader("Thế 'Bánh mì kẹp' — Lịch thi đấu đa giải trước & sau trận 4–7 ngày")
    sw_c1, sw_c2 = st.columns(2)

    for col, side_key, team_title in ((sw_c1, "home", home_name), (sw_c2, "away", away_name)):
        with col:
            sw = report["sandwich"][side_key]
            st.markdown(f"#### {team_title}")
            lvl = sw["warning_level"]
            if "ĐỎ" in lvl:
                st.error(f"🚨 **{lvl}**\n\n{sw['warning_detail']}")
            elif "VÀNG" in lvl:
                st.warning(f"⚠️ **{lvl}**\n\n{sw['warning_detail']}")
            else:
                st.success(f"✅ **{lvl}**\n\n{sw['warning_detail']}")

            st.markdown("**Trận VĐQG / Cúp QG vừa đá TRƯỚC trận Cúp châu Âu:**")
            if sw["before"]:
                df_b = pd.DataFrame(
                    [
                        {
                            "Ngày giờ (VN)": m["kickoff_vn"].replace(" (GMT+7)", ""),
                            "Nghỉ": f"{m['gap_days']} ngày",
                            "Giải": m["league_name"],
                            "Sân": m["venue_tag"],
                            "Đối thủ": m["opponent_name"],
                            "Tỷ số": f"{m['home_score']}-{m['away_score']}" if m["home_score"] is not None else "Chưa rõ",
                        }
                        for m in sw["before"]
                    ]
                )
                st.dataframe(df_b, use_container_width=True, hide_index=True)
            else:
                st.caption("Không có trận nào trong vòng 7 ngày trước trận trên lịch đa giải ESPN.")

            st.markdown("**Trận VĐQG / Cúp QG phải đá SAU trận Cúp châu Âu:**")
            if sw["after"]:
                df_a = pd.DataFrame(
                    [
                        {
                            "Ngày giờ (VN)": m["kickoff_vn"].replace(" (GMT+7)", ""),
                            "Nghỉ": f"{m['gap_days']} ngày",
                            "Giải": m["league_name"],
                            "Sân": m["venue_tag"],
                            "Đối thủ": m["opponent_name"],
                        }
                        for m in sw["after"]
                    ]
                )
                st.dataframe(df_a, use_container_width=True, hide_index=True)
            else:
                st.caption("Không có trận nào trong vòng 7 ngày sau trận trên lịch đa giải ESPN.")

    st.divider()
    st.markdown("**Lưu ý Di chuyển / Mặt sân / Thời tiết từ báo chí RSS:**")
    travel_note = ""
    for line in (ai_summary.get("text") or "").splitlines():
        if "di chuyển" in line.lower() or "mặt sân" in line.lower():
            travel_note = line
            break
    st.write(travel_note or "Chưa ghi nhận thông tin mới về di chuyển hoặc mặt sân trong các nguồn RSS.")


# ------------------------------------------------------------------------------
# TAB 5: XUẤT WORD (.DOCX), GỬI TELEGRAM & LỊCH SỬ PHIÊN
# ------------------------------------------------------------------------------
with tab5:
    st.subheader("Xuất báo cáo Microsoft Word (.docx) & Gửi sang Telegram")
    safe_file = re.sub(r"[^a-zA-Z0-9_-]+", "_", f"{fx['league_code']}_{home_name}_vs_{away_name}")
    filename = f"{safe_file}.docx"

    ex_c1, ex_c2 = st.columns(2)
    with ex_c1:
        st.download_button(
            label="📥 Tải báo cáo Word (.docx) chuẩn bảng biểu",
            data=active["docx_bytes"],
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary",
            use_container_width=True,
        )

    with ex_c2:
        if st.button("✈️ Gửi báo cáo sang Telegram cá nhân", use_container_width=True):
            tg_token = _get_secret("TELEGRAM_BOT_TOKEN")
            tg_chat = _get_secret("TELEGRAM_CHAT_ID")
            msg_html = format_full_telegram_report(report, ai_summary)
            ok, info_msg = send_telegram_message(tg_token, tg_chat, msg_html)
            if ok:
                st.success(f"Đã gửi báo cáo sang Telegram! ({info_msg})")
            else:
                st.error(info_msg)

    st.divider()
    st.subheader("Lịch sử báo cáo đã chạy trong phiên làm việc")
    history = st.session_state.get("report_history", [])
    if len(history) <= 1:
        st.caption("Mới có 1 báo cáo trong phiên hiện tại. Khi bạn phân tích thêm các trận khác, danh sách sẽ hiện ở đây để mở lại tức thì.")
    else:
        for idx, item in enumerate(history):
            hc1, hc2 = st.columns([4, 1])
            hc1.write(f"**{idx + 1}.** {item['label']}")
            if hc2.button("Mở lại", key=f"open_hist_{idx}", use_container_width=True):
                st.session_state["active_entry"] = item
                st.rerun()
