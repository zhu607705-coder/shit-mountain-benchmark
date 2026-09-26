"""Per-engine last-success cache. Versions make transitive changes observable."""
class Cache:
    def __init__(self):
        self.entries = {}
        self.clock = 0

    def lookup(self, name, signature):
        entry = self.entries.get(name)
        return entry if entry is not None and entry[0] == signature else None

    def store(self, name, signature, value):
        self.clock += 1
        entry = signature, value, self.clock
        self.entries[name] = entry
        return entry

    def forget(self, name):
        self.entries.pop(name, None)
