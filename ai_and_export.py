# -*- coding: utf-8 -*-
"""
UEFA 2026/2027 AI Summarizer, Word (.docx) Exporter & Telegram Formatter/Sender
SDK: google-genai (>=1.0.0), NO Google Search Grounding.
Fallback chain: gemini-2.5-flash -> gemini-2.5-flash-lite -> gemini-flash-latest -> gemini-2.0-flash -> Raw RSS.
Zero hardcoded secrets.
"""

from __future__ import annotations

import html
import io
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any

import requests
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from google import genai
from google.genai import types

# ==============================================================================
# CẤU HÌNH GEMINI API CHUẨN (CHỐNG 404 & CHỐNG CẮT TIMEOUT SỚM)
# ==============================================================================
MODEL_FALLBACK_CHAIN = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-2.0-flash",
]
MODEL_TIMEOUT_SECONDS = 25
TELEGRAM_HTTP_TIMEOUT = (4, 7)


def _clean_rss_text(raw: str) -> str:
    """Giải mã ký tự HTML (&nbsp;, &amp;...) và chuẩn hóa khoảng trắng."""
    unescaped = html.unescape(raw or "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", unescaped).strip()


def _format_raw_rss_fallback(articles: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    """Hiển thị danh sách tin RSS gốc khi Gemini gặp 429, hết lượt hoặc không có API Key."""
    if not articles:
        body = (
            "Chưa ghi nhận bài báo mới trong các nguồn RSS uy tín (UEFA, BBC, Sky, Guardian, "
            "Reuters, ESPN, Marca, Kicker, Gazzetta) cho cặp đấu này."
        )
    else:
        lines = [f"*(Đang hiển thị danh sách tin RSS gốc — lý do: {reason})*\n"]
        for i, art in enumerate(articles, start=1):
            clean_title = _clean_rss_text(art.get("title", ""))
            clean_snip = _clean_rss_text(art.get("snippet", ""))
            lines.append(
                f"{i}. **[{art['source']} - {art['published_str']}]** {clean_title}\n"
                f"   - Tóm lược: {clean_snip or 'Không có đoạn trích.'}\n"
                f"   - Link: {art['link']}"
            )
        body = "\n".join(lines)

    return {
        "mode": "rss_fallback",
        "model_used": "RSS Gốc (Fallback)",
        "status_note": reason,
        "text": body,
        "articles": articles,
    }


def _call_single_gemini_model(api_key: str, model_name: str, prompt: str) -> str:
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=MODEL_TIMEOUT_SECONDS * 1000),
    )
    resp = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=1100,
        ),
    )
    text = (getattr(resp, "text", None) or "").strip()
    if not text:
        raise ValueError("Gemini returned empty response")
    return text


