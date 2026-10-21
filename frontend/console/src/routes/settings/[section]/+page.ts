import { error } from '@sveltejs/kit';
import { findSection } from '$lib/components/settings/sections';

export function load({ params }: { params: { section: string } }) {
	const section = findSection(params.section);
	if (!section) error(404, `No settings section "${params.section}"`);
	return { section };
}
