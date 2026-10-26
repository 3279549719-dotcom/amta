"""Batch text-layer creation while retaining Photoshop DOM typography defaults."""

TEXT_DEFAULTS = r"""
// Capture DOM defaults once: raw ActionDescriptor defaults differ (notably anti-aliasing).
var seedLayer = doc.artLayers.add(); seedLayer.kind = LayerKind.TEXT;
var seedRef = new ActionReference(); seedRef.putIdentifier(stringIDToTypeID('layer'), seedLayer.id);
var seedText = executeActionGet(seedRef).getObjectValue(stringIDToTypeID('textKey'));
seedLayer.remove();
function copyDescriptor(value) {
    var copy = new ActionDescriptor(); copy.fromStream(value.toStream()); return copy;
}
"""

TEXT_LAYER = r"""
    // 文字层 {index}: {name}
    var dpiScale{index} = 72 / doc.resolution;
    var fontPS{index} = findFontPostScriptName('{font_family}');
    var mk{index} = new ActionDescriptor();
    var ref{index} = new ActionReference();
    ref{index}.putClass(stringIDToTypeID('textLayer'));
    mk{index}.putReference(charIDToTypeID('null'), ref{index});
    var text{index} = new ActionDescriptor();
    text{index}.putEnumerated(stringIDToTypeID('antiAlias'),stringIDToTypeID('antiAliasType'),seedText.getEnumerationValue(stringIDToTypeID('antiAlias')));
    text{index}.putString(stringIDToTypeID('textKey'), '{text}');
    text{index}.putEnumerated(stringIDToTypeID('orientation'), stringIDToTypeID('orientation'),
        stringIDToTypeID({direction} === Direction.VERTICAL ? 'vertical' : 'horizontal'));
    var click{index} = new ActionDescriptor();
    click{index}.putUnitDouble(stringIDToTypeID('horizontal'), charIDToTypeID('#Prc'), {x} / doc.width.as('px') * 100);
    click{index}.putUnitDouble(stringIDToTypeID('vertical'), charIDToTypeID('#Prc'), {y} / doc.height.as('px') * 100);
    text{index}.putObject(stringIDToTypeID('textClickPoint'), stringIDToTypeID('paint'), click{index});
    var style{index} = copyDescriptor(seedText.getList(stringIDToTypeID('textStyleRange')).getObjectValue(0).getObjectValue(stringIDToTypeID('textStyle')));
    if(fontPS{index}) style{index}.putString(stringIDToTypeID('fontPostScriptName'), fontPS{index});
    style{index}.putUnitDouble(stringIDToTypeID('size'), charIDToTypeID('#Pnt'), {font_size} * dpiScale{index});
    style{index}.putUnitDouble(stringIDToTypeID('impliedFontSize'), charIDToTypeID('#Pnt'), {font_size} * dpiScale{index});
    style{index}.putBoolean(stringIDToTypeID('autoLeading'), false);
    style{index}.putUnitDouble(stringIDToTypeID('leading'), charIDToTypeID('#Pnt'), {leading} * dpiScale{index});
    var color{index} = new ActionDescriptor();
    color{index}.putDouble(stringIDToTypeID('red'), {color_r});
    color{index}.putDouble(stringIDToTypeID('green'), {color_g});
    color{index}.putDouble(stringIDToTypeID('blue'), {color_b});
    style{index}.putObject(stringIDToTypeID('color'), stringIDToTypeID('RGBColor'), color{index});
    var range{index} = new ActionDescriptor();
    range{index}.putInteger(stringIDToTypeID('from'), 0);
    range{index}.putInteger(stringIDToTypeID('to'), '{text}'.length);
    range{index}.putObject(stringIDToTypeID('textStyle'), stringIDToTypeID('textStyle'), style{index});
    var styles{index} = new ActionList();
    styles{index}.putObject(stringIDToTypeID('textStyleRange'), range{index});
    text{index}.putList(stringIDToTypeID('textStyleRange'), styles{index});
    var para{index} = copyDescriptor(seedText.getList(stringIDToTypeID('paragraphStyleRange')).getObjectValue(0).getObjectValue(stringIDToTypeID('paragraphStyle')));
    para{index}.putEnumerated(stringIDToTypeID('align'), stringIDToTypeID('alignmentType'),
        stringIDToTypeID({justification} === Justification.CENTER ? 'center' : ({justification} === Justification.RIGHT ? 'right' : 'left')));
    var prange{index} = new ActionDescriptor();
    prange{index}.putInteger(stringIDToTypeID('from'),0);
    prange{index}.putInteger(stringIDToTypeID('to'),'{text}'.length);
    prange{index}.putObject(stringIDToTypeID('paragraphStyle'),stringIDToTypeID('paragraphStyle'),para{index});
    var paras{index}=new ActionList();
    paras{index}.putObject(stringIDToTypeID('paragraphStyleRange'),prange{index});
    text{index}.putList(stringIDToTypeID('paragraphStyleRange'),paras{index});
    mk{index}.putObject(charIDToTypeID('Usng'), stringIDToTypeID('textLayer'), text{index});
    executeAction(charIDToTypeID('Mk  '), mk{index}, DialogModes.NO);
    var tl{index} = doc.activeLayer;
    tl{index}.name = '{name}';
    var ti{index} = tl{index}.textItem;
    {tcy_code}
"""
