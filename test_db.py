import sys, os
sys.path.insert(0, os.path.abspath('backend'))
from app.services.graph_builder import GraphBuilderService

builder = GraphBuilderService()
print("base_path:", builder.db.base_path)
storage = builder.db.get_storage("mirofish_ebbdeb4190f24b7d")
print("Storage class:", type(storage))
if hasattr(storage, 'db_path'):
    print("db_path:", storage.db_path)
if hasattr(storage, 'data_dir'):
    print("data_dir:", storage.data_dir)
print("Nodes:", len(storage.list_nodes()))
print("Edges:", len(storage.get_edges()))
