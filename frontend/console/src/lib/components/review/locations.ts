import type { CaseLocation } from '$lib/api_endpoint';

export interface LocationLink {
	url: string;
	/** Parent folder shown to tell copies apart. */
	folder: string;
	file: string;
}

export interface LocationGroups {
	primary: LocationLink | null;
	others: LocationLink[];
}

const parentOf = (path: string) => path.split('/').slice(0, -1).join('/');

/** One link per distinct OneDrive address, the first as the main link, the rest as "other copies". */
export function groupLocations(locations: CaseLocation[]): LocationGroups {
	const seen = new Set<string>();
	const links: LocationLink[] = [];
	for (const location of locations) {
		if (!location.web_url || seen.has(location.web_url)) continue;
		seen.add(location.web_url);
		links.push({
			url: location.web_url,
			folder: parentOf(location.path) || location.root_name,
			file: location.file_name
		});
	}
	return { primary: links[0] ?? null, others: links.slice(1) };
}

/** Last two folder names, enough to tell copies apart in a narrow list. */
export function shortFolder(folder: string): string {
	return folder.split('/').slice(-2).join(' / ');
}
