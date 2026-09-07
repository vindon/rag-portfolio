# Acme Corp IT Helpdesk — Knowledge Base
**Internal IT Support Reference | Updated January 2025**

---

## Password Management

### Resetting Your Password
**Self-service reset (fastest — available 24/7):**
1. Go to https://sso.acmecorp.internal/reset
2. Enter your corporate email address
3. Click the reset link sent to your registered mobile number via SMS
4. Choose a new password meeting the requirements below
5. Your new password is active immediately

**Password requirements:**
- Minimum 12 characters
- At least one uppercase letter, one lowercase letter, one number, one symbol
- Cannot reuse last 10 passwords
- Must not contain your name or email address

**If you're locked out (5 failed attempts):**
- Account locks for 30 minutes automatically, OR
- Call IT Helpdesk: ext. 4357 (HELP) for immediate unlock
- Slack: #it-helpdesk channel with your employee ID

**Password expiry:** Corporate passwords expire every 90 days. You will receive email reminders at 14 days and 3 days before expiry.

### Multi-Factor Authentication (MFA)
MFA is mandatory for all corporate accounts. Supported methods:
- **Microsoft Authenticator** (recommended) — push notification
- **Google Authenticator** — TOTP code
- **Hardware token (YubiKey)** — contact IT for hardware token issuance

To enroll or change MFA method: https://mfa.acmecorp.internal

---

## VPN Setup

### Cisco AnyConnect VPN (Corporate Standard)
VPN is required for all remote access to internal systems.

**Windows installation:**
1. Download from: https://software.acmecorp.internal/vpn/anyconnect-win.exe
2. Run installer as Administrator
3. Accept the End User License Agreement
4. Server address: vpn.acmecorp.com
5. Use your corporate username (firstname.lastname) and password
6. MFA prompt will appear — approve in Authenticator app

**macOS installation:**
1. Download from: https://software.acmecorp.internal/vpn/anyconnect-mac.dmg
2. Open the .dmg file and run the installer
3. Grant System Extension permissions when prompted (System Preferences → Security)
4. Server address: vpn.acmecorp.com
5. Connect with your corporate credentials + MFA

**Linux (Ubuntu/Debian):**
```bash
sudo apt install openconnect
sudo openconnect vpn.acmecorp.com --user=firstname.lastname
```

**Common VPN issues:**
- "Certificate error" → Download and install the corporate root CA from https://pki.acmecorp.internal/ca.crt
- "Connection timeout" → Try alternate server: vpn2.acmecorp.com
- "Authentication failed" → Verify MFA is enrolled and clock is synced
- Split tunnelling is enabled — only Acme traffic routes through VPN

---

## Software Installation

### Approved Software Catalogue
All software installations must use approved versions from the Acme software portal.

**Portal URL:** https://software.acmecorp.internal
**Direct requests:** Submit a ticket at https://helpdesk.acmecorp.internal

### Slack
**Windows/macOS:** Download from https://software.acmecorp.internal/slack
- Enterprise Grid account — sign in with your corporate SSO (not a personal Slack account)
- Your workspace: acmecorp.slack.com

**If Slack crashes on startup (macOS):**
```bash
rm -rf ~/Library/Application\ Support/Slack/Cache
rm -rf ~/Library/Caches/com.tinyspeck.slackmacgap
```
Restart Slack after clearing cache.

### Zoom
**Installation:** https://software.acmecorp.internal/zoom
- Sign in with "SSO" option → company domain: acmecorp
- Background blur is pre-enabled by policy
- Recording to local disk is disabled; cloud recording requires manager approval

**Zoom audio issues:**
- System Preferences → Sound → Input → select the correct microphone
- In Zoom: Settings → Audio → Test Speaker and Microphone
- Background noise cancellation: Settings → Audio → Suppress background noise → Auto

### Visual Studio Code
**Installation:** https://software.acmecorp.internal/vscode
- IT-managed extensions are pre-installed (ESLint, Prettier, GitLens)
- Settings sync is enabled via corporate GitHub account
- Copilot is licensed for all engineering roles

**Remote SSH extension:**
Install `ms-vscode-remote.remote-ssh` to connect to dev servers.
Add to `~/.ssh/config`:
```
Host devbox
  HostName devbox.acmecorp.internal
  User firstname.lastname
  IdentityFile ~/.ssh/id_ed25519
```

