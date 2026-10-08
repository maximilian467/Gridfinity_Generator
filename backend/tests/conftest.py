import os
import tempfile

# Muss vor dem Import der App passieren (auch Worker-Prozesse erben die Variablen)
os.environ["GRIDFINITY_DATA"] = tempfile.mkdtemp(prefix="gridfinity_test_")
os.environ.setdefault("AUTH_DISABLED", "1")       # test_security.py schaltet den Login gezielt ein
