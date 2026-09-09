from amta.translation.translate import translate_plain
import inspect
src = inspect.getsource(translate_plain)
print("import OK")
print("retry loop:", "FOUND" if "for _ in range" in src else "removed")
print("binary split:", "FOUND" if "mid = len" in src else "removed")
print("punct retry:", "FOUND" if "_SENTENCE_END" in src else "removed")
print("mechanical_guardrails:", "FOUND" if "mechanical_guardrails" in src else "removed")
