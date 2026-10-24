"""
Lean CLI for Voxtral Notetaker
"""

import os
import sys
import time
import argparse
import click

from rich.console import Console

from .config import NotetakerConfig, Language, StorageProvider
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
    config = NotetakerConfig.load() if os.path.exists('config.yaml') else NotetakerConfig()
    
    if device is not None:
        config.audio.device_index = device
    
    if no_upload:
        config.storage.auto_upload = False
    
    notetaker = Notetaker(config)
    
    if device is not None:
        notetaker.set_device(device)
    
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
            
            if no_diarization:
                # Just transcribe without diarization
                recording = notetaker.stop_recording()
                if recording:
                    result = notetaker.transcribe(recording.file_path, lang)
                    console.log(f"\n[bold green]Transcript:[/bold green]\n{result.text}")
            else:
                result = notetaker.stop_and_transcribe(lang)
                
                console.log(f"\n[bold green]Meeting Result:[/bold green]")
                console.log(f"File: {result.audio_file}")
                console.log(f"Duration: {result.duration:.1f}s")
                console.log(f"Language: {result.language}")
                console.log(f"Confidence: {result.confidence*100:.1f}%")
                console.log(f"Speakers: {', '.join(result.speakers) if result.speakers else 'None'}")
                console.log(f"\n[bold]Transcript:[/bold]\n{result.transcript}")
                
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
def transcribe(file: str, language: str, no_diarization: bool):
    """Transcribe an existing audio file"""
    if not os.path.exists(file):
        console.log(f"File not found: {file}", style="red")
        return
    
    config = NotetakerConfig.load() if os.path.exists('config.yaml') else NotetakerConfig()
    notetaker = Notetaker(config)
    
    try:
        lang = Language(language) if language != 'auto' else Language.AUTO
        result = notetaker.transcribe(file, lang)
        
        console.log(f"[bold green]Transcription:[/bold green]")
        console.log(f"Language: {result.language}")
        console.log(f"Confidence: {result.confidence*100:.1f}%")
        console.log(f"Duration: {result.duration:.1f}s")
        console.log(f"\n{result.text}")
        
        if not no_diarization:
            console.log("\n[bold]Diarizing...[/bold]")
            segments = notetaker.diarizer.diarize(file)
            
            if segments:
                console.log(f"Found {len(set(s.speaker_id for s in segments))} speakers")
                for seg in segments[:10]:
                    console.log(f"  [{seg.speaker_id}] {seg.start:.1f}s - {seg.end:.1f}s")
            else:
                console.log("No speakers detected")
        
    except Exception as e:
        console.log(f"Error: {e}", style="red")
    finally:
        notetaker.close()


@cli.command()
def devices():
    """List available audio input devices"""
    config = NotetakerConfig()
    notetaker = Notetaker(config)
    
    devices = notetaker.get_available_devices()
    
    if not devices:
        console.log("No audio input devices found", style="red")
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
    console.log("\nEdit the file to add your Voxtral API key and storage settings.")
    console.log("\nQuick start:")
    console.log("  1. Get Voxtral API key from https://voxtral.com")
    console.log("  2. Edit config.yaml and set voxtral.api_key")
    console.log("  3. Run: python -m voxtral_notetaker record")


@cli.command()
@click.option('--provider', type=click.Choice(['local', 'google_drive', 'dropbox', 's3']), 
              default=None, help='Storage provider')
@click.option('--file', default=None, help='File to upload')
def upload(provider: str, file: str):
    """Upload file to cloud storage"""
    config = NotetakerConfig.load() if os.path.exists('config.yaml') else NotetakerConfig()
    
    if provider:
        config.storage.provider = StorageProvider(provider)
    
    notetaker = Notetaker(config)
    
    if not file:
        console.log("Please specify a file to upload", style="red")
        return
    
    if not os.path.exists(file):
        console.log(f"File not found: {file}", style="red")
        return
    
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
