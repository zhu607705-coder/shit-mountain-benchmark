"""Independent rebuild-from-current-state oracle, with no persistent cache."""
import copy


class Fault(Exception):
    pass


class Engine:
    def __init__(self, nodes, aliases):
        self.nodes, self.aliases = copy.deepcopy(nodes), dict(aliases)

    def step(self, command):
        kind = command["op"]
        if kind == "set":
            self.nodes[command["name"]] = copy.deepcopy(command["node"])
        elif kind == "delete":
            self.nodes.pop(command["name"], None)
        elif kind == "alias":
            self.aliases[command["name"]] = command["target"]
        elif kind == "unalias":
            self.aliases.pop(command["name"], None)
        else:
            try:
                values = self._evaluate(command["target"], set(), {}, set(command.get("cancel_at", [])))
                return {"value": list(values)}
            except Fault as exc:
                return {"error": str(exc)}
        return {"ok": True}

    def _evaluate(self, name, ancestors, memo, cancelled):
        alias_path = set()
        while name in self.aliases:
            if name in alias_path:
                raise Fault("ALIAS_CYCLE")
            alias_path.add(name)
            name = self.aliases[name]
        if name not in self.nodes:
            raise Fault("MISSING")
        if name in ancestors:
            raise Fault("CYCLE")
        if name in memo:
            return memo[name]
        node = self.nodes[name]
        children = [self._evaluate(dep, ancestors | {name}, memo, cancelled)
                    for dep in node.get("deps", [])]
        if name in cancelled:
            raise Fault("CANCELLED")
        operation = node["op"]
        if operation == "input":
            answer = tuple(node["data"])
        elif operation == "concat":
            answer = tuple(element for child in children for element in child)
        elif operation == "sum":
            length = max(map(len, children), default=0)
            answer = tuple(sum(child[i] for child in children if i < len(child)) for i in range(length))
        elif operation == "sort":
            answer = tuple(sorted(element for child in children for element in child))
        elif operation == "unique":
            answer = tuple(sorted({element for child in children for element in child}))
        elif operation == "scale":
            answer = tuple(node["factor"] * element for child in children for element in child)
        elif operation == "fail":
            raise Fault("FAILED")
        else:
            raise Fault("OP")
        memo[name] = answer
        return answer
