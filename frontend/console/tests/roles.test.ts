import { describe, expect, it } from 'vitest';
import { hasRole, visibleNav } from '../src/lib/auth/roles';

describe('roles', () => {
	it('ranks admin above reviewer above viewer', () => {
		expect(hasRole(['viewer'], 'reviewer')).toBe(false);
		expect(hasRole(['viewer', 'reviewer'], 'reviewer')).toBe(true);
		expect(hasRole(['admin'], 'reviewer')).toBe(true);
		expect(hasRole(['unknown'], 'viewer')).toBe(false);
	});

	it('shows each role only the areas it may use', () => {
		const labels = (roles: string[]) => visibleNav(roles).map((item) => item.label);
		expect(labels(['viewer'])).toEqual(['Benchmark', 'Ops']);
		expect(labels(['viewer', 'reviewer'])).toEqual(['Review', 'Benchmark', 'Entities', 'Ops', 'Audit']);
		expect(labels(['viewer', 'reviewer', 'admin'])).toEqual([
			'Review',
			'Benchmark',
			'Entities',
			'Settings',
			'Ops',
			'Audit'
		]);
	});
});
