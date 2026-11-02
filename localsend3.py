# -*- coding: utf-8 -*-
# ============================================================================
#  Web LocalSend Pro
#  ارسال فایل و متن بین دستگاه‌های یک شبکه محلی (FastAPI + یک صفحه وب)
# ============================================================================

# ---------------------------------------------------------------------------
# بخش ۱: کتابخانه‌های استاندارد پایتون
# subprocess: اجرای دستور pip   |  sys/os: اطلاعات سیستم و مسیر فایل‌ها
# socket: پیدا کردن IP دستگاه   |  webbrowser: باز کردن خودکار مرورگر
# time: زمان و تایمر            |  Timer/Thread: اجرای کارهای پس‌زمینه
# ---------------------------------------------------------------------------
import subprocess
import sys
import socket
import os
import webbrowser
import time
from threading import Timer, Thread

# بسته‌های مورد نیاز پروژه؛ اگر نصب نباشند خودکار نصب می‌شوند
# Required packages
REQUIRED_PACKAGES = ["fastapi", "uvicorn", "python-multipart"]

def auto_install_dependencies():
    """Checks and installs missing packages automatically."""
    # این تابع بررسی می‌کند هر بسته قابل import هست یا نه؛ اگر نبود با pip نصبش می‌کند
    import importlib
    for package in REQUIRED_PACKAGES:
        try:
            importlib.import_module(package.replace("-", "_"))
        except ImportError:
            print(f"[*] Missing package '{package}'. Installing...")
            try:
                cmd = [sys.executable, "-m", "pip", "install", package]
                # در لینوکس جدید برای نصب سراسری این فلگ لازم است
                if os.name != "nt":
                    cmd.append("--break-system-packages")
                subprocess.check_call(cmd)
            except Exception as e:
                print(f"[!] Failed to install {package}: {e}")
                sys.exit(1)
    importlib.invalidate_caches()

auto_install_dependencies()

# ---------------------------------------------------------------------------
# بخش ۲: ایمپورت FastAPI (بعد از نصب خودکار بسته‌ها)
# JSONResponse جدید است: برای برگرداندن خطای 404 به شکل استاندارد
# ---------------------------------------------------------------------------
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from typing import List

app = FastAPI()

# پوشه‌ای که فایل‌های دریافتی در آن ذخیره می‌شوند: ~/Downloads/WebLocalSend
# Setup download directory
UPLOAD_DIR = os.path.join(os.path.expanduser('~'), 'Downloads', 'WebLocalSend')
os.makedirs(UPLOAD_DIR, exist_ok=True)

# اندازه هر تکه‌ای که هنگام ذخیره فایل خوانده می‌شود (۱ مگابایت)
# با این کار فایل‌های بزرگ (چند صد مگابایتی) کل رم را اشغال نمی‌کنند
CHUNK_SIZE = 1024 * 1024

# ---------------------------------------------------------------------------
# بخش ۳: حافظه مرکزی سرور (همه چیز در RAM نگه داشته می‌شود، دیتابیس نداریم)
# online_devices : دستگاه‌های آنلاین   |   transfers : تاریخچه ارسال‌ها
# ---------------------------------------------------------------------------
# Central Memory Storage
online_devices = {}  # {client_id: {"name": str, "ip": str, "last_seen": float}}
transfers = []       # [{"id": int, "sender": str, "receiver": str, "type": str, "content": str, "time": str}]

# وضعیت «ضربان قلب» میزبان؛ برای اینکه اگر مرورگر میزبان بسته شد سرور هم خاموش شود
# Heartbeat State Tracking
HOST_CONNECTED = False
HOST_LAST_SEEN = time.time()
START_TIME = time.time()

def get_local_ip():
    # با یک اتصال UDP (بدون ارسال داده واقعی) آدرس IP دستگاه در شبکه محلی را می‌فهمیم
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def safe_filename(name: str) -> str:
    """فقط نام فایل را نگه می‌دارد و مسیر را حذف می‌کند (جلوگیری از ../ و حمله Path Traversal)"""
    return os.path.basename(name.replace("\\", "/"))

def monitor_host_heartbeat():
    """Background thread that destroys the server if the host browser crashes or closes."""
    # هر ۲ ثانیه چک می‌کند: اگر مرورگر میزبان بیش از ۱۰ ثانیه ping نفرستاده باشد سرور بسته می‌شود
    # اگر هم تا ۳۰ ثانیه بعد از اجرا هیچ میزبانی وصل نشد، سرور خودش را خاموش می‌کند
    global HOST_CONNECTED, HOST_LAST_SEEN
    while True:
        time.sleep(2)
        now = time.time()
        if HOST_CONNECTED:
            if now - HOST_LAST_SEEN > 10:
                print("\n[!] Host browser window closed (Heartbeat lost). Shutting down server...")
                os._exit(0)
        else:
            if now - START_TIME > 30:
                print("\n[!] No host connection detected within grace period. Shutting down...")
                os._exit(0)

