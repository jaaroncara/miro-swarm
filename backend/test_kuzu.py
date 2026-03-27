import kuzu
db = kuzu.Database("data/kuzu_db/mirofish_ebbdeb4190f24b7d/graph.kuzu")
conn = kuzu.Connection(db)
res = conn.execute("CALL show_tables() RETURN *").get_next()
print("Tables:")
while res:
    print(res)
    res = conn.execute("CALL show_tables() RETURN *").get_next()
