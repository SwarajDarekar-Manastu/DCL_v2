import type { CaseLocation } from '$lib/api_endpoint';

export interface LocationLink {
	url: string;
	/** The folder under its root, whole, because copies often differ in one folder high up (Test Plan 10 / 11 / 12). */
	folder: string;
	file: string;
}

export interface LocationGroups {
	primary: LocationLink | null;
	others: LocationLink[];
}

/** The parent folder without the root's own name, which every copy shares. */
const folderOf = (path: string, root: string) => {
	const parts = path.split('/').slice(0, -1);
	return (parts[0] === root ? parts.slice(1) : parts).join('/');
};

/** One link per distinct OneDrive address, the first as the main link, the rest as "other copies". */
export function groupLocations(locations: CaseLocation[]): LocationGroups {
	const seen = new Set<string>();
	const links: LocationLink[] = [];
	for (const location of locations) {
		if (!location.web_url || seen.has(location.web_url)) continue;
		seen.add(location.web_url);
		links.push({
			url: location.web_url,
			folder: folderOf(location.path, location.root_name) || location.root_name,
			file: location.file_name
		});
	}
	return { primary: links[0] ?? null, others: links.slice(1) };
}
