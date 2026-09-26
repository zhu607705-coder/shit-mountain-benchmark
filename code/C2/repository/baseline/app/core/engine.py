"""Incremental evaluator: validate current graph on every build, reuse pure work."""
import copy
from .cache import Cache
from .operations import BuildFault, execute


class Engine:
    def __init__(self, nodes, aliases):
        self.nodes = copy.deepcopy(nodes)
        self.aliases = dict(aliases)
        self.revisions = {name: 0 for name in nodes}
        self.clock = 0
        self.cache = Cache()

    def step(self, command):
        operation = command["op"]
        if operation == "set":
            name = command["name"]
            self.nodes[name] = copy.deepcopy(command["node"])
            self.clock += 1
            self.revisions[name] = self.clock
        elif operation == "delete":
            name = command["name"]
            self.nodes.pop(name, None)
            self.revisions.pop(name, None)
            self.cache.forget(name)
        elif operation == "alias":
            self.aliases[command["name"]] = command["target"]
        elif operation == "unalias":
            self.aliases.pop(command["name"], None)
        else:
            try:
                entry = self._visit(command["target"], set(), {}, set(command.get("cancel_at", [])))
                return {"value": list(entry[1])}
            except BuildFault as exc:
                return {"error": str(exc)}
        return {"ok": True}

    def _resolve(self, name):
        visited = set()
        while name in self.aliases:
            if name in visited:
                raise BuildFault("ALIAS_CYCLE")
            visited.add(name)
            name = self.aliases[name]
        return name

    def _visit(self, requested, active, memo, cancelled):
        name = self._resolve(requested)
        if name not in self.nodes:
            raise BuildFault("MISSING")
        if name in active:
            raise BuildFault("CYCLE")
        if name in memo:
            return memo[name]
        active.add(name)
        try:
            node = self.nodes[name]
            children = [self._visit(dep, active, memo, cancelled) for dep in node.get("deps", [])]
            if name in cancelled:
                raise BuildFault("CANCELLED")
            signature = self.revisions[name], tuple(child[2] for child in children)
            entry = self.cache.lookup(name, signature)
            if entry is None:
                value = execute(node, [child[1] for child in children])
                entry = self.cache.store(name, signature, value)
            memo[name] = entry
            return entry
        finally:
            active.remove(name)