def summarize_uefa_rss_with_ai(
    fixture: dict[str, Any],
    articles: list[dict[str, Any]],
    api_key: str | None,
) -> dict[str, Any]:
    """
    Tóm tắt tin họp báo HLV, án treo giò mốc thẻ UEFA, cầu thủ không đăng ký UEFA,
    phòng thay đồ và di chuyển/mặt sân từ tối đa 8 bài RSS uy tín.
    CẤM BỊA SỐ, BẮT BUỘC DẪN NGUỒN [Tên nguồn - Ngày đăng].
    """
    trimmed_articles = (articles or [])[:8]
    if not trimmed_articles:
        return {
            "mode": "empty_rss",
            "model_used": "Không có tin RSS",
            "status_note": "Không tìm thấy bài báo mới trong các nguồn RSS uy tín.",
            "text": (
                "- **Họp báo HLV & Tin nóng 24h:** Chưa ghi nhận thông tin mới trong các nguồn RSS\n"
                "- **Án treo giò / Mốc thẻ phạt UEFA:** Chưa ghi nhận thông tin mới trong các nguồn RSS\n"
                "- **Cầu thủ không đăng ký danh sách UEFA / Nhân sự mới:** Chưa ghi nhận thông tin mới trong các nguồn RSS\n"
                "- **Phòng thay đồ & Tâm lý thi đấu:** Chưa ghi nhận thông tin mới trong các nguồn RSS\n"
                "- **Di chuyển / Mặt sân / Thời tiết:** Chưa ghi nhận thông tin mới trong các nguồn RSS"
            ),
            "articles": [],
        }

    if not api_key or not api_key.strip():
        return _format_raw_rss_fallback(trimmed_articles, "Chưa cấu hình GEMINI_API_KEY")

    rss_block_lines = []
    for idx, art in enumerate(trimmed_articles, start=1):
        clean_title = _clean_rss_text(art.get("title", ""))
        snippet = _clean_rss_text(art.get("snippet", ""))[:180]
        rss_block_lines.append(
            f"[{idx}] Nguồn: {art['source']} | Ngày đăng: {art['published_str']} | "
            f"Tiêu đề: {clean_title} | Đoạn trích: {snippet}"
        )
    rss_context = "\n".join(rss_block_lines)

    prompt = f"""Bạn là biên tập viên tổng hợp dữ liệu thực tế cho trận {fixture['league_name']}:
{fixture['home_name']} vs {fixture['away_name']} (giờ đá: {fixture['kickoff_vn']}).

QUY TẮC TUYỆT ĐỐI:
1. CHỈ ĐƯỢC dùng thông tin có trong danh sách bài báo RSS dưới đây. TUYỆT ĐỐI KHÔNG tự nhớ kiến thức cũ, KHÔNG bịa tên cầu thủ, KHÔNG suy diễn.
2. Mọi thông tin trích ra BẮT BUỘC phải ghi kèm trích dẫn đúng dạng [Tên nguồn - Ngày đăng] ở cuối ý.
3. Trình bày ngắn gọn, rõ ràng bằng tiếng Việt theo đúng 5 mục sau. Mục nào KHÔNG có dữ liệu trong danh sách RSS bên dưới thì BẮT BUỘC ghi nguyên văn: "Chưa ghi nhận thông tin mới trong các nguồn RSS".

5 MỤC BẮT BUỘC:
- **Họp báo HLV & Tin nóng 24h:**
- **Án treo giò / Mốc thẻ phạt UEFA:**
- **Cầu thủ không đăng ký danh sách UEFA / Nhân sự mới:**
- **Phòng thay đồ & Tâm lý thi đấu:**
- **Di chuyển / Mặt sân / Thời tiết:**

DANH SÁCH BÀI BÁO RSS UY TÍN:
{rss_context}
"""

    last_error = ""
    for model_name in MODEL_FALLBACK_CHAIN:
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(_call_single_gemini_model, api_key.strip(), model_name, prompt)
            ai_text = future.result(timeout=MODEL_TIMEOUT_SECONDS)
            executor.shutdown(wait=False)
            return {
                "mode": "ai_success",
                "model_used": model_name,
                "status_note": f"Tóm tắt thành công bằng {model_name} từ {len(trimmed_articles)} nguồn RSS uy tín.",
                "text": ai_text,
                "articles": trimmed_articles,
            }
        except FuturesTimeout:
            last_error = f"{model_name} quá thời gian chờ ({MODEL_TIMEOUT_SECONDS}s)"
            executor.shutdown(wait=False)
        except Exception as exc:
            err_msg = str(exc)
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                last_error = f"{model_name} giới hạn lượt (429)"
            elif "404" in err_msg:
                last_error = f"{model_name} không khả dụng (404)"
            else:
                last_error = f"{model_name} lỗi: {err_msg[:90]}"
            executor.shutdown(wait=False)

    return _format_raw_rss_fallback(trimmed_articles, last_error or "Lỗi gọi Gemini API")


# ==============================================================================
# XUẤT BÁO CÁO MICROSOFT WORD (.DOCX) CHUẨN BẢNG BIỂU
# ==============================================================================
def _set_cell_shading(cell: Any, fill_hex: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill_hex)
    tc_pr.append(shd)


