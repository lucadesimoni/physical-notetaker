"""
Audio recording and processing module
Supports multiple microphones including Jabra Spiders
"""

import os
import wave
import time
import queue
import threading
import numpy as np
from typing import Optional, Tuple, List, Callable
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

import pyaudio
from pydub import AudioSegment
from pydub.effects import normalize
import noisereduce as nr
import librosa

from .config import AudioConfig, AudioFormat


@dataclass
class AudioChunk:
    """Represents a chunk of audio data"""
    data: bytes
    timestamp: float
    sample_rate: int
    channels: int


@dataclass
class RecordingInfo:
    """Information about a recording"""
    file_path: str
    start_time: datetime
    end_time: datetime
    duration: float
    sample_rate: int
    channels: int
    format: AudioFormat


class AudioProcessor:
    """Audio processing utilities"""
    
    def __init__(self, config: AudioConfig):
        self.config = config
    
    def reduce_noise(self, audio_data: np.ndarray, sample_rate: int) -> np.ndarray:
        """Apply noise reduction to audio data"""
        try:
            # Use stationary noise reduction
            reduced_noise = nr.reduce_noise(
                y=audio_data,
                sr=sample_rate,
                stationary=True,
                prop_decrease=0.8,
                time_constant_s=0.5
            )
            return reduced_noise
        except Exception as e:
            print(f"Noise reduction failed: {e}")
            return audio_data
    
    def enhance_audio(self, audio_data: np.ndarray, sample_rate: int) -> np.ndarray:
        """Enhance audio quality"""
        try:
            # Normalize
            audio_data = self._normalize(audio_data)
            
            # Apply spectral gating for noise reduction
            if self.config.noise_reduction:
                audio_data = self.reduce_noise(audio_data, sample_rate)
            
            # Apply dynamic range compression
            audio_data = self._compress(audio_data)
            
            return audio_data
        except Exception as e:
            print(f"Audio enhancement failed: {e}")
            return audio_data
    
    def _normalize(self, audio_data: np.ndarray) -> np.ndarray:
        """Normalize audio to -1 dB"""
        max_val = np.max(np.abs(audio_data))
        if max_val > 0:
            return audio_data / (max_val * 1.1)
        return audio_data
    
    def _compress(self, audio_data: np.ndarray, threshold: float = 0.1, ratio: float = 4.0) -> np.ndarray:
        """Apply simple dynamic range compression"""
        abs_data = np.abs(audio_data)
        compressed = np.copy(audio_data)
        
        mask = abs_data > threshold
        compressed[mask] = np.sign(audio_data[mask]) * (
            threshold + (abs_data[mask] - threshold) / ratio
        )
        
        return compressed
    
    def resample(self, audio_data: np.ndarray, original_rate: int, target_rate: int) -> np.ndarray:
        """Resample audio data"""
        if original_rate == target_rate:
            return audio_data
        
        try:
            return librosa.resample(audio_data, orig_sr=original_rate, target_sr=target_rate)
        except Exception as e:
            print(f"Resampling failed: {e}")
            return audio_data
    
    def convert_to_16bit(self, audio_data: np.ndarray) -> np.ndarray:
        """Convert audio to 16-bit PCM"""
        # Normalize to [-1, 1] range
        audio_data = self._normalize(audio_data)
        # Convert to int16
        return (audio_data * 32767).astype(np.int16)
    
    def save_audio(self, audio_data: np.ndarray, sample_rate: int, 
                   file_path: str, format: AudioFormat = AudioFormat.WAV) -> RecordingInfo:
        """Save audio data to file"""
        start_time = datetime.now()
        
        # Convert to 16-bit PCM
        audio_16bit = self.convert_to_16bit(audio_data)
        
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        
        if format == AudioFormat.WAV:
            with wave.open(file_path, 'wb') as wf:
                wf.setnchannels(1 if len(audio_data.shape) == 1 else audio_data.shape[1])
                wf.setsampwidth(2)  # 2 bytes for 16-bit
                wf.setframerate(sample_rate)
                wf.writeframes(audio_16bit.tobytes())
        elif format == AudioFormat.MP3:
            audio_segment = AudioSegment(
                audio_16bit.tobytes(),
                frame_rate=sample_rate,
                sample_width=2,
                channels=1 if len(audio_data.shape) == 1 else audio_data.shape[1]
            )
            audio_segment.export(file_path, format='mp3', bitrate='192k')
        elif format == AudioFormat.FLAC:
            audio_segment = AudioSegment(
                audio_16bit.tobytes(),
                frame_rate=sample_rate,
                sample_width=2,
                channels=1 if len(audio_data.shape) == 1 else audio_data.shape[1]
            )
            audio_segment.export(file_path, format='flac')
        elif format == AudioFormat.OGG:
            audio_segment = AudioSegment(
                audio_16bit.tobytes(),
                frame_rate=sample_rate,
                sample_width=2,
                channels=1 if len(audio_data.shape) == 1 else audio_data.shape[1]
            )
            audio_segment.export(file_path, format='ogg', bitrate='192k')
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        return RecordingInfo(
            file_path=file_path,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            sample_rate=sample_rate,
            channels=1 if len(audio_data.shape) == 1 else audio_data.shape[1],
            format=format
        )


