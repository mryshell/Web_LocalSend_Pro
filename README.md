# 🚀 Web LocalSend Pro

<p align="center">
  <a href="README.fa.md">🔴 <b>فارسی</b></a> | 
  <a href="README.md">🔵 <b>English</b></a>
</p>

A lightweight, secure, and ultra-fast web-based tool for **secure file and text transfer** between devices (Windows, Linux, Android, iOS) over a local network (shared Wi-Fi) without requiring internet or third-party apps.

---

## ✨ Key Features

* **Privacy First:** Does not read or parse sensitive text files (prevents token leaks and exploits).
* **Smart Character Counter:** Built-in validation with a live warning for a 10,000-character ceiling.
* **QR Code Sharing:** Automatically generates QR codes for instant mobile connection.
* **Auto-Shutdown System (Heartbeat):** Automatically closes the server if the host browser crashes or closes to secure the system.
* **Auto Dependency Installer:** Installs required packages (`FastAPI`, `Uvicorn`) on the first run.

---

## 🛠️ Setup & Execution

### 1. Prerequisites
Make sure `Python 3` is installed on your system.

### 2. Run the Server
Open your `terminal`/`CMD` in the project directory and run:

```bash
python localsend.py