def _add_styled_table(doc: Document, headers: list[str], rows: list[list[str]]) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    hdr_cells = table.rows[0].cells
    for i, text in enumerate(headers):
        hdr_cells[i].text = str(text)
        _set_cell_shading(hdr_cells[i], "1F4E79")
        for p in hdr_cells[i].paragraphs:
            for run in p.runs:
                run.bold = True
                run.font.size = Pt(9.5)
                run.font.color.rgb = RGBColor(255, 255, 255)

    for r_idx, row_vals in enumerate(rows):
        row_cells = table.add_row().cells
        bg = "F2F6FA" if r_idx % 2 == 1 else "FFFFFF"
        for i, val in enumerate(row_vals):
            row_cells[i].text = str(val)
            _set_cell_shading(row_cells[i], bg)
            for p in row_cells[i].paragraphs:
                for run in p.runs:
                    run.font.size = Pt(9)


def build_word_report(report: dict[str, Any], ai_summary: dict[str, Any]) -> bytes:
    """Tạo file báo cáo Microsoft Word (.docx) chuẩn bảng biểu, 100% số thật."""
    doc = Document()
    for section in doc.sections:
        section.top_margin = Inches(0.6)
        section.bottom_margin = Inches(0.6)
        section.left_margin = Inches(0.6)
        section.right_margin = Inches(0.6)

    fx = report["fixture"]
    home_name = fx["home_name"]
    away_name = fx["away_name"]

    title = doc.add_heading(f"BÁO CÁO PHÂN TÍCH {fx['league_name'].upper()}", level=0)
    title.runs[0].font.color.rgb = RGBColor(20, 55, 105)

    meta = doc.add_paragraph()
    meta.add_run(f"Cặp đấu: {home_name} vs {away_name}\n").bold = True
    meta.add_run(f"Giờ bóng lăn: {fx['kickoff_vn']} | Sân: {fx['venue']}\n")
    meta.add_run(
        f"Giai đoạn: {report['knockout']['stage_label']} ({report['knockout']['round_detail']})\n"
    )
    meta.add_run(f"Thời điểm xuất dữ liệu: {report['generated_at_vn']} (Nguồn: ESPN API & RSS uy tín)")

    # --- PHẦN 1: NHÂN SỰ, T-75 & BÁO CHÍ ---
    doc.add_heading("1. Nhân sự, Pháp lý UEFA & Đội hình ra sân T-75", level=1)
    lu_h = report["lineups"]["home"]
    lu_a = report["lineups"]["away"]
    h_xi = (
        f"Sơ đồ {lu_h['formation'] or 'N/A'}: "
        + ", ".join(f"#{p['jersey']} {p['name']} ({p['pos']})" for p in lu_h["starters"])
        if lu_h["confirmed"]
        else "Chưa công bố đội hình chính thức T-75 trên ESPN."
    )
    a_xi = (
        f"Sơ đồ {lu_a['formation'] or 'N/A'}: "
        + ", ".join(f"#{p['jersey']} {p['name']} ({p['pos']})" for p in lu_a["starters"])
        if lu_a["confirmed"]
        else "Chưa công bố đội hình chính thức T-75 trên ESPN."
    )
    _add_styled_table(
        doc,
        ["Hạng mục", home_name, away_name],
        [
            ["Đội hình chính thức T-75", h_xi, a_xi],
            [
                "Chấn thương / Treo giò (đã lọc)",
                "\n".join(f"- {i['name']} ({i['pos']}): {i['status']} | {i['detail']}" for i in report["injuries"]["home"])
                or "Chưa ghi nhận ca vắng mặt trên ESPN.",
                "\n".join(f"- {i['name']} ({i['pos']}): {i['status']} | {i['detail']}" for i in report["injuries"]["away"])
                or "Chưa ghi nhận ca vắng mặt trên ESPN.",
            ],
        ],
    )

    doc.add_heading("Nhóm trụ cột 4 tuyến mùa 2026/27 (ESPN Roster)", level=2)
    kp_rows: list[list[str]] = []
    for line_name in ("Thủ môn", "Hậu vệ", "Tiền vệ", "Tiền đạo"):
        h_list = report["key_players"]["home"].get(line_name, [])
        a_list = report["key_players"]["away"].get(line_name, [])
        h_txt = "\n".join(
            f"{p['name']} ({p['appearances']} trận, {p['goals']}B/{p['assists']}KT)"
            for p in h_list
        ) or "Chưa có dữ liệu"
        a_txt = "\n".join(
            f"{p['name']} ({p['appearances']} trận, {p['goals']}B/{p['assists']}KT)"
            for p in a_list
        ) or "Chưa có dữ liệu"
        kp_rows.append([line_name, h_txt, a_txt])
    _add_styled_table(doc, ["Tuyến", home_name, away_name], kp_rows)

    doc.add_heading(f"Tin họp báo, Pháp lý UEFA & Báo chí ({ai_summary.get('model_used', 'RSS')})", level=2)
    for line in (ai_summary.get("text") or "").splitlines():
        if line.strip():
            doc.add_paragraph(line.replace("**", ""))

    # --- PHẦN 2: CỤC DIỆN BẢNG ĐẤU ---
    doc.add_heading("2. Cục diện Bảng đấu League Phase 36 đội & Động lực", level=1)
    ko = report["knockout"]
    if ko["is_knockout"]:
        doc.add_paragraph(
            f"Bối cảnh Knock-out: {ko['round_detail']} | {ko['leg_info'] or 'Đang cập nhật'} | "
            f"Tổng tỷ số: {ko['aggregate_summary'] or 'Chưa có'}"
        )

    hs = report.get("home_standing")
    as_ = report.get("away_standing")
    st_rows = []
    for team_lbl, st in ((home_name, hs), (away_name, as_)):
        if st:
            st_rows.append(
                [
                    team_lbl,
                    f"#{st['rank']}",
                    str(st["played"]),
                    f"{st['wins']}-{st['draws']}-{st['losses']}",
                    f"{st['gf']}:{st['ga']} ({st['gd']:+d})",
                    str(st["points"]),
                    st["zone"],
                ]
            )
        else:
            st_rows.append([team_lbl, "N/A", "-", "-", "-", "-", "Chưa có trên BXH ESPN"])
    _add_styled_table(doc, ["Đội", "Hạng", "Trận", "T-H-B", "BT:BB (HS)", "Điểm", "Phân vùng động lực"], st_rows)

    # --- PHẦN 3: H2H, PHONG ĐỘ & HIỆU SUẤT BOXSCORE ---
    doc.add_heading("3. Đối đầu (H2H), Phong độ 5 trận & Hiệu suất trận đấu (ESPN)", level=1)
    if report["h2h"]:
        h2h_rows = [
            [m["date_vn"], m["league"], f"{m['home_name']} vs {m['away_name']}", m["score"]]
            for m in report["h2h"]
        ]
        _add_styled_table(doc, ["Ngày", "Giải đấu", "Cặp đấu", "Tỷ số"], h2h_rows)
    else:
        doc.add_paragraph("Lịch sử đối đầu H2H: Chưa có dữ liệu đối đầu gần đây.")

    doc.add_heading("Phong độ 5 trận gần nhất & Tỷ lệ thắng cách biệt >= 2 bàn", level=2)
    fh = report["form"]["home"]
    fa = report["form"]["away"]
    form_rows = [
        [
            "Cúp châu Âu (5 trận)",
            f"{fh['euro_5']['form_str']} ({fh['euro_5']['gf']}:{fh['euro_5']['ga']}) | Thắng >=2 bàn: {fh['euro_5']['win_by_2_count']}/{fh['euro_5']['count']} ({fh['euro_5']['win_by_2_pct']}%)",
            f"{fa['euro_5']['form_str']} ({fa['euro_5']['gf']}:{fa['euro_5']['ga']}) | Thắng >=2 bàn: {fa['euro_5']['win_by_2_count']}/{fa['euro_5']['count']} ({fa['euro_5']['win_by_2_pct']}%)",
        ],
        [
            "Mọi đấu trường (5 trận)",
            f"{fh['all_5']['form_str']} ({fh['all_5']['gf']}:{fh['all_5']['ga']}) | Thắng >=2 bàn: {fh['all_5']['win_by_2_count']}/{fh['all_5']['count']} ({fh['all_5']['win_by_2_pct']}%)",
            f"{fa['all_5']['form_str']} ({fa['all_5']['gf']}:{fa['all_5']['ga']}) | Thắng >=2 bàn: {fa['all_5']['win_by_2_count']}/{fa['all_5']['count']} ({fa['all_5']['win_by_2_pct']}%)",
        ],
        [
            "Tách Sân nhà (Chủ) / Sân khách (Khách)",
            f"Sân nhà: {fh['home_5']['form_str']} ({fh['home_5']['gf']}:{fh['home_5']['ga']}) | >=2 bàn: {fh['home_5']['win_by_2_pct']}%",
            f"Sân khách: {fa['away_5']['form_str']} ({fa['away_5']['gf']}:{fa['away_5']['ga']}) | >=2 bàn: {fa['away_5']['win_by_2_pct']}%",
        ],
    ]
    _add_styled_table(doc, ["Phạm vi", home_name, away_name], form_rows)

    doc.add_heading("Hiệu suất nâng cao từ ESPN Boxscore & KeyEvents (Không dùng xG)", level=2)
    bh = report["boxscore"]["home"]["overall"]
    ba = report["boxscore"]["away"]["overall"]
    bh_h = report["boxscore"]["home"]["home_split"]
    ba_a = report["boxscore"]["away"]["away_split"]

    def _fmt_gtypes(d: dict[str, int]) -> str:
        return ", ".join(f"{k}: {v}" for k, v in d.items())

    box_rows = [
        ["Số trận mẫu (Tổng / Sân tương ứng)", f"{bh['sample_size']} trận (Nhà: {bh_h['sample_size']})", f"{ba['sample_size']} trận (Khách: {ba_a['sample_size']})"],
        ["Cú sút TB/trận (Tổng / Tương ứng)", f"{bh['shots_avg']} (Nhà: {bh_h['shots_avg']})", f"{ba['shots_avg']} (Khách: {ba_a['shots_avg']})"],
        ["Sút trúng đích SoT TB/trận", f"{bh['sot_avg']} (Nhà: {bh_h['sot_avg']})", f"{ba['sot_avg']} (Khách: {ba_a['sot_avg']})"],
        ["Hiệu số SoT TB/trận", f"{bh['sot_diff_avg']:+.2f} (Nhà: {bh_h['sot_diff_avg']:+.2f})", f"{ba['sot_diff_avg']:+.2f} (Khách: {ba_a['sot_diff_avg']:+.2f})"],
        ["Tỷ lệ chuyển hóa Bàn/SoT (%)", f"{bh['conversion_pct']}%", f"{ba['conversion_pct']}%"],
        ["Phạt góc TB/trận", f"{bh['corners_avg']} (Nhà: {bh_h['corners_avg']})", f"{ba['corners_avg']} (Khách: {ba_a['corners_avg']})"],
        ["Kiểm soát bóng TB (%)", f"{bh['possession_avg']}% (Nhà: {bh_h['possession_avg']}%)", f"{ba['possession_avg']}% (Khách: {ba_a['possession_avg']}%)"],
        ["Phân loại bàn thắng (KeyEvents)", _fmt_gtypes(bh["goals_for_types"]), _fmt_gtypes(ba["goals_for_types"])],
        ["Phân loại bàn thua (KeyEvents)", _fmt_gtypes(bh["goals_against_types"]), _fmt_gtypes(ba["goals_against_types"])],
    ]
    _add_styled_table(doc, ["Chỉ số thực tế ESPN", home_name, away_name], box_rows)

    # --- PHẦN 4: THẾ BÁNH MÌ KẸP ---
    doc.add_heading("4. Thế 'Bánh mì kẹp' (Lịch 4-7 ngày trước & sau trận)", level=1)
    sh = report["sandwich"]["home"]
    sa = report["sandwich"]["away"]

    def _fmt_sand_list(items: list[dict[str, Any]]) -> str:
        if not items:
            return "Không có trận trong khung 7 ngày"
        lines = []
        for m in items:
            sc = f" [{m['home_score']}-{m['away_score']}]" if m["state"] == "post" and m["home_score"] is not None else ""
            lines.append(
                f"- {m['kickoff_vn']} ({m['gap_days']} ngày): {m['league_name']} | "
                f"{m['venue_tag']} vs {m['opponent_name']}{sc}"
            )
        return "\n".join(lines)

    sand_rows = [
        ["Trận ngay TRƯỚC (3-7 ngày)", _fmt_sand_list(sh["before"]), _fmt_sand_list(sa["before"])],
        ["Trận ngay SAU (3-7 ngày)", _fmt_sand_list(sh["after"]), _fmt_sand_list(sa["after"])],
        ["Cảnh báo mật độ & xoay tua", f"{sh['warning_level']}\n{sh['warning_detail']}", f"{sa['warning_level']}\n{sa['warning_detail']}"],
    ]
    _add_styled_table(doc, ["Hạng mục", home_name, away_name], sand_rows)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


