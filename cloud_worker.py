import asyncio
import html
import os
import re
import time
from datetime import datetime, timedelta, timezone
from aiohttp import web
from telethon import TelegramClient, events, functions
from telethon.sessions import StringSession

# ================= CẤU HÌNH TỪ BIẾN MÔI TRƯỜNG CLOUD =================
API_ID = int(os.environ.get("API_ID", "2040"))
API_HASH = os.environ.get("API_HASH", "b18441a1ff607e10a989891a5462e627").strip()
STRING_SESSION = os.environ.get("STRING_SESSION", "").strip()
SEND_MODE = os.environ.get("SEND_MODE", "command").strip()  # "command" hoặc "pre_armed"
PORT = int(os.environ.get("PORT", "7860"))

PRIMARY_CHANNEL_ID = -1003987571424
TARGET_CHANNEL_IDS = {-1003987571424, 3987571424, -1003587571424, 3587571424}
TARGET_BOT_USERNAME = os.environ.get("BOT_USERNAME", "geminiveri_bot")
TARGET_BOT_ID = int(os.environ.get("BOT_ID", "8278181665"))
NOTIFY_SAVED_MESSAGES = os.environ.get("NOTIFY_SAVED_MESSAGES", "true").lower() == "true"

VN_TZ = timezone(timedelta(hours=7))
START_EPOCH = time.time()

# Từ khóa loại trừ chống bắt nhầm văn bản thường
IGNORE_WORDS = {
    "GIFTCODE", "CODE", "TANG", "MIEN", "NHAP", "COIN", "XU",
    "SLOT", "NHANH", "NHAT", "TIEP", "CHAN", "BOT", "VERIFY",
    "GEMINI", "EDWARD", "OFFICIAL", "ADMIN", "FREE", "TEST",
    "LOI", "KHOA", "TAI", "KHOAN", "NGAY", "LUON", "XONG",
}

# Biên dịch sẵn Regex (Pre-compiled) để tốc độ xử lý đạt mức micro-giây (~0.005ms)
RE_SLASH_CODE = re.compile(
    r"/code(?:\s*[:=]\s*|\s+)[\"'`\[\(<]*([A-Za-z0-9_-]{4,35})(?![\w\u00C0-\u1EF9])",
    flags=re.IGNORECASE,
)
RE_LABELED_CODE = re.compile(
    r"(?:^|[^\w\u00C0-\u1EF9])(?:Mã|Giftcode|Code)\s*[:=]\s*[\"'`\[\(<]*([A-Za-z0-9_-]{4,35})(?![\w\u00C0-\u1EF9])",
    flags=re.IGNORECASE | re.MULTILINE,
)

STATE = {
    "status": "Đang khởi động...",
    "account": "Chưa kết nối",
    "channels": "Đang dò kênh...",
    "started_at": datetime.now(VN_TZ).strftime("%H:%M:%S %d/%m/%Y"),
    "last_ping": datetime.now(VN_TZ).strftime("%H:%M:%S %d/%m/%Y"),
    "tg_ping_ms": 0.0,
    "total_caught": 0,
    "history": [],
}


def now_vn() -> str:
    return datetime.now(VN_TZ).strftime("%H:%M:%S %d/%m/%Y")


def format_uptime() -> str:
    sec = int(time.time() - START_EPOCH)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}p {s}s"


