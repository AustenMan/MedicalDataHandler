import os
import time
import queue
import threading
import concurrent.futures
from typing import Any, Callable, Optional
from utils.general_utils import get_traceback

class SharedStateManager:
    """ Manages threading and multiprocessing for the application. """
    RESERVED_LC_COUNT = 4 # Withhold logical cores from the executor for the main process and threads
    
    def __init__(self, executor=None):
        """ Initializes the shared state manager. """
        # Get total logical cores, defaulting to 1 if retrieval fails
        total_logical_cores = os.cpu_count() or 1  
        
        # Determine available worker processes, ensuring at least 1 worker is always available
        self.worker_processes = max(1, total_logical_cores - self.RESERVED_LC_COUNT)
        
        # Warn if CPU resources are very low
        if total_logical_cores < self.RESERVED_LC_COUNT + 1:
            print(
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
        self._executor = executor or concurrent.futures.ProcessPoolExecutor(max_workers=self.worker_processes)
        
        # Persistent texture thread; it will continuously wait for and execute texture updates.
        self._texture_queue = queue.PriorityQueue(maxsize=3)
        self._texture_thread = threading.Thread(target=self._persistent_texture_loop, daemon=True)
        self._texture_thread.start()
        
        # Persistent action thread: it will continuously wait for and execute actions.
        self._action_queue = queue.Queue()
        self._action_thread = threading.Thread(target=self._persistent_action_thread, daemon=True)
        self._action_thread.start()
        
        # Cleanup thread
        self._cleanup_thread = None
    
    ### PERSISTENT THREAD LOOPS ###
    def _persistent_action_thread(self):
        """Persistent loop that waits for and executes actions from a queue."""
        while True:
            try:
                if self.shutdown_event.is_set():
                    break
                
                func, args, kwargs = self._action_queue.get()
                
                try:
                    if self.cleanup_event.is_set():
                        continue
                    
                    if func is None:
                        print(f"No function provided to action loop.")
                        continue
                    
                    func(*args, **kwargs)
                except Exception as e:
                    print(f"Action function error: {get_traceback(e)}")
                finally:
                    self._action_queue.task_done()
            except Exception as e:
                print(f"Action loop error: {get_traceback(e)}")
    
    def _persistent_texture_loop(self):
        """Persistent loop that renders textures from a queue."""
        while True:
            try:
                if self.shutdown_event.is_set():
                    break
                
                priority, func, args, kwargs = self._texture_queue.get()
                
                try:
                    if self.cleanup_event.is_set():
                        continue
                    
                    if func is None:
                        print(f"No function provided to texture rendering loop.")
                        continue
                    
                    func(*args, **kwargs)
                except Exception as e:
                    print(f"Texture rendering error: {get_traceback(e)}")
                finally:
                    self._texture_queue.task_done()
            except Exception as e:
                print(f"Texture render loop error: {get_traceback(e)}")
    
    ### ACTION CONTROL ###
    def add_action(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """
        Adds an action to the queue.
        
        Args:
            func: A callable function to execute. 
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.
        """
        self._action_queue.put((func, args, kwargs))
    
    def add_texture_render(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """
        Adds an action to the persistent texture thread's queue.
        
        Args:
            func: A callable function to execute. 
            *args: Positional arguments for the function. (ex: texture_action_type (str) is one of "reset", "initialize", or "update")
            **kwargs: Keyword arguments for the function.
        """
        action_type = kwargs.get("texture_action_type", "update")
        
        try:
            if action_type == "reset": # Highest priority
                self._texture_queue.put((0, func, args, kwargs), timeout=0.1)
            elif action_type == "initialize": # Second highest priority
                self._texture_queue.put((1, func, args, kwargs))
            else: # Update (default) - Lowest priority
                self._texture_queue.put((2, func, args, kwargs))
        except queue.Full:
            pass
    
    def add_executor_action(self, func: Optional[Callable[..., Any]], *args: Any, **kwargs: Any) -> Optional[concurrent.futures.Future]:
        """
        Submits an action to the executor.
        
        Args:
            func: A callable function to execute. 
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.
        
        Returns:
            A Future representing the execution of the action, or None if the cleanup event is cleared
            or if no function (or valid default) is provided.
        """
        if self.shutdown_event.is_set() or self.cleanup_event.is_set():
            return None
        
        if func is None:
            print(f"No function provided to add to the executor.")
            return None

        try:
            return self._executor.submit(func, *args, **kwargs)
        except Exception as e:
            print(f"Failed to submit function: {get_traceback(e)}")
            return None
    
    def is_action_in_queue(self) -> bool:
        """ Returns whether any action is in the queue. """
        if self._executor is not None:
            with self._executor._shutdown_lock:
                is_executor_busy = len(self._executor._pending_work_items) > 0
        else:
            is_executor_busy = False
        
        with self.thread_lock:
            does_action_thread_exist = self._action_thread is not None and self._action_thread.is_alive()
            does_texture_thread_exist = self._texture_thread is not None and self._texture_thread.is_alive()
        
        is_action_in_progress = self.action_event.is_set() or (does_action_thread_exist and not self._action_queue.empty())
        is_texture_busy = does_texture_thread_exist and not self._texture_queue.empty()
        
        return is_action_in_progress or is_executor_busy or is_texture_busy
    
    ### CLEANUP COTNROL ###
    def is_cleanup_thread_alive(self) -> bool:
        """ Returns whether the cleanup thread is alive. """
        return (self._cleanup_thread is not None and self._cleanup_thread.is_alive()) or self.cleanup_event.is_set()
    
    def start_cleanup_thread(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """ 
        Starts a cleanup thread. 
        
        Args:
            func: A callable function to execute. 
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.
        """
        def cleanup_action():
            """ """
            print("Cleanup starting, please wait...")
            
            # Ensure the cleanup event is set to block actions
            self.cleanup_event.set()
            
            # Wait for actions to complete
            while self.is_action_in_queue():
                time.sleep(0.1)
            
            # Ensure the data loading event is set to block data loading
            self.action_event.set()
            
            # Call the provided function with its arguments
            with self.thread_lock:
                func(*args, **kwargs)
            
            # Clear the cleanup event to allow actions and the data loading event to allow data loading
            self.cleanup_event.clear()
            self.action_event.clear()
            
            print("Cleanup complete. Previous data and actions were cleared.")
        
        # Cleanup first then the run the func
        self._cleanup_thread = threading.Thread(target=cleanup_action, daemon=True)
        self._cleanup_thread.start()
    
    ### SHUTDOWN CONTROL ###
    def shutdown_manager(self, timeout=5.0) -> None:
        """ Shuts down the shared state manager. """
        self.shutdown_event.set()
        
        # Kill the threads
        for thread in [self._action_thread, self._texture_thread, self._cleanup_thread]:
            if thread is not None and thread.is_alive():
                thread.join(timeout=timeout)
            thread = None
        
        # Shutdown the executor
        if self._executor:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None
