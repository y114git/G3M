"""
Кастомные исключения для DELTAHUB.

Иерархия исключений позволяет более точно обрабатывать ошибки
и предоставлять пользователю понятные сообщения.
"""

from typing import Optional, List


class DELTAHUBError(Exception):
    """Базовое исключение для всех ошибок DELTAHUB."""
    pass


class ModError(DELTAHUBError):
    """Базовое исключение для ошибок, связанных с модами."""
    
    def __init__(self, message: str, mod_key: Optional[str] = None, mod_name: Optional[str] = None):
        super().__init__(message)
        self.mod_key = mod_key
        self.mod_name = mod_name


class ModInstallationError(ModError):
    """Ошибка при установке мода."""
    
    def __init__(self, message: str, mod_key: Optional[str] = None, mod_name: Optional[str] = None, 
                 reason: Optional[str] = None):
        super().__init__(message, mod_key, mod_name)
        self.reason = reason


class ModUninstallationError(ModError):
    """Ошибка при удалении мода."""
    
    def __init__(self, message: str, mod_key: Optional[str] = None, mod_name: Optional[str] = None,
                 reason: Optional[str] = None):
        super().__init__(message, mod_key, mod_name)
        self.reason = reason


class ModValidationError(ModError):
    """Ошибка валидации мода (неверный формат конфига, отсутствующие файлы и т.д.)."""
    
    def __init__(self, message: str, mod_key: Optional[str] = None, mod_name: Optional[str] = None,
                 validation_errors: Optional[List[str]] = None):
        super().__init__(message, mod_key, mod_name)
        self.validation_errors = validation_errors or []


class ModConfigError(ModError):
    """Ошибка при чтении или записи конфигурации мода."""
    
    def __init__(self, message: str, config_path: Optional[str] = None, mod_key: Optional[str] = None,
                 mod_name: Optional[str] = None):
        super().__init__(message, mod_key, mod_name)
        self.config_path = config_path


class ModUpdateError(ModError):
    """Ошибка при обновлении мода."""
    
    def __init__(self, message: str, mod_key: Optional[str] = None, mod_name: Optional[str] = None,
                 reason: Optional[str] = None):
        super().__init__(message, mod_key, mod_name)
        self.reason = reason


class NetworkError(DELTAHUBError):
    """Базовое исключение для сетевых ошибок."""
    
    def __init__(self, message: str, url: Optional[str] = None, status_code: Optional[int] = None):
        super().__init__(message)
        self.url = url
        self.status_code = status_code


class NetworkTimeoutError(NetworkError):
    """Ошибка таймаута при сетевом запросе."""
    
    def __init__(self, message: str, url: Optional[str] = None, timeout: Optional[float] = None):
        super().__init__(message, url)
        self.timeout = timeout


class NetworkConnectionError(NetworkError):
    """Ошибка подключения к сети."""
    pass


class HTTPError(NetworkError):
    """Ошибка HTTP ответа (4xx, 5xx статусы)."""
    
    def __init__(self, message: str, url: Optional[str] = None, status_code: Optional[int] = None,
                 response_body: Optional[str] = None):
        super().__init__(message, url, status_code)
        self.response_body = response_body


class FileOperationError(DELTAHUBError):
    """Базовое исключение для ошибок файловых операций."""
    
    def __init__(self, message: str, file_path: Optional[str] = None, operation: Optional[str] = None):
        super().__init__(message)
        self.file_path = file_path
        self.operation = operation


class MissingFileError(FileOperationError):
    """Файл или директория не найдены."""
    pass


class FilePermissionError(FileOperationError):
    """Ошибка доступа к файлу (нет прав на чтение/запись)."""
    
    def __init__(self, message: str, file_path: Optional[str] = None, operation: Optional[str] = None,
                 required_permission: Optional[str] = None):
        super().__init__(message, file_path, operation)
        self.required_permission = required_permission


class ArchiveError(FileOperationError):
    """Ошибка при работе с архивами (zip, rar, 7z)."""
    
    def __init__(self, message: str, archive_path: Optional[str] = None, 
                 archive_type: Optional[str] = None):
        super().__init__(message, archive_path, 'extract')
        self.archive_type = archive_type


class ArchiveCorruptedError(ArchiveError):
    """Архив поврежден или имеет неверный формат."""
    pass


class DataParsingError(DELTAHUBError):
    """Ошибка парсинга данных (JSON, XML и т.д.)."""
    
    def __init__(self, message: str, data_source: Optional[str] = None, data_type: Optional[str] = None):
        super().__init__(message)
        self.data_source = data_source
        self.data_type = data_type


class JSONParsingError(DataParsingError):
    """Ошибка парсинга JSON."""
    
    def __init__(self, message: str, json_source: Optional[str] = None, 
                 line_number: Optional[int] = None, column_number: Optional[int] = None):
        super().__init__(message, json_source, 'JSON')
        self.line_number = line_number
        self.column_number = column_number

