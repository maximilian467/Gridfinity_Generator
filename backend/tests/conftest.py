import os
import tempfile

# Muss vor dem Import der App passieren (auch Worker-Prozesse erben die Variable)
os.environ["GRIDFINITY_DATA"] = tempfile.mkdtemp(prefix="gridfinity_test_")
