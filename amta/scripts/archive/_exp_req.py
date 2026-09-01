import json
import os
baseB = "E:/manga translator agent/amta-wt-b/workspace/touhou-single-wing/artifacts"
baseA = "E:/manga translator agent/amta-wt-a/workspace/touhou-single-wing/artifacts"
def req_stats(p):
    s = {"lt":0,"gc":0,"li":0,"rounds":0,"calls":0,"len":0}
    if not os.path.exists(p): return s
    doc = json.load(open(p,encoding="utf-8")); entries = doc.get("trace",[]) if isinstance(doc,dict) else doc
    for e in entries:
        calls = e.get("tool_calls") or []
        if calls: s["rounds"]+=1
        for c in calls:
            n=c.get("name","")
            if n=="lookup_term": s["lt"]+=1
            elif n=="get_context": s["gc"]+=1
            elif n=="lookup_image": s["li"]+=1
        s["calls"]+=1
        s["len"]+=len(e.get("content") or "")
    return s
for grp,base in [("B",baseB),("A",baseA)]:
    print("===== GROUP", grp, "=====")
    for n in (11,12):
        page="page_%d"%n
        s=req_stats(os.path.join(base,page+"_trace.json"))
        print("  %s: LLM_calls=%d rounds=%d req_lookup_image=%d text_len=%d" % (page, s["calls"], s["rounds"], s["li"], s["len"]))