<script lang="ts">
	import type { CaseFilters } from '$lib/api_endpoint';

	interface Props {
		filters: CaseFilters;
		onChange: (filters: CaseFilters) => void;
	}

	let { filters, onChange }: Props = $props();

	const FLAG_TYPES = [
		'UNIT_AMBIGUITY',
		'SCHEMA_UNKNOWN',
		'LOW_CONFIDENCE_EXTRACTION',
		'PARSE_FAILURE',
		'UNSUPPORTED_FORMAT',
		'CONFLICT',
		'SENSITIVE_CONTENT',
		'HELD_LARGE_FILE',
		'CLOUD_RESTRICTED'
	] as const;
	const ROUTES = ['A1', 'A2', 'B', 'C', 'D', 'E', 'F', 'G'] as const;
	const STATUSES = ['OPEN', 'IN_PROGRESS', 'REOPENED', 'RESOLVED', 'REJECTED_FILE'] as const;

	function set<K extends keyof CaseFilters>(key: K, value: CaseFilters[K] | '') {
		const next = { ...filters, [key]: value === '' ? undefined : value };
		onChange(next);
	}
	const text = (e: Event) => (e.currentTarget as HTMLInputElement | HTMLSelectElement).value;
</script>

<form class="filters" aria-label="Queue filters" onsubmit={(e) => e.preventDefault()}>
	<label
		>Severity
		<select value={filters.severity ?? ''} onchange={(e) => set('severity', text(e) as CaseFilters['severity'])}>
			<option value="">any</option>
			<option value="HARD">HARD</option>
			<option value="SOFT">SOFT</option>
		</select>
	</label>
	<label
		>Flag type
		<select value={filters.flag_type ?? ''} onchange={(e) => set('flag_type', text(e) as CaseFilters['flag_type'])}>
			<option value="">any</option>
			{#each FLAG_TYPES as t (t)}<option value={t}>{t}</option>{/each}
		</select>
	</label>
	<label
		>Route
		<select value={filters.route ?? ''} onchange={(e) => set('route', text(e) as CaseFilters['route'])}>
			<option value="">any</option>
			{#each ROUTES as r (r)}<option value={r}>{r}</option>{/each}
		</select>
	</label>
	<label
		>Status
		<select value={filters.status ?? ''} onchange={(e) => set('status', text(e) as CaseFilters['status'])}>
			<option value="">open</option>
			{#each STATUSES as s (s)}<option value={s}>{s}</option>{/each}
		</select>
	</label>
	<label>Root <input value={filters.root_name ?? ''} onchange={(e) => set('root_name', text(e))} /></label>
	<label>Test plan <input value={filters.test_plan_id ?? ''} onchange={(e) => set('test_plan_id', text(e))} /></label>
	<label>Assignee <input value={filters.assignee ?? ''} onchange={(e) => set('assignee', text(e))} /></label>
	<label class="check"
		><input
			type="checkbox"
			checked={filters.has_suggestion === true}
			onchange={(e) => set('has_suggestion', (e.currentTarget as HTMLInputElement).checked ? true : undefined)}
		/> Has suggestion</label
	>
	<label
		>Sort
		<select value={filters.sort ?? 'impact'} onchange={(e) => set('sort', text(e) as CaseFilters['sort'])}>
			<option value="impact">impact</option>
			<option value="age">age</option>
			<option value="severity">severity</option>
		</select>
	</label>
</form>

<style>
	.filters {
		display: grid;
		gap: 0.4rem;
		font-size: 0.8rem;
	}
	label {
		display: grid;
		gap: 0.15rem;
	}
	.check {
		display: flex;
		align-items: center;
		gap: 0.35rem;
	}
	select,
	input:not([type='checkbox']) {
		font: inherit;
		padding: 0.2rem 0.3rem;
		background: var(--surface);
		color: inherit;
		border: 1px solid var(--border);
		border-radius: 0.25rem;
	}
</style>
