from collections import defaultdict


class Projection:
    def __init__(self):
        self.amounts = defaultdict(float)
        self.status = {}

    def apply_post(self, event, factor=1):
        for account, amount in event["entries"]:
            self.amounts[(event["tenant"], account)] += float(amount) * factor
        self.status[(event["tenant"], event["id"])] = "ACTIVE" if factor == 1 else "REVERSED"

    def reverse(self, event, store):
        target = store.get(event["tenant"], event["target"])
        if target and target["kind"] == "post":
            self.apply_post(target, -1)
            self.status[(event["tenant"], event["id"])] = "APPLIED"
        else:
            self.status[(event["tenant"], event["id"])] = "ORPHAN"

    def export(self):
        return {"balances": [[t, a, int(v)] for (t, a), v in sorted(self.amounts.items()) if v],
                "statuses": [[t, i, s] for (t, i), s in sorted(self.status.items())]}
