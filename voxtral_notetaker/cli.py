"""
Command Line Interface for Voxtral Notetaker
"""

import os
import sys
import time
import argparse
import asyncio
from typing import Optional, List
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from .config import NotetakerConfig, Language, StorageProvider, AudioFormat
from .core import Notetaker, MeetingResult
from .audio import AudioRecorder
from .transcription import TranscriptionResult


console = Console()


@click.group()
@click.version_option(version="1.0.0", message="Voxtral Notetaker v%(version)")
def cli():
    """Voxtral Notetaker - Raspberry Pi based meeting notes system"""
    pass


@cli.command()
@click.option('--output', '-o', type=str, default=None, help='Output audio file path')
@click.option('--format', '-f', type=click.Choice([f.value for f in AudioFormat]), 
              default='wav', help='Audio format')
@click.option('--device', '-d', type=int, default=None, help='Audio device index')
@click.option('--duration', type=float, default=None, help='Recording duration in seconds')
@click.option('--live', is_flag=True, help='Show live transcription')
@click.option('--debug', is_flag=True, help='Enable debug logging')
def record(output: Optional[str], format: str, device: Optional[int], 
          duration: Optional[float], live: bool, debug: bool):
    """Start audio recording"""
    
    if debug:
        console.log("Debug mode enabled")
    
    # Load configuration
    config = NotetakerConfig.load() if os.path.exists('config.yaml') else NotetakerConfig()
    
    # Override from command line
    if format:
        config.audio.format = AudioFormat(format)
    if device is not None:
        config.audio.device_index = device
    
    # Create notetaker
    notetaker = Notetaker(config)
    
    # Set device if specified
    if device is not None:
        notetaker.set_audio_device(device)
    
    # Determine output file
    if not output:
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        output = f"recording_{timestamp}.{config.audio.format.value}"
    
    console.log(f"Starting recording to: {output}")
    
    if live:
        console.log("Live transcription enabled (Ctrl+C to stop)")
    
    try:
        # Start recording
        success = notetaker.start_recording(output)
        if not success:
            console.log("Failed to start recording", style="red")
            return
        
        console.log("Recording... (Press Ctrl+C to stop)", style="green")
        
        # If duration specified, sleep and stop
        if duration:
            console.log(f"Will stop after {duration} seconds")
            time.sleep(duration)
            result = notetaker.stop_and_transcribe()
            _display_result(result)
        else:
            # Wait for Ctrl+C
            try:
                if live:
                    # Show live transcription
                    async def show_live():
                        async for text in notetaker.transcribe_live():
                            console.print(f"\n[bold blue]Live Transcript:[/bold blue]\n{text}\n")
                    
                    asyncio.run(show_live())
                else:
                    # Just wait
                    while True:
                        time.sleep(1)
            except KeyboardInterrupt:
                console.log("\nStopping recording...")
                result = notetaker.stop_and_transcribe()
                _display_result(result)
                
    except KeyboardInterrupt:
        console.log("\nStopping recording...")
        result = notetaker.stop_and_transcribe()
        _display_result(result)
    except Exception as e:
        console.log(f"Error: {e}", style="red")
    finally:
        notetaker.close()


@cli.command()
@click.argument('file', type=str)
@click.option('--output', '-o', type=str, default=None, help='Output text file')
@click.option('--language', '-l', type=click.Choice([l.value for l in Language]), 
              default='auto', help='Language for transcription')
