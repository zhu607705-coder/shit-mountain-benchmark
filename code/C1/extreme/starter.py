"""Faulty stage-v2 implementation: durable receipts are scoped to a physical epoch."""
import json
from pathlib import Path
import sqlite3


class Connection(sqlite3.Connection):
    def __exit__(self,*args):
        try:return super().__exit__(*args)
        finally:self.close()


class Ledger:
    def __init__(self,root):
        root=Path(root);root.mkdir(parents=True,exist_ok=True);self.path=root/'ledger.sqlite3'
        with self.connect() as c:
            c.executescript('CREATE TABLE IF NOT EXISTS routes(name TEXT PRIMARY KEY,epoch INTEGER);'
                'CREATE TABLE IF NOT EXISTS balances(name TEXT,epoch INTEGER,amount INTEGER,PRIMARY KEY(name,epoch));'
                'CREATE TABLE IF NOT EXISTS receipts(source TEXT,epoch INTEGER,txid TEXT,payload TEXT,result TEXT,PRIMARY KEY(source,epoch,txid));')
    def connect(self):return sqlite3.connect(self.path,timeout=5,factory=Connection)
    def open_account(self,name,balance):
        with self.connect() as c:
            c.execute('INSERT INTO routes VALUES(?,0)',(name,));c.execute('INSERT INTO balances VALUES(?,0,?)',(name,balance))
    def migrate(self,name):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE');epoch=c.execute('SELECT epoch FROM routes WHERE name=?',(name,)).fetchone()[0]
            value=c.execute('SELECT amount FROM balances WHERE name=? AND epoch=?',(name,epoch)).fetchone()[0]
            c.execute('INSERT INTO balances VALUES(?,?,?)',(name,epoch+1,value));c.execute('UPDATE routes SET epoch=? WHERE name=?',(epoch+1,name))
        return epoch+1
    def transfer(self,txid,source,target,amount,hook=None):
        payload=json.dumps([source,target,amount]);result={'txid':txid,'amount':amount}
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE');se=c.execute('SELECT epoch FROM routes WHERE name=?',(source,)).fetchone()[0]
            te=c.execute('SELECT epoch FROM routes WHERE name=?',(target,)).fetchone()[0]
            row=c.execute('SELECT payload,result FROM receipts WHERE source=? AND epoch=? AND txid=?',(source,se,txid)).fetchone()
            if row:
                if row[0]!=payload:raise ValueError('request conflict')
                return json.loads(row[1])
            balance=c.execute('SELECT amount FROM balances WHERE name=? AND epoch=?',(source,se)).fetchone()[0]
            if type(amount) is not int or amount<0 or balance<amount:raise ValueError('invalid transfer')
            c.execute('UPDATE balances SET amount=amount-? WHERE name=? AND epoch=?',(amount,source,se))
            c.execute('UPDATE balances SET amount=amount+? WHERE name=? AND epoch=?',(amount,target,te))
            c.execute('INSERT INTO receipts VALUES(?,?,?,?,?)',(source,se,txid,payload,json.dumps(result)))
        if hook:hook('after_commit')
        return result
    def snapshot(self):
        with self.connect() as c:return dict(c.execute('SELECT b.name,b.amount FROM balances b JOIN routes r ON b.name=r.name AND b.epoch=r.epoch'))
