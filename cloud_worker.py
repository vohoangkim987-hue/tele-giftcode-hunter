import asyncio
import html
import os
import re
import time
from datetime import datetime, timedelta, timezone
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ================= CẤU HÌNH TỪ BIẾN MÔI TRƯỜNG CLOUD =================
API_ID = int(os.environ.get("API_ID", "2040"))
API_HASH = os.environ.get("API_HASH", "b18441a1ff607e10a989891a5462e627").strip()
STRING_SESSION = os.environ.get("STRING_SESSION", "").strip()
SEND_MODE = os.environ.get("SEND_MODE", "command").strip()  # "command" hoặc "pre_armed"
PORT = int(os.environ.get("PORT", "7860"))

PRIMARY_CHANNEL_ID = -1003587571424
TARGET_CHANNEL_IDS = {-1003587571424, 3587571424}
TARGET_BOT_USERNAME = os.environ.get("BOT_USERNAME", "geminiveri_bot")
TARGET_BOT_ID = int(os.environ.get("BOT_ID", "8278181665"))
NOTIFY_SAVED_MESSAGES = os.environ.get("NOTIFY_SAVED_MESSAGES", "true").lower() == "true"

VN_TZ = timezone(timedelta(hours=7))
IGNORE_WORDS = {
    "GIFTCODE", "CODE", "TANG", "MIEN", "NHAP", "COIN",
    "SLOT", "NHANH", "NHAT", "TIEP", "CHAN", "BOT"
}

STATE = {
    "status": "Đang khởi động...",
    "account": "Chưa kết nối",
    "started_at": datetime.now(VN_TZ).strftime("%H:%M:%S %d/%m/%Y"),
    "last_ping": datetime.now(VN_TZ).strftime("%H:%M:%S %d/%m/%Y"),
    "total_caught": 0,
    "history": [],
}


def now_vn() -> str:
    return datetime.now(VN_TZ).strftime("%H:%M:%S %d/%m/%Y")


def extract_giftcodes(text: str) -> list[str]:
    """Trích xuất mã Giftcode từ mọi định dạng tin nhắn của Edward Verify Official."""
    if not text:
        return []
    found = []
    # Ưu tiên 1: Bắt sau '/code <MÃ>'
    for match in re.finditer(r"/code[\s:=-]+([A-Za-z0-9_-]{3,35})", text, flags=re.IGNORECASE):
        code = match.group(1).strip().upper()
        if code not in IGNORE_WORDS and code not in found:
            found.append(code)
    # Ưu tiên 2: Bắt sau 'Mã: <MÃ>', 'Giftcode: <MÃ>', 'Code: <MÃ>'
    for match in re.finditer(r"(?:Mã|Giftcode|Code)[\s:=-]+([A-Za-z0-9_-]{3,35})", text, flags=re.IGNORECASE):
        code = match.group(1).strip().upper()
        if code not in IGNORE_WORDS and code not in found:
            found.append(code)
    return found


# ================= WEB SERVER DASHBOARD & KEEP-ALIVE =================
async def handle_dashboard(request):
    STATE["last_ping"] = now_vn()
    rows = ""
    for item in reversed(STATE["history"]):
        rows += (
            f"<tr>"
            f"<td>{html.escape(item['time'])}</td>"
            f"<td><b style='color:#00e676'>{html.escape(item['code'])}</b></td>"
            f"<td>{html.escape(item['speed'])}</td>"
            f"<td>{html.escape(item['reply'])}</td>"
            f"</tr>"
        )
    if not rows:
        rows = "<tr><td colspan='4' style='text-align:center;color:#888'>Đang canh mã mới 24/24...</td></tr>"

    page = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="15">
