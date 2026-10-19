# Setup

Enter the WattBox's **local** SSH credentials under this app's Configuration.
Set `wattbox_host`, `ssh_port` (normally 22), `test_outlet`,
`expected_outlet_label` (exact label from WattBox), and `device_alias`.

Start the app and choose **Open Web UI**. Inspect and approve its SSH identity,
then read the labels and status. The app sends no device requests at startup.

To run a reboot test, enable `allow_reboot`, save and restart this app only.
Read status, confirm the device/outlet mapping, and select the reboot button.
An off outlet, different label, unexpected model, expired confirmation, or active
cooldown blocks the action. RESET only is supported; no global reset or manual
off/on action is exposed. Five minutes must pass between reset attempts.

The saved SSH identity cannot be silently replaced. If it changes, investigate
the device identity before resetting app data. If the reboot acknowledgement
times out, its outcome is unknown and the command will not be resent.

Use Refresh results to see the outlet verification after 15, 30, and 60 seconds.
Check the TV itself to confirm the Apple TV is operating normally. Outlet status
does not establish device reachability, successful boot, HDMI output or playback.

This version has no phone voice connection, cloud access, or other integrations.
No Home Assistant configuration, automations or existing integrations are edited.
All credentials stay in app configuration; include them only in protected backups.

If the first check fails, verify local credentials, SSH availability, and the
saved identity. WattBox SSH implementations/firmware can vary; do not weaken
SSH or enable Telnet to work around a failure before reviewing it.