class AudioRecorder:
    """Audio recorder with support for multiple microphones"""
    
    def __init__(self, config: AudioConfig):
        self.config = config
        self.audio = pyaudio.PyAudio()
        self._is_recording = False
        self._audio_queue = queue.Queue()
        self._recording_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._audio_data: List[bytes] = []
        self._start_time: Optional[datetime] = None
        
        # Initialize audio processor
        self.processor = AudioProcessor(config)
        
        # List available devices
        self._list_devices()
    
    def _list_devices(self):
        """List available audio input devices"""
        print("Available audio input devices:")
        for i in range(self.audio.get_device_count()):
            device_info = self.audio.get_device_info_by_index(i)
            if device_info.get('maxInputChannels', 0) > 0:
                print(f"  {i}: {device_info.get('name', 'Unknown')} "
                      f"(Channels: {device_info.get('maxInputChannels')})"
                      f" - Sample Rate: {device_info.get('defaultSampleRate')}")
    
    def _get_device_index(self) -> int:
        """Get the device index to use"""
        if self.config.device_index is not None:
            return self.config.device_index
        
        # Try to find Jabra device
        for i in range(self.audio.get_device_count()):
            device_info = self.audio.get_device_info_by_index(i)
            device_name = device_info.get('name', '').lower()
            if 'jabra' in device_name or 'spider' in device_name:
                print(f"Found Jabra device at index {i}: {device_info.get('name')}")
                return i
        
        # Return default input device
        return self.audio.get_default_input_device_info()['index']
    
    def _audio_callback(self, in_data: bytes, frame_count: int, time_info, status):
        """Callback for audio stream"""
        if self._is_recording:
            chunk = AudioChunk(
                data=in_data,
                timestamp=time.time(),
                sample_rate=self.config.sample_rate,
                channels=self.config.channels
            )
            self._audio_queue.put(chunk)
            self._audio_data.append(in_data)
        
        return (in_data, pyaudio.paContinue)
    
    def start_recording(self, output_file: Optional[str] = None) -> bool:
        """Start audio recording"""
        if self._is_recording:
            print("Already recording")
            return False
        
        try:
            device_index = self._get_device_index()
            
            self._stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=self.config.channels,
                rate=self.config.sample_rate,
                input=True,
                frames_per_buffer=self.config.chunk_size,
                input_device_index=device_index,
                stream_callback=self._audio_callback
            )
            
            self._is_recording = True
            self._audio_data = []
            self._start_time = datetime.now()
            self._stop_event.clear()
            
            print(f"Started recording at {self.config.sample_rate}Hz, "
                  f"{self.config.channels} channels, "
                  f"device index: {device_index}")
            
            return True
            
        except Exception as e:
            print(f"Failed to start recording: {e}")
            self._is_recording = False
            return False
    
    def stop_recording(self) -> Optional[RecordingInfo]:
        """Stop audio recording and return recording info"""
        if not self._is_recording:
            print("Not recording")
            return None
        
        self._is_recording = False
        
        if hasattr(self, '_stream'):
            self._stream.stop_stream()
            self._stream.close()
        
        end_time = datetime.now()
        
        if self._audio_data and self._start_time:
            # Combine all audio data
            audio_data = b''.join(self._audio_data)
            
            # Convert to numpy array
            audio_np = np.frombuffer(audio_data, dtype=np.int16)
            
            # Apply enhancement if enabled
            if self.config.enhancement:
                audio_np = self.processor.enhance_audio(audio_np, self.config.sample_rate)
            
            # Save to file if output file specified
            if output_file:
                recording_info = self.processor.save_audio(
                    audio_np, 
                    self.config.sample_rate, 
                    output_file, 
                    self.config.format
                )
                return recording_info
            
            # Return basic info
            duration = (end_time - self._start_time).total_seconds()
            return RecordingInfo(
                file_path="",
                start_time=self._start_time,
                end_time=end_time,
                duration=duration,
                sample_rate=self.config.sample_rate,
                channels=self.config.channels,
                format=self.config.format
            )
        
        return None
    
    def get_audio_queue(self) -> queue.Queue:
        """Get the audio queue for real-time processing"""
        return self._audio_queue
    
    def is_recording(self) -> bool:
        """Check if currently recording"""
        return self._is_recording
    
    def get_available_devices(self) -> List[dict]:
        """Get list of available audio input devices"""
        devices = []
        for i in range(self.audio.get_device_count()):
            device_info = self.audio.get_device_info_by_index(i)
            if device_info.get('maxInputChannels', 0) > 0:
                devices.append({
                    'index': i,
                    'name': device_info.get('name', 'Unknown'),
                    'max_input_channels': device_info.get('maxInputChannels'),
                    'default_sample_rate': device_info.get('defaultSampleRate'),
                    'host_api': device_info.get('hostApi')
                })
        return devices
    
    def set_device(self, device_index: int):
        """Set the audio input device"""
        self.config.device_index = device_index
    
    def close(self):
        """Close the audio recorder"""
        if hasattr(self, '_stream'):
            self._stream.stop_stream()
            self._stream.close()
        self.audio.terminate()
        self._is_recording = False
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class AudioSplitter:
    """Split long recordings into smaller chunks"""
    
    def __init__(self, max_duration_minutes: int = 30):
        self.max_duration = max_duration_minutes * 60  # in seconds
    
    def split_audio(self, input_file: str, output_dir: str, 
                   format: AudioFormat = AudioFormat.WAV) -> List[str]:
        """Split audio file into chunks"""
        try:
            audio = AudioSegment.from_file(input_file, format=format.value)
            
            chunk_duration = self.max_duration * 1000  # in milliseconds
            chunks = []
            
            for i, chunk in enumerate(audio[::chunk_duration]):
                output_file = os.path.join(
                    output_dir, 
                    f"{os.path.splitext(os.path.basename(input_file))[0]}_part{i+1}.{format.value}"
                )
                chunk.export(output_file, format=format.value)
                chunks.append(output_file)
            
            return chunks
        except Exception as e:
            print(f"Failed to split audio: {e}")
            return []