@click.option('--email', is_flag=True, help='Send transcript via email')
@click.option('--upload', is_flag=True, help='Upload to cloud storage')
@click.option('--debug', is_flag=True, help='Enable debug logging')
def transcribe(file: str, output: Optional[str], language: str, 
             email: bool, upload: bool, debug: bool):
    """Transcribe an audio file"""
    
    if not os.path.exists(file):
        console.log(f"File not found: {file}", style="red")
        return
    
    console.log(f"Transcribing: {file}")
    
    # Load configuration
    config = NotetakerConfig.load() if os.path.exists('config.yaml') else NotetakerConfig()
    
    # Create notetaker
    notetaker = Notetaker(config)
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Transcribing...", total=None)
            
            # Transcribe
            result = notetaker.transcribe(file, Language(language))
            
            progress.remove_task(task)
        
        # Display result
        console.log(f"\n[bold green]Transcription Complete[/bold green]")
        console.log(f"Language: {result.language}")
        console.log(f"Confidence: {result.confidence * 100:.1f}%")
        console.log(f"Duration: {result.duration:.1f} seconds")
        console.log(f"\nText:\n{result.text}")
        
        # Save to file
        if output:
            with open(output, 'w', encoding='utf-8') as f:
                f.write(result.text)
            console.log(f"Saved to: {output}")
        
        # Upload to cloud
        if upload:
            upload_results = notetaker.upload_to_cloud(file)
            for result in upload_results:
                if result.success:
                    console.log(f"Uploaded to {result.provider}: {result.url or result.file_path}")
                else:
                    console.log(f"Upload failed to {result.provider}: {result.error}", style="red")
        
        # Send email
        if email:
            email_result = notetaker.send_email(
                f"Transcription: {os.path.basename(file)}",
                result
            )
            if email_result.success:
                console.log(f"Email sent to {len(email_result.recipients)} recipients")
            else:
                console.log(f"Email failed: {email_result.error}", style="red")
                
    except Exception as e:
        console.log(f"Error: {e}", style="red")
    finally:
        notetaker.close()


@cli.command()
@click.option('--language', '-l', type=click.Choice([l.value for l in Language]), 
              default='auto', help='Language for transcription')
@click.option('--output-dir', '-o', type=str, default='./transcripts', 
              help='Output directory for transcripts')
@click.option('--pattern', '-p', type=str, default='*.wav', 
              help='File pattern to match')
@click.option('--email', is_flag=True, help='Send transcripts via email')
@click.option('--upload', is_flag=True, help='Upload to cloud storage')
@click.option('--debug', is_flag=True, help='Enable debug logging')
def batch(language: str, output_dir: str, pattern: str, 
        email: bool, upload: bool, debug: bool):
    """Batch transcribe multiple audio files"""
    
    # Find files matching pattern
    files = list(Path('.').glob(pattern))
    
    if not files:
        console.log(f"No files found matching: {pattern}", style="red")
        return
    
    console.log(f"Found {len(files)} files to transcribe")
    
    # Load configuration
    config = NotetakerConfig.load() if os.path.exists('config.yaml') else NotetakerConfig()
    
    # Create notetaker
    notetaker = Notetaker(config)
    
    # Create output directory
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            for i, file_path in enumerate(files):
                task = progress.add_task(f"Transcribing {file_path.name} ({i+1}/{len(files)})", total=None)
                
                try:
                    result = notetaker.transcribe(str(file_path), Language(language))
                    
                    # Save transcript
                    output_file = Path(output_dir) / f"{file_path.stem}.txt"
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(result.text)
                    
                    # Upload
                    if upload:
                        notetaker.upload_to_cloud(str(file_path))
                    
                    # Send email
                    if email:
                        notetaker.send_email(
                            f"Transcription: {file_path.name}",
                            result
                        )
                    
                    console.log(f"Completed: {file_path.name}", style="green")
                    
                except Exception as e:
                    console.log(f"Failed {file_path.name}: {e}", style="red")
                
                progress.remove_task(task)
        
        console.log(f"\nBatch processing complete!")
        
    except Exception as e:
        console.log(f"Error: {e}", style="red")
    finally:
        notetaker.close()


