import collections
import os

from xue.ansi import C


class PluginHook:
    def __init__(self):
        self._handlers = collections.defaultdict(list)

    def register(self, event, handler):
        self._handlers[event].append(handler)

    def emit(self, event, **kwargs):
        for handler in self._handlers.get(event, []):
            try:
                handler(**kwargs)
            except Exception:
                pass


class PluginManager:
    EVENTS = ["on_start", "on_page", "on_link", "on_error", "on_stop", "on_domain_discovered"]

    def __init__(self):
        self.hooks = {event: PluginHook() for event in self.EVENTS}
        self.plugins = []

    def register(self, event, handler):
        if event in self.hooks:
            self.hooks[event].register(event, handler)

    def emit(self, event, **kwargs):
        if event in self.hooks:
            self.hooks[event].emit(event, **kwargs)

    def load_from_directory(self, plugin_dir):
        if not os.path.isdir(plugin_dir):
            return
        import importlib.util
        for filename in os.listdir(plugin_dir):
            if filename.endswith(".py") and not filename.startswith("_"):
                filepath = os.path.join(plugin_dir, filename)
                try:
                    spec = importlib.util.spec_from_file_location(filename[:-3], filepath)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    if hasattr(module, "register"):
                        module.register(self)
                        self.plugins.append(filename[:-3])
                        print(f"  {C.GREEN}[+]{C.RST} Plugin loaded: {filename[:-3]}")
                except Exception as e:
                    print(f"  {C.RED}[!]{C.RST} Failed to load plugin {filename}: {e}")
