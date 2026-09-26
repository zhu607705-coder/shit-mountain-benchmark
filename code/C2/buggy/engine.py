from cache import Cache
from operations import execute


class Engine:
    def __init__(self, nodes, aliases):
        self.nodes, self.aliases = nodes, aliases
        self.cache = Cache()
        self.active = set()

    def step(self, command):
        op = command["op"]
        if op == "set":
            self.nodes[command["name"]] = command["node"]
            self.cache.invalidate(command["name"])
        elif op == "delete":
            self.nodes.pop(command["name"], None)
        elif op == "alias":
            self.aliases[command["name"]] = command["target"]
        elif op == "unalias":
            self.aliases.pop(command["name"], None)
        else:
            try:
                return {"value": self.build(command["target"], set(command.get("cancel_at", [])))}
            except RuntimeError as exc:
                return {"error": str(exc)}
        return {"ok": True}

    def build(self, name, cancelled):
        name = self.aliases.get(name, name)
        hit = self.cache.get(name)
        if hit is not None:
            return hit
        if name not in self.nodes:
            raise RuntimeError("MISSING")
        if name in self.active:
            raise RuntimeError("CYCLE")
        self.active.add(name)
        self.cache.put(name, [])
        node = self.nodes[name]
        children = [self.build(dep, cancelled) for dep in node.get("deps", [])]
        if name in cancelled:
            raise RuntimeError("CANCELLED")
        value = execute(node, children)
        self.cache.put(name, value)
        self.active.remove(name)
        return value
