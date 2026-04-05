import logging
from logging.handlers import RotatingFileHandler
import os

def setup_industrial_logger(log_file="app_rolling.log"):
    """
    Sets up a non-intrusive rotating file logger.
    - Max size: 10MB
    - Backups: 3
    - Format: [Timestamp] [Level] Message
    """
    logger = logging.getLogger("LiberalRoller")
    logger.setLevel(logging.INFO)
    
    # Prevent duplicate handlers if re-initialized
    if not logger.handlers:
        handler = RotatingFileHandler(
            log_file, 
            maxBytes=10*1024*1024, 
            backupCount=3,
            encoding='utf-8'
        )
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    return logger

# Global logger instance
logger = setup_industrial_logger()
