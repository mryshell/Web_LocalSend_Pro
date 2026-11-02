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
        /* ---------- رنگ‌ها: متغیرهای تم تیره (پیش‌فرض) ---------- */
        :root {
            --bg-body: #16181d;
            --bg-card: #20242c;
            --text-main: #e4e7eb;
            --bg-input: #16181d;
            --border-color: #374151;
            --text-muted: #9ca3af;
            --accent-color: #10b981;
            --danger-color: #ef4444;
        }
        /* رنگ‌های تم روشن؛ با کلاس light-theme روی body فعال می‌شود */
        body.light-theme {
            --bg-body: #f3f4f6;
            --bg-card: #ffffff;
            --text-main: #1f2937;
            --bg-input: #f9fafb;
            --border-color: #d1d5db;
            --text-muted: #6b7280;
        }
        /* استایل کلی صفحه: همه چیز وسط صفحه چیده می‌شود */
        body {
            background-color: var(--bg-body); color: var(--text-main);
            font-family: system-ui, -apple-system, sans-serif;
            display: flex; flex-direction: column; min-height: 100vh;
            align-items: center; justify-content: center; margin: 0; padding: 16px; box-sizing: border-box;
            transition: background-color 0.2s, color 0.2s;
        }
        /* کارت اصلی برنامه */
        .card {
            width: 100%; max-width: 420px; background-color: var(--bg-card);
            border-radius: 24px; padding: 24px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.3);
            border: 1px solid var(--border-color); box-sizing: border-box;
        }

        /* دکمه تغییر تم (بالای کارت) */
        .top-controls { display: flex; justify-content: flex-end; align-items: center; margin-bottom: 16px; }
        .theme-btn { background: none; border: 1px solid var(--border-color); color: var(--text-main); padding: 6px 12px; border-radius: 8px; cursor: pointer; font-size: 11px; font-weight: bold; }
        .theme-btn:hover { background: var(--bg-body); }

        h1 { color: var(--accent-color); margin: 0 0 4px 0; font-size: 24px; text-align: center; }

        /* فیلد نام دستگاه */
        .name-container { text-align: center; margin-bottom: 16px; }
        .name-input {
            width: 80%; max-width: 260px; background: var(--bg-input); border: 1px solid var(--border-color);
            border-radius: 8px; padding: 6px 12px; color: #6ee7b7; text-align: center; font-size: 14px; font-weight: bold;
        }
        .name-input:focus { outline: none; border-color: var(--accent-color); }

        /* QR Code و برچسب آدرس سرور */
        .qr-box { display: flex; justify-content: center; margin: 12px auto; background: white; padding: 8px; border-radius: 16px; width: 130px; height: 130px; }
        .url-tag { background-color: var(--bg-input); color: #6ee7b7; font-family: monospace; padding: 4px 10px; border-radius: 8px; font-size: 11px; display: inline-block; margin-bottom: 16px; border: 1px solid var(--border-color); }

        .label { font-size: 12px; color: var(--text-muted); font-weight: bold; margin-bottom: 6px; display: block; text-align: left; }

        /* لیست انتخاب دستگاه‌های گیرنده (چک‌باکس‌ها) */
        .device-selector-list {
            background-color: var(--bg-input); border: 1px solid var(--border-color); border-radius: 12px;
            max-height: 130px; overflow-y: auto; padding: 8px; margin-bottom: 14px; box-sizing: border-box;
        }
        .device-checkbox-item {
            display: flex; align-items: center; gap: 10px; padding: 6px 8px;
            border-radius: 6px; cursor: pointer; transition: background 0.15s; font-size: 13px;
        }
        .device-checkbox-item:hover { background-color: var(--bg-card); }
        .device-checkbox-item input[type="checkbox"] { accent-color: var(--accent-color); width: 16px; height: 16px; cursor: pointer; }
        .all-item { border-bottom: 1px solid var(--border-color); margin-bottom: 4px; padding-bottom: 8px; color: var(--accent-color); font-weight: bold; }

        /* کادر متن */
        textarea {
            width: 100%; background-color: var(--bg-input); border: 1px solid var(--border-color);
            border-radius: 10px; padding: 10px; color: var(--text-main); box-sizing: border-box; font-size: 14px;
        }
        textarea:focus { outline: none; border-color: var(--accent-color); }

        /* شمارنده کاراکتر (قرمز می‌شود اگر از حد مجاز بگذرد) */
        .counter-container {
            display: flex; justify-content: flex-end; font-size: 11px; color: var(--text-muted); margin-top: 4px; margin-bottom: 14px; font-weight: bold;
        }
        .counter-container.danger { color: var(--danger-color); }

        /* ناحیه کشیدن و رها کردن فایل (input شفاف روی کل ناحیه قرار دارد) */
        .dropzone {
            border: 2px dashed var(--border-color); border-radius: 14px; padding: 24px 16px; text-align: center; position: relative; cursor: pointer; margin-bottom: 14px;
        }
        .dropzone:hover { border-color: var(--accent-color); }
        .dropzone input { position: absolute; top: 0; left: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; }

        /* ---------- [جدید] لیست فایل‌های انتخاب‌شده + نوار پیشرفت ---------- */
        .pending-list { max-height: 190px; overflow-y: auto; margin-bottom: 8px; }
        .file-item {
            background: var(--bg-input); border: 1px solid var(--border-color);
            border-radius: 10px; padding: 8px 10px; margin-bottom: 8px; text-align: left;
        }
        .file-row { display: flex; align-items: center; gap: 8px; }
        /* برچسب فرمت فایل (مثلا PDF یا MP4) */
        .file-ext {
            background: var(--accent-color); color: #111827; font-size: 10px; font-weight: bold;
            padding: 2px 6px; border-radius: 6px; flex-shrink: 0;
        }
        .file-name { flex-grow: 1; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        /* دکمه ✕ برای انصراف از ارسال همان فایل */
        .file-remove { background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 14px; padding: 0 2px; }
        .file-remove:hover { color: var(--danger-color); }
        .file-meta { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted); margin-top: 4px; font-weight: bold; }
        /* نوار پیشرفت: track پس‌زمینه است و bar قسمت پر شده */
        .progress-track { height: 6px; background: var(--border-color); border-radius: 999px; overflow: hidden; margin-top: 6px; }
        .progress-bar { height: 100%; width: 0%; background: var(--accent-color); transition: width 0.15s linear; }
        .progress-bar.error { background: var(--danger-color); }

        /* دکمه‌ها */
        .btn {
            width: 100%; background-color: var(--accent-color); color: #111827; font-weight: bold; padding: 10px; border-radius: 10px; border: none; cursor: pointer; transition: background 0.2s; font-size: 14px;
        }
        .btn:hover { background-color: #059669; }
        .btn:disabled { background-color: var(--border-color); color: var(--text-muted); cursor: not-allowed; }
        .btn-secondary { background-color: var(--border-color); color: var(--text-main); margin-top: 8px; }
        .btn-secondary:hover { background-color: var(--text-muted); color: #111827; }

        /* کادر «آخرین دریافتی» */
        .latest-box { background-color: var(--bg-input); border: 1px solid var(--border-color); border-radius: 14px; padding: 12px; margin-top: 16px; text-align: left; }
        .latest-title { font-size: 11px; color: var(--accent-color); font-weight: bold; text-transform: uppercase; margin-bottom: 6px; }

        .latest-content {
            font-family: monospace; font-size: 13px; word-break: break-all; white-space: pre-wrap;
            display: -webkit-box; -webkit-line-clamp: 5; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis;
        }

        .copy-utility-btn {
            background: var(--accent-color); color: #111827; border: none; padding: 4px 10px; border-radius: 6px;
            font-size: 11px; font-weight: bold; cursor: pointer; margin-top: 8px; display: inline-flex; align-items: center; gap: 4px;
        }
        .copy-utility-btn:hover { background: #059669; }

        /* پنجره‌های پاپ‌آپ (تاریخچه و پیام خطا) */
        .modal-overlay {
            position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7);
            display: flex; align-items: center; justify-content: center; z-index: 1000; visibility: hidden; opacity: 0; transition: all 0.2s ease;
        }
        .modal {
            background-color: var(--bg-card); border: 1px solid var(--border-color); width: 90%; max-width: 450px; border-radius: 20px; padding: 20px; box-sizing: border-box; display: flex; flex-direction: column; max-height: 80vh;
        }
        /* [جدید] پاپ‌آپ پیام (مثلا فایل حذف شده) کوچک‌تر است */
        .modal.alert-modal { max-width: 340px; }
        .modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; border-bottom: 1px solid var(--border-color); padding-bottom: 8px; }
        .modal-title { font-size: 16px; font-weight: bold; color: var(--accent-color); }
        .close-modal { color: var(--text-muted); font-size: 20px; cursor: pointer; background: none; border: none; }
        .close-modal:hover { color: var(--text-main); }
        .modal-body { overflow-y: auto; flex-grow: 1; padding-right: 4px; }

        /* آیتم‌های تاریخچه: خط سبز = دریافتی ، خط آبی = ارسالی */
        .history-item { background: var(--bg-input); border-radius: 10px; padding: 10px; margin-bottom: 8px; font-size: 12px; border-left: 3px solid var(--border-color); text-align: left;}
        .history-item.inbound { border-left-color: var(--accent-color); }
        .history-item.outbound { border-left-color: #3b82f6; }
        .hist-meta { display: flex; justify-content: space-between; color: var(--text-muted); font-size: 10px; margin-bottom: 4px; }

        .hist-content {
            font-family: monospace; word-break: break-all; color: var(--text-main); white-space: pre-wrap;
            display: -webkit-box; -webkit-line-clamp: 5; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis;
        }

        .download-btn { color: var(--accent-color); text-decoration: none; font-weight: bold; margin-top: 4px; display: inline-block; cursor: pointer; }
        .hidden { display: none !important; }
    </style>
</head>
<body>

    <!-- ===================== کارت اصلی برنامه ===================== -->
    <div class="card">
        <div class="top-controls">
            <button class="theme-btn" onclick="switchTheme()">🌓 Change Mode</button>
        </div>

        <h1>Web LocalSend Pro</h1>
        <!-- نام نمایشی این دستگاه؛ برای بقیه دستگاه‌ها دیده می‌شود -->
        <div class="name-container">
            <input type="text" id="my-name-input" class="name-input" oninput="updateMyName(this.value)" placeholder="Enter your name...">
        </div>

        <!-- QR Code و آدرس سرور برای وصل شدن موبایل -->
        <div class="qr-box"><canvas id="qr-code"></canvas></div>
        <div style="text-align: center;"><div class="url-tag">SERVER_URL_PLACEHOLDER</div></div>

        <!-- انتخاب گیرنده‌ها: چند دستگاه همزمان یا همه -->
        <label class="label">🎯 Target Recipients (Select multiple):</label>
        <div class="device-selector-list" id="device-checkbox-list">
            <div class="device-checkbox-item all-item">
                <input type="checkbox" id="check-all-devices" onchange="toggleSelectAll(this)">
                <label for="check-all-devices">All (Send to Everyone)</label>
            </div>
            <div id="dynamic-devices-box">
                <p style="font-size:11px; color:var(--text-muted); margin:4px 8px;">Waiting for other devices...</p>
            </div>
        </div>

        <!-- ناحیه انتخاب فایل: حالا انتخاب فایل ارسال را شروع نمی‌کند، فقط فایل‌ها را به لیست اضافه می‌کند -->
        <div class="dropzone">
            <input type="file" id="file-input" multiple onchange="addSelectedFiles()">
            <span style="color: var(--text-muted); font-size: 13px;">Drag & Drop files or click to select</span>
        </div>

        <!-- [جدید] لیست فایل‌های انتخاب‌شده (نام، فرمت، حجم، نوار پیشرفت) + دکمه ارسال و انصراف -->
        <div id="pending-box" class="hidden" style="margin-bottom: 14px;">
            <div class="pending-list" id="pending-list"></div>
            <button id="send-files-btn" onclick="startUpload()" class="btn">Send Files</button>
            <button id="cancel-files-btn" onclick="cancelAllFiles()" class="btn btn-secondary">✖ Clear Selection</button>
        </div>

        <!-- ارسال متن -->
        <textarea id="text-input" rows="2" placeholder="Type message or paste links to send..." oninput="validateCharacterCount()"></textarea>
        <div class="counter-container" id="char-counter-label">Remaining: 10,000</div>

        <button id="submit-text-btn" onclick="sendText()" class="btn">Send Securely</button>

        <button onclick="toggleModal(true)" class="btn btn-secondary">📜 View Full History</button>

        <!-- آخرین پیام یا فایل دریافتی -->
        <div id="latest-container" class="latest-box hidden">
            <div class="latest-title" id="latest-type">📥 Latest Received</div>
            <div class="latest-content" id="latest-body">No data yet.</div>
            <div id="latest-action-zone"></div>
        </div>
    </div>

    <!-- ===================== پنجره تاریخچه ===================== -->
    <div id="history-modal" class="modal-overlay" onclick="if(event.target===this) toggleModal(false)">
        <div class="modal">
            <div class="modal-header">
                <div class="modal-title">Transaction History</div>
                <button onclick="toggleModal(false)" class="close-modal">&times;</button>
            </div>
            <div class="modal-body" id="history-list">
                <p style="text-align:center; color:var(--text-muted); font-size:12px;">No history records found.</p>
            </div>
        </div>
    </div>

    <!-- [جدید] پاپ‌آپ پیام: برای «فایل حذف شده یا وجود ندارد» و خطاهای مشابه (بدون خاموش شدن سرور) -->
    <div id="alert-modal" class="modal-overlay" onclick="if(event.target===this) closePopup()">
        <div class="modal alert-modal">
            <div class="modal-header">
                <div class="modal-title" id="alert-title" style="color: var(--danger-color);">Notice</div>
                <button onclick="closePopup()" class="close-modal">&times;</button>
            </div>
            <div class="modal-body">
                <p id="alert-message" style="font-size:13px; margin:0 0 14px 0; line-height:1.5;"></p>
            </div>
            <button onclick="closePopup()" class="btn">OK</button>
        </div>
    </div>

    <script>
        // ================= بخش ۱: هویت دستگاه =================
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
        document.getElementById('my-name-input').value = myName;

        // بازیابی تم ذخیره‌شده (تیره/روشن)
        if (localStorage.getItem('cfg_theme') === 'light') {
            document.body.classList.add('light-theme');
        }

        let selectedClientIds = new Set();   // شناسه دستگاه‌های انتخاب‌شده به عنوان گیرنده
        const MAX_CHARS = 10000;             // سقف تعداد کاراکتر پیام متنی

        // ================= بخش ۲: توابع کمکی عمومی =================
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

        // تغییر تم و ذخیره آن
        function switchTheme() {
            document.body.classList.toggle('light-theme');
            const mode = document.body.classList.contains('light-theme') ? 'light' : 'dark';
            localStorage.setItem('cfg_theme', mode);
        }

        // تغییر نام دستگاه و اطلاع دادن به سرور
        function updateMyName(val) {
            let cleanName = val.trim();
            if(!cleanName) cleanName = "Anonymous";
            myName = cleanName;
            localStorage.setItem('custom_nickname', cleanName);
            pingServer();
        }

        // ================= بخش ۳: پاپ‌آپ پیام (جدید) =================
        // نمایش پنجره پیام با عنوان و متن دلخواه
        function showPopup(title, message) {
            document.getElementById('alert-title').innerText = title;
            document.getElementById('alert-message').innerText = message;
            const modal = document.getElementById('alert-modal');
            modal.style.visibility = 'visible';
            modal.style.opacity = '1';
        }

        function closePopup() {
            const modal = document.getElementById('alert-modal');
            modal.style.visibility = 'hidden';
            modal.style.opacity = '0';
        }

        // ================= بخش ۴: شمارنده کاراکتر =================
        // Live Integrity Engine for Input Text Fields
        // با هر تایپ، کاراکترهای باقی‌مانده را حساب می‌کند و اگر از حد گذشت دکمه ارسال را غیرفعال می‌کند
        function validateCharacterCount() {
            const textInput = document.getElementById('text-input');
            const counterLabel = document.getElementById('char-counter-label');
            const submitBtn = document.getElementById('submit-text-btn');

            const currentLen = textInput.value.length;
            const remaining = MAX_CHARS - currentLen;

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
                new QRious({ element: document.getElementById('qr-code'), value: "SERVER_URL_PLACEHOLDER", size: 130 });
            }
        });

        // اگر میزبان (localhost) صفحه را ببندد، به سرور خبر می‌دهیم تا خاموش شود
        window.addEventListener('pagehide', () => {
            if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
                navigator.sendBeacon('/api/shutdown');
            }
        });

        // ================= بخش ۵: انتخاب گیرنده‌ها =================
        // چک‌باکس «All»: همه دستگاه‌ها را تیک می‌زند یا برمی‌دارد
        function toggleSelectAll(masterCanvas) {
            const boxes = document.querySelectorAll('.device-single-checkbox');
            selectedClientIds.clear();
            boxes.forEach(box => {
                box.checked = masterCanvas.checked;
                if(masterCanvas.checked) selectedClientIds.add(box.value);
            });
        }

        // تغییر وضعیت چک‌باکس یک دستگاه
        function handleSingleCheckboxChange(box) {
            if(box.checked) {
                selectedClientIds.add(box.value);
            } else {
                selectedClientIds.delete(box.value);
                document.getElementById('check-all-devices').checked = false;
            }
        }

        // باز و بسته کردن پنجره تاریخچه
        function toggleModal(show) {
            const modal = document.getElementById('history-modal');
            modal.style.visibility = show ? 'visible' : 'hidden';
            modal.style.opacity = show ? '1' : '0';
            if(show) updateData();
        }

        // ping: هر ۴ ثانیه به سرور می‌گوید «من هنوز آنلاینم» و نامم را می‌فرستد
        async function pingServer() {
            try {
                await fetch('/api/ping', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body: `client_id=${clientId}&name=${encodeURIComponent(myName)}`
                });
            } catch(e) {}
        }

        // نمایش لیست دستگاه‌های آنلاین به صورت چک‌باکس (به جز خود دستگاه)
        function renderDeviceCheckboxes(devices) {
            const boxContainer = document.getElementById('dynamic-devices-box');
            const peerIds = Object.keys(devices).filter(id => id !== clientId);

            if (peerIds.length === 0) {
                boxContainer.innerHTML = '<p style="font-size:11px; color:var(--text-muted); margin:4px 8px;">Waiting for other devices...</p>';
                document.getElementById('check-all-devices').checked = false;
                return;
            }

            let htmlContent = '';
            peerIds.forEach(id => {
                const dev = devices[id];
                const isChecked = selectedClientIds.has(id) ? 'checked' : '';
                htmlContent += `
                    <div class="device-checkbox-item">
                        <input type="checkbox" value="${id}" id="chk-${id}" class="device-single-checkbox" ${isChecked} onchange="handleSingleCheckboxChange(this)">
                        <label for="chk-${id}">${escapeHtml(dev.name)} <span style="color:var(--text-muted); font-size:11px;">[${escapeHtml(dev.ip)}]</span></label>
                    </div>
                `;
            });
            boxContainer.innerHTML = htmlContent;
        }

        // ================= بخش ۶: کپی متن =================
        // کپی متن در کلیپ‌بورد؛ اگر مرورگر clipboard API نداشت از روش جایگزین استفاده می‌شود
        function copyTextFromElement(targetElement, buttonId) {
            const textToCopy = targetElement.innerText;
            const btnSpan = document.getElementById(buttonId);

            function updateSuccessUI() {
                if (btnSpan) {
                    btnSpan.innerText = "Copied! ✓";
                    setTimeout(() => { btnSpan.innerText = "Copy Text"; }, 2000);
                }
            }

            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(textToCopy)
                    .then(updateSuccessUI)
                    .catch(() => { runFallbackCopyEngine(textToCopy, updateSuccessUI); });
            } else {
                runFallbackCopyEngine(textToCopy, updateSuccessUI);
            }
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

        // ================= بخش ۷: انتخاب، پیش‌نمایش و آپلود فایل (جدید) =================
        // pendingFiles: لیست فایل‌های انتخاب‌شده؛ هر آیتم = { id, file, status, xhr, loaded, total }
        // status یکی از: pending (آماده) | uploading (در حال ارسال) | done (ارسال شد) | error (خطا) | canceled (لغو)
        let pendingFiles = [];
        let fileCounter = 0;          // شمارنده برای ساخت id یکتا برای هر فایل
        let isUploading = false;      // آیا الان صف آپلود در حال کار است؟
        let cancelRequested = false;  // آیا کاربر دکمه انصراف کلی را زده؟

        // وقتی کاربر فایل انتخاب یا Drop کرد: فایل‌ها فقط به لیست اضافه می‌شوند (ارسال خودکار نیست)
        function addSelectedFiles() {
            const fileInput = document.getElementById('file-input');
            for (const file of fileInput.files) {
                pendingFiles.push({ id: ++fileCounter, file: file, status: 'pending', xhr: null, loaded: 0, total: file.size });
            }
            fileInput.value = '';   // خالی می‌کنیم تا بتوان همان فایل را دوباره انتخاب کرد
            renderPending();
        }

        // ساخت دوباره کل لیست فایل‌های انتخاب‌شده (نام + فرمت + حجم + نوار پیشرفت)
        function renderPending() {
            const box = document.getElementById('pending-box');
            const list = document.getElementById('pending-list');

            if (pendingFiles.length === 0) {
                box.classList.add('hidden');
                list.innerHTML = '';
                return;
            }
            box.classList.remove('hidden');

            list.innerHTML = pendingFiles.map(it => `
                <div class="file-item" id="file-item-${it.id}">
                    <div class="file-row">
                        <span class="file-ext">${escapeHtml(getFileExt(it.file.name))}</span>
                        <span class="file-name" title="${escapeHtml(it.file.name)}">${escapeHtml(it.file.name)}</span>
                        <button class="file-remove" title="Cancel this file" onclick="removeFile(${it.id})">✕</button>
                    </div>
                    <div class="file-meta">
                        <span id="file-size-${it.id}"></span>
                        <span id="file-state-${it.id}"></span>
                    </div>
                    <div class="progress-track hidden" id="file-track-${it.id}">
                        <div class="progress-bar" id="file-bar-${it.id}"></div>
                    </div>
                </div>
            `).join('');

            pendingFiles.forEach(updateItemUI);
            updateQueueButtons();
        }

        // به‌روزرسانی ظاهر فقط یک فایل (بدون ساخت دوباره لیست؛ برای نرم بودن نوار پیشرفت)
        function updateItemUI(it) {
            const sizeEl = document.getElementById('file-size-' + it.id);
            const stateEl = document.getElementById('file-state-' + it.id);
            const track = document.getElementById('file-track-' + it.id);
            const bar = document.getElementById('file-bar-' + it.id);
            if (!sizeEl) return;

            const percent = it.total > 0 ? Math.min(100, Math.floor((it.loaded / it.total) * 100)) : 0;
            sizeEl.innerText = formatBytes(it.file.size);
            stateEl.style.color = '';
            bar.classList.remove('error');

            if (it.status === 'pending') {
                stateEl.innerText = 'Ready';
                track.classList.add('hidden');
            } else if (it.status === 'uploading') {
                track.classList.remove('hidden');
                bar.style.width = percent + '%';
                sizeEl.innerText = formatBytes(it.loaded) + ' / ' + formatBytes(it.total);
                // وقتی ۱۰۰٪ ارسال شد، سرور هنوز در حال ذخیره فایل روی دیسک است
                stateEl.innerText = (percent >= 100) ? 'Saving...' : percent + '%';
            } else if (it.status === 'done') {
                track.classList.remove('hidden');
                bar.style.width = '100%';
                stateEl.innerText = 'Sent ✓';
                stateEl.style.color = 'var(--accent-color)';
            } else if (it.status === 'error') {
                track.classList.remove('hidden');
                bar.classList.add('error');
                stateEl.innerText = 'Failed ✕ (press Send to retry)';
                stateEl.style.color = 'var(--danger-color)';
            } else if (it.status === 'canceled') {
                track.classList.add('hidden');
                stateEl.innerText = 'Canceled';
                stateEl.style.color = 'var(--danger-color)';
            }
        }

        // تنظیم متن و وضعیت دکمه‌های «ارسال» و «انصراف» بر اساس حالت فعلی
        function updateQueueButtons() {
            const sendBtn = document.getElementById('send-files-btn');
            const cancelBtn = document.getElementById('cancel-files-btn');
            const waiting = pendingFiles.filter(f => f.status === 'pending' || f.status === 'error').length;

            if (isUploading) {
                sendBtn.disabled = true;
                sendBtn.innerText = 'Uploading...';
                cancelBtn.innerText = '✖ Cancel Upload';
            } else {
                sendBtn.disabled = (waiting === 0);
                sendBtn.innerText = 'Send ' + waiting + (waiting === 1 ? ' File' : ' Files');
                cancelBtn.innerText = '✖ Clear Selection';
            }
            // در حین آپلود، انتخاب فایل جدید غیرفعال است تا صف به هم نریزد
            document.getElementById('file-input').disabled = isUploading;
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
                setTimeout(() => { pendingFiles = pendingFiles.filter(f => f.id !== id); renderPending(); }, 800);
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
            const targetIds = Array.from(selectedClientIds).join(',');
            if (isUploading || pendingFiles.length === 0) return;
            if (!targetIds) { alert('Please select at least one recipient device first!'); return; }

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
                    setTimeout(() => { pendingFiles = pendingFiles.filter(f => f.id !== it.id); renderPending(); }, 800);
                    resolve();
                };

                xhr.open('POST', '/api/upload');
                xhr.send(formData);
            });
        }

        // پایان صف: بازگرداندن دکمه‌ها به حالت عادی و تمیز کردن لیست
        function finishQueue() {
            isUploading = false;
            if (cancelRequested) {
                pendingFiles = [];
                cancelRequested = false;
            } else {
                // فایل‌های موفق بعد از ۲ ثانیه از لیست پاک می‌شوند؛ فایل‌های خطادار می‌مانند تا دوباره تلاش شود
                setTimeout(() => {
                    if (isUploading) return;
                    pendingFiles = pendingFiles.filter(f => f.status !== 'done');
                    renderPending();
                }, 2000);
            }
            renderPending();
            updateData();
        }

        // ================= بخش ۸: دانلود فایل با بررسی وجود فایل (جدید) =================
        // قبل از دانلود از سرور می‌پرسیم فایل هنوز روی دیسک هست یا نه:
        //   هست  -> دانلود در همین دستگاه شروع می‌شود (مرورگر خودش پیشرفت را نشان می‌دهد)
        //   نیست -> پاپ‌آپ نمایش داده می‌شود و کاربر به صفحه سفید JSON نمی‌رود
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
                } else {
                    showPopup('⚠️ File Not Found', 'This file has been deleted or does not exist anymore on the host device.');
                }
            } catch (err) {
                showPopup('⚠️ Connection Error', 'Could not reach the server. Please check your connection and try again.');
            }
        }

        // ================= بخش ۹: ارسال متن =================
        async function sendText() {
            const textInput = document.getElementById('text-input');
            const targetIds = Array.from(selectedClientIds).join(',');
            const textValue = textInput.value;
            if (!textValue.trim() || textValue.length > MAX_CHARS) return;
            if (!targetIds) { alert('Please select at least one recipient device first!'); return; }

            const formData = new FormData();
            formData.append('sender_id', clientId);
            formData.append('target_ids', targetIds);
            formData.append('text', textValue);

            try {
                let response = await fetch('/api/text', { method: 'POST', body: formData });
                await response.json();
                textInput.value = '';
                validateCharacterCount();
                updateData();
            } catch (err) { alert('Error sending text'); }
        }

        // ================= بخش ۱۰: همگام‌سازی با سرور =================
        // هر ۳ ثانیه اطلاعات جدید (دستگاه‌ها، آخرین دریافتی، تاریخچه) از سرور گرفته و نمایش داده می‌شود
        async function updateData() {
            try {
                let response = await fetch(`/api/sync?client_id=${clientId}`);
                let data = await response.json();

                renderDeviceCheckboxes(data.devices);

                // کادر «آخرین دریافتی»
                const latestBox = document.getElementById('latest-container');
                if (data.latest_received) {
                    latestBox.classList.remove('hidden');
                    document.getElementById('latest-type').innerText = `📥 Received from ${data.latest_received.sender_name}`;

                    if (data.latest_received.type === 'text') {
                        document.getElementById('latest-body').innerText = data.latest_received.content;
                        document.getElementById('latest-action-zone').innerHTML = `
                            <button class="copy-utility-btn" onclick="copyTextFromElement(document.getElementById('latest-body'), 'lbl-copy-latest')">
                                📋 <span id="lbl-copy-latest">Copy Text</span>
                            </button>
                        `;
                    } else {
                        document.getElementById('latest-body').innerText = `📦 File: ${data.latest_received.content}`;
                        // لینک دانلود حالا به جای رفتن مستقیم به آدرس، از handleDownload رد می‌شود
                        document.getElementById('latest-action-zone').innerHTML = `<a href="#" data-file="${encodeURIComponent(data.latest_received.content)}" onclick="handleDownload(event, this)" class="download-btn">📥 Download File</a>`;
                    }
                } else {
                    latestBox.classList.add('hidden');
                }

                // لیست تاریخچه
                const histList = document.getElementById('history-list');
                if (data.history.length === 0) {
                    histList.innerHTML = '<p style="text-align:center; color:var(--text-muted); font-size:12px;">No history records found.</p>';
                } else {
                    histList.innerHTML = '';
                    data.history.forEach((item, index) => {
                        const isInbound = item.receiver === clientId;
                        const directionClass = isInbound ? 'inbound' : 'outbound';
                        const badge = isInbound ? `From: ${escapeHtml(item.sender_name)}` : `To: ${escapeHtml(item.receiver_name)}`;

                        let ActionHtml = '';
                        if (item.type === 'file') {
                            ActionHtml = `<br><a href="#" data-file="${encodeURIComponent(item.content)}" onclick="handleDownload(event, this)" class="download-btn">Download Asset</a>`;
                        } else {
                            ActionHtml = `
                                <br><button class="copy-utility-btn" style="margin-top:4px; padding:2px 6px; font-size:10px;" onclick="copyTextFromElement(this.closest('.history-item').querySelector('.hist-content'), 'lbl-hist-${index}')">
                                    📋 <span id="lbl-hist-${index}">Copy Text</span>
                                </button>
                            `;
                        }

                        histList.innerHTML += `
                            <div class="history-item ${directionClass}">
                                <div class="hist-meta">
                                    <span>${badge} (${item.type.toUpperCase()})</span>
                                    <span>${item.time}</span>
                                </div>
                                <div class="hist-content">${escapeHtml(item.content)}</div>
                                ${ActionHtml}
                            </div>`;
                    });
                }
            } catch (err) { console.error('Sync failure'); }
        }

        // شروع برنامه: ping و sync اولیه، سپس تکرار دوره‌ای
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
