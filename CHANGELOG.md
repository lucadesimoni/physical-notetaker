# Changelog

## 1.1.0 (2026-11-04)

First release. Turns the original prototype into a device anyone can use:
press a button, talk, get the memo by email.

### Downloads

- **Windows:** `notetaker-windows-v1.1.0.zip`. Unzip, double-click
  **Notetaker starten.bat**, paste your Mistral API key. Python and all
  packages are installed automatically.
- **Raspberry Pi:** `notetaker-raspberry-pi-v1.1.0.tar.gz`. Unpack, run
  `sudo ./install.sh`, open `http://notetaker.local` on your phone.
- **Python package:** `voxtral_notetaker-1.1.0-py3-none-any.whl` for developers.

### New

- **Transcription with Mistral Voxtral**: Voxtral Small Transcribe 3 for the
  final transcript with speaker labels, Voxtral Mini Transcribe 3 for quick
  and live checks.
- **Swiss German**: default meeting language, dialect clean-up to Standard
  German (Mistral Small 4), commands and dates in dialect ("Mach es Notiz",
  "bis am Friitig"), vocabulary hints for names and terms.
- **Meeting memo**: notes, open questions and tasks with owner and due date,
  AI summary, sent by email and shown on the web page.
- **Voice commands**: "Mach eine Notiz", "Erstell einen Task", "Recherchiere",
  confirmed out loud during the meeting; "Beende die Aufnahme" stops.
- **Speaker names** from introductions ("Ich bin Anna", "I bi d'Sabine");
  correct names afterwards and remake the memo without transcribing again.
- **Always-on device**: one button to start/stop, spoken announcements (also
  tells everyone the meeting is recorded), status light, autostart on boot.
- **Never lose a meeting**: recording is saved to disk continuously and
  recovered after a power cut; memos are created when the internet is back.
- **Web page for phones**: start/stop, meetings with downloads, settings
  behind a PIN, printable sticker with QR code, setup hotspot without Wi-Fi.
- **Storage care**: old audio of finished meetings is deleted, memos stay.
- **Windows**: one double-click, only the API key to enter, Windows voice,
  warning when Windows blocks the microphone.
- **German and English** web page and announcements.
- **Tested automatically** on Windows and Linux ARM (Raspberry Pi) on every change.

### License

PolyForm Noncommercial 1.0.0: free for non-commercial use. Owner:
Outthinkx by Luca De Simoni.
