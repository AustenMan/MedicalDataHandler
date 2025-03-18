import sys
import logging
from collections import deque

APP_LOGGER_NAME = "mdh_logger"

class StreamToLogger:
    """
    A fake file-like stream object that redirects writes to a logger instance.
    
    Args:
        logger (logging.Logger): The logger instance to which messages will be redirected.
        log_level (int): The logging level (e.g., logging.INFO, logging.ERROR).
    
    Attributes:
        logger (logging.Logger): The logger instance for redirection.
        log_level (int): The logging level.
        buffer (str): A temporary buffer to accumulate messages.
    """
    def __init__(self, logger, log_level=logging.INFO):
        self.logger = logger
        self.log_level = log_level
        self.buffer = ''
    
    def write(self, message):
        """
        Writes a message to the logger, handling line breaks and logging only non-empty lines.
        
        Args:
            message (str): The message to write to the logger.
        """
        # Add the incoming message to the buffer
        self.buffer += message
        # Check if a newline is in the buffer
        while '\n' in self.buffer:
            # Split at the newline
            line, self.buffer = self.buffer.split('\n', 1)
            # Log the line if it's not empty
            if line.strip():
                self.logger.log(self.log_level, line.strip())
    
    def flush(self):
        """
        Flushes any remaining content in the buffer to the logger.
        """
        # Log any remaining content in the buffer
        if self.buffer.strip():
            self.logger.log(self.log_level, self.buffer.strip())
        self.buffer = ''

class BufferHandler(logging.Handler):
    """
    A custom logging handler that stores log messages in a buffer.
    
    Args:
        buffer_length (int): The maximum number of messages to store in the buffer.
    
    Attributes:
        _messages (deque): A deque to store log messages, with a maximum length.
    """
    def __init__(self, buffer_length):
        super().__init__()
        self._messages = deque(maxlen=buffer_length)
    
    def emit(self, record):
        """
        Processes a log record and appends the formatted message to the buffer.
        
        Args:
            record (logging.LogRecord): The log record to process.
        """
        message = self.format(record)
        self._messages.append(message)
    
    def get_messages(self):
        """
        Retrieves all messages currently in the buffer.
        
        Returns:
            list: A list of log messages.
        """
        return list(self._messages)
    
    def get_latest_message(self):
        """
        Retrieves the latest message in the buffer.
        
        Returns:
            str: The latest log message.
        """
        return self._messages[-1] if self._messages else ""
    
    def clear_messages(self):
        """
        Clears all messages from the buffer.
        """
        self._messages.clear()

def start_logger(logger_level=logging.DEBUG, use_buffer_handler=True, buffer_length=300, redirect_stdout=True):
    """
    Configures and returns a logger with optional buffering and stdout/stderr redirection.
    
    Args:
        logger_level (int): The logging level (e.g., logging.DEBUG, logging.INFO).
        use_buffer_handler (bool): Whether to use a buffer handler for log messages.
        buffer_length (int): The maximum number of messages to store in the buffer.
        redirect_stdout (bool): Whether to redirect stdout and stderr to the logger.
    
    Returns:
        logging.Logger: A configured logger instance.
    """
    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.setLevel(logger_level)
    logger.propagate = False  # Prevent messages from being propagated to the root logger multiple times
    
    # Check if handlers are already added to prevent duplicate logs
    if not logger.handlers:
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        
        if use_buffer_handler:
            buffer_handler = BufferHandler(buffer_length)
            buffer_handler.setFormatter(formatter)
            logger.addHandler(buffer_handler)
        
        # Optionally add a StreamHandler to output to the console
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
    
    if redirect_stdout:
        # Redirect stdout and stderr to the logger
        sys.stdout = StreamToLogger(logger, logging.INFO)
        sys.stderr = StreamToLogger(logger, logging.ERROR)
    
    return logger

def get_logger():
    """
    Retrieves the logger instance for the application.
    
    Returns:
        logging.Logger: The logger instance.
    """
    return logging.getLogger(APP_LOGGER_NAME)

def safe_log(logger=None, level: str = "error", msg: str = "Error: No message provided to safe_log function.", print_and_log=False, print_as_backup=True):
    """
    Logs a message safely to a logger or prints it as a fallback.
    
    Args:
        logger (logging.Logger or None): The logger instance to use for logging.
        level (str): The logging level ("info", "warning", or "error").
        msg (str): The message to log or print.
        print_and_log (bool): Whether to both print and log the message.
        print_as_backup (bool): Whether to print the message if no logger is provided.
    """
    if logger:
        try:
            if level.lower() == "info":
                logger.info(msg)
            elif level.lower() == "warning":
                logger.warning(msg)
            else:
                logger.error(msg, exc_info=True)
        except Exception as e:
            print(f"Error logging message with logger {logger} : {e}\n\tMessage: {msg}", flush=True)
        if print_and_log:
            print(msg, flush=True)
    elif print_as_backup:
        print(msg, flush=True)
