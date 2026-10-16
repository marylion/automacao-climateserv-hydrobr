import logging
from dataclasses import dataclass, field
from datetime import datetime
from getpass import getuser
from logging import FileHandler, Logger, LogRecord
from pathlib import Path
from queue import Queue
from threading import Lock
from typing import Callable

try:
    from rich.logging import RichHandler
except ImportError:  # pragma: no cover - fallback for standalone scripts without rich
    RichHandler = None


HandlerFactory = Callable[[], logging.Handler | None]


@dataclass(slots=True)
class LoggerRegistration:
    logger: Logger
    config_signature: str


def _timestamp(kind: str) -> str:
    if kind == "logs":
        return datetime.now().strftime("%Y_%m_%d")
    if kind == "execution":
        return datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    raise ValueError(f"Unsupported timestamp kind: {kind}")


def _resolve_level(level: str | int | None, default: int = logging.DEBUG) -> int:
    if level is None:
        return default
    if isinstance(level, int):
        return level

    mapping = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    return mapping.get(str(level).upper(), default)


class TkinterLogHandler(logging.Handler):
    def __init__(self, log_queue: Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: LogRecord) -> None:
        try:
            self.log_queue.put(record)
        except Exception:
            self.handleError(record)


@dataclass(slots=True)
class StandaloneLoggerConfig:
    name: str = "app"
    app_log_name: str = "app"
    log_dir: Path | str = Path("./logs")
    level: str | int = logging.DEBUG
    console_level: str | int | None = None
    propagate: bool = False
    enable_console: bool = True
    prefer_rich_console: bool = True
    enable_email_handler: bool = False
    enable_ui_handler: bool = False
    file_execution_simple: bool = True
    file_execution_tiny: bool = True
    file_execution_complete: bool = True
    file_daily_simple: bool = True
    file_daily_tiny: bool = True
    file_daily_complete: bool = True
    file_all_simple: bool = True
    file_all_tiny: bool = True
    file_all_complete: bool = True
    file_root_simple: bool = True
    file_root_tiny: bool = True
    email_handler_factory: HandlerFactory | None = None
    ui_queue: Queue | None = None
    current_user: str = field(default_factory=getuser)

    @property
    def resolved_log_dir(self) -> Path:
        return Path(self.log_dir)

    @property
    def resolved_level(self) -> int:
        return _resolve_level(self.level, logging.DEBUG)

    @property
    def resolved_console_level(self) -> int:
        if self.console_level is None:
            return self.resolved_level
        return _resolve_level(self.console_level, self.resolved_level)

    @property
    def cache_key(self) -> str:
        return self.name

    @property
    def config_signature(self) -> str:
        return "|".join(
            [
                str(self.resolved_log_dir.resolve()),
                self.app_log_name,
                str(self.resolved_level),
                str(self.resolved_console_level),
                str(self.enable_console),
                str(self.prefer_rich_console),
                str(self.enable_email_handler),
                str(self.enable_ui_handler),
                str(self.file_execution_simple),
                str(self.file_execution_tiny),
                str(self.file_execution_complete),
                str(self.file_daily_simple),
                str(self.file_daily_tiny),
                str(self.file_daily_complete),
                str(self.file_all_simple),
                str(self.file_all_tiny),
                str(self.file_all_complete),
                str(self.file_root_simple),
                str(self.file_root_tiny),
            ]
        )