@cli.command()
def devices():
    """List available audio input devices"""
    
    console.log("Available Audio Input Devices:", style="bold")
    console.log("=" * 50)
    
    # Create temporary recorder to list devices
    config = NotetakerConfig()
    recorder = AudioRecorder(config.audio)
    
    devices = recorder.get_available_devices()
    
    if not devices:
        console.log("No audio input devices found", style="red")
        return
    
    table = Table(title="Audio Devices", show_header=True)
    table.add_column("Index", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Channels", style="blue")
    table.add_column("Sample Rate", style="magenta")
    table.add_column("Host API", style="yellow")
    
    for device in devices:
        table.add_row(
            str(device['index']),
            device['name'],
            str(device['max_input_channels']),
            str(device['default_sample_rate']),
            str(device.get('host_api', 'N/A'))
        )
    
    console.print(table)
    
    recorder.close()


@cli.command()
def setup():
    """Run setup wizard"""
    
    console.log(Panel("[bold]Voxtral Notetaker Setup[/bold]", border_style="blue"))
    
    config = NotetakerConfig()
    
    # Voxtral API Key
    api_key = click.prompt("Enter your Voxtral API key", type=str, default="")
    if api_key:
        config.voxtral.api_key = api_key
    
    # Enable Swiss German
    swiss_german = click.confirm("Enable Swiss German support?", default=True)
    config.voxtral.enable_swiss_german = swiss_german
    
    # Audio settings
    console.log("\n[bold]Audio Settings[/bold]")
    
    devices = []
    try:
        recorder = AudioRecorder(config.audio)
        devices = recorder.get_available_devices()
        recorder.close()
    except:
        pass
    
    if devices:
        console.log("Available devices:")
        for i, device in enumerate(devices):
            console.log(f"  {i}: {device['name']}")
        
        device_index = click.prompt("Select audio device (index)", type=int, default=None)
        if device_index is not None:
            config.audio.device_index = device_index
    
    sample_rate = click.prompt("Sample rate (Hz)", type=int, default=44100)
    config.audio.sample_rate = sample_rate
    
    # Storage settings
    console.log("\n[bold]Storage Settings[/bold]")
    
    provider = click.prompt(
        "Storage provider",
        type=click.Choice([p.value for p in StorageProvider]),
        default='local'
    )
    config.storage.provider = StorageProvider(provider)
    
    if provider == 'google_drive':
        google_creds = click.prompt("Google credentials JSON file path", type=str, default="")
        config.storage.google_credentials = google_creds
        folder_id = click.prompt("Google Drive folder ID (optional)", type=str, default="")
        config.storage.google_folder_id = folder_id or None
    
    elif provider == 'dropbox':
        token = click.prompt("Dropbox access token", type=str, default="")
        config.storage.dropbox_token = token
        folder = click.prompt("Dropbox folder", type=str, default="/VoxtralNotetaker")
        config.storage.dropbox_folder = folder
    
    elif provider == 's3':
        bucket = click.prompt("S3 bucket name", type=str, default="")
        config.storage.s3_bucket = bucket
        region = click.prompt("S3 region", type=str, default="eu-central-1")
        config.storage.s3_region = region
        access_key = click.prompt("S3 access key", type=str, default="")
        config.storage.s3_access_key = access_key
        secret_key = click.prompt("S3 secret key", type=str, default="")
        config.storage.s3_secret_key = secret_key
    
    # Email settings
    console.log("\n[bold]Email Settings[/bold]")
    
    enable_email = click.confirm("Enable email sending?", default=True)
    config.email.enabled = enable_email
    
    if enable_email:
        smtp_host = click.prompt("SMTP host", type=str, default="smtp.gmail.com")
        config.email.smtp_host = smtp_host
        
        smtp_port = click.prompt("SMTP port", type=int, default=587)
        config.email.smtp_port = smtp_port
        
        smtp_user = click.prompt("SMTP username", type=str, default="")
        config.email.smtp_user = smtp_user
        
        smtp_password = click.prompt("SMTP password", type=str, default="", hide_input=True)
        config.email.smtp_password = smtp_password
        
        from_email = click.prompt("From email address", type=str, default="notetaker@voxtral.local")
        config.email.from_email = from_email
        
        to_emails = click.prompt("Recipient emails (comma separated)", type=str, default="")
        if to_emails:
            config.email.to_emails = [e.strip() for e in to_emails.split(',') if e.strip()]
    
    # Save configuration
    config.save('config.yaml')
    
    console.log(f"\n[green]Configuration saved to config.yaml[/green]")
    console.log("\nYou can now use the notetaker with:")
    console.log("  python -m voxtral_notetaker record")
    console.log("  python -m voxtral_notetaker transcribe --file your_audio.wav")


@cli.command()
@click.option('--config-file', '-c', type=str, default='config.yaml', 
              help='Configuration file to validate')
def validate(config_file: str):
    """Validate configuration file"""
    
    try:
        config = NotetakerConfig.load(config_file)
        console.log("[green]Configuration is valid![/green]")
        
        # Display configuration summary
        console.log("\nConfiguration Summary:")
        console.log(f"  Audio: {config.audio.sample_rate}Hz, {config.audio.channels} channels")
        console.log(f"  Voxtral: {config.voxtral.model}, Swiss German: {config.voxtral.enable_swiss_german}")
        console.log(f"  Diarization: {'Enabled' if config.diarization.enabled else 'Disabled'}")
        console.log(f"  Storage: {config.storage.provider.value}")
        console.log(f"  Email: {'Enabled' if config.email.enabled else 'Disabled'}")
        
    except Exception as e:
        console.log(f"[red]Configuration error: {e}[/red]")


def _display_result(result: MeetingResult):
    """Display meeting result"""
    console.log(f"\n[bold green]Meeting Complete[/bold green]")
    console.log(f"Audio file: {result.audio_file}")
    console.log(f"Duration: {(result.end_time - result.start_time).total_seconds():.1f} seconds")
    console.log(f"Language: {result.language}")
    console.log(f"Confidence: {result.confidence * 100:.1f}%")
    
    if result.speaker_segments:
        console.log(f"Speakers detected: {len(set(seg.speaker_id for seg in result.speaker_segments))}")
    
    console.log(f"\nTranscript:\n{result.transcript}")
    
    # Storage results
    if result.storage_results:
        console.log("\nUpload Results:")
        for upload in result.storage_results:
            if upload.success:
                console.log(f"  [green]✓ {upload.provider}: {upload.url or upload.file_path}[/green]")
            else:
                console.log(f"  [red]✗ {upload.provider}: {upload.error}[/red]")
    
    # Email result
    if result.email_result:
        if result.email_result.success:
            console.log(f"\n[green]Email sent to {len(result.email_result.recipients)} recipients[/green]")
        else:
            console.log(f"\n[red]Email failed: {result.email_result.error}[/red]")


@cli.command()
@click.option('--file', '-f', type=str, default=None, help='Audio file to analyze')
@click.option('--debug', is_flag=True, help='Enable debug logging')
def analyze(file: Optional[str], debug: bool):
    """Analyze audio file for speaker diarization"""
    
    if not file:
        console.log("Please specify an audio file with --file", style="red")
        return
    
    if not os.path.exists(file):
        console.log(f"File not found: {file}", style="red")
        return
    
    # Load configuration
    config = NotetakerConfig.load() if os.path.exists('config.yaml') else NotetakerConfig()
    
    # Create notetaker
    notetaker = Notetaker(config)
    
    try:
        console.log(f"Analyzing: {file}")
        
        # Perform diarization
        from .diarization import SpeakerDiarizer
        diarizer = SpeakerDiarizer(config.diarization)
        result = diarizer.diarize(file)
        
        console.log(f"\n[bold green]Diarization Results[/bold green]")
        console.log(f"Audio duration: {result.audio_duration:.1f} seconds")
        console.log(f"Processing time: {result.processing_time:.1f} seconds")
        console.log(f"Total speakers: {result.total_speakers}")
        
        if result.segments:
            console.log("\nSpeaker Segments:")
            for i, seg in enumerate(result.segments):
                console.log(f"  {i+1}. [{seg.start:.1f}s - {seg.end:.1f}s] {seg.speaker_id} ({seg.speaker_name or 'Unknown'}) - Confidence: {seg.confidence:.1f}")
        else:
            console.log("No speaker segments detected")
            
    except Exception as e:
        console.log(f"Error: {e}", style="red")
    finally:
        notetaker.close()


if __name__ == '__main__':
    cli()
