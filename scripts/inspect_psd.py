"""Reopen PSDs in Photoshop and save local previews + editable layer metadata."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from amta.typeset.psd_export import find_photoshop_executable

SCRIPT = r"""
#target photoshop
function quote(s) { return '"' + s.replace(/\\/g,'\\\\').replace(/"/g,'\\"').replace(/\r/g,'\\r').replace(/\n/g,'\\n').replace(/\t/g,'\\t') + '"'; }
function json(x) {
 if(x===null) return 'null';
 if(typeof x==='string') return quote(x);
 if(typeof x==='number'||typeof x==='boolean') return String(x);
 var a=[];var k;
 if(x instanceof Array){for(k=0;k<x.length;k++)a.push(json(x[k]));return '['+a.join(',')+']';}
 for(k in x) if(x.hasOwnProperty(k)) a.push(quote(k)+':'+json(x[k]));
 return '{'+a.join(',')+'}';
}
function typeName(id) {try{return typeIDToStringID(id)||typeIDToCharID(id);}catch(e){return String(id);}}
function decode(d,list) {
 var result=list?[]:{};
 for(var i=0;i<d.count;i++) {
  var k=list?i:d.getKey(i),t=d.getType(k),v=null;
  if(t===DescValueType.BOOLEANTYPE)v=d.getBoolean(k);
  else if(t===DescValueType.STRINGTYPE)v=d.getString(k);
  else if(t===DescValueType.INTEGERTYPE)v=d.getInteger(k);
  else if(t===DescValueType.DOUBLETYPE)v=d.getDouble(k);
  else if(t===DescValueType.UNITDOUBLE)v={unit:typeName(d.getUnitDoubleType(k)),value:d.getUnitDoubleValue(k)};
  else if(t===DescValueType.ENUMERATEDTYPE)v={type:typeName(d.getEnumerationType(k)),value:typeName(d.getEnumerationValue(k))};
  else if(t===DescValueType.OBJECTTYPE)v=decode(d.getObjectValue(k),false);
  else if(t===DescValueType.LISTTYPE)v=decode(d.getList(k),true);
  if(list)result.push(v);else result[typeName(k)]=v;
 }
 return result;
}
var old = app.documents.length ? app.activeDocument : null;
var rulers = app.preferences.rulerUnits, types = app.preferences.typeUnits, dialogs = app.displayDialogs;
var doc = null, result = {};
try {
 app.preferences.rulerUnits=Units.PIXELS;app.preferences.typeUnits=TypeUnits.PIXELS;app.displayDialogs=DialogModes.NO;
 doc=app.open(new File(INPUT));
 result={version:app.version,width:doc.width.as('px'),height:doc.height.as('px'),resolution:doc.resolution,layers:[]};
 for(var i=0;i<doc.layers.length;i++){
  var layer=doc.layers[i];var row={name:layer.name,kind:String(layer.kind),visible:layer.visible};
  if(layer.kind===LayerKind.TEXT){var t=layer.textItem;row.contents=t.contents;row.font=t.font;
   row.size=t.size.as('pt');row.leading=t.leading.as('pt');row.direction=String(t.direction);
   row.justification=String(t.justification);row.position=[t.position[0].as('px'),t.position[1].as('px')];
   row.color=[t.color.rgb.red,t.color.rgb.green,t.color.rgb.blue];
   var ref=new ActionReference();ref.putIdentifier(stringIDToTypeID('layer'),layer.id);
   row.text_descriptor=decode(executeActionGet(ref).getObjectValue(stringIDToTypeID('textKey')),false);
  }
  result.layers.push(row);
 }
 doc.saveAs(new File(PREVIEW),new PNGSaveOptions(),true);
} catch(e) {result.error=String(e);}
finally {
 if(doc)doc.close(SaveOptions.DONOTSAVECHANGES);
 app.preferences.rulerUnits=rulers;app.preferences.typeUnits=types;app.displayDialogs=dialogs;
 if(old){try{app.activeDocument=old;}catch(e){}}
}
var f=new File(METADATA+'.tmp');f.encoding='UTF8';f.open('w');f.write(json(result));f.close();f.rename(new File(METADATA).name);
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    executable = find_photoshop_executable()
    if not executable:
        raise RuntimeError("Photoshop not found")
    for index, source in enumerate(args.files):
        folder = (args.output / f"{index}-{source.parent.name}").resolve()
        folder.mkdir(parents=True, exist_ok=False)
        copy = folder / "inspection.psd"
        shutil.copyfile(source, copy)
        script = SCRIPT
        for key, path in [("INPUT", copy), ("PREVIEW", folder / "preview.png"), ("METADATA", folder / "metadata.json")]:
            script = script.replace(key, json.dumps(path.as_posix(), ensure_ascii=False))
        jsx = folder / "inspect.jsx"
        jsx.write_text(script, encoding="utf-8-sig")
        subprocess.Popen([executable, "-r", str(jsx)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 300
        meta = folder / "metadata.json"
        while not meta.exists() and time.monotonic() < deadline:
            time.sleep(0.5)
        if not meta.exists():
            raise RuntimeError("Photoshop inspection timed out")
        data = json.loads(meta.read_text(encoding="utf-8-sig"))
        if "error" in data:
            raise RuntimeError(data["error"])
        print(json.dumps({"source": str(source), "layers": len(data["layers"]), "folder": str(folder)}), flush=True)
        copy.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