# ---------------------------------------------------------------------------
# بخش ۴: رابط کاربری (HTML + CSS + JavaScript) به صورت یک رشته داخل پایتون
# طراحی: Material 3 Expressive با شیشه‌ای (Blur) ، انیمیشن‌های فنری و همه هشدارها داخل خود UI
# سرور این رشته را در مسیر "/" به مرورگر می‌فرستد
# ---------------------------------------------------------------------------
# Secure Core UI with Real-time Character Counter Engine
HTML_UI = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Web LocalSend Pro</title>
    <!-- کتابخانه QRious برای ساخت QR Code آدرس سرور -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/qrious/4.0.2/qrious.min.js" defer></script>
    <style>
        /* =====================================================================
           بخش ۱: توکن‌های طراحی (Design Tokens) - الهام گرفته از Material 3 Expressive
           همه رنگ‌ها و منحنی‌های انیمیشن یک‌جا تعریف شده‌اند تا تغییر تم فقط عوض شدن متغیرها باشد
           ===================================================================== */
        :root {
            color-scheme: dark;
            /* رنگ‌های تم تیره */
            --bg: #09100c;
            --primary: #6fe0ae;
            --on-primary: #00382a;
            --primary-container: #0b5139;
            --on-primary-container: #8ff7c5;
            --secondary-container: #2b4a3c;
            --on-secondary-container: #cdeedc;
            --tertiary-container: #1f4a63;
            --on-tertiary-container: #c7e7ff;
            --error: #ffb4ab;
            --error-container: #93000a;
            --on-error-container: #ffdad6;
            --on-surface: #e1e8e3;
            --on-surface-variant: #b4c0b9;
            --outline: #85908a;
            --outline-variant: rgba(255,255,255,0.14);
            --surface-high: rgba(255,255,255,0.06);
            --surface-higher: rgba(255,255,255,0.11);
            --primary-glow: rgba(111,224,174,0.16);
            --primary-glow-strong: rgba(111,224,174,0.55);
            --glass: rgba(20,28,24,0.58);
            --glass-border: rgba(255,255,255,0.10);
            --scrim: rgba(2,8,5,0.55);
            --inverse: #e1e8e3;
            --on-inverse: #18201b;
            --shadow: 0 40px 90px -25px rgba(0,0,0,0.7);
            --blob1: #10b981; --blob2: #3b82f6; --blob3: #8b5cf6;
            --blob-opacity: 0.5;
            /* منحنی‌های حرکتی: spring = فنری با کمی پرش ، emph = نرم و شتاب‌دار مثل متریال */
            --spring: cubic-bezier(0.34, 1.56, 0.64, 1);
            --emph: cubic-bezier(0.2, 0, 0, 1);
            --emph-dec: cubic-bezier(0.05, 0.7, 0.1, 1);
        }
        /* رنگ‌های تم روشن؛ با کلاس light-theme روی body فعال می‌شود */
        body.light-theme {
            color-scheme: light;
            --bg: #eaf3ec;
            --primary: #006c4f;
            --on-primary: #ffffff;
            --primary-container: #9af3c9;
            --on-primary-container: #002116;
            --secondary-container: #cfe9d9;
            --on-secondary-container: #0b1f15;
            --tertiary-container: #cde5ff;
            --on-tertiary-container: #001d32;
            --error: #ba1a1a;
            --error-container: #ffdad6;
            --on-error-container: #410002;
            --on-surface: #171d19;
            --on-surface-variant: #3f4943;
            --outline: #6f7973;
            --outline-variant: rgba(0,40,20,0.16);
            --surface-high: rgba(0,60,30,0.05);
            --surface-higher: rgba(0,60,30,0.09);
            --primary-glow: rgba(0,108,79,0.14);
            --primary-glow-strong: rgba(0,108,79,0.45);
            --glass: rgba(255,255,255,0.58);
            --glass-border: rgba(255,255,255,0.8);
            --scrim: rgba(20,40,30,0.35);
            --inverse: #2d3530;
            --on-inverse: #eef4ef;
            --shadow: 0 40px 90px -30px rgba(10,60,40,0.35);
            --blob-opacity: 0.42;
        }

        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }

        /* استایل کلی صفحه: کارت اصلی وسط صفحه قرار می‌گیرد */
        body {
            margin: 0; min-height: 100vh; padding: 20px 16px;
            display: flex; align-items: center; justify-content: center;
            background: var(--bg); color: var(--on-surface);
            font-family: "Google Sans", "Roboto", system-ui, -apple-system, "Segoe UI", sans-serif;
            overflow-x: hidden;
        }

        /* ---------- پس‌زمینه: سه لکه رنگی بلور شده که آرام حرکت می‌کنند ---------- */
        .bg { position: fixed; inset: 0; overflow: hidden; z-index: 0; pointer-events: none; }
        .blob { position: absolute; border-radius: 50%; filter: blur(90px); opacity: var(--blob-opacity); will-change: transform; transition: opacity 0.6s; }
        .b1 { width: 440px; height: 440px; background: var(--blob1); top: -140px; left: -120px; animation: drift1 22s ease-in-out infinite alternate; }
        .b2 { width: 400px; height: 400px; background: var(--blob2); bottom: -160px; right: -100px; animation: drift2 27s ease-in-out infinite alternate; }
        .b3 { width: 320px; height: 320px; background: var(--blob3); top: 42%; left: 58%; animation: drift3 31s ease-in-out infinite alternate; }
        @keyframes drift1 { to { transform: translate(160px, 120px) scale(1.2); } }
        @keyframes drift2 { to { transform: translate(-180px, -90px) scale(1.15); } }
        @keyframes drift3 { to { transform: translate(-140px, 80px) scale(0.85); } }

        /* ---------- کارت اصلی: شیشه‌ای با بلور زیاد ---------- */
        .card {
            position: relative; z-index: 1; width: 100%; max-width: 440px; padding: 24px;
            border-radius: 36px; background: var(--glass); border: 1px solid var(--glass-border);
            -webkit-backdrop-filter: blur(36px) saturate(1.5); backdrop-filter: blur(36px) saturate(1.5);
            box-shadow: var(--shadow), inset 0 1px 0 rgba(255,255,255,0.08);
            animation: cardIn 0.9s var(--spring) backwards;
        }
        @keyframes cardIn { from { opacity: 0; transform: translateY(50px) scale(0.93); } }

        /* ورود پله‌ای (Stagger) بخش‌های کارت هنگام باز شدن صفحه */
        .rise { animation: rise 0.8s var(--emph-dec) backwards; animation-delay: calc(var(--i, 0) * 70ms + 180ms); }
        @keyframes rise { from { opacity: 0; transform: translateY(22px); } }

        /* =====================================================================
           بخش ۲: اجزای پایه (آیکون، دکمه‌ها، ریپل)
           ===================================================================== */
        .slot { display: contents; }
        .ic { width: 20px; height: 20px; fill: currentColor; flex-shrink: 0; }
        .sw { display: inline-block; }   /* برای انیمیشن تعویض متن */

        /* افکت موج (Ripple) هنگام کلیک */
        .ripple { position: relative; overflow: hidden; }
        .ripple-wave {
            position: absolute; border-radius: 50%; background: currentColor; opacity: 0.22;
            transform: scale(0); animation: ripple 0.65s var(--emph) forwards; pointer-events: none;
        }
        @keyframes ripple { to { transform: scale(1); opacity: 0; } }

        /* دکمه‌های آیکونی گرد؛ هنگام هاور شکلشان به مربع گرد تبدیل می‌شود (Shape Morph) */
        .icon-btn {
            width: 44px; height: 44px; border-radius: 50%; border: none; cursor: pointer;
            background: var(--surface-high); color: var(--on-surface);
            display: grid; place-items: center; position: relative; overflow: hidden;
            transition: border-radius 0.4s var(--spring), transform 0.3s var(--spring), background-color 0.25s;
        }
        .icon-btn:hover { border-radius: 14px; background: var(--surface-higher); }
        .icon-btn:active { transform: scale(0.88); }
        .icon-btn.small { width: 32px; height: 32px; }
        .icon-btn.small .ic { width: 16px; height: 16px; }
        .icon-btn.small:hover { color: var(--error); }

        /* دکمه تغییر تم: دو آیکون روی هم؛ با چرخش و محو شدن جابجا می‌شوند */
        #theme-btn .ic { position: absolute; transition: transform 0.7s var(--spring), opacity 0.35s; }
        #theme-btn .sun { opacity: 0; transform: rotate(-120deg) scale(0.3); }
        body.light-theme #theme-btn .sun { opacity: 1; transform: none; }
        body.light-theme #theme-btn .moon { opacity: 0; transform: rotate(120deg) scale(0.3); }

        /* دکمه‌های اصلی (Filled / Tonal / Text) */
        .btn {
            position: relative; overflow: hidden; width: 100%; height: 52px; border: none; cursor: pointer;
            display: inline-flex; align-items: center; justify-content: center; gap: 8px;
            border-radius: 26px; font: inherit; font-size: 15px; font-weight: 600;
            background: var(--primary); color: var(--on-primary);
            transition: border-radius 0.45s var(--spring), transform 0.3s var(--spring), background-color 0.3s, opacity 0.35s, box-shadow 0.35s;
        }
        .btn::before { content: ''; position: absolute; inset: 0; background: currentColor; opacity: 0; transition: opacity 0.25s; pointer-events: none; }
        .btn:hover::before { opacity: 0.09; }
        .btn:hover { border-radius: 18px; box-shadow: 0 10px 26px -10px var(--primary-glow-strong); }
        .btn:active { border-radius: 14px; transform: scale(0.97); }
        .btn:disabled { opacity: 0.4; cursor: not-allowed; box-shadow: none; }
        .btn:disabled::before { display: none; }
        .btn.tonal { background: var(--secondary-container); color: var(--on-secondary-container); }
        .btn.text { background: transparent; color: var(--primary); width: auto; padding: 0 22px; height: 44px; border-radius: 22px; }
        .btn.text:hover { box-shadow: none; }
        .btn + .btn { margin-top: 8px; }
        .btn-row { display: flex; gap: 8px; margin-top: 2px; }
        .btn-row .btn + .btn { margin-top: 0; }

        /* دکمه‌های کوچک داخل کادرها (دانلود / کپی) */
        .chip-btn {
            position: relative; overflow: hidden; display: inline-flex; align-items: center; gap: 6px; margin-top: 10px;
            padding: 7px 14px; border-radius: 999px; border: none; cursor: pointer; text-decoration: none;
            background: var(--primary-container); color: var(--on-primary-container);
            font: inherit; font-size: 12px; font-weight: 700;
            transition: border-radius 0.4s var(--spring), transform 0.3s var(--spring), filter 0.25s;
        }
        .chip-btn:hover { border-radius: 10px; filter: brightness(1.12); }
        .chip-btn:active { transform: scale(0.93); }
        .chip-btn .ic { width: 16px; height: 16px; }

        /* =====================================================================
           بخش ۳: انیمیشن باز و بسته شدن نرم (Collapse)
           هر چیزی که ظاهر یا ناپدید می‌شود با این کلاس قد و شفافیتش نرم تغییر می‌کند
           (از تکنیک grid-template-rows بین 0fr و 1fr استفاده شده)
           ===================================================================== */
        .collapse {
            display: grid; grid-template-rows: 0fr; opacity: 0; transform: translateY(10px) scale(0.96);
            transition: grid-template-rows 0.5s var(--emph), opacity 0.35s var(--emph), transform 0.6s var(--spring);
        }
        .collapse.open { grid-template-rows: 1fr; opacity: 1; transform: none; }
        .collapse-inner { overflow: hidden; min-height: 0; }

        /* =====================================================================
           بخش ۴: هدر و نام دستگاه
           ===================================================================== */
        .topbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; }
        .brand { display: flex; align-items: center; gap: 12px; }
        h1 { margin: 0; font-size: 22px; font-weight: 600; letter-spacing: -0.2px; }
        /* لوگو: شکلش مدام بین چند فرم گرد و نیمه‌مربع تغییر می‌کند (Shape Morph) */
        .logo {
            width: 46px; height: 46px; display: grid; place-items: center; color: var(--on-primary);
            background: linear-gradient(135deg, var(--primary), #5eead4 150%);
            box-shadow: 0 10px 24px -8px var(--primary-glow-strong);
            animation: logoMorph 7s ease-in-out infinite;
        }
        .logo .ic { width: 26px; height: 26px; }
        @keyframes logoMorph {
            0%, 100% { border-radius: 16px; transform: rotate(0deg); }
            33% { border-radius: 28px 14px 28px 14px; transform: rotate(-6deg); }
            66% { border-radius: 50%; transform: rotate(6deg); }
        }

        /* فیلدهای متنی با لیبل شناور (Text Field) */
        .tf {
            position: relative; border-radius: 20px; background: var(--surface-high); border: 1.5px solid var(--outline-variant);
            transition: border-color 0.3s, box-shadow 0.4s var(--emph), background-color 0.3s, border-radius 0.45s var(--spring);
        }
        .tf:focus-within { border-color: var(--primary); box-shadow: 0 0 0 4px var(--primary-glow); background: var(--surface-higher); border-radius: 16px; }
        .tf input, .tf textarea {
            display: block; width: 100%; border: none; outline: none; background: transparent; color: var(--on-surface);
            font: inherit; font-size: 15px; padding: 26px 16px 8px; border-radius: inherit;
        }
        .tf textarea { resize: none; padding-top: 28px; min-height: 92px; }
        .tf label {
            position: absolute; left: 17px; top: 17px; color: var(--on-surface-variant); font-size: 15px; pointer-events: none;
            transform-origin: left top; transition: transform 0.4s var(--emph), color 0.25s;
        }
        .tf input:focus + label, .tf input:not(:placeholder-shown) + label,
        .tf textarea:focus + label, .tf textarea:not(:placeholder-shown) + label { transform: translateY(-10px) scale(0.78); }
        .tf:focus-within label { color: var(--primary); }
        .name-field input { color: var(--primary); font-weight: 600; }

        /* QR Code و آدرس سرور */
        .qr { display: flex; flex-direction: column; align-items: center; margin: 20px 0 2px; }
        .qr-box {
            background: #fff; padding: 10px; border-radius: 26px; width: 154px; height: 154px; display: grid; place-items: center;
            box-shadow: 0 16px 36px -14px rgba(0,0,0,0.5);
            transition: transform 0.6s var(--spring), border-radius 0.6s var(--spring);
        }
        .qr-box:hover { border-radius: 40px; transform: scale(1.05) rotate(-2deg); }
        .qr-box canvas { display: block; border-radius: 6px; }
        .url-chip {
            display: inline-flex; align-items: center; gap: 8px; margin-top: 14px; padding: 7px 14px; border-radius: 999px;
            border: 1px solid var(--outline-variant); background: var(--surface-high); color: var(--primary);
            font-family: ui-monospace, "SFMono-Regular", Menlo, monospace; font-size: 12px; cursor: pointer;
            transition: border-radius 0.4s var(--spring), transform 0.3s var(--spring), background-color 0.25s;
        }
        .url-chip:hover { border-radius: 12px; background: var(--surface-higher); }
        .url-chip:active { transform: scale(0.95); }
        .url-chip .ic { width: 15px; height: 15px; }

        /* =====================================================================
           بخش ۵: لیست گیرنده‌ها (Recipients)
           ===================================================================== */
        .section-head { display: flex; justify-content: space-between; align-items: center; margin: 22px 4px 8px; }
        .label { font-size: 12px; font-weight: 700; letter-spacing: 0.8px; text-transform: uppercase; color: var(--on-surface-variant); }
        .badge { font-size: 12px; font-weight: 700; padding: 4px 11px; border-radius: 999px; background: var(--primary-container); color: var(--on-primary-container); }

        .device-list {
            border-radius: 26px; background: var(--surface-high); border: 1.5px solid var(--outline-variant);
            padding: 6px; max-height: 226px; overflow-y: auto; transition: border-color 0.3s;
        }
        /* لرزش لیست هنگام ارسال بدون انتخاب گیرنده */
        .device-list.shake { animation: shake 0.55s var(--emph); }
        @keyframes shake {
            0%, 100% { transform: translateX(0); border-color: var(--outline-variant); }
            15% { transform: translateX(-9px); border-color: var(--error); }
            35% { transform: translateX(8px); border-color: var(--error); }
            55% { transform: translateX(-5px); border-color: var(--error); }
            75% { transform: translateX(3px); border-color: var(--error); }
        }
        .dev-tile {
            position: relative; overflow: hidden; display: flex; align-items: center; gap: 12px; padding: 10px 12px; margin-bottom: 4px;
            border-radius: 18px; cursor: pointer; font-size: 14px;
            transition: background-color 0.3s, border-radius 0.45s var(--spring), transform 0.3s var(--spring), color 0.3s;
        }
        .dev-tile:hover { background: var(--surface-high); }
        .dev-tile:active { transform: scale(0.98); }
        /* کاشی انتخاب‌شده رنگ ثانویه می‌گیرد و گردتر می‌شود */
        .dev-tile:has(input:checked) { background: var(--secondary-container); color: var(--on-secondary-container); border-radius: 24px; }
        .dev-tile.all { font-weight: 700; color: var(--primary); }
        .dev-tile.all:has(input:checked) { color: var(--on-secondary-container); }
        .dev-tile input { position: absolute; opacity: 0; pointer-events: none; }

        /* چک‌باکس سفارشی؛ تیک با انیمیشن کشیده می‌شود */
        .box {
            width: 22px; height: 22px; flex-shrink: 0; display: grid; place-items: center; border-radius: 8px; border: 2px solid var(--outline);
            transition: background-color 0.25s, border-color 0.25s, border-radius 0.45s var(--spring), transform 0.45s var(--spring), box-shadow 0.3s;
        }
        .box svg {
            width: 16px; height: 16px; fill: none; stroke: var(--on-primary); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round;
            stroke-dasharray: 24; stroke-dashoffset: 24; transition: stroke-dashoffset 0.45s 0.05s var(--emph);
        }
        .dev-tile input:checked + .box { background: var(--primary); border-color: var(--primary); border-radius: 7px; transform: scale(1.1); }
        .dev-tile input:checked + .box svg { stroke-dashoffset: 0; }
        .dev-tile input:focus-visible + .box { box-shadow: 0 0 0 4px var(--primary-glow); }

        .dev-ic { width: 36px; height: 36px; flex-shrink: 0; border-radius: 12px; display: grid; place-items: center; background: var(--surface-higher); transition: border-radius 0.45s var(--spring); }
        .dev-tile:hover .dev-ic { border-radius: 50%; }
        .dev-text { display: flex; flex-direction: column; min-width: 0; }
        .dev-name { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .dev-ip { font-size: 11px; opacity: 0.7; font-weight: 500; }
        .empty { margin: 8px 10px; font-size: 12px; color: var(--on-surface-variant); text-align: center; }

        /* =====================================================================
           بخش ۶: ناحیه انتخاب فایل + لیست فایل‌ها + نوار پیشرفت موجی
           ===================================================================== */
        .dropzone {
            position: relative; margin-top: 16px; padding: 22px 16px; text-align: center; cursor: pointer;
            border-radius: 28px; border: 2px dashed var(--outline);
            transition: border-color 0.3s, background-color 0.3s, transform 0.5s var(--spring), border-radius 0.5s var(--spring);
        }
        .dropzone:hover, .dropzone.drag { border-color: var(--primary); background: var(--primary-glow); }
        .dropzone.drag { transform: scale(1.035); border-radius: 38px; }
        .dropzone input { position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; }
        .dz-icon {
            width: 54px; height: 54px; margin: 0 auto 8px; display: grid; place-items: center; border-radius: 18px;
            background: var(--primary-container); color: var(--on-primary-container);
            animation: floaty 3.4s ease-in-out infinite; transition: border-radius 0.5s var(--spring);
        }
        .dz-icon .ic { width: 28px; height: 28px; }
        .dropzone:hover .dz-icon, .dropzone.drag .dz-icon { border-radius: 50%; }
        @keyframes floaty { 50% { transform: translateY(-6px); } }
        .dz-title { font-size: 14px; font-weight: 600; }
        .dz-sub { font-size: 12px; color: var(--on-surface-variant); margin-top: 2px; }

        #pending-box { margin-top: 14px; }
        .pending-list { max-height: 210px; overflow-y: auto; }
        .file-item {
            margin-bottom: 8px; padding: 10px 12px; border-radius: 22px; text-align: left;
            background: var(--surface-high); border: 1px solid var(--outline-variant);
            transition: background-color 0.3s, border-color 0.3s;
        }
        .file-row { display: flex; align-items: center; gap: 10px; }
        /* برچسب فرمت فایل (PDF, MP4, ...) ؛ هنگام آپلود شکلش مدام تغییر می‌کند */
        .file-ext {
            min-width: 42px; height: 42px; padding: 0 6px; flex-shrink: 0; display: grid; place-items: center; border-radius: 14px;
            background: var(--tertiary-container); color: var(--on-tertiary-container); font-size: 11px; font-weight: 800; letter-spacing: 0.3px;
        }
        .file-item.uploading .file-ext { animation: morph 2.4s ease-in-out infinite; }
        @keyframes morph { 50% { border-radius: 50%; } }
        .file-item.done .file-ext { background: var(--primary-container); color: var(--on-primary-container); }
        .file-item.error .file-ext { background: var(--error-container); color: var(--on-error-container); }
        .file-name { flex-grow: 1; min-width: 0; font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .file-meta { display: flex; justify-content: space-between; margin-top: 6px; font-size: 11px; font-weight: 700; color: var(--on-surface-variant); }
        .file-item.done .state { color: var(--primary); }
        .file-item.error .state { color: var(--error); }
        .file-item.canceled .state { color: var(--error); }

        /* نوار پیشرفت موجی (Wavy Progress) ؛ قسمت پر شده موج می‌زند و جلو می‌رود */
        .prog { position: relative; height: 14px; margin-top: 8px; }
        .prog-track { position: absolute; left: 0; right: 0; top: 5px; height: 4px; border-radius: 4px; background: var(--surface-higher); }
        .prog-wave {
            position: absolute; left: 0; top: 0; height: 14px; width: 0%; max-width: 100%; background: var(--primary);
            -webkit-mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='14' viewBox='0 0 20 14'%3E%3Cpath d='M-10 7Q-5 1 0 7T10 7T20 7T30 7' fill='none' stroke='black' stroke-width='3.4' stroke-linecap='round'/%3E%3C/svg%3E") repeat-x 0 0 / 20px 14px;
            mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='14' viewBox='0 0 20 14'%3E%3Cpath d='M-10 7Q-5 1 0 7T10 7T20 7T30 7' fill='none' stroke='black' stroke-width='3.4' stroke-linecap='round'/%3E%3C/svg%3E") repeat-x 0 0 / 20px 14px;
            transition: width 0.4s var(--emph), background-color 0.3s; animation: waveflow 0.9s linear infinite;
        }
        @keyframes waveflow { to { -webkit-mask-position: 20px 0; mask-position: 20px 0; } }
        .file-item.done .prog-wave { animation: none; }
        .file-item.error .prog-wave { background: var(--error); animation: none; }

        /* =====================================================================
           بخش ۷: شمارنده متن و آخرین دریافتی
           ===================================================================== */
        .counter { display: flex; justify-content: flex-end; margin: 6px 6px 14px; font-size: 12px; font-weight: 700; color: var(--on-surface-variant); transition: color 0.3s; }
        .counter.danger { color: var(--error); animation: nudge 0.4s var(--emph); }
        @keyframes nudge { 30% { transform: translateX(-4px); } 60% { transform: translateX(3px); } }

        #latest-container { margin-top: 16px; }
        .latest { padding: 14px 16px; border-radius: 26px; text-align: left; background: var(--surface-high); border: 1.5px solid var(--outline-variant); }
        .latest-title { font-size: 11px; font-weight: 800; letter-spacing: 0.8px; text-transform: uppercase; color: var(--primary); margin-bottom: 8px; }
        .latest-content {
            font-family: ui-monospace, Menlo, monospace; font-size: 13px; word-break: break-all; white-space: pre-wrap;
            display: -webkit-box; -webkit-line-clamp: 5; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis;
        }

        /* =====================================================================
           بخش ۸: پنجره‌های پاپ‌آپ (دیالوگ و تاریخچه) با بلور پس‌زمینه
           ===================================================================== */
        .overlay {
            position: fixed; inset: 0; z-index: 1000; display: flex; align-items: center; justify-content: center; padding: 16px;
            background: var(--scrim); opacity: 0; visibility: hidden;
            -webkit-backdrop-filter: blur(0px); backdrop-filter: blur(0px);
            transition: opacity 0.4s var(--emph), backdrop-filter 0.5s var(--emph), -webkit-backdrop-filter 0.5s var(--emph), visibility 0s linear 0.55s;
        }
        .overlay.open {
            opacity: 1; visibility: visible; -webkit-backdrop-filter: blur(16px) saturate(1.2); backdrop-filter: blur(16px) saturate(1.2);
            transition: opacity 0.4s var(--emph), backdrop-filter 0.5s var(--emph), -webkit-backdrop-filter 0.5s var(--emph), visibility 0s;
        }
        .dialog {
            width: 100%; background: var(--glass); border: 1px solid var(--glass-border); box-shadow: var(--shadow);
            -webkit-backdrop-filter: blur(40px) saturate(1.6); backdrop-filter: blur(40px) saturate(1.6);
            opacity: 0; transform: translateY(50px) scale(0.86);
            transition: transform 0.6s var(--spring), opacity 0.35s var(--emph);
        }
        .overlay.open .dialog { opacity: 1; transform: none; }
        .overlay:not(.open) .dialog { transition: transform 0.4s var(--emph), opacity 0.3s var(--emph); }

        /* دیالوگ پیام (مثلا فایل حذف شده) */
        .alert-dialog { max-width: 340px; border-radius: 34px; padding: 26px 24px 18px; text-align: center; }
        .dlg-icon { width: 60px; height: 60px; margin: 0 auto 14px; display: grid; place-items: center; border-radius: 22px; background: var(--error-container); color: var(--on-error-container); }
        .dlg-icon .ic { width: 30px; height: 30px; }
        .overlay.open .dlg-icon { animation: wobble 0.9s 0.2s var(--spring); }
        @keyframes wobble { 0% { transform: scale(0.4) rotate(-30deg); border-radius: 50%; } 60% { transform: scale(1.12) rotate(8deg); } 100% { transform: none; } }
        .alert-dialog h2 { margin: 0 0 8px; font-size: 22px; font-weight: 600; }
        .alert-dialog p { margin: 0 0 18px; font-size: 14px; line-height: 1.55; color: var(--on-surface-variant); }
        .dlg-actions { display: flex; justify-content: flex-end; }

        /* پنجره تاریخچه */
        .sheet { max-width: 470px; max-height: 82vh; border-radius: 34px; padding: 20px; display: flex; flex-direction: column; }
        .sheet-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
        .sheet-head h2 { margin: 0; font-size: 20px; font-weight: 600; color: var(--primary); }
        .sheet-body { overflow-y: auto; flex-grow: 1; padding-right: 2px; }
        .history-item { margin-bottom: 8px; padding: 12px 14px; border-radius: 20px; font-size: 12px; text-align: left; background: var(--surface-high); border-left: 4px solid var(--outline); }
        .history-item.inbound { border-left-color: var(--primary); }
        .history-item.outbound { border-left-color: #60a5fa; }
        .hist-meta { display: flex; justify-content: space-between; gap: 8px; margin-bottom: 6px; font-size: 11px; font-weight: 700; color: var(--on-surface-variant); }
        .hist-content {
            font-family: ui-monospace, Menlo, monospace; word-break: break-all; white-space: pre-wrap;
            display: -webkit-box; -webkit-line-clamp: 5; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis;
        }

        /* =====================================================================
           بخش ۹: اسنک‌بار (پیام‌های کوتاه و هشدارها داخل خود UI)
           ===================================================================== */
        .snackbar {
            position: fixed; left: 50%; bottom: 24px; z-index: 1200; max-width: calc(100vw - 32px); width: max-content;
            display: flex; align-items: center; gap: 12px; padding: 12px 10px 12px 16px; border-radius: 22px;
            background: var(--inverse); color: var(--on-inverse); font-size: 14px; font-weight: 600;
            box-shadow: 0 18px 40px -12px rgba(0,0,0,0.55);
            opacity: 0; visibility: hidden; transform: translate(-50%, 140%) scale(0.9);
            transition: transform 0.6s var(--spring), opacity 0.3s var(--emph), visibility 0s linear 0.6s;
        }
        .snackbar.open { opacity: 1; visibility: visible; transform: translate(-50%, 0) scale(1); transition: transform 0.6s var(--spring), opacity 0.3s var(--emph), visibility 0s; }
        .snackbar .sn-icon { display: grid; place-items: center; }
        .snackbar.error .sn-icon { color: #e5484d; }
        .snackbar.success .sn-icon { color: #12a06c; }
        .snackbar.info .sn-icon { color: #3b82f6; }
        .sn-action { border: none; background: transparent; color: inherit; font: inherit; font-weight: 800; cursor: pointer; padding: 6px 12px; border-radius: 14px; opacity: 0.8; transition: background-color 0.25s, opacity 0.25s, border-radius 0.4s var(--spring); }
        .sn-action:hover { opacity: 1; background: rgba(128,128,128,0.2); border-radius: 8px; }

        /* انیمیشن چرخش دایره‌ای تغییر تم (View Transitions API) */
        ::view-transition-old(root), ::view-transition-new(root) { animation: none; mix-blend-mode: normal; }
        ::view-transition-old(root) { z-index: 1; }
        ::view-transition-new(root) { z-index: 2; }
        /* اگر مرورگر View Transitions نداشت، تغییر رنگ‌ها نرم انجام می‌شود */
        body.theme-anim, body.theme-anim * { transition: background-color 0.5s, color 0.5s, border-color 0.5s !important; }

        /* احترام به تنظیم «کاهش حرکت» سیستم‌عامل */
        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after { animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; transition-duration: 0.01ms !important; }
        }
        @media (max-width: 480px) { .card { padding: 20px 18px; border-radius: 32px; } }
    </style>
</head>
<body>

    <!-- پس‌زمینه لکه‌های رنگی بلور شده -->
    <div class="bg" aria-hidden="true"><i class="blob b1"></i><i class="blob b2"></i><i class="blob b3"></i></div>

    <!-- ===================== کارت اصلی برنامه (همه چیز داخل یک قاب) ===================== -->
    <main class="card">
        <!-- هدر: لوگو + عنوان + دکمه تغییر تم -->
        <header class="topbar rise" style="--i:0">
            <div class="brand">
                <div class="logo"><i class="slot" data-ic="swap"></i></div>
                <h1>Web LocalSend Pro</h1>
            </div>
            <button class="icon-btn ripple" id="theme-btn" onclick="switchTheme(event)" aria-label="Change theme">
                <i class="slot" data-ic="sun"></i><i class="slot" data-ic="moon"></i>
            </button>
        </header>

        <!-- نام نمایشی این دستگاه؛ برای بقیه دستگاه‌ها دیده می‌شود -->
        <div class="tf name-field rise" style="--i:1">
            <input type="text" id="my-name-input" placeholder=" " autocomplete="off" oninput="updateMyName(this.value)">
            <label for="my-name-input">Your device name</label>
        </div>

        <!-- QR Code و آدرس سرور (با کلیک کپی می‌شود) -->
        <section class="qr rise" style="--i:2">
            <div class="qr-box"><canvas id="qr-code"></canvas></div>
            <button class="url-chip ripple" id="url-chip" onclick="copyServerUrl()" title="Copy link"><span>SERVER_URL_PLACEHOLDER</span><i class="slot" data-ic="copy"></i></button>
        </section>

        <!-- انتخاب گیرنده‌ها: چند دستگاه همزمان یا همه -->
        <section class="rise" style="--i:3">
            <div class="section-head">
                <span class="label">Target Recipients</span>
                <span class="badge" id="recipient-badge">0 / 0 selected</span>
            </div>
            <div class="device-list" id="device-checkbox-list">
                <label class="dev-tile all ripple">
                    <input type="checkbox" id="check-all-devices" onchange="toggleSelectAll(this)">
                    <span class="box"><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></span>
                    <span class="dev-text"><span class="dev-name">All (Send to Everyone)</span></span>
                </label>
                <div id="dynamic-devices-box"></div>
                <div class="collapse open" id="devices-empty"><div class="collapse-inner"><p class="empty">Waiting for other devices...</p></div></div>
            </div>
        </section>

        <!-- ناحیه انتخاب فایل: انتخاب فایل ارسال را شروع نمی‌کند، فقط فایل‌ها را به لیست اضافه می‌کند -->
        <div class="dropzone rise" id="dropzone" style="--i:4">
            <input type="file" id="file-input" multiple onchange="addSelectedFiles()">
            <div class="dz-icon"><i class="slot" data-ic="upload"></i></div>
            <div class="dz-title">Drag &amp; Drop files here</div>
            <div class="dz-sub">or click to select</div>
        </div>

        <!-- لیست فایل‌های انتخاب‌شده (نام، فرمت، حجم، نوار پیشرفت) + دکمه ارسال و انصراف -->
        <div class="collapse" id="pending-box">
            <div class="collapse-inner">
                <div class="pending-list" id="pending-list"></div>
                <div class="btn-row">
                    <button id="send-files-btn" onclick="startUpload()" class="btn ripple"><i class="slot" data-ic="send"></i><span class="sw" id="send-files-label">Send Files</span></button>
                    <button id="cancel-files-btn" onclick="cancelAllFiles()" class="btn tonal ripple"><i class="slot" data-ic="close"></i><span class="sw" id="cancel-files-label">Clear Selection</span></button>
                </div>
            </div>
        </div>

        <!-- ارسال متن -->
        <section class="rise" style="--i:5; margin-top:16px;">
            <div class="tf" id="text-field">
                <textarea id="text-input" rows="3" placeholder=" " oninput="validateCharacterCount()"></textarea>
                <label for="text-input">Type message or paste links to send...</label>
            </div>
            <div class="counter" id="char-counter-label">Remaining: 10,000</div>
            <button id="submit-text-btn" onclick="sendText()" class="btn ripple"><i class="slot" data-ic="send"></i><span>Send Securely</span></button>
            <button onclick="toggleModal(true)" class="btn tonal ripple"><i class="slot" data-ic="history"></i><span>View Full History</span></button>
        </section>

        <!-- آخرین پیام یا فایل دریافتی -->
        <div class="collapse" id="latest-container">
            <div class="collapse-inner">
                <div class="latest" id="latest-card">
                    <div class="latest-title" id="latest-type">Latest Received</div>
                    <div class="latest-content" id="latest-body">No data yet.</div>
                    <div id="latest-action-zone"></div>
                </div>
            </div>
        </div>
    </main>

    <!-- ===================== پنجره تاریخچه ===================== -->
    <div id="history-modal" class="overlay" onclick="if(event.target===this) toggleModal(false)">
        <div class="dialog sheet" role="dialog" aria-modal="true">
            <div class="sheet-head">
                <h2>Transaction History</h2>
                <button onclick="toggleModal(false)" class="icon-btn ripple" aria-label="Close"><i class="slot" data-ic="close"></i></button>
            </div>
            <div class="sheet-body">
                <div class="collapse open" id="history-empty"><div class="collapse-inner"><p class="empty">No history records found.</p></div></div>
                <div id="history-list"></div>
            </div>
        </div>
    </div>

    <!-- ===================== دیالوگ پیام (مثلا فایل حذف شده؛ سرور خاموش نمی‌شود) ===================== -->
    <div id="alert-modal" class="overlay" onclick="if(event.target===this) closePopup()">
        <div class="dialog alert-dialog" role="alertdialog" aria-modal="true">
            <div class="dlg-icon" id="alert-icon"></div>
            <h2 id="alert-title">Notice</h2>
            <p id="alert-message"></p>
            <div class="dlg-actions"><button onclick="closePopup()" class="btn text ripple">OK</button></div>
        </div>
    </div>

    <!-- ===================== اسنک‌بار: هشدارها و پیام‌های کوتاه ===================== -->
    <div id="snackbar" class="snackbar" role="status" aria-live="polite">
        <span class="sn-icon" id="sn-icon"></span><span id="sn-text"></span>
        <button class="sn-action" onclick="hideSnack()">OK</button>
    </div>

    <script>
        // ================= بخش ۱: ابزارهای پایه و آیکون‌ها =================
        const $ = (id) => document.getElementById(id);
        // اگر کاربر در سیستم‌عامل «کاهش حرکت» را روشن کرده باشد، انیمیشن‌های جاوااسکریپتی خاموش می‌شوند
        const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

        // آیکون‌های SVG داخل خود کد (بدون نیاز به اینترنت)
        const ICON = {
            swap: '<svg class="ic" viewBox="0 0 24 24"><path d="M6.99 11L3 15l3.99 4v-3H14v-2H6.99v-3zM21 9l-3.99-4v3H10v2h7.01v3L21 9z"/></svg>',
            sun: '<svg class="ic sun" viewBox="0 0 24 24"><path d="M6.76 4.84l-1.8-1.79-1.41 1.41 1.79 1.79 1.42-1.41zM4 10.5H1v2h3v-2zm9-9.95h-2V3.5h2V.55zm7.45 3.91l-1.41-1.41-1.79 1.79 1.41 1.41 1.79-1.79zm-3.21 13.7l1.79 1.8 1.41-1.41-1.8-1.79-1.4 1.4zM20 10.5v2h3v-2h-3zm-8-5c-3.31 0-6 2.69-6 6s2.69 6 6 6 6-2.69 6-6-2.69-6-6-6zm-1 16.95h2V19.5h-2v2.95zm-7.45-3.91l1.41 1.41 1.79-1.8-1.41-1.41-1.79 1.8z"/></svg>',
            moon: '<svg class="ic moon" viewBox="0 0 24 24"><path d="M12 3c-4.97 0-9 4.03-9 9s4.03 9 9 9 9-4.03 9-9c0-.46-.04-.92-.1-1.36-.98 1.37-2.58 2.26-4.4 2.26-2.98 0-5.4-2.42-5.4-5.4 0-1.81.89-3.42 2.26-4.4-.44-.06-.9-.1-1.36-.1z"/></svg>',
            copy: '<svg class="ic" viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>',
            upload: '<svg class="ic" viewBox="0 0 24 24"><path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM14 13v4h-4v-4H7l5-5 5 5h-3z"/></svg>',
            send: '<svg class="ic" viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>',
            close: '<svg class="ic" viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>',
            history: '<svg class="ic" viewBox="0 0 24 24"><path d="M13 3a9 9 0 0 0-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42A8.954 8.954 0 0 0 13 21a9 9 0 0 0 0-18zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z"/></svg>',
            download: '<svg class="ic" viewBox="0 0 24 24"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>',
            phone: '<svg class="ic" viewBox="0 0 24 24"><path d="M17 1.01L7 1c-1.1 0-2 .9-2 2v18c0 1.1.9 2 2 2h10c1.1 0 2-.9 2-2V3c0-1.1-.9-1.99-2-1.99zM17 19H7V5h10v14z"/></svg>',
            laptop: '<svg class="ic" viewBox="0 0 24 24"><path d="M20 18c1.1 0 1.99-.9 1.99-2L22 6c0-1.1-.9-2-2-2H4c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2H0v2h24v-2h-4zM4 6h16v10H4V6z"/></svg>',
            ok: '<svg class="ic" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>',
            error: '<svg class="ic" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>',
            info: '<svg class="ic" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>'
        };
        // جای‌گذاری آیکون‌ها در همه اسلات‌های صفحه
        document.querySelectorAll('[data-ic]').forEach(el => { el.innerHTML = ICON[el.dataset.ic] || ''; });

        // تبدیل متن به متن امن HTML (جلوگیری از اجرای کد داخل نام فایل یا نام دستگاه - XSS)
        function escapeHtml(str) {
            return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                              .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        }

        // تبدیل تعداد بایت به متن خوانا (KB / MB / GB)
        function formatBytes(bytes) {
            if (bytes < 1024) return bytes + ' B';
            const units = ['KB', 'MB', 'GB', 'TB'];
            let value = bytes;
            let i = -1;
            do { value /= 1024; i++; } while (value >= 1024 && i < units.length - 1);
            return value.toFixed(value >= 100 ? 0 : 1) + ' ' + units[i];
        }

        // استخراج فرمت فایل از روی پسوند (آخرین نقطه نام فایل)
        function getFileExt(name) {
            const dot = name.lastIndexOf('.');
            if (dot <= 0 || dot === name.length - 1) return 'FILE';
            return name.substring(dot + 1).toUpperCase().substring(0, 5);
        }

        // ================= بخش ۲: موتور انیمیشن =================
        // باز/بسته کردن نرم یک عنصر collapse
        function setCollapse(el, open) { el.classList.toggle('open', open); }

        // اضافه کردن نرم یک آیتم به لیست: اول با ارتفاع صفر ساخته می‌شود و بعد باز می‌شود
        function enterNode(parent, node, delay, before) {
            if (delay) node.style.transitionDelay = delay + 'ms';
            parent.insertBefore(node, before || null);
            void node.offsetHeight;   // اجبار مرورگر به محاسبه استایل اولیه تا انیمیشن اجرا شود
            requestAnimationFrame(() => {
                node.classList.add('open');
                if (delay) setTimeout(() => { node.style.transitionDelay = ''; }, delay + 900);
            });
        }

        // حذف نرم یک آیتم: اول جمع می‌شود و بعد از DOM پاک می‌شود
        function leaveNode(node) {
            node.classList.add('leaving');
            node.classList.remove('open');
            setTimeout(() => node.remove(), 700);
        }

        // تغییر نرم متن (محو شدن به بالا و ورود از پایین)
        function swapText(el, txt) {
            if (el.textContent === txt && !el._busy) return;
            if (reduceMotion || !el.animate) { el.textContent = txt; return; }
            el._next = txt;
            if (el._busy) return;
            el._busy = true;
            el.animate([{ opacity: 1, transform: 'translateY(0)' }, { opacity: 0, transform: 'translateY(-7px)' }], { duration: 120, easing: 'ease-in' }).onfinish = () => {
                el.textContent = el._next;
                el.animate([{ opacity: 0, transform: 'translateY(7px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 260, easing: 'cubic-bezier(0.2,0,0,1)' }).onfinish = () => {
                    el._busy = false;
                    if (el.textContent !== el._next) swapText(el, el._next);
                };
            };
        }

        // پرش کوتاه (Pop) برای جلب توجه به یک عنصر
        function popEl(el) {
            if (reduceMotion || !el.animate) return;
            el.animate([{ transform: 'scale(1)' }, { transform: 'scale(1.18)' }, { transform: 'scale(1)' }], { duration: 420, easing: 'cubic-bezier(0.34,1.56,0.64,1)' });
        }

        // لرزش یک عنصر (برای خطا)
        function shake(el) {
            el.classList.remove('shake');
            void el.offsetWidth;
            el.classList.add('shake');
            el.addEventListener('animationend', () => el.classList.remove('shake'), { once: true });
        }

        // افکت موج هنگام کلیک روی هر عنصر با کلاس ripple
        document.addEventListener('pointerdown', (e) => {
            const t = e.target.closest('.ripple');
            if (!t || t.disabled) return;
            const r = t.getBoundingClientRect();
            const size = Math.max(r.width, r.height) * 2;
            const s = document.createElement('span');
            s.className = 'ripple-wave';
            s.style.width = s.style.height = size + 'px';
            s.style.left = (e.clientX - r.left - size / 2) + 'px';
            s.style.top = (e.clientY - r.top - size / 2) + 'px';
            t.appendChild(s);
            setTimeout(() => s.remove(), 700);
        });

        // ================= بخش ۳: اسنک‌بار و دیالوگ‌ها (همه هشدارها داخل UI) =================
        let snackTimer = null;
        // نمایش پیام کوتاه؛ type یکی از: info | success | error
        function showSnack(message, type, duration) {
            type = type || 'info';
            const sb = $('snackbar');
            const wasOpen = sb.classList.contains('open');
            $('sn-text').textContent = message;
            $('sn-icon').innerHTML = type === 'error' ? ICON.error : (type === 'success' ? ICON.ok : ICON.info);
            sb.className = 'snackbar open ' + type;
            if (wasOpen && sb.animate && !reduceMotion) {
                sb.animate([{ transform: 'translate(-50%, 0) scale(0.94)' }, { transform: 'translate(-50%, 0) scale(1)' }], { duration: 350, easing: 'cubic-bezier(0.34,1.56,0.64,1)' });
            }
            clearTimeout(snackTimer);
            snackTimer = setTimeout(hideSnack, duration || 3800);
        }
        function hideSnack() { $('snackbar').classList.remove('open'); }

        // دیالوگ خطا با عنوان و متن دلخواه
        function showPopup(title, message) {
            $('alert-icon').innerHTML = ICON.error;
            $('alert-title').textContent = title;
            $('alert-message').textContent = message;
            $('alert-modal').classList.add('open');
        }
        function closePopup() { $('alert-modal').classList.remove('open'); }

        // باز و بسته کردن پنجره تاریخچه
        function toggleModal(show) {
            $('history-modal').classList.toggle('open', show);
            if (show) updateData();
        }

        // کلید Esc بالاترین پنجره باز را می‌بندد
        window.addEventListener('keydown', (e) => {
            if (e.key !== 'Escape') return;
            if ($('alert-modal').classList.contains('open')) closePopup();
            else if ($('history-modal').classList.contains('open')) toggleModal(false);
        });

        // ================= بخش ۴: هویت دستگاه =================
        // هر مرورگر یک شناسه تصادفی می‌گیرد و در localStorage ذخیره می‌شود تا با رفرش عوض نشود
        if (!localStorage.getItem('client_id')) {
            localStorage.setItem('client_id', 'dev_' + Math.random().toString(36).substring(2, 11));
        }
        const clientId = localStorage.getItem('client_id');

        // ساخت نام پیش‌فرض دستگاه از روی User-Agent مرورگر (مثلا Windows PC (a1b2))
        function getDeviceFriendlyName() {
            const ua = navigator.userAgent;
            let os = "Unknown Device";
            if (/android/i.test(ua)) os = "Android Phone";
            else if (/iPad|iPhone|iPod/.test(ua)) os = "iPhone/iPad";
            else if (/windows/i.test(ua)) os = "Windows PC";
            else if (/linux/i.test(ua)) os = "Linux PC";
            else if (/mac/i.test(ua)) os = "Macbook";
            return os + " (" + clientId.substring(4, 8) + ")";
        }

        if (!localStorage.getItem('custom_nickname')) {
            localStorage.setItem('custom_nickname', getDeviceFriendlyName());
        }
        let myName = localStorage.getItem('custom_nickname');
        $('my-name-input').value = myName;

        // بازیابی تم ذخیره‌شده (تیره/روشن)
        if (localStorage.getItem('cfg_theme') === 'light') {
            document.body.classList.add('light-theme');
        }

        let selectedClientIds = new Set();   // شناسه دستگاه‌های انتخاب‌شده به عنوان گیرنده
        const MAX_CHARS = 10000;             // سقف تعداد کاراکتر پیام متنی

        // تغییر تم با انیمیشن دایره‌ای از محل کلیک (اگر مرورگر پشتیبانی کند)
        function switchTheme(ev) {
            const apply = () => {
                document.body.classList.toggle('light-theme');
                localStorage.setItem('cfg_theme', document.body.classList.contains('light-theme') ? 'light' : 'dark');
            };
            if (!document.startViewTransition || reduceMotion) {
                document.body.classList.add('theme-anim');
                apply();
                setTimeout(() => document.body.classList.remove('theme-anim'), 650);
                return;
            }
            const x = ev.clientX, y = ev.clientY;
            const r = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
            const t = document.startViewTransition(apply);
            t.ready.then(() => {
                document.documentElement.animate(
                    { clipPath: ['circle(0px at ' + x + 'px ' + y + 'px)', 'circle(' + r + 'px at ' + x + 'px ' + y + 'px)'] },
                    { duration: 700, easing: 'cubic-bezier(0.2,0,0,1)', pseudoElement: '::view-transition-new(root)' }
                );
            }).catch(() => {});
        }

        // تغییر نام دستگاه و اطلاع دادن به سرور
        function updateMyName(val) {
            let cleanName = val.trim();
            if (!cleanName) cleanName = "Anonymous";
            myName = cleanName;
            localStorage.setItem('custom_nickname', cleanName);
            pingServer();
        }

        // ================= بخش ۵: شمارنده کاراکتر =================
        // Live Integrity Engine for Input Text Fields
        // با هر تایپ، کاراکترهای باقی‌مانده را حساب می‌کند و اگر از حد گذشت دکمه ارسال را غیرفعال می‌کند
        function validateCharacterCount() {
            const textInput = $('text-input');
            const counterLabel = $('char-counter-label');
            const submitBtn = $('submit-text-btn');

            const remaining = MAX_CHARS - textInput.value.length;

            if (remaining >= 0) {
                counterLabel.innerText = "Remaining: " + remaining.toLocaleString();
                counterLabel.classList.remove('danger');
                submitBtn.disabled = false;
            } else {
                counterLabel.innerText = "Limit Exceeded By: " + Math.abs(remaining).toLocaleString();
                counterLabel.classList.add('danger');
                submitBtn.disabled = true;
            }
        }

        // ساخت QR Code بعد از لود شدن صفحه
        window.addEventListener('DOMContentLoaded', () => {
            if (typeof QRious !== 'undefined') {
                new QRious({ element: $('qr-code'), value: "SERVER_URL_PLACEHOLDER", size: 132 });
            }
        });

        // اگر میزبان (localhost) صفحه را ببندد، به سرور خبر می‌دهیم تا خاموش شود
        window.addEventListener('pagehide', () => {
            if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
                navigator.sendBeacon('/api/shutdown');
            }
        });

        // ================= بخش ۶: کپی متن =================
        // کپی متن در کلیپ‌بورد؛ اگر مرورگر clipboard API نداشت از روش جایگزین استفاده می‌شود
        function copyRaw(text, onSuccess) {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(onSuccess).catch(() => runFallbackCopyEngine(text, onSuccess));
            } else {
                runFallbackCopyEngine(text, onSuccess);
            }
        }

        function copyTextFromElement(targetElement, buttonId) {
            const btnSpan = $(buttonId);
            copyRaw(targetElement.innerText, () => {
                if (btnSpan) {
                    swapText(btnSpan, "Copied!");
                    setTimeout(() => swapText(btnSpan, "Copy Text"), 2000);
                }
            });
        }

        // کپی آدرس سرور با کلیک روی برچسب زیر QR
        function copyServerUrl() {
            copyRaw($('url-chip').innerText.trim(), () => showSnack('Link copied to clipboard', 'success', 2200));
        }

        // روش جایگزین کپی: ساخت یک textarea مخفی و اجرای دستور execCommand('copy')
        function runFallbackCopyEngine(text, successCallback) {
            try {
                const textArea = document.createElement("textarea");
                textArea.value = text;
                textArea.style.position = "fixed";
                textArea.style.left = "-9999px";
                textArea.style.top = "-9999px";
                document.body.appendChild(textArea);
                textArea.focus();
                textArea.select();
                textArea.setSelectionRange(0, 99999);
                const successful = document.execCommand('copy');
                document.body.removeChild(textArea);
                if (successful) successCallback();
            } catch (err) {}
        }

        // ================= بخش ۷: انتخاب گیرنده‌ها =================
        // لیست چک‌باکس‌های دستگاه‌های فعلی (به جز آیتم‌هایی که در حال حذف‌شدن هستند)
        function peerBoxes() {
            return Array.from(document.querySelectorAll('#dynamic-devices-box [data-id]:not(.leaving) .device-single-checkbox'));
        }

        // به‌روزرسانی نشان «۲ / ۳ selected» با یک پرش کوتاه
        function updateRecipientBadge() {
            const txt = selectedClientIds.size + ' / ' + peerBoxes().length + ' selected';
            const el = $('recipient-badge');
            if (el.textContent !== txt) { el.textContent = txt; popEl(el); }
        }

        // چک‌باکس «All» همیشه با وضعیت بقیه هماهنگ می‌ماند
        function syncAllCheckbox() {
            const boxes = peerBoxes();
            $('check-all-devices').checked = boxes.length > 0 && boxes.every(b => b.checked);
        }

        // چک‌باکس «All»: همه دستگاه‌ها را تیک می‌زند یا برمی‌دارد
        function toggleSelectAll(master) {
            const boxes = peerBoxes();
            if (boxes.length === 0) {
                master.checked = false;
                showSnack('No other devices are online yet', 'info');
                return;
            }
            selectedClientIds.clear();
            boxes.forEach(box => {
                box.checked = master.checked;
                if (master.checked) selectedClientIds.add(box.value);
            });
            updateRecipientBadge();
        }

        // تغییر وضعیت چک‌باکس یک دستگاه
        function handleSingleCheckboxChange(box) {
            if (box.checked) selectedClientIds.add(box.value);
            else selectedClientIds.delete(box.value);
            syncAllCheckbox();
            updateRecipientBadge();
        }

        // اگر گیرنده انتخاب نشده باشد، هشدار داخل UI نشان می‌دهد و رشته خالی برمی‌گرداند
        function getTargets() {
            const ids = Array.from(selectedClientIds).join(',');
            if (!ids) {
                showSnack('Select at least one recipient device first', 'error');
                shake($('device-checkbox-list'));
            }
            return ids;
        }

        // ping: هر ۴ ثانیه به سرور می‌گوید «من هنوز آنلاینم» و نامم را می‌فرستد
        async function pingServer() {
            try {
                await fetch('/api/ping', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body: `client_id=${clientId}&name=${encodeURIComponent(myName)}`
                });
            } catch (e) {}
        }

        // ساخت یک کاشی دستگاه (با آیکون موبایل یا لپ‌تاپ بر اساس نام)
        function buildDeviceNode(id) {
            const n = document.createElement('div');
            n.className = 'collapse';
            n.dataset.id = id;
            n.innerHTML = `<div class="collapse-inner"><label class="dev-tile ripple">
                <input type="checkbox" class="device-single-checkbox" onchange="handleSingleCheckboxChange(this)">
                <span class="box"><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></span>
                <span class="dev-ic"></span>
                <span class="dev-text"><span class="dev-name"></span><span class="dev-ip"></span></span>
            </label></div>`;
            const input = n.querySelector('input');
            input.value = id;
            input.checked = selectedClientIds.has(id);
            return n;
        }

        // نمایش لیست دستگاه‌های آنلاین؛ فقط تفاوت‌ها اعمال می‌شود (بدون پرش و چشمک زدن)
        function renderDeviceCheckboxes(devices) {
            const box = $('dynamic-devices-box');
            const peerIds = Object.keys(devices).filter(id => id !== clientId);

            // دستگاه‌هایی که رفته‌اند: از انتخاب‌ها خارج و با انیمیشن حذف می‌شوند
            const existing = new Map();
            box.querySelectorAll('[data-id]:not(.leaving)').forEach(n => existing.set(n.dataset.id, n));
            existing.forEach((node, id) => {
                if (!peerIds.includes(id)) { selectedClientIds.delete(id); leaveNode(node); existing.delete(id); }
            });

            // دستگاه‌های جدید اضافه و قدیمی‌ها به‌روز می‌شوند
            peerIds.forEach((id, i) => {
                const dev = devices[id];
                let node = existing.get(id);
                if (!node) {
                    node = buildDeviceNode(id);
                    enterNode(box, node, firstSync ? i * 70 : 0);
                }
                node.querySelector('.dev-name').textContent = dev.name;
                node.querySelector('.dev-ip').textContent = dev.ip;
                node.querySelector('.dev-ic').innerHTML = /phone|iphone|ipad/i.test(dev.name) ? ICON.phone : ICON.laptop;
            });

            setCollapse($('devices-empty'), peerIds.length === 0);
            syncAllCheckbox();
            updateRecipientBadge();
        }

        // ================= بخش ۸: انتخاب، پیش‌نمایش و آپلود فایل =================
        // pendingFiles: لیست فایل‌های انتخاب‌شده؛ هر آیتم = { id, file, status, xhr, loaded, total }
        // status یکی از: pending (آماده) | uploading (در حال ارسال) | done (ارسال شد) | error (خطا) | canceled (لغو)
        let pendingFiles = [];
        let fileCounter = 0;          // شمارنده برای ساخت id یکتا برای هر فایل
        let isUploading = false;      // آیا الان صف آپلود در حال کار است؟
        let cancelRequested = false;  // آیا کاربر دکمه انصراف کلی را زده؟

        // انیمیشن حالت Drag روی ناحیه انتخاب فایل
        const dz = $('dropzone');
        ['dragenter', 'dragover'].forEach(ev => dz.addEventListener(ev, () => dz.classList.add('drag')));
        ['dragleave', 'drop'].forEach(ev => dz.addEventListener(ev, () => dz.classList.remove('drag')));

        // وقتی کاربر فایل انتخاب یا Drop کرد: فایل‌ها فقط به لیست اضافه می‌شوند (ارسال خودکار نیست)
        function addSelectedFiles() {
            const fileInput = $('file-input');
            for (const file of fileInput.files) {
                pendingFiles.push({ id: ++fileCounter, file: file, status: 'pending', xhr: null, loaded: 0, total: file.size });
            }
            fileInput.value = '';   // خالی می‌کنیم تا بتوان همان فایل را دوباره انتخاب کرد
            dz.classList.remove('drag');
            renderPending();
        }

        // ساخت کاشی یک فایل (فرمت + نام + حجم + نوار پیشرفت موجی + دکمه انصراف)
        function buildFileNode(it) {
            const n = document.createElement('div');
            n.className = 'collapse';
            n.dataset.fid = it.id;
            const safeName = escapeHtml(it.file.name);
            n.innerHTML = `<div class="collapse-inner"><div class="file-item" id="file-item-${it.id}">
                <div class="file-row">
                    <span class="file-ext">${escapeHtml(getFileExt(it.file.name))}</span>
                    <span class="file-name" title="${safeName}">${safeName}</span>
                    <button class="icon-btn small ripple" title="Cancel this file" onclick="removeFile(${it.id})">${ICON.close}</button>
                </div>
                <div class="file-meta"><span id="file-size-${it.id}"></span><span class="state sw" id="file-state-${it.id}"></span></div>
                <div class="collapse" id="file-track-${it.id}"><div class="collapse-inner">
                    <div class="prog"><div class="prog-track"></div><div class="prog-wave" id="file-bar-${it.id}"></div></div>
                </div></div>
            </div></div>`;
            return n;
        }

        // هماهنگ کردن لیست نمایش‌داده‌شده با آرایه pendingFiles (فقط تفاوت‌ها، با انیمیشن)
        function renderPending() {
            const list = $('pending-list');
            const ids = new Set(pendingFiles.map(f => f.id));

            list.querySelectorAll('[data-fid]:not(.leaving)').forEach(n => {
                if (!ids.has(Number(n.dataset.fid))) leaveNode(n);
            });
            pendingFiles.forEach(it => {
                if (!list.querySelector('[data-fid="' + it.id + '"]:not(.leaving)')) {
                    it._shown = null;
                    enterNode(list, buildFileNode(it), 0);
                }
            });

            updateQueueButtons();
            setCollapse($('pending-box'), pendingFiles.length > 0);
            pendingFiles.forEach(updateItemUI);
        }

        // به‌روزرسانی ظاهر فقط یک فایل (بدون ساخت دوباره لیست؛ برای نرم بودن نوار پیشرفت)
        function updateItemUI(it) {
            const item = $('file-item-' + it.id);
            if (!item) return;
            const sizeEl = $('file-size-' + it.id);
            const stateEl = $('file-state-' + it.id);
            const bar = $('file-bar-' + it.id);

            const percent = it.total > 0 ? Math.min(100, Math.floor((it.loaded / it.total) * 100)) : 0;
            item.classList.remove('uploading', 'done', 'error', 'canceled');
            item.classList.add(it.status);
            sizeEl.textContent = formatBytes(it.file.size);

            let label = 'Ready';
            let width = 0;
            if (it.status === 'uploading') {
                sizeEl.textContent = formatBytes(it.loaded) + ' / ' + formatBytes(it.total);
                label = (percent >= 100) ? 'Saving...' : percent + '%';   // در ۱۰۰٪ سرور هنوز در حال ذخیره روی دیسک است
                width = percent;
            } else if (it.status === 'done') { label = 'Sent ✓'; width = 100; }
            else if (it.status === 'error') { label = 'Failed ✕ (press Send to retry)'; width = percent; }
            else if (it.status === 'canceled') { label = 'Canceled'; }

            bar.style.width = width + '%';
            setCollapse($('file-track-' + it.id), it.status === 'uploading' || it.status === 'done' || it.status === 'error');

            // تغییر وضعیت با انیمیشن ، اما درصد پیشرفت مستقیم نوشته می‌شود
            if (it._shown !== it.status) { swapText(stateEl, label); it._shown = it.status; }
            else if (it.status === 'uploading') { stateEl.textContent = label; }
        }

        // تنظیم متن و وضعیت دکمه‌های «ارسال» و «انصراف» بر اساس حالت فعلی
        function updateQueueButtons() {
            // در حین آپلود، انتخاب فایل جدید غیرفعال است تا صف به هم نریزد
            $('file-input').disabled = isUploading;
            if (pendingFiles.length === 0) return;

            const sendBtn = $('send-files-btn');
            const waiting = pendingFiles.filter(f => f.status === 'pending' || f.status === 'error').length;
            const animate = $('pending-box').classList.contains('open');
            const setLabel = (el, txt) => { if (animate) swapText(el, txt); else el.textContent = txt; };

            if (isUploading) {
                sendBtn.disabled = true;
                setLabel($('send-files-label'), 'Uploading...');
                setLabel($('cancel-files-label'), 'Cancel Upload');
            } else {
                sendBtn.disabled = (waiting === 0);
                setLabel($('send-files-label'), 'Send ' + waiting + (waiting === 1 ? ' File' : ' Files'));
                setLabel($('cancel-files-label'), 'Clear Selection');
            }
        }

        // دکمه ✕ کنار هر فایل: انصراف از ارسال همان فایل
        function removeFile(id) {
            const it = pendingFiles.find(f => f.id === id);
            if (!it) return;

            if (it.status === 'uploading' && it.xhr) {
                // فایلی که همین الان در حال ارسال است: درخواست قطع می‌شود
                it.xhr.abort();
            } else if (isUploading && it.status === 'pending') {
                // فایل منتظر در صف (در حین آپلود): فقط علامت لغو می‌خورد تا حلقه آن را رد کند
                it.status = 'canceled';
                updateItemUI(it);
                setTimeout(() => { pendingFiles = pendingFiles.filter(f => f.id !== id); renderPending(); }, 900);
            } else {
                // فایلی که هنوز ارسال شروع نشده: از لیست حذف می‌شود
                pendingFiles = pendingFiles.filter(f => f.id !== id);
                renderPending();
            }
        }

        // دکمه انصراف کلی: همه ارسال‌ها قطع و لیست خالی می‌شود
        // (فایل‌هایی که قبلا کامل ارسال شده‌اند در تاریخچه می‌مانند)
        function cancelAllFiles() {
            cancelRequested = true;
            pendingFiles.forEach(it => {
                if (it.status === 'uploading' && it.xhr) it.xhr.abort();
                else if (it.status === 'pending' || it.status === 'error') it.status = 'canceled';
            });
            if (!isUploading) {
                pendingFiles = [];
                cancelRequested = false;
                renderPending();
            }
            // اگر آپلود در حال اجراست، حلقه صف خودش تمیزکاری را انجام می‌دهد (تابع finishQueue)
        }

        // شروع ارسال: فایل‌ها یکی‌یکی (با نوار پیشرفت جدا) به سرور فرستاده می‌شوند
        async function startUpload() {
            if (isUploading || pendingFiles.length === 0) return;
            const targetIds = getTargets();
            if (!targetIds) return;

            // فایل‌هایی که قبلا خطا خورده بودند دوباره آماده ارسال می‌شوند
            pendingFiles.forEach(it => {
                if (it.status === 'error') { it.status = 'pending'; it.loaded = 0; updateItemUI(it); }
            });

            isUploading = true;
            cancelRequested = false;
            updateQueueButtons();

            for (const it of pendingFiles) {
                if (cancelRequested) break;
                if (it.status !== 'pending') continue;
                await uploadOneFile(it, targetIds);
            }
            finishQueue();
        }

        // ارسال یک فایل با XMLHttpRequest (چون fetch رویداد پیشرفت آپلود ندارد)
        function uploadOneFile(it, targetIds) {
            return new Promise(resolve => {
                const xhr = new XMLHttpRequest();
                it.xhr = xhr;
                it.status = 'uploading';
                it.loaded = 0;
                updateItemUI(it);

                const formData = new FormData();
                formData.append('sender_id', clientId);
                formData.append('target_ids', targetIds);
                formData.append('files', it.file);

                // رویداد پیشرفت: هر بار که مقداری از فایل ارسال شد، نوار پیشرفت به‌روز می‌شود
                xhr.upload.onprogress = (e) => {
                    if (e.lengthComputable) {
                        it.loaded = e.loaded;
                        it.total = e.total;
                        updateItemUI(it);
                    }
                };
                // پایان موفق (کد ۲xx از سرور)
                xhr.onload = () => {
                    if (xhr.status >= 200 && xhr.status < 300) {
                        it.status = 'done';
                        it.loaded = it.total;
                    } else {
                        it.status = 'error';
                    }
                    updateItemUI(it);
                    resolve();
                };
                // خطای شبکه (مثلا قطع شدن Wi-Fi)
                xhr.onerror = () => { it.status = 'error'; updateItemUI(it); resolve(); };
                // انصراف کاربر: بعد از لغو، آن فایل از لیست حذف می‌شود
                xhr.onabort = () => {
                    it.status = 'canceled';
                    updateItemUI(it);
                    setTimeout(() => { pendingFiles = pendingFiles.filter(f => f.id !== it.id); renderPending(); }, 900);
                    resolve();
                };

                xhr.open('POST', '/api/upload');
                xhr.send(formData);
            });
        }

        // پایان صف: اعلام نتیجه، بازگرداندن دکمه‌ها به حالت عادی و تمیز کردن لیست
        function finishQueue() {
            const sent = pendingFiles.filter(f => f.status === 'done').length;
            const failed = pendingFiles.filter(f => f.status === 'error').length;
            const wasCanceled = cancelRequested;

            isUploading = false;
            if (wasCanceled) {
                pendingFiles = [];
                cancelRequested = false;
                showSnack(sent > 0 ? 'Upload canceled (' + sent + ' sent before cancel)' : 'Upload canceled', 'info');
            } else {
                if (failed > 0) showSnack(failed + (failed === 1 ? ' file' : ' files') + ' failed to upload', 'error');
                else if (sent > 0) showSnack(sent + (sent === 1 ? ' file' : ' files') + ' sent successfully', 'success');
                // فایل‌های موفق بعد از ۲ ثانیه از لیست پاک می‌شوند؛ فایل‌های خطادار می‌مانند تا دوباره تلاش شود
                setTimeout(() => {
                    if (isUploading) return;
                    pendingFiles = pendingFiles.filter(f => f.status !== 'done');
                    renderPending();
                }, 2200);
            }
            renderPending();
            updateData();
        }

        // ================= بخش ۹: دانلود فایل با بررسی وجود فایل =================
        // قبل از دانلود از سرور می‌پرسیم فایل هنوز روی دیسک هست یا نه:
        //   هست  -> دانلود در همین دستگاه شروع می‌شود (مرورگر خودش پیشرفت را نشان می‌دهد)
        //   نیست -> دیالوگ داخل UI نمایش داده می‌شود و کاربر به صفحه سفید JSON نمی‌رود
        async function handleDownload(event, el) {
            event.preventDefault();
            const encodedName = el.dataset.file;
            try {
                const res = await fetch('/api/check/' + encodedName);
                const data = await res.json();
                if (data.exists) {
                    // ساخت یک لینک مخفی و کلیک خودکار روی آن برای شروع دانلود
                    const a = document.createElement('a');
                    a.href = '/download/' + encodedName;
                    a.download = decodeURIComponent(encodedName);
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    showSnack('Download started', 'success', 2200);
                } else {
                    showPopup('File Not Found', 'This file has been deleted or does not exist anymore on the host device.');
                }
            } catch (err) {
                showPopup('Connection Error', 'Could not reach the server. Please check your connection and try again.');
            }
        }

        // ================= بخش ۱۰: ارسال متن =================
        async function sendText() {
            const textInput = $('text-input');
            const textValue = textInput.value;
            if (textValue.length > MAX_CHARS) return;
            if (!textValue.trim()) {
                showSnack('Type a message first', 'error');
                shake($('text-field'));
                return;
            }
            const targetIds = getTargets();
            if (!targetIds) return;

            const formData = new FormData();
            formData.append('sender_id', clientId);
            formData.append('target_ids', targetIds);
            formData.append('text', textValue);

            $('submit-text-btn').disabled = true;
            try {
                let response = await fetch('/api/text', { method: 'POST', body: formData });
                await response.json();
                textInput.value = '';
                showSnack('Message sent', 'success', 2400);
                updateData();
            } catch (err) {
                showSnack('Error sending text. Please try again', 'error');
            }
            validateCharacterCount();
        }

        // ================= بخش ۱۱: همگام‌سازی با سرور =================
        let firstSync = true;       // آیا هنوز همگام‌سازی اول انجام نشده؟ (برای ورود پله‌ای و جلوگیری از اعلان اضافه)
        let lastLatestId = null;    // شناسه آخرین مورد دریافتی که نمایش داده شده

        // کادر «آخرین دریافتی»: محتوا فقط وقتی مورد جدید برسد عوض می‌شود (بدون چشمک زدن)
        function renderLatest(l) {
            const box = $('latest-container');
            if (!l) { setCollapse(box, false); lastLatestId = null; return; }

            const wasOpen = box.classList.contains('open');
            const title = 'Received from ' + l.sender_name;
            if (wasOpen) swapText($('latest-type'), title); else $('latest-type').textContent = title;

            if (l.id !== lastLatestId) {
                $('latest-body').textContent = (l.type === 'text') ? l.content : ('File: ' + l.content);
                if (l.type === 'text') {
                    $('latest-action-zone').innerHTML = `<button class="chip-btn ripple" onclick="copyTextFromElement($('latest-body'), 'lbl-copy-latest')">${ICON.copy}<span class="sw" id="lbl-copy-latest">Copy Text</span></button>`;
                } else {
                    // لینک دانلود از handleDownload رد می‌شود تا قبل از دانلود وجود فایل چک شود
                    $('latest-action-zone').innerHTML = `<a href="#" data-file="${encodeURIComponent(l.content)}" onclick="handleDownload(event, this)" class="chip-btn ripple">${ICON.download}<span>Download File</span></a>`;
                }
                if (wasOpen && !reduceMotion && $('latest-card').animate) {
                    $('latest-card').animate([{ transform: 'scale(0.96)', boxShadow: '0 0 0 0 var(--primary-glow-strong)' }, { transform: 'scale(1)', boxShadow: '0 0 0 14px transparent' }], { duration: 700, easing: 'cubic-bezier(0.2,0,0,1)' });
                }
                if (!firstSync) {
                    showSnack('New ' + (l.type === 'text' ? 'message' : 'file') + ' from ' + l.sender_name, 'info');
                }
                lastLatestId = l.id;
            }
            setCollapse(box, true);
        }

        // ساخت کادر یک رکورد تاریخچه
        function buildHistoryNode(item) {
            const isInbound = item.receiver === clientId;
            const n = document.createElement('div');
            n.className = 'collapse';
            n.dataset.hid = item.id;
            let actionHtml;
            if (item.type === 'file') {
                actionHtml = `<a href="#" data-file="${encodeURIComponent(item.content)}" onclick="handleDownload(event, this)" class="chip-btn ripple">${ICON.download}<span>Download Asset</span></a>`;
            } else {
                actionHtml = `<button class="chip-btn ripple" onclick="copyTextFromElement(this.closest('.history-item').querySelector('.hist-content'), 'lbl-hist-${item.id}')">${ICON.copy}<span class="sw" id="lbl-hist-${item.id}">Copy Text</span></button>`;
            }
            n.innerHTML = `<div class="collapse-inner"><div class="history-item ${isInbound ? 'inbound' : 'outbound'}">
                <div class="hist-meta"><span class="hist-badge"></span><span>${escapeHtml(item.time)}</span></div>
                <div class="hist-content">${escapeHtml(item.content)}</div>
                <div>${actionHtml}</div>
            </div></div>`;
            return n;
        }

        // لیست تاریخچه: فقط رکوردهای جدید با انیمیشن بالای لیست اضافه می‌شوند
        function renderHistory(items) {
            const list = $('history-list');
            setCollapse($('history-empty'), items.length === 0);

            const existing = new Map();
            list.querySelectorAll('[data-hid]:not(.leaving)').forEach(n => existing.set(n.dataset.hid, n));

            // items از جدید به قدیم است؛ از قدیمی‌ترین شروع می‌کنیم تا جدیدترین بالا بنشیند
            for (let i = items.length - 1; i >= 0; i--) {
                const item = items[i];
                let node = existing.get(String(item.id));
                if (!node) {
                    node = buildHistoryNode(item);
                    const delay = firstSync ? Math.min(items.length - 1 - i, 8) * 60 : 0;
                    enterNode(list, node, delay, list.firstChild);
                }
                const isInbound = item.receiver === clientId;
                const who = isInbound ? 'From: ' + item.sender_name : 'To: ' + item.receiver_name;
                node.querySelector('.hist-badge').textContent = who + ' (' + item.type.toUpperCase() + ')';
            }
        }

        // هر ۳ ثانیه اطلاعات جدید (دستگاه‌ها، آخرین دریافتی، تاریخچه) از سرور گرفته و نمایش داده می‌شود
        async function updateData() {
            try {
                let response = await fetch(`/api/sync?client_id=${clientId}`);
                let data = await response.json();

                renderDeviceCheckboxes(data.devices);
                renderLatest(data.latest_received);
                renderHistory(data.history);
                firstSync = false;
            } catch (err) { console.error('Sync failure'); }
        }

        // شروع برنامه: ping و sync اولیه، سپس تکرار دوره‌ای
        validateCharacterCount();
        pingServer();
        updateData();
        setInterval(pingServer, 4000);
        setInterval(updateData, 3000);
    </script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# بخش ۵: مسیرهای (Endpoint) سرور
# ---------------------------------------------------------------------------

# صفحه اصلی: آدرس واقعی سرور را جای SERVER_URL_PLACEHOLDER می‌گذارد و صفحه را می‌فرستد
@app.get("/", response_class=HTMLResponse)
async def read_root():
    local_ip = get_local_ip()
    port = 5050
    return HTML_UI.replace("SERVER_URL_PLACEHOLDER", f"http://{local_ip}:{port}")

# ping: هر دستگاه با این مسیر اعلام می‌کند آنلاین است
# اگر درخواست از خود میزبان (localhost) بود، ضربان قلب میزبان هم به‌روز می‌شود
@app.post("/api/ping")
async def ping_device(request: Request, client_id: str = Form(...), name: str = Form(...)):
    global HOST_CONNECTED, HOST_LAST_SEEN

    if request.client.host in ["127.0.0.1", "::1", "localhost"]:
        HOST_CONNECTED = True
        HOST_LAST_SEEN = time.time()

    online_devices[client_id] = {
        "name": name,
        "ip": request.client.host,
        "last_seen": time.time()
    }
    return {"status": "alive"}

# آپلود فایل: فایل روی دیسک میزبان ذخیره و برای هر گیرنده یک رکورد در تاریخچه ثبت می‌شود
# نکته: مرورگر حالا هر فایل را در یک درخواست جدا می‌فرستد (برای نوار پیشرفت هر فایل)
@app.post("/api/upload")
async def upload_files(
    sender_id: str = Form(...),
    target_ids: str = Form(...),
    files: List[UploadFile] = File(...)
):
    timestamp = time.strftime("%H:%M:%S")
    targets = target_ids.split(",")
    for file in files:
        if file.filename:
            # فقط نام فایل (بدون مسیر) استفاده می‌شود تا کسی نتواند بیرون از پوشه ذخیره کند
            clean_name = safe_filename(file.filename)
            file_path = os.path.join(UPLOAD_DIR, clean_name)

            # ذخیره تکه‌تکه (۱ مگابایتی) به جای خواندن کل فایل در رم؛ مناسب فایل‌های بزرگ
            with open(file_path, "wb") as f:
                while True:
                    chunk = await file.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)

            for target in targets:
                if target.strip():
                    transfers.append({
                        "id": len(transfers) + 1,
                        "sender": sender_id,
                        "receiver": target.strip(),
                        "type": "file",
                        "content": clean_name,
                        "time": timestamp
                    })
    return {"status": "success", "message": "Files successfully routed."}

# دریافت متن: برای هر گیرنده یک رکورد متنی در تاریخچه اضافه می‌کند
@app.post("/api/text")
async def receive_text(
    sender_id: str = Form(...),
    target_ids: str = Form(...),
    text: str = Form(...)
):
    if text.strip():
        timestamp = time.strftime("%H:%M:%S")
        targets = target_ids.split(",")
        for target in targets:
            if target.strip():
                transfers.append({
                    "id": len(transfers) + 1,
                    "sender": sender_id,
                    "receiver": target.strip(),
                    "type": "text",
                    "content": text.strip(),
                    "time": timestamp
                })
        return {"status": "success", "message": "Text dispatched successfully."}
    return {"status": "error", "message": "Content cannot be empty."}

# همگام‌سازی: دستگاه‌های آفلاین (بیش از ۱۲ ثانیه بدون ping) حذف می‌شوند
# و دستگاه فقط تاریخچه خودش و آخرین مورد دریافتی‌اش را می‌گیرد
@app.get("/api/sync")
async def sync_state(client_id: str):
    now = time.time()
    dead_nodes = [k for k, v in online_devices.items() if now - v["last_seen"] > 12]
    for k in dead_nodes:
        online_devices.pop(k, None)

    name_map = {k: v["name"] for k, v in online_devices.items()}

    user_history = []
    latest_received = None

    for t in transfers:
        if t["sender"] == client_id or t["receiver"] == client_id:
            resolved_item = t.copy()
            resolved_item["sender_name"] = name_map.get(t["sender"], "Disconnected Host")
            resolved_item["receiver_name"] = name_map.get(t["receiver"], "Disconnected Host")
            user_history.append(resolved_item)

            if t["receiver"] == client_id:
                latest_received = resolved_item

    user_history.reverse()

    return {
        "devices": online_devices,
        "latest_received": latest_received,
        "history": user_history
    }

# خاموش کردن سرور (وقتی صفحه میزبان بسته شود صدا زده می‌شود)
@app.post("/api/shutdown")
def kill_server_instance():
    print("\n[!] Host trigger received. Executing clean auto-shutdown process...")
    os._exit(0)

# [جدید] بررسی وجود فایل: قبل از دانلود، مرورگر می‌پرسد فایل هنوز روی دیسک هست یا نه
# فقط {"exists": true/false} برمی‌گرداند و هیچ تاثیری روی اجرای سرور ندارد
@app.get("/api/check/{filename}")
async def check_file(filename: str):
    file_path = os.path.join(UPLOAD_DIR, safe_filename(filename))
    return {"exists": os.path.isfile(file_path)}

# دانلود فایل: اگر وجود داشته باشد ارسال می‌شود؛ در غیر این صورت خطای استاندارد 404
@app.get("/download/{filename}")
async def download_file(filename: str):
    clean_name = safe_filename(filename)
    file_path = os.path.join(UPLOAD_DIR, clean_name)
    if os.path.isfile(file_path):
        return FileResponse(path=file_path, filename=clean_name, media_type='application/octet-stream')
    return JSONResponse(status_code=404, content={"status": "error", "message": "File not found."})

# ---------------------------------------------------------------------------
# بخش ۶: اجرای برنامه
# ---------------------------------------------------------------------------
def open_browser(url):
    # باز کردن خودکار مرورگر پیش‌فرض روی آدرس سرور
    webbrowser.open(url)

if __name__ == "__main__":
    local_ip = get_local_ip()
    port = 5050
    server_url = f"http://127.0.0.1:{port}"

    print("\n" + "="*60)
    print(f"[*] Cluster Activated. Server local link: {server_url}")
    print(f"[*] Access Link for target nodes: http://{local_ip}:{port}")
    print("="*60 + "\n")

    # نخ پس‌زمینه برای نظارت بر ضربان قلب میزبان
    Thread(target=monitor_host_heartbeat, daemon=True).start()
    # بعد از ۱.۵ ثانیه مرورگر باز می‌شود (تا سرور فرصت بالا آمدن داشته باشد)
    Timer(1.5, open_browser, args=[server_url]).start()

    # اجرای سرور روی همه کارت‌های شبکه (0.0.0.0) تا دستگاه‌های دیگر هم وصل شوند
    import importlib
    uvicorn_module = importlib.import_module("uvicorn")
    uvicorn_module.run(app, host="0.0.0.0", port=port)
