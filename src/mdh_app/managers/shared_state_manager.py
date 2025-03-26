import logging
import queue
import threading
import concurrent.futures
from os import cpu_count
from time import sleep
from typing import Any, Callable, Optional

from mdh_app.utils.general_utils import get_traceback, get_callable_name

logger = logging.getLogger(__name__)

class SharedStateManager:
    """ Manages threading and multiprocessing for the application. """
    RESERVED_LC_COUNT = 4 # Withhold logical cores from the executor for the main process and threads
    
    def __init__(self) -> None:
        """ Initializes the shared state manager. """
        # Get total logical cores, defaulting to 1 if retrieval fails
        total_logical_cores = cpu_count() or 1  
        
        # Determine available workers, ensuring at least 1 worker is always available
        self.num_workers = max(1, total_logical_cores - self.RESERVED_LC_COUNT)
        
        # Warn if CPU resources are very low
        if total_logical_cores < self.RESERVED_LC_COUNT + 1:
            logger.info(
                f"Warning: Only {total_logical_cores} logical cores detected but "
                f">={self.RESERVED_LC_COUNT + 1} is recommended for optimal performance. "
                "Your system may experience performance issues due to limited CPU resources."
            )
        
        # Signal whether an action is in progress. Set will block new actions. Clear will allow new actions.
        self.action_event = threading.Event()
        self.action_event.clear()
        
        # Signal cleanup in progress. Set will cancel all actions and perform cleanup. Clear will allow new actions.
        self.cleanup_event = threading.Event()
        self.cleanup_event.clear() 
        
        # Signal event for program shutdown. Set will finish cleanup/exit. Clear will allow program to run.
        self.shutdown_event = threading.Event()
        self.shutdown_event.clear() # Set to shutdown
        
        # Thread lock
        self.thread_lock = threading.Lock()
        
        # Executor
        self._executor: Optional[concurrent.futures.Executor] = None
        
        # Persistent texture thread; it will continuously wait for and execute texture updates.
        self._texture_pending: dict[int, tuple[Callable, tuple, dict]] = {}
        self._texture_lock = threading.Lock()
        self._texture_thread = threading.Thread(target=self._persistent_texture_loop, daemon=True)
        self._texture_thread.start()
        
        # Persistent action thread: it will continuously wait for and execute actions.
        self._action_queue = queue.Queue(maxsize=1)
        self._action_thread = threading.Thread(target=self._persistent_action_loop, daemon=True)
        self._action_thread.start()
    
    ### PERSISTENT THREAD LOOPS ###
    def _persistent_action_loop(self) -> None:
        """Persistent loop that waits for and executes actions from a queue."""
        while not self.shutdown_event.is_set():
            try:
                func, args, kwargs = self._action_queue.get()
            except queue.Empty:
                continue
            
            self.action_event.set()
            try:
                if not self.cleanup_event.is_set():
                    func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Failed to perform '{get_callable_name(func)}'." + get_traceback(e))
            finally:
                self.action_event.clear()
                self._action_queue.task_done()
    
    def _persistent_texture_loop(self) -> None:
        """Persistent loop that renders textures from a queue."""
        while not self.shutdown_event.is_set():
            # Wait to render if cleanup is in progress
            if self.cleanup_event.is_set():
                continue
            
            task = None
            with self._texture_lock:
                if self._texture_pending:
                    # Get the highest priority pending task
                    priority = min(self._texture_pending.keys())
                    task = self._texture_pending.pop(priority)
            
            if task is None:
                sleep(1/60)
                continue
            
            func, args, kwargs = task
            try:
                func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Failed to render the texture using '{get_callable_name(func)}'." + get_traceback(e))
    
    ### ACTION CONTROL ###
    def submit_action(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """Attempts to submit an action."""
        if self.shutdown_event.is_set():
            logger.info(f"'{get_callable_name(func)}' was not performed because program is shutting down.")
        elif self.shutdown_event.is_set():
            logger.info(f"'{get_callable_name(func)}' was not performed because cleanup is in progress.")
        elif self.action_event.is_set():
            logger.info(f"'{get_callable_name(func)}' was not performed because another action is in progress.")
        else:
            try:
                self._action_queue.put_nowait((func, args, kwargs))
            except queue.Full:
                logger.info(f"'{get_callable_name(func)}' was not performed because an action is already in progress; try again afterwards.")
    
    def submit_texture_update(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """
        Submits a texture update, replacing any pending task at the same priority level.
        Priorities:
            0 - reset, 1 - initialize, 2 - update (default).
        """
        if self.shutdown_event.is_set():
            logger.info(f"'{get_callable_name(func)}' was not performed because program shutdown in progress.")
            return

        action_type = kwargs.get("texture_action_type", "update")
        priority = {"reset": 0, "initialize": 1, "update": 2}.get(action_type, 2)

        with self._texture_lock:
            self._texture_pending[priority] = (func, args, kwargs)
    
    def submit_executor_action(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Optional[concurrent.futures.Future]:
        """Submits an action to the executor if available. Returns a Future or None on failure."""
        if self.shutdown_event.is_set():
            logger.info(f"Executor '{get_callable_name(func)}' was not performed because program is shutting down.")
        elif self.shutdown_event.is_set():
            logger.info(f"Executor '{get_callable_name(func)}' was not performed because cleanup is in progress.")
        elif self._executor is None:
            logger.info("Executor action was not performed because the executor does not exist. It must be started first.")
        else:
            try:
                return self._executor.submit(func, *args, **kwargs)
            except Exception as e:
                logger.error(f"Submission failed for executor '{get_callable_name(func)}'." + get_traceback(e))
        return None
    
    def startup_executor(self, use_process_pool: bool = False, max_workers: Optional[int] = None) -> None:
        """Starts an executor (thread or process pool)."""
        if self._executor is not None:
            logger.debug("Executor already running; shutting down previous executor.")
            self.shutdown_executor()
        workers = max(min(self.num_workers, max_workers or self.num_workers), 1)
        if use_process_pool:
            self._executor = concurrent.futures.ProcessPoolExecutor(max_workers=workers)
        else:
            self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    
    def is_action_in_progress(self) -> bool:
        """Returns True if an action is queued or running."""
        return self.action_event.is_set() or self._executor is not None or not self._action_queue.empty()
    
    ### CLEANUP COTNROL ###
    def start_cleanup(self, cleanup_func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """Starts the cleanup process."""
        threading.Thread(target=cleanup_func, daemon=True).start()
    
    ### SHUTDOWN CONTROL ###
    def shutdown_executor(self) -> None:
        """ Shuts down the executor. """
        if self._executor:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None
    
    def shutdown_manager(self, timeout=5.0) -> None:
        """ Shuts down the shared state manager. """
        self.shutdown_event.set()
        
        # Kill the threads
        for thread in [self._action_thread, self._texture_thread]:
            if thread is not None and thread.is_alive():
                thread.join(timeout=timeout)
        
        # Shutdown the executor
        self.shutdown_executor()
