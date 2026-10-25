# DeskOS v2 — Workstation Companion & Intelligent Desk Assistant

[![Docker Stack](https://img.shields.io/badge/Docker-Compose%20v2-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![Raspberry Pi](https://img.shields.io/badge/Hardware-Raspberry%20Pi%204-C51850?logo=raspberrypi&logoColor=white)](https://www.raspberrypi.org/)
[![Nginx SSL](https://img.shields.io/badge/Security-Nginx%20HTTPS%20%2B%20SAN-009639?logo=nginx&logoColor=white)](https://nginx.org/)
[![Google Gemini](https://img.shields.io/badge/AI-Gemini%20Flash%20Lite-8E75C2?logo=google&logoColor=white)](https://aistudio.google.com/)
[![Google Workspace](https://img.shields.io/badge/Workspace-Calendar%20%2B%20Docs-4285F4?logo=google&logoColor=white)](https://workspace.google.com/)

A modern, containerized **Workstation Companion & Voice-Powered Desk Assistant**. DeskOS transforms any dedicated screen, tablet, or phone (such as a docked Realme C2 or iPad) into an autonomous desk HUD that continuously monitors your primary workstation laptop, organizes tasks, manages Google Calendar and Docs, and answers voice commands with zero cloud latency.

---

## 🏗️ System Architecture

DeskOS follows an asynchronous **Master-Agent Companion Architecture**:

```
 ┌────────────────────────────────────────┐       ┌──────────────────────────────────────────────────┐
 │      WORKSTATION LAPTOP (Client)       │       │             DESK COMPANION (Host)                │
 │       aryam-Vostro-3405 (Ubuntu)       │       │          Raspberry Pi 4 / Docker Host            │
 │                                        │       │                                                  │
 │  ┌──────────────────────────────────┐  │       │   ┌──────────────────────────────────────────┐   │
 │  │      Telemetry Sidecar Agent     │  │ HTTPS │   │         Nginx Reverse Proxy (:443)       │   │
 │  │        (systemd user daemon)     │──┼───────┼──>│       SSL SAN + HTTP/2 + SSE unbuffered  │   │
 │  │   CPU, RAM, NVMe, Battery, Temp  │  │ PUSH  │   └────────────────────┬─────────────────────┘   │
 │  └──────────────────────────────────┘  │       │                        │ :8765                   │
 └────────────────────────────────────────┘       │   ┌────────────────────▼─────────────────────┐   │
                                                  │   │         DeskOS Master Core Container     │   │
                                                  │   │  • SSE Real-time Broadcaster             │   │
                                                  │   │  • Zero-Trust 6-Digit Device PIN Gate    │   │
 ┌────────────────────────────────────────┐       │   │  • Gemini Function Calling Engine        │   │
 │         PHONE / TABLET DOCK            │       │   │  • Google Calendar & Docs Services       │   │
 │        Realme C2 / Mobile Browser      │       │   │  • SQLite Task & Reminder Store          │   │
 │                                        │       │   └──────────────────────────────────────────┘   │
 │  ┌──────────────────────────────────┐  │       └──────────────────────────────────────────────────┘
 │  │        DeskOS HTML5 HUD          │  │
 │  │  • Real-time SSE Gauges          │  │
 │  │  • Mobile Push-To-Talk (PTT)     │  │
 │  │  • Hardware Alarm (my-alert.mp3) │<─┴─────── (Live SSE Telemetry + Voice Feedback)
 │  └──────────────────────────────────┘
 └────────────────────────────────────────┘
```

---

## ✨ Core Capabilities

### 1. 📊 Workstation Telemetry Companion
* **Zero Container Distortion:** The Pi displays actual workstation metrics (`aryam-Vostro-3405`) pushed from your laptop sidecar agent, rather than the Pi's internal Docker stats.
* **Full Hardware Telemetry:** CPU load, RAM allocation, NVMe read/write throughput, battery percentage, charging state, core thermals, and active development runtimes (Node, Bun, Docker, VS Code).
* **Real-time Server-Sent Events (SSE):** Metric broadcasts arrive every 2–3 seconds over an unbuffered HTTP stream (`proxy_buffering off;`) with zero polling overhead.

### 2. 🚨 Hardware Warning Thresholds & Audible Alarm
* **Automatic Detection:** DeskOS analyzes incoming hardware counters:
  * Sustained CPU $\ge 90\%$ (3 samples) $\rightarrow$ Warning / Critical if $\ge 96\%$
  * Sustained RAM $\ge 90\%$ (3 samples) $\rightarrow$ Warning / Critical if $\ge 95\%$
  * CPU Thermals $\ge 85^\circ\text{C}$ $\rightarrow$ Warning / Critical if $\ge 92^\circ\text{C}$
  * Low Storage: $< 8\%$ free on primary disk.
* **Audible Alarm:** Automatically plays `/sounds/my-alert.mp3` at full volume.
* **Haptics & Visuals:** Displays pulsating amber/red alert banners and triggers mobile device vibration.

### 3. 🎙️ Voice Assistant & Smart Speech Engine
* **Phonetic Wake Word:** Supports *"Hello Desk"*, *"Hey Desk"*, *"Ok Desk"*, and *"Desk"* with tactile audio feedback.
* **Mobile Push-To-Talk (PTT) Mode:** Automatically detects mobile devices (such as Android / Realme C2) and disables continuous background microphone polling. This **completely eliminates the annoying repetitive Android OS mic chime loop** while preserving battery.
* **Dual-Microphone Anti-Stutter Filter (`cleanDuplicateSpeech`):** Cleans and deduplicates transcript stutter caused by smartphone beamforming and noise-cancelling dual mics.
* **Multilingual Recognition:** Supports `en-IN`, `hi-IN`, and `en-US` Speech Recognition.

### 4. 📅 Google Workspace Integration
* **Google Calendar:** Real-time agenda deck showing today's and upcoming meetings. Cancel meetings directly from the HUD or via voice (*"Cancel my meeting with Johnny"*).
* **Google Docs:** Generates meeting briefs, task recaps, and notes directly to Google Drive via voice commands (*"Create a doc summarizing my daily standup"*).
* **Token Persistence:** Seamless offline OAuth refresh token persistence in `data/token.json`.

### 5. 🔒 Zero-Trust Device Security & Pairing Gate
* **6-Digit Pairing PIN:** Unknown remote devices are blocked by a secure modal gate until authenticated using the PIN displayed on the workstation terminal or configured in `.env`.
* **365-Day Session Cookie:** Authenticated devices receive a cryptographically secure `deskos_token` cookie valid for 1 year.
* **Localhost Bypass:** Loopback (`127.0.0.1`) is auto-whitelisted for local kiosk and developer use.

---

## 📁 Repository Structure

```
deskos/
├── agent/
│   └── desk_agent.py             # Workstation telemetry sidecar daemon (runs on laptop)
├── assistant.py                  # Gemini function-calling router & assistant tools
├── data/                         # Persistent volume mount (SQLite, tokens, auth state)
│   ├── authorized_devices.json   # (Ignored) Paired device tokens
│   ├── deskos.sqlite3            # (Ignored) Tasks and reminders database
│   └── token.json                # (Ignored) Google Workspace OAuth tokens
├── device_auth.py                # Zero-trust PIN validation & cookie authorization
├── docker-compose.yml            # Multi-container orchestration (DeskOS + Nginx)
├── Dockerfile                    # Multi-arch Debian Bookworm Python 3.11 image
├── nginx/
│   ├── certs/                    # SSL certificates (deskos.crt, deskos.key)
│   └── nginx.conf                # HTTPS redirect & unbuffered SSE streaming config
├── reminder_store.py             # SQLite persistence layer for tasks & schedules
├── requirements.txt              # Production Python dependencies
├── scripts/
│   ├── deploy_to_pi.py           # Automated SSH/rsync sync and container reload
│   ├── gen_certs.sh              # OpenSSL multi-domain & IP SAN certificate generator
│   └── install_laptop_agent.sh   # Systemd service installer for laptop telemetry agent
├── server.py                     # Asynchronous DeskOS master HTTP & SSE server
├── services/
│   ├── calendar_service.py       # Google Calendar API integration
│   ├── docs_service.py           # Google Docs & Drive API integration
│   └── gmail_service.py          # Gmail API integration
└── static/
    ├── icons/                    # Web manifest PWA icons
    ├── index.html                # Single-page Desk Assistant console (100dvh, zero scroll)
    └── sounds/
        └── my-alert.mp3          # Workstation hardware siren audio
```

---

## 🚀 Installation & Deployment Guide

### Prerequisites
* **Master Host:** Raspberry Pi 4 (or Linux server) with Docker & Docker Compose installed.
* **Workstation:** Ubuntu / Debian laptop with Python 3.10+ and `psutil`.
* **Display Device:** Any smartphone, tablet, or secondary monitor on the local Wi-Fi.

---

### Step 1: Configure Environment on Raspberry Pi

1. Clone or copy the repository to your Raspberry Pi:
   ```bash
   git clone https://github.com/your-username/deskos.git ~/deskos
   cd ~/deskos
   ```

2. Create your `.env` configuration:
   ```bash
   cp .env.example .env
   nano .env
   ```
   Populate your keys:
   ```ini
   GEMINI_API_KEY=your_gemini_api_key_here
   DESKOS_GEMINI_MODEL=gemini-flash-lite-latest
   DESKOS_DEVICE_PIN=010622
   DESKOS_AGENT_SECRET=deskos-laptop-secret-key
   ```

3. Generate the Multi-Domain SSL Certificate (includes IP SAN):
   ```bash
   bash scripts/gen_certs.sh
   ```

4. Launch the Docker Stack:
   ```bash
   sudo docker-compose up -d --build
   ```
   Check status:
   ```bash
   sudo docker-compose ps
   ```

---

### Step 2: Install Workstation Telemetry Agent on Your Laptop

To stream live CPU, RAM, NVMe, and temperature metrics from your laptop to the Raspberry Pi:

1. On your laptop, install dependencies:
   ```bash
   pip install psutil
   ```

2. Run the automated systemd installer:
   ```bash
   bash scripts/install_laptop_agent.sh "https://raspberrypi.local"
   ```
   *(Or pass the Pi's IP: `bash scripts/install_laptop_agent.sh "https://192.168.29.137"`)*

3. Verify the service is active and streaming:
   ```bash
   systemctl --user status deskos-agent.service
   journalctl --user -u deskos-agent.service -f
   ```

---

### Step 3: Access DeskOS on Mobile Devices & Tablets

#### On Modern Devices (Android 12+, iOS, iPadOS, Desktop):
* Open Chrome or Safari and go to:
  ```
  https://raspberrypi.local
  ```
  *(or `https://deskos.local`)*

#### On Older Devices (Android 9, Realme C2, ColorOS):
Android 9 does not natively resolve `.local` mDNS domains. Access the Pi directly via its static LAN IP:
1. Connect your phone to your **home Wi-Fi**.
2. Open **Google Chrome**.
3. Navigate to:
   ```
   https://192.168.29.137
   ```
4. Tap **"Advanced"** $\rightarrow$ **"Proceed to 192.168.29.137 (unsafe)"** *(bypasses local self-signed certificate)*.
5. Enter your 6-digit Device Pairing PIN: **`010622`**.

---

## 🛠️ Rapid Updates & Development Sync

The [scripts/deploy_to_pi.py](file:///home/aryam/Documents/deskos/scripts/deploy_to_pi.py) script allows you to make changes on your laptop and instantly deploy them to the Pi in seconds without slow Docker rebuilds:

```bash
# Deploys code, static files, and SSL certs, then hot-restarts the Pi container:
python3 scripts/deploy_to_pi.py
```

---

## 🛡️ Git Safety & Sensitive Files (`.gitignore`)

DeskOS is designed with strict security practices. The following sensitive files are **never committed to version control**:

| File / Pattern | Reason for Exclusion |
| :--- | :--- |
| `.env` / `.env.*` | Stores your private `GEMINI_API_KEY` and `DESKOS_AGENT_SECRET`. |
| `credentials.json` | Google Cloud Console OAuth 2.0 Client Secrets. |
| `data/token.json` | Google user offline refresh tokens. |
| `data/authorized_devices.json` | Authorized device session tokens. |
| `data/*.sqlite3*` | Local databases holding personal tasks and reminders. |
| `nginx/certs/*.key`, `*.crt` | Private SSL keys and TLS certificates. |
| `scripts/deploy_to_pi.py` | Local deployment automation containing host SSH passwords. |
| `/static/sounds/my-alert.mp3` | Large local audio assets. |

Always use `.env.example` as a template for committing configuration documentation.

---

## 📋 API & Route Reference

| Route / Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/` or `/assistant` | `GET` | Main Desk Assistant HUD and telemetry cluster. |
| `/tasks` | `GET` | Task and agenda management deck. |
| `/google` | `GET` | Google Calendar events and Google Docs view. |
| `/reminders` | `GET` | Scheduled reminder deck. |
| `/analytics` | `GET` | Productivity velocity & hardware analytics deck. |
| `/api/events` | `GET` | Real-time Server-Sent Events (SSE) telemetry stream. |
| `/api/status` | `GET` | Current workstation hardware snapshot. |
| `/api/telemetry/report` | `POST` | Ingestion endpoint for workstation telemetry agent. |
| `/api/auth/pair` | `POST` | 6-digit PIN device pairing endpoint. |
| `/api/assistant/enqueue` | `POST` | Natural language voice & text command router. |
| `/api/calendar/events` | `GET` | Google Calendar synchronization. |
| `/api/docs` | `GET` | Google Docs generated notes list. |

---

## 📜 License
DeskOS is open-source under the MIT License. Developed for self-hosted productivity and private home workstation companionship.
