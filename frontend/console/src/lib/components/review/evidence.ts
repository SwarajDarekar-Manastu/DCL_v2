// Helpers for the evidence panes (file 08 §4.2 EvidencePane). Table HTML from the pipeline is read for its cell
// text only and never inserted into the page.

/** Cell text of the first table in an HTML string. */
export function tableCells(html: string | null | undefined): string[][] {
	if (!html) return [];
	const doc = new DOMParser().parseFromString(html, 'text/html');
	return [...doc.querySelectorAll('tr')]
		.map((tr) => [...tr.querySelectorAll('th,td')].map((cell) => (cell.textContent ?? '').replace(/\s+/g, ' ').trim()))
		.filter((row) => row.length > 0);
}

/** Cells that differ between two readings of the same table, as "row:col" keys (missing cells differ too). */
export function cellDiff(a: string[][], b: string[][]): Set<string> {
	const out = new Set<string>();
	const rows = Math.max(a.length, b.length);
	for (let r = 0; r < rows; r++) {
		const cols = Math.max(a[r]?.length ?? 0, b[r]?.length ?? 0);
		for (let c = 0; c < cols; c++) if ((a[r]?.[c] ?? null) !== (b[r]?.[c] ?? null)) out.add(`${r}:${c}`);
	}
	return out;
}

export function fmtBytes(n: number | null | undefined): string {
	if (n === null || n === undefined) return '—';
	const units = ['B', 'KB', 'MB', 'GB', 'TB'];
	let value = n;
	let i = 0;
	while (value >= 1024 && i < units.length - 1) {
		value /= 1024;
		i++;
	}
	return `${i === 0 ? value : value.toFixed(1)} ${units[i]}`;
}

/** The context split around the first occurrence of the value, so the pane can mark it. */
export function around(context: string, value: string): { before: string; match: string; after: string } | null {
	const i = value ? context.indexOf(value) : -1;
	return i < 0 ? null : { before: context.slice(0, i), match: value, after: context.slice(i + value.length) };
}