def get_formatters(current_user: str) -> dict[str, dict[str, str]]:
    return {
        "file": {
            "fmt": f"%(levelname)-8s - %(asctime)s [{current_user}] - %(pathname)s:%(lineno)d %(funcName)s(): %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
            "fmt_simple": f"%(asctime)s [{current_user}] %(levelname)s: %(funcName)s.%(lineno)d(): %(message)s",
            "datefmt_simple": "%H:%M:%S",
            "fmt_tiny": f"%(asctime)s - %(levelname)-8s - [{current_user}] - %(message)s",
            "datefmt_tiny": "%Y-%m-%d %H:%M:%S",
        },
        "console": {
            "fmt": f"%(levelname)-8s - %(asctime)s [{current_user}] \"%(filename)s\" - %(funcName)s(): %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "gui": {
            "fmt": f"%(levelname)-8s - %(asctime)s [{current_user}] - %(pathname)s:%(lineno)d %(funcName)s(): %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    }


def create_file_handler(
    log_path: Path,
    *,
    level: int,
    fmt: str,
    datefmt: str,
) -> FileHandler:
    log_path.parent.mkdir(exist_ok=True, parents=True)
    handler = FileHandler(log_path, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
    return handler


def create_console_handler(config: StandaloneLoggerConfig) -> logging.Handler:
    formatters = get_formatters(config.current_user)
    formatter = logging.Formatter(
        fmt=formatters["console"]["fmt"],
        datefmt=formatters["console"]["datefmt"],
    )

    if config.prefer_rich_console and RichHandler is not None:
        handler = RichHandler(
            level=config.resolved_console_level,
            rich_tracebacks=True,
            omit_repeated_times=True,
            show_time=False,
            show_level=False,
            show_path=False,
        )
    else:
        handler = logging.StreamHandler()

    handler.setLevel(config.resolved_console_level)
    handler.setFormatter(formatter)
    return handler


def create_ui_handler(config: StandaloneLoggerConfig) -> logging.Handler | None:
    if config.ui_queue is None:
        return None

    formatters = get_formatters(config.current_user)
    handler = TkinterLogHandler(config.ui_queue)
    handler.setLevel(config.resolved_level)
    handler.setFormatter(logging.Formatter(formatters["gui"]["fmt"], formatters["gui"]["datefmt"]))
    return handler


def create_email_handler(config: StandaloneLoggerConfig) -> logging.Handler | None:
    if config.email_handler_factory is None:
        return None
    return config.email_handler_factory()


def create_project_like_handlers(config: StandaloneLoggerConfig) -> list[logging.Handler]:
    log_dir = config.resolved_log_dir
    formatters = get_formatters(config.current_user)
    handlers: list[logging.Handler] = []

    if config.file_execution_simple:
        handlers.append(
            create_file_handler(
                log_dir / "each" / "simple" / f"{config.app_log_name}_{_timestamp('execution')}.log",
                level=config.resolved_level,
                fmt=formatters["file"]["fmt_simple"],
                datefmt=formatters["file"]["datefmt"],
            )
        )
    if config.file_execution_tiny:
        handlers.append(
            create_file_handler(
                log_dir / "each" / "tiny" / f"{config.app_log_name}_{_timestamp('execution')}.log",
                level=config.resolved_level,
                fmt=formatters["file"]["fmt_tiny"],
                datefmt=formatters["file"]["datefmt_tiny"],
            )
        )
    if config.file_execution_complete:
        handlers.append(
            create_file_handler(
                log_dir / "each" / "complete" / f"{config.app_log_name}_{_timestamp('execution')}.log",
                level=config.resolved_level,
                fmt=formatters["file"]["fmt"],
                datefmt=formatters["file"]["datefmt"],
            )
        )
    if config.file_daily_simple:
        handlers.append(
            create_file_handler(
                log_dir / "daily" / "simple" / f"{config.app_log_name}_{_timestamp('logs')}.log",
                level=config.resolved_level,
                fmt=formatters["file"]["fmt_simple"],
                datefmt=formatters["file"]["datefmt_simple"],
            )
        )
    if config.file_daily_tiny:
        handlers.append(
            create_file_handler(
                log_dir / "daily" / "tiny" / f"{config.app_log_name}_{_timestamp('logs')}.log",
                level=config.resolved_level,
                fmt=formatters["file"]["fmt_tiny"],
                datefmt=formatters["file"]["datefmt_tiny"],
            )
        )
    if config.file_daily_complete:
        handlers.append(
            create_file_handler(
                log_dir / "daily" / "complete" / f"{config.app_log_name}_{_timestamp('logs')}.log",
                level=config.resolved_level,
                fmt=formatters["file"]["fmt"],
                datefmt=formatters["file"]["datefmt"],
            )
        )
    if config.file_all_simple:
        handlers.append(
            create_file_handler(
                log_dir / "all" / "simple" / f"{config.app_log_name}.log",
                level=config.resolved_level,
                fmt=formatters["file"]["fmt_simple"],
                datefmt=formatters["file"]["datefmt_simple"],
            )
        )
    if config.file_all_tiny:
        handlers.append(
            create_file_handler(
                log_dir / "all" / "tiny" / f"{config.app_log_name}.log",
                level=config.resolved_level,
                fmt=formatters["file"]["fmt_tiny"],
                datefmt=formatters["file"]["datefmt_tiny"],
            )
        )
    if config.file_all_complete:
        handlers.append(
            create_file_handler(
                log_dir / "all" / "complete" / f"{config.app_log_name}.log",
                level=config.resolved_level,
                fmt=formatters["file"]["fmt"],
                datefmt=formatters["file"]["datefmt"],
            )
        )
    if config.file_root_simple:
        handlers.append(
            create_file_handler(
                log_dir / f"{config.app_log_name}.log",
                level=config.resolved_level,
                fmt=formatters["file"]["fmt"],
                datefmt=formatters["file"]["datefmt"],
            )
        )
    if config.file_root_tiny:
        handlers.append(
            create_file_handler(
                log_dir / f"{config.app_log_name}_tiny.log",
                level=config.resolved_level,
                fmt=formatters["file"]["fmt_tiny"],
                datefmt=formatters["file"]["datefmt_tiny"],
            )
        )

    if config.enable_console:
        handlers.append(create_console_handler(config))

    ui_handler = create_ui_handler(config) if config.enable_ui_handler else None
    if ui_handler is not None:
        handlers.append(ui_handler)

    email_handler = create_email_handler(config) if config.enable_email_handler else None
    if email_handler is not None:
        handlers.append(email_handler)

    return handlers


def build_project_like_logger(config: StandaloneLoggerConfig) -> Logger:
    logger = logging.getLogger(config.name)
    logger.setLevel(config.resolved_level)
    logger.propagate = config.propagate
    logger.handlers.clear()
    config.resolved_log_dir.mkdir(exist_ok=True, parents=True)

    for handler in create_project_like_handlers(config):
        logger.addHandler(handler)

    return logger


def build_full_logger(
    *,
    name: str = "app",
    app_log_name: str = "app",
    log_dir: Path | str = Path("./logs"),
    level: str | int = logging.DEBUG,
    console_level: str | int | None = None,
    enable_console: bool = True,
    prefer_rich_console: bool = True,
    enable_email_handler: bool = False,
    enable_ui_handler: bool = False,
    email_handler_factory: HandlerFactory | None = None,
    ui_queue: Queue | None = None,
    file_root_simple: bool = True,
    file_root_tiny: bool = True,
) -> Logger:
    config = StandaloneLoggerConfig(
        name=name,
        app_log_name=app_log_name,
        log_dir=log_dir,
        level=level,
        console_level=console_level,
        enable_console=enable_console,
        prefer_rich_console=prefer_rich_console,
        enable_email_handler=enable_email_handler,
        enable_ui_handler=enable_ui_handler,
        email_handler_factory=email_handler_factory,
        ui_queue=ui_queue,
        file_root_simple=file_root_simple,
        file_root_tiny=file_root_tiny,
    )
    return get_logger(config)


def build_simple_logger(
    *,
    name: str = "app_simple",
    app_log_name: str = "app",
    log_dir: Path | str = Path("./logs"),
    level: str | int = logging.INFO,
    enable_console: bool = True,
    prefer_rich_console: bool = True,
) -> Logger:
    config = StandaloneLoggerConfig(
        name=name,
        app_log_name=app_log_name,
        log_dir=log_dir,
        level=level,
        enable_console=enable_console,
        prefer_rich_console=prefer_rich_console,
        file_execution_simple=False,
        file_execution_tiny=False,
        file_execution_complete=False,
        file_daily_simple=False,
        file_daily_tiny=False,
        file_daily_complete=False,
        file_all_simple=False,
        file_all_tiny=False,
        file_all_complete=False,
        file_root_simple=True,
        file_root_tiny=True,
    )
    return get_logger(config)


def build_root_simple_logger(
    *,
    name: str = "app_simple",
    app_log_name: str = "app",
    log_dir: Path | str = Path("./logs"),
    level: str | int = logging.DEBUG,
    enable_console: bool = True,
    prefer_rich_console: bool = True,
) -> Logger:
    return build_simple_logger(
        name=name,
        app_log_name=app_log_name,
        log_dir=log_dir,
        level=level,
        enable_console=enable_console,
        prefer_rich_console=prefer_rich_console,
    )

def build_logger(
    *,
    name: str = "app_simple",
    app_log_name: str = "app",
    log_dir: Path | str = Path("./logs"),
    level: str | int = logging.DEBUG,
    enable_console: bool = True,
    prefer_rich_console: bool = True,
) -> Logger:
    return build_simple_logger(
            name=name,
            app_log_name=app_log_name,
            log_dir=log_dir,
            level=level,
            enable_console=enable_console,
            prefer_rich_console=prefer_rich_console,
        )

class StandaloneAppLogger:
    _instances: dict[str, LoggerRegistration] = {}
    _lock = Lock()

    @classmethod
    def get_logger(cls, config: StandaloneLoggerConfig | None = None) -> Logger:
        config = config or StandaloneLoggerConfig()
        cache_key = config.cache_key
        config_signature = config.config_signature

        if cache_key not in cls._instances:
            with cls._lock:
                if cache_key not in cls._instances:
                    cls._instances[cache_key] = LoggerRegistration(
                        logger=cls._create_logger(config),
                        config_signature=config_signature,
                    )

        registration = cls._instances[cache_key]
        if registration.config_signature != config_signature:
            raise ValueError(f"Logger {config.name} ja foi configurado com outra configuracao.")

        return registration.logger

    @classmethod
    def _create_logger(cls, config: StandaloneLoggerConfig) -> Logger:
        return build_project_like_logger(config)


def get_logger(config: StandaloneLoggerConfig | None = None) -> Logger:
    return StandaloneAppLogger.get_logger(config)





if __name__ == "__main__":
    logger = get_logger()

    standalone_logger = get_logger(
        StandaloneLoggerConfig(
            name="standalone_example",
            app_log_name="standalone_app",
            log_dir=Path("./logs"),
            level="DEBUG",
        )
    )
    standalone_logger.debug("Logger standalone funcionando corretamente")
    standalone_logger.info("Logger standalone funcionando corretamente")
    standalone_logger.warning("Logger standalone funcionando corretamente")
    standalone_logger.error("Logger standalone funcionando corretamente")

    simple_logger = build_simple_logger(name="standalone_simple", app_log_name="standalone_simple")
    simple_logger.info("Logger simples na raiz de logs funcionando corretamente")