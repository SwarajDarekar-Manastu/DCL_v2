// Settings › Prompts (file 08 §3.2 Prompts; S2's prompt registry): prompts stay files in the repository, so this
// screen reads them, compares versions and runs one on a sample; it never edits.

import type { PromptVersion } from '$lib/api_endpoint';

export interface PromptGroup {
	area: string;
	name: string;
	versions: PromptVersion[]; // newest first
}

/** Versions grouped per prompt, areas and names in order, newest version first. */
export function groupPrompts(list: PromptVersion[]): PromptGroup[] {
	const groups = new Map<string, PromptGroup>();
	for (const p of list) {
		const key = `${p.area}/${p.name}`;
		const group = groups.get(key) ?? { area: p.area, name: p.name, versions: [] };
		group.versions.push(p);
		groups.set(key, group);
	}
	for (const g of groups.values()) g.versions.sort((a, b) => b.number - a.number);
	return [...groups.values()].sort((a, b) => a.area.localeCompare(b.area) || a.name.localeCompare(b.name));
}

export interface DiffRow {
	left: string | null;
	right: string | null;
	kind: 'same' | 'changed' | 'removed' | 'added';
}

/** A unified diff as side-by-side rows: removed lines pair with the added lines that follow them. */
export function sideBySide(unified: string): DiffRow[] {
	const rows: DiffRow[] = [];
	let removed: string[] = [];
	let added: string[] = [];
	const flush = () => {
		const n = Math.max(removed.length, added.length);
		for (let i = 0; i < n; i++) {
			const left = removed[i] ?? null;
			const right = added[i] ?? null;
			rows.push({ left, right, kind: left !== null && right !== null ? 'changed' : left !== null ? 'removed' : 'added' });
		}
		removed = [];
		added = [];
	};
	for (const line of unified.split('\n')) {
		if (line.startsWith('---') || line.startsWith('+++') || line.startsWith('@@')) {
			flush();
			continue;
		}
		if (line.startsWith('-')) removed.push(line.slice(1));
		else if (line.startsWith('+')) added.push(line.slice(1));
		else {
			flush();
			if (line.startsWith(' ')) rows.push({ left: line.slice(1), right: line.slice(1), kind: 'same' });
		}
	}
	flush();
	return rows;
}
