import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import ImageWithRegions from '../../src/lib/components/viewer/ImageWithRegions.svelte';

describe('ImageWithRegions', () => {
	it('positions regions as percentages of the image, so they scale with it', () => {
		render(ImageWithRegions, {
			src: 'u',
			alt: 'page',
			width: 1000,
			height: 2000,
			regions: [{ bbox: [0.1, 0.25, 0.6, 0.3], kind: 'cited', label: 'x', confidence: null }]
		});
		const { left, top, width, height } = screen.getByTestId('region').style;
		expect({ left, top, width, height }).toEqual({ left: '10%', top: '25%', width: '50%', height: '5%' });
	});
});

describe('ImageWithRegions keyboard access', () => {
	it('lets keyboard users reach every region by Tab, named by kind and label', () => {
		render(ImageWithRegions, {
			src: 'p.png',
			alt: 'page 3',
			width: 1000,
			height: 1400,
			regions: [
				{ bbox: [0.1, 0.1, 0.5, 0.2], kind: 'cited', label: 'Table 4', confidence: null },
				{ bbox: [0.1, 0.5, 0.5, 0.6], kind: 'flag', label: 'operator note', confidence: 0.82 }
			]
		});
		const regions = screen.getAllByRole('button');
		expect(regions.map((r) => r.getAttribute('aria-label'))).toEqual([
			'cited region: Table 4',
			'flag region: operator note (confidence 0.82)'
		]);
		regions[1].focus();
		expect(document.activeElement).toBe(regions[1]);
		expect(regions.every((r) => r.tabIndex === 0)).toBe(true);
	});
});

describe('ImageWithRegions without recorded dimensions', () => {
	it('takes the image size and still places regions by percentage', () => {
		const { container } = render(ImageWithRegions, {
			src: 'p.png',
			alt: 'page 3',
			width: null,
			height: null,
			regions: [{ bbox: [0.1, 0.2, 0.5, 0.4], kind: 'cited', label: 'x', confidence: null }]
		});
		const img = screen.getByRole('img');
		expect(img.hasAttribute('width')).toBe(false);
		expect((container.firstElementChild as HTMLElement).getAttribute('style') ?? '').not.toContain('aspect-ratio');
		const { left, top, width, height } = screen.getByTestId('region').style;
		expect([left, top, width, height]).toEqual(['10%', '20%', '40%', '20%']);
	});
});
