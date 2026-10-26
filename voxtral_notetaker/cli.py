"""
Lean CLI for Voxtral Notetaker
"""

import os
import re
import time
from datetime import datetime

import click

from rich.console import Console

from .config import NotetakerConfig, Language, StorageProvider, load_config
from .core import Notetaker


console = Console()


@click.group()
def cli():
    """Voxtral Notetaker - Lean conference transcription system"""
    pass


@cli.command()
@click.option('--output', '-o', default=None, help='Output file path')
@click.option('--device', '-d', type=int, default=None, help='Audio device index')
@click.option('--language', '-l', type=click.Choice(['en', 'de', 'de-CH', 'auto']), 
              default='auto', help='Language for transcription')
@click.option('--no-diarization', is_flag=True, help='Disable speaker diarization')
@click.option('--no-upload', is_flag=True, help='Disable cloud upload')
def record(output: str, device: int, language: str, no_diarization: bool, no_upload: bool):
    """Start recording and transcribe meeting"""
    config = load_config()
    
    if device is not None:
        config.audio.device_index = device
    
    if no_upload:
        config.storage.auto_upload = False
    
    notetaker = Notetaker(config)
    
    try:
        console.log("Starting recording... (Ctrl+C to stop)")
        
        if not notetaker.start_recording(output):
            console.log("Failed to start recording", style="red")
            return
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            console.log("\nStopping and transcribing...")
            
            lang = Language(language) if language != 'auto' else Language.AUTO
            
            result = notetaker.stop_and_transcribe(lang, diarize=not no_diarization)
            
            console.log("\n[bold green]Meeting Result:[/bold green]")
            console.log(f"File: {result.audio_file}")
            console.log(f"Duration: {result.duration:.1f}s")
            console.log(f"Language: {result.language}")
            if result.confidence is not None:
                console.log(f"Confidence: {result.confidence*100:.1f}%")
            console.log(f"Speakers: {', '.join(result.speakers) if result.speakers else 'None'}")
            console.log(f"\n[bold]Transcript:[/bold]\n{result.transcript}")
            
            if result.memo:
                console.print(f"\n{result.memo.to_markdown()}")
                console.log(f"Memo saved: {result.memo_file}")
            
            if result.storage_results:
                console.log("\n[bold]Uploaded:[/bold]")
                for r in result.storage_results:
                    if r.success:
                        console.log(f"  [green]✓ {r.provider}: {r.url or r.file_path}[/green]")
                    else:
                        console.log(f"  [red]✗ {r.provider}: {r.error}[/red]")
            
    except Exception as e:
        console.log(f"Error: {e}", style="red")
    finally:
        notetaker.close()


@cli.command()
@click.argument('file')
@click.option('--language', '-l', type=click.Choice(['en', 'de', 'de-CH', 'auto']), 
              default='auto', help='Language for transcription')
@click.option('--no-diarization', is_flag=True, help='Disable speaker diarization')
@click.option('--fast', is_flag=True, help='Use the fast, cheaper model (voxtral.fast_model)')
def transcribe(file: str, language: str, no_diarization: bool, fast: bool):
    """Transcribe an existing audio file"""
    if not os.path.exists(file):
        console.log(f"File not found: {file}", style="red")
        return
    
    config = load_config()
    notetaker = Notetaker(config)
    
    try:
        lang = Language(language) if language != 'auto' else Language.AUTO
        diarize = not no_diarization and config.diarization.enabled
        result = notetaker.transcribe(file, lang, diarize=notetaker._use_api_diarization(diarize),
                                      fast=fast)
        
        console.log("[bold green]Transcription:[/bold green]")
        console.log(f"Language: {result.language}")
        if result.confidence is not None:
            console.log(f"Confidence: {result.confidence*100:.1f}%")
        console.log(f"Duration: {result.duration:.1f}s")
        
        segments = notetaker._speaker_segments(file, result, diarize)
        if segments:
            console.log(f"Found {len(set(s['speaker_id'] for s in segments))} speakers\n")
            console.print(notetaker._format_transcript_with_speakers(result.text, segments))
        else:
            if diarize:
                console.log("No speakers detected")
            console.print(f"\n{result.text}")
        
    except Exception as e:
        console.log(f"Error: {e}", style="red")
    finally:
        notetaker.close()


