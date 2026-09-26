class Snapshot:
    def __init__(self,data,version):self._data=data;self.version=version
    def get(self,key):return self._data.get(key)
    def scan(self,prefix=''):return [(k,v) for k,v in self._data.items() if k.startswith(prefix)]
