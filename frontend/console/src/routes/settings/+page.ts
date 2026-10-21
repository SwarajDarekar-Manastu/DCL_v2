import { redirect } from '@sveltejs/kit';
import { SETTINGS_SECTIONS } from '$lib/components/settings/sections';

export function load() {
	redirect(307, `/settings/${SETTINGS_SECTIONS[0].id}`);
}