def extract_giftcodes(text: str) -> list[str]:
    """
    Trích xuất chính xác mã Giftcode từ tin nhắn kênh Edward Verify Official.
    - Bắt '/code MÃ_CODE' hoặc '/code: MÃ_CODE'
    - Bắt 'Mã: MÃ_CODE', 'Giftcode: MÃ_CODE', 'Code: MÃ_CODE' (bắt buộc có dấu ':' hoặc '=')
    - Không cắt ngang từ tiếng Việt có dấu, không bắt nhầm câu văn thông thường.
    """
    if not text:
        return []
    found = []
    for match in RE_SLASH_CODE.finditer(text):
        code = match.group(1).strip().upper()
        if code not in IGNORE_WORDS and code not in found:
            found.append(code)
    for match in RE_LABELED_CODE.finditer(text):
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
<title>Auto Săn Giftcode 24/7 v2.0 - Edward Verify</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 24px; }}
  .card {{ max-width: 860px; margin: 0 auto; background: #1e293b; border-radius: 14px; padding: 24px; box-shadow: 0 10px 25px rgba(0,0,0,0.4); }}
  h1 {{ margin-top: 0; font-size: 22px; color: #38bdf8; }}
  .badge {{ display: inline-block; padding: 6px 12px; border-radius: 999px; background: #065f46; color: #34d399; font-weight: 600; font-size: 13px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 18px 0; }}
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
    <h1>⚡ Cloud Hunter 24/7 (v2.0 Turbo): Edward Verify ➔ Gemini Verify</h1>
    <div class="badge">● {html.escape(STATE['status'])}</div>
    <div class="grid">
      <div class="stat"><span>Tài khoản Telegram</span><strong>{html.escape(STATE['account'])}</strong></div>
      <div class="stat"><span>Thời gian chạy phiên</span><strong>{html.escape(format_uptime())}</strong></div>
      <div class="stat"><span>Ping tới Telegram</span><strong style="color:#34d399">{STATE['tg_ping_ms']:.1f} ms</strong></div>
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
    return web.json_response({
        "ok": True,
        "status": STATE["status"],
        "uptime": format_uptime(),
        "tg_ping_ms": round(STATE["tg_ping_ms"], 1),
        "caught": STATE["total_caught"],
    })


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_dashboard)
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌐 Web Dashboard 24/7 (v2.0) đang chạy tại cổng {PORT}", flush=True)


# ================= TELETHON BOT WORKER 24/7 =================
async def keep_warm_ping_loop(client: TelegramClient):
    """
    Giữ nóng đường truyền TCP/MTProto mỗi 25 giây để tránh TCP slow-start khi kênh im lặng lâu,
    đồng thời đo độ trễ thực tế (ms) tới máy chủ Telegram.
    """
    ping_id = 1000
    while True:
        try:
            if client.is_connected():
                ping_id += 1
                t0 = time.perf_counter()
                await client(functions.PingRequest(ping_id=ping_id))
                STATE["tg_ping_ms"] = (time.perf_counter() - t0) * 1000
                STATE["last_ping"] = now_vn()
        except Exception:
            pass
        await asyncio.sleep(25)


async def run_telethon_worker():
    if not API_ID or not API_HASH or not STRING_SESSION:
        STATE["status"] = "⚠️ Thiếu biến môi trường API_ID, API_HASH hoặc STRING_SESSION!"
        print(STATE["status"], flush=True)
        while True:
            await asyncio.sleep(60)

    client = TelegramClient(
        StringSession(STRING_SESSION),
        API_ID,
        API_HASH,
        use_ipv6=False,
        connection_retries=15,
        retry_delay=1,
        auto_reconnect=True,
        flood_sleep_threshold=5,
    )
    await client.connect()

    if not await client.is_user_authorized():
        STATE["status"] = "❌ STRING_SESSION hết hạn hoặc không hợp lệ!"
        print(STATE["status"], flush=True)
        while True:
            await asyncio.sleep(60)

    me = await client.get_me()
    my_id = me.id
    STATE["account"] = f"{me.first_name or ''} (@{me.username or me.id})"
    STATE["status"] = "Đang trực chiến 24/7 (v2.0 Turbo)"
    print(f"✅ Đã kết nối Cloud 24/7 với tài khoản: {STATE['account']}", flush=True)

    # 1. Cache danh sách hội thoại và xác nhận kênh Edward Verify Official
    dialogs = await client.get_dialogs(limit=150)
    target_channels = set(TARGET_CHANNEL_IDS)
    matched_channel_names = []
    active_channel_entity = None

    for d in dialogs:
        if "edward verify" in (d.name or "").lower() or d.id in target_channels:
            target_channels.add(d.id)
            if hasattr(d.entity, "id"):
                target_channels.add(d.entity.id)
                target_channels.add(int(f"-100{d.entity.id}"))
            matched_channel_names.append(f"{d.name} (ID: {d.id})")
            if active_channel_entity is None:
                active_channel_entity = d.entity

    STATE["channels"] = ", ".join(matched_channel_names) if matched_channel_names else str(PRIMARY_CHANNEL_ID)
    print(f"📡 Đã kết nối kênh mục tiêu: {STATE['channels']}", flush=True)

    # 2. Cache sẵn InputPeer của bot @geminiveri_bot để bắn 0 độ trễ
    try:
        bot_entity = await client.get_input_entity(TARGET_BOT_USERNAME)
    except Exception:
        bot_entity = await client.get_input_entity(TARGET_BOT_ID)
    print(f"🤖 Đã nạp sẵn cache Bot nhận code: @{TARGET_BOT_USERNAME} (ID: {TARGET_BOT_ID})", flush=True)

    # 3. Tự động bấm [✖ Hủy] nếu @geminiveri_bot đang bị kẹt ở câu hỏi chờ nhập mã cũ
    try:
        bot_msgs = await client.get_messages(bot_entity, limit=2)
        for bm in bot_msgs:
            if bm and "gửi mã giftcode của bạn vào đây" in (bm.message or "").lower() and bm.buttons:
                await bm.click(0)
                print("🧹 Đã tự động bấm [✖ Hủy] khung chờ nhập mã cũ trong @geminiveri_bot!", flush=True)
                break
    except Exception:
        pass

    # 4. Nạp bộ lọc bỏ qua mã cũ trên kênh
    seen_codes = set()
    try:
        lookup_target = active_channel_entity or PRIMARY_CHANNEL_ID
        old_msgs = await client.get_messages(lookup_target, limit=25)
        for m in old_msgs:
            for c in extract_giftcodes(m.message or ""):
                seen_codes.add(c)
    except Exception:
        for ch_id in list(target_channels):
            try:
                old_msgs = await client.get_messages(ch_id, limit=25)
                for m in old_msgs:
                    for c in extract_giftcodes(m.message or ""):
                        seen_codes.add(c)
                if seen_codes:
                    break
            except Exception:
                continue

    # Khởi động luồng Keep-Warm Ping mỗi 25s
    asyncio.create_task(keep_warm_ping_loop(client))
    await asyncio.sleep(0.3)

    if seen_codes:
        print(f"📌 Đã nạp bộ lọc bỏ qua {len(seen_codes)} mã cũ trên kênh: {', '.join(sorted(seen_codes))}", flush=True)
    print(
        f"🎯 HỆ THỐNG v2.0 TURBO ĐANG TRỰC CHIẾN 24/24 (Ping Telegram: {STATE['tg_ping_ms']:.1f} ms)!\n"
        f"💡 Mẹo: Mở 'Saved Messages' trên điện thoại gõ !check để kiểm tra trạng thái bất cứ lúc nào.",
        flush=True,
    )

    last_code_sent = {"code": None, "raw_followup_sent": False, "timestamp": 0.0}

    if SEND_MODE == "pre_armed":
        await client.send_message(bot_entity, "/code")

    def log_caught_code(code: str, payload: str, elapsed_ms: float):
        STATE["total_caught"] += 1
        entry = {
            "time": now_vn(),
            "code": code,
            "speed": f"{elapsed_ms:.1f} ms",
            "reply": "Đang chờ bot phản hồi...",
        }
        STATE["history"].append(entry)
        if len(STATE["history"]) > 30:
            STATE["history"].pop(0)
        print(f"🔥 [{entry['time']}] BẮT ĐƯỢC MÃ: {code} -> Đã bắn '{payload}' ({entry['speed']})", flush=True)

    async def process_msg(event):
        # Bỏ qua tin nhắn do chính mình gửi đi để tiết kiệm CPU
        if event.out:
            return
        text = event.raw_text
        if not text:
            return
        if (event.chat_id not in target_channels) and ("@geminiveri_bot" not in text.lower()):
            return

        codes = extract_giftcodes(text)
        if not codes:
            return

        for code in codes:
            if code in seen_codes:
                continue
            seen_codes.add(code)

            payload = code if SEND_MODE == "pre_armed" else f"/code {code}"
            t0 = time.perf_counter()
            await client.send_message(bot_entity, payload)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            last_code_sent["code"] = code
            last_code_sent["raw_followup_sent"] = (SEND_MODE == "pre_armed")
            last_code_sent["timestamp"] = time.time()

            log_caught_code(code, payload, elapsed_ms)

            if SEND_MODE == "pre_armed":
                async def re_arm():
                    await asyncio.sleep(1.5)
                    await client.send_message(bot_entity, "/code")
                asyncio.create_task(re_arm())

    # Lắng nghe tin nhắn mới & chỉnh sửa từ kênh
    @client.on(events.NewMessage(incoming=True))
    async def on_new(event):
        await process_msg(event)

    @client.on(events.MessageEdited(incoming=True))
    async def on_edit(event):
        await process_msg(event)

    # Lệnh kiểm tra nhanh trên điện thoại: gõ !check hoặc !ping vào Saved Messages
    @client.on(events.NewMessage(chats=my_id, outgoing=True))
    async def on_self_command(event):
        cmd = (event.raw_text or "").strip().lower()
        if cmd not in ("!check", "!ping", "/check"):
            return
        t0 = time.perf_counter()
        await client(functions.PingRequest(ping_id=9999))
        live_ping = (time.perf_counter() - t0) * 1000
        STATE["tg_ping_ms"] = live_ping

        recent_lines = "\n".join(
            f"  • `{x['code']}` ({x['speed']}) ➔ {x['reply']}"
            for x in STATE["history"][-5:]
        ) or "  • Chưa có mã mới nào phát trong phiên này"

        report = (
            f"🟢 **CLOUD HUNTER 24/7 (v2.0 Turbo) ĐANG HOẠT ĐỘNG!**\n\n"
            f"👤 **Tài khoản:** {STATE['account']}\n"
            f"⏱ **Thời gian chạy phiên này:** `{format_uptime()}`\n"
            f"⚡ **Độ trễ tới Server Telegram:** `{live_ping:.1f} ms`\n"
            f"📡 **Kênh đang canh:** `{STATE['channels']}`\n"
            f"🤖 **Bot nạp mã:** `@{TARGET_BOT_USERNAME}`\n"
            f"🎯 **Số mã đã bắn trong phiên:** `{STATE['total_caught']}`\n"
            f"📋 **5 mã gần nhất:**\n{recent_lines}"
        )
        await event.reply(report)

    @client.on(events.NewMessage(from_users=bot_entity))
    async def on_bot_reply(event):
        reply_text = (event.raw_text or "").strip()
        if not reply_text:
            return

        reply_lower = reply_text.lower()
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
                    f"🤖 **Phản hồi từ Gemini Verify:**\n{reply_text}",
                )
            except Exception:
                pass

    while True:
        try:
            if not client.is_connected():
                await client.connect()
            await client.run_until_disconnected()
        except Exception as e:
            print(f"⚠️ Mất kết nối tạm thời ({e}), đang tự động kết nối lại sau 2 giây...", flush=True)
            await asyncio.sleep(2)


async def main():
    await start_web_server()
    await run_telethon_worker()


if __name__ == "__main__":
    asyncio.run(main())
