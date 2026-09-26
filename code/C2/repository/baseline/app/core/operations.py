"""Pure vector operators. All cache values are immutable tuples."""


class BuildFault(Exception):
    pass


def execute(node, children):
    operation = node["op"]
    if operation == "input":
        return tuple(node["data"])
    if operation == "sum":
        output = [0] * max((len(child) for child in children), default=0)
        for child in children:
            for index, value in enumerate(child):
                output[index] += value
        return tuple(output)
    values = [value for child in children for value in child]
    if operation == "concat":
        return tuple(values)
    if operation == "scale":
        return tuple(value * node["factor"] for value in values)
    if operation == "sort":
        return tuple(sorted(values))
    if operation == "unique":
        return tuple(sorted(set(values)))
    raise BuildFault("FAILED" if operation == "fail" else "OP")
