# Helpdesk platforms: annotation guidelines (v1)

These tickets already have their problem area, APPS or STORAGE (shown at the bottom of the card). For these two areas the technician depends on the system the problem is on, so pick **the one system the problem is on**.

## The main rule

Pick the system from **what the ticket shows**: a system it names (Windows 11, Ubuntu, macOS), or an unmistakable sign of one, such as a `C:\` path, PowerShell or cmd for Windows, and `apt`, `sudo` or a `/home` path for Linux. Don't guess from the app alone: Excel, Word, Chrome or git don't name a system. If nothing shows the system, choose **UNSTATED**.

Pick the system **the problem is on**, not every system the ticket mentions. A user who moved from Windows 10 to Linux and has a problem on Linux is LINUX. Choose **SEVERAL** only when the problem happens on more than one system, or you can't tell which one it is on.

Don't think about which technician will get the ticket: the routing table does that from the area and the system.

## Systems

Hover a label to see its full definition, what not to mark and examples.

- **WINDOWS**: a Windows desktop or laptop.
- **WINDOWS_SERVER**: Windows Server.
- **LINUX**: Linux or another Unix system, including WSL and Linux VMs.
- **MAC_MOBILE**: a Mac, iPhone, iPad or Android device.
- **SEVERAL**: more than one system, or several named and you can't tell which.
- **UNSTATED**: nothing in the ticket shows the system.

Flag a ticket if you're unsure. If the area itself looks wrong, flag it too, and still pick the system: the areas are locked, and flagged tickets are looked at separately.