<title>Auto Săn Giftcode 24/7 - Edward Verify</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 24px; }}
  .card {{ max-width: 820px; margin: 0 auto; background: #1e293b; border-radius: 14px; padding: 24px; box-shadow: 0 10px 25px rgba(0,0,0,0.4); }}
  h1 {{ margin-top: 0; font-size: 22px; color: #38bdf8; }}
  .badge {{ display: inline-block; padding: 6px 12px; border-radius: 999px; background: #065f46; color: #34d399; font-weight: 600; font-size: 13px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 18px 0; }}
  .stat {{ background: #0f172a; padding: 14px; border-radius: 10px; border: 1px solid #334155; }}
  .stat span {{ display: block; font-size: 12px; color: #94a3b8; }}
  .stat strong {{ font-size: 16px; color: #f8fafc; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 14px; }}
  th, td {{ padding: 10px 12px; border-bottom: 1px solid #334155; text-align: left; }}
  th {{ color: #94a3b8; font-weight: 600; background: #0f172a; }}
</style>
</head>
<body>
  <div class="card">
    <h1>⚡ Cloud Hunter 24/7: Edward Verify ➔ Gemini Verify</h1>
    <div class="badge">● {html.escape(STATE['status'])}</div>
    <div class="grid">
      <div class="stat"><span>Tài khoản Telegram</span><strong>{html.escape(STATE['account'])}</strong></div>
      <div class="stat"><span>Khởi động lúc</span><strong>{html.escape(STATE['started_at'])}</strong></div>
      <div class="stat"><span>Cập nhật gần nhất</span><strong>{html.escape(STATE['last_ping'])}</strong></div>
      <div class="stat"><span>Số mã đã bắn</span><strong style="color:#38bdf8">{STATE['total_caught']} mã</strong></div>
    </div>
    <h3>📋 Lịch sử săn Giftcode tự động</h3>
    <table>
      <thead><tr><th>Thời gian</th><th>Mã Code</th><th>Tốc độ</th><th>Phản hồi từ @geminiveri_bot</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</body>
</html>"""
    return web.Response(text=page, content_type="text/html")


async def handle_health(request):
    STATE["last_ping"] = now_vn()
    return web.json_response({"ok": True, "status": STATE["status"], "caught": STATE["total_caught"]})


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_dashboard)
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌐 Web Dashboard 24/7 đang chạy tại cổng {PORT}", flush=True)


# ================= TELETHON BOT WORKER 24/7 =================
async def run_telethon_worker():
    if not API_ID or not API_HASH or not STRING_SESSION:
        STATE["status"] = "⚠️ Thiếu biến môi trường API_ID, API_HASH hoặc STRING_SESSION!"
        print(STATE["status"], flush=True)
        while True:
            await asyncio.sleep(60)

    client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        STATE["status"] = "❌ STRING_SESSION hết hạn hoặc không hợp lệ!"
        print(STATE["status"], flush=True)
        while True:
            await asyncio.sleep(60)

    me = await client.get_me()
    STATE["account"] = f"{me.first_name or ''} (@{me.username or me.id})"
    STATE["status"] = "Đang trực chiến 24/7 (Edward Verify -> Gemini Verify)"
    print(f"✅ Đã kết nối Cloud 24/7 với tài khoản: {STATE['account']}", flush=True)

    # 1. Cache danh sách hội thoại và xác nhận kênh Edward Verify Official
    dialogs = await client.get_dialogs(limit=150)
    target_channels = set(TARGET_CHANNEL_IDS)
    matched_channel_names = []
    for d in dialogs:
        if "edward verify" in (d.name or "").lower() or d.id in target_channels:
            target_channels.add(d.id)
            if hasattr(d.entity, "id"):
                target_channels.add(d.entity.id)
                target_channels.add(int(f"-100{d.entity.id}"))
            matched_channel_names.append(f"{d.name} (ID: {d.id})")

    if matched_channel_names:
        print(f"📡 Đã kết nối kênh mục tiêu: {', '.join(matched_channel_names)}", flush=True)
    else:
        print(f"📡 Đang theo dõi ID kênh mục tiêu: {PRIMARY_CHANNEL_ID}", flush=True)

    # 2. Cache sẵn thực thể bot @geminiveri_bot để bắn 0 độ trễ
    try:
        bot_entity = await client.get_input_entity(TARGET_BOT_USERNAME)
    except Exception:
        bot_entity = await client.get_input_entity(TARGET_BOT_ID)
    print(f"🤖 Đã nạp sẵn cache Bot nhận code: @{TARGET_BOT_USERNAME} (ID: {TARGET_BOT_ID})", flush=True)

    # 3. Kiểm tra nếu khung chat @geminiveri_bot đang bị treo ở bước 'Gửi mã Giftcode của bạn vào đây:' thì bấm [Hủy] để đưa về trạng thái chuẩn
    try:
        bot_msgs = await client.get_messages(bot_entity, limit=2)
        for bm in bot_msgs:
            if bm and "gửi mã giftcode của bạn vào đây" in (bm.message or "").lower() and bm.buttons:
                await bm.click(0)
                print("🧹 Đã tự động bấm [✖ Hủy] khung chờ nhập mã cũ trong @geminiveri_bot để sẵn sàng nhận lệnh mới!", flush=True)
                break
    except Exception:
        pass

    # 4. Đọc các mã cũ từ kênh Edward Verify Official để chống gửi trùng
    seen_codes = set()
    try:
        old_msgs = await client.get_messages(PRIMARY_CHANNEL_ID, limit=20)
        for m in old_msgs:
            for c in extract_giftcodes(m.message or ""):
                seen_codes.add(c)
    except Exception:
        for ch_id in list(target_channels):
            try:
                old_msgs = await client.get_messages(ch_id, limit=20)
                for m in old_msgs:
                    for c in extract_giftcodes(m.message or ""):
                        seen_codes.add(c)
                if seen_codes:
                    break
            except Exception:
                continue

    if seen_codes:
        print(f"📌 Đã nạp bộ lọc bỏ qua {len(seen_codes)} mã cũ trên kênh: {', '.join(sorted(seen_codes))}", flush=True)
    print("🎯 HỆ THỐNG ĐANG TRỰC CHIẾN 24/24 - SẴN SÀNG BẮT MÃ MỚI TỐC ĐỘ MILI-GIÂY!", flush=True)

    last_code_sent = {"code": None, "raw_followup_sent": False, "timestamp": 0.0}

    if SEND_MODE == "pre_armed":
        await client.send_message(bot_entity, "/code")

    async def process_msg(event):
        text = event.raw_text or ""
        if not text:
            return
        if (event.chat_id not in target_channels) and ("@geminiveri_bot" not in text.lower()):
            return

        for code in extract_giftcodes(text):
            if code in seen_codes:
                continue
            seen_codes.add(code)

            t0 = time.perf_counter()
            payload = code if SEND_MODE == "pre_armed" else f"/code {code}"
            await client.send_message(bot_entity, payload)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            last_code_sent["code"] = code
            last_code_sent["raw_followup_sent"] = (SEND_MODE == "pre_armed")
            last_code_sent["timestamp"] = time.time()

            STATE["total_caught"] += 1
            entry = {
                "time": now_vn(),
                "code": code,
                "speed": f"{elapsed_ms:.1f} ms",
                "reply": "Đang chờ bot phản hồi..."
            }
            STATE["history"].append(entry)
            if len(STATE["history"]) > 30:
                STATE["history"].pop(0)

            print(f"🔥 [{entry['time']}] BẮT ĐƯỢC MÃ: {code} -> Đã bắn '{payload}' ({entry['speed']})", flush=True)

            if SEND_MODE == "pre_armed":
                async def re_arm():
                    await asyncio.sleep(1.5)
                    await client.send_message(bot_entity, "/code")
                asyncio.create_task(re_arm())

    @client.on(events.NewMessage())
    async def on_new(event):
        await process_msg(event)

    @client.on(events.MessageEdited())
    async def on_edit(event):
        await process_msg(event)

    @client.on(events.NewMessage(from_users=bot_entity))
    async def on_bot_reply(event):
        reply_text = (event.raw_text or "").strip()
        if not reply_text:
            return

        reply_lower = reply_text.lower()
        # Dự phòng 2 lớp: nếu bot hỏi 'Gửi mã Giftcode của bạn vào đây' hoặc báo lỗi cú pháp khi đang ở chế độ chờ nhập mã
        if (
            ("gửi mã giftcode của bạn vào đây" in reply_lower or "không tồn tại" in reply_lower or "không hợp lệ" in reply_lower)
            and last_code_sent["code"]
            and not last_code_sent["raw_followup_sent"]
            and (time.time() - last_code_sent["timestamp"] < 5.0)
        ):
            last_code_sent["raw_followup_sent"] = True
            await client.send_message(bot_entity, last_code_sent["code"])
            print(f"⚡ Đã tự động bắn bồi mã rời: {last_code_sent['code']}", flush=True)
            return

        first_line = reply_text.splitlines()[0]
        print(f"📩 [{now_vn()}] Phản hồi từ @geminiveri_bot: {first_line}", flush=True)
        if STATE["history"]:
            STATE["history"][-1]["reply"] = first_line

        if NOTIFY_SAVED_MESSAGES and last_code_sent["code"] and (time.time() - last_code_sent["timestamp"] < 15.0):
            try:
                await client.send_message(
                    "me",
                    f"🎯 **[AUTO CLOUD 24/7]** Đã tự động bắt mã: `{last_code_sent['code']}`\n"
                    f"🤖 **Phản hồi từ Gemini Verify:**\n{reply_text}"
                )
            except Exception:
                pass

    # Vòng lặp tự động kết nối lại nếu máy chủ Telegram bảo trì ngắn hạn
    while True:
        try:
            if not client.is_connected():
                await client.connect()
            await client.run_until_disconnected()
        except Exception as e:
            print(f"⚠️ Mất kết nối tạm thời ({e}), đang tự động kết nối lại sau 3 giây...", flush=True)
            await asyncio.sleep(3)


async def main():
    await start_web_server()
    await run_telethon_worker()


if __name__ == "__main__":
    asyncio.run(main())
