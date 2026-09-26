"""Event payload validation; envelopes are guaranteed by the input contract."""


def valid(event):
    kind = event["kind"]
    if kind == "reverse":
        return (set(event) == {"tenant", "id", "kind", "target"}
                and isinstance(event["target"], str) and event["target"] != "")
    if kind != "post" or set(event) != {"tenant", "id", "kind", "entries"}:
        return False
    entries = event["entries"]
    if not isinstance(entries, list) or len(entries) < 2:
        return False
    total = 0
    for entry in entries:
        if not isinstance(entry, list) or len(entry) != 2:
            return False
        account, amount = entry
        if not isinstance(account, str) or not account:
            return False
        if type(amount) is not int or not -10**12 <= amount <= 10**12:
            return False
        total += amount
    return total == 0
