"""Independent batch relational specification; never imports the submission."""
import json
from collections import defaultdict


def classify(event):
    if event["kind"] == "post":
        if set(event) != {"tenant", "id", "kind", "entries"}:
            return False
        rows = event["entries"]
        if not isinstance(rows, list) or len(rows) < 2:
            return False
        for row in rows:
            if not isinstance(row, list) or len(row) != 2:
                return False
            account, amount = row
            if not isinstance(account, str) or not account:
                return False
            if type(amount) is not int or abs(amount) > 10**12:
                return False
        return sum(row[1] for row in rows) == 0
    return (
        event["kind"] == "reverse"
        and set(event) == {"tenant", "id", "kind", "target"}
        and isinstance(event["target"], str)
        and bool(event["target"])
    )


def solve(events):
    # Oracle intentionally materializes full JSON variants then performs joins.
    relation = defaultdict(set)
    for event in events:
        relation[(event["tenant"], event["id"])].add(
            json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        )
    unique = {
        key: json.loads(next(iter(payloads)))
        for key, payloads in relation.items() if len(payloads) == 1
    }
    valid = {key: event for key, event in unique.items() if classify(event)}
    posts = {key: event for key, event in valid.items() if event["kind"] == "post"}
    reversals = {key: event for key, event in valid.items() if event["kind"] == "reverse"}
    targets = {(key[0], event["target"]) for key, event in reversals.items()}
    statuses = []
    for tenant, identity in sorted(relation):
        key = tenant, identity
        if len(relation[key]) != 1:
            status = "CONFLICT"
        elif key not in valid:
            status = "INVALID"
        elif key in posts:
            status = "REVERSED" if key in targets else "ACTIVE"
        else:
            status = "APPLIED" if (tenant, valid[key]["target"]) in posts else "ORPHAN"
        statuses.append([tenant, identity, status])
    terms = defaultdict(list)
    for key in posts.keys() - targets:
        for account, amount in posts[key]["entries"]:
            terms[(key[0], account)].append(amount)
    balances = [[tenant, account, sum(terms[(tenant, account)])]
                for tenant, account in sorted(terms) if sum(terms[(tenant, account)])]
    return {"balances": balances, "statuses": statuses}
