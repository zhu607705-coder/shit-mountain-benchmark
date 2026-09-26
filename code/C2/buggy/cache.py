"""Cache from an older single-graph implementation."""
class Cache:
    entries = {}

    def get(self, name):
        return self.entries.get(name)

    def put(self, name, value):
        self.entries[name] = value

    def invalidate(self, name):
        self.entries.pop(name, None)
