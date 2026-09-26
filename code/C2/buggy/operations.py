def execute(node, children):
    op = node["op"]
    if op == "input":
        return node["data"]
    merged = [x for child in children for x in child]
    if op == "concat":
        return merged
    if op == "sum":
        return [sum(row) for row in zip(*children)]
    if op == "sort":
        return sorted(merged)
    if op == "unique":
        return list(set(merged))
    if op == "scale":
        return [x * node["factor"] for x in merged]
    raise RuntimeError("FAILED" if op == "fail" else "OP")
