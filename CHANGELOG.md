# Changelog

## 1.3.0 (2026-11-11)

Much better Swiss German dialect, Swiss place names and names from past
meetings help the transcription.

### Downloads

- **Windows:** `Notetaker-Setup-1.3.0.exe` (installer, recommended) or
  `notetaker-windows-v1.3.0.zip`.
- **Raspberry Pi:** `notetaker-raspberry-pi-v1.3.0.tar.gz`. Unpack, run
  `sudo ./install.sh`.
- **Python package:** `voxtral_notetaker-1.3.0-py3-none-any.whl`.

### New

- **Better dialect clean-up:** Mistral Medium 3.5 rewrites lines that are
  still in dialect ("Am Wochenend lafe ech duerch" → "Am Wochenende laufe ich
  durch"). Lines already in Standard German stay exactly as recognised.
  Measured on Swiss German sentences from 8 cantons: word error rate
  53 % → 41 %; formal speech unchanged (14 %).
- **Swiss place names help:** misheard places ("Meltigen", "Genpe") get the
  most similar official names (about 4,400) as hints, so the clean-up writes
  Meltingen or Gempen where that clearly fits, and never guesses another
  place. Correct place names: 13 % → 27 % on the dialect sentences.
- **Dialect words:** 2,700 Swiss German words from the Swiss German
  Wikipedia (CC BY-SA 4.0) help find dialect lines.
- **Names from past meetings:** corrected speaker names, names from
  introductions and task owners are used as hints for the transcription.
- **No passages in English by mistake:** in German meetings, segments that
  came out in English are transcribed again in German.
- **Swiss Standard German:** "ss" instead of "ß", quotes «so», Swiss words
  kept (since 1.2.0, now also in the clean-up and summary prompts).
- New settings: `voxtral.dialect_model`, `voxtral.place_hints`,
  `voxtral.learn_vocabulary`, `voxtral.fix_language_flips`.

### Fixed

- The clean-up with Mistral Large 4 failed on every call (it needs top_p 1),
  and answers of reasoning models were not read.
- Benchmark: options for the reference column, per-dialect results and
  correctly recognised names.

## 1.2.0 (2026-11-10)

Windows installer, much better results with quiet microphones, Swiss
Standard German, and log files for troubleshooting.

### Downloads

- **Windows (new, recommended):** `Notetaker-Setup-1.2.0.exe`. Double-click,
  follow the installer, paste your Mistral API key. Start menu and desktop
  shortcuts, uninstall via Windows settings (your settings and recordings
  are kept). Windows may still show "Unknown publisher" until the installer
  is code-signed.
- **Windows (ZIP):** `notetaker-windows-v1.2.0.zip`, as before.
- **Raspberry Pi:** `notetaker-raspberry-pi-v1.2.0.tar.gz`. Unpack, run
  `sudo ./install.sh`.
- **Python package:** `voxtral_notetaker-1.2.0-py3-none-any.whl`.

### New

- **Windows installer** with icon and publisher name; per user, no admin
  rights needed.
- **Swiss Standard German:** for Swiss meetings (de-CH, the default) the
  transcript, memo and emails are written the Swiss way: "ss" instead of
  "ß" ("Massnahme", "gross"), quotes «so»; Swiss words such as Traktandum,
  Pendenz or Velo are kept.
- **Quiet microphones:** recordings are raised to a good level before
  transcription (a recording that was recognised badly was 30 dB too quiet);
  the device warns after 30 seconds when the microphone is very quiet.
- **Transcribe again:** a button on each meeting page redoes the
  transcription from the audio.
- **Log file for troubleshooting:** `logs/notetaker.log` with details of
  every step, never with passwords, keys or meeting content; download it
  under Einstellungen → Fehlersuche.
- **Cleaner window:** a short start banner and status lines only.
- **Benchmark:** `scripts/benchmark_swiss_german.py` measures Swiss German
  accuracy on recordings with an official Standard German text, and can
  compare with other systems (e.g. Plaud) on your own recordings.

### Fixed

- **Dialect clean-up lost text:** with long lines only the first part was
  kept. It also reworded correct Standard German. It now keeps every line
  whole and only touches lines with dialect words (measured on 40 official
  Swiss German samples: word error rate 21 % → 14 %).
- The device's own announcements ("Aufnahme gestartet ...") no longer
  appear in the transcript.
- Noise reduction is off by default; it made recognition worse.
- No more technical setuptools messages when starting on Windows.

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
