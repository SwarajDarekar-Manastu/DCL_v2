// The Case editor's form state and its mapping to the Benchmark API (CaseSpec, file 08 §5.3).

import type { BenchmarkCase, BenchmarkCaseContent, BenchmarkCategory, CaseSpec, ExpectedBehavior } from '$lib/api_endpoint';
import { splitList } from './links';

export const CATEGORIES: BenchmarkCategory[] = [
	'TELEMETRY_MATH',
	'FACT_LOOKUP',
	'CODE',
	'FAILURE_ANALYSIS',
	'STANDARDS',
	'DESIGN_SYNTHESIS',
	'NAVIGATIONAL',
	'VISUAL',
	'OUT_OF_SCOPE',
	'HALTED_DATA_BEHAVIOR',
	'CONFLICT_BEHAVIOR',
	'MULTILINGUAL',
	'LIBRARY_VS_INTERNAL'
];

export const BEHAVIORS: { value: ExpectedBehavior; label: string }[] = [
	{ value: 'must_clarify', label: 'must ask a clarifying question' },
	{ value: 'must_state_insufficient_evidence', label: 'must state insufficient evidence' },
	{ value: 'must_mention_halted_case', label: 'must mention the halted review case' },
	{ value: 'must_label_external', label: 'must label external sources' },
	{ value: 'must_present_both_conflicting_values', label: 'must present both conflicting values' }
];

export interface NumericRow {
	metric: string;
	value: string;
	unit: string;
	tolerance_pct: string;
}
export interface CitationRow {
	file_name: string;
	doc_id: string;
	standard_id: string;
	page: string;
}
export interface AnchorRow {
	doc_id: string;
	anchor: string;
}

export interface CaseForm {
	suite: string;
	category: BenchmarkCategory;
	question: string;
	difficulty: string;
	notes: string;
	language: string;
	paraphrases: string; // one per line
	numeric: NumericRow[];
	citations: CitationRow[];
	mustNotCite: CitationRow[];
	tools: string; // comma list
	toolsOrdered: boolean;
	entities: string; // comma list
	anchors: AnchorRow[];
	behaviors: ExpectedBehavior[];
	clarification: string;
}

export const emptyNumeric = (): NumericRow => ({ metric: '', value: '', unit: '', tolerance_pct: '1' });
export const emptyCitation = (): CitationRow => ({ file_name: '', doc_id: '', standard_id: '', page: '' });
export const emptyAnchor = (): AnchorRow => ({ doc_id: '', anchor: '' });

export function emptyForm(suite = ''): CaseForm {
	return {
		suite,
		category: 'FACT_LOOKUP',
		question: '',
		difficulty: '',
		notes: '',
		language: 'en',
		paraphrases: '',
		numeric: [],
		citations: [],
		mustNotCite: [],
		tools: '',
		toolsOrdered: false,
		entities: '',
		anchors: [],
		behaviors: [],
		clarification: ''
	};
}

const str = (v: unknown) => (v === null || v === undefined ? '' : String(v));
const citationRow = (c: CaseSpec['expected_citations'][number]): CitationRow => ({
	file_name: str(c.file_name),
	doc_id: str(c.doc_id),
	standard_id: str(c.standard_id),
	page: str(c.page)
});

export function formFromCase(c: BenchmarkCase): CaseForm {
	const spec = c.spec;
	return {
		suite: c.suite,
		category: c.category,
		question: c.question,
		difficulty: str(c.difficulty),
		notes: str(c.notes),
		language: spec.language ?? 'en',
		paraphrases: (spec.paraphrases ?? []).join('\n'),
		numeric: (spec.expected_numeric ?? []).map((n) => ({
			metric: n.metric,
			value: String(n.value),
			unit: n.unit,
			tolerance_pct: String(n.tolerance_pct ?? 1)
		})),
		citations: (spec.expected_citations ?? []).map(citationRow),
		mustNotCite: (spec.must_not_cite ?? []).map(citationRow),
		tools: (spec.expected_tools?.tools ?? []).join(', '),
		toolsOrdered: spec.expected_tools?.ordered ?? false,
		entities: (spec.expected_entities ?? []).join(', '),
		anchors: (spec.retrieval_gold_anchors ?? []).map((a) => ({ doc_id: a.doc_id, anchor: a.anchor })),
		behaviors: [...(spec.expected_behavior ?? [])],
		clarification: str(spec.clarification_answer)
	};
}

