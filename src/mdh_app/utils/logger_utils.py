import os
import sys
import logging
from datetime import datetime
from collections import deque
from typing import List

from mdh_app.utils.general_utils import get_source_dir

class StreamToLogger:
    """
    Redirects writes from stdout/stderr to a logger.

    Args:
        logger: Logger instance to redirect output to.
        log_level: Logging level (e.g., logging.INFO, logging.ERROR).
    """
    def __init__(self, logger: logging.Logger, log_level: int = logging.INFO) -> None:
        self.logger = logger
        self.log_level = log_level
        self._buffer = ""

    def write(self, message: str) -> None:
        """Writes message to logger, line-buffered."""
        self._buffer += message
        while '\n' in self._buffer:
            line, self._buffer = self._buffer.split('\n', 1)
            if line.strip():
                self.logger.log(self.log_level, line.strip())

    def flush(self) -> None:
        """Flushes remaining buffer content to the logger."""
        if self._buffer.strip():
            self.logger.log(self.log_level, self._buffer.strip())
        self._buffer = ""

class BufferHandler(logging.Handler):
    """
    Custom logging handler that retains recent log messages in a ring buffer.

    Args:
        buffer_length: Maximum number of log messages to retain.
    """
    def __init__(self, buffer_length: int) -> None:
        super().__init__()
        self._messages: deque[str] = deque(maxlen=buffer_length)

    def emit(self, record: logging.LogRecord) -> None:
        """Formats and stores the log record."""
        msg = self.format(record)
        self._messages.append(msg)

    def get_messages(self) -> List[str]:
        """Returns all buffered log messages."""
        return list(self._messages)

    def get_latest_message(self) -> str:
        """Returns the most recent log message, or an empty string if buffer is empty."""
        return self._messages[-1] if self._messages else ""

    def clear_messages(self) -> None:
        """Clears all messages from the buffer."""
        self._messages.clear()

def start_root_logger(
    logger_level: int = logging.DEBUG,
    buffer_length: int = 300,
    redirect_stdout: bool = True
) -> logging.Logger:
    """
    Initializes the application-wide root logger with console, buffer, and timestamped file output.

    Args:
        logger_level: Logging level to apply.
        buffer_length: Max number of messages to buffer.
        redirect_stdout: Redirects sys.stdout/sys.stderr to the logger.

    Returns:
        The configured logger instance.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(logger_level)
    root_logger.propagate = False  # Prevent messages from being propagated to the root logger multiple times
    
    # Check if handlers are already added to prevent duplicate logs
    if not root_logger.handlers:
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        
        # Create logs directory
        project_root_dir = get_source_dir()
        parent_dir = os.path.dirname(project_root_dir)
        logs_dir = os.path.join(parent_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        
        # Create timestamped log file
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_file_path = os.path.join(logs_dir, f"app_log_{timestamp}.log")
        
        # File handler
        file_handler = logging.FileHandler(log_file_path)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        
        # Buffer handler
        buffer_handler = BufferHandler(buffer_length)
        buffer_handler.setFormatter(formatter)
        root_logger.addHandler(buffer_handler)
        
        # Stream handler
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)
    
    # Redirect stdout and stderr to the logger
    if redirect_stdout and not isinstance(sys.stdout, StreamToLogger):
        sys.stdout = StreamToLogger(root_logger, logging.INFO)
        sys.stderr = StreamToLogger(root_logger, logging.ERROR)
    
    return root_logger

def get_root_logger() -> logging.Logger:
    """Returns the configured application logger."""
    return logging.getLogger()