@cli.command()
@click.argument('file')
@click.option('--language', '-l', type=click.Choice(['en', 'de', 'de-CH', 'auto']),
              default='auto', help='Meeting language')
@click.option('--title', '-t', default=None, help='Memo title')
@click.option('--date', 'meeting_date', default=None,
              help='Meeting date (YYYY-MM-DD), used to resolve due dates')
@click.option('--output', '-o', default=None, help='Output file (default: <file>_memo.md)')
@click.option('--no-summary', is_flag=True, help='Skip the AI summary')
def memo(file: str, language: str, title: str, meeting_date: str, output: str, no_summary: bool):
    """Create a meeting memo from a transcript file"""
    if not os.path.exists(file):
        console.log(f"File not found: {file}", style="red")
        return
    
    try:
        date = datetime.strptime(meeting_date, '%Y-%m-%d') if meeting_date else datetime.now()
    except ValueError:
        console.log("Invalid --date, expected YYYY-MM-DD", style="red")
        return
    
    with open(file, encoding='utf-8') as f:
        transcript = f.read()
    
    if language == 'auto':
        language = 'de-CH' if notetaker_language_is_german(transcript) else 'en'
    
    # Speakers from "[Name] ..." labels, in order of appearance
    participants = list(dict.fromkeys(re.findall(r'^\s*\[([^\]]+)\]', transcript, re.MULTILINE)))
    
    notetaker = Notetaker(load_config())
    try:
        for name in participants:
            notetaker.set_speaker_name(name, name)
        notetaker.extract_commands(transcript, language, date)
        result = notetaker.build_memo(
            transcript=transcript, language=language, title=title,
            participants=participants, date=date, summarize=not no_summary,
        )
        
        output = output or f"{os.path.splitext(file)[0]}_memo.md"
        with open(output, 'w', encoding='utf-8') as f:
            f.write(result.to_markdown())
        
        console.print(result.to_markdown())
        console.log(f"Memo saved: {output}")
        if not no_summary and not notetaker.summarizer.available:
            console.log("No AI summary: set MISTRAL_API_KEY or voxtral.api_key in config.yaml")
    finally:
        notetaker.close()


def notetaker_language_is_german(text: str) -> bool:
    from .commands import CommandParser
    return CommandParser()._detect_language(text).startswith('de')


@cli.command()
@click.option('--config', 'config_path', default=None, help='Config file (default: config.yaml)')
@click.option('--no-web', is_flag=True, help='Do not start the setup/status web page')
@click.option('-v', '--verbose', is_flag=True, help='Debug logging')
def run(config_path: str, no_web: bool, verbose: bool):
    """Run the always-on notetaker (button start/stop, queue, web page)"""
    import logging
    from .service import NotetakerService
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    service = NotetakerService(config_path=config_path)
    if not no_web and service.config.web.enabled:
        console.log(f"Web page: http://<this-device>:{service.config.web.port}")
    service.run_forever(web=not no_web)


@cli.command()
@click.argument('file')
@click.option('--language', '-l', type=click.Choice(['en', 'de', 'de-CH', 'auto']),
              default=None, help='Meeting language (default: service.language)')
@click.option('--title', '-t', default=None, help='Memo title')
@click.option('--speaker', 'speakers', multiple=True, metavar='ID=NAME',
              help='Name a speaker, e.g. --speaker speaker_0=Anna (repeatable)')
@click.option('--no-upload', is_flag=True, help='Do not upload the results')
@click.option('--fresh', is_flag=True,
              help='Transcribe again instead of reusing the saved transcription')
