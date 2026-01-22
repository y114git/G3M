from typing import Optional, List, Callable, Any
from functools import wraps
import logging
logger = logging.getLogger(__name__)


class DELTAHUBError(Exception):
    pass


class AppError(DELTAHUBError):

    def __init__(self, key: str, **kwargs):
        self.key = key
        self.kwargs = kwargs
        from managers.localization_manager import tr
        super().__init__(tr(key, **kwargs))

    def get_message(self) -> str:
        from managers.localization_manager import tr
        return tr(self.key, **self.kwargs)


def handle_errors(error_key: str = 'errors.operation_failed', log_level: str = 'error', reraise: bool = False, default_return: Any = None):

    def decorator(func: Callable) -> Callable:

        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except AppError:
                raise
            except Exception as e:
                log_func = getattr(logger, log_level, logger.error)
                log_func(f'{func.__name__}: {e}', exc_info=True)
                if reraise:
                    raise AppError(error_key, error=str(e)) from e
                return default_return
        return wrapper
    return decorator


def safe_operation(func: Callable) -> Callable:

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.warning(f'{func.__name__}: {e}')
            return None
    return wrapper


class ModError(DELTAHUBError):

    def __init__(self, message: str, key: Optional[str] = None, mod_name: Optional[str] = None):
        super().__init__(message)
        self.key = key
        self.mod_name = mod_name


class ModInstallationError(ModError):

    def __init__(self, message: str, key: Optional[str] = None, mod_name: Optional[str] = None, reason: Optional[str] = None):
        super().__init__(message, key, mod_name)
        self.reason = reason


class ModUninstallationError(ModError):

    def __init__(self, message: str, key: Optional[str] = None, mod_name: Optional[str] = None, reason: Optional[str] = None):
        super().__init__(message, key, mod_name)
        self.reason = reason


class ModValidationError(ModError):

    def __init__(self, message: str, key: Optional[str] = None, mod_name: Optional[str] = None, validation_errors: Optional[List[str]] = None):
        super().__init__(message, key, mod_name)
        self.validation_errors = validation_errors or []


class ModConfigError(ModError):

    def __init__(self, message: str, config_path: Optional[str] = None, key: Optional[str] = None, mod_name: Optional[str] = None):
        super().__init__(message, key, mod_name)
        self.config_path = config_path


class ModUpdateError(ModError):

    def __init__(self, message: str, key: Optional[str] = None, mod_name: Optional[str] = None, reason: Optional[str] = None):
        super().__init__(message, key, mod_name)
        self.reason = reason


class NetworkError(DELTAHUBError):

    def __init__(self, message: str, url: Optional[str] = None, status_code: Optional[int] = None):
        super().__init__(message)
        self.url = url
        self.status_code = status_code


class NetworkTimeoutError(NetworkError):

    def __init__(self, message: str, url: Optional[str] = None, timeout: Optional[float] = None):
        super().__init__(message, url)
        self.timeout = timeout


class NetworkConnectionError(NetworkError):
    pass


class HTTPError(NetworkError):

    def __init__(self, message: str, url: Optional[str] = None, status_code: Optional[int] = None, response_body: Optional[str] = None):
        super().__init__(message, url, status_code)
        self.response_body = response_body


class FileOperationError(DELTAHUBError):

    def __init__(self, message: str, file_path: Optional[str] = None, operation: Optional[str] = None):
        super().__init__(message)
        self.file_path = file_path
        self.operation = operation


class MissingFileError(FileOperationError):
    pass


class FilePermissionError(FileOperationError):

    def __init__(self, message: str, file_path: Optional[str] = None, operation: Optional[str] = None, required_permission: Optional[str] = None):
        super().__init__(message, file_path, operation)
        self.required_permission = required_permission


class ArchiveError(FileOperationError):

    def __init__(self, message: str, archive_path: Optional[str] = None, archive_type: Optional[str] = None):
        super().__init__(message, archive_path, 'extract')
        self.archive_type = archive_type


class ArchiveCorruptedError(ArchiveError):
    pass


class DataParsingError(DELTAHUBError):

    def __init__(self, message: str, data_source: Optional[str] = None, data_type: Optional[str] = None):
        super().__init__(message)
        self.data_source = data_source
        self.data_type = data_type


class JSONParsingError(DataParsingError):

    def __init__(self, message: str, json_source: Optional[str] = None, line_number: Optional[int] = None, column_number: Optional[int] = None):
        super().__init__(message, json_source, 'JSON')
        self.line_number = line_number
        self.column_number = column_number
