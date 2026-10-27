import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import type { Evidence } from '../../src/lib/api_endpoint';
import EvidencePane from '../../src/lib/components/review/EvidencePane.svelte';
import { around, cellDiff, fmtBytes, tableCells } from '../../src/lib/components/review/evidence';

vi.mock('../../src/lib/api_endpoint', async (importOriginal) => {
	const real = await importOriginal<typeof import('../../src/lib/api_endpoint')>();
	return { ...real, presignAsset: vi.fn(async (uri: string) => ({ url: `https://minio.example/${uri.slice(5)}`, expires_in_s: 900 })) };
});

const show = (evidence: Evidence, onPickUnit?: (u: string, g: string) => void) => render(EvidencePane, { evidence, suggestion: null, onPickUnit });

describe('evidence helpers', () => {
	it('reads table HTML as text only and marks differing cells', () => {
		const a = tableCells('<table><tr><th>p</th><th>bar</th></tr><tr><td>12.4</td><td><script>x()</script>ok</td></tr></table>');
		const b = tableCells('<table><tr><th>p</th><th>bar</th></tr><tr><td>12.9</td></tr></table>');
		expect(a).toEqual([['p', 'bar'], ['12.4', 'x()ok']]);
		expect([...cellDiff(a, b)].sort()).toEqual(['1:0', '1:1']);
		expect(tableCells(null)).toEqual([]);
	});

	it('formats sizes and finds the value in its context', () => {
		expect([fmtBytes(512), fmtBytes(5 * 1024 ** 3), fmtBytes(null)]).toEqual(['512 B', '5.0 GB', '—']);
		expect(around('Chamber pressure 12.4 at t0', '12.4')).toEqual({ before: 'Chamber pressure ', match: '12.4', after: ' at t0' });
		expect(around('nothing here', '7')).toBeNull();
	});
});

describe('EvidencePane, remaining kinds', () => {
	it('low_confidence: readings with confidence, zoom, and two table readings with the difference marked', async () => {
		show({
			kind: 'low_confidence',
			crops: [{ crop_uri: 's3://dcl-assets/c1.png', model_value: '7.5', alternatives: ['7.6', '1.5'], confidence: 0.42, printed_label: 'Tank P (barg)' }],
			table_a_html: '<table><tr><td>T4</td><td>13.5</td></tr></table>',
			table_b_html: '<table><tr><td>T4</td><td>15.5</td></tr></table>'
		});
		const readings = screen.getByRole('list', { name: 'Uncertain readings' });
		expect(readings.textContent).toContain('7.5');
		expect(readings.textContent).toContain('confidence 42%');
		expect(readings.textContent).toContain('Also possible: 7.6, 1.5');
		await fireEvent.click(screen.getByRole('button', { name: 'Zoom crop 1: Tank P (barg)' }));
		expect(screen.getByRole('dialog', { name: 'Zoomed image' })).toBeTruthy();
		const marked = within(screen.getByRole('table', { name: 'Table reading B' })).getByText('15.5');
		expect(marked.getAttribute('data-diff')).toBe('true');
		expect(screen.getByText('1 cell differs between the two readings.')).toBeTruthy();
	});

	it('low_confidence: OCR readings per crop and the page OCR text behind a toggle', async () => {
		show({
			kind: 'low_confidence',
			crops: [{ crop_uri: 's3://dcl-assets/c1.png', model_value: '7.5', alternatives: [], confidence: 0.42, printed_label: null, ocr_text: '7,5' }],
			table_a_html: null,
			table_b_html: null,
			page_ocr_text: 'Test 4  Tank P (barg)  7,5'
		});
		expect(screen.getByText('7,5')).toBeTruthy();
		expect(screen.queryByLabelText('Page OCR text')).toBeNull();
		await fireEvent.click(screen.getByRole('button', { name: 'Show page OCR text' }));
		expect(screen.getByLabelText('Page OCR text').textContent).toBe('Test 4  Tank P (barg)  7,5');
	});

	it('unit_fact: the value marked in its context and pickable units', async () => {
		const pick = vi.fn();
		show(
			{
				kind: 'unit_fact',
				value_raw: '12.4',
				context: 'Peak chamber pressure 12.4 during T4',
				candidate_units: [{ unit: 'bar', gauge_or_abs: 'gauge', score: 0.8, reason: 'test plan states barg' }]
			},
			pick
		);
		expect(screen.getByText('12.4', { selector: 'mark' })).toBeTruthy();
		await fireEvent.click(screen.getByRole('button', { name: 'bar (gauge)' }));
		expect(pick).toHaveBeenCalledWith('bar', 'gauge');
	});

	it('json_schema, file_facts and sensitive show their facts, never a secret', () => {
		show({ kind: 'json_schema', top_level_keys: ['meta', 'sections'], flattened_sample: ['meta.title=TR37'], closest_schema: 'test_report.v2', missing_keys: ['results'] });
		expect(screen.getByText('test_report.v2')).toBeTruthy();
		expect(screen.getByText('results').className).toContain('text-hard');
		document.body.innerHTML = '';
		show({ kind: 'file_facts', size_bytes: 5 * 1024 ** 3, extension: '.mp4', folder: 'TP01/Front camera', note: 'over the download cap' });
		expect(screen.getByText('5.0 GB')).toBeTruthy();
		expect(screen.getByText('over the download cap')).toBeTruthy();
		document.body.innerHTML = '';
		show({ kind: 'sensitive', pattern: 'aws_access_key', redacted_preview: 'key = AKIA************', line: 12, page: null });
		expect(screen.getByText(/on line 12/).textContent).toContain('aws_access_key');
		expect(screen.getByText('key = AKIA************')).toBeTruthy();
	});
});
