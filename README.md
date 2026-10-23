# DeskOS — Your Personal Workstation Dashboard

A lightweight, self-hosted workstation dashboard that turns an old Android phone into a dedicated desk display for your laptop.

DeskOS runs on your Ubuntu laptop and serves a live dashboard over your local Wi-Fi. Open it on a phone, tablet, or another browser to see your workstation status, monitor system resources, manage focus sessions, and receive warning alerts.

> **Built for:** Ubuntu/Linux + an Android phone such as the Realme C2  
> **Architecture:** Python backend + HTML, CSS and JavaScript frontend  
> **Deployment:** Local network, with optional systemd service

## ✨ Features

### 🕒 Digital desk clock
- Large digital clock with the current date.
- Responsive layout for desktop and mobile screens.
- Ambient clock mode for a clean, minimal display.
- Fullscreen support for a more dedicated desk-clock experience.

### 📊 Live workstation monitoring
Monitor your laptop's system status from your phone.

- CPU utilization.
- RAM utilization and usage details.
- Disk usage and available storage.
- Network download and upload activity.
- Disk read/write activity.
- System uptime.
- Battery status when available.
- CPU temperature only when a sensor has a recognizable CPU label; otherwise it is shown as unavailable.

### ⚠️ Workstation alerts
DeskOS checks system metrics and displays warnings when configured thresholds are reached.

- Sustained high CPU usage.
- Sustained high memory usage.
- High reported system temperature.
- Low available disk space.
- Warning popups for newly active warning conditions, rather than every changed metric value.
- Non-critical popups dismiss automatically after 10 seconds; critical warnings require manual acknowledgement.
- Optional custom alert audio.
- Browser-supported phone vibration for warnings.
- Separate warning and critical alert presentation.

**Note:** Audio and vibration depend on browser support, Android permissions, and page activity. A webpage cannot guarantee alerts when the browser is suspended or closed.

### 💻 Developer environment
- Detect running Node.js processes.
- Detect running Bun processes.
- Display detected process IDs.
- Lightweight process monitoring rather than continuous intensive scanning.

Process detection is informational; it does not currently establish whether an application or API endpoint is healthy.

### ⏱️ Focus timer
- 25-minute focus session.
- Start and pause controls.
- Reset functionality.
- Remaining-time display.

### 📱 Phone-friendly experience
- Responsive dashboard for smaller screens.
- Fullscreen mode.
- Screen Wake Lock support where available.
- Ambient clock mode when the laptop is unavailable.
- Automatic connection-status updates.
- Local-network access without requiring a cloud account.

### ⚙️ Lightweight operation
DeskOS is designed to reuse an existing laptop as the monitoring server and an old Android phone as the display. It avoids unnecessary cloud infrastructure and keeps monitoring work relatively infrequent.

Actual resource usage depends on the hardware, operating system, and enabled monitoring features.

---

## 🖥️ How it works

```text
┌─────────────────────────────┐
│       Ubuntu Laptop         │
│                             │
│  Python monitoring server   │
│  CPU / RAM / Disk / Network │
│  Temperature / Processes    │
└──────────────┬──────────────┘
               │
               │ Local Wi-Fi
               │ HTTP / JSON
               ▼
┌─────────────────────────────┐
│       Android Phone         │
│         Realme C2           │
│                             │
│  Digital clock              │
│  Live system dashboard      │
│  Warning popups             │
│  Sound and vibration        │
│  Focus timer                │
└─────────────────────────────┘
```

The laptop runs the backend and collects system metrics. The phone loads the dashboard and periodically requests updated information from the backend.

DeskOS is intended for a trusted local network. The default HTTP setup does not provide encryption or authentication.

---

## 🧰 Technology stack

| Technology | Purpose |
|---|---|
| Python | Backend server and system monitoring |
| psutil | CPU, memory, disk, network and process information |
| HTML | Dashboard structure |
| CSS | Responsive styling and dark interface |
| JavaScript | Clock, API polling, charts/meters, alerts and focus timer |
| Web Audio API / HTML audio | Browser-based alert sound |
| Vibration API | Phone vibration where supported |
| systemd | Optional automatic server startup on Linux |

