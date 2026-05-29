import subprocess
import sys
import socket
import os
import webbrowser
import time
from threading import Timer, Thread

# Required packages
REQUIRED_PACKAGES = ["fastapi", "uvicorn", "python-multipart"]

def auto_install_dependencies():
    """Checks and installs missing packages automatically."""
    import importlib
    for package in REQUIRED_PACKAGES:
        try:
            importlib.import_module(package.replace("-", "_"))
        except ImportError:
            print(f"[*] Missing package '{package}'. Installing...")
            try:
                cmd = [sys.executable, "-m", "pip", "install", package]
                if os.name != "nt":
                    cmd.append("--break-system-packages")
                subprocess.check_call(cmd)
            except Exception as e:
                print(f"[!] Failed to install {package}: {e}")
                sys.exit(1)
    importlib.invalidate_caches()

auto_install_dependencies()

from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, FileResponse
from typing import List

app = FastAPI()

# Setup download directory
UPLOAD_DIR = os.path.join(os.path.expanduser('~'), 'Downloads', 'WebLocalSend')
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Central Memory Storage
online_devices = {}  # {client_id: {"name": str, "ip": str, "last_seen": float}}
transfers = []       # [{"id": int, "sender": str, "receiver": str, "type": str, "content": str, "time": str}]

# Heartbeat State Tracking
HOST_CONNECTED = False
HOST_LAST_SEEN = time.time()
START_TIME = time.time()

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def monitor_host_heartbeat():
    """Background thread that destroys the server if the host browser crashes or closes."""
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