def process(file: str, language: str, title: str, speakers, no_upload: bool, fresh: bool):
    """Create transcript and memo for an existing recording"""
    if not os.path.exists(file):
        console.log(f"File not found: {file}", style="red")
        raise SystemExit(1)
    config = load_config()
    lang = Language(language or config.service.language or 'auto')
    notetaker = Notetaker(config)
    try:
        for entry in speakers:
            speaker_id, _, name = entry.partition('=')
            if speaker_id and name:
                notetaker.set_speaker_name(speaker_id.strip(), name.strip())
        result = notetaker.process_recording(file, language=lang, title=title,
                                             upload=False if no_upload else None,
                                             use_cache=not fresh)
        console.print(result.memo.to_markdown())
        console.log(f"Memo saved: {result.memo_file}")
        console.log(f"Transcript saved: {result.transcript_file}")
    except Exception as e:
        console.log(f"Error: {e}", style="red")
        raise SystemExit(1)
    finally:
        notetaker.close()


@cli.command()
def queue():
    """Show recordings and their processing status"""
    from .jobs import JobStore
    config = load_config()
    jobs = JobStore(config.service.recordings_dir).all()
    if not jobs:
        console.log("No recordings yet")
        return
    for job in jobs:
        line = f"{job.id}  {job.status:<10} {job.title or ''}"
        if job.last_error and job.status != 'done':
            line += f"  ({job.last_error})"
        console.print(line)


@cli.command()
@click.argument('job_id', required=False)
def retry(job_id: str):
    """Queue failed recordings again (all, or one by id)"""
    from .jobs import JobStore
    config = load_config()
    count = JobStore(config.service.recordings_dir).retry(job_id)
    console.log(f"{count} recording(s) queued again. The running service picks them up.")


@cli.command()
def devices():
    """List available audio input devices"""
    config = NotetakerConfig()
    notetaker = Notetaker(config)
    
    devices = notetaker.get_available_devices()
    
    if not devices:
        console.log("No audio input devices found", style="red")
        notetaker.close()
        return
    
    console.log("Available audio input devices:")
    for i, dev in enumerate(devices):
        marker = " [Jabra]" if 'jabra' in dev['name'].lower() else ""
        console.log(f"  {dev['index']}: {dev['name']}{marker}")
    
    notetaker.close()


@cli.command()
def setup():
    """Create default configuration"""
    config = NotetakerConfig()
    config.save('config.yaml')
    console.log("Created config.yaml")
    console.log("\nSet your Mistral API key and storage settings.")
    console.log("\nQuick start:")
    console.log("  1. Create an API key in Mistral AI Studio (https://console.mistral.ai)")
    console.log("  2. export MISTRAL_API_KEY=... (or set voxtral.api_key in config.yaml)")
    console.log("  3. Run: python -m voxtral_notetaker record")


@cli.command()
@click.option('--provider', type=click.Choice(['local', 'google_drive', 'dropbox', 's3', 'all']), 
              default=None, help='Storage provider')
@click.option('--file', default=None, help='File to upload')
def upload(provider: str, file: str):
    """Upload file to cloud storage"""
    config = load_config()
    
    if provider:
        config.storage.provider = StorageProvider(provider)
    
    if not file:
        console.log("Please specify a file to upload", style="red")
        return
    
    if not os.path.exists(file):
        console.log(f"File not found: {file}", style="red")
        return
    
    notetaker = Notetaker(config)
    
    try:
        results = notetaker.storage.upload(file)
        
        for r in results:
            if r.success:
                console.log(f"[green]✓ {r.provider}: {r.url or r.file_path}[/green]")
            else:
                console.log(f"[red]✗ {r.provider}: {r.error}[/red]")
    except Exception as e:
        console.log(f"Error: {e}", style="red")
    finally:
        notetaker.close()


if __name__ == '__main__':
    cli()
