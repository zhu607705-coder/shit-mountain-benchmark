"""Historical event store. Public IDs were assumed to be globally unique."""
class Store:
    def __init__(self):
        self.records = {}

    def append(self, event):
        identity = event["id"]
        if identity in self.records:
            return False
        self.records[identity] = event
        return True

    def get(self, tenant, identity):
        return self.records.get(identity)