### Accessing Microsoft 365
- Web: https://office.acmecorp.internal (redirects to M365)
- Desktop apps: Download via Microsoft 365 portal (up to 5 personal devices)
- Sign in with your corporate email — SSO is enabled

---

## Hardware Requests

### Requesting New Equipment
Standard equipment requests are fulfilled within **5 business days**.
Priority requests (broken equipment, new hires) within **24 hours**.

**Standard equipment available:**
- Laptops: MacBook Pro 14" M4, Dell XPS 13, ThinkPad X1 Carbon
- Monitors: LG 27" 4K USB-C, Dell 24" IPS
- Peripherals: Logitech MX Keys, MX Master 3, Jabra Evolve2 85
- Phones: iPhone 16 Pro (exec/sales), iPhone 15 (standard roles)

**Request process:**
1. Submit request: https://helpdesk.acmecorp.internal → Hardware Request
2. Manager approval required for items over ₹50,000
3. Finance approval required for items over ₹1,00,000
4. Receive confirmation email with estimated delivery date
5. Collect from IT Hub (Chennai: Floor 3, Desk 34) or receive courier

**Laptop refresh cycle:** Laptops are replaced every 3 years. IT will contact you proactively.

### Reporting Damaged Equipment
- Report immediately to avoid data loss liability
- IT Hub: Floor 3, Desk 34 (walk-in, no appointment needed)
- Loaner devices available same-day while repairs are assessed
- Accidental damage: covered by company policy (1 incident per year)
- Intentional damage: employee is liable

---

## Network & Connectivity

### Office Wi-Fi
- **ACME-CORP** (2.4 GHz/5 GHz) — corporate devices, auto-joins with SSO
- **ACME-GUEST** (5 GHz) — visitors and personal devices, no VPN required
- **ACME-IoT** — conference room devices only, managed by IT

**If Wi-Fi is slow in the office:**
1. Forget ACME-CORP and rejoin (flushes cached credentials)
2. Try 5 GHz band (faster, shorter range) vs 2.4 GHz (slower, longer range)
3. Check https://status.acmecorp.internal for known network issues
4. Contact IT if speeds below 50 Mbps on a wired connection

### Wired Ethernet
Ethernet ports in all desks — use the provided USB-C to Ethernet adapter.
IP addresses are assigned via DHCP automatically.

**Static IP requests:** Required for servers and IoT devices. Submit ticket with MAC address.

---

## Common Errors & Fixes

### "Your account has been disabled"
This occurs when: account has been inactive 90 days, suspicious login detected, or HR-initiated suspension. Contact HR or IT immediately — do not attempt to reset password.

### "Access denied to SharePoint"
- Verify you are connected to VPN or are in the office
- Ensure you are signed into the correct account (firstname.lastname@acmecorp.com, not personal)
- Request access via the document owner or submit a helpdesk ticket

### "Outlook keeps asking for password"
1. Open Keychain Access (macOS) → search "acmecorp" → delete all entries
2. Sign out of Outlook → restart Outlook → sign back in
3. If persists: System Preferences → Internet Accounts → remove and re-add Exchange

### "Printer not found" or "Printer offline"
1. Verify you are on ACME-CORP Wi-Fi (printers are not accessible on ACME-GUEST)
2. Re-add printer: System Preferences → Printers → Add Printer → search for printer name
3. Chennai office printers: PRNT-CHN-01 (Floor 2), PRNT-CHN-02 (Floor 3)
4. Print jobs held > 30 minutes are automatically deleted

---

## IT Support Contacts

| Channel | Contact | Hours | Response SLA |
|---------|---------|-------|-------------|
| Slack | #it-helpdesk | 24/7 (bot), 8am–8pm (human) | Urgent: 1h, Normal: 4h |
| Portal | helpdesk.acmecorp.internal | 24/7 | Urgent: 2h, Normal: 8h |
| Phone | Ext. 4357 | 8am–8pm Mon–Fri | Immediate |
| Walk-in | IT Hub, Floor 3, Desk 34 | 9am–6pm Mon–Fri | Immediate |
| Email | it@acmecorp.internal | 24/7 | Next business day |

**Priority levels:**
- **P1 Critical:** Production systems down, security breach → Response in 30 min
- **P2 High:** Can't work, data loss risk → Response in 2 hours
- **P3 Normal:** Degraded function, workaround exists → Response in 8 hours
- **P4 Low:** Enhancement, non-urgent question → Response in 2 business days
