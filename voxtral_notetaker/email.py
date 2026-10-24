"""
Email sending module for distributing meeting notes
"""

import os
import smtplib
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

import jinja2

from .config import EmailConfig
from .transcription import TranscriptionResult


@dataclass
class EmailResult:
    """Result of email sending"""
    success: bool
    recipients: List[str]
    subject: str
    error: Optional[str] = None
    message_id: Optional[str] = None


class EmailSender:
    """Email sender for meeting notes distribution"""
    
    def __init__(self, config: EmailConfig):
        self.config = config
        self._template_env = None
    
    def send(self, subject: str, 
             body: str, 
             to_emails: Optional[List[str]] = None,
             cc_emails: Optional[List[str]] = None,
             bcc_emails: Optional[List[str]] = None,
             attachments: Optional[List[str]] = None,
             is_html: bool = False) -> EmailResult:
        """Send an email with optional attachments"""
        
        if not self.config.enabled:
            return EmailResult(
                success=False,
                recipients=to_emails or [],
                subject=subject,
                error="Email sending is disabled"
            )
        
        # Use configured emails if not provided
        recipients = to_emails or self.config.to_emails
        cc_recipients = cc_emails or self.config.cc_emails
        bcc_recipients = bcc_emails or self.config.bcc_emails
        
        if not recipients:
            return EmailResult(
                success=False,
                recipients=[],
                subject=subject,
                error="No recipients specified"
            )
        
        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = self.config.from_email
            msg['To'] = ', '.join(recipients)
            if cc_recipients:
                msg['Cc'] = ', '.join(cc_recipients)
            msg['Subject'] = subject
            msg['Date'] = datetime.now().strftime('%a, %d %b %Y %H:%M:%S %z')
            
            # Add body
            if is_html:
                msg.attach(MIMEText(body, 'html'))
            else:
                msg.attach(MIMEText(body, 'plain'))
            
            # Add attachments
            if attachments:
                for file_path in attachments:
                    if os.path.exists(file_path):
                        self._add_attachment(msg, file_path)
            
            # Send email
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port) as server:
                if self.config.use_tls:
                    server.starttls()
                
                if self.config.smtp_user and self.config.smtp_password:
                    server.login(self.config.smtp_user, self.config.smtp_password)
                
                # Combine all recipients
                all_recipients = recipients + cc_recipients + bcc_recipients
                
                # Send
                response = server.sendmail(
                    self.config.from_email,
                    all_recipients,
                    msg.as_string()
                )
                
                # Get message ID from response
                message_id = msg['Message-ID'] if 'Message-ID' in msg else None
                
                return EmailResult(
                    success=True,
                    recipients=all_recipients,
                    subject=subject,
                    message_id=message_id
                )
                
        except Exception as e:
            return EmailResult(
                success=False,
                recipients=recipients,
                subject=subject,
                error=str(e)
            )
    
    def send_transcription(self, result: TranscriptionResult,
                           subject: Optional[str] = None,
                           to_emails: Optional[List[str]] = None) -> EmailResult:
        """Send transcription result via email"""
        
        # Generate subject
        if not subject:
            subject = self._render_template(
                self.config.subject_template,
                {'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            )
        
        # Generate body
        body = self._render_template(
            self.config.body_template,
            {
                'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'transcript': result.text,
                'language': result.language,
                'confidence': f"{result.confidence * 100:.1f}%",
                'duration': f"{result.duration:.1f} seconds"
            }
        )
        
        # Collect attachments
        attachments = []
        
        # Add audio file if configured
        if self.config.send_audio and hasattr(result, 'audio_file'):
            attachments.append(result.audio_file)
        
        # Create transcript file
        if self.config.send_transcript:
            transcript_file = self._create_transcript_file(result)
            if transcript_file:
                attachments.append(transcript_file)
        
        # Create notes file
        if self.config.send_notes:
            notes_file = self._create_notes_file(result)
            if notes_file:
                attachments.append(notes_file)
        
        # Send email
        return self.send(
            subject=subject,
            body=body,
            to_emails=to_emails,
            attachments=attachments,
            is_html=False
        )
    
    def _add_attachment(self, msg: MIMEMultipart, file_path: str):
        """Add file attachment to email"""
        with open(file_path, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
        
        # Encode file in ASCII characters
        encoders.encode_base64(part)
        
        # Add header
        part.add_header(
            'Content-Disposition',
            f'attachment; filename="{os.path.basename(file_path)}"'
        )
        
        msg.attach(part)
    
    def _create_transcript_file(self, result: TranscriptionResult) -> Optional[str]:
        """Create a transcript text file"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"transcript_{timestamp}.txt"
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"Transcription Results\n")
                f.write(f"===================\n\n")
                f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Language: {result.language}\n")
                f.write(f"Confidence: {result.confidence * 100:.1f}%\n")
                f.write(f"Duration: {result.duration:.1f} seconds\n\n")
                f.write(f"Transcript:\n")
                f.write(f"---\n\n")
                f.write(result.text)
            
            return filename
        except Exception as e:
            print(f"Failed to create transcript file: {e}")
            return None
    
    def _create_notes_file(self, result: TranscriptionResult) -> Optional[str]:
        """Create a formatted notes file"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"notes_{timestamp}.md"
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"# Meeting Notes\n\n")
                f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(f"**Language:** {result.language}\n\n")
                f.write(f"**Confidence:** {result.confidence * 100:.1f}%\n\n")
                f.write(f"**Duration:** {result.duration:.1f} seconds\n\n")
                f.write(f"---\n\n")
                f.write(f"## Transcript\n\n")
                f.write(result.text)
                
                # Add metadata
                f.write(f"\n\n---\n\n")
                f.write(f"*Generated by Voxtral Notetaker*\n")
            
            return filename
        except Exception as e:
            print(f"Failed to create notes file: {e}")
            return None
    
    def _render_template(self, template: str, context: Dict[str, Any]) -> str:
        """Render a Jinja2 template"""
        try:
            if not self._template_env:
                self._template_env = jinja2.Environment(
                    loader=jinja2.BaseLoader(),
                    autoescape=False
                )
            
            tmpl = self._template_env.from_string(template)
            return tmpl.render(**context)
        except Exception as e:
            print(f"Template rendering failed: {e}")
            return template.format(**context)
    
    def send_with_template(self, template_file: str, 
                          context: Dict[str, Any],
                          to_emails: Optional[List[str]] = None,
                          attachments: Optional[List[str]] = None) -> EmailResult:
        """Send email using a template file"""
        
        # Load template
        with open(template_file, 'r', encoding='utf-8') as f:
            template_content = f.read()
        
        # Parse template (split by first occurrence of ---)
        parts = template_content.split('---', 1)
        
        if len(parts) >= 2:
            subject = parts[0].strip()
            body = parts[1].strip()
        else:
            subject = "Meeting Notes"
            body = template_content
        
        # Render body
        rendered_body = self._render_template(body, context)
        
        # Send email
        return self.send(
            subject=self._render_template(subject, context),
            body=rendered_body,
            to_emails=to_emails,
            attachments=attachments,
            is_html=False
        )
