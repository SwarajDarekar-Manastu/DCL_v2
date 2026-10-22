// Color theme: system preference by default, manual override persisted in localStorage ("dcl-theme").
// app.html applies the same rule inline before first paint, so there is no flash; this module keeps
// the <html class="dark"> in sync afterwards and exposes the toggle.

export type ThemePreference = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

export const THEME_STORAGE_KEY = 'dcl-theme';
const QUERY = '(prefers-color-scheme: dark)';

export function readPreference(storage: Pick<Storage, 'getItem'> | null): ThemePreference {
	try {
		const value = storage?.getItem(THEME_STORAGE_KEY);
		return value === 'light' || value === 'dark' ? value : 'system';
	} catch {
		return 'system';
	}
}

export function resolveTheme(preference: ThemePreference, systemDark: boolean): ResolvedTheme {
	if (preference === 'system') return systemDark ? 'dark' : 'light';
	return preference;
}

export function applyTheme(root: Element, resolved: ResolvedTheme): void {
	root.classList.toggle('dark', resolved === 'dark');
}

class ThemeState {
	preference = $state<ThemePreference>('system');
	systemDark = $state(false);
	resolved = $derived(resolveTheme(this.preference, this.systemDark));
}

export const theme = new ThemeState();

export function setPreference(preference: ThemePreference): void {
	theme.preference = preference;
	try {
		if (preference === 'system') localStorage.removeItem(THEME_STORAGE_KEY);
		else localStorage.setItem(THEME_STORAGE_KEY, preference);
	} catch {
		/* storage unavailable: the choice lasts for this page */
	}
}

/** Reads the stored preference, follows the system setting, and mirrors the result onto <html>. */
export function startTheme(): () => void {
	theme.preference = readPreference(typeof localStorage === 'undefined' ? null : localStorage);
	const media = window.matchMedia(QUERY);
	theme.systemDark = media.matches;
	const onChange = (event: MediaQueryListEvent) => (theme.systemDark = event.matches);
	media.addEventListener('change', onChange);
	const stop = $effect.root(() => {
		$effect(() => applyTheme(document.documentElement, theme.resolved));
	});
	return () => {
		media.removeEventListener('change', onChange);
		stop();
	};
}
