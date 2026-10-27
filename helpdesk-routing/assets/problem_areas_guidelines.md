# Helpdesk problem areas: annotation guidelines (v1.1)

Pick the **one problem area** of each IT support ticket. The area is used to route the ticket to a technician and to count recurring problems each month.

## The main rule

Choose the area of **the main problem the user needs fixed, not where they noticed it**. A disk that won't mount on Windows is STORAGE. A printer that won't join the Wi-Fi is NETWORK. A router problem the user noticed on their phone is NETWORK.

Pick the area from what the problem is. Don't think about which technician will get it: the routing is worked out separately, from the area and the system the ticket names.

## Areas

Hover a label to see its full definition, what not to mark and examples.

- **WINDOWS**: The Windows desktop operating system itself: installing, booting, updates, settings, drivers, the taskbar and Explorer, built-in tools such as winget, signing in to Windows (including BitLocker recovery), and Windows scripting (PowerShell, cmd, batch files). Not Windows Server (LINUX_AND_SERVERS), not choosing a boot device in the BIOS or boot menu (HARDWARE), not an app that misbehaves on Windows (APPS), not network settings or network commands on Windows (NETWORK), not a disk problem that happens to be on Windows (STORAGE).
- **APPS**: Applications and tools on any system: Office and Outlook, LibreOffice, browsers, email clients, media and file tools such as FFmpeg, yt-dlp, Pandoc, PDF and image editors, command-line and developer tools such as git, rsync, gpg and regular expressions, and hosted services used through an app or website, such as Microsoft 365 mail rules or an S3 bucket. Includes signing in to an app or online service, and an app running inside a virtual machine or Windows Sandbox. Not an app on a Mac, iPhone, iPad or Android device (OTHER), and not a service the organisation runs on its own server (LINUX_AND_SERVERS).
- **HARDWARE**: Physical devices and components: PCs and laptops, peripherals, printers, displays, power, batteries and UPS, BIOS and firmware, the boot menu and boot order (booting from USB or another drive), and drives that are dead, clicking or not detected at all. Not I/O errors or SMART warnings on a drive that still shows up (STORAGE).
- **LINUX_AND_SERVERS**: Linux and Unix systems (desktops and servers), including signing in and permissions on them, Windows Server, services the organisation runs on its own servers, and virtual machines and containers themselves. Not an app or command-line tool on Linux (APPS), not an app inside a VM (APPS).
- **NETWORK**: Wi-Fi, LAN and Ethernet, DNS, routers and switches, VPN, firewalls, proxies and remote access, on any device, when the network connection is the thing to fix. Includes network settings and network commands on any system (Wi-Fi profiles, proxy settings, netsh, ping) and signing in to network devices. Not a self-hosted VPN or web server that is down on the server itself (LINUX_AND_SERVERS).
- **STORAGE**: Disks, partitions, file systems, RAID, backup and data recovery on a drive that still shows up, even when it reports I/O errors or SMART warnings, on any system. Not how a tool such as rsync behaves (APPS).
- **OTHER**: The thing to fix is a Mac, iPhone, iPad or Android device, or an app on one, or the problem fits none of the areas above.

## Sign-in and password problems

There is no separate area for accounts. A sign-in, password, MFA or permissions problem belongs to the area of **what the user signs in to**: Windows → WINDOWS, an app or online service (Microsoft 365, Gmail) → APPS, a Linux machine or server → LINUX_AND_SERVERS, a router or switch → NETWORK, a Mac or phone → OTHER.

## When you're unsure

**Flag the ticket** (flag icon) whenever you hesitated between two areas or no area fits well, then pick your best answer and submit. Flagged tickets show where the definitions still need work.
