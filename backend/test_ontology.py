import sys, os
from dotenv import load_dotenv
load_dotenv("../.env")
sys.path.insert(0, os.path.abspath("."))
from app.services.ontology_generator import OntologyGenerator

try:
    generator = OntologyGenerator()
    texts = ["Test document with some business details. The sales team should increase quotas by 10%."]
    result = generator.generate(
        document_texts=texts,
        simulation_requirement="Simulate the business outcome."
    )
    print("SUCCESS")
    print(result)
except Exception as e:
    import traceback
    traceback.print_exc()
    print("Failed test ontology:", str(e))
