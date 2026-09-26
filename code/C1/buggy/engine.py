from storage import Store
from projection import Projection


def solve(events):
    store, projection = Store(), Projection()
    for event in events:
        if not store.append(event):
            continue
        if event["kind"] == "post":
            projection.apply_post(event)
        elif event["kind"] == "reverse":
            projection.reverse(event, store)
        else:
            projection.status[(event["tenant"], event["id"])] = "INVALID"
    return projection.export()
