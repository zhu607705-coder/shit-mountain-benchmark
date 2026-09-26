"""Two-phase identity quarantine followed by an integer-only projection."""
import json
from collections import defaultdict
from validation import valid


def solve(events):
    identities = {}
    conflicts = set()
    for event in events:
        key = event["tenant"], event["id"]
        if key in conflicts:
            continue
        # JSON number spelling matters: true, 1 and 1.0 are distinct payloads.
        token = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        previous = identities.get(key)
        if previous is None:
            identities[key] = (token, event)
        elif previous[0] != token:
            conflicts.add(key)

    usable, states = {}, {}
    for key, (_, event) in identities.items():
        if key in conflicts:
            states[key] = "CONFLICT"
        elif not valid(event):
            states[key] = "INVALID"
        else:
            usable[key] = event
    suppressed = set()
    for key, event in usable.items():
        if event["kind"] == "reverse":
            target = (key[0], event["target"])
            if target in usable and usable[target]["kind"] == "post":
                suppressed.add(target)
                states[key] = "APPLIED"
            else:
                states[key] = "ORPHAN"

    balances = defaultdict(int)
    for key, event in usable.items():
        if event["kind"] == "post":
            states[key] = "REVERSED" if key in suppressed else "ACTIVE"
            if key not in suppressed:
                for account, amount in event["entries"]:
                    balances[(key[0], account)] += amount
    return {"balances": [[t, a, value] for (t, a), value in sorted(balances.items()) if value],
            "statuses": [[t, i, status] for (t, i), status in sorted(states.items())]}