# ==============================================================================
# GỬI & ĐỊNH DẠNG TIN NHẮN TELEGRAM (CHỐNG TRÀN 4096 KÝ TỰ)
# ==============================================================================
def _split_telegram_text(text: str, max_len: int = 3850) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    cur_len = 0
    for line in text.splitlines(keepends=True):
        if cur_len + len(line) > max_len and current:
            chunks.append("".join(current))
            current = [line]
            cur_len = len(line)
        else:
            current.append(line)
            cur_len += len(line)
    if current:
        chunks.append("".join(current))
    return chunks


def send_telegram_message(
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str = "HTML",
) -> tuple[bool, str]:
    """Gửi tin nhắn Telegram an toàn, tự động chia đoạn nếu dài hơn 3850 ký tự."""
    if not bot_token or not chat_id:
        return False, "Thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID."

    url = f"https://api.telegram.org/bot{bot_token.strip()}/sendMessage"
    chunks = _split_telegram_text(text)

    for idx, chunk in enumerate(chunks, start=1):
        payload = {
            "chat_id": str(chat_id).strip(),
            "text": chunk,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        try:
            resp = requests.post(url, json=payload, timeout=TELEGRAM_HTTP_TIMEOUT)
            if resp.status_code != 200:
                if parse_mode == "HTML":
                    payload.pop("parse_mode", None)
                    resp2 = requests.post(url, json=payload, timeout=TELEGRAM_HTTP_TIMEOUT)
                    if resp2.status_code == 200:
                        continue
                return False, f"Telegram lỗi HTTP {resp.status_code} ở phần {idx}: {resp.text[:150]}"
        except Exception as exc:
            return False, f"Lỗi kết nối Telegram ở phần {idx}: {exc}"

    return True, f"Đã gửi thành công ({len(chunks)} tin nhắn)."


def format_full_telegram_report(report: dict[str, Any], ai_summary: dict[str, Any]) -> str:
    """Định dạng báo cáo đầy đủ gửi Telegram cho nút Web App và lệnh /match, /ucl, /uel."""
    fx = report["fixture"]
    esc = html.escape
    h_name = esc(fx["home_name"])
    a_name = esc(fx["away_name"])

    lines = [
        f"🏆 <b>{esc(fx['league_name'])}</b>",
        f"⚽ <b>{h_name} vs {a_name}</b>",
        f"🕒 {esc(fx['kickoff_vn'])} | 🏟 {esc(fx['venue'])}",
        f"📌 {esc(report['knockout']['stage_label'])} — {esc(report['knockout']['round_detail'])}",
    ]
    if report["knockout"]["is_knockout"] and report["knockout"]["aggregate_summary"]:
        lines.append(f"🔁 Tổng tỷ số: {esc(report['knockout']['aggregate_summary'])}")

    # 1. Đội hình T-75
    lines.append("\n<b>1️⃣ ĐỘI HÌNH T-75 & CHẤN THƯƠNG</b>")
    for side_key, team_lbl in (("home", h_name), ("away", a_name)):
        lu = report["lineups"][side_key]
        if lu["confirmed"]:
            xi_str = ", ".join(esc(p["name"]) for p in lu["starters"])
            lines.append(f"✅ <b>{team_lbl}</b> ({esc(lu['formation'] or 'XI')}): {xi_str}")
        else:
            lines.append(f"⏳ <b>{team_lbl}</b>: Chưa công bố đội hình T-75")

        injs = report["injuries"][side_key][:6]
        if injs:
            inj_str = "; ".join(f"{esc(i['name'])} ({esc(i['status'])})" for i in injs)
            lines.append(f"🏥 Vắng/Chấn thương {team_lbl}: {inj_str}")

    # 2. BXH League Phase
    lines.append("\n<b>2️⃣ CỤC DIỆN BXH LEAGUE PHASE</b>")
    for team_lbl, st in ((h_name, report.get("home_standing")), (a_name, report.get("away_standing"))):
        if st:
            lines.append(
                f"• <b>{team_lbl}</b>: Hạng #{st['rank']} | {st['points']}đ ({st['played']} trận, HS {st['gd']:+d}) — {esc(st['zone'])}"
            )
        else:
            lines.append(f"• <b>{team_lbl}</b>: Chưa có vị trí trên BXH ESPN")

    # 3. H2H, Phong độ & Hiệu suất Boxscore
    lines.append("\n<b>3️⃣ H2H, PHONG ĐỘ & HIỆU SUẤT ESPN</b>")
    if report["h2h"]:
        h2h_txt = " | ".join(
            f"{esc(m['date_vn'])}: {esc(m['home_name'])} {esc(m['score'])} {esc(m['away_name'])}"
            for m in report["h2h"][:3]
        )
        lines.append(f"⚔️ H2H gần nhất: {h2h_txt}")
    else:
        lines.append("⚔️ H2H: Chưa có dữ liệu đối đầu gần đây.")

    fh = report["form"]["home"]
    fa = report["form"]["away"]
    lines.append(
        f"📈 <b>{h_name}</b>: Cúp Âu {esc(fh['euro_5']['form_str'])} ({fh['euro_5']['gf']}:{fh['euro_5']['ga']}) | "
        f"Mọi giải {esc(fh['all_5']['form_str'])} | Thắng >=2 bàn: {fh['all_5']['win_by_2_pct']}%"
    )
    lines.append(
        f"📈 <b>{a_name}</b>: Cúp Âu {esc(fa['euro_5']['form_str'])} ({fa['euro_5']['gf']}:{fa['euro_5']['ga']}) | "
        f"Mọi giải {esc(fa['all_5']['form_str'])} | Thắng >=2 bàn: {fa['all_5']['win_by_2_pct']}%"
    )

    bh = report["boxscore"]["home"]["overall"]
    ba = report["boxscore"]["away"]["overall"]
    lines.append(
        f"📊 <b>Boxscore ({bh['sample_size']}/{ba['sample_size']} trận):</b>\n"
        f"• {h_name}: Sút {bh['shots_avg']} | SoT {bh['sot_avg']} (HS {bh['sot_diff_avg']:+.1f}) | Góc {bh['corners_avg']} | Bóng {bh['possession_avg']}%\n"
        f"• {a_name}: Sút {ba['shots_avg']} | SoT {ba['sot_avg']} (HS {ba['sot_diff_avg']:+.1f}) | Góc {ba['corners_avg']} | Bóng {ba['possession_avg']}%"
    )

    # 4. Thế Bánh mì kẹp
    lines.append("\n<b>4️⃣ THẾ BÁNH MÌ KẸP (4-7 NGÀY)</b>")
    for side_key, team_lbl in (("home", h_name), ("away", a_name)):
        sw = report["sandwich"][side_key]
        b_txt = (
            f"Trước ({sw['before'][0]['gap_days']}ng): {esc(sw['before'][0]['opponent_name'])} ({esc(sw['before'][0]['league_name'])})"
            if sw["before"]
            else "Trước: Trống"
        )
        a_txt = (
            f"Sau ({sw['after'][0]['gap_days']}ng): {esc(sw['after'][0]['opponent_name'])} ({esc(sw['after'][0]['league_name'])})"
            if sw["after"]
            else "Sau: Trống"
        )
        lines.append(f"• <b>{team_lbl}</b>: {b_txt} | {a_txt}\n  ⚠️ {esc(sw['warning_level'])}")

    # 5. Tin báo chí AI / RSS
    lines.append(f"\n<b>5️⃣ HỌP BÁO & PHÁP LÝ UEFA ({esc(ai_summary.get('model_used', 'RSS'))})</b>")
    clean_ai = esc((ai_summary.get("text") or "").replace("**", ""))
    lines.append(clean_ai[:1450])

    return "\n".join(lines)


def format_t90_digest_telegram(matches: list[dict[str, Any]], window_label: str) -> str:
    """1 tin nhắn tổng hợp gọn mốc T-90 phút (chống bão tin nhắn khi có 14-18 trận cùng giờ)."""
    esc = html.escape
    lines = [
        f"⏰ <b>TỔNG HỢP LỊCH CÚP CHÂU ÂU SẮP ĐÁ ({esc(window_label)})</b>",
        f"Tổng cộng: <b>{len(matches)} trận</b> chuẩn bị bóng lăn:\n",
    ]
    for lg_code in ("UCL", "UEL"):
        lg_matches = [m for m in matches if m["league_code"] == lg_code]
        if not lg_matches:
            continue
        icon = "🔵" if lg_code == "UCL" else "🟠"
        lines.append(f"{icon} <b>{lg_code} ({len(lg_matches)} trận):</b>")
        for m in lg_matches:
            t_short = m["kickoff_dt_vn"].strftime("%H:%M") if m.get("kickoff_dt_vn") else ""
            lines.append(f"  • {t_short} | {esc(m['home_name'])} vs {esc(m['away_name'])}")
        lines.append("")

    lines.append("💡 <i>Gõ <code>/match TênĐội</code> để lấy báo cáo sâu + tóm tắt AI báo chí cho bất kỳ trận nào.</i>")
    return "\n".join(lines)


def format_t75_auto_alert_telegram(snapshot: dict[str, Any]) -> str:
    """Tin nhắn tự động mốc T-70..T-30 khi đã có đội hình chính thức T-75 (KHÔNG gọi Gemini AI)."""
    esc = html.escape
    fx = snapshot["fixture"]
    h_name = esc(fx["home_name"])
    a_name = esc(fx["away_name"])
    icon = "🔵" if fx["league_code"] == "UCL" else "🟠"

    lines = [
        f"{icon} <b>ĐỘI HÌNH CHÍNH THỨC T-75 | {fx['league_code']}</b>",
        f"⚽ <b>{h_name} vs {a_name}</b> ({esc(fx['kickoff_vn'])})",
    ]

    for side_key, team_lbl in (("home", h_name), ("away", a_name)):
        lu = snapshot["lineups"][side_key]
        if lu["confirmed"]:
            xi = ", ".join(esc(p["name"]) for p in lu["starters"])
            lines.append(f"\n✅ <b>{team_lbl} ({esc(lu['formation'] or 'XI')}):</b>\n{xi}")
        else:
            lines.append(f"\n⏳ <b>{team_lbl}:</b> Chưa cập nhật đủ 11 cầu thủ.")

        injs = snapshot["injuries"][side_key][:5]
        if injs:
            inj_s = ", ".join(f"{esc(i['name'])} ({esc(i['status'])})" for i in injs)
            lines.append(f"🏥 Vắng: {inj_s}")

    hs = snapshot.get("home_standing")
    as_ = snapshot.get("away_standing")
    if hs or as_:
        h_st = f"#{hs['rank']} ({hs['points']}đ - {hs['zone']})" if hs else "N/A"
        a_st = f"#{as_['rank']} ({as_['points']}đ - {as_['zone']})" if as_ else "N/A"
        lines.append(f"\n📊 <b>BXH:</b> {h_name} {esc(h_st)} | {a_name} {esc(a_st)}")

    if snapshot["knockout"]["is_knockout"]:
        lines.append(
            f"🔥 <b>Knock-out:</b> {esc(snapshot['knockout']['round_detail'])} "
            f"{esc(snapshot['knockout']['aggregate_summary'])}"
        )

    lines.append(f"\n💬 <i>Xem tin báo chí AI & Bánh mì kẹp: gửi <code>/match {esc(fx['home_name'])}</code></i>")
    return "\n".join(lines)
