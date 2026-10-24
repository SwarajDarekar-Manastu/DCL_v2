import { describe, expect, it } from 'vitest';
import type { RuleCreated, RulePreview, RuleSimulation } from '../../src/lib/api_endpoint';
import {
	deactivatedLine,
	deactivateLabel,
	deactivateTitle,
	EFFECT_NOTICE,
	previewLine,
	savedLine,
	simulationLine,
	usageLine
} from '../../src/lib/components/review/rule_effect';

const preview = (over: Partial<RulePreview> = {}): RulePreview => ({
	matched_documents: 14,
	waiting_documents: 3,
	finished_documents: 11,
	sample: [],
	effect: 'resolves',
	resolves_flags: 9,
	open_channels: [],
	problem: null,
	...over
});
const created = (over: Partial<RuleCreated> = {}) => ({ proposed_files: 0, resolved_flags: 0, rebuilt_doc_ids: [], ...over }) as RuleCreated;

describe('previewLine', () => {
	it('says how many open flags a resolving rule would answer, among how many files', () => {
		expect(previewLine(preview())).toBe('9 open flags would be answered, among 14 matching files.');
		expect(previewLine(preview({ resolves_flags: 1, matched_documents: 1 }))).toBe('1 open flag would be answered, among 1 matching file.');
	});

	it('says when no open flag matches yet, and that later flags are answered too', () => {
		expect(previewLine(preview({ resolves_flags: 0 }))).toBe('No open flag matches now (14 matching files in scope). A matching flag raised later is answered too.');
	});

	it('says how many files a document rule changes at their rebuild', () => {
		expect(previewLine(preview({ effect: 'applies' }))).toBe('14 matching files would change at the next rebuild, which saving starts.');
		expect(previewLine(preview({ effect: 'applies', matched_documents: 0 }))).toBe('No file matches yet. Files that match later change when they are built.');
	});

	it('says how many waiting files a unit rule would fill in', () => {
		expect(previewLine(preview({ effect: 'proposes' }))).toBe('3 waiting files would show it as a proposal.');
		expect(previewLine(preview({ effect: 'proposes', waiting_documents: 0 }))).toMatch(/^No file is waiting for it now/);
	});

	it('gives the reason first when the server will not take the body, and says nothing acts for a stored kind', () => {
		expect(previewLine(preview({ problem: 'column: Field required' }))).toBe('The server will not accept this rule: column: Field required');
		expect(previewLine(preview({ effect: 'stored' }))).toBe('Nothing reads this kind; no file would change.');
	});
});

describe('after saving', () => {
	it('shows the answered flags and the files rebuilt or resumed for a resolving rule', () => {
		expect(savedLine(created({ resolved_flags: 9, rebuilt_doc_ids: ['a', 'b', 'c'] }), 'resolves')).toBe('Rule saved. It answered 9 open flags; 3 files are being rebuilt or resumed.');
		expect(savedLine(created({ resolved_flags: 1, rebuilt_doc_ids: ['a'] }), 'resolves')).toBe('Rule saved. It answered 1 open flag; 1 file is being rebuilt or resumed.');
		expect(savedLine(created(), 'resolves')).toBe('Rule saved. No open flag matched yet; a matching flag raised later is answered too.');
	});

	it('shows the files rebuilt for a document rule', () => {
		expect(savedLine(created({ rebuilt_doc_ids: ['a', 'b'] }), 'applies')).toBe('Rule saved. 2 files are being rebuilt to apply it.');
		expect(savedLine(created(), 'applies')).toBe('Rule saved. No file matched yet; files that match later change when they are built.');
	});

	it('keeps the proposal wording for a unit rule', () => {
		expect(savedLine(created({ proposed_files: 12 }), 'proposes')).toBe('Rule saved. 12 files now show it as a proposal.');
		expect(savedLine(created({ proposed_files: 1 }), 'proposes')).toBe('Rule saved. 1 file now shows it as a proposal.');
		expect(savedLine(created(), 'proposes')).toBe('Rule saved.');
	});
});

describe('switching a rule off', () => {
	it('names the button and the tooltip by what the rule did', () => {
		expect(deactivateLabel('proposes')).toBe('Stop proposing');
		expect(deactivateLabel('resolves')).toBe('Switch off');
		expect(deactivateLabel('applies')).toBe('Switch off');
		expect(deactivateTitle('resolves')).toBe('Switches the rule off. The flags it answered are open again and those files are rebuilt.');
		expect(deactivateTitle('applies')).toMatch(/rebuilt without it/);
		expect(deactivateTitle('proposes')).toMatch(/never changed/);
		expect(deactivatedLine('resolves')).toMatch(/open again/);
		expect(deactivatedLine('proposes')).toBe('Rule switched off. Approved files are unchanged.');
	});
});

describe('listing', () => {
	it('shows what a saved rule has done, by kind', () => {
		const counts = { flags_resolved: 4, flags_proposed: 12, flags_decided: 3, files_waiting: 9 };
		expect(usageLine(counts, 'resolves')).toBe('4 flags answered');
		expect(usageLine({ ...counts, flags_resolved: 1 }, 'resolves')).toBe('1 flag answered');
		expect(usageLine(counts, 'applies')).toBe('Changes the matching files at their rebuild.');
		expect(usageLine(counts, 'proposes')).toBe('12 proposed · 3 decided · 9 files waiting');
	});

	it('words a simulation by whether the rule acts', () => {
		const sim: RuleSimulation = { matched_documents: 5, waiting_documents: 2, finished_documents: 3, sample: [] };
		expect(simulationLine(sim, 'proposes')).toBe('Reaches 5 files: 2 waiting, 3 already processed (a proposal never changes them).');
		expect(simulationLine(sim, 'resolves')).toBe('Reaches 5 files: 2 waiting, 3 already processed.');
	});

	it('has a notice for every effect, warning for the ones that act', () => {
		expect(EFFECT_NOTICE.resolves.tone).toBe('warning');
		expect(EFFECT_NOTICE.applies.tone).toBe('warning');
		expect(EFFECT_NOTICE.proposes.tone).toBe('info');
		expect(EFFECT_NOTICE.resolves.text).toBe('Saving answers the matching open flags the way you would and rebuilds those files.');
		expect(EFFECT_NOTICE.applies.text).toBe('The matched documents change at their next rebuild, which saving starts.');
	});
});