# Secure Core UI with Real-time Character Counter Engine
HTML_UI = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Web LocalSend Pro</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/qrious/4.0.2/qrious.min.js" defer></script>
    <style>
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
        body.light-theme {
            --bg-body: #f3f4f6;
            --bg-card: #ffffff;
            --text-main: #1f2937;
            --bg-input: #f9fafb;
            --border-color: #d1d5db;
            --text-muted: #6b7280;
        }
        body {
            background-color: var(--bg-body); color: var(--text-main);
            font-family: system-ui, -apple-system, sans-serif;
            display: flex; flex-direction: column; min-height: 100vh;
            align-items: center; justify-content: center; margin: 0; padding: 16px; box-sizing: border-box;
            transition: background-color 0.2s, color 0.2s;
        }
        .card {
            width: 100%; max-width: 420px; background-color: var(--bg-card);
            border-radius: 24px; padding: 24px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.3);
            border: 1px solid var(--border-color); box-sizing: border-box;
        }
        
        .top-controls { display: flex; justify-content: flex-end; align-items: center; margin-bottom: 16px; }
        .theme-btn { background: none; border: 1px solid var(--border-color); color: var(--text-main); padding: 6px 12px; border-radius: 8px; cursor: pointer; font-size: 11px; font-weight: bold; }
        .theme-btn:hover { background: var(--bg-body); }

        h1 { color: var(--accent-color); margin: 0 0 4px 0; font-size: 24px; text-align: center; }
        
        .name-container { text-align: center; margin-bottom: 16px; }
        .name-input {
            width: 80%; max-width: 260px; background: var(--bg-input); border: 1px solid var(--border-color);
            border-radius: 8px; padding: 6px 12px; color: #6ee7b7; text-align: center; font-size: 14px; font-weight: bold;
        }
        .name-input:focus { outline: none; border-color: var(--accent-color); }

        .qr-box { display: flex; justify-content: center; margin: 12px auto; background: white; padding: 8px; border-radius: 16px; width: 130px; height: 130px; }
        .url-tag { background-color: var(--bg-input); color: #6ee7b7; font-family: monospace; padding: 4px 10px; border-radius: 8px; font-size: 11px; display: inline-block; margin-bottom: 16px; border: 1px solid var(--border-color); }
        
        .label { font-size: 12px; color: var(--text-muted); font-weight: bold; margin-bottom: 6px; display: block; text-align: left; }
        
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

        textarea {
            width: 100%; background-color: var(--bg-input); border: 1px solid var(--border-color);
            border-radius: 10px; padding: 10px; color: var(--text-main); box-sizing: border-box; font-size: 14px;
        }
        textarea:focus { outline: none; border-color: var(--accent-color); }
        
        .counter-container {
            display: flex; justify-content: flex-end; font-size: 11px; color: var(--text-muted); margin-top: 4px; margin-bottom: 14px; font-weight: bold;
        }
        .counter-container.danger { color: var(--danger-color); }

        .dropzone {
            border: 2px dashed var(--border-color); border-radius: 14px; padding: 24px 16px; text-align: center; position: relative; cursor: pointer; margin-bottom: 14px;
        }
        .dropzone:hover { border-color: var(--accent-color); }
        .dropzone input { position: absolute; top: 0; left: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; }
        
        .btn {
            width: 100%; background-color: var(--accent-color); color: #111827; font-weight: bold; padding: 10px; border-radius: 10px; border: none; cursor: pointer; transition: background 0.2s; font-size: 14px;
        }
        .btn:hover { background-color: #059669; }
        .btn:disabled { background-color: var(--border-color); color: var(--text-muted); cursor: not-allowed; }
        .btn-secondary { background-color: var(--border-color); color: var(--text-main); margin-top: 8px; }
        .btn-secondary:hover { background-color: var(--text-muted); color: #111827; }
        
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

        .modal-overlay {
            position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7);
            display: flex; align-items: center; justify-content: center; z-index: 1000; visibility: hidden; opacity: 0; transition: all 0.2s ease;
        }
        .modal {
            background-color: var(--bg-card); border: 1px solid var(--border-color); width: 90%; max-width: 450px; border-radius: 20px; padding: 20px; box-sizing: border-box; display: flex; flex-direction: column; max-height: 80vh;
        }
        .modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; border-bottom: 1px solid var(--border-color); padding-bottom: 8px; }
        .modal-title { font-size: 16px; font-weight: bold; color: var(--accent-color); }
        .close-modal { color: var(--text-muted); font-size: 20px; cursor: pointer; background: none; border: none; }
        .close-modal:hover { color: var(--text-main); }
        .modal-body { overflow-y: auto; flex-grow: 1; padding-right: 4px; }
        
        .history-item { background: var(--bg-input); border-radius: 10px; padding: 10px; margin-bottom: 8px; font-size: 12px; border-left: 3px solid var(--border-color); text-align: left;}
        .history-item.inbound { border-left-color: var(--accent-color); }
        .history-item.outbound { border-left-color: #3b82f6; }
        .hist-meta { display: flex; justify-content: space-between; color: var(--text-muted); font-size: 10px; margin-bottom: 4px; }
        
        .hist-content { 
            font-family: monospace; word-break: break-all; color: var(--text-main); white-space: pre-wrap;
            display: -webkit-box; -webkit-line-clamp: 5; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis;
        }
        
        .download-btn { color: var(--accent-color); text-decoration: none; font-weight: bold; margin-top: 4px; display: inline-block; }
        .hidden { display: none !important; }
    </style>
</head>
<body>

    <div class="card">
        <div class="top-controls">
            <button class="theme-btn" onclick="switchTheme()">🌓 Change Mode</button>
        </div>

        <h1>Web LocalSend Pro</h1>
        <div class="name-container">
            <input type="text" id="my-name-input" class="name-input" oninput="updateMyName(this.value)" placeholder="Enter your name...">
        </div>
        
        <div class="qr-box"><canvas id="qr-code"></canvas></div>
        <div style="text-align: center;"><div class="url-tag">SERVER_URL_PLACEHOLDER</div></div>
        
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

        <div class="dropzone">
            <input type="file" id="file-input" multiple onchange="uploadFiles()">
            <span style="color: var(--text-muted); font-size: 13px;">Drag & Drop files or click to send</span>
        </div>

        <textarea id="text-input" rows="2" placeholder="Type message or paste links to send..." oninput="validateCharacterCount()"></textarea>
        <div class="counter-container" id="char-counter-label">Remaining: 10,000</div>
        
        <button id="submit-text-btn" onclick="sendText()" class="btn">Send Securely</button>
        
        <button onclick="toggleModal(true)" class="btn btn-secondary">📜 View Full History</button>

        <div id="latest-container" class="latest-box hidden">
            <div class="latest-title" id="latest-type">📥 Latest Received</div>
            <div class="latest-content" id="latest-body">No data yet.</div>
            <div id="latest-action-zone"></div>
        </div>
    </div>

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

    <script>
        if (!localStorage.getItem('client_id')) {
            localStorage.setItem('client_id', 'dev_' + Math.random().toString(36).substring(2, 11));
        }
        const clientId = localStorage.getItem('client_id');

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

        if (localStorage.getItem('cfg_theme') === 'light') {
            document.body.classList.add('light-theme');
        }

        let selectedClientIds = new Set();
        const MAX_CHARS = 10000;

        function switchTheme() {
            document.body.classList.toggle('light-theme');
            const mode = document.body.classList.contains('light-theme') ? 'light' : 'dark';
            localStorage.setItem('cfg_theme', mode);
        }

        function updateMyName(val) {
            let cleanName = val.trim();
            if(!cleanName) cleanName = "Anonymous";
            myName = cleanName;
            localStorage.setItem('custom_nickname', cleanName);
            pingServer();
        }

        // Live Integrity Engine for Input Text Fields
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

        window.addEventListener('DOMContentLoaded', () => {
            if (typeof QRious !== 'undefined') {
                new QRious({ element: document.getElementById('qr-code'), value: "SERVER_URL_PLACEHOLDER", size: 130 });
            }
        });

        window.addEventListener('pagehide', () => {
            if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
                navigator.sendBeacon('/api/shutdown');
            }
        });

        function toggleSelectAll(masterCanvas) {
            const boxes = document.querySelectorAll('.device-single-checkbox');
            selectedClientIds.clear();
            boxes.forEach(box => {
                box.checked = masterCanvas.checked;
                if(masterCanvas.checked) selectedClientIds.add(box.value);
            });
        }

        function handleSingleCheckboxChange(box) {
            if(box.checked) {
                selectedClientIds.add(box.value);
            } else {
                selectedClientIds.delete(box.value);
                document.getElementById('check-all-devices').checked = false;
            }
        }

        function toggleModal(show) {
            const modal = document.getElementById('history-modal');
            modal.style.visibility = show ? 'visible' : 'hidden';
            modal.style.opacity = show ? '1' : '0';
            if(show) updateData();
        }

        async function pingServer() {
            try {
                await fetch('/api/ping', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body: `client_id=${clientId}&name=${encodeURIComponent(myName)}`
                });
            } catch(e) {}
        }

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
                        <label for="chk-${id}">${dev.name} <span style="color:var(--text-muted); font-size:11px;">[${dev.ip}]</span></label>
                    </div>
                `;
            });
            boxContainer.innerHTML = htmlContent;
        }

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

        async function uploadFiles() {
            const fileInput = document.getElementById('file-input');
            const targetIds = Array.from(selectedClientIds).join(',');
            if (fileInput.files.length === 0) return;
            if (!targetIds) { alert('Please select at least one recipient device first!'); fileInput.value=''; return; }

            const formData = new FormData();
            formData.append('sender_id', clientId);
            formData.append('target_ids', targetIds);
            for (let file of fileInput.files) { formData.append('files', file); }

            try {
                let response = await fetch('/api/upload', { method: 'POST', body: formData });
                await response.json();
                fileInput.value = '';
                updateData();
            } catch (err) { alert('Error uploading files'); }
        }

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

        async function updateData() {
            try {
                let response = await fetch(`/api/sync?client_id=${clientId}`);
                let data = await response.json();

                renderDeviceCheckboxes(data.devices);

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
                        document.getElementById('latest-action-zone').innerHTML = `<a href="/download/${encodeURIComponent(data.latest_received.content)}" class="download-btn">📥 Download File</a>`;
                    }
                } else {
                    latestBox.classList.add('hidden');
                }

                const histList = document.getElementById('history-list');
                if (data.history.length === 0) {
                    histList.innerHTML = '<p style="text-align:center; color:var(--text-muted); font-size:12px;">No history records found.</p>';
                } else {
                    histList.innerHTML = '';
                    data.history.forEach((item, index) => {
                        const isInbound = item.receiver === clientId;
                        const directionClass = isInbound ? 'inbound' : 'outbound';
                        const badge = isInbound ? `From: ${item.sender_name}` : `To: ${item.receiver_name}`;
                        
                        let ActionHtml = '';
                        if (item.type === 'file') {
                            ActionHtml = `<br><a href="/download/${encodeURIComponent(item.content)}" class="download-btn">Download Asset</a>`;
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
                                <div class="hist-content">${item.content}</div>
                                ${ActionHtml}
                            </div>`;
                    });
                }
            } catch (err) { console.error('Sync failure'); }
        }

        pingServer();
        updateData();
        setInterval(pingServer, 4000); 
        setInterval(updateData, 3000);  
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def read_root():
    local_ip = get_local_ip()
    port = 5050
    return HTML_UI.replace("SERVER_URL_PLACEHOLDER", f"http://{local_ip}:{port}")

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
            file_path = os.path.join(UPLOAD_DIR, file.filename)
            with open(file_path, "wb") as f:
                f.write(await file.read())
            
            for target in targets:
                if target.strip():
                    transfers.append({
                        "id": len(transfers) + 1,
                        "sender": sender_id,
                        "receiver": target.strip(),
                        "type": "file",
                        "content": file.filename,
                        "time": timestamp
                    })
    return {"status": "success", "message": "Files successfully routed."}

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

@app.post("/api/shutdown")
def kill_server_instance():
    print("\n[!] Host trigger received. Executing clean auto-shutdown process...")
    os._exit(0)

@app.get("/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(path=file_path, filename=filename, media_type='application/octet-stream')
    return {"status": "error", "message": "File not found."}

def open_browser(url):
    webbrowser.open(url)

if __name__ == "__main__":
    local_ip = get_local_ip()
    port = 5050
    server_url = f"http://127.0.0.1:{port}"
    
    print("\n" + "="*60)
    print(f"[*] Cluster Activated. Server local link: {server_url}")
    print(f"[*] Access Link for target nodes: http://{local_ip}:{port}")
    print("="*60 + "\n")
    
    Thread(target=monitor_host_heartbeat, daemon=True).start()
    Timer(1.5, open_browser, args=[server_url]).start()
    
    import importlib
    uvicorn_module = importlib.import_module("uvicorn")
    uvicorn_module.run(app, host="0.0.0.0", port=port)
