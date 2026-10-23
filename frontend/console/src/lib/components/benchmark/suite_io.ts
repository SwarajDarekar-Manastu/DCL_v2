// Suite import and clone (file 08 §5.5 Suites: "import/export JSON; clone"). Files are the SuiteExport format of
// GET /benchmark/suites/{suite}/export; the API validates every case again on import.

import type { BenchmarkCaseCreate, SuiteExport } from '$lib/api_endpoint';

/** Never used for tuning by any session; scored only in the M10 report (DECISIONS 2026-10-22). */
export const HOLD_OUT_CASES: readonly string[] = ['tp07-t01-throughput-valve-open', 'tp07-t01-t3-soak-20s', 'inj14-t03-fail-mfm-pressure-mean'];

const CASE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/;

export type Parsed<T> = { ok: true; value: T } | { ok: false; error: string };

/** A suite file as exported by the Console API, checked enough to say what it would import. */
export function parseSuiteFile(text: string): Parsed<SuiteExport> {
	let data: unknown;
	try {
		data = JSON.parse(text);
	} catch {
		return { ok: false, error: 'not a JSON file' };
	}
	const file = data as Partial<SuiteExport>;
	if (typeof file?.suite !== 'string' || !file.suite.trim()) return { ok: false, error: 'no suite name ("suite")' };
	if (!Array.isArray(file.cases)) return { ok: false, error: 'no case list ("cases")' };
	const bad = file.cases.find((c) => typeof c?.case_id !== 'string' || c.suite !== file.suite);
	if (bad) return { ok: false, error: `case ${String(bad?.case_id ?? '?')} is not a case of suite ${file.suite}` };
	return { ok: true, value: file as SuiteExport };
}

export interface ClonePlan {
	cases: BenchmarkCaseCreate[];
	skipped: { retired: string[]; holdOut: string[]; idTooLong: string[] };
}

export const cloneId = (suite: string, caseId: string) => `${suite.trim().toLowerCase().replace(/[^a-z0-9._-]+/g, '-')}.${caseId}`;

/** The cases of a suite copied into a new suite under new ids; retired and hold-out cases are not copied. */
export function clonePlan(source: SuiteExport, newSuite: string): ClonePlan {
	const plan: ClonePlan = { cases: [], skipped: { retired: [], holdOut: [], idTooLong: [] } };
	for (const c of source.cases) {
		if (c.status === 'retired') plan.skipped.retired.push(c.case_id);
		else if (HOLD_OUT_CASES.includes(c.case_id)) plan.skipped.holdOut.push(c.case_id);
		else {
			const id = cloneId(newSuite, c.case_id);
			if (!CASE_ID.test(id)) plan.skipped.idTooLong.push(c.case_id);
			else plan.cases.push({ ...c, case_id: id, suite: newSuite.trim() });
		}
	}
	return plan;
}
