import hashlib,json

def key_for(node,dep_stats):
    return hashlib.md5(json.dumps([node.get('op'),sorted(dep_stats)],sort_keys=True).encode()).hexdigest()
