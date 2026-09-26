import json

def encode(state):
    return json.dumps(state,ensure_ascii=False)
