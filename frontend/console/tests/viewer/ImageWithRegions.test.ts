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
