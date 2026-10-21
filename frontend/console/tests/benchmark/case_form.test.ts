import { describe, expect, it } from 'vitest';
import { emptyForm, formFromCase, problems, toContent } from '../../src/lib/components/benchmark/case_form';
import { benchCase } from './fixtures';

describe('case form', () => {
	it('round-trips every CaseSpec field through the form', () => {
		const c = benchCase();
		const content = toContent(formFromCase(c));
		expect(content).toEqual({
			suite: c.suite,
			category: c.category,
			question: c.question,
			difficulty: 2,
			notes: 'Excel-verified',
			spec: c.spec
		});
	});

	it('drops blank rows and empty tool lists', () => {
		const form = emptyForm('telemetry');
		form.question = 'Q?';
		form.citations.push({ file_name: '', doc_id: '', standard_id: '', page: '' });
		form.anchors.push({ doc_id: '', anchor: '' });
		const spec = toContent(form).spec!;
		expect(spec.expected_citations).toEqual([]);
		expect(spec.retrieval_gold_anchors).toEqual([]);
		expect(spec.expected_tools).toBeNull();
		expect(problems(form)).toEqual([]);
	});

	it('names what must be fixed', () => {
		const form = emptyForm('');
		form.difficulty = '7';
		form.numeric.push({ metric: 'p', value: 'abc', unit: '', tolerance_pct: '-1' });
		form.citations.push({ file_name: '', doc_id: '', standard_id: '', page: '3' });
		form.anchors.push({ doc_id: 'd', anchor: 'node:5f0c:' });
		expect(problems(form)).toEqual([
			'suite is required',
			'question is required',
			'difficulty must be 1 to 5',
			'expected number 1 needs a metric and a unit',
			'expected number 1 needs a numeric value',
			'expected number 1 needs a tolerance ≥ 0',
			'expected citation 1 needs a file name, doc id or standard id',
			'gold passage 1: anchor must start with page:, line:, t: or cells:'
		]);
	});
});