const orNull = (v: string) => (v.trim() ? v.trim() : null);

function citation(row: CitationRow) {
	return {
		file_name: orNull(row.file_name),
		doc_id: orNull(row.doc_id),
		standard_id: orNull(row.standard_id),
		page: row.page.trim() ? Number(row.page) : null
	};
}

const blankCitation = (r: CitationRow) => !r.file_name.trim() && !r.doc_id.trim() && !r.standard_id.trim() && !r.page.trim();

/** What must be fixed before saving, or [] when the form maps to a valid request. */
export function problems(form: CaseForm): string[] {
	const out: string[] = [];
	if (!form.suite.trim()) out.push('suite is required');
	if (!form.question.trim()) out.push('question is required');
	if (form.difficulty && !/^[1-5]$/.test(form.difficulty)) out.push('difficulty must be 1 to 5');
	form.numeric.forEach((n, i) => {
		if (!n.metric.trim() || !n.unit.trim()) out.push(`expected number ${i + 1} needs a metric and a unit`);
		if (n.value.trim() === '' || Number.isNaN(Number(n.value))) out.push(`expected number ${i + 1} needs a numeric value`);
		if (Number.isNaN(Number(n.tolerance_pct)) || Number(n.tolerance_pct) < 0) out.push(`expected number ${i + 1} needs a tolerance ≥ 0`);
	});
	for (const [name, rows] of [
		['expected citation', form.citations],
		['forbidden citation', form.mustNotCite]
	] as const) {
		rows.forEach((r, i) => {
			if (blankCitation(r)) return;
			if (!r.file_name.trim() && !r.doc_id.trim() && !r.standard_id.trim()) out.push(`${name} ${i + 1} needs a file name, doc id or standard id`);
			if (r.page.trim() && !/^[1-9][0-9]*$/.test(r.page.trim())) out.push(`${name} ${i + 1} has an invalid page`);
		});
	}
	form.anchors.forEach((a, i) => {
		if (!a.doc_id.trim() && !a.anchor.trim()) return;
		if (!a.doc_id.trim() || !a.anchor.trim()) out.push(`gold passage ${i + 1} needs a doc id and an anchor`);
		else if (!/^(page|line|t|cells):/.test(a.anchor.trim())) out.push(`gold passage ${i + 1}: anchor must start with page:, line:, t: or cells:`);
	});
	return out;
}

/** Form → request body (the server validates again, including anchors). */
export function toContent(form: CaseForm): BenchmarkCaseContent {
	const tools = splitList(form.tools);
	return {
		suite: form.suite.trim(),
		category: form.category,
		question: form.question.trim(),
		difficulty: form.difficulty ? Number(form.difficulty) : null,
		notes: orNull(form.notes),
		spec: {
			language: form.language.trim() || 'en',
			paraphrases: form.paraphrases
				.split('\n')
				.map((p) => p.trim())
				.filter(Boolean),
			expected_numeric: form.numeric.map((n) => ({
				metric: n.metric.trim(),
				value: Number(n.value),
				unit: n.unit.trim(),
				tolerance_pct: Number(n.tolerance_pct || 0)
			})),
			expected_citations: form.citations.filter((r) => !blankCitation(r)).map(citation),
			must_not_cite: form.mustNotCite.filter((r) => !blankCitation(r)).map(citation),
			expected_tools: tools.length ? { tools, ordered: form.toolsOrdered } : null,
			expected_entities: splitList(form.entities),
			retrieval_gold_anchors: form.anchors
				.filter((a) => a.doc_id.trim() && a.anchor.trim())
				.map((a) => ({ doc_id: a.doc_id.trim(), anchor: a.anchor.trim() })),
			expected_behavior: form.behaviors,
			clarification_answer: orNull(form.clarification)
		}
	};
}
