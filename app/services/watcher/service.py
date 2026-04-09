import time
import os
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class HotFolderHandler(FileSystemEventHandler):
    def __init__(self, callback):
        self.callback = callback
        self.processing_paths = set()

    def on_created(self, event):
        # Ignoramos archivos ocultos o temporales
        if os.path.basename(event.src_path).startswith('.'):
            return
            
        # Damos un pequeño margen para que el archivo/carpeta termine de copiarse
        # En producción esto se manejaría comprobando si el archivo está bloqueado
        path = event.src_path
        if path not in self.processing_paths:
            self.processing_paths.add(path)
            # Lanzamos en un hilo para no bloquear el observer
            threading.Thread(target=self._delayed_callback, args=(path,)).start()

    def _delayed_callback(self, path):
        time.sleep(2)  # Wait for file copy to complete
        try:
            self.callback(path)
        finally:
            if path in self.processing_paths:
                self.processing_paths.remove(path)

class WatcherService:
    def __init__(self, hot_folder_path: str, callback):
        self.hot_folder_path = hot_folder_path
        self.callback = callback
        self.observer = Observer()

    def start(self):
        os.makedirs(self.hot_folder_path, exist_ok=True)
        event_handler = HotFolderHandler(self.callback)
        self.observer.schedule(event_handler, self.hot_folder_path, recursive=False)
        self.observer.start()

    def stop(self):
        self.observer.stop()
        self.observer.join()