---

## 📋 Requirements

On the laptop:

- Ubuntu or another compatible Linux distribution.
- Python 3.
- A working Wi-Fi or local network connection.
- A modern browser on the phone.
- Python dependencies listed in `requirements.txt`.

On the phone:

- Android with a compatible browser.
- Access to the same local network as the laptop.
- Sound and vibration enabled if you want warning notifications.

---

## 🚀 Getting started

### 1. Clone the repository

After uploading DeskOS to GitHub, clone your repository:

```bash
git clone https://github.com/YOUR_USERNAME/deskos.git
cd deskos
```

Replace `YOUR_USERNAME/deskos` with your actual GitHub repository path.

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

If Python's virtual-environment module is missing on Ubuntu, install it:

```bash
sudo apt update
sudo apt install python3-venv
```

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 4. Start the server

For a project whose backend entry point is `server.py`:

```bash
python server.py
```

The server defaults to port `8765`. To use port `8769` (as in the systemd example below), set the listening address and port explicitly:

```bash
DESKOS_HOST=0.0.0.0 DESKOS_PORT=8769 python server.py
```

Keep the terminal open while testing.

### 5. Open DeskOS on your phone

Find your laptop's local IP address:

```bash
hostname -I
```

For example, if the laptop's IP is `192.168.1.10` and the server uses port `8769`, open:

```text
http://192.168.1.10:8769
```

Use your laptop's actual IP address and the port configured for your server.

**Important:** The laptop and phone should be connected to the same network, and the firewall must allow the selected port. Some guest Wi-Fi networks isolate devices from one another.

### 6. Enable phone alerts

1. Open DeskOS on your phone.
2. Tap **Enable phone alerts**.
3. Confirm that the test sound and vibration work.
4. Keep the dashboard page active for the most reliable results.
5. Enable Android's **Stay awake while charging** option if you want the display to remain on while charging.

Browser-based vibration and sound are subject to device and browser limitations.

### Run regression tests

From the project root, run the backend tests with:

```bash
python -m unittest discover -s tests -v
```

The tests exercise the local health/status endpoints and CPU-temperature sensor selection. They do not verify browser behavior or physical phone alerts.

---

## 🔔 Configure a custom alert sound

DeskOS can play a custom audio file instead of generating a basic beep.

The dashboard's audio element should point to a path that your backend actually serves. For example:

```javascript
const alertSound = new Audio('/sounds/my-alert.mp3');
alertSound.preload = 'auto';
alertSound.volume = 1.0;
```

Place the sound file in the appropriate directory for your server's static-file configuration, and update the URL to match that configuration.

For example, if your server serves the `static` directory at `/static`, a file located at `static/sounds/my-alert.mp3` would normally be referenced as:

```javascript
const alertSound = new Audio('/static/sounds/my-alert.mp3');
```

To play it when a warning appears:

```javascript
async function playAlertSound() {
  try {
    alertSound.pause();
    alertSound.currentTime = 0;
    await alertSound.play();
  } catch (error) {
    console.warn('Could not play DeskOS alert sound:', error);
  }
}
```

Call this function from your existing alert handler rather than creating a new audio object on every dashboard refresh.

The browser may require a user interaction before allowing sound playback.

### Vibration

A longer vibration pattern can be requested through the browser's Vibration API:

```javascript
if ('vibrate' in navigator) {
  navigator.vibrate([500, 150, 500, 150, 700]);
}
```

The values represent alternating vibration and pause durations in milliseconds. The phone controls the actual vibration intensity; JavaScript cannot directly increase motor strength.

---

## 🔄 Run DeskOS automatically with systemd

You can run the backend as a background service so it starts automatically when Ubuntu boots.

Create a service file:

