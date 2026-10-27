// The page check's logic (PageCheck.svelte): the state of each unsure entry from its draft answer, the spans of
// a table grid, and text split around crossed-out parts.

import type { PageEntry, PageReading, Resolution } from '$lib/api_endpoint';

export type EntryState = 'to check' | 'confirmed' | 'corrected' | 'unreadable';

export const STATE_MARK: Record<EntryState, string> = { 'to check': '○', confirmed: '✓', corrected: '✎', unreadable: '✗' };

/** An entry is to check until it has an answer; keeping the reader's value is "confirmed". */
export function entryState(entry: Pick<PageEntry, 'value'>, draft: Resolution | null | undefined): EntryState {
	if (!draft || draft.action !== 'set_value') return 'to check';
	if (draft.illegible) return 'unreadable';
	return (draft.value ?? '') === (entry.value ?? '') ? 'confirmed' : 'corrected';
}

type Cell = PageReading['blocks'][number]['parts'][number] extends { rows?: (infer R)[][] | null } ? R : never;

/** rowspan and colspan of each origin cell, from the positions that point at it ("r:c" keys). */
export function spans(rows: Cell[][]): Map<string, { rowspan: number; colspan: number }> {
	const out = new Map<string, { rowspan: number; colspan: number }>();
	rows.forEach((row, r) =>
		row.forEach((cell, c) => {
			if (cell.span_of) return;
			let colspan = 1;
			while (row[c + colspan]?.span_of?.[0] === r && row[c + colspan]?.span_of?.[1] === c) colspan += 1;
			let rowspan = 1;
			while (rows[r + rowspan]?.[c]?.span_of?.[0] === r && rows[r + rowspan]?.[c]?.span_of?.[1] === c) rowspan += 1;
			out.set(`${r}:${c}`, { rowspan, colspan });
		})
	);
	return out;
}

/** The text in order, each piece marked when it was crossed out on the page. */
export function segments(text: string, struck: readonly string[]): { text: string; struck: boolean }[] {
	const out: { text: string; struck: boolean }[] = [];
	let rest = text;
	for (const piece of struck) {
		const at = rest.indexOf(piece);
		if (at < 0) continue;
		if (at > 0) out.push({ text: rest.slice(0, at), struck: false });
		out.push({ text: piece, struck: true });
		rest = rest.slice(at + piece.length);
	}
	if (rest) out.push({ text: rest, struck: false });
	return out;
}

/** "table:block:t:r:c" for an entry in a cell, "text:block" for one in text. */
export function placeKey(place: PageEntry['located']): string | null {
	if (!place) return null;
	return place.cell && place.table !== null && place.table !== undefined
		? `table:${place.block_key}:${place.table}:${place.cell[0]}:${place.cell[1]}`
		: `text:${place.block_key}`;
}
