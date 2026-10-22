import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import FailedTasks from '../../src/lib/components/ops/FailedTasks.svelte';
import type { FailedTask } from '../../src/lib/api_endpoint';

const task: FailedTask = {
	task_id: '4f1c',
	task: 'backend.celery_redis.tasks_process.process_document',
	queue: 'cpu_parse',
	args: "('doc-1',)",
	kwargs: '{}',
	error: 'ValueError: no unit',
	retries: 3,
	at: '2026-10-22T10:15:00Z'
};

describe('FailedTasks', () => {
	it('lists each failed task with its error and stored arguments', () => {
		render(FailedTasks, { items: [task, { ...task, task_id: 'b2', queue: null, error: 'PoisonTask: worker lost 3 times' }] });
		const rows = screen.getAllByRole('row').slice(1).map((r) => r.textContent);
		expect(rows[0]).toContain('2026-10-22 10:15:00');
		expect(rows[0]).toContain('process_document');
		expect(rows[0]).toContain('cpu_parse');
		expect(rows[0]).toContain("('doc-1',)");
		expect(rows[1]).toContain('—');
		expect(rows[1]).toContain('PoisonTask: worker lost 3 times');
	});

	it('says so when nothing failed', () => {
		render(FailedTasks, { items: [] });
		expect(screen.getByText('No failed tasks.')).toBeTruthy();
		expect(screen.queryByRole('table')).toBeNull();
	});
});
