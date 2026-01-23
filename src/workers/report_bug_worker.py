"""Bug report submission worker.

This module provides a worker for collecting and submitting bug reports with logs.
"""
import os
import sys
import shutil
import tempfile
import zipfile
import logging
import platform
from typing import List
from datetime import datetime
from PyQt6.QtCore import QObject, pyqtSignal, PYQT_VERSION_STR
from config.constants import CLOUD_FUNCTIONS_BASE_URL, NETWORK_TIMEOUT_LONG, LAUNCHER_VERSION
from utils.network_utils import get_session
from utils.path_utils import get_user_data_root
from managers.localization_manager import tr


class ReportBugWorker(QObject):
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)
    error = pyqtSignal(str)

    def __init__(self, report_text: str, attached_files: List[str], attach_logs: bool, app_state):
        super().__init__()
        self.report_text = report_text
        self.attached_files = attached_files
        self.attach_logs = attach_logs
        self.app_state = app_state
        self.temp_dir = None
        self.zip_path = None

    def _get_system_info(self) -> str:
        try:
            info_lines = ['=' * 60, 'SYSTEM INFORMATION', '=' * 60, f"Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", '', f'Operating System: {platform.system()}', f'OS Version: {platform.platform()}', f'Architecture: {platform.architecture()[0]}', f'Processor: {platform.machine()}', '', f'Python Version: {sys.version.split()[0]}', f'PyQt6 Version: {PYQT_VERSION_STR}', f'DELTAHUB Version: {LAUNCHER_VERSION}', '', '=' * 60, 'USER REPORT', '=' * 60, '']
            return '\n'.join(info_lines)
        except Exception as e:
            logging.warning(f'ReportBugWorker: Failed to collect system info: {e}')
            return f"System Information: Error collecting info ({e})\n\n{'=' * 60}\nUSER REPORT\n{'=' * 60}\n\n"

    def run(self):
        try:
            self.progress.emit(-1)
            self.temp_dir = tempfile.mkdtemp(prefix='deltahub-report-')
            logging.info(f'ReportBugWorker: Created temp directory: {self.temp_dir}')
            report_file_path = os.path.join(self.temp_dir, 'REPORT.txt')
            with open(report_file_path, 'w', encoding='utf-8') as f:
                system_info = self._get_system_info()
                f.write(system_info)
                f.write(self.report_text)
            logging.info('ReportBugWorker: Created REPORT.txt with system information')
            self.progress.emit(20)
            total_attachments = len(self.attached_files)
            for i, file_path in enumerate(self.attached_files):
                if not os.path.exists(file_path):
                    logging.warning(f'ReportBugWorker: File not found: {file_path}')
                    continue
                dest_path = os.path.join(self.temp_dir, os.path.basename(file_path))
                shutil.copy2(file_path, dest_path)
                logging.info(f'ReportBugWorker: Copied file: {os.path.basename(file_path)}')
                self.progress.emit(20 + int((i + 1) / total_attachments * 20) if total_attachments else 40)
            self.progress.emit(40)
            if self.attach_logs:
                user_data_root = get_user_data_root()
                log_files = []
                if os.path.exists(user_data_root):
                    log_files = [os.path.join(root, file) for root, _, files in os.walk(user_data_root) for file in files if file.endswith('.log')]
                logging.info(f'ReportBugWorker: Found {len(log_files)} log files')
                for i, log_path in enumerate(log_files):
                    try:
                        rel_path = os.path.relpath(log_path, user_data_root)
                        dest_path = os.path.join(self.temp_dir, 'logs', rel_path)
                        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                        shutil.copy2(log_path, dest_path)
                        logging.info(f'ReportBugWorker: Copied log: {rel_path}')
                    except Exception as e:
                        logging.warning(f'ReportBugWorker: Failed to copy log {log_path}: {e}')
                self.progress.emit(60)
            self.zip_path = os.path.join(tempfile.gettempdir(), f'deltahub-report-{os.getpid()}.zip')
            with zipfile.ZipFile(self.zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(self.temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, self.temp_dir)
                        zipf.write(file_path, arcname)
                        logging.debug(f'ReportBugWorker: Added to ZIP: {arcname}')
            zip_size = os.path.getsize(self.zip_path)
            logging.info(f'ReportBugWorker: Created ZIP archive: {self.zip_path} ({zip_size} bytes)')
            self.progress.emit(70)
            if not CLOUD_FUNCTIONS_BASE_URL:
                raise ValueError('CLOUD_FUNCTIONS_BASE_URL is not configured')
            url = f"{CLOUD_FUNCTIONS_BASE_URL.rstrip('/')}/uploadBugReport"
            session = get_session()
            self.progress.emit(80)
            with open(self.zip_path, 'rb') as f:
                files = {'file': (os.path.basename(self.zip_path), f, 'application/zip')}
                response = session.post(url, files=files, timeout=NETWORK_TIMEOUT_LONG)
            self.progress.emit(90)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and data.get('ok'):
                    logging.info('ReportBugWorker: Report uploaded successfully')
                    self.progress.emit(100)
                    self.finished.emit(True, '')
                else:
                    error_msg = data.get('error', 'Unknown error') if isinstance(data, dict) else 'Unknown error'
                    if 'cooldown' in str(error_msg).lower():
                        error_msg = tr('dialogs.report_bug_cooldown', minutes='30')
                    logging.warning(f'ReportBugWorker: Upload failed: {error_msg}')
                    self.finished.emit(False, error_msg)
            elif response.status_code == 429:
                error_msg = tr('dialogs.report_bug_cooldown', minutes='30')
                self.finished.emit(False, error_msg)
            else:
                error_text = response.text[:200] if hasattr(response, 'text') else 'Unknown error'
                logging.warning(f'ReportBugWorker: Upload failed. Status: {response.status_code}, Response: {error_text}')
                self.finished.emit(False, f'HTTP {response.status_code}: {error_text}')
        except Exception as e:
            error_msg = str(e)
            logging.error(f'ReportBugWorker: Error: {e}', exc_info=True)
            self.error.emit(error_msg)
            self.finished.emit(False, error_msg)
        finally:
            self._cleanup()

    def _cleanup(self):
        try:
            if self.temp_dir and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                logging.info(f'ReportBugWorker: Removed temp directory: {self.temp_dir}')
        except Exception as e:
            logging.warning(f'ReportBugWorker: Failed to remove temp directory: {e}')
        try:
            if self.zip_path and os.path.exists(self.zip_path):
                os.remove(self.zip_path)
                logging.info(f'ReportBugWorker: Removed ZIP file: {self.zip_path}')
        except Exception as e:
            logging.warning(f'ReportBugWorker: Failed to remove ZIP file: {e}')