```bash
sudo nano /etc/systemd/system/deskos.service
```

Add the following configuration, adjusting the paths and port to match your installation:

```ini
[Unit]
Description=DeskOS Workstation Dashboard
After=network.target

[Service]
Type=simple
User=YOUR_LINUX_USERNAME
WorkingDirectory=/absolute/path/to/deskos
Environment=DESKOS_HOST=0.0.0.0
Environment=DESKOS_PORT=8769
ExecStart=/absolute/path/to/deskos/.venv/bin/python /absolute/path/to/deskos/server.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Replace `YOUR_LINUX_USERNAME` and both project paths before saving. The `ExecStart` command must use the actual Python interpreter and backend file locations.

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now deskos
```

Check its status:

```bash
sudo systemctl status deskos
```

Follow the logs:

```bash
journalctl -u deskos -f
```

Restart it after changing backend code:

```bash
sudo systemctl restart deskos
```

**Laptop sleep:** systemd does not prevent Ubuntu from suspending. Configure your laptop's power settings if you need the dashboard server to stay available continuously.

---

## 🛠️ Troubleshooting

### The phone says "Laptop unavailable"

1. Confirm that DeskOS is running on the laptop.
2. Verify that the phone uses the correct laptop IP and server port.
3. Open the backend's `/api/status` endpoint directly in the phone browser.
4. Confirm that the endpoint returns JSON.
5. Check firewall rules and Wi-Fi client isolation.
6. Inspect the backend logs for errors.

### The custom sound does not play

- Verify that the audio URL opens directly in the phone browser.
- Check that the file exists at the expected server path.
- Ensure the filename and extension match exactly.
- Tap the phone's **Enable phone alerts** button before testing.
- Check Android media volume and browser restrictions.

### Vibration does not work

- Confirm that the phone supports browser-triggered vibration.
- Check Android settings and vibration permissions.
- Test while the dashboard is open and active.
- Remember that some browsers do not implement the Vibration API.

### CPU temperature or battery information is missing

Not all systems expose the same sensors. Battery readings depend on the laptop hardware, and temperature readings depend on available Linux sensor drivers. Missing values do not necessarily indicate a DeskOS failure.

### The service fails to start

Check the service logs:

```bash
journalctl -u deskos -n 100 --no-pager
```

Verify the working directory, Python executable, dependencies, configured port, and server environment-variable support.

---

## 🔐 Security and privacy

- DeskOS is designed for use on a trusted local network.
- The default setup uses HTTP, not HTTPS.
- Do not expose the server port directly to the public internet.
- The dashboard may reveal workstation information, such as resource usage and running process IDs.
- Use a trusted Wi-Fi network and appropriate firewall rules.
- Add authentication and encrypted transport before exposing the dashboard beyond your trusted local network.

---

## 🗺️ Future improvements

Potential future enhancements include:

- Configurable CPU, RAM, temperature and storage thresholds.
- Separate sound profiles for warnings and critical alerts.
- A dashboard settings panel for choosing alert sounds and vibration patterns.
- Configurable monitoring intervals.
- Application and API health checks for Node.js and Bun projects.
- More detailed service monitoring.
- Better support for offline and reconnection states.
- Secure controls for workstation power management.
- A configurable dashboard layout and additional clock styles.

These are possible future enhancements, not promises that every feature is already implemented.

---

## 🤝 Contributing

Suggestions, bug reports, and contributions are welcome.

1. Fork the repository.
2. Create a feature branch.
3. Make a focused change.
4. Test the dashboard on your intended device.
5. Open a pull request with a clear explanation.

Please avoid committing personal audio files, credentials, private IP details, virtual environments, or machine-specific configuration.

---

## 📄 License

Choose a license before publishing the repository. For example, the MIT License is a common choice for open-source software. If you select MIT, add a `LICENSE` file with the appropriate copyright holder and year.

---

**DeskOS — Give your old phone a new purpose.**

A lightweight dashboard for the workstation you use every day.
