"use strict";
/**
 * repairs.js: counts what BPMNGen's XML cleanup changed in a model (fix D2, 19 Oct 2026).
 *
 * BPMNGen's cleanup may add or remove elements (e.g. sequence flows; see docs/BPMNGEN_ANALYSIS.md). Its code is
 * not read here: the effect is measured from outside by counting BPMN elements in the RAW model output
 * (raw_model_output.txt) and in the FINAL model (generated.bpmn). Any element type whose count differs was
 * changed by the cleanup. Used by run_bpmngen.ts (meta.json -> repair_counts); plain JavaScript, so it can be
 * tested with Node alone (tests/test_bpmngen_repairs.py).
 *
 * Counted: every *task (task, userTask, serviceTask, ...) as "task", plus the element types in TYPES. Only opening
 * tags are counted, with or without a namespace prefix (bpmn:task, task). The raw output may not be valid XML;
 * counting by tag name still works.
 */

const TYPES = ["startEvent", "endEvent", "intermediateThrowEvent", "intermediateCatchEvent", "boundaryEvent",
    "exclusiveGateway", "parallelGateway", "inclusiveGateway", "eventBasedGateway", "complexGateway",
    "sequenceFlow", "messageFlow", "participant", "lane", "subProcess"];

function countElements(xml) {
    const counts = { task: 0 };
    for (const type of TYPES) counts[type] = 0;
    const openingTag = /<(?:[A-Za-z_][\w.-]*:)?([A-Za-z_][\w.-]*)(?=[\s/>])/g;
    let match;
    while ((match = openingTag.exec(xml || "")) !== null) {
        const name = match[1];
        if (/task$/i.test(name)) counts.task++;
        else if (Object.prototype.hasOwnProperty.call(counts, name)) counts[name]++;
    }
    return counts;
}

/**
 * raw: the model's raw answer; cleaned: BPMNGen's cleaned output; finalXml: the final BPMN, or null when there is
 * no model (cut-off answer). Returns the counts before/after, the changed types and their total change.
 */
function countRepairs(raw, cleaned, finalXml) {
    const before = countElements(raw);
    const after = finalXml === null || finalXml === undefined ? null : countElements(finalXml);
    const changed = after ? Object.keys(before).filter((k) => before[k] !== after[k]) : null;
    return {
        elements_raw: before,
        elements_final: after,
        changed_element_types: changed,
        n_element_changes: after ? changed.reduce((sum, k) => sum + Math.abs(before[k] - after[k]), 0) : null,
        boundary_events_in_raw: before.boundaryEvent,
        boundary_events_in_final: after ? after.boundaryEvent : null,
        raw_equals_cleaned: cleaned === null || cleaned === undefined ? null : (raw || "") === cleaned,
    };
}

module.exports = { TYPES, countElements, countRepairs };
