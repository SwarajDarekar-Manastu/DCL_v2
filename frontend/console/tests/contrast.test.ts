// WCAG AA for the select option lists (and the popover tokens the dropdown menus use), computed from the real
// colour tokens in src/app.css for both themes. jsdom does not apply the stylesheet, so the CSS is read here.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';

const css = readFileSync('src/app.css', 'utf8');

/** Every custom property of every top-level block with this selector (the palette and the semantic layer). */
function block(selector: ':root' | '.dark'): Record<string, string> {
	const out: Record<string, string> = {};
	let at = css.indexOf(`\n${selector} {`);
	while (at >= 0) {
		const body = css.slice(at, css.indexOf('\n}', at));
		for (const m of body.matchAll(/(--[\w-]+):\s*([^;]+);/g)) out[m[1]] = m[2].trim();
		at = css.indexOf(`\n${selector} {`, at + 1);
	}
	return out;
}

/** oklch(L C H) with C = 0 (the grays used here) to relative luminance; L is perceptual lightness. */
function luminance(oklch: string): number {
	const [l, c] = oklch.replace(/oklch\(|\)/g, '').split(/\s+/).map(Number);
	expect(c).toBe(0); // gray tokens only; a chroma would need the full OKLab conversion
	return l ** 3; // OKLab achromatic: linear sRGB = L^3 on every channel, so Y = L^3
}

const contrast = (a: string, b: string) => {
	const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
	return (hi + 0.05) / (lo + 0.05);
};

function token(theme: Record<string, string>, base: Record<string, string>, name: string): string {
	const semantic = base[name];
	const ref = semantic?.match(/var\((--[\w-]+)\)/)?.[1];
	return ref ? (theme[ref] ?? base[ref]) : (theme[name] ?? semantic);
}

describe('select option contrast', () => {
	it('gives options the popover colours, not inherited ones', () => {
		expect(css).toMatch(/select option,\s*select optgroup \{\s*background-color: var\(--popover\);\s*color: var\(--popover-foreground\);/);
		expect(css).toMatch(/select option:checked \{[^}]*color: var\(--popover-foreground\)/);
	});

	for (const name of [':root', '.dark'] as const) {
		it(`meets WCAG AA (4.5:1) for option text in ${name === ':root' ? 'light' : 'dark'} mode`, () => {
			const base = block(':root');
			const theme = block(name);
			const bg = token(theme, base, '--popover');
			const fg = token(theme, base, '--popover-foreground');
			const muted = token(theme, base, '--muted-foreground');
			expect(bg).not.toBe(fg);
			expect(contrast(fg, bg)).toBeGreaterThanOrEqual(4.5);
			expect(contrast(muted, bg)).toBeGreaterThanOrEqual(4.5); // disabled options and placeholders
		});
	}
});
